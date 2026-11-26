# OpenThai Dictation for Umbrel

Runs iApp OpenThai 2.0 FP32 with ONNX Runtime on an amd64 CPU. The app serves a dictation API and has no browser UI.

1. Install **OpenThai Dictation** from the Mochilab community store. Wait for startup. The first start downloads about 2.60 GB of pinned model artifacts. It requires free space for both the archive and its extracted files during installation.
2. In Umbrel, open the app's **App Settings → Default credentials** and copy the password. Use it as the API bearer key. Keep this password private.
3. If you use a reverse proxy, use HTTPS from the clients, keep the origin port private and allow only `GET /v1/models` and `POST /v1/audio/transcriptions`. The server authenticates both endpoints. The package binds TCP 18081 on the host's primary private IPv4 address and falls back to loopback if it cannot find one. Check the selected binding before configuring a proxy.
4. On each OpenBot device, go to **Settings → Voice → Voice server**. Enter your HTTPS base URL ending in `/v1` and the Umbrel password as the API key. Connect, enable Dictation and choose `openthai-2.0-asr-fp32`. This package provides dictation. Keep your existing spoken replies configuration.

The transcription endpoint accepts a multipart form with `file` (16 kHz mono 16-bit PCM WAV), `model`, optional `response_format=json` and optional `language=th`. It returns a JSON object with a `text` string. The app accepts up to 120 seconds of recording and 25 MB per request, with one inference active and one request waiting. It keeps audio in memory and disables access logging.

Stop exposing the API before uninstalling it. Switch OpenBot back to the previous recognizer on each device. Uninstalling deletes Umbrel app data, including the downloaded model. The Umbrel password is derived from the device and app ID, so reinstalling the same app does not rotate it.

Model licence, including the required redistribution notice: [OpenMDW-1.1](app/LICENSE.OpenThai). Source: [iApp OpenThai 2.0 ONNX](https://huggingface.co/iapp/OpenThai2.0-ASR-Streaming-ONNX/tree/9f142a4).
