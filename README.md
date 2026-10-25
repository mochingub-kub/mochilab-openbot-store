# Mochilab OpenBot Community App Store

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

- OpenBot is pinned to **0.50.0** in this proposed package; this community package is not affiliated with Umbrel or Nightly Labs.
- The upstream OpenBot container has no published host port. Its only filesystem mount is its own persistent Umbrel app data folder (`/data` inside the container).
- A separate, unprivileged static NGINX page is available through the Umbrel app proxy on port **26771**. It instantly redirects the dock click to https://openbot.run/app; it does not host the OpenBot Web UI.
- OpenBot needs its upstream `seccomp.json` profile for the Electron sandbox; an executable `hooks/pre-start` retrieves the exact file from the **v0.50.0** tag and verifies its Git blob SHA. This requires outbound HTTPS, `curl`, and `git` on the Umbrel host.
- No privileged mode, host Docker socket, Cloudflare route, device mount, external HDD, or access to the other Mochilab app folders is configured.
- This is a **development preview**: AI agents can execute commands and change data within their own container. Do not grant additional host mounts.
- Preserve the entire `/data` recovery unit (database, keyring, keyring password, provider sessions) in an **independent backup** before upgrades or removing the app.
- Do not change the image to `latest` or downgrade its database. Verify a compatible backup and restore before upgrading.

## UmbrelOS update packaging note

On umbrelOS 2.0, app updates copy only selected package paths, including `hooks/`. They do **not** automatically copy arbitrary new directories. Package `0.49.0-1` mistakenly stored its AppArmor profile in `security/`, so OpenBot could not start after updating. Package `0.49.0-2` places the verified policy in `hooks/` and the `pre-start` hook loads that exact file. **Host AppArmor loading and OpenBot login still need real-device validation.**

## Dock direct-open behavior (0.49.0-3)

The installed Umbrel dock URL remains local and managed by Umbrel. The static redirect has no credentials or privileged access. Umbrel updater **does not copy** the `landing/` directory on updates. `hooks/pre-start` copies the versioned `hooks/openbot-direct.html` into the app-owned `landing/index.html` atomically when needed. The redirect does **not** restart, re-sign-in, or migrate the OpenBot engine and leaves `/data` untouched; the Umbrel app update itself restarts containers, so plan around active agents.

## Validation status

Manifest YAML, Compose YAML, and hook syntax checked statically. The upstream seccomp Git blob SHA and launcher image digest were checked against upstream sources. **Fresh install, GHCR image pull, sign-in, functional test, persistence across restart, and backup/restore have NOT yet been tested on this Umbrel device.**

Source documentation: https://github.com/nightly-labs/openbot/blob/v0.50.0/docs/docker.md
Umbrel community stores: https://github.com/getumbrel/umbrel-community-app-store


## Prepared 0.50.0 release (not installed until merged/updated)

This proposal changes only the pinned image, manifest version and the verified upstream seccomp download URL. The upstream seccomp Git blob is identical for 0.49.0 and 0.50.0 (6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418), so the old on-disk file name seccomp-0.49.0.json is deliberately reused for compatibility. The AppArmor policy, mounts, CPU/RAM limits and network exposure are unchanged.

The developer's release workflow 40199231815 passed the two Docker image builds, publication and anonymous pull verification. This verifies upstream image availability, not installation on Mochilab.

The local in-server recovery folder is NOT a confirmed independent backup. Before the owner merges and applies this proposal, stop OpenBot while idle, make a consistent separate secure full-/data backup including keyring/password/provider sessions, verify it, and confirm the recovery procedure. Upgrading can migrate the database, so an older image cannot simply be restarted against newer data. See docs/upgrade-0.50.0.md.

**Not fixed:** Codex Workspace only in this Linux Docker container still requires separate bubblewrap/security-policy investigation. Do not enable Full access, privileged, CAP_SYS_ADMIN or unconfined as a shortcut.
