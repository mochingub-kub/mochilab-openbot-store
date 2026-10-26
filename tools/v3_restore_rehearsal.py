#!/usr/bin/env python3
"""OpenBot V3 file-level restore rehearsal in isolated, auto-cleaned HDD scratch.

Reads only the verified backup transaction. Restores data and configuration
to a NEW private temporary directory on that same external HDD, compares
checksums and attributes, then removes only this new temporary copy.
Never stops/starts OpenBot, edits production, reads live /data, or changes
its security policy. Does not test whether the restored APP boots.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

import v3_workspace_transaction as tx

PARENT = Path("/home/umbrel/umbrel/external/mochi-external")
BACKUP_NAME = re.compile(r"\A\.mochilab-openbot-v3-backup-only-\d{8}-\d{6}-[0-9a-f]{8}\Z")
SCHEMA = "mochilab-openbot-v3-backup-only"


def verify_backup(backup):
    if os.geteuid() != 0:
        tx.fail("RUN_AS_ROOT_ON_UMBREL_HOST")
    if not backup.is_absolute() or backup.parent != PARENT or not BACKUP_NAME.fullmatch(backup.name):
        tx.fail("BACKUP_TRANSACTION_PATH_UNEXPECTED")
    if backup.is_symlink() or not backup.is_dir() or backup.resolve(strict=True) != backup:
        tx.fail("BACKUP_TRANSACTION_PATH_UNSAFE")
    st = backup.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        tx.fail("BACKUP_TRANSACTION_PERMISSIONS_UNSAFE")
    marker = backup / "manifest.json"
    tx.regular(marker)
    if marker.stat().st_uid != 0 or stat.S_IMODE(marker.stat().st_mode) != 0o600:
        tx.fail("BACKUP_MANIFEST_PERMISSIONS_UNSAFE")
    m = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(m, dict) or m.get("schema") != SCHEMA or m.get("app") != str(tx.APP):
        tx.fail("BACKUP_MANIFEST_IDENTITY_INVALID")
    if m.get("state") != "BACKED_UP" or m.get("data_restore_test") != "NOT_RUN":
        tx.fail("BACKUP_MANIFEST_NOT_APPROVED_FOR_REHEARSAL")
    expected = m.get("original_sha256")
    if not isinstance(expected, dict) or set(expected) != set(tx.BACKUP_CONFIG):
        tx.fail("BACKUP_CONFIG_HASHES_INVALID")
    for d in (backup / "config", backup / "data"):
        if d.is_symlink() or not d.is_dir():
            tx.fail("BACKUP_DIRECTORY_INVALID")
    for rel in tx.BACKUP_CONFIG:
        file = backup / "config" / rel
        tx.regular(file)
        if tx.digest(file.read_bytes()) != expected[rel]:
            tx.fail("BACKUP_CONFIG_CHECKSUM_FAILED")
    return m


def rehearsal(backup):
    m = verify_backup(backup)
    if shutil.which("rsync") is None:
        tx.fail("RSYNC_UNAVAILABLE")
    # Confirm this is still the physically independent mount selected by owner.
    tx.external_backup_parent(PARENT)
    if tx.run(["findmnt", "-T", str(PARENT), "-no", "TARGET"]) != str(PARENT):
        tx.fail("BACKUP_PARENT_IS_NOT_MOUNT_ROOT")
    data = backup / "data"
    source_bytes = int(tx.run(["du", "-sb", str(data)]).split()[0])
    if shutil.disk_usage(PARENT).free < source_bytes * 1.2 + 1024**3:
        tx.fail("INSUFFICIENT_REHEARSAL_SCRATCH_SPACE")

    # All restores are confined to an automatically generated private
    # directory. TemporaryDirectory cleans ONLY the directory it just made.
    # No deletion, write, or rsync target ever points at production /data.
    with tempfile.TemporaryDirectory(prefix=".mochilab-openbot-v3-restore-test-",
                                     dir=str(PARENT)) as scratch:
        root = Path(scratch)
        if root.parent != PARENT or root.is_symlink():
            tx.fail("SCRATCH_DIRECTORY_UNSAFE")
        config_out = root / "config"
        data_out = root / "data"
        config_out.mkdir(mode=0o700)
        data_out.mkdir(mode=0o700)

        for name in ("config", "data"):
            src = backup / name
            target = root / name
            tx.run(["rsync", "-aHAX", "--numeric-ids", "--",
                    str(src) + "/", str(target) + "/"])
            delta = tx.run(["rsync", "-aHAXnci", "--delete", "--numeric-ids", "--",
                            str(src) + "/", str(target) + "/"])
            if delta:
                tx.fail("RESTORED_COPY_CHECKSUM_OR_METADATA_MISMATCH_" + name.upper())
        for rel in tx.BACKUP_CONFIG:
            file = root / "config" / rel
            tx.regular(file)
            if tx.digest(file.read_bytes()) != m["original_sha256"][rel]:
                tx.fail("RESTORED_CONFIG_CHECKSUM_MISMATCH")
    # The temporary copy was removed when the context exited successfully.
    print("RESULT=V3_FILE_RESTORE_REHEARSAL_PASS")
    print("RESTORED_DATA_BYTES=" + str(source_bytes))
    print("CONFIG_RESTORED_HASHES_VERIFIED=YES")
    print("RESTORED_DATA_RSYNC_CHECKSUM=PASS")
    print("TEMPORARY_TEST_COPY_CLEANED=YES")
    print("BACKUP_CONTENTS_CHANGED=NO")
    print("PRODUCTION_APP_OR_DATA_CHANGED=NO")
    print("OPENBOT_FULL_APPLICATION_RESTORE_TEST=NOT_RUN")
    print("CODEX_WORKSPACE_FUNCTIONAL_TEST=NOT_RUN")


def main():
    parser = argparse.ArgumentParser(description="V3 isolated file-level restore rehearsal")
    parser.add_argument("--rehearse", type=Path, required=True, metavar="VERIFIED_BACKUP_TRANSACTION")
    a = parser.parse_args()
    try:
        rehearsal(a.rehearse)
    except (tx.Blocked, OSError, ValueError, KeyError, TypeError) as e:
        print("BLOCKED=" + (str(e) if isinstance(e, tx.Blocked)
                             else "RESTORE_REHEARSAL_UNEXPECTED_ERROR"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
