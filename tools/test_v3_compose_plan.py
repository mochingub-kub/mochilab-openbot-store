import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v3_compose_plan import simulate, Blocked

BASE='''version: "3.7"
services:
  app_proxy:
    container_name: mochilab-openbot_app_proxy_1
    environment:
      APP_HOST: mochilab-openbot_landing_1
      APP_PORT: 8080
  landing:
    container_name: mochilab-openbot_landing_1
    image: nginx
  openbot:
    image: ghcr.io/nightly-labs/openbot:0.49.0
    container_name: mochilab-openbot_openbot_1
    security_opt:
      - seccomp=${APP_DATA_DIR}/seccomp-0.49.0.json # policy
      - "apparmor=mochilab-openbot"
      - no-new-privileges:true
    volumes:
      - ${APP_DATA_DIR}/data:/data
'''

class Cases(unittest.TestCase):
    def check_block(self, s):
        with self.assertRaises(Blocked): simulate(s)
    def test_patched_runtime_compose(self):
        self.assertEqual(len(simulate(BASE)),64)
    def test_unreviewed_runtime_host_path_denied(self):
        self.check_block(BASE.replace('${APP_DATA_DIR}/data:/data','/media/umbrel-data/openbot:/data'))
    def test_umbrel_data_root_short_form_passes(self):
        self.assertEqual(len(simulate(BASE.replace('${APP_DATA_DIR}/data:/data','${APP_DATA_ROOT}:/data'))),64)
    def test_no_changes_to_comments_or_whitespace(self):
        self.assertEqual(len(simulate(BASE.replace('    volumes:', '\n    # preserve original comment\n    volumes:'))),64)
    def test_unpinned_image_rejected(self):
        self.check_block(BASE.replace('ghcr.io/nightly-labs/openbot:0.49.0','evil:latest'))
    def test_duplicate_security_opt_rejected(self):
        self.check_block(BASE.replace('      - no-new-privileges:true', '      - apparmor=mochilab-openbot\n      - no-new-privileges:true'))
    def test_missing_nnp_rejected(self):
        self.check_block(BASE.replace('      - no-new-privileges:true',''))
    def test_missing_container_name_rejected(self):
        self.check_block(BASE.replace('    container_name: mochilab-openbot_landing_1\n',''))
    def test_unknown_service_rejected(self):
        self.check_block(BASE + '  attacker:\n    image: evil\n')
    def test_anchor_alias_rejected(self):
        self.check_block(BASE.replace('    image: nginx','    image: &ref nginx'))
    def test_duplicate_key_rejected(self):
        self.check_block(BASE.replace('    image: nginx','    image: nginx\n    image: other'))
    def test_multiple_documents_rejected(self):
        self.check_block(BASE + '---\nfoo: bar\n')
    def test_external_privileges_rejected(self):
        self.check_block(BASE.replace('    security_opt:', '    privileged: true\n    security_opt:'))
    def test_absent_real_security_opt_rejected(self):
        self.check_block(BASE.replace('apparmor=mochilab-openbot','apparmor=some-other-label'))
    def test_mapping_security_opt_rejected(self):
        self.check_block(BASE.replace('    security_opt:\n      - seccomp=${APP_DATA_DIR}/seccomp-0.49.0.json # policy\n      - "apparmor=mochilab-openbot"\n      - no-new-privileges:true', '    security_opt:\n      apparmor: mochilab-openbot'))


    @staticmethod
    def umbrel_long_volume():
        return """    volumes:
      - type: bind
        source: ${APP_DATA_ROOT}
        target: /data
        read_only: false
        bind:
          create_host_path: false
"""

    def long_compose(self, replacement=None):
        original = "    volumes:\n      - ${APP_DATA_DIR}/data:/data\n"
        longform = self.umbrel_long_volume() if replacement is None else replacement
        assert original in BASE
        return BASE.replace(original, longform)

    def test_umbrel_managed_long_volume_passes(self):
        self.assertEqual(len(simulate(self.long_compose())), 64)

    def test_umbrel_long_volume_source_drift_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "${APP_DATA_ROOT}", "/etc",
        )))

    def test_umbrel_long_volume_type_drift_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "type: bind", "type: volume",
        )))

    def test_umbrel_long_volume_target_drift_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "target: /data", "target: /host",
        )))

    def test_umbrel_long_volume_readonly_drift_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "read_only: false", "read_only: true",
        )))

    def test_umbrel_long_volume_bind_creation_drift_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "create_host_path: false", "create_host_path: true",
        )))

    def test_umbrel_long_volume_extra_option_denied(self):
        self.check_block(self.long_compose(self.umbrel_long_volume().replace(
            "create_host_path: false", "create_host_path: false\n          propagation: shared",
        )))

if __name__=='__main__': unittest.main(verbosity=2)
