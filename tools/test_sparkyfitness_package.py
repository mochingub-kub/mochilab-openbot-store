import copy
from pathlib import Path
import subprocess
import unittest

from sparkyfitness_release_plan import APP, APP_IMAGES, ROOT, load_package, validate_update, version


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.before = load_package(ROOT / APP)
        major, minor, patch = version(self.before[0]["version"])
        self.target = f"v{major}.{minor}.{patch + 1}"
        self.release = {"tag_name": self.target, "draft": False, "prerelease": False}
        self.after = copy.deepcopy(self.before)
        self.after[0]["version"] = self.release["tag_name"]
        self.after[0]["releaseNotes"] = "Example release"
        for service, repo in APP_IMAGES.items():
            self.after[1]["services"][service]["image"] = repo + ":" + self.target + "@sha256:" + "a" * 64

    def test_version_only_candidate(self):
        validate_update(self.before, self.after, self.release)

    def test_block_db_mount_origin_and_auth_changes(self):
        for field, value in (("image", "postgres:19-alpine"),
                             ("volumes", ["/data/db:/var/lib/postgresql"])):
            after = copy.deepcopy(self.after)
            after[1]["services"]["db"][field] = value
            with self.assertRaises(ValueError):
                validate_update(self.before, after, self.release)
        for field in ("PROXY_AUTH_ADD", "APP_HOST"):
            after = copy.deepcopy(self.after)
            after[1]["services"]["app_proxy"]["environment"][field] = "changed"
            with self.assertRaises(ValueError):
                validate_update(self.before, after, self.release)

    def test_block_wrong_repo_unpinned_image_and_manifest(self):
        for image in ("attacker/server:v1.12.2@sha256:" + "a" * 64,
                      "codewithcj/sparkyfitness_server:latest"):
            after = copy.deepcopy(self.after)
            after[1]["services"]["server"]["image"] = image
            with self.assertRaises(ValueError):
                validate_update(self.before, after, self.release)
        self.after[0]["port"] = 9999
        with self.assertRaises(ValueError):
            validate_update(self.before, self.after, self.release)

    def test_block_unstable_same_version_and_downgrade(self):
        for value in (self.before[0]["version"], "v0.0.0", self.target + "-beta", "latest"):
            release = dict(self.release, tag_name=value)
            with self.assertRaises(ValueError):
                validate_update(self.before, self.after, release)
        for key in ("draft", "prerelease"):
            with self.assertRaises(ValueError):
                validate_update(self.before, self.after, dict(self.release, **{key: True}))

    def test_package_storage_dns_secrets_and_readiness(self):
        manifest, compose = self.before
        self.assertEqual(manifest["id"], APP)
        self.assertEqual(manifest["storage"], {"dataRoot": "data"})
        self.assertEqual(manifest["port"], 3019)
        services = compose["services"]
        self.assertEqual(set(services), {"app_proxy", "db", "server", "frontend", "garmin"})
        self.assertEqual(services["app_proxy"]["environment"]["APP_HOST"], APP + "_frontend_1")
        self.assertEqual(services["server"]["environment"]["SPARKY_FITNESS_DB_HOST"], APP + "_db_1")
        self.assertEqual(services["frontend"]["environment"]["SPARKY_FITNESS_SERVER_HOST"], APP + "_server_1")
        self.assertEqual(services["server"]["depends_on"]["db"]["condition"], "service_healthy")
        self.assertEqual(services["frontend"]["depends_on"]["server"]["condition"], "service_healthy")
        self.assertEqual(services["server"]["user"], "1000:1000")
        for name, service in services.items():
            self.assertFalse(set(service) & {"ports", "privileged", "devices", "network_mode", "pid"})
            for mount in service.get("volumes", []):
                self.assertTrue(mount.startswith("${APP_DATA_DIR}/data/"))
                folder = mount.split(":")[0].replace("${APP_DATA_DIR}", str(ROOT / APP))
                self.assertTrue(Path(folder, ".gitkeep").is_file())
            if name != "app_proxy":
                self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")

    def test_entropy_stability_isolation_and_tor(self):
        # Only a synthetic seed is used. No host or owner secrets are read.
        script = '''
        derive_entropy() { printf '%s' "$1" | openssl dgst -sha256 -hmac 'synthetic-seed' | sed 's/^.* //'; }
        app_entropy_identifier="$1"
        APP_HIDDEN_SERVICE="$2"
        source "$3"
        printf '%s\\n' "$APP_MOCHILAB_SPARKYFITNESS_DB_PASSWORD" \
          "$APP_MOCHILAB_SPARKYFITNESS_APP_DB_PASSWORD" \
          "$APP_MOCHILAB_SPARKYFITNESS_API_ENCRYPTION_KEY" \
          "$APP_MOCHILAB_SPARKYFITNESS_BETTER_AUTH_SECRET" \
          "$APP_MOCHILAB_SPARKYFITNESS_TOR_ORIGIN"
        '''
        def exported(seed="app-" + APP + "-seed", onion="not-enabled.onion"):
            return subprocess.check_output(["bash", "-c", script, "test", seed, onion,
                                            str(ROOT / APP / "exports.sh")], text=True).splitlines()
        first = exported()
        self.assertEqual(first, exported())
        self.assertEqual(len(set(first[:4])), 4)
        self.assertTrue(all(len(value) == 64 for value in first[:4]))
        self.assertNotEqual(first[:4], exported("another-app")[:4])
        self.assertEqual(first[4], "")
        self.assertEqual(exported(onion="notyetset.onion")[4], "")
        self.assertEqual(exported(onion="")[4], "")
        self.assertEqual(exported(onion="example.onion")[4], ",http://example.onion")


if __name__ == "__main__":
    unittest.main()
