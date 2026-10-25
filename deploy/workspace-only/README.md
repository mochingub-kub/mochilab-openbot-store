# OpenBot Workspace only - UmbrelOS 2.x guarded deployment

User-approved scope: OpenBot Workspace only production policy, minimum off-device copy for rollback, and real functional test. **Do not update OpenBot or build a new backup system** in this change.

## Why the first script was retired

On the installed UmbrelOS 2.0.0 host, OpenBot app-data is present but `/home/umbrel/umbrel/scripts/app` **does not exist** (user's SSH screenshots). That path was incorrectly assumed by V1. UmbrelOS 2 starts/stops apps through its managed `umbreld` lifecycle process, with a packaged legacy-compat App Script and runtime Compose overlays. Running a manually invented lifecycle command would bypass important Umbrel protections. The original `tools/apply-openbot-workspace.sh` is now **fail-closed (deprecated)**. Do not recreate `scripts/app`, change host packages, or run V1.

## V2: tools/apply-openbot-workspace-v2.sh

Four deliberately separated steps:
1. `--check` while the original OpenBot is running. **Read-only**. Validates hashes, original security label, independent external storage, free space, and new AppArmor parser. Result `PRECHECK_PASS_NEXT_UMBREL_MCP_STOP`.
2. **Assistant** stops only OpenBot with connected Umbrel MCP `stop_app`; confirm `stopped` (do not assume accepted = completed). **Owner** runs `--stage` from UmbrelOS Host SSH. The script requires all OpenBot containers stopped. It saves original config and a consistent, offline `/data` copy with checksum comparison to a newly created mode-0700 directory on a separate external ext4/xfs/btrfs filesystem, then installs the pinned Compose/hook/AppArmor/Seccomp candidate. It neither stops nor starts the app. On a partial config write error, it attempts original-config restore while the app remains stopped.
3. **Assistant** starts OpenBot using Umbrel MCP `start_app`; inspect `get_app_status` for `ready` and lack of failure and check logs. The owner runs `--verify` inside Host SSH, which checks Docker's actual security options and executes an offline, native Codex 0.164.0 write containment test with synthetic files only. **A running app is not proof that the feature works**.
4. Test a new, disposable Codex Agent in the OpenBot UI with `Workspace only`. Test a positive write inside its workspace and a denied attempt to write a **user-prepared synthetic canary** outside it; check there is no unexpected prompt for Full access. Check existing Agents/UI and that the restart retained sessions. Do not inspect or display secrets.

If start/verification/Agent test fails: the assistant uses `stop_app` first, and owner runs `--rollback <RECOVERY_COPY_LOCATION>` from Host SSH, which restores pinned original Compose and hooks/profile from the exact v2 backup folder. The assistant then calls `start_app` and validates the original AppArmor profile. **V2 does not claim automatic App restart/rollback**, because UmbrelOS 2 app lifecycle is managed by `umbreld`. No automatic restoration of data is performed; this change does not migrate or delete /data. Preserve the independent backup.

**No new privileges**: candidate keeps `no-new-privileges:true` and `cap_drop: ALL` and does not run Docker privileged or grant host CAP_SYS_ADMIN. The scoped AppArmor profile adds mount/pivot-root allowances used by native Codex, and Seccomp grants these syscalls to all processes in the OpenBot container; this remains a material accepted limitation, even after a successful lab test. Workspace only is a write sandbox, not read/network/secret isolation.

The rollback copy contains OpenBot account/session credentials. External HDD must remain private. V2 requires a distinct mounted POSIX-permission-capable filesystem (ext4/xfs/btrfs) with sufficient capacity; it will block on exFAT/NTFS rather than silently lose ownership/ACL metadata. If blocked, stop; **do not format or move external storage**.

## Commands (UmbrelOS Host SSH)

```bash
git -C /tmp/mochilab-openbot-workspace-review pull --ff-only
bash -n /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace-v2.sh
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace-v2.sh --check
```

Only after PRECHECK_PASS, coordinate Umbrel MCP stop. Then:

```bash
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace-v2.sh --stage
```

After STAGED and connected Umbrel MCP start:

```bash
sudo bash /tmp/mochilab-openbot-workspace-review/tools/apply-openbot-workspace-v2.sh --verify
```

Record `RECOVERY_COPY_LOCATION` outside public documentation and never share backup file contents, secret values, or session tokens in chat. Use it if rollback is needed; rollback requires the app already stopped via MCP.

This script is not deployed by GitHub commits alone. The owner must run SSH commands explicitly, and Umbrel MCP controls app lifecycle at assistant checkpoints.
