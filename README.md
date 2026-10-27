# Mochilab OpenBot Community App Store

> **Workspace only repair: V2 ห้ามใช้ deploy production.** Exact hash ของ compose เทียบ repo ใช้ไม่ได้กับไฟล์ runtime ที่ Umbrel ปรับ เช่น container_name ห้าม copy repo compose ทับไฟล์จริง อ่าน [ประกาศ retire V2](docs/workspace-only-v2-retired-th.md) และ [แนวทาง V3 semantic patch](docs/workspace-only-v3-th.md) ก่อนดำเนินการ V3 ยังเป็น DESIGN_ONLY ไม่มีการซ่อม production หรือ Functional Test ผ่านจากเอกสารนี้

Private-use packaging published in a public repository for umbrelOS 2.0. Installs **Nightly Labs OpenBot** from https://openbot.run — NOT CopilotKit/OpenBot.

## Install on Umbrel

1. Open **Umbrel > App Store > ... > Community App Stores > Add**.
2. Paste https://github.com/mochingub-kub/mochilab-openbot-store
3. Open the **Mochilab** store and install **OpenBot**.
4. Open the OpenBot icon on the Umbrel home screen. Its local page **redirects automatically** to the upstream OpenBot Web App at https://openbot.run/app. The OpenBot engine still runs in the self-hosted container.
5. In an **UmbrelOS host** SSH terminal (not Portainer's terminal), run:

```sh
sudo docker exec -it mochilab-openbot_openbot_1 openbot login
```

Enter your email and one-time code **inside that terminal only**. Open https://openbot.run/app using the same account and select your server.

Do not paste one-time codes, API keys, or credentials into issues or chats.

## Packaging and risks

- This reviewed package candidate pins OpenBot **0.50.0** (Umbrel **0.50.0-1**); it is not affiliated with Umbrel or Nightly Labs. **Do not update Production until this Draft PR is approved and merged.**
- The upstream OpenBot container has no published host port. Its only filesystem mount is its own persistent Umbrel app data folder (`/data` inside the container).
- A separate, unprivileged static NGINX page is available through the Umbrel app proxy on port **26771**. It instantly redirects the dock click to https://openbot.run/app; it does not host the OpenBot Web UI.
- OpenBot still needs the upstream Electron sandbox Seccomp profile; the pinned upstream **v0.49.0** artifact is unchanged in v0.50.0 (verified identical Git blob). `hooks/pre-start` also loads the exact reviewed **V3 Codex Workspace-only** AppArmor/Seccomp policies in enforce mode. The hook's original fetch may need outbound HTTPS, `curl`, and `git` on the Umbrel host.
- No privileged mode, host Docker socket, Cloudflare route, device mount, external HDD, or access to the other Mochilab app folders is configured.
- This is a **development preview**: AI agents can execute commands and change data within their own container. Do not grant additional host mounts.
- Preserve the entire `/data` recovery unit (database, keyring, keyring password, provider sessions) in an **independent backup** before upgrades or removing the app.
- Do not change the image to `latest` or downgrade its database. Verify a compatible backup and restore before upgrading.

## UmbrelOS update packaging note

On umbrelOS 2.0, app updates copy only selected package paths, including `hooks/`. They do **not** automatically copy arbitrary new directories. Package `0.49.0-1` mistakenly stored its AppArmor profile in `security/`, so OpenBot could not start after updating. Package `0.49.0-2` places the verified policy in `hooks/` and the `pre-start` hook loads that exact file. **Host AppArmor loading and OpenBot login still need real-device validation.**

## Dock direct-open behavior (0.49.0-3)

The installed Umbrel dock URL remains local and managed by Umbrel. The static redirect has no credentials or privileged access. Umbrel updater **does not copy** the `landing/` directory on updates. `hooks/pre-start` copies the versioned `hooks/openbot-direct.html` into the app-owned `landing/index.html` atomically when needed. The redirect does **not** restart, re-sign-in, or migrate the OpenBot engine and leaves `/data` untouched; the Umbrel app update itself restarts containers, so plan around active agents.

## Updater and validation

See [Safe Updater runbook](docs/SAFE-UPDATER.md). A scheduled GitHub workflow will propose upstream Stable versions as **Draft PRs for review only**, never automatically deploy. This package candidate keeps the exact V3 Workspace-only policies in Umbrel's whitelisted hooks/ folder.

The owner has already verified native V3 Codex workspace writes and denied outside/symlink writes plus a real Workspace-only OpenBot UI file creation on **0.49.0**. Those functional results do not automatically certify **0.50.0**. CI checks the candidate image's published linux/amd64 manifest, the immutable security blobs and packaging. A new stopped independent backup, real update, sign-in, subsequent V3 functional test and full application rollback remain untested for 0.50.0.

Source documentation: https://github.com/nightly-labs/openbot/blob/v0.50.0/docs/docker.md
Umbrel community stores: https://github.com/getumbrel/umbrel-community-app-store
