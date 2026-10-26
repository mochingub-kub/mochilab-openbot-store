"""Unit tests for read-only Docker runtime footprint check. No live Docker access."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v3_workspace_transaction as tx
import v3_effective_runtime_check as eff


class EffectiveReadOnly(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "app"
        (self.root / "data").mkdir(parents=True)
        (self.root / "landing").mkdir(parents=True)
        app_patch = mock.patch.object(tx, "APP", self.root)
        app_patch.start()
        self.addCleanup(app_patch.stop)
        self.services = [self.fixture("landing"), self.fixture("openbot")]
        self.work = [
            mock.patch.object(tx, "owned_root", return_value=True),
            mock.patch.object(tx, "check_installed", return_value=("old","sha","candidate")),
            mock.patch.object(tx, "check_artifacts", return_value=None),
            mock.patch.object(tx, "check_live_baseline", return_value=None),
        ]
        for p in self.work:
            p.start()
            self.addCleanup(p.stop)

    def fixture(self, service):
        is_openbot = service == "openbot"
        return {
            "Id": "mock-id-" + service,
            "State": {"Running": True, "Status": "running"},
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "mochilab-openbot",
                    "com.docker.compose.service": service,
                },
                "Image": eff.OPENBOT_IMAGE if is_openbot else eff.LANDING_IMAGE,
                "User": "" if is_openbot else "101:101",
            },
            "HostConfig": {
                "Privileged": False, "CapAdd": None, "Devices": [],
                "PidMode": "", "IpcMode": "", "NetworkMode": "umbrel_main_network",
                "PortBindings": {},
                "ReadonlyRootfs": not is_openbot,
                "CapDrop": None if is_openbot else ["ALL"],
                "SecurityOpt": [
                    "no-new-privileges:true",
                    "apparmor=mochilab-openbot",
                    "seccomp=/host/seccomp-0.49.0.json",
                ] if is_openbot else ["no-new-privileges:true"],
                "Tmpfs": {} if is_openbot else {"/tmp": "rw,nosuid,nodev,size=64m"},
            },
            "NetworkSettings": {"Networks": {"umbrel_main_network": {}}},
            "Mounts": [{
                "Type": "bind",
                "Destination": "/data" if is_openbot else "/usr/share/nginx/html",
                "Source": str(self.root / ("data" if is_openbot else "landing")),
                "RW": is_openbot,
            }]
        }

    def execute(self):
        def read(args, **kwargs):
            if args[:3] == ["docker","ps","-aq"]:
                return "landing-id\nopenbot-id"
            if args[:2] == ["docker", "inspect"]:
                return json.dumps(self.services)
            raise AssertionError("unexpected command")
        with mock.patch.object(tx, "run", side_effect=read), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            eff.main_check()
        return output.getvalue()

    def test_exact_expected_services_pass(self):
        output = self.execute()
        self.assertIn("RESULT=V3_EFFECTIVE_RUNNING_BASELINE_PASS_NO_WRITES",output)
        self.assertIn("EFFECTIVE_COMPOSE_AFTER_V3_STAGE=NOT_TESTED",output)

    def test_extra_openbot_host_mount_denied(self):
        self.services[1]["Mounts"].append({
            "Type": "bind", "Destination": "/host", "Source": "/etc",
            "RW": True
        })
        with self.assertRaises(tx.Blocked):
            self.execute()

    def test_extra_privileges_denied(self):
        self.services[1]["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
        with self.assertRaises(tx.Blocked):
            self.execute()

    def test_public_host_port_binding_denied(self):
        self.services[1]["HostConfig"]["PortBindings"] = {
            "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9090"}]
        }
        with self.assertRaises(tx.Blocked):
            self.execute()

    def test_unknown_network_denied(self):
        self.services[1]["NetworkSettings"]["Networks"]["host"] = {}
        with self.assertRaises(tx.Blocked):
            self.execute()

    def test_wrong_landing_user_denied(self):
        self.services[0]["Config"]["User"] = "root"
        with self.assertRaises(tx.Blocked):
            self.execute()

    def test_duplicate_service_denied(self):
        self.services[1]["Config"]["Labels"]["com.docker.compose.service"]="landing"
        with self.assertRaises(tx.Blocked):
            self.execute()

if __name__ == "__main__":
    unittest.main(verbosity=2)
