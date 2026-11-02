# Mochilab OpenBot Community App Store

An **unofficial Community App Store package** for running [Nightly Labs OpenBot](https://openbot.run/) on [umbrelOS](https://umbrel.com/).

> **Personal project · no support · use at your own risk.**
> I built this package for my own home server and made the repository public so other umbrelOS users can install it. **This is not a maintained service or an officially supported app.**

**Before installing:** I do not promise updates, fixes, troubleshooting, compatibility testing, or responses to issues and pull requests. I may stop maintaining this repository at any time. You are responsible for your installation, security, and backups. See [Support and liability](#support-and-liability).

## Install on umbrelOS

1. Open **App Store → Community App Stores** in umbrelOS.
2. Add this repository:

   `https://github.com/mochingub-kub/mochilab-openbot-store`

3. Open the **Mochilab** community store and install **OpenBot**.
4. For the first-time engine login, connect to the **umbrelOS host via SSH** (not a Portainer container) and run:

   ```sh
   sudo docker exec -it mochilab-openbot_openbot_1 openbot login
   ```

5. Complete the email / one-time-code sign-in privately. Open the OpenBot app icon in umbrelOS; it redirects to [the official OpenBot Web App](https://openbot.run/app). Sign in to the web client and select your self-hosted server.

**Not one-click or fully offline:** The engine runs on your umbrelOS device, but the app icon opens the upstream web client. Initial engine authentication requires SSH. This package does not install Ollama or configure AI providers.

## What the package does

- Runs the upstream, version-pinned OpenBot Docker engine rather than a modified fork.
- Stores persistent OpenBot data in Umbrel-managed app storage mounted as `/data`.
- Uses the Umbrel app proxy and a minimal launcher redirect. The OpenBot engine itself does not publish a host port.
- Preserves the packaged AppArmor, Seccomp, and `no-new-privileges` settings. It does not mount the host Docker socket or unrelated host directories.

Check the [current app manifest](mochilab-openbot/umbrel-app.yml) and [Docker Compose configuration](mochilab-openbot/docker-compose.yml) for the actual version and permissions. The files in the repository, not a dated README claim, define the package.

## Compatibility and security

This package was made for **one personal umbrelOS setup**. It has **not** been certified or broadly tested on other hardware, operating-system versions, kernels, or configurations.

- Its startup hooks require particular AppArmor / Seccomp support. Installation or startup may fail on other devices.
- OpenBot agents can execute commands and modify files within their container. Container restrictions reduce some risks but **do not guarantee complete isolation**.
- Persistent app data can contain login sessions, encryption-related material, agent files, and other secrets. **Never upload app-data folders, backups, authentication tokens, or unredacted logs to a public issue or repository.**
- Do not expose admin interfaces, SSH, or container management ports to the public internet just to make this app work.
- A reported status of `ready` is not proof that your providers, agents, login, or backups work.

## Backups and updates

**Back up the complete app data and configuration before installing an update**, including workspaces, database, keyrings, and sessions. A copy of `openbot.db` by itself is not a complete recovery backup.

Upstream releases can change the database schema. **Downgrading only a Docker image may not restore a previous working state**; you may need matching older app data as well. Test recovery independently before trusting a backup.

The GitHub release watcher may propose **draft pull requests** for newer upstream versions, but it **does not automatically merge, install, deploy, or back up** your app.

For generic precautions, see [Safe updates and recovery](docs/SAFE-UPDATER.md). That document is a public guide, **not a report about the current state of anyone's server**.

## Support and liability

**There is no support commitment for this community package.**

- I maintain it only when I choose to and have spare time. There is **no guaranteed release schedule or compatibility testing**.
- I am **not offering technical support, installation assistance, debugging, or bug fixes** for other people's servers.
- Issues and pull requests may go unanswered or be closed without a fix. Please do not expect personal troubleshooting.
- **You install and run it entirely at your own risk.** The package is provided **as is, without warranty**. To the extent permitted by applicable law, I accept no liability for data loss, downtime, failed updates, security incidents, incompatibility, or other harm arising from its use.

**Upstream license:** OpenBot's upstream repository currently publishes the [PolyForm Noncommercial License 1.0.0](https://github.com/nightly-labs/openbot/blob/main/LICENSE). Installing through a community store does not grant additional commercial-use rights. Review upstream terms before using OpenBot, especially for business or commercial work.

For sensitive reports, see [Security and privacy](SECURITY.md).

This repository is **not affiliated with or endorsed by Nightly Labs or Umbrel**. Please do not send issues caused by *this community packaging* to Nightly Labs as if it were an officially supported integration. For the upstream OpenBot software itself, use its [official documentation and repository](https://github.com/nightly-labs/openbot).

## Credits

[OpenBot](https://github.com/nightly-labs/openbot) is developed by **Nightly Labs**. This repository only provides an unofficial umbrelOS package. It is **not** the unrelated CopilotKit project with a similar name.
