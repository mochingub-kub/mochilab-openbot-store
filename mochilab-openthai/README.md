# OpenThai Dictation for Umbrel

Runs iApp OpenThai 2.0 FP32 with ONNX Runtime on an amd64 CPU. The app serves a dictation API and has no browser UI.

1. Install **OpenThai Dictation** from the Mochilab community store. Wait for startup. The first start downloads about 2.60 GB of pinned model artifacts. It requires free space for both the archive and its extracted files during installation.
2. In Umbrel, open the app's **App Settings → Default credentials** and copy the password. Use it as the API bearer key. Keep this password private.
3. If you use a reverse proxy, use HTTPS from the clients, keep the origin port private and allow only `GET /v1/models` and `POST /v1/audio/transcriptions`. The server authenticates both endpoints. The package binds TCP 18081 on the host's primary private IPv4 address and falls back to loopback if it cannot find one. Check the selected binding before configuring a proxy.
4. On each OpenBot device, go to **Settings → Voice → Voice server**. Enter your HTTPS base URL ending in `/v1` and the Umbrel password as the API key. Connect, enable Dictation and choose `openthai-2.0-asr-fp32`. This package provides dictation. Keep your existing spoken replies configuration.

The transcription endpoint accepts a multipart form with `file` (16 kHz mono 16-bit PCM WAV), `model`, optional `response_format=json` and optional `language=th`. It returns a JSON object with a `text` string. The app accepts up to 120 seconds of recording and 5 MB per request, with one inference active and one request waiting. It keeps audio in memory and disables access logging.

Stop exposing the API before uninstalling it. Switch OpenBot back to the previous recognizer on each device. Uninstalling deletes Umbrel app data, including the downloaded model. The initial Umbrel password is derived from the device and app ID. Reinstalling the same app does not rotate it.

## Rotate the API key

On the Umbrel host, open a private interactive SSH terminal and run:

```sh
sudo docker exec -it mochilab-openthai_asr_1 python /app/auth.py rotate
```

The command atomically writes a worker-owned key file with mode 0600 and prints the new key once. Save it directly in a password manager and update OpenBot on each device. The old key stops working immediately. Umbrel's Default credentials page continues to show the initial device-derived password. The key file takes precedence; the API and healthcheck use the same source.

## Build and enable a release

Pull requests build the image locally in CI and test the actual runtime with a 4 GiB memory limit. The registry publish job runs on pushes to `main`. Keep the manifest disabled until the reviewed image has been built on `main`. A follow-up PR pins that commit's image digest and enables the manifest after confirming an anonymous GHCR pull.

The first start keeps incomplete downloads across restarts. The app validates the archive and model weights by size and SHA-256 before making a model revision available. Startup grace is 30 minutes to allow the model to finish downloading before the healthcheck marks the container unhealthy.

Regenerate the Linux amd64 Python 3.14 locks from the app directory after updating requirements:

```sh
uv pip compile requirements.txt --python-version 3.14 --python-platform x86_64-manylinux_2_28 --only-binary :all: --generate-hashes --no-header --no-annotate -o requirements.lock
uv pip compile requirements-ci.txt --python-version 3.14 --python-platform x86_64-manylinux_2_28 --only-binary :all: --generate-hashes --no-header --no-annotate -o requirements-ci.lock
```

Model licence, including the required redistribution notice: [OpenMDW-1.1](app/LICENSE.OpenThai). Source: [iApp OpenThai 2.0 ONNX](https://huggingface.co/iapp/OpenThai2.0-ASR-Streaming-ONNX/tree/9f142a4).
