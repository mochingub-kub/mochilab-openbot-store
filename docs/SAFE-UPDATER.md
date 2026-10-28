# Mochilab OpenBot — safe updates, recovery, and cleanup

**Current live baseline (inspected 27 October 2026, Asia/Bangkok):** Umbrel package `0.52.0-1`, upstream `ghcr.io/nightly-labs/openbot:0.52.0`, application `ready` and no pending update. The prior 0.49/0.50 release-candidate instructions in this document are historical and do **not** represent the running system.

This is a runbook for the **UmbrelOS host** and its managed `mochilab-openbot` app, not Portainer's independent Docker environment. Do not copy old host commands blindly into a container or a Mac.

## What the running package keeps

- App proxy for an unprivileged landing-page redirect; no OpenBot host port published.
- Only the app-owned `/data` persistent bind mount; no extra host paths, external HDD mount, Docker socket or privileged container setting.
- V3 Codex Workspace-only AppArmor (`mochilab-openbot-workspace`) + V3 Seccomp (`seccomp-workspace.json`) + `no-new-privileges`. `hooks/pre-start` checks pinned hashes and loads the profiles.
- The pinned upstream Electron artifact `seccomp-0.49.0.json` and original `mochilab-openbot.apparmor` remain referenced by that hook. **Their older names do not mean they are unused.**
- `hooks/openbot-direct.html` and `landing/index.html` implement the Umbrel dock redirect. Do not delete them.
- Sections in the OpenBot sidebar are organizational, not access-control boundaries.

Confirm these invariants from fresh Umbrel app details, Compose, hook, and logs before each update. Do not assume they will remain true forever.

## Backup/recovery evidence (accurate scope)

The pre-0.52 backup was made with OpenBot **stopped** on 27 October 2026 by copying the complete Umbrel app tree to a physically separate external HDD. The copied app root, `data`, configuration directory, workspaces, keyring and other important directory **listings and file sizes** matched the source at that time. The pre-0.52 copy contains the database and encryption dependencies. It is still **not** an isolated full-app restore test, cryptographic content verification, or proof of backup encryption.

The external HDD currently holds five OpenBot snapshot generations: two earlier V3-era sets, one pre-0.50 set, one pre-0.51.1 set, and the latest pre-0.52 set. Their directory presence does not establish full restore capability. The pre-0.52 snapshot is the important rollback checkpoint for the Tasks-to-Threads migration. Preserve it until an independent restore plan is verified.

The old `tools/openbot_upgrade_backup.py` validates the **exact historical 0.49.0-3 manifest and 0.49.0 image** and has no approved 0.52 backup mode. A preflight against current 0.52 is expected to refuse; do **not** bypass those guards or claim the helper works for present production. Its old `--rehearse` is a file-copy check for its legacy snapshot format, never a full app restore.

### Minimal safe backup checkpoint (conceptual; not a one-line command)

1. Inspect `mochilab-openbot` current version, active operations, data location, dependency list, external target and available space.
2. Check that no agent jobs or app operations are active. Stop **only OpenBot** using its Umbrel app controls; confirm `stopped`.
3. Copy the complete app directory, **including hidden `/data` content**, to an independent, access-restricted location. Do not exclude keyrings, keyring password files, OAuth/provider sessions, or Agent workspaces.
4. Compare source and destination and, for a verified backup claim, use appropriate checksum/integrity validation. Keep the backup private: it contains sign-in sessions and other secrets.
5. Restart OpenBot; confirm it is `ready`, then check login and Agent functionality separately. An isolated restore rehearsal is needed before claiming recoverability.
6. Record the date, source app version, backup type, validation actually done, and restore-test status. Do not publish backup contents or secret values.

## Current backup helper: staged, not running on production

The new tool is `tools/openbot_backup_current.py`. It is a reviewed proposal, not a scheduled job or a deployed host service. Do not use `tools/openbot_upgrade_backup.py` for the current 0.52 installation: that file is intentionally pinned to the legacy 0.49 state.

