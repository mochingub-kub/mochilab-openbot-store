import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import logging
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
from model import OpenThai, SAMPLE_RATE

MODEL_ID = "openthai-2.0-asr-fp32"
UPLOAD_BYTES = 5_000_000
MAX_AUDIO_FRAMES = 120 * SAMPLE_RATE
MAX_PENDING = 2
LOGGER = logging.getLogger("uvicorn.error")


class MemoryFormParser(MultiPartParser):
    # The stream rejects bodies above this limit before a file can roll over.
    spool_max_size = UPLOAD_BYTES


async def bounded_body(request):
    count = 0
    async for block in request.stream():
        count += len(block)
        if count > UPLOAD_BYTES:
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


def create_app(load_model=OpenThai):
    @asynccontextmanager
    async def lifespan(app):
        load_key()
        app.state.model = await anyio.to_thread.run_sync(load_model, os.environ.get("MODEL_CACHE", "/data/models"))
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
        return JSONResponse(
            {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "task": "automatic-speech-recognition"}]},
            headers={"Cache-Control": "no-store"},
        )

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

    return app


app = create_app()
