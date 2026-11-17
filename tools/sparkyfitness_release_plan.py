#!/usr/bin/env python3
"""Prepare a local, review-only release using the pinned upstream updater."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = "mochilab-sparkyfitness"
APP_IMAGES = {
    "server": "codewithcj/sparkyfitness_server",
    "frontend": "codewithcj/sparkyfitness",
    "garmin": "codewithcj/sparkyfitness_garmin",
}
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")


def version(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("Expected a stable vX.Y.Z tag")
    return tuple(map(int, match.groups()))


def load_package(folder):
    return tuple(yaml.safe_load((folder / name).read_text()) for name in
                 ("umbrel-app.yml", "docker-compose.yml"))


def validate_update(before, after, release):
    """Allow only version, release notes and three release image pins."""
    old_manifest, old_compose = copy.deepcopy(before)
    manifest, compose = copy.deepcopy(after)
    target = release["tag_name"]
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Draft and prerelease updates are blocked")
    if version(target) <= version(old_manifest["version"]):
        raise ValueError("Same-version repins and downgrades are blocked")
    if manifest["id"] != APP or manifest["version"] != target:
        raise ValueError("Unexpected app ID or release version")
    for field in ("version", "releaseNotes"):
        manifest.pop(field)
        old_manifest.pop(field)
    if manifest != old_manifest:
        raise ValueError("Manifest settings changed outside version and release notes")
    for service, repo in APP_IMAGES.items():
        image = compose["services"][service].pop("image")
        old_compose["services"][service].pop("image")
        if not re.fullmatch(re.escape(repo + ":" + target) + r"@sha256:[0-9a-f]{64}", image):
            raise ValueError("Unexpected runtime image or unpinned digest")
    if compose != old_compose:
        raise ValueError("Infrastructure changed; database, mounts and secrets need separate review")


def latest_release():
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Mochilab-SparkyFitness-review"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        "https://api.github.com/repos/CodeWithCJ/SparkyFitness/releases/latest", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    version(release["tag_name"])
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Expected a published stable release")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-latest", action="store_true",
                        help="Write a local candidate only when a newer stable release exists")
    args = parser.parse_args()
    package = ROOT / APP
    before = load_package(package)
    release = latest_release()
    current = before[0]["version"]
    target = release["tag_name"]
    print(f"CURRENT={current}\nLATEST={target}\nRELEASE={release['html_url']}")
    if version(target) <= version(current):
        print("RESULT=NO_NEW_RELEASE")
        return
    if not args.prepare_latest:
        print("RESULT=REVIEW_AVAILABLE")
        return
    with tempfile.TemporaryDirectory(prefix="sparkyfitness-review-") as temp:
        candidate = Path(temp) / APP
        shutil.copytree(package, candidate)
        subprocess.run([
            "node", str(ROOT / "tools/vendor/sparkyfitness/update-package.mjs"),
            "--version", target, "--no-postgres", "--target", str(candidate),
        ], check=True, timeout=240)
        validate_update(before, load_package(candidate), release)
        for name in ("umbrel-app.yml", "docker-compose.yml"):
            (package / name).write_bytes((candidate / name).read_bytes())
    print(f"REVIEW_TARGET_VERSION={target}\nRESULT=REVIEW_CANDIDATE_PREPARED")


if __name__ == "__main__":
    main()
