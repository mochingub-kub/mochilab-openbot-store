# Mochilab OpenBot safe updater — review gate

This is the **0.50.0-1 release candidate**, not an instruction to update the current
0.49.0-3 production app. It is designed for umbrelOS custom Community App Stores.

## Why a normal update cannot be done yet

The owner successfully staged a separate V3 Workspace-only AppArmor/Seccomp
configuration on the **0.49.0** production image. The currently published
Community App Store on main, however, still has the ORIGINAL 0.49 Compose and
pre-start hook. In UmbrelOS's inspected legacy app update implementation,
the update replaces **docker-compose.yml**, **hooks/**, and finally **umbrel-app.yml**
but does not replace arbitrary app-root files like seccomp-workspace.json.
An update with the old store version can therefore revert the working V3
sandbox. Do not press Update until this proposal is approved and published.

## The stable candidate

- Source: upstream v0.50.0, 2026-10-25; use exact Docker image tag
  ghcr.io/nightly-labs/openbot:0.50.0, never floating latest.
- Umbrel manifest package: 0.50.0-1.
- Upstream official seccomp.json blob is **unchanged** between 0.49.0 and 0.50.0,
  Git blob SHA 6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418.
- The existing V3 AppArmor and Seccomp reviewed artifacts are unchanged:
  AppArmor blob afd0d87e7a09e39afad12864fb988586ce95104e,
  Seccomp blob 4fa610c6303f4610844dc6ae0da5546030a77cbb.
- These V3 files now ship under hooks/ (the Umbrel update whitelist).
  pre-start copies Seccomp to the app-root path only when missing, using a
  no-clobber copy and hash check. If an existing file was modified, it stops.
- Keep original /data: whole app data + database + all provider auth, keyring,
  keyring password, Agent workspaces, chats and Shared folder.
- No extra Docker privileges, capabilities, host mounts, ports or socket.
- The code is **not** proof that upstream 0.50 database migrations are reversible.

## What "Updater" automates

The GitHub Actions release-watch job checks upstream Stable daily after merge.
If the pinned security artifact and upstream Seccomp hash have not changed,
it can propose the next version by modifying **only** the package manifest
and image tag and opening a **Draft PR** (GitHub settings must allow Actions
to open PRs, which has not yet been validated). It verifies versioned GHCR
linux/amd64 image presence. **It NEVER merges, deploys, upgrades, stops OpenBot,
or touches production.** If Security upstream changes, it blocks review
rather than widening privileges silently.

## Checkpoints before approving a production update

Production owner approval is **still needed** to:
- Merge/publish the reviewed app-store PR.
- Stop OpenBot and create a FRESH backup of the **current** 0.49/V3 data,
  because additional Agent UI work has occurred since the previous V3 backup.
- Perform a file-level restore rehearsal from that new snapshot.
- Trigger Umbrel's app update and revalidate its real effect.

Use the bundled tools/openbot_upgrade_backup.py **on the UmbrelOS Host** from
the exact reviewed checkout commit, never inside Portainer or the OpenBot
Agent. The helper provides:
- --preflight: read-only baseline + separate physical HDD and capacity checks
- --backup: stopped-only (all OpenBot containers absent), prompt BACKUP-050,
  complete config and /data rsync with checksum comparison, root-private
  0700 directory on the verified independent HDD, 0600 manifest.
- --rehearse SNAPSHOT: isolated file-level restored copy to a new, temporary
  private directory on the HDD, checksum verification and scratch cleanup.
  It never restores into or alters live production /data.

**The backup includes secrets.** The external HDD is not known to be encrypted;
do not share files, backup manifests with sensitive paths, auth exports or
Docker inspect environment fields in chat.

## Safe rollback principle

An image downgrade is not enough if a newer version has migrated the database.
If production 0.50 has an error, stop the app, then assess the precise failure
and seek a NEW, action-specific authorization before replacing any config or
the entire /data with the fresh stopped pre-upgrade snapshot. Restoring older
/data overwrites newer conversations; do not attempt it automatically. Keep
the 0.49 image and previous V3 transaction copies available during acceptance.

## Actual acceptance after deployment

1. Umbrel reports new installed package version 0.50.0-1 and no active failure.
2. Docker inspect confirms actual GHCR image tag/digest, exact V3 AppArmor
   enforce, reviewed Seccomp path, no extra capabilities/privileged mode,
   only the original /data mount; verified network unchanged.
3. Codex CLI native Sandbox starts and passes bounded own-workspace write,
   outside-write denied and symlink-escape denied, without policy weakening.
4. In the real OpenBot UI, choose a Codex Agent with Permissions = Workspace
   only. Verify it can create/read a disposable workspace file. UI negative
   outside tests and Computer Use/browser are **not** implied to be covered.
5. Confirm login/session, saved Agents, chat and remote client access.
6. Recheck after a normal app restart if possible. Do not delete backups
   until accepted. No automatic backup configuration is done in this PR.

The older V3 tools and rollback evidence remain in Draft PR #4. This updater
PR is independently reviewable and does not merge or modify that PR.
