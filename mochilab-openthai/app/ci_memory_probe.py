"""Run the public Thai smoke test against the constrained CI container."""
import csv
import io
import os
import re
import subprocess
import tarfile
import time
import unicodedata
import urllib.request
import wave

import httpx2 as httpx
import numpy as np
from scipy.io import wavfile

DATASET = "https://huggingface.co/datasets/google/fleurs/resolve/70bb2e84b976b7e960aa89f1c648e09c59f894dd/data/th_th"
FILENAME = "10817866832102011221.wav"
MODEL_ID = "openthai-2.0-asr-fp32"
CAP_GIB = 4


def get_clip():
    with urllib.request.urlopen(DATASET + "/test.tsv?download=true", timeout=60) as source:
        reference = next(row[3] for row in csv.reader(io.TextIOWrapper(source), delimiter="\t") if row[1] == FILENAME)
    with urllib.request.urlopen(DATASET + "/audio/test.tar.gz?download=true", timeout=60) as source:
        with tarfile.open(fileobj=source, mode="r|gz") as archive:
            member = next(item for item in archive if item.name.endswith("/" + FILENAME))
            rate, samples = wavfile.read(io.BytesIO(archive.extractfile(member).read()))
    assert rate == 16000 and samples.ndim == 1
    if samples.dtype.kind == "f":
        samples = np.rint(np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2")
    elif samples.dtype.itemsize != 2:
        samples = (samples.astype("float64") / 2**(samples.dtype.itemsize * 8 - 16)).astype("<i2")
    return samples.astype("<i2"), reference


def pcm_wave(samples):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(samples.tobytes())
    return output.getvalue()


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold()
                   if not (c.isspace() or unicodedata.category(c).startswith("P")))


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    container = os.environ["ASR_CI_CONTAINER"]
    cap = int(docker("inspect", "-f", "{{.HostConfig.Memory}}", container))
    assert cap == CAP_GIB * 1024**3
    address = docker("port", container, "8080/tcp")
    headers = {"Authorization": "Bearer " + os.environ["APP_PASSWORD"]}
    with httpx.Client(base_url=f"http://{address}", timeout=150, trust_env=False) as client:
        deadline = time.monotonic() + 720
        while time.monotonic() < deadline:
            if docker("inspect", "-f", "{{.State.Running}}", container) != "true":
                raise RuntimeError("OpenThai container exited during model initialization")
            try:
                if client.get("/v1/models", headers=headers, timeout=3).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(4)
        else:
            raise TimeoutError("Container did not become ready")
        clip, reference = get_clip()

        def send(samples):
            return client.post(
                "/v1/audio/transcriptions",
                headers=headers,
                files={"file": ("audio.wav", pcm_wave(samples), "audio/wav")},
                data={"model": MODEL_ID, "language": "th", "response_format": "json"},
            )

        assert normalize(send(clip).raise_for_status().json()["text"]) == normalize(reference)
        block = np.concatenate((clip, np.zeros(8000, dtype="<i2")))
        long_clip = np.resize(block, 120 * 16000)
        started = time.monotonic()
        result = send(long_clip).raise_for_status().json()["text"]
        elapsed = time.monotonic() - started
        assert len(result) > len(reference) * 5, "The full clip did not yield enough transcription"
    status = docker("exec", container, "cat", "/proc/1/status")
    peak = int(re.search(r"^VmHWM:\s+(\d+)\s+kB", status, re.M).group(1))
    assert peak * 1024 < cap
    cgroup_peak = int(docker("exec", container, "cat", "/sys/fs/cgroup/memory.peak"))
    print(f"120S_RESULT cap={CAP_GIB:.1f}GiB process_peak={peak / 1024**2:.2f}GiB "
          f"cgroup_peak={cgroup_peak / 1024**3:.2f}GiB wall={elapsed:.2f}s short_clip=exact")


if __name__ == "__main__":
    main()
