from concurrent.futures import ThreadPoolExecutor
import io
import os
from threading import Event
import time
import unittest
import wave

from fastapi.testclient import TestClient
import numpy as np

from model import encode_wav_24k, TTS_SAMPLE_RATE
from server import create_app, MAX_SPEECH_CHARS, MODEL_ID, SPEECH_BODY_BYTES, TTS_MODEL_ID, TTS_VOICES, UPLOAD_BYTES

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


class SpeechModel:
    def __init__(self, cache):
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.last = None

    def synthesize(self, text, speed=1.0):
        self.last = (text, speed)
        self.started.set()
        if not self.release.wait(8):
            raise TimeoutError
        return encode_wav_24k(np.zeros(2400, dtype="float32"))


class AppTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "APP_PASSWORD", None)
        os.environ["APP_PASSWORD"] = KEY
        self.app = create_app(Model, SpeechModel)
        self.client = self.enterContext(TestClient(self.app))

    def send(self, payload=None, fields=None):
        return self.client.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("audio.wav", wav() if payload is None else payload, "audio/wav")},
            data={"model": MODEL_ID, "response_format": "json", "language": "th"} if fields is None else fields,
        )

    def send_speech(self, body=None):
        payload = {"model": TTS_MODEL_ID, "input": "สวัสดีค่ะ", "voice": "paradee", "response_format": "wav"}
        if body is not None:
            payload = body
        return self.client.post("/v1/audio/speech", headers=AUTH, json=payload)

    def test_auth_and_route_surface(self):
        routes = (
            ("GET", "/v1/models"),
            ("GET", "/v1/audio/voices"),
            ("GET", "/v1/audio/speech/voices"),
            ("POST", "/v1/audio/transcriptions"),
            ("POST", "/v1/audio/speech"),
        )
        for method, url in routes:
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                result = self.client.request(method, url, headers=headers)
                self.assertEqual((result.status_code, result.content), (401, b""))
        for url in ("/", "/docs", "/openapi.json", "/redoc", "/v1/models/", "/v1/audio/voices/"):
            self.assertEqual(self.client.get(url, headers=AUTH).status_code, 404)
        self.assertEqual(self.client.post("/v1/models", headers=AUTH).status_code, 405)
        self.assertEqual(self.client.get("/v1/audio/speech", headers=AUTH).status_code, 405)
        response = self.client.get("/v1/models", headers=AUTH)
        self.assertEqual(
            [(item["id"], item["task"]) for item in response.json()["data"]],
            [
                (MODEL_ID, "automatic-speech-recognition"),
                (TTS_MODEL_ID, "text-to-speech"),
            ],
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        for url in ("/v1/audio/voices", "/v1/audio/speech/voices"):
            voices_res = self.client.get(url, headers=AUTH)
            self.assertEqual(voices_res.status_code, 200)
            self.assertEqual(voices_res.json(), {"voices": list(TTS_VOICES)})
            self.assertEqual(voices_res.headers["cache-control"], "no-store")

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

    def test_speech_and_input_limits(self):
        res = self.send_speech()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "audio/wav")
        self.assertEqual(res.headers["cache-control"], "no-store")
        with wave.open(io.BytesIO(res.content), "rb") as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, TTS_SAMPLE_RATE))
            self.assertEqual(audio.getnframes(), 2400)
        self.assertEqual(self.app.state.tts.last, ("สวัสดีค่ะ", 1.0))

        res_speed = self.send_speech({
            "model": TTS_MODEL_ID,
            "input": "ทดสอบ",
            "voice": "alloy",
            "speed": 1.25,
        })
        self.assertEqual(res_speed.status_code, 200)
        self.assertEqual(self.app.state.tts.last, ("ทดสอบ", 1.25))

        for bad in (
            {"model": "wrong", "input": "สวัสดี", "voice": "paradee"},
            {"model": TTS_MODEL_ID, "input": "   ", "voice": "paradee"},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": ""},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "v" * 65},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "paradee", "response_format": "mp3"},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "paradee", "speed": 0.2},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "paradee", "speed": 2.5},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "paradee", "speed": True},
            {"model": TTS_MODEL_ID, "input": "สวัสดี", "voice": "paradee", "extra": 1},
        ):
            self.assertEqual(self.send_speech(bad).status_code, 400)

        self.assertEqual(
            self.send_speech({"model": TTS_MODEL_ID, "input": "ก" * (MAX_SPEECH_CHARS + 1), "voice": "paradee"}).status_code,
            413,
        )
        oversize = self.client.post(
            "/v1/audio/speech",
            headers={**AUTH, "Content-Type": "application/json", "Content-Length": str(SPEECH_BODY_BYTES + 1)},
            content=b"{}",
        )
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

    def test_shared_semaphore_and_pending_limit(self):
        worker = self.app.state.model
        worker.release.clear()
        with ThreadPoolExecutor(max_workers=5) as pool:
            first = pool.submit(self.send)
            try:
                self.assertTrue(worker.started.wait(3))
                waiting = [pool.submit(self.send_speech) for _ in range(3)]
                deadline = time.monotonic() + 3
                while self.app.state.pending < 4 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(self.app.state.pending, 4)
                self.assertTrue(all(not f.done() for f in waiting))
                self.assertEqual(self.send_speech().status_code, 429)
                self.assertEqual(self.send().status_code, 429)
            finally:
                worker.release.set()
            self.assertEqual(first.result().status_code, 200)
            for item in waiting:
                self.assertEqual(item.result().status_code, 200)


if __name__ == "__main__":
    unittest.main()
