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

    def test_existing_asr_cache_skips_redownload_during_tts_upgrade(self):
        existing_asr = self.cache / model.REVISION
        existing_asr.mkdir()
        for name in model.GRAPH_FILES | {"encoder.onnx.data"}:
            (existing_asr / name).write_bytes(b"cached")
        tts_payloads = {
            "paradee_thai.onnx": b"onnx-graph",
            "config.json": b'{"vocab":{"a":1}}',
            "g2p/dict.txt": b"word\n",
            "g2p/ipa.json": b"{}",
        }
        tts_lookup = {
            rel: (f"https://example.test/{rel}", len(data), hashlib.sha256(data).hexdigest())
            for rel, data in tts_payloads.items()
        }
        self.enterContext(patch.object(model, "TTS_ARTIFACTS", tts_lookup))
        fetched_urls = []

        def fetch(request, timeout):
            fetched_urls.append(request.full_url)
            rel = request.full_url.removeprefix("https://example.test/")
            return Response(tts_payloads[rel])

        self.enterContext(patch.object(model.urllib.request, "urlopen", side_effect=fetch))
        self.assertEqual(model.install_model(self.cache), existing_asr)
        self.assertEqual(fetched_urls, [])
        installed_tts = model.install_tts_model(self.cache)
        self.assertEqual(len(fetched_urls), len(tts_payloads))
        self.assertTrue((installed_tts / "paradee_thai.onnx").is_file())
        self.assertTrue((installed_tts / "g2p" / "dict.txt").is_file())

    def test_split_phoneme_words_enforces_400_phoneme_limit(self):
        words = ["sa↓.wat↓.diː→"] * 45
        chunks = model.split_phoneme_words(words, max_phonemes=400)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 400 for chunk in chunks))
        long_single_word = ".".join(["kaː→"] * 120)
        long_chunks = model.split_phoneme_words([long_single_word], max_phonemes=400)
        self.assertGreater(len(long_chunks), 1)
        self.assertTrue(all(len(chunk) <= 400 for chunk in long_chunks))


class AuthStartupTest(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.key_path = directory / "api-key"
        self.enterContext(patch.object(auth, "KEY_PATH", self.key_path))

    def test_invalid_umbrel_key_fails_before_model_load(self):
        engine = Mock()
        tts_engine = Mock()
        for key in ("", "z" * 64, "a" * 63):
            with patch.dict(os.environ, {"APP_PASSWORD": key}):
                with self.assertRaisesRegex(RuntimeError, "64-character"):
                    with TestClient(create_app(engine, tts_engine)):
                        self.fail("Invalid key started the service")
        engine.assert_not_called()
        tts_engine.assert_not_called()

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
            with TestClient(create_app(Mock(), Mock())) as client:
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
