import hashlib
import io
import json
import logging
from pathlib import Path
import shutil
import urllib.request
import wave
import zipfile

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import onnxruntime as ort
from scipy.fft import rfft

from fastthaig2p import G2P, ipa_to_kokoro, normalize, set_data_root

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

TTS_REVISION = "cd812941e8848bffe0dcc9182720ba7cc8ddd13e"
TTS_BASE_URL = f"https://huggingface.co/pythainlp/MakHamTTS/resolve/{TTS_REVISION}/paradee_thai"
G2P_REVISION = "c41fa9006869dd3f7b8fc861de16388e89d8ad0c"
G2P_BASE_URL = f"https://raw.githubusercontent.com/awslabs/FastThaiG2P/{G2P_REVISION}/data"
TTS_ARTIFACTS = {
    "paradee_thai.onnx": (
        f"{TTS_BASE_URL}/paradee_thai.onnx?download=true",
        34_778_468,
        "245dd682d70b9ec72ff480ecd1fa139d1c792100417a97f1f56390c9965a7a1e",
    ),
    "config.json": (
        f"{TTS_BASE_URL}/config.json?download=true",
        2_669,
        "1340bbfedc4871b311c8dedcd5cf85022f80773db120b1cd85883ecb1883ca43",
    ),
    "g2p/dict.txt": (
        f"{G2P_BASE_URL}/dict.txt",
        1_520_330,
        "0e64eeb8b75343c624abbccee03eb69ec6aa53de350763e3be5479779e77a9e3",
    ),
    "g2p/ipa.json": (
        f"{G2P_BASE_URL}/ipa.json",
        3_661_000,
        "affeb3c09478f0d8b1e0f01e9d0174b9c7084b84a1c7547b45b204b2a9dc3971",
    ),
    "g2p/fallback/PhSTrigram.sts": (
        f"{G2P_BASE_URL}/fallback/PhSTrigram.sts",
        1_400_502,
        "b36b0af18d29d16169305c1c76a91cfeb9742e7bc37692ea2235bbf30e916df3",
    ),
    "g2p/fallback/sylform_var.pkl": (
        f"{G2P_BASE_URL}/fallback/sylform_var.pkl",
        249_521,
        "152d1395b9251075d41e96f65fa2e7a50cc319c71bf8308b7c19fe35a083836f",
    ),
    "g2p/fallback/sylrule.lts": (
        f"{G2P_BASE_URL}/fallback/sylrule.lts",
        3_855,
        "58e73cb4eda8c4126a5f9f5ea0aa2a38e8dcc1d6e6d6de324be7d6833d248d1f",
    ),
    "g2p/fallback/sylseg.3g": (
        f"{G2P_BASE_URL}/fallback/sylseg.3g",
        15_795_689,
        "3450baabc27dbb078939eb0729083e60d51c7b13363d3641cc605faaf32b502e",
    ),
    "g2p/fallback/thaisyl.dict": (
        f"{G2P_BASE_URL}/fallback/thaisyl.dict",
        31_777,
        "90928774b54f00ad7f25cfb13703d5f549f4fa65458002cd75387f3616a1e0fb",
    ),
    "g2p/fallback/thdict": (
        f"{G2P_BASE_URL}/fallback/thdict",
        2_402_529,
        "8727c78b62b13b5adeef24d2b1abcd4e7a1cf6be54b7590c32f8acebc2850b76",
    ),
}
TTS_SAMPLE_RATE = 24_000
MAX_TTS_PHONEMES = 400
LOGGER = logging.getLogger("uvicorn.error")


def download_url(url, target, expected_size, expected_digest):
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    offset = target.stat().st_size if target.exists() else 0
    if offset > expected_size:
        target.unlink()
        offset = 0
    if offset < expected_size:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=45) as source:
            if offset and source.status == 206:
                content_range = f"bytes {offset}-{expected_size - 1}/{expected_size}"
                if source.headers.get("Content-Range") != content_range:
                    raise ValueError("Unexpected HTTP Content-Range for the model artifact")
            elif source.status == 200:
                offset = 0
            else:
                raise ValueError("Unexpected HTTP response for the model artifact")
            received = offset
            oversized = False
            with target.open("ab" if offset else "wb") as output:
                while block := source.read(1 << 20):
                    received += len(block)
                    if received > expected_size:
                        oversized = True
                        break
                    output.write(block)
            if oversized:
                target.unlink()
                raise ValueError("Model download exceeded its pinned size")
            if received != expected_size:
                raise ValueError("Incomplete model download retained for resume")
    with target.open("rb") as source:
        valid = hashlib.file_digest(source, "sha256").hexdigest() == expected_digest
    if not valid:
        target.unlink()
        raise ValueError("Model download does not match its pinned SHA-256")


