from concurrent.futures import ThreadPoolExecutor
import io
import os
from threading import Event
import time
import unittest
import wave

from fastapi.testclient import TestClient
import numpy as np

from server import create_app, MODEL_ID, UPLOAD_BYTES

KEY = "a" * 64
AUTH = {"Authorization": f"Bearer {KEY}"}


def wav(frames=1600, rate=16000):
    file = io.BytesIO()
    with wave.open(file, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x00\x00" * frames)
    return file.getvalue()


class Model:
    def __init__(self, cache):
        self.started = Event()
        self.release = Event()
        self.release.set()

    def transcribe(self, waveform):
        assert waveform.dtype == np.float32 and waveform.ndim == 1
        self.started.set()
        if not self.release.wait(8):
            raise TimeoutError
        return "สวัสดี"


class AppTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "APP_PASSWORD", None)
        os.environ["APP_PASSWORD"] = KEY
        self.app = create_app(Model)
        self.client = self.enterContext(TestClient(self.app))

    def send(self, payload=None, fields=None):
        return self.client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("audio.wav", wav() if payload is None else payload, "audio/wav")},
            data={"model": MODEL_ID, "response_format": "json", "language": "th"} if fields is None else fields,
        )

    def test_auth_and_route_surface(self):
        for method, url in (("GET", "/v1/models"), ("POST", "/v1/audio/transcriptions")):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                result = self.client.request(method, url, headers=headers)
                self.assertEqual((result.status_code, result.content), (401, b""))
        for url in ("/", "/docs", "/openapi.json", "/redoc", "/v1/models/"):
            self.assertEqual(self.client.get(url, headers=AUTH).status_code, 404)
        self.assertEqual(self.client.post("/v1/models", headers=AUTH).status_code, 405)
        self.assertEqual(self.client.get("/v1/models", headers=AUTH).json()["data"][0]["id"], MODEL_ID)

    def test_transcription_and_input_limits(self):
        result = self.send()
        self.assertEqual(result.json(), {"text": "สวัสดี"})
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(self.send(fields={"model": MODEL_ID}).status_code, 200)
        self.assertEqual(self.send(payload=wav(rate=8000)).status_code, 400)
        self.assertEqual(self.send(payload=b"invalid").status_code, 400)
        self.assertEqual(self.send(fields={"model": "unknown"}).status_code, 400)
        self.assertEqual(self.send(payload=wav(frames=120 * 16000 + 1)).status_code, 413)
        oversize = self.client.post("/v1/audio/transcriptions", headers={
            **AUTH, "Content-Type": "multipart/form-data; boundary=test", "Content-Length": str(UPLOAD_BYTES + 1)
        })
        self.assertEqual(oversize.status_code, 413)

    def test_streamed_body_limit(self):
        def oversized_chunks():
            yield b"--test\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\n\r\n"
            for _ in range(26):
                yield b"x" * 1_000_000

        res = self.client.post("/v1/audio/transcriptions", headers={
            **AUTH, "Content-Type": "multipart/form-data; boundary=test"
        }, content=oversized_chunks())
        self.assertEqual(res.status_code, 413)

    def test_one_active_one_waiting(self):
        worker = self.app.state.model
        worker.release.clear()
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(self.send)
            try:
                self.assertTrue(worker.started.wait(3))
                second = pool.submit(self.send)
                deadline = time.monotonic() + 3
                while self.app.state.pending < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(self.app.state.pending, 2)
                self.assertFalse(second.done())
                self.assertEqual(self.send().status_code, 429)
            finally:
                worker.release.set()
            self.assertEqual(first.result().status_code, 200)
            self.assertEqual(second.result().status_code, 200)


if __name__ == "__main__":
    unittest.main()
