# Mochilab Umbrel Store

A community store for [umbrelOS](https://umbrel.com/) with three self-hosted apps for AI teammates, Thai voice, and fitness tracking.

## Apps

| Icon | App | What it does | Status | Package details |
| :---: | --- | --- | --- | --- |
| <img src="https://openbot.run/favicon.ico" width="28" height="28" alt=""> | **OpenBot** | Run the Nightly Labs OpenBot engine on your Umbrel for persistent AI teammates. | Available | [Manifest](mochilab-openbot/umbrel-app.yml) · [Setup](#openbot-setup) · [Safe updates](docs/SAFE-UPDATER.md) |
| <img src="./mochilab-openthai/icon.svg" width="28" height="28" alt=""> | **Siang เสียง** | Dictate in Thai and hear Thai replies in OpenBot. Speech processing runs on your Umbrel. | Available | [Manifest](mochilab-openthai/umbrel-app.yml) · [Setup and rollback](mochilab-openthai/README.md) |
| <img src="https://raw.githubusercontent.com/CodeWithCJ/SparkyFitness/324d48d5c8835d4726d5e22c16fcbe3b9298bc48/docs/src/public/logo.png" width="28" height="28" alt=""> | **SparkyFitness** | Track nutrition, exercise, and body metrics on your Umbrel. | Available | [Manifest](mochilab-sparkyfitness/umbrel-app.yml) · [Setup and backups](docs/SPARKYFITNESS.md) |

## Add the store on umbrelOS

1. Open **App Store** from the Umbrel dock. In the top-right menu (**⋯**), choose **Community App Stores**.
2. Paste `https://github.com/mochingub-kub/mochilab-umbrel-store` and click **Add**.
3. Click **Open** next to **Mochilab Umbrel Store**, then choose an app and click **Install**.

If the new URL is still pending, use the URL of this GitHub repository.

[Umbrel's community store guide](https://umbrel.com/support/apps/how-to-add-a-community-app-store) shows the menu and dialog.

## OpenBot setup

On the umbrelOS host, open a private SSH session and run:

```sh
sudo docker exec -it mochilab-openbot_openbot_1 openbot login
```

Complete the email sign-in privately. The Umbrel launcher opens the [OpenBot Web App](https://openbot.run/app). Sign in with the same account and select your self-hosted server. Configure AI providers in OpenBot.

The package runs the pinned upstream engine image with Umbrel-managed app data and includes AppArmor and Seccomp profiles. Review the [Compose configuration](mochilab-openbot/docker-compose.yml) for the runtime settings.

## Backups and updates

Back up the complete app data before updating. OpenBot backups need the database, workspaces, keyrings, and sessions. A database migration may require restoring matching older app data as well as the older image. Test recovery before relying on a backup.

The release watchers can propose draft PRs. Updates require review and a separate action in Umbrel. See [Safe updates and recovery](docs/SAFE-UPDATER.md) for the OpenBot procedure.

## Support and liability

Mochilab is a personal community project. Packages are provided as is, without warranty, guaranteed updates, compatibility testing, or technical support. You are responsible for your installation, data, security, and backups. To the extent permitted by applicable law, the maintainer accepts no liability for data loss, downtime, security incidents, or other harm arising from use.

Mochilab is an independent packager. Report upstream software issues through the relevant upstream project. See [Security and privacy](SECURITY.md) before reporting a vulnerability or sharing diagnostics. Keep app data, backups, credentials, and unredacted logs private.

## Licences and credits

- **OpenBot** is developed by Nightly Labs under the [PolyForm Noncommercial License 1.0.0](https://github.com/nightly-labs/openbot/blob/main/LICENSE).
- **Siang เสียง** uses iApp's OpenThai model under [OpenMDW 1.1](mochilab-openthai/app/LICENSE.OpenThai), plus PyThaiNLP MakHam Paradee and FastThaiG2P under Apache-2.0, with a BSD-3-Clause fallback component. See the [licence and notices](mochilab-openthai/app/LICENSE.FastThaiG2P). The [icon source](mochilab-openthai/icon.svg) includes the Lucide ISC notice.
- **SparkyFitness** is developed by CodeWithCJ and distributed under its [non-commercial licence](mochilab-sparkyfitness/LICENSE).
