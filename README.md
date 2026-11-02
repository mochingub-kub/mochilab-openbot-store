# Mochilab OpenBot Community App Store

An unofficial [umbrelOS](https://umbrel.com/) Community App Store package for [Nightly Labs OpenBot](https://openbot.run/).

I made this for my own home server, and I'm sharing it in case it's useful to anyone else running umbrelOS. You can add this repository as a Community App Store instead of building your own Umbrel app package.

> **Personal project · shared as-is.** This is not an official Umbrel or Nightly Labs app store. I made it for my own setup, not as a supported product. **Use it at your own risk.**

## Install on umbrelOS

1. In umbrelOS, go to **App Store → Community App Stores**.
2. Add this GitHub repository as a community store:
   
   `https://github.com/mochingub-kub/mochilab-openbot-store`
3. Open the **Mochilab** store and install **OpenBot**.
4. For the **first-time login**, connect to the **umbrelOS host via SSH** (not a Portainer container) and run:

   ```sh
   sudo docker exec -it mochilab-openbot_openbot_1 openbot login
   ```

5. Complete the email / one-time-code login privately. Open the OpenBot icon in the Umbrel dashboard; it redirects to [OpenBot Web App](https://openbot.run/app). Sign in with the same account and select your self-hosted server.

**Important:** This is **not** a completely one-click or fully offline setup. The OpenBot engine runs on your Umbrel machine, but the dashboard icon opens the upstream web client. First-time authentication still requires SSH. This store does not install Ollama or configure AI providers for you.

## Current package

| Item | Version / configuration |
| --- | --- |
| Community store | `Mochilab` |
| Umbrel app ID | `mochilab-openbot` |
| Umbrel package | `0.58.0-1` |
| OpenBot engine | `ghcr.io/nightly-labs/openbot:0.58.0` |
| Persistent data | Umbrel-managed app data mounted as `/data` |
| OpenBot host port | Not published |
| Launcher | Redirects to `https://openbot.run/app` |

**Status checked November 2, 2026:** `0.58.0-1` was installed and reported `ready` on my own umbrelOS machine. That does **not** mean every agent, provider, feature, or clean installation on other hardware has been tested.

For the actual package version, check [the Umbrel manifest](mochilab-openbot/umbrel-app.yml) and [Docker Compose file](mochilab-openbot/docker-compose.yml). This dated README snapshot may become outdated.

## Compatibility and limitations

- Built and tested for **my personal umbrelOS setup**. Other hardware, OS versions, and configurations are **not guaranteed** to work.
- The package uses Umbrel pre-start hooks and custom **AppArmor / Seccomp** security profiles. Hosts without the expected kernel features and tooling may fail to start it.
- OpenBot may execute commands and modify files within its container. The configured security controls reduce privileges, but they are **not a guarantee of isolation or safety**.
- The container uses only its own app-data mount; it does not publish an OpenBot host port, run privileged, or mount the host Docker socket. Please review the Compose file and hooks before installing.
- The app's persistent data may contain provider sessions, local tools, agent files, encryption-related files, and other sensitive material. Keep backups private.

## Maintenance, support, and responsibility

**I maintain this repository only when I have spare time.** It was created for personal use, and I don't promise regular updates, quick fixes, compatibility testing, or technical support. Upstream OpenBot releases may arrive long before this package is updated, and I may stop maintaining it at any time.

You're welcome to try it and share feedback or open an issue, but **I cannot guarantee a reply or a fix**. Please don't rely on this repository for production-critical use.

**Provided as-is, without warranty.** You are responsible for checking compatibility, securing your server, and backing up your data. I do not assume responsibility for failed installations, downtime, security problems, lost data, or damage resulting from using this unofficial package.

## Backups and updates

- **Back up the entire Umbrel app data and configuration before upgrading**, not just `openbot.db`. This includes workspaces, keyrings, login/session state, and the other files needed to restore it.
- Updates can introduce database migrations. **Downgrading only the Docker image may not be a valid rollback**; restoring matching older app data may be required and can discard newer changes.
- Images are version-pinned rather than using `latest`. The release watcher may prepare **draft pull requests**, but it does not automatically release or deploy updates.
- A `ready` app status is not a substitute for testing login, agents, providers, data preservation, and recovery.

For detailed, **owner-specific** historical update and recovery notes, see [SAFE-UPDATER.md](docs/SAFE-UPDATER.md). Parts of that document describe older releases and should not be treated as universal installation instructions.

## Credits and scope

[OpenBot](https://github.com/nightly-labs/openbot) is developed by **Nightly Labs**. This repository is simply my personal Umbrel packaging; it is **not affiliated with or endorsed by** Nightly Labs or the Umbrel team.

This store is for Nightly Labs OpenBot, **not** the unrelated CopilotKit project with a similar name.

If you give it a try on your own Umbrel machine, I hope it helps. Just keep in mind that this is a hobby project, not a maintained product.
