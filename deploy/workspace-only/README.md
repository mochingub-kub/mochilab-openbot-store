# Mochilab OpenBot Workspace only — guarded Production deployment

**Operator approved on 26 October 2026**, subject to a verified minimal recovery copy, safe rollback, scoped security policy, and live functional validation. This is **not** an OpenBot upgrade or an automated backup system. The guarded script does not run by publishing this commit.

## What was proved

- Owner's synthetic **real Codex 0.164.0** offline tests passed with the narrower single AppArmor profile: inside Workspace write, outside write denial, symlink escape denial, and lab profile cleanup.
- Parent/child AppArmor Px with no-new-privileges did **not** pass and is not part of this deployment.
- OpenBot production still used original `mochilab-openbot` profile before this change. Live Agent integration remains untested.
- The added Seccomp allowances (`mount`, `pivot_root`, and `umount2` only with `MNT_DETACH`) apply to **the whole OpenBot Container**, even though AppArmor narrows allowed mount paths. This is a meaningful accepted security tradeoff, NOT per-process isolation.
- The profile is meant for write restrictions, NOT secrecy: OpenBot's Workspace only allows reads outside Workspace and network access. Existing /data sharing remains.

## Deployment review boundaries

Files in `deploy/workspace-only/` are pinned candidates; they are **not** the main Umbrel App Store package. The hook separately verifies its AppArmor/Seccomp blob hashes. The Compose change retains `no-new-privileges:true` and adds `cap_drop: ALL` to the `openbot` service.

The guarded script `tools/apply-openbot-workspace.sh` is **Host SSH only**, not a job to run from OpenBot Agent, Portainer DinD, or Docker inside a Container. It checks exact current baseline hashes and mounted data path, the effective old security label, the selected independent external filesystem, free space, parser and staged blob hashes. It refuses to proceed if any baseline drifted.

The only backup destination it may create is a fresh private hidden directory under UmbrelOS's connected external filesystem `/External/mochi-external` (host-backed `/home/umbrel/umbrel/external/mochi-external`). It never alters or deletes the existing photo directory. It requires a separate ext4/xfs/btrfs mount and writes with root-only mode 0700. The copy contains **OpenBot account/session credentials**; treat the external drive as sensitive and protect physical access. If the drive is unencrypted, this backup is not encrypted.

The script stops **only** OpenBot through Umbrel's own app lifecycle script (no Portainer) before copying /data. It verifies the offline copied files with an rsync checksum dry run; this is **not a full disaster recovery restore test**. Original Compose, hooks, AppArmor and Seccomp are preserved. It installs four new pinned artifacts and recreates the OpenBot container with the changed Compose and hook, then confirms Docker security options and executes native Codex 0.164.0 on a generated, non-secret Workspace. **Startup failure or native sandbox failure triggers best-effort automatic original-config rollback.** Data is not restored automatically because this change does not migrate the database or data layout. Preserve the external backup.

## Commands, one checkpoint at a time

UmbrelOS Host SSH (not Portainer):

```bash
git -C /tmp/mochilab-openbot-workspace-review pull --ff-only
bash -n /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace.sh
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace.sh --check
```

Proceed **only if** `RESULT=PRECHECK_PASS` and the owner has accepted the external backup containing account secrets and the temporary OpenBot downtime. The prior chat approval was for this scoped change; no Full access or UmbrelOS Host privilege escalation is allowed.

```bash
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace.sh --apply
```

At its prompt, the operator types `APPLY-OPENBOT-WORKSPACE`. Required result: `PRODUCTION_NATIVE_CODEX_SANDBOX=PASS` and `RESULT=PRODUCTION_POLICY_APPLIED_NATIVE_TEST_PASSED_AGENT_NOT_YET_VERIFIED`. The script prints the **exact** backup directory.

If the real OpenBot Agent fails its Workspace-only test, use the printed backup directory (same Host SSH):

```bash
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace.sh --rollback /home/umbrel/umbrel/external/mochi-external/.mochilab-openbot-workspace-rollback.ACTUAL_DIRECTORY
```

Substitute the actual printed backup directory, **do not** use the illustrative suffix. Rollback restores original Compose and pre-start hook, restarts OpenBot, and verifies the original AppArmor label. The copied /data remains available for separate manual recovery if necessary.

## Final Agent test (mandatory)

Open OpenBot Web UI, create a **disposable** Codex Agent with **Workspace only** (no Full access) and synthetic files; never ask it to reveal secrets or read other Agents' data. Ask it to create an innocuous file in its own Workspace, then attempt (and be denied) a write to an **explicitly approved synthetic outside-Workspace canary** prepared by the operator. Report only success/denial, not sensitive filesystem paths. Do not equate local Codex debug-subcommand success with real Agent success.

After positive inside write, negative outside write, verified unchanged agent identities, and normal app UI, mark the change provisionally usable. Test persistence across a controlled restart in a separate checkpoint. An app update can overwrite local package files; re-review then. Roll back if functional acceptance fails.

## Limitations

This custom policy can be dropped by a future Umbrel app update; use the same reviewed custom package on updates. Running this script does not install a Backup System, verify photo backups, or prove credential read isolation. Do not change Kernel sysctls, expose SSH, add `CAP_SYS_ADMIN`, or disable `no-new-privileges`.
