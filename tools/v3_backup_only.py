#!/usr/bin/env python3
"""Independent stopped-only V3 OpenBot backup checkpoint.

This creates a verified backup but NEVER stages security changes, starts/stops
apps, changes data under /data, or loads AppArmor. Backup may contain private
OpenBot sessions/credentials; it is created with mode 0700 for root only.
"""
import argparse
from pathlib import Path
import secrets
import shutil
import sys
import time

import v3_workspace_transaction as tx

SCHEMA = "mochilab-openbot-v3-backup-only"


def backup_only(parent):
    tx.owned_root()
    tx.check_stopped()
    tx.check_installed()
    # Pinned artifacts and the current AppArmor label must still be reviewed,
    # but parsing here is read-only and does not load a kernel policy.
    tx.check_artifacts()
    for command in ("git", "rsync", "findmnt", "lsblk", "du", "docker"):
        if shutil.which(command) is None:
            tx.fail("BACKUP_TOOL_MISSING_" + command.upper())
    size = tx.external_backup_parent(parent)
    if tx.run(["findmnt", "-T", str(parent), "-no", "TARGET"]) != str(parent):
        tx.fail("BACKUP_PARENT_MUST_BE_MOUNT_ROOT")
    print("MODE=BACKUP_ONLY_NO_POLICY_CHANGES")
    print("APP_CONTAINERS_ABSENT=YES")
    print("SOURCE_DATA_BYTES=" + str(size))
    if input("Type BACKUP-V3 to create an independent OpenBot backup: ").strip() != "BACKUP-V3":
        tx.fail("BACKUP_OPERATOR_CONFIRMATION_MISSING")
    tx.check_stopped()
    original = {rel: tx.digest((tx.APP / rel).read_bytes()) for rel in tx.BACKUP_CONFIG}
    manifest = {
        "schema": SCHEMA,
        "app": str(tx.APP),
        "state": "PREPARING",
        "original_sha256": original,
        "data_restore_test": "NOT_RUN",
        "production_mutation": "NONE",
    }
    path = parent / (
        ".mochilab-openbot-v3-backup-only-"
        + time.strftime("%Y%m%d-%H%M%S")
        + "-" + secrets.token_hex(4)
    )
    tx.secure_dir(path)
    try:
        tx.prepare_backup(parent, manifest, transaction=path)
        tx.check_stopped()
    except Exception:
        # Fail closed. A partial backup directory is preserved, never removed
        # automatically, and must not be treated as a successful checkpoint.
        manifest["state"] = "UNTRUSTED_INCOMPLETE"
        tx.manifest_save(path, manifest)
        print("BLOCKED=BACKUP_ONLY_INCOMPLETE_DO_NOT_STAGE", file=sys.stderr)
        print("INCOMPLETE_TRANSACTION=" + str(path), file=sys.stderr)
        raise
    if manifest["state"] != "BACKED_UP":
        tx.fail("BACKUP_MANIFEST_STATE_DRIFT")
    print("RESULT=V3_BACKUP_ONLY_VERIFIED_COPY")
    print("BACKUP_TRANSACTION=" + str(path))
    print("CONFIG_HASHES_VERIFIED=YES")
    print("DATA_RSYNC_CHECKSUM_COMPARISON=PASS")
    print("SOURCE_DATA_MODIFIED=NO")
    print("APP_REMAINS_STOPPED=YES")
    print("SECURITY_POLICY_CHANGED=NO")
    print("RESTORE_TEST=NOT_RUN")
    print("BACKUP_ENCRYPTED_AT_REST=NOT_ESTABLISHED")


def main():
    p = argparse.ArgumentParser(description="OpenBot V3 offline backup-only checkpoint")
    p.add_argument("--backup-only", type=Path, required=True, metavar="EXTERNAL_HDD_MOUNT")
    a = p.parse_args()
    try:
        backup_only(a.backup_only)
    except (tx.Blocked, OSError, ValueError, KeyError) as e:
        print("BLOCKED=" + (str(e) if isinstance(e, tx.Blocked)
                            else "BACKUP_ONLY_UNEXPECTED_VALIDATION_ERROR"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
