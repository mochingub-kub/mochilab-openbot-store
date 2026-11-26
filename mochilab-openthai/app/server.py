import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import math
import os
import wave

import anyio
from fastapi import FastAPI, Request
import numpy as np
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from auth import load_key
from model import MakHamParadee, OpenThai, SAMPLE_RATE

MODEL_ID = "openthai-2.0-asr-fp32"
TTS_MODEL_ID = "makham-paradee-tts-fp32"
TTS_VOICES = ("paradee", "alloy")
UPLOAD_BYTES = 5_000_000
SPEECH_BODY_BYTES = 16_384
MAX_SPEECH_CHARS = 1_000
MAX_VOICE_CHARS = 64
MAX_AUDIO_FRAMES = 120 * SAMPLE_RATE
MAX_PENDING = 4
LOGGER = logging.getLogger("uvicorn.error")


class MemoryFormParser(MultiPartParser):
    # The stream rejects bodies above this limit before a file can roll over.
    spool_max_size = UPLOAD_BYTES


async def bounded_body(request, limit=UPLOAD_BYTES):
    count = 0
    async for block in request.stream():
        count += len(block)
        if count > limit:
            raise BodyTooLarge
        yield block


class BodyTooLarge(MultiPartException):
    def __init__(self):
        super().__init__("Upload too large")


def read_wave(upload):
    try:
        with wave.open(upload.file, "rb") as audio:
            if audio.getframerate() != SAMPLE_RATE or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                return 400, None
            frames = audio.getnframes()
            if frames > MAX_AUDIO_FRAMES:
                return 413, None
            data = audio.readframes(frames)
            if not frames or len(data) != 2 * frames:
                return 400, None
    except (wave.Error, EOFError, OSError):
        return 400, None
    return 200, np.frombuffer(data, dtype="<i2").astype("float32") / np.float32(32768)


def create_app(load_model=OpenThai, load_tts=MakHamParadee):
    @asynccontextmanager
    async def lifespan(app):
        load_key()
        cache = os.environ.get("MODEL_CACHE", "/data/models")
        app.state.model = await anyio.to_thread.run_sync(load_model, cache)
        app.state.tts = await anyio.to_thread.run_sync(load_tts, cache) if load_tts is not None else None
        app.state.worker = asyncio.Semaphore(1)
        app.state.pending = 0
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    def authorized(request):
        try:
            expected = hashlib.sha256(load_key().encode()).digest()
        except (OSError, RuntimeError):
            return False
        value = request.headers.get("authorization", "")
        scheme, _, token = value.partition(" ")
        candidate = hashlib.sha256(token.encode()).digest()
        match = hmac.compare_digest(candidate, expected)
        return scheme.lower() == "bearer" and match

    def deny():
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})

    @app.get("/v1/models")
    async def models(request: Request):
        if not authorized(request):
            return deny()
        data = [{"id": MODEL_ID, "object": "model", "task": "automatic-speech-recognition"}]
        if request.app.state.tts is not None:
            data.append({"id": TTS_MODEL_ID, "object": "model", "task": "text-to-speech"})
        return JSONResponse({"object": "list", "data": data}, headers={"Cache-Control": "no-store"})

    @app.get("/v1/audio/voices")
    @app.get("/v1/audio/speech/voices")
    async def voices(request: Request):
        if not authorized(request):
            return deny()
        return JSONResponse({"voices": list(TTS_VOICES)}, headers={"Cache-Control": "no-store"})

    @app.post("/v1/audio/transcriptions")
    async def transcribe(request: Request):
        if not authorized(request):
            return deny()
        if request.app.state.pending >= MAX_PENDING:
            return Response(status_code=429, headers={"Retry-After": "3"})
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
            return Response(status_code=400)
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal() or len(length) > 12:
                return Response(status_code=400)
            if int(length) > UPLOAD_BYTES:
                return Response(status_code=413)
        request.app.state.pending += 1
        try:
            try:
                async with asyncio.timeout(20):
                    form = await MemoryFormParser(
                        request.headers, bounded_body(request), max_files=1, max_fields=3, max_part_size=1024
                    ).parse()
            except BodyTooLarge:
                return Response(status_code=413)
            except TimeoutError:
                return Response(status_code=408)
            except (ClientDisconnect, MultiPartException, MultipartParseError):
                return Response(status_code=400)
            try:
                upload = form.get("file")
                if (
                    len(form) != len(form.multi_items())
                    or set(form) - {"file", "model", "response_format", "language"}
                    or not isinstance(upload, UploadFile)
                    or form.get("model") != MODEL_ID
                    or form.get("response_format", "json") != "json"
                    or form.get("language", "th") not in ("th", "th-TH")
                ):
                    return Response(status_code=400)
                status, waveform = read_wave(upload)
            finally:
                await form.close()
            if status != 200:
                return Response(status_code=status)
            try:
                async with request.app.state.worker:
                    result = await anyio.to_thread.run_sync(request.app.state.model.transcribe, waveform)
            except Exception:
                LOGGER.error("OpenThai inference failed")
                return Response(status_code=500)
            return JSONResponse({"text": result}, headers={"Cache-Control": "no-store"})
        finally:
            request.app.state.pending -= 1

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        if not authorized(request):
            return deny()
        if request.app.state.tts is None:
            return Response(status_code=404)
        if request.app.state.pending >= MAX_PENDING:
            return Response(status_code=429, headers={"Retry-After": "3"})
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return Response(status_code=400)
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal() or len(length) > 12:
                return Response(status_code=400)
            if int(length) > SPEECH_BODY_BYTES:
                return Response(status_code=413)
        request.app.state.pending += 1
        try:
            chunks = []
            try:
                async with asyncio.timeout(10):
                    async for block in bounded_body(request, SPEECH_BODY_BYTES):
                        chunks.append(block)
            except BodyTooLarge:
                return Response(status_code=413)
            except TimeoutError:
                return Response(status_code=408)
            except ClientDisconnect:
                return Response(status_code=400)
            try:
                payload = json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return Response(status_code=400)
            if not isinstance(payload, dict) or set(payload) - {"model", "input", "voice", "response_format", "speed"}:
                return Response(status_code=400)
            model_name = payload.get("model")
            text = payload.get("input")
            voice = payload.get("voice")
            response_format = payload.get("response_format", "wav")
            raw_speed = payload.get("speed", 1.0)
            if (
                model_name != TTS_MODEL_ID
                or not isinstance(text, str)
                or not text.strip()
                or not isinstance(voice, str)
                or not 1 <= len(voice.strip()) <= MAX_VOICE_CHARS
                or response_format != "wav"
                or isinstance(raw_speed, bool)
                or not isinstance(raw_speed, (int, float))
                or not math.isfinite(raw_speed)
                or not 0.5 <= float(raw_speed) <= 2.0
            ):
                return Response(status_code=400)
            if len(text) > MAX_SPEECH_CHARS:
                return Response(status_code=413)
            try:
                async with request.app.state.worker:
                    wav_bytes = await anyio.to_thread.run_sync(
                        request.app.state.tts.synthesize, text, float(raw_speed)
                    )
            except Exception:
                LOGGER.error("MakHam Paradee synthesis failed")
                return Response(status_code=500)
            return Response(
                content=wav_bytes,
                media_type="audio/wav",
                headers={"Cache-Control": "no-store"},
            )
        finally:
            request.app.state.pending -= 1

    return app


app = create_app()
