"""Synthetic stopped-only 0.50 upgrade snapshot tests; never touch real Umbrel."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import openbot_upgrade_backup as bk


@unittest.skipUnless(shutil.which("rsync"), "rsync is required to test a real snapshot copy")
class BackupLifecycle(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.app = self.root / "app"
        self.hdd = self.root / "hdd"
        self.app.mkdir()
        self.hdd.mkdir()
        (self.app / "data").mkdir()
        for rel in bk.CONFIG:
            p = self.app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synth-" + rel)
        (self.app / "data" / "fixture.txt").write_text("synthetic-private-session")
        (self.app / "data" / "link").symlink_to("fixture.txt")
        patches = [
            mock.patch.object(bk, "APP", self.app),
            mock.patch.object(bk, "PARENT", self.hdd),
            mock.patch.object(bk, "require_root", return_value=None),
            mock.patch.object(bk, "check_stopped", return_value=None),
            mock.patch.object(bk, "independent_disk", return_value=80),
            mock.patch.object(bk, "check_app", side_effect=self.hashes),
            mock.patch("builtins.input", return_value="BACKUP-050"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def hashes(self):
        return {rel: bk.sha256(self.app / rel) for rel in bk.CONFIG}

    def create(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            bk.backup()
        root, = list(self.hdd.glob(bk.PREFIX + "*"))
        return root, out.getvalue()

    def test_copy_checksum_and_restoration_into_only_temporary_scratch(self):
        snap, text = self.create()
        self.assertIn("RESULT=OPENBOT_050_BACKUP_VERIFIED", text)
        self.assertEqual((snap / "data" / "fixture.txt").read_text(), "synthetic-private-session")
        self.assertTrue((snap / "data" / "link").is_symlink())
        self.assertEqual(json.loads((snap / "manifest.json").read_text())["state"],
                         "FILE_BACKUP_CHECKSUM_VERIFIED")
        self.assertEqual(snap.stat().st_mode & 0o777, 0o700)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            bk.rehearse(snap)
        self.assertIn("RESULT=OPENBOT_050_FILE_RESTORE_REHEARSAL_PASS", out.getvalue())
        self.assertIn("TEST_SCRATCH_REMOVED=YES", out.getvalue())
        self.assertEqual((self.app / "data" / "fixture.txt").read_text(),
                         "synthetic-private-session")
        self.assertEqual(list(self.hdd.glob(".mochilab-openbot-050-restore-test-*")), [])
        self.assertTrue(snap.is_dir())

    def test_declined_approval_does_not_create_a_snapshot(self):
        with mock.patch("builtins.input", return_value="NO"):
            with self.assertRaises(bk.Blocked) as e:
                bk.backup()
        self.assertIn("OPERATOR_DECLINED", str(e.exception))
        self.assertEqual(list(self.hdd.iterdir()), [])

    def test_config_backup_tampering_blocks_rehearsal(self):
        snap, _ = self.create()
        (snap / "config" / "docker-compose.yml").write_text("tampered")
        with self.assertRaises(bk.Blocked) as e:
            bk.rehearse(snap)
        self.assertIn("SNAPSHOT_CONFIG_CORRUPT", str(e.exception))
        self.assertEqual(list(self.hdd.glob(".mochilab-openbot-050-restore-test-*")), [])

    def test_outside_snapshot_path_blocks_rehearsal(self):
        fake = self.root / "other"
        fake.mkdir()
        with self.assertRaises(bk.Blocked) as e:
            bk.rehearse(fake)
        self.assertIn("SNAPSHOT_LOCATION_INVALID", str(e.exception))

    def test_snapshot_permission_widening_blocks_restore(self):
        snap, _ = self.create()
        snap.chmod(0o755)
        with self.assertRaises(bk.Blocked) as e:
            bk.rehearse(snap)
        self.assertIn("SNAPSHOT_PERMISSIONS_UNSAFE", str(e.exception))

    def test_failed_copy_is_never_marked_good(self):
        original = bk.run
        def broken(args, **kwargs):
            if args[0] == "rsync":
                raise bk.Blocked("SYNTHETIC_RSYNC_FAILURE")
            return original(args, **kwargs)
        with mock.patch.object(bk, "run", side_effect=broken):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(bk.Blocked):
                    bk.backup()
        snap, = list(self.hdd.glob(bk.PREFIX + "*"))
        self.assertFalse((snap / "manifest.json").exists())
        self.assertEqual((self.app / "data" / "fixture.txt").read_text(),
                         "synthetic-private-session")


if __name__ == "__main__":
    unittest.main(verbosity=2)
