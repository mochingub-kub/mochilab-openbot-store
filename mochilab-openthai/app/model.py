import hashlib
import logging
from pathlib import Path
import shutil
import urllib.request
import zipfile

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import onnxruntime as ort
from scipy.fft import rfft

REVISION = "9f142a4"
BASE_URL = f"https://huggingface.co/iapp/OpenThai2.0-ASR-Streaming-ONNX/resolve/{REVISION}"
ARTIFACTS = {
    "encoder.onnx.data": (2_454_405_120, "a139201333ab89d5e965bc12abb1c534aa285d82e40051c2dda605365c74f18b"),
    "openthai2.0-asr-streaming-fp32.asr.zip": (149_365_631, "d4161d14e1c61c779ae01cf02356a99d2752f7931ce2d04be8098c57270d463f"),
}
GRAPH_FILES = {"encoder.onnx", "decoder_joint.onnx", "tokens.txt"}
SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 20 * SAMPLE_RATE
FRONTEND_WINDOW = np.pad(np.hanning(400).astype("float32"), (56, 56))
LOGGER = logging.getLogger("uvicorn.error")


def download(name, target):
    expected_size, expected_digest = ARTIFACTS[name]
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(f"{BASE_URL}/{name}?download=true", timeout=45) as source, target.open("xb") as output:
        while block := source.read(1 << 20):
            received += len(block)
            if received > expected_size:
                raise ValueError("Model download exceeded its pinned size")
            digest.update(block)
            output.write(block)
    if received != expected_size or digest.hexdigest() != expected_digest:
        raise ValueError("Model download does not match its pinned SHA-256 and size")


def install_model(cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    installed = cache / REVISION
    staging = cache / f".{REVISION}.incoming"
    if staging.exists():
        shutil.rmtree(staging)
    if installed.is_dir():
        return installed
    LOGGER.info("Downloading and verifying pinned OpenThai FP32 model")
    staging.mkdir(mode=0o700)
    try:
        weight, archive = (staging / name for name in ARTIFACTS)
        download(weight.name, weight)
        download(archive.name, archive)
        with zipfile.ZipFile(archive) as package:
            if set(package.namelist()) != GRAPH_FILES or len(package.infolist()) != len(GRAPH_FILES):
                raise ValueError("Unexpected contents in the pinned model archive")
            for name in sorted(GRAPH_FILES):
                with package.open(name) as source, (staging / name).open("xb") as output:
                    shutil.copyfileobj(source, output)
        archive.unlink()
        staging.rename(installed)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    LOGGER.info("OpenThai model files verified")
    return installed


def mel_filterbank():
    fft_hz = np.linspace(0, 8000, 257)
    linear_step = 200 / 3
    log_step = np.log(6.4) / 27
    mel = np.linspace(0, 15 + np.log(8) / log_step, 130)
    hz = mel * linear_step
    hz[mel >= 15] = 1000 * np.exp(log_step * (mel[mel >= 15] - 15))
    widths = np.diff(hz)
    ramps = hz[:, None] - fft_hz
    weights = np.maximum(0, np.minimum(-ramps[:-2] / widths[:-1, None], ramps[2:] / widths[1:, None]))
    return (weights * (2 / (hz[2:] - hz[:-2]))[:, None]).astype("float32")


MEL_FILTERBANK = mel_filterbank()


def log_mel(waveform):
    emphasized = np.empty_like(waveform)
    emphasized[0] = waveform[0]
    emphasized[1:] = waveform[1:] - np.float32(0.97) * waveform[:-1]
    centered = np.pad(emphasized, (256, 256))
    frames = sliding_window_view(centered, 512)[::160][:max(1, len(waveform) // 160)]
    power = np.abs(rfft(frames * FRONTEND_WINDOW, axis=-1)) ** 2
    return np.log(MEL_FILTERBANK @ power.T + np.float32(2**-24))[None, :, :]


def audio_chunks(waveform):
    while len(waveform) > CHUNK_SAMPLES:
        start = CHUNK_SAMPLES - 2 * SAMPLE_RATE
        blocks = waveform[start:CHUNK_SAMPLES].reshape(-1, 320)
        split = start + int(np.argmin(np.mean(blocks**2, axis=1))) * 320 + 160
        yield waveform[:split]
        waveform = waveform[split:]
    yield waveform


class OpenThai:
    def __init__(self, cache):
        path = install_model(cache)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        options.add_session_config_entry("session.disable_prepacking", "1")
        providers = ["CPUExecutionProvider"]
        self.encoder = ort.InferenceSession(str(path / "encoder.onnx"), options, providers=providers)
        self.decoder = ort.InferenceSession(str(path / "decoder_joint.onnx"), options, providers=providers)
        self.tokens = (path / "tokens.txt").read_text(encoding="utf-8").splitlines()
        self.encoder_inputs = [item.name for item in self.encoder.get_inputs()]
        self.decoder_inputs = [item.name for item in self.decoder.get_inputs()]
        self.decoder_integer_types = [
            "int64" if item.type == "tensor(int64)" else "int32"
            for item in self.decoder.get_inputs()[1:3]
        ]
        if len(self.tokens) != 14988 or len(self.encoder_inputs) != 3 or len(self.decoder_inputs) != 5:
            raise RuntimeError("Unexpected OpenThai graph interface")

    def _decode(self, waveform):
        if np.max(np.abs(waveform)) < 1 / 32768:
            return ""
        features = log_mel(waveform)
        inputs = [features, np.array([features.shape[-1]], dtype="int64"), np.array([32], dtype="int64")]
        encoded, *lengths = self.encoder.run(None, dict(zip(self.encoder_inputs, inputs)))
        frame_count = int(lengths[0].reshape(-1)[0]) if lengths else encoded.shape[1]
        states = [np.zeros((2, 1, 640), dtype="float32") for _ in range(2)]
        blank = len(self.tokens)
        last_token = blank
        pieces = []
        length = np.array([1], dtype=self.decoder_integer_types[1])
        for index in range(frame_count):
            frame = encoded[:, index:index + 1, :].transpose(0, 2, 1)
            for _ in range(10):
                token = np.array([[last_token]], dtype=self.decoder_integer_types[0])
                logits, *outputs = self.decoder.run(None, dict(zip(self.decoder_inputs, [frame, token, length, *states])))
                scores = logits.reshape(-1)
                scores[blank] -= 2.5 if len(waveform) < 32000 else 1.0
                prediction = int(scores.argmax())
                if prediction == blank:
                    break
                states = outputs[-2:]
                last_token = prediction
                pieces.append(self.tokens[prediction])
        return "".join(pieces).replace("▁", " ").strip()

    def transcribe(self, waveform):
        return " ".join(text for chunk in audio_chunks(waveform) if (text := self._decode(chunk)))
