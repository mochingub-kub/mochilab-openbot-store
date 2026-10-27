# Mochilab OpenBot Community App Store

Community packaging for **Nightly Labs OpenBot** (https://openbot.run) on umbrelOS, maintained for the Mochilab home server. This is **not** CopilotKit/OpenBot and is not an official Umbrel or Nightly Labs store.

## Verified installation (27 October 2026, Asia/Bangkok)

| Item | Last verified state |
| --- | --- |
| Umbrel app ID | `mochilab-openbot` |
| Installed Umbrel package | `0.52.0-1` |
| Running engine image | `ghcr.io/nightly-labs/openbot:0.52.0` |
| App status | `ready`; no pending app operation or reported last operation failure |
| Store update | None pending at the time of inspection |
| Data | Umbrel-managed internal app data, mounted as `/data` in OpenBot |
| Other host mounts / published OpenBot port | None configured |
| Umbrel app proxy authentication | Enabled |
| Provider startup | Codex, Antigravity (AGY), OpenCode reported `available` in post-upgrade logs |
| End-to-end tests | Agent replies, browser/Thai fonts, all agent settings, and full-app restore **not yet verified** |

`ready` and provider initialization are **not** evidence that every agent or workflow works.

OpenBot 0.52.0 migrates legacy Tasks into multiple conversation Threads (database migration 47). Downgrading only the Docker image is **not a valid rollback** after this database migration. Details: [v0.52.0 release](https://github.com/nightly-labs/openbot/releases/tag/v0.52.0), [Tasks-to-Threads change](https://github.com/nightly-labs/openbot/pull/3329).

## Install / connect

1. In Umbrel, go to **App Store > Community App Stores** and add `https://github.com/mochingub-kub/mochilab-openbot-store`.
2. Install OpenBot from the **Mochilab** store.
3. Open the Umbrel app icon. The local, unprivileged redirect opens `https://openbot.run/app` while the OpenBot engine stays on Umbrel.
4. For a first-time engine login only, use an **UmbrelOS host** SSH session (not Portainer's Docker-in-Docker):

   ```sh
   sudo docker exec -it mochilab-openbot_openbot_1 openbot login
   ```

5. Enter the email and one-time code privately in the interactive login, and select the self-hosted server in the web app.

Never put sign-in codes, session material, backup contents, API keys, or agent secrets in GitHub or chat logs.

## Packaging and security boundaries

- OpenBot runs from a **version-pinned** image, not `latest`. It has only its Umbrel-owned `/data` bind mount and no host Docker socket, privileged mode, host port, external disk, or other app mount.
- `docker-compose.yml` keeps the reviewed V3 Codex Workspace-only `mochilab-openbot-workspace` AppArmor label, `seccomp-workspace.json`, and `no-new-privileges`. These settings limit the container; they do **not** make every provider or agent a separate security boundary.
- The `hooks/pre-start` file validates and loads two pinned AppArmor policies, verifies the V3 Seccomp file, and ensures the upstream Electron seccomp artifact is available. **Do not delete** `seccomp-0.49.0.json` merely because its name contains an older version: the hook still uses it. Do not remove the original `mochilab-openbot.apparmor` or `hooks/seccomp-workspace.json` either.
- Umbrel uses the `landing/` directory for a nonprivileged redirect. On update, the pre-start hook refreshes its page from `hooks/openbot-direct.html`. Both are needed.
- Sidebar sections (e.g. ORBIT, COMET, GENESIS) organize agents only; they are **not** filesystem or data-isolation barriers. AGY/OpenCode permissions must not be treated as equivalent to the Codex Workspace-only sandbox.
- OpenBot can run code inside its container. Use the existing private/admin access controls; do not broaden host permissions or publish administrative interfaces as part of an update.

## Data, backups, and cleanup

The complete persistent recovery unit is `/data`: the `openbot.db` database, Agent/Shared/Downloads files, provider sign-ins, encrypted keyring **and keyring-password files**, session state, and local tools. Back up the **whole app configuration and /data**, never only `openbot.db`.

On 27 October 2026 a fresh pre-0.52 stopped-app copy was placed on a separate external HDD and source/destination directory listings and important file sizes were compared. **No full application restore or comprehensive content-checksum validation has been performed**, and backup encryption at rest has not been established. Preserve that pre-upgrade copy while evaluating 0.52 and its irreversible migration.

The external HDD also contains four older OpenBot backup generations. These are **retention candidates, not automatically trash**: confirm independent recovery, age/version, and restoration capability before approving any deletion. Do not remove external snapshots, app workspaces, provider auth, logs, fonts, or caches based on filenames alone. No external-photo library is part of this OpenBot cleanup.

The old `tools/openbot_upgrade_backup.py` is a **0.49-to-0.50 legacy backup helper**. Its preflight intentionally requires the old 0.49 package and will reject the live 0.52 installation. Do **not** present it as the current backup solution. Retain the script and tests for historical recovery evidence until a reviewed replacement exists.

## Update workflow

1. Inspect the actual installed version, upstream Stable release, app-store manifest, current image and security/volume settings.
2. Review release notes for database migrations, permission changes and provider behavior. Retain a rollback strategy for **both** code and data.
3. Stop the app and make a protected independent complete backup. Verify what was actually copied; distinguish file listing/sizes from checksums or an isolated full restore.
4. Propose only the pinned engine image and Umbrel version changes in a reviewed GitHub PR. Review CI and unchanged security artifacts. The automated release watcher creates **Draft PRs only**; it never deploys.
5. After publishing the reviewed store change, wait for Umbrel to refresh the community registry. Then update using Umbrel's app updater; do not manually edit the running app's Compose or downgrade its database.
6. Inspect app version and actual image, logs, provider startup, data preservation, Agent/Thread/UI functionality, and original AppArmor/Seccomp controls. `ready` alone is insufficient.
7. Keep the previous data snapshot until functional checks and a recovery plan pass. Full rollback requires stopping the app and restoring the matching older data/config snapshot; it may discard newer conversations and requires separate approval.

See [Safe update / recovery runbook](docs/SAFE-UPDATER.md) for current checkpoints and limitations.

Official technical reference: https://github.com/nightly-labs/openbot/blob/v0.52.0/docs/docker.md