- **Preflight only (no writes):** `sudo python3 tools/openbot_backup_current.py --preflight` on the **UmbrelOS host**, from a reviewed local checkout. It checks the known app data path, configuration/version, pinned security hashes, complete important data files, HDD mount, distinct physical disk, filesystem, backup space, and required tools. Any unexpected layout blocks execution. Do not assume this host-specific script works on another Umbrel setup.
- **List snapshots (no writes):** `sudo python3 tools/openbot_backup_current.py --inventory`. This lists candidate backup directory names without inspecting secret values.
- **Create only after an authorized maintenance stop:** Stop *only OpenBot* using Umbrel's app controls, verify it is stopped, then run `sudo python3 tools/openbot_backup_current.py --backup` from the reviewed checkout. It requires typing `BACKUP-OPENBOT`, checks Umbrel and Docker stopped state again, and copies the **entire app tree**, including hidden data, settings, keyrings and agents. It compares the source and copied files and hashes their contents. If a check fails, its newly created temporary staging directory is cleaned up (an abrupt power loss may leave a staging folder). The script never deletes existing snapshots or overwrites them. OpenBot remains stopped; start it through Umbrel afterward and test login and Agent replies.
- **Verify:** `sudo python3 tools/openbot_backup_current.py --verify /home/umbrel/umbrel/external/mochi-external/SNAPSHOT_NAME`. Requires the *exact* snapshot directory created by this helper, checks a private manifest and every file hash.
- **Disposable file restore rehearsal:** `sudo python3 tools/openbot_backup_current.py --rehearse /home/umbrel/umbrel/external/mochi-external/SNAPSHOT_NAME`. Copies the snapshot into a private temporary directory on that same external HDD, checks every copied file, and runs SQLite `PRAGMA quick_check` against the **disposable copy**. The temporary restore directory is removed afterwards. This is **file-level recovery evidence only**; it cannot prove that an isolated OpenBot instance can authenticate, decrypt secrets, and load all agents.

**Hard limits:** No scheduling, automatic snapshot creation on update detection, old-backup pruning, Docker update, host config mutation, or production restore is implemented. No existing HDD snapshot has been deleted. For actual implementation, obtain the exact reviewed GitHub commit and check its SHA-256 before using any downloaded script as root; never pipe a remote script directly to `sudo`. No tokens, password files, manifest contents, or backup data belong in GitHub.

## One retained backup: rotation policy (not yet automated)

The owner's target is **one verified current-version backup after each completed rotation**, not an unlimited history. This is a retention policy, **not an implemented updater or cleanup script**. The GitHub release-watch workflow only proposes Draft PRs; it does not back up production. Do not run the legacy 0.49 helper against 0.52.

1. **Normal state:** retain one full, access-restricted OpenBot app-tree backup on the independent external HDD, including the database, hidden `/data` files, keyrings and keyring-password, Agents, and matching app configuration. Record source version and integrity/restore evidence. The live app's data is not itself a backup.
2. **Before an approved production upgrade:** inspect whether that copy is recent, complete, and a valid rollback point for the installed version and any planned data migration. If it is stale or missing, stop OpenBot and create a second **temporary** snapshot without modifying the known-good one. Check capacity first; fail closed if there is insufficient independent space. Do not back up just because a GitHub release was detected.
3. **After the upgrade:** validate real app login, Agent/Thread histories, provider turns, and app/security settings. Create or select a backup matching the *new running version*, perform file integrity and relevant database checks, and rehearse restoration in isolation. A directory listing, matching file sizes, and `ready` alone do not qualify.
4. **Promote and prune:** after a recoverable backup is confirmed, retire superseded snapshots using an explicit, reviewed list of **exact snapshot directories** and separate owner authorization. Never use an unbounded wildcard, broad `rsync --delete`, or automatically delete a known-good backup on update failure. Leave unrelated `PhotoLibrary` untouched. If validation fails, keep the old rollback and stop cleanup.
5. **Historical migration exception:** the existing pre-0.52 backup is the rollback point for migration 47, **not** a backup of data created on current 0.52. Keep it until the current-version full backup and isolated recovery plan are validated and the owner accepts losing the old-version rollback option.

