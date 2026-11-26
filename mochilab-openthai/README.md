# Siang เสียง for Umbrel

Runs iApp OpenThai 2.0 FP32 (ASR) and PyThaiNLP MakHam Paradee FP32 + FastThaiG2P (TTS) with ONNX Runtime on an amd64 CPU. Use the OpenAI-compatible Voice server API for Thai dictation and spoken replies in OpenBot. The app processes voice locally on your Umbrel. Existing OpenThai Dictation installations receive the Siang name through a normal store update.

1. Install or update **Siang เสียง** from the Mochilab community store. Wait for startup. The first start downloads about 2.60 GB of pinned ASR model artifacts and about 57 MB of pinned TTS and G2P artifacts into `/data/models`. Updating the app reuses the existing verified `/data/models/9f142a4` ASR directory without redownloading the 2.60 GB weights.
2. In Umbrel, open the app's **App Settings → Default credentials** and copy the password. Use it as the API bearer key. Keep this password private.
3. If you use a reverse proxy, use HTTPS from the clients, keep the origin port private and allow only `GET /v1/models`, `GET /v1/audio/voices`, `GET /v1/audio/speech/voices`, `POST /v1/audio/transcriptions` and `POST /v1/audio/speech`. The server authenticates all endpoints.
4. On each OpenBot device, go to **Settings → Voice → Voice server**. Enter your HTTPS base URL ending in `/v1` and the Umbrel password as the API key. Connect, enable **Dictation** (`openthai-2.0-asr-fp32`) and enable **Spoken replies** (`makham-paradee-tts-fp32`, voice `paradee`).

- **Dictation (`POST /v1/audio/transcriptions`):** Accepts a multipart form with `file` (16 kHz mono 16-bit PCM WAV), `model`, optional `response_format=json` and optional `language=th`. Returns `{"text": "..."}`. Accepts up to 120 seconds of recording and 5 MB per request.
- **Spoken replies (`POST /v1/audio/speech`):** Accepts JSON `{"model": "makham-paradee-tts-fp32", "input": "...", "voice": "paradee", "response_format": "wav", "speed": 1.0}` (up to 1,000 characters per request), splits text into chunks of at most 400 phonemes, and returns a 24 kHz mono 16-bit PCM WAV response.
- **Concurrency & privacy:** Both endpoints share a single active CPU worker semaphore with up to 4 requests in flight (1 active, 3 queued). Audio, transcripts, and input text are processed in memory and never logged or written to disk.

Stop exposing the API before uninstalling it. Switch OpenBot back to the previous recognizer and speech engine on each device. Uninstalling deletes Umbrel app data, including the downloaded models. The initial Umbrel password is derived from the device and app ID. Reinstalling the same app does not rotate it.

## Cloudflare policy

The Cloudflare WAF for `asr.mochingub.com` allows exactly five method and path pairs:

- `GET /v1/models`
- `GET /v1/audio/voices`
- `GET /v1/audio/speech/voices`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`

The host-wide rate limit is 20 requests per 10 seconds per source IP and Cloudflare location, with a 10-second block.

## Roll back an app release and keep the data

1. In a rollback PR, restore the previous known-good image pin in Compose. Keep the app ID and data mount in place. To roll back from 0.2.0 to the ASR-only image, use the pin from [the 0.1.0 Compose file](https://github.com/mochingub-kub/mochilab-openbot-store/blob/db18a6f2885ba1b2c4181c5ca3d5d77e5130f985/mochilab-openthai/docker-compose.yml#L3).
2. Give the rollback release a new app version so Umbrel offers **Update**. After merge, refresh the community store and apply **Update** to Siang เสียง. Use the update in place. Uninstalling deletes the app data.
3. Wait for the app to start, then test the voice features supported by the restored image. The models and any rotated key stay in the existing app data directory.

## Rotate the API key

On the Umbrel host, open a private interactive SSH terminal and run:

```sh
sudo docker exec -it mochilab-openthai_asr_1 python /app/auth.py rotate
```

The command atomically writes a worker-owned key file with mode 0600 and prints the new key once. Save it directly in a password manager and update OpenBot on each device. The old key stops working immediately. Umbrel's Default credentials page continues to show the initial device-derived password. The key file takes precedence; the API and healthcheck use the same source.

## Build and enable a release

Pull requests build the image locally in CI and test speech recognition and synthesis together in a container with a 4 GiB memory limit. Image source changes merged to `main` trigger the registry publish job.

For an installed app, keep the current `umbrel-app.yml` and Compose image pin in place while staging the update. Keep the app enabled and do not set `disabled: true`. After CI publishes the image from `main`, verify that it pulls anonymously from GHCR. In one release PR, pin the verified digest in Compose and update the manifest version and release notes.

The first start keeps incomplete downloads across restarts. The app validates the archive, G2P files, and model weights by size and SHA-256 before making a model revision available. Startup grace is 30 minutes to allow the models to finish downloading before the healthcheck marks the container unhealthy.

Regenerate the Linux amd64 Python 3.14 locks from the app directory after updating requirements:

```sh
uv pip compile requirements.txt --python-version 3.14 --python-platform x86_64-manylinux_2_28 --only-binary :all: --generate-hashes --no-header --no-annotate -o requirements.lock
uv pip compile requirements-ci.txt --python-version 3.14 --python-platform x86_64-manylinux_2_28 --only-binary :all: --generate-hashes --no-header --no-annotate -o requirements-ci.lock
```

Model and G2P licences:
- OpenThai 2.0 ASR: [OpenMDW-1.1](app/LICENSE.OpenThai) ([iApp OpenThai 2.0 ONNX](https://huggingface.co/iapp/OpenThai2.0-ASR-Streaming-ONNX/tree/9f142a4))
- MakHam Paradee TTS & FastThaiG2P: [Apache-2.0 & BSD-3-Clause](app/LICENSE.FastThaiG2P) ([PyThaiNLP MakHamTTS](https://huggingface.co/pythainlp/MakHamTTS/tree/cd81294) · [AWS FastThaiG2P](https://github.com/awslabs/FastThaiG2P/tree/c41fa90))
