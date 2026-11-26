import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from fastapi.testclient import TestClient

import auth
import model
from server import create_app


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class ModelInstallTest(unittest.TestCase):
    def setUp(self):
        self.cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.weight = b"sample weights"
        self.archive_name = "openthai2.0-asr-streaming-fp32.asr.zip"

    def fixtures(self, names=model.GRAPH_FILES):
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as out:
            for name in sorted(names):
                out.writestr(name, name.encode())
        artifacts = {"encoder.onnx.data": self.weight, self.archive_name: package.getvalue()}
        lookup = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in artifacts.items()}
        self.enterContext(patch.object(model, "ARTIFACTS", lookup))
        return artifacts

    def mock_downloads(self, artifacts):
        def fetch(request, timeout):
            data = artifacts[request.full_url.split("/")[-1].split("?")[0]]
            requested = request.get_header("Range")
            if not requested:
                return Response(data)
            offset = int(requested.removeprefix("bytes=").removesuffix("-"))
            return Response(data[offset:], 206, {"Content-Range": f"bytes {offset}-{len(data)-1}/{len(data)}"})
        return self.enterContext(patch.object(model.urllib.request, "urlopen", side_effect=fetch))

    def test_hash_mismatch_removes_bad_artifact(self):
        assets = self.fixtures()
        self.mock_downloads({**assets, "encoder.onnx.data": b"!" * len(self.weight)})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            model.install_model(self.cache)
        self.assertFalse((self.cache / model.REVISION).exists())
        self.assertFalse((self.cache / f".{model.REVISION}.incoming" / "encoder.onnx.data").exists())

    def test_unexpected_zip_entry_blocks_install(self):
        self.mock_downloads(self.fixtures(model.GRAPH_FILES | {"../unexpected"}))
        with self.assertRaisesRegex(ValueError, "Unexpected contents"):
            model.install_model(self.cache)
        self.assertFalse((self.cache / model.REVISION).exists())
        self.assertFalse((self.cache / "unexpected").exists())

    def test_interrupted_response_resumes_on_next_start(self):
        assets = self.fixtures()
        get = self.mock_downloads(assets)
        good_response = get.side_effect
        get.side_effect = lambda request, timeout: Response(self.weight[:6])
        with self.assertRaisesRegex(ValueError, "retained for resume"):
            model.install_model(self.cache)
        incomplete = self.cache / f".{model.REVISION}.incoming" / "encoder.onnx.data"
        self.assertEqual(incomplete.read_bytes(), self.weight[:6])
        get.reset_mock()
        get.side_effect = good_response
        installed = model.install_model(self.cache)
        self.assertEqual(get.call_args_list[0].args[0].get_header("Range"), "bytes=6-")
        self.assertEqual((installed / "encoder.onnx.data").read_bytes(), self.weight)
        self.assertEqual({p.name for p in installed.iterdir()}, model.GRAPH_FILES | {"encoder.onnx.data"})
        self.assertFalse(incomplete.parent.exists())

    def test_range_fallback_replaces_partial_on_full_response(self):
        assets = self.fixtures()
        stage = self.cache / f".{model.REVISION}.incoming"
        stage.mkdir()
        (stage / "encoder.onnx.data").write_bytes(b"wrong")
        self.enterContext(patch.object(model.urllib.request, "urlopen", side_effect=lambda request, timeout: Response(
            assets[request.full_url.split("/")[-1].split("?")[0]]
        )))
        self.assertEqual((model.install_model(self.cache) / "encoder.onnx.data").read_bytes(), self.weight)


class AuthStartupTest(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.key_path = directory / "api-key"
        self.enterContext(patch.object(auth, "KEY_PATH", self.key_path))

    def test_invalid_umbrel_key_fails_before_model_load(self):
        engine = Mock()
        for key in ("", "z" * 64, "a" * 63):
            with patch.dict(os.environ, {"APP_PASSWORD": key}):
                with self.assertRaisesRegex(RuntimeError, "64-character"):
                    with TestClient(create_app(engine)):
                        self.fail("Invalid key started the service")
        engine.assert_not_called()

    def test_override_requires_mode_length_and_printable_ascii(self):
        for value, mode, message in [
            ("s" * 32, 0o644, "mode 0600"),
            ("short", 0o600, "32–256"),
            ("s" * 31 + " ", 0o600, "without spaces"),
            ("s" * 257, 0o600, "32–256"),
        ]:
            with self.subTest(mode=mode, message=message):
                self.key_path.write_text(value)
                self.key_path.chmod(mode)
                with patch.dict(os.environ, {"APP_PASSWORD": "a" * 64}):
                    with self.assertRaisesRegex(RuntimeError, message):
                        auth.load_key()

    def test_rotation_replaces_umbrel_key_without_restart(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "a" * 64}):
            with TestClient(create_app(Mock())) as client:
                def check(key):
                    return client.get("/v1/models", headers={"Authorization": "Bearer " + key}).status_code
                self.assertEqual(check("a" * 64), 200)
                first = auth.rotate_key()
                self.assertEqual(self.key_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(auth.load_key(), first)
                self.assertEqual(check("a" * 64), 401)
                self.assertEqual(check(first), 200)
                second = auth.rotate_key()
                self.assertNotEqual(first, second)
                self.assertEqual(check(first), 401)
                self.assertEqual(check(second), 200)