At the time of this review, the HDD still has **five** historical snapshots; none has passed a confirmed full application restore test, and no automatic rotation is active. Do **not** claim that the one-backup target has already been achieved.

## Upstream Stable upgrades

1. Query current upstream Stable release, read migration/permission notes, and inspect actual installed Umbrel app/version/images.
2. Confirm backup and a rollback copy *before* changes. From v0.51.1 to v0.52.0, migration **47** converts Tasks into multiple Threads. A Docker image downgrade alone cannot open migrated data.
3. Review the version-pinned `mochilab-openbot/docker-compose.yml` and `mochilab-openbot/umbrel-app.yml`. Preserve hooks, sandbox, resource limits, volumes, proxy auth and redirect. Avoid `latest` tags.
4. The release-watch GitHub Actions workflow and `tools/openbot_release_plan.py` may prepare **Draft PRs** when checks pass. They do not merge, deploy, or create a live backup. Each upstream release can introduce migrations not captured by generic notes; manually review the exact release.
5. Merge the deliberately reviewed package version change, allow Umbrel's custom store to refresh, then use the **Umbrel update** operation. App-store refresh and an accepted update request are not proof that a new image is running.
6. Validate actual package version, pinned image, logs, UI/Thread behavior, provider initialize, Agent history/permissions, and the sandbox. Include a small synthetic turn per actually used provider; do not assume a provider merely being `available` is an end-to-end pass.
7. Do not clean up rollback snapshots at the end of the update solely because the app is `ready`.

**Rollback:** Stop the app; assess whether the issue is app configuration, provider, or migrated database. If database migration occurred, a full restore of matching older configuration **and** data is required, not only a Docker image downgrade. Such a restore overwrites changes made since the snapshot and needs action-specific owner approval.

## Cleanup review — what not to treat as trash

| Item | Assessment as of 27 Oct 2026 | Action |
| --- | --- | --- |
| `seccomp-0.49.0.json` | Still used and hash-checked by `hooks/pre-start` | **Keep** |
| `seccomp-workspace.json`, both AppArmor policy files, `hooks/` | Required startup/security assets | **Keep** |
| `landing/`, `hooks/openbot-direct.html` | Required for Umbrel icon redirect | **Keep** |
| `data/.config/OpenBot/openbot.db`, `data/OpenBot/Agents` | Persistent chats/agents and migration state | **Keep** |
| `data/.local/share/keyrings` and `data/.config/openbot-container` | Essential encryption keys/password dependencies | **Keep** |
| Provider auth folders, browser data, `data/.cache`, local fonts | May be needed for sign-in, browser, runtime, or Thai glyph support; no measured cache bloat | **Do not manually clear** |
| External pre-0.52 snapshot | Historical rollback checkpoint for migration 47; not a current 0.52 backup | **Keep until new recoverable backup and owner-approved retirement** |
| Older external snapshots (four sets) | Retention candidates; no verified full restore or safe-to-delete decision yet | **Hold until a current-version recoverable copy exists and the owner approves exact deletion targets** |
| Unrelated Umbrel Community Store `https://github.com/CopilotKit/openbot` | Removed on 27 Oct 2026 via Umbrel CLI; system logs confirmed removal and later store checks no longer requested it | **Resolved — do not re-add** |
| Legacy backup helper and its tests in GitHub | Historical/CI reference; not compatible with current live app | **Retain and label legacy** |

There is substantial internal free space, so cache removal is not justified without a measured issue. The existing Umbrel MCP can inspect the external backup directory, but does not authorize permanent deletion from USB storage. Do not silently remove any backup and never touch unrelated photo storage.

## Verified versus not verified

**Verified through the live Umbrel app** on the above date: installed version/image; app status; app data-root location; no extra mounts; startup logs previously reported Codex, Antigravity and OpenCode available; full pre-upgrade directory copy exists.

**Not verified:** complete database row-level preservation, full restore, all Agents' functional behavior, encrypted backup, current filesystem-level permission hashes, and browser Thai-font rendering. These require their own controlled tests and should not be marked PASS without evidence.

For the authoritative upstream software version, always re-check https://github.com/nightly-labs/openbot/releases rather than relying on this dated snapshot.
