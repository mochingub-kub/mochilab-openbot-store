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
        self.actual_check_live_baseline = tx.check_live_baseline
        self.actual_check_stopped = tx.check_stopped
        self.actual_external_backup_parent = tx.external_backup_parent
        self.patchers = [
            mock.patch.object(tx, "check_stopped", side_effect=lambda: True),
            mock.patch.object(tx, "check_live_baseline", side_effect=lambda **_: True),
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

    def test_interrupted_publish_can_restore_exact_original(self):
        original = tx.atomic_publish

        def fail_before_hook(target, payload, **kwargs):
            if target.name == "pre-start":
                raise OSError("synthetic interrupted hook publish")
            return original(target, payload, **kwargs)

        with mock.patch.object(tx, "atomic_publish", side_effect=fail_before_hook):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError):
                    tx.stage(self.parent)
        transaction, = list(self.parent.glob(".mochilab-openbot-v3-*"))
        manifest = json.loads((transaction / "manifest.json").read_text())
        self.assertEqual(manifest["state"], "NEEDS_RECOVERY")
        with contextlib.redirect_stdout(io.StringIO()):
            tx.restore(transaction)
        self.assertEqual((self.app / "hooks/pre-start").read_text(), "old-hooks/pre-start\n")
        self.assertEqual((self.app / "docker-compose.yml").read_text(), "old-docker-compose.yml\n")
        self.assertFalse((self.app / tx.NEW_ONLY[0]).exists())
        self.assertEqual((self.app / "data" / "canary.txt").read_text(), "private test fixture")

    def test_transaction_permissions_are_strict(self):
        transaction = self.do_stage()
        transaction.chmod(0o755)
        with self.assertRaises(tx.Blocked) as error:
            tx.restore(transaction)
        self.assertIn("TRANSACTION_OWNERSHIP_OR_PERMISSIONS_UNSAFE", str(error.exception))

    def test_saved_container_baseline_requires_expected_isolation(self):
        obj = {
            "State": {"Running": False},
            "AppArmorProfile": "mochilab-openbot",
            "HostConfig": {
                "Privileged": False, "CapAdd": None,
                "SecurityOpt": [
                    "apparmor=mochilab-openbot",
                    "seccomp=/app/seccomp-0.49.0.json",
                    "no-new-privileges:true",
                ],
            },
            "Config": {
                "Image": "ghcr.io/nightly-labs/openbot:0.49.0",
                "Labels": {
                    "com.docker.compose.project": "mochilab-openbot",
                    "com.docker.compose.service": "openbot",
                },
            },
            "Mounts": [
                {"Destination": "/data", "Source": str(self.app / "data"), "RW": True},
            ],
        }
        with mock.patch.object(tx, "docker_info", return_value=obj):
            original = self.actual_check_live_baseline
            original(require_running=False)
            with self.assertRaises(tx.Blocked):
                original(require_running=True)
            obj["HostConfig"]["Privileged"] = True
            with self.assertRaises(tx.Blocked):
                original(require_running=False)

    @staticmethod
    def make_umbreld_runtime(source):
        import yaml
        baseline = yaml.safe_load(source)
        del baseline["services"]["app_proxy"]
        return yaml.safe_dump(baseline, sort_keys=False)

    def test_umbreld_generated_runtime_with_real_service_fields_passes(self):
        from test_v3_compose_plan import BASE
        # Generated file is a full Compose minus app_proxy, NOT an override.
        generated = self.make_umbreld_runtime(BASE)
        self.assertIn("security_opt:", generated)
        self.assertIn("volumes:", generated)
        tx.validate_umbreld_runtime_compose(BASE, generated)

    def test_umbreld_generated_runtime_with_managed_long_volume_passes(self):
        from test_v3_compose_plan import BASE, Cases
        baseline = BASE.replace(
            "    volumes:\n      - ${APP_DATA_DIR}/data:/data\n",
            Cases.umbrel_long_volume(),
        )
        tx.validate_umbreld_runtime_compose(
            baseline, self.make_umbreld_runtime(baseline)
        )

    def test_umbreld_security_override_drift_denied(self):
        from test_v3_compose_plan import BASE
        generated = self.make_umbreld_runtime(BASE).replace(
            "apparmor=mochilab-openbot",
            "apparmor=unconfined",
        )
        with self.assertRaises(tx.Blocked) as error:
            tx.validate_umbreld_runtime_compose(BASE, generated)
        self.assertIn("UMBRELD_RUNTIME_COMPOSE_SEMANTIC_DRIFT", str(error.exception))

    def test_umbreld_extra_mount_drift_denied(self):
        from test_v3_compose_plan import BASE
        generated = self.make_umbreld_runtime(BASE).replace(
            "    volumes:\n",
            "    volumes:\n    - /etc:/host:rw\n",
        )
        with self.assertRaises(tx.Blocked):
            tx.validate_umbreld_runtime_compose(BASE, generated)

    def test_umbreld_unknown_service_drift_denied(self):
        from test_v3_compose_plan import BASE
        generated = self.make_umbreld_runtime(BASE) + "  attacker:\n    image: untrusted\n"
        with self.assertRaises(tx.Blocked):
            tx.validate_umbreld_runtime_compose(BASE, generated)

    def test_umbreld_duplicate_yaml_key_denied(self):
        from test_v3_compose_plan import BASE
        generated = self.make_umbreld_runtime(BASE)
        generated = generated.replace("services:\n", "services:\nservices:\n", 1)
        with self.assertRaises(tx.Blocked):
            tx.validate_umbreld_runtime_compose(BASE, generated)

    def test_umbreld_retained_app_proxy_denied(self):
        from test_v3_compose_plan import BASE
        with self.assertRaises(tx.Blocked):
            tx.validate_umbreld_runtime_compose(BASE, BASE)

    def test_umbrel_stop_removed_all_app_containers_is_valid(self):
        # Real Umbrel app-script: docker compose rm --force --stop
        with mock.patch.object(tx, "run", side_effect=["", ""]) as docker_read:
            self.assertTrue(self.actual_check_stopped())
        self.assertEqual(docker_read.call_count, 2)
        self.assertEqual(docker_read.call_args_list[0].args[0][:3],
                         ["docker", "ps", "-aq"])
        self.assertEqual(docker_read.call_args_list[1].args[0][:3],
                         ["docker", "inspect", "--format"])

    def test_umbrel_stop_blocks_lingering_project_containers(self):
        with mock.patch.object(tx, "run", return_value="docker-id-abc") as docker_read:
            with self.assertRaises(tx.Blocked) as error:
                self.actual_check_stopped()
        self.assertIn("APP_CONTAINERS_STILL_PRESENT", str(error.exception))
        self.assertEqual(docker_read.call_count, 1)

    def test_umbrel_stop_blocks_unlabeled_container_with_same_name(self):
        with mock.patch.object(tx, "run", side_effect=["", "docker-id-xyz"]):
            with self.assertRaises(tx.Blocked) as error:
                self.actual_check_stopped()
        self.assertIn("OPENBOT_NAMED_CONTAINER_STILL_PRESENT", str(error.exception))

    def test_app_armor_workspace_label_requires_distinct_unused_name(self):
        profiles = pathlib.Path(self.tmp.name) / "profiles.txt"
        profiles.write_text("mochilab-openbot (enforce)\n")
        tx.require_fresh_workspace_profile(profiles)
        profiles.write_text("mochilab-openbot-workspace (enforce)\n")
        with self.assertRaises(tx.Blocked) as exc:
            tx.require_fresh_workspace_profile(profiles)
        self.assertIn("WORKSPACE_PROFILE_ALREADY_LOADED", str(exc.exception))

    def test_missing_kernel_profile_list_blocks_preflight(self):
        path = pathlib.Path(self.tmp.name) / "absent"
        with self.assertRaises(tx.Blocked) as exc:
            tx.require_fresh_workspace_profile(path)
        self.assertIn("APPARMOR_KERNEL_PROFILE_LIST_UNAVAILABLE", str(exc.exception))

    def test_backup_preflight_does_not_modify_app_or_hdd(self):
        before = (self.app / "docker-compose.yml").read_bytes()
        original_data = (self.app / "data" / "canary.txt").read_bytes()
        with mock.patch.object(tx, "check_live_baseline", return_value=True), \
             mock.patch.object(tx, "run", return_value=str(self.parent)), \
             mock.patch.object(tx.shutil, "which", return_value="/usr/bin/verified"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                tx.backup_preflight(self.parent)
        self.assertIn("V3_BACKUP_PREFLIGHT_PASS_NO_WRITES", out.getvalue())
        self.assertIn("BACKUP_COPY_CREATED=NO", out.getvalue())
        self.assertEqual((self.app / "docker-compose.yml").read_bytes(), before)
        self.assertEqual((self.app / "data" / "canary.txt").read_bytes(), original_data)
        self.assertFalse(list(self.parent.glob(".mochilab-openbot-v3-*")))

    def test_backup_preflight_refuses_missing_rsync(self):
        def which(name):
            return None if name == "rsync" else "/usr/bin/verified"
        with mock.patch.object(tx.shutil, "which", side_effect=which), \
             mock.patch.object(tx, "check_live_baseline", return_value=True):
            with self.assertRaises(tx.Blocked) as error:
                tx.backup_preflight(self.parent)
        self.assertIn("BACKUP_TOOL_MISSING_RSYNC", str(error.exception))
        self.assertFalse(list(self.parent.glob(".mochilab-openbot-v3-*")))

    def test_external_backup_mount_readonly_rejected(self):
        with mock.patch.object(tx, "run", side_effect=[
            str(self.parent) + " ext4", "ro,nosuid,nodev"
        ]):
            with self.assertRaises(tx.Blocked) as error:
                self.actual_external_backup_parent(self.parent)
        self.assertIn("BACKUP_MOUNT_NOT_READ_WRITE", str(error.exception))

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
