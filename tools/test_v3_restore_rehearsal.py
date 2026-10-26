"""Offline rehearsal tests with synthetic user data, never an Umbrel runtime."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v3_workspace_transaction as tx
import v3_restore_rehearsal as restore


class Rehearsal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.parent = self.root / "external"
        self.parent.mkdir()
        self.backup = self.parent / ".mochilab-openbot-v3-backup-only-20261026-042601-6d1a1298"
        self.backup.mkdir(mode=0o700)
        self.config = self.backup / "config"
        self.data = self.backup / "data"
        self.config.mkdir(mode=0o700)
        self.data.mkdir(mode=0o700)
        expected = {}
        for rel in tx.BACKUP_CONFIG:
            source = self.config / rel
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("original data of " + rel + "\n")
            expected[rel] = tx.digest(source.read_bytes())
        (self.data / "canary.txt").write_text("synthetic private data")
        m = {
            "schema": "mochilab-openbot-v3-backup-only",
            "app": str(self.app),
            "state": "BACKED_UP",
            "data_restore_test": "NOT_RUN",
            "original_sha256": expected
        }
        manifest = self.backup / "manifest.json"
        manifest.write_text(json.dumps(m))
        manifest.chmod(0o600)
        self.patchers = [
            mock.patch.object(tx, "APP", self.app),
            mock.patch.object(restore, "PARENT", self.parent),
            mock.patch.object(restore.os, "geteuid", return_value=0),
            mock.patch.object(tx, "external_backup_parent", return_value=123),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.real_run = tx.run

        def run_cmd(args, **kwargs):
            if args[:2] == ["findmnt", "-T"] and args[-1] == "TARGET":
                return str(self.parent)
            return self.real_run(args, **kwargs)
        self.run_patcher = mock.patch.object(tx, "run", side_effect=run_cmd)
        self.run_patcher.start()
        self.addCleanup(self.run_patcher.stop)

    def test_file_level_restore_rehearsal_verifies_and_cleans_scratch(self):
        before = (self.data / "canary.txt").read_bytes()
        original_config = (self.config / "docker-compose.yml").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            restore.rehearsal(self.backup)
        self.assertIn("RESULT=V3_FILE_RESTORE_REHEARSAL_PASS", out.getvalue())
        self.assertIn("OPENBOT_FULL_APPLICATION_RESTORE_TEST=NOT_RUN", out.getvalue())
        self.assertEqual((self.data / "canary.txt").read_bytes(), before)
        self.assertEqual((self.config / "docker-compose.yml").read_bytes(), original_config)
        self.assertEqual(list(self.parent.glob(".mochilab-openbot-v3-restore-test-*")), [])

    def test_tampered_config_backup_blocks_before_restore(self):
        (self.config / "docker-compose.yml").write_text("tampered")
        with self.assertRaises(tx.Blocked) as error:
            restore.rehearsal(self.backup)
        self.assertIn("BACKUP_CONFIG_CHECKSUM_FAILED", str(error.exception))
        self.assertEqual(list(self.parent.glob(".mochilab-openbot-v3-restore-test-*")), [])

    def test_unsafe_backup_folder_permission_refused(self):
        self.backup.chmod(0o755)
        with self.assertRaises(tx.Blocked) as error:
            restore.rehearsal(self.backup)
        self.assertIn("BACKUP_TRANSACTION_PERMISSIONS_UNSAFE", str(error.exception))

    def test_backup_state_must_be_verified(self):
        mpath = self.backup / "manifest.json"
        m = json.loads(mpath.read_text())
        m["state"] = "UNTRUSTED_INCOMPLETE"
        mpath.write_text(json.dumps(m))
        with self.assertRaises(tx.Blocked) as error:
            restore.rehearsal(self.backup)
        self.assertIn("BACKUP_MANIFEST_NOT_APPROVED_FOR_REHEARSAL", str(error.exception))

    def test_backup_path_outside_exact_mount_refused(self):
        with self.assertRaises(tx.Blocked) as error:
            restore.rehearsal(self.root / "fake-backup")
        self.assertIn("BACKUP_TRANSACTION_PATH_UNEXPECTED", str(error.exception))

    def test_failed_rsync_never_reports_pass_and_scratch_is_cleaned(self):
        def fail_rsync(args, **kwargs):
            if args[0] == "rsync":
                raise tx.Blocked("SYNTHETIC_RSYNC_FAILURE")
            if args[:2] == ["findmnt", "-T"] and args[-1] == "TARGET":
                return str(self.parent)
            return self.real_run(args, **kwargs)
        with mock.patch.object(tx, "run", side_effect=fail_rsync):
            with self.assertRaises(tx.Blocked):
                restore.rehearsal(self.backup)
        self.assertEqual(list(self.parent.glob(".mochilab-openbot-v3-restore-test-*")), [])
        self.assertEqual((self.data / "canary.txt").read_text(), "synthetic private data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
