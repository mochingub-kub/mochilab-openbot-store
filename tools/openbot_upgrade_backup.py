#!/usr/bin/env python3
"""No-privilege-escalation, stopped-only OpenBot 0.49/V3 pre-upgrade snapshot.

Backup and isolated FILE-level restore rehearsal only. No data is deleted from
the actual app; no Docker/OS changes; no restore to production. Run on the real
UmbrelOS host with sudo only after the owner authorizes a maintenance stop.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

APP = Path("/home/umbrel/umbrel/app-data/mochilab-openbot")
PARENT = Path("/home/umbrel/umbrel/external/mochi-external")
PROJECT = "mochilab-openbot"
SCHEMA = "mochilab-openbot-0.50-preupgrade-file-backup-v1"
PREFIX = ".mochilab-openbot-pre050-"
CONFIG = (
    "docker-compose.yml", "docker-compose.umbreld.yml", "umbrel-app.yml",
    "hooks/pre-start", "hooks/mochilab-openbot.apparmor",
    "hooks/mochilab-openbot-workspace.apparmor", "hooks/openbot-direct.html",
    "seccomp-0.49.0.json", "seccomp-workspace.json", "landing/index.html",
)
V3_AA_HASH = "afd0d87e7a09e39afad12864fb988586ce95104e"
V3_SEC_HASH = "4fa610c6303f4610844dc6ae0da5546030a77cbb"
OLD_SEC_HASH = "6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418"


class Blocked(Exception):
    pass


def block(reason):
    raise Blocked(reason)


def run(args, *, check=True):
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and proc.returncode:
        block("COMMAND_FAILED_" + Path(args[0]).name.upper())
    return proc.stdout.strip()


def sha256(file):
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def git_blob(file):
    raw = file.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def regular(file):
    st = file.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        block("UNSAFE_CONFIG_FILE")
    return st


def require_root():
    if os.geteuid() != 0:
        block("REQUIRES_ROOT_ON_UMBREL_HOST")


def check_app():
    require_root()
    if APP.is_symlink() or not APP.is_dir() or APP.resolve(strict=True) != APP:
        block("APP_ROOT_CHANGED")
    data = APP / "data"
    if data.is_symlink() or not data.is_dir() or data.resolve(strict=True) != data:
        block("DATA_ROOT_CHANGED")
    for rel in CONFIG:
        regular(APP / rel)
    compose = (APP / "docker-compose.yml").read_text(encoding="utf-8")
    manifest = (APP / "umbrel-app.yml").read_text(encoding="utf-8")
    d = "$" + "{APP_DATA_DIR}"
    required = (
        "image: ghcr.io/nightly-labs/openbot:0.49.0",
        "apparmor=mochilab-openbot-workspace",
        "seccomp=" + d + "/seccomp-workspace.json",
        d + "/data:/data",
        "no-new-privileges:true",
    )
    if not all(line in compose for line in required):
        block("EXPECTED_049_V3_COMPOSE_NOT_FOUND")
    if 'version: "0.49.0-3"' not in manifest:
        block("EXPECTED_049_UMBREL_PACKAGE_NOT_FOUND")
    if any(a in compose for a in ("privileged: true", "cap_add:", "/var/run/docker.sock",
                                   "network_mode: host")):
        block("CONFIG_PRIVILEGE_DRIFT")
    for rel, expected in (
        ("hooks/mochilab-openbot-workspace.apparmor", V3_AA_HASH),
        ("seccomp-workspace.json", V3_SEC_HASH),
        ("seccomp-0.49.0.json", OLD_SEC_HASH),
    ):
        if git_blob(APP / rel) != expected:
            block("SECURITY_POLICY_HASH_DRIFT")
    return {rel: sha256(APP / rel) for rel in CONFIG}


def check_stopped():
    ids = run(["docker", "ps", "-aq", "--filter",
               "label=com.docker.compose.project=" + PROJECT])
    if ids:
        block("OPENBOT_CONTAINERS_STILL_PRESENT")
    named = run(["docker", "inspect", "--format", "{{.Id}}",
                 "mochilab-openbot_openbot_1"], check=False)
    if named:
        block("OPENBOT_NAMED_CONTAINER_PRESENT")


def independent_disk():
    if not PARENT.is_dir() or PARENT.is_symlink() or PARENT.resolve(strict=True) != PARENT:
        block("BACKUP_PARENT_UNSAFE")
    target = run(["findmnt", "-T", str(PARENT), "-no", "TARGET"])
    if target != str(PARENT):
        block("BACKUP_HDD_MOUNT_ROOT_MISSING")
    fstype = run(["findmnt", "-T", str(PARENT), "-no", "FSTYPE"])
    if fstype not in ("ext4", "xfs", "btrfs"):
        block("BACKUP_FILESYSTEM_UNEXPECTED")
    if "rw" not in run(["findmnt", "-T", str(PARENT), "-no", "OPTIONS"]).split(","):
        block("BACKUP_DEVICE_READ_ONLY")
    if PARENT.stat().st_dev == (APP / "data").stat().st_dev:
        block("BACKUP_ON_SAME_FILESYSTEM")
    def physical(path):
        src = run(["findmnt", "-T", str(path), "-no", "SOURCE"]).split("[")[0]
        if not src.startswith("/dev/"):
            block("BACKUP_SOURCE_DEVICE_UNVERIFIED")
        root = run(["lsblk", "-no", "PKNAME", src])
        if not root:
            block("BACKUP_PHYSICAL_DEVICE_UNVERIFIED")
        return root
    if physical(PARENT) == physical(APP / "data"):
        block("BACKUP_AND_DATA_SHARE_PHYSICAL_DISK")
    data_bytes = int(run(["du", "-sb", str(APP / "data")]).split()[0])
    if shutil.disk_usage(PARENT).free < data_bytes * 1.35 + 1024**3:
        block("BACKUP_DISK_INSUFFICIENT_SPACE")
    return data_bytes


def manifest_file(path, obj):
    file = path / "manifest.json"
    if file.is_symlink():
        block("UNSAFE_MANIFEST")
    with file.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    file.chmod(0o600)


def backup():
    hashes = check_app()
    check_stopped()
    if shutil.which("rsync") is None:
        block("RSYNC_MISSING")
    nbytes = independent_disk()
    print("MODE=V3_TO_050_BACKUP_ONLY")
    print("SOURCE_DATA_BYTES=" + str(nbytes))
    print("APP_CONTAINERS_ABSENT=YES")
    if input("Type BACKUP-050 to create a private independent snapshot: ").strip() != "BACKUP-050":
        block("OPERATOR_DECLINED")
    check_stopped()
    check_app()
    name = PREFIX + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    path = PARENT / name
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)
    m = {
        "schema": SCHEMA, "state": "INCOMPLETE_DO_NOT_RESTORE",
        "source": str(APP), "config_sha256": hashes,
        "source_bytes": nbytes,
    }
    try:
        (path / "config").mkdir(mode=0o700)
        (path / "data").mkdir(mode=0o700)
        for rel in CONFIG:
            dst = path / "config" / rel
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            run(["rsync", "-aHAX", "--numeric-ids", "--", str(APP / rel), str(dst)])
            if sha256(dst) != hashes[rel]:
                block("CONFIG_COPY_HASH_MISMATCH")
        run(["rsync", "-aHAX", "--numeric-ids", "--",
             str(APP / "data") + "/", str(path / "data") + "/"])
        diff = run(["rsync", "-aHAXnci", "--delete", "--numeric-ids", "--",
                    str(APP / "data") + "/", str(path / "data") + "/"])
        if diff:
            block("DATA_COPY_CHECKSUM_MISMATCH")
        check_stopped()
        if any(sha256(APP / rel) != digest for rel, digest in hashes.items()):
            block("SOURCE_CONFIG_CHANGED_DURING_BACKUP")
        m["state"] = "FILE_BACKUP_CHECKSUM_VERIFIED"
        manifest_file(path, m)
    except Exception:
        print("BACKUP_UNTRUSTED_DIRECTORY=" + str(path), file=sys.stderr)
        raise
    print("RESULT=OPENBOT_050_BACKUP_VERIFIED")
    print("BACKUP_TRANSACTION=" + str(path))
    print("CONFIG_HASHES_VERIFIED=YES")
    print("DATA_RSYNC_CHECKSUM=PASS")
    print("PRODUCTION_FILES_CHANGED=NO")
    print("APP_REMAINS_STOPPED=YES")
    print("RESTORE_REHEARSAL=NOT_RUN")
    print("BACKUP_ENCRYPTED_AT_REST=NOT_ESTABLISHED")


def safe_snapshot(path):
    if path.parent != PARENT or not path.name.startswith(PREFIX):
        block("SNAPSHOT_LOCATION_INVALID")
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        block("SNAPSHOT_DIRECTORY_UNSAFE")
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        block("SNAPSHOT_PERMISSIONS_UNSAFE")
    marker = path / "manifest.json"
    regular(marker)
    if marker.stat().st_uid != os.geteuid() or stat.S_IMODE(marker.stat().st_mode) != 0o600:
        block("SNAPSHOT_MANIFEST_PERMISSIONS_UNSAFE")
    m = json.loads(marker.read_text(encoding="utf-8"))
    if m.get("schema") != SCHEMA or m.get("state") != "FILE_BACKUP_CHECKSUM_VERIFIED" or m.get("source") != str(APP):
        block("SNAPSHOT_MANIFEST_UNVERIFIED")
    hashes = m.get("config_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(CONFIG):
        block("SNAPSHOT_CONFIG_LIST_INVALID")
    for rel in CONFIG:
        regular(path / "config" / rel)
        if sha256(path / "config" / rel) != hashes[rel]:
            block("SNAPSHOT_CONFIG_CORRUPT")
    if not (path / "data").is_dir() or (path / "data").is_symlink():
        block("SNAPSHOT_DATA_INVALID")
    return m


def rehearse(path):
    require_root()
    independent_disk()
    m = safe_snapshot(path)
    if shutil.which("rsync") is None:
        block("RSYNC_MISSING")
    nbytes = int(m["source_bytes"])
    if shutil.disk_usage(PARENT).free < nbytes * 1.2 + 1024**3:
        block("REHEARSAL_DISK_INSUFFICIENT_SPACE")
    with tempfile.TemporaryDirectory(prefix=".mochilab-openbot-050-restore-test-", dir=PARENT) as name:
        scratch = Path(name)
        for key in ("config", "data"):
            dest = scratch / key
            dest.mkdir(mode=0o700)
            run(["rsync", "-aHAX", "--numeric-ids", "--",
                 str(path / key) + "/", str(dest) + "/"])
            diff = run(["rsync", "-aHAXnci", "--delete", "--numeric-ids", "--",
                        str(path / key) + "/", str(dest) + "/"])
            if diff:
                block("RESTORED_COPY_DIFFERS_" + key.upper())
        for rel in CONFIG:
            if sha256(scratch / "config" / rel) != m["config_sha256"][rel]:
                block("RESTORED_CONFIG_HASH_MISMATCH")
    print("RESULT=OPENBOT_050_FILE_RESTORE_REHEARSAL_PASS")
    print("RESTORED_DATA_BYTES=" + str(nbytes))
    print("RESTORED_CONFIG_HASHES=PASS")
    print("RESTORED_DATA_RSYNC_CHECKSUM=PASS")
    print("TEST_SCRATCH_REMOVED=YES")
    print("LIVE_APP_OR_DATA_CHANGED=NO")
    print("OPENBOT_FULL_APP_RESTORE_TEST=NOT_RUN")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--backup", action="store_true")
    group.add_argument("--rehearse", type=Path, metavar="SNAPSHOT_DIR")
    args = parser.parse_args()
    try:
        if args.preflight:
            check_app()
            n = independent_disk()
            print("RESULT=OPENBOT_050_BACKUP_PREFLIGHT_PASS_NO_WRITES")
            print("SOURCE_DATA_BYTES=" + str(n))
            print("PRODUCTION_UNMODIFIED=YES")
        elif args.backup:
            backup()
        else:
            rehearse(args.rehearse)
        return 0
    except (Blocked, OSError, ValueError, KeyError, TypeError) as err:
        print("BLOCKED=" + (str(err) if isinstance(err, Blocked)
                             else "BACKUP_REHEARSAL_UNEXPECTED_ERROR"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
