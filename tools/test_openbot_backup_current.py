"""Synthetic tests; never contact real Umbrel or touch existing backup disks."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase, main, mock

import openbot_backup_current as bk


class BackupCurrentTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = self.base / 'app'
        self.parent = self.base / 'hdd'
        self.app.mkdir()
        self.parent.mkdir()
        for path in bk.REQUIRED_FILES:
            file = self.app / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'test')
        db = self.app / 'data/.config/OpenBot/openbot.db'
        db.unlink()
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE messages (id INT, body TEXT)')
        conn.execute('INSERT INTO messages VALUES (1, "preserved")')
        conn.commit()
        conn.close()
        (self.app / 'data/OpenBot/Agents/Agent-01').mkdir(parents=True)
        (self.app / 'data/OpenBot/Agents/Agent-01/prompt.txt').write_text('test')
        (self.app / 'data/OpenBot/Shared').mkdir(parents=True)
        (self.app / 'data/.secret').write_text('private')
        (self.app / 'data/OpenBot/Shared/link').symlink_to('../Agents/Agent-01/prompt.txt')
        self.patches = [
            mock.patch.object(bk, 'APP', self.app),
            mock.patch.object(bk, 'PARENT', self.parent),
            mock.patch.object(bk, 'require_root', lambda: None),
            mock.patch.object(bk, 'check_app', lambda: '0.52.0-1'),
            mock.patch.object(bk, 'check_storage', lambda: 25000),
            mock.patch.object(bk, 'check_stopped', lambda: None),
            mock.patch('builtins.input', return_value='BACKUP-OPENBOT'),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _backup(self):
        with contextlib.redirect_stdout(io.StringIO()):
            bk.backup()
        snaps = list(self.parent.glob(bk.PREFIX + '*'))
        return max(snaps, key=lambda p: p.stat().st_ctime)

    def test_backup_stores_all_hidden_files_agents_keys_and_config(self):
        snap = self._backup()
        metadata = bk.verify_snapshot(snap)
        self.assertEqual(metadata['package'], '0.52.0-1')
        self.assertIn('data/.secret', metadata['inventory'])
        self.assertIn('data/OpenBot/Agents/Agent-01/prompt.txt', metadata['inventory'])
        self.assertIn('data/.config/openbot-container/keyring-password', metadata['inventory'])
        self.assertIn('app-gateway.json', metadata['inventory'])
        self.assertEqual(metadata['inventory']['data/OpenBot/Shared/link']['kind'], 'link')
        self.assertFalse(metadata['isolated_full_app_restore'])
        self.assertEqual((snap / 'manifest.json').stat().st_mode & 0o777, 0o600)

    def test_backup_retains_previous_snapshot(self):
        first = self._backup()
        second = self._backup()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertEqual(len(list(self.parent.iterdir())), 2)

    def test_backup_does_not_touch_unrelated_photos(self):
        photos = self.parent / 'PhotoLibrary'
        photos.mkdir()
        (photos / 'precious.jpg').write_bytes(b'photo')
        self._backup()
        self.assertEqual((photos / 'precious.jpg').read_bytes(), b'photo')

    def test_verify_detects_corruption(self):
        snap = self._backup()
        target = snap / 'app/data/.secret'
        target.write_text('tampered')
        with self.assertRaisesRegex(bk.Blocked, 'HASH_OR_METADATA_MISMATCH'):
            bk.verify_snapshot(snap)

    def test_verify_detects_missing_required(self):
        snap = self._backup()
        (snap / 'app/data/.config/openbot-container/keyring-password').unlink()
        with self.assertRaises(bk.Blocked):
            bk.verify_snapshot(snap)

    def test_verify_blocks_symlink_snapshot_root(self):
        snap = self._backup()
        symlink = self.parent / (bk.PREFIX + '20261027-000000-00000000')
        symlink.symlink_to(snap, target_is_directory=True)
        with self.assertRaisesRegex(bk.Blocked, 'SNAPSHOT_NOT_REAL_DIRECTORY'):
            bk.verify_snapshot(symlink)

    def test_verify_blocks_unrelated_path(self):
        snap = self._backup()
        with self.assertRaisesRegex(bk.Blocked, 'SNAPSHOT_NAME_OR_PATH_INVALID'):
            bk.verify_snapshot(snap / 'app')

    def test_rehearse_file_restore_and_sqlite_integrity(self):
        snap = self._backup()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            bk.rehearse(snap)
        self.assertIn('ISOLATED_FILE_RESTORE_REHEARSAL_PASS', captured.getvalue())
        self.assertIn('FULL_APP_RESTORE_TEST=NOT_RUN', captured.getvalue())
        self.assertFalse(list(self.parent.glob('.mochilab-openbot-restore-test-*')))
        db = sqlite3.connect(self.app / 'data/.config/OpenBot/openbot.db')
        self.assertEqual(db.execute('SELECT body FROM messages').fetchone(), ('preserved',))
        db.close()

    def test_rehearse_blocks_corruption_before_copy(self):
        snap = self._backup()
        (snap / 'app/data/.secret').write_text('bad')
        with self.assertRaises(bk.Blocked):
            bk.rehearse(snap)
        self.assertFalse(list(self.parent.glob('.mochilab-openbot-restore-test-*')))

    def test_rehearse_rejects_database_corruption(self):
        db = self.app / 'data/.config/OpenBot/openbot.db'
        db.write_bytes(b'not sqlite')
        snap = self._backup()
        with self.assertRaises(sqlite3.DatabaseError):
            bk.rehearse(snap)
        self.assertFalse(list(self.parent.glob('.mochilab-openbot-restore-test-*')))

    def test_backup_refuses_nonstopped_app_before_copy(self):
        with mock.patch.object(bk, 'check_stopped', side_effect=bk.Blocked('UMBREL_APP_NOT_STOPPED')):
            with self.assertRaisesRegex(bk.Blocked, 'NOT_STOPPED'):
                bk.backup()
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_backup_failed_rsync_keeps_previous_and_no_manifest(self):
        previous = self._backup()
        real_run = bk.run
        def fail_rsync(args, **kwargs):
            if args[0] == 'rsync':
                raise bk.Blocked('COMMAND_FAILED_RSYNC')
            return real_run(args, **kwargs)
        with mock.patch.object(bk, 'run', side_effect=fail_rsync):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(bk.Blocked):
                    bk.backup()
        self.assertTrue(previous.is_dir())
        self.assertEqual(sum(1 for p in self.parent.iterdir() if (p / 'manifest.json').exists()), 1)
        self.assertFalse(list(self.parent.glob('.mochilab-openbot-staging-*')))

    def test_backup_blocks_file_mismatch_and_marks_incomplete(self):
        previous = self._backup()
        original = bk.inventory
        count = {'n':0}
        def mismatch(path):
            count['n'] += 1
            result = original(path)
            if count['n'] == 2:
                result['data/.secret']['sha256'] = '0'*64
            return result
        with mock.patch.object(bk, 'inventory', side_effect=mismatch):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(bk.Blocked, 'CHANGED_DURING_VERIFICATION'):
                    bk.backup()
        self.assertTrue(previous.is_dir())
        self.assertEqual(sum(1 for p in self.parent.iterdir() if (p / 'manifest.json').exists()), 1)
        self.assertFalse(list(self.parent.glob('.mochilab-openbot-staging-*')))


class StrictConfigTests(TestCase):
    def test_yaml_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'bad.yml'
            path.write_text('id: one\nid: two\n')
            with self.assertRaisesRegex(bk.Blocked, 'DUPLICATE_OR_INVALID_YAML_KEY'):
                bk.strict_yaml(path)

    def test_yaml_rejects_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'bad.yml'
            path.write_text('id: &x one\nvalue: *x\n')
            with self.assertRaisesRegex(bk.Blocked, 'YAML_ALIAS_OR_ANCHOR'):
                bk.strict_yaml(path)

    def test_script_contains_no_prune_or_delete_mode(self):
        source = Path(bk.__file__).read_text()
        self.assertNotIn('shutil.rmtree(', source)
        self.assertNotIn('os.unlink(', source)
        self.assertNotIn("'--prune'", source)
        self.assertNotIn("'--delete-old'", source)


if __name__ == '__main__':
    main()
