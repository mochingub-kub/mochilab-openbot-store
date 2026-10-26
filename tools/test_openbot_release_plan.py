"""Offline Mochilab OpenBot updater regression tests; no Docker or host access."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import openbot_release_plan as up


class SafeUpdater(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for relative in (
            up.IMAGE_FILE, up.MANIFEST_FILE,
            "mochilab-openbot/hooks/pre-start",
            "mochilab-openbot/hooks/mochilab-openbot-workspace.apparmor",
            "mochilab-openbot/hooks/seccomp-workspace.json",
        ):
            dest = self.root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(up.ROOT / relative, dest)
        self.initial_version = up.current(self.root)

    def test_packaged_version_and_security_integrity(self):
        self.assertEqual(up.current(self.root), self.initial_version)

    def test_build_next_version_edits_only_image_manifest_and_note(self):
        before = (self.root / up.IMAGE_FILE).read_text()
        hook = (self.root / "mochilab-openbot/hooks/pre-start").read_bytes()
        self.assertTrue(up.propose(self.root, "999.999.999"))
        self.assertEqual(up.current(self.root), "999.999.999")
        after = (self.root / up.IMAGE_FILE).read_text()
        self.assertEqual(after.replace("openbot:999.999.999", "openbot:" + self.initial_version), before)
        m = (self.root / up.MANIFEST_FILE).read_text()
        self.assertIn('version: "999.999.999-1"', m)
        self.assertIn("engine to 999.999.999", m)
        self.assertEqual(hook, (self.root / "mochilab-openbot/hooks/pre-start").read_bytes())
        self.assertEqual(list(self.root.rglob("*.apparmor"))[0].read_bytes(),
                         (up.ROOT / "mochilab-openbot/hooks/mochilab-openbot-workspace.apparmor").read_bytes())

    def test_same_or_older_release_does_not_downgrade(self):
        compose = (self.root / up.IMAGE_FILE).read_bytes()
        self.assertFalse(up.propose(self.root, self.initial_version))
        self.assertFalse(up.propose(self.root, "0.0.0"))
        self.assertEqual((self.root / up.IMAGE_FILE).read_bytes(), compose)

    def test_bad_version_rejected_without_modifications(self):
        compose = (self.root / up.IMAGE_FILE).read_bytes()
        with self.assertRaises(up.Blocked):
            up.propose(self.root, "latest")
        self.assertEqual((self.root / up.IMAGE_FILE).read_bytes(), compose)

    def test_app_manifest_mismatch_rejected(self):
        manifest = self.root / up.MANIFEST_FILE
        manifest.write_text(manifest.read_text().replace("version: \"" + self.initial_version + "-1\"", "version: \"0.0.0-1\""))
        with self.assertRaises(up.Blocked) as err:
            up.current(self.root)
        self.assertIn("PACKAGE_IMAGE_VERSION_DRIFT", str(err.exception))

    def test_v3_seccomp_modified_rejected(self):
        file = self.root / "mochilab-openbot/hooks/seccomp-workspace.json"
        file.write_bytes(file.read_bytes() + b"\n ")
        with self.assertRaises(up.Blocked) as err:
            up.current(self.root)
        self.assertIn("V3_REVIEWED_ARTIFACT_DRIFT", str(err.exception))

    def test_v3_apparmor_modified_rejected(self):
        file = self.root / "mochilab-openbot/hooks/mochilab-openbot-workspace.apparmor"
        file.write_bytes(file.read_bytes() + b"\n")
        with self.assertRaises(up.Blocked) as err:
            up.current(self.root)
        self.assertIn("V3_REVIEWED_ARTIFACT_DRIFT", str(err.exception))

    def test_expanded_capabilities_refused(self):
        compose = self.root / up.IMAGE_FILE
        compose.write_text(compose.read_text() + "\n    privileged: true\n")
        with self.assertRaises(up.Blocked):
            up.current(self.root)

    def test_removed_workspace_profile_refused(self):
        compose = self.root / up.IMAGE_FILE
        compose.write_text(compose.read_text().replace(
            "apparmor=mochilab-openbot-workspace", "apparmor=unconfined"))
        with self.assertRaises(up.Blocked):
            up.current(self.root)

    def test_upstream_unchanged_seccomp_accepted(self):
        rel = {"tag_name": "v0.51.1", "prerelease": False, "draft": False,
               "assets": [{"name": "OpenBot-0.51.1-x86_64.AppImage"}]}
        with mock.patch.object(up, "github_json", side_effect=[
            rel, {"sha": up.UPSTREAM_SC}
        ]) as http:
            self.assertEqual(up.stable(), "0.51.1")
            self.assertEqual(http.call_count, 2)

    def test_upstream_seccomp_change_stops_review(self):
        rel = {"tag_name": "v0.51.1", "prerelease": False, "draft": False,
               "assets": [{"name": "OpenBot-0.51.1-x86_64.AppImage"}]}
        with mock.patch.object(up, "github_json", side_effect=[
            rel, {"sha": "0000000000000000000000000000000000000000"}
        ]):
            with self.assertRaises(up.Blocked) as err:
                up.stable()
        self.assertIn("UPSTREAM_SECCOMP_CHANGED_MANUAL_REVIEW_REQUIRED",
                      str(err.exception))

    def test_prerelease_rejected(self):
        with mock.patch.object(up, "github_json", return_value={
            "tag_name": "v0.51.0-rc1", "prerelease": True
        }):
            with self.assertRaises(up.Blocked):
                up.stable()


if __name__ == "__main__":
    unittest.main(verbosity=2)
