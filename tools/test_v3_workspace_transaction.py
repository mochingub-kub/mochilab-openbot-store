"""Isolated filesystem regression tests; never connect to Docker or Umbrel."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v3_workspace_transaction as tx


class Transaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.app = root / "app"
        self.parent = root / "external"
        self.policy = root / "reviewed"
        for directory in (self.app / "data", self.app / "hooks", self.parent, self.policy):
            directory.mkdir(parents=True)
        for rel in tx.BACKUP_CONFIG:
            path = self.app / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("old-" + rel + "\n")
        (self.app / "data" / "canary.txt").write_text("private test fixture")
        for rel in tx.STAGED:
            (self.policy / pathlib.Path(rel).name).write_text("new-" + rel + "\n")
        self.app_patch = mock.patch.object(tx, "APP", self.app)
        self.app_patch.start()
        self.addCleanup(self.app_patch.stop)
        self.patchers = [
            mock.patch.object(tx, "check_stopped", side_effect=lambda: True),
            mock.patch.object(tx, "check_installed",
                              side_effect=lambda: ("sample", "baseline-hash", "new simulated compose\n")),
            mock.patch.object(tx, "check_artifacts", return_value=self.policy),
            mock.patch.object(tx, "external_backup_parent", return_value=15),
            mock.patch("builtins.input", return_value="STAGE-V3"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def do_stage(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tx.stage(self.parent)
        transactions = list(self.parent.glob(".mochilab-openbot-v3-*"))
        self.assertEqual(len(transactions), 1)
        return transactions[0]

    def test_stage_and_rollback_retains_data(self):
        transaction = self.do_stage()
        manifest = json.loads((transaction / "manifest.json").read_text())
        self.assertEqual(manifest["state"], "STAGED")
        self.assertEqual((transaction / "data" / "canary.txt").read_text(), "private test fixture")
        self.assertEqual((self.app / "docker-compose.yml").read_text(), "new simulated compose\n")
        self.assertTrue((self.app / tx.NEW_ONLY[0]).exists())
        with contextlib.redirect_stdout(io.StringIO()):
            tx.restore(transaction)
        self.assertEqual((self.app / "docker-compose.yml").read_text(), "old-docker-compose.yml\n")
        self.assertEqual((self.app / "hooks/pre-start").read_text(), "old-hooks/pre-start\n")
        self.assertFalse((self.app / tx.NEW_ONLY[0]).exists())
        self.assertFalse((self.app / tx.NEW_ONLY[1]).exists())
        self.assertEqual((self.app / "data" / "canary.txt").read_text(), "private test fixture")
        manifest = json.loads((transaction / "manifest.json").read_text())
        self.assertEqual(manifest["state"], "ROLLED_BACK")

    def test_rollback_blocks_third_party_edit(self):
        transaction = self.do_stage()
        path = self.app / "docker-compose.yml"
        path.write_text("third-party config\n")
        with self.assertRaises(tx.Blocked) as error:
            tx.restore(transaction)
        self.assertIn("ROLLBACK_CONFLICT_", str(error.exception))
        self.assertEqual(path.read_text(), "third-party config\n")

    def test_manifest_invalid_owner_blocks(self):
        transaction = self.do_stage()
        (transaction / "manifest.json").write_text('{"schema": "not-v3"}')
        with self.assertRaises(tx.Blocked):
            tx.restore(transaction)

    def test_staging_requires_explicit_operator_confirmation(self):
        with mock.patch("builtins.input", return_value=""):
            with self.assertRaises(tx.Blocked) as error:
                tx.stage(self.parent)
        self.assertIn("OPERATOR_CONFIRMATION_MISSING", str(error.exception))
        self.assertFalse(list(self.parent.glob(".mochilab-openbot-v3-*")))

    def test_atomic_replacement_keeps_metadata_and_unrelated_bytes(self):
        target = self.app / "hooks/pre-start"
        before = target.stat()
        tx.atomic_publish(target, b"updated\n")
        after = target.stat()
        self.assertEqual((before.st_uid, before.st_gid, before.st_mode & 0o777),
                         (after.st_uid, after.st_gid, after.st_mode & 0o777))
        self.assertEqual(target.read_bytes(), b"updated\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