def download(name, target):
    expected_size, expected_digest = ARTIFACTS[name]
    download_url(f"{BASE_URL}/{name}?download=true", target, expected_size, expected_digest)


def install_model(cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    installed = cache / REVISION
    staging = cache / f".{REVISION}.incoming"
    if installed.is_dir():
        return installed
    LOGGER.info("Downloading and verifying pinned OpenThai FP32 model")
    staging.mkdir(mode=0o700, exist_ok=True)
    weight, archive = (staging / name for name in ARTIFACTS)
    download(weight.name, weight)
    download(archive.name, archive)
    with zipfile.ZipFile(archive) as package:
        if set(package.namelist()) != GRAPH_FILES or len(package.infolist()) != len(GRAPH_FILES):
            raise ValueError("Unexpected contents in the pinned model archive")
        for name in sorted(GRAPH_FILES):
            with package.open(name) as source, (staging / name).open("wb") as output:
                shutil.copyfileobj(source, output)
    # Keep both inputs recoverable until the verified directory is visible.
    staging.rename(installed)
    (installed / archive.name).unlink(missing_ok=True)
    LOGGER.info("OpenThai model files verified")
    return installed


def install_tts_model(cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    revision_key = f"paradee-{TTS_REVISION[:7]}-{G2P_REVISION[:7]}"
    installed = cache / revision_key
    staging = cache / f".{revision_key}.incoming"
    if installed.is_dir():
        return installed
    LOGGER.info("Downloading and verifying pinned MakHam Paradee FP32 TTS model")
    staging.mkdir(mode=0o700, exist_ok=True)
    for rel_path, (url, expected_size, expected_digest) in TTS_ARTIFACTS.items():
        download_url(url, staging / rel_path, expected_size, expected_digest)
    staging.rename(installed)
    LOGGER.info("MakHam Paradee TTS model files verified")
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


def split_phoneme_words(words, max_phonemes=MAX_TTS_PHONEMES):
    chunks = []
    current = []
    current_len = 0
    for word in words:
        word = word.strip()
        if not word:
            continue
        while len(word) > max_phonemes:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            cut = word.rfind(".", 0, max_phonemes)
            if cut <= 0:
                cut = max_phonemes
            chunks.append(word[:cut].strip("."))
            word = word[cut:].lstrip(".")
        if not word:
            continue
        added = len(word) if not current else current_len + 1 + len(word)
        if current and added > max_phonemes:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = added
    if current:
        chunks.append(" ".join(current))
    return chunks


def encode_wav_24k(samples):
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(TTS_SAMPLE_RATE)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()


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


class MakHamParadee:
    def __init__(self, cache):
        path = install_tts_model(cache)
        set_data_root(path / "g2p")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        options.add_session_config_entry("session.disable_prepacking", "1")
        self.session = ort.InferenceSession(
            str(path / "paradee_thai.onnx"), options, providers=["CPUExecutionProvider"]
        )
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        self.vocab = config["vocab"]
        self.g2p = G2P(dict_path=path / "g2p" / "dict.txt", ipa_path=path / "g2p" / "ipa.json")
        if {item.name for item in self.session.get_inputs()} != {"input_ids", "speed"}:
            raise RuntimeError("Unexpected MakHam Paradee graph interface")

    def _phoneme_words(self, text):
        clauses = [clause.strip() for clause in str(text).replace("\r", "\n").split("\n") if clause.strip()]
        words = []
        for clause in clauses:
            converted = ipa_to_kokoro(self.g2p.convert(clause))
            filtered = " ".join(
                "".join(ch for ch in token if ch in self.vocab)
                for token in converted.split()
            )
            words.extend(token for token in filtered.split() if token)
        return words

    def synthesize(self, text, speed=1.0):
        words = self._phoneme_words(text)
        chunks = split_phoneme_words(words, MAX_TTS_PHONEMES)
        if not chunks:
            return encode_wav_24k(np.zeros(int(0.05 * TTS_SAMPLE_RATE), dtype="float32"))
        segments = []
        speed_tensor = np.array([float(speed)], dtype="float32")
        for chunk in chunks:
            ids = [0] + [self.vocab[c] for c in chunk if c in self.vocab] + [0]
            if len(ids) <= 2:
                continue
            audio = self.session.run(
                None,
                {
                    "input_ids": np.array([ids], dtype="int64"),
                    "speed": speed_tensor,
                },
            )[0][0].reshape(-1).astype("float32")
            if len(audio):
                segments.append(audio)
        if not segments:
            return encode_wav_24k(np.zeros(int(0.05 * TTS_SAMPLE_RATE), dtype="float32"))
        return encode_wav_24k(np.concatenate(segments))
