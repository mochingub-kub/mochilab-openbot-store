# Mochilab OpenBot Community App Store

Private-use packaging published in a public repository for umbrelOS 2.0. Installs **Nightly Labs OpenBot** from https://openbot.run — NOT CopilotKit/OpenBot.

## Install on Umbrel

1. Open **Umbrel > App Store > ... > Community App Stores > Add**.
2. Paste https://github.com/mochingub-kub/mochilab-openbot-store
3. Open the **Mochilab** store and install **OpenBot**.
4. Open the OpenBot icon on the Umbrel home screen. The icon opens a **local launcher**, not the full OpenBot chat interface.
5. In an **UmbrelOS host** SSH terminal (not Portainer's terminal), run:

```sh
sudo docker exec -it mochilab-openbot_openbot_1 openbot login
```

Enter your email and one-time code **inside that terminal only**. Open https://openbot.run/app using the same account and select your server.

Do not paste one-time codes, API keys, or credentials into issues or chats.

## Packaging and risks

- OpenBot is pinned to **0.49.0**; this community package is not affiliated with Umbrel or Nightly Labs.
- The upstream OpenBot container has no published host port. Its only filesystem mount is its own persistent Umbrel app data folder (`/data` inside the container).
- A separate, unprivileged static NGINX launcher is available through Umbrel app proxy on port **26771**.
- OpenBot needs its upstream `seccomp.json` profile for the Electron sandbox; an executable `hooks/pre-start` retrieves the exact file from the **v0.49.0** tag and verifies its Git blob SHA. This requires outbound HTTPS, `curl`, and `git` on the Umbrel host.
- No privileged mode, host Docker socket, Cloudflare route, device mount, external HDD, or access to the other Mochilab app folders is configured.
- This is a **development preview**: AI agents can execute commands and change data within their own container. Do not grant additional host mounts.
- Preserve the entire `/data` recovery unit (database, keyring, keyring password, provider sessions) in an **independent backup** before upgrades or removing the app.
- Do not change the image to `latest` or downgrade its database. Verify a compatible backup and restore before upgrading.

## Validation status

Manifest YAML, Compose YAML, and hook syntax checked statically. The upstream seccomp Git blob SHA and launcher image digest were checked against upstream sources. **Fresh install, GHCR image pull, sign-in, functional test, persistence across restart, and backup/restore have NOT yet been tested on this Umbrel device.**

Source documentation: https://github.com/nightly-labs/openbot/blob/v0.49.0/docs/docker.md
Umbrel community stores: https://github.com/getumbrel/umbrel-community-app-store
