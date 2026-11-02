# OpenBot on umbrelOS — safe updates and recovery

This is a **general public guide** for the unofficial Mochilab OpenBot Community App Store package. It is not a live status report, a supported upgrade tool, or a record of the maintainer's home server.

**Community package only:** There is no warranty, guaranteed maintenance, troubleshooting service, or compatibility promise. Follow the [README](../README.md) before installing.

## Package boundaries

The packaged OpenBot container uses an Umbrel-managed `/data` volume, pinned upstream image, AppArmor and Seccomp profiles, and `no-new-privileges`. It does not need privileged mode, access to the host Docker socket, or additional host folders.

Do not remove `hooks/pre-start`, the AppArmor policy files, `hooks/seccomp-workspace.json`, or the launcher files to simplify installation. The startup hook may also maintain a pinned upstream seccomp artifact with an older version in its filename. Those files are part of the reviewed package and must be evaluated together.

Some providers may behave differently inside this container; a security profile is not a guarantee of complete isolation or provider compatibility.

## Before upgrading

1. Verify your **own** installed version, device compatibility, and package manifest; do not assume README dates describe your server.
2. Read the upstream release and migration notes. Version changes may require a database migration that an image-only downgrade cannot reverse.
3. Identify the complete Umbrel application data and configuration. Back up the **entire** app state to an independent, private location, including database, workspaces, sessions, encryption dependencies, and hidden files.
4. Prefer a consistent stopped-app backup: stop only the affected application after checking that no agent tasks are running. Confirm the backup copies correctly and, where possible, test an isolated restore.
5. Preserve a known-good pre-upgrade backup until actual functionality has been checked. Never overwrite your only recovery copy.

**Security:** An app backup can contain authentication credentials and tokens. Do not upload backups, unredacted logs, session files, or keyrings to GitHub or publish them with a bug report.

## Upgrade review and verification

1. Compare the [manifest](../mochilab-openbot/umbrel-app.yml) and [Compose file](../mochilab-openbot/docker-compose.yml) with the intended upstream version.
2. Ensure data mounts, proxy routing, resource limits, pre-start hook, AppArmor, Seccomp, and `no-new-privileges` did not change without a separate security review.
3. The repository release watcher may prepare a **draft pull request**, but does not install or deploy an upgrade.
4. Perform the upgrade only after reviewing the release and preparing your own backup and recovery plan.
5. Check the installed image and actual app logs. Test sign-in, conversations, relevant agents/providers, and access to existing data. A `ready` status alone is insufficient.
6. Keep the previous backup until you have confidence that data and recovery remain functional.

## Recovery and rollback

If an upgrade causes trouble, determine whether it changed the application image, configuration, or database. A database migration may make an older image incompatible with newer data. Reverting can require **both** a matching older package and an entire matching older app-data backup; doing so may discard conversations or other work created afterward.

Never delete a previous backup simply because the updated app starts. Never attempt a restore against production data without confirming the target, copies, expected data loss, and permissions.

## Legacy helper warning

The checked-in `tools/openbot_upgrade_backup.py` was built for **a specific old 0.49-to-0.50 upgrade** and intentionally rejects other live versions. **It is not a current backup solution and must not be run on a newer production installation.** Existing tests are historical regression tests, not proof of a fully tested restore.

No personal host inventory, backup counts, device paths, or private operational history is required for this public installation guide. For authoritative software releases, consult the [upstream OpenBot repository](https://github.com/nightly-labs/openbot/releases).
