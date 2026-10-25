# Mochilab OpenBot 0.50.0: operator-only upgrade gate

**Prepared, not deployed.** Do not merge or trigger Umbrel update until every protection item passes.

## Verified inputs (25 October 2026)
- Umbrel app `mochilab-openbot`: version 0.49.0-3; last inspected state ready, not a functional assertion.
- OpenBot release v0.50.0. GitHub Actions workflow run https://github.com/nightly-labs/openbot/actions/runs/40199231815 passed amd64/arm64 image builds and "Verify anonymous Docker image access".
- Upstream v0.49.0 and v0.50.0 Docker seccomp.json have the same Git blob SHA `6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418`.
- This PR retains the original /data mount, named enforced AppArmor profile, seccomp hash, no-new-privileges, RAM and CPU limits. No extra host mounts, ports, privileges, or Docker socket.
- The copy under /Home/Documents/OpenBot-Recovery-2026-10-25 is on the same Umbrel device, not a proven independent recoverable backup.

## Preconditions: STOP if any fail

1. Review exactly these proposed source changes. Confirm no active/queued agent jobs; record agent IDs and accounts/settings without exposing credentials.
2. Inspect a separate, trusted backup destination. Confirm disk, mount, free capacity, and that backup access is restricted. Do not assume the photo disk is an independent recovery plan.
3. Stop only the OpenBot app/engine during a maintenance window, verify it closed databases. Back up the **entire** persistent /data recovery unit, including database, workspaces, keyring, keyring password, provider sessions, and browser files. Copy securely, preserve metadata. Never share the archive or a token.
4. Verify backup integrity and perform at least an isolated restore inspection/check. Keep a separate copy of the reviewed original image/config. Document exact recovery instructions before changing /data.
5. Do not roll an upgraded database back using only an old image tag. If the upgrade fails after migration, restore the COMPLETE pre-upgrade /data together with a compatible prior image.
6. Only then merge this PR, refresh the Mochilab community store, and use Umbrel's app update. The app will restart/recreate and work may be interrupted.
7. Confirm actual engine version, app logs, connected remote client, sign-in, a benign Codex exchange, GitHub connector read, and agent IDs/models/routines unchanged. Do not report success from state ready alone.
8. The Codex Workspace only bubblewrap mount/newroot problem is **separate**, still unverified, and must not be claimed fixed by this engine upgrade.

Sources: https://github.com/nightly-labs/openbot/blob/v0.50.0/docs/docker.md and https://github.com/nightly-labs/openbot/releases/tag/v0.50.0
