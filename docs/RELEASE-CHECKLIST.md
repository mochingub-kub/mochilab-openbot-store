# OpenBot release checklist for community-store maintainers

This checklist documents the **human-controlled release process** for the public, unofficial umbrelOS OpenBot package. It applies to a maintainer reviewing a release, not to any particular server. There is **no promised update schedule or support**; see [README](../README.md) and [Safe updates and recovery](SAFE-UPDATER.md).

> Important: GitHub Actions can check package consistency and propose a **draft PR**, but GitHub does **not** back up, merge, deploy, run agents on, or clean up any user's umbrelOS installation. Every install has its own storage and recovery requirements.

## Before a release

- [ ] Inspect the upstream **stable** release and migration/security notes. Compare the upstream version with the actual installed version and the package on the default GitHub branch. Do not infer the installed version from a draft PR or an old chat.
- [ ] Inspect the candidate PR diff. For routine releases, changes should be limited to the version-pinned image, app manifest version, and release notes. Any changes to volumes, network access, AppArmor, Seccomp, hooks, resource limits, or privilege boundaries require separate review.
- [ ] Check that the GHCR image exists for the target architecture and package validation CI passes. CI does not test an individual install's data, credentials, providers, or restore path.
- [ ] On the **installation being updated**, check for active agent work. Make a private, consistent, complete pre-upgrade backup of application state and configuration to an independent destination. Preserve the current rollback copy until the new backup is verified. A database file alone is not enough.
- [ ] Review a recovery path for the **matching old image and old data**, including possible database migrations. If a backup or recovery path is unverified, disclose that limitation and do not pretend it passed.

## Deploy and validate

- [ ] Explicitly approve and merge the reviewed PR only after the pre-upgrade safeguards. Refresh the Community Store and update only the intended app through umbrelOS. The release watcher never does this automatically.
- [ ] Read back the installed app version and image tag, check container logs, and inspect the retained data.
- [ ] Test sign-in, an existing conversation, a real provider/agent interaction, and any sandbox behavior the installation relies on. **App `ready` is not a functional test.**
- [ ] If the update fails, stop and evaluate a restore of both matching package and data rather than attempting an image-only downgrade after a schema migration.

## Retention and cleanup — separate, optional maintenance

- [ ] Keep the most recent verified **pre-upgrade** recovery snapshot during normal operation. A temporary second snapshot may be needed while upgrading.
- [ ] **Do not automatically prune when a release is detected, a PR is merged, or the app first becomes `ready`.** Only consider cleanup after an adequate backup, successful functional validation, and a recovery review.
- [ ] Before deleting anything, inventory the precise backup directories, protect the chosen keeper, exclude unrelated and system backups, show the deletion plan, and obtain installation-owner approval for those exact permanent deletions.
- [ ] After deletion, read the storage directory again and confirm the keeper exists. Record clearly if a full app restore test was not completed.

No cleanup script, personal host path, device inventory, private backup data, or automatic retention job is distributed by this public Community Store. Keep any installation-specific maintenance procedure **outside this public repository**. Do not post secrets, sessions, keyrings, or private backups in PRs or issues.

This is a review checklist, not a universal backup/restore implementation or a guarantee of data recovery.
