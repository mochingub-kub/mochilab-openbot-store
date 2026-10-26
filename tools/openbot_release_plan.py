#!/usr/bin/env python3
"""Propose a new OpenBot stable release in a Git checkout; NEVER deploy to Umbrel.

Only a draft PR may use the generated image and manifest version edits.
Keep V3 AppArmor/Seccomp immutable, require an unchanged upstream seccomp Git blob.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
IMAGE_FILE = Path("mochilab-openbot/docker-compose.yml")
MANIFEST_FILE = Path("mochilab-openbot/umbrel-app.yml")
UPSTREAM_SC = "6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418"
WORKSPACE_AA = "afd0d87e7a09e39afad12864fb988586ce95104e"
WORKSPACE_SC = "4fa610c6303f4610844dc6ae0da5546030a77cbb"
API = "https://api.github.com/repos/nightly-labs/openbot"
IMAGE = re.compile(r"(?m)^    image: ghcr\.io/nightly-labs/openbot:(\d+\.\d+\.\d+)$")
PACKAGE = re.compile(r'(?m)^version: "(\d+\.\d+\.\d+)-([1-9]\d*)"$')
RELEASE_NOTE = re.compile(r"(?m)^  Update the self-hosted OpenBot engine to (\d+\.\d+\.\d+)\b")
VERSION = re.compile(r"\A(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


class Blocked(Exception):
    pass


def need(ok, reason):
    if not ok:
        raise Blocked(reason)


def one(regex, text, reason):
    values = list(regex.finditer(text))
    need(len(values) == 1, reason)
    return values[0]


def key(v):
    need(VERSION.fullmatch(v) is not None, "INVALID_VERSION")
    return tuple(int(x) for x in v.split("."))


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def current(root=ROOT):
    root = Path(root)
    compose = (root / IMAGE_FILE).read_text(encoding="utf-8")
    manifest = (root / MANIFEST_FILE).read_text(encoding="utf-8")
    version = one(IMAGE, compose, "IMAGE_TAG_NOT_EXACTLY_ONE").group(1)
    package = one(PACKAGE, manifest, "PACKAGE_VERSION_NOT_EXACTLY_ONE")
    note = one(RELEASE_NOTE, manifest, "RELEASE_NOTES_VERSION_MISSING")
    need(version == package.group(1) == note.group(1), "PACKAGE_IMAGE_VERSION_DRIFT")
    key(version)
    # The new package must preserve the *actual* V3 policy and sole app-data bind.
    d = "$" + "{APP_DATA_DIR}"
    for line in ("      - apparmor=mochilab-openbot-workspace\n",
                 "      - seccomp=" + d + "/seccomp-workspace.json\n",
                 "      - no-new-privileges:true\n",
                 "      - " + d + "/data:/data\n"):
        need(line in compose, "V3_CONTAINER_SECURITY_DRIFT")
    need(not any(flag in compose for flag in
                 ("    privileged:", "    cap_add:", "/var/run/docker.sock",
                  "network_mode: host", "      - /:/host")),
         "HOST_ACCESS_EXPANSION")
    for name, sha in (
        ("mochilab-openbot/hooks/mochilab-openbot-workspace.apparmor", WORKSPACE_AA),
        ("mochilab-openbot/hooks/seccomp-workspace.json", WORKSPACE_SC),
    ):
        path = root / name
        need(path.is_file() and not path.is_symlink() and
             blob_sha(path.read_bytes()) == sha, "V3_REVIEWED_ARTIFACT_DRIFT")
    hook = root / "mochilab-openbot/hooks/pre-start"
    need(hook.is_file() and not hook.is_symlink(), "PRE_START_HOOK_MISSING")
    code = hook.read_text(encoding="utf-8")
    for fragment in (UPSTREAM_SC, WORKSPACE_AA, WORKSPACE_SC,
                     'V3_SEC_SOURCE="' + "$" + '{APP_DIR}/hooks/seccomp-workspace.json"',
                     "V3_SEC_TARGET", "apparmor_parser"):
        need(fragment in code, "PRE_START_V3_GUARD_MISSING")
    return version


def github_json(url):
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "mochilab-updater/1.0",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        return json.load(response)


def stable():
    release = github_json(API + "/releases/latest")
    need(isinstance(release, dict) and not release.get("draft") and
         not release.get("prerelease"), "RELEASE_NOT_STABLE")
    tag = release.get("tag_name")
    need(isinstance(tag, str) and tag.startswith("v"), "INVALID_RELEASE_TAG")
    version = tag[1:]
    key(version)
    need(any(isinstance(a, dict) and a.get("name") ==
             "OpenBot-" + version + "-x86_64.AppImage"
             for a in release.get("assets", [])),
         "RELEASE_ASSET_MISSING")
    seccomp = github_json(API + "/contents/docker/seccomp.json?ref=" + tag)
    need(isinstance(seccomp, dict) and seccomp.get("sha") == UPSTREAM_SC,
         "UPSTREAM_SECCOMP_CHANGED_MANUAL_REVIEW_REQUIRED")
    return version


def propose(root, target):
    root = Path(root)
    installed = current(root)
    if key(target) <= key(installed):
        return False
    cpath, mpath = root / IMAGE_FILE, root / MANIFEST_FILE
    compose, manifest = cpath.read_text(), mpath.read_text()
    pkg_rev = one(PACKAGE, manifest, "PACKAGE_REVISION").group(2)
    next_compose = IMAGE.sub("    image: ghcr.io/nightly-labs/openbot:" + target, compose)
    next_manifest = PACKAGE.sub('version: "' + target + '-1"', manifest)
    next_manifest = RELEASE_NOTE.sub(
        "  Update the self-hosted OpenBot engine to " + target, next_manifest)
    need(next_compose != compose and next_manifest != manifest,
         "NO_VERSION_CHANGE")
    # Exactly three version fields may be changed. No security/policy edits.
    need(next_compose.replace("openbot:" + target, "openbot:" + installed) == compose,
         "COMPOSE_PATCH_TOO_BROAD")
    need(next_manifest.replace('version: "' + target + '-1"',
                               'version: "' + installed + '-' + pkg_rev + '"')
         .replace("engine to " + target, "engine to " + installed) == manifest,
         "MANIFEST_PATCH_TOO_BROAD")
    cpath.write_text(next_compose)
    mpath.write_text(next_manifest)
    need(current(root) == target, "UPDATED_REVIEW_CANDIDATE_INVALID")
    return True


def main():
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check-current", action="store_true")
    options.add_argument("--check-latest", action="store_true")
    options.add_argument("--prepare-latest", action="store_true")
    args = parser.parse_args()
    try:
        present = current()
        if args.check_current:
            print("RESULT=UPDATER_V3_PACKAGE_INTEGRITY_PASS")
            print("PINNED_VERSION=" + present)
            return 0
        version = stable()
        print("PINNED_VERSION=" + present)
        print("UPSTREAM_STABLE_VERSION=" + version)
        if args.check_latest:
            print("RESULT=UPDATE_REVIEW_AVAILABLE" if key(version) > key(present)
                  else "RESULT=ALREADY_ON_STABLE")
            return 0
        changed = propose(ROOT, version)
        print("RESULT=REVIEW_CANDIDATE_PREPARED" if changed else "RESULT=ALREADY_ON_STABLE")
        print("REVIEW_TARGET_VERSION=" + version)
        print("UPSTREAM_SECCOMP_BLOB_UNCHANGED=YES")
        print("V3_WORKSPACE_POLICY_CHANGED=NO")
        print("PRODUCTION_UPDATED=NO")
        print("GHCR_IMAGE_AVAILABLE=NOT_VERIFIED_BY_SCRIPT")
        return 0
    except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
        print("BLOCKED=" + (str(error) if isinstance(error, Blocked)
                             else "UPDATER_UNEXPECTED_ERROR"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
