# Mochilab OpenBot V3 Workspace-only configuration candidate

**STATE: Draft PR only. NOT installed, deployed or safety-certified.** The installed
OpenBot package is 0.49.0-3 and remains on its original AppArmor/Seccomp policies.

## Verified baseline and scope

Owner's UmbrelOS Terminal read-only check on 2026-10-26:
- V3 planner accepted the actual runtime Compose: ALLOWED_PATCHES=2_SECURITY_OPT_SCALARS_ONLY, HOST_FILES_CHANGED=NO.
- Container was running as AppArmor 'mochilab-openbot', with only /data as a RW mount.
- NoNewPrivs=1, Seccomp=2, Seccomp_filters=1.
- Bubblewrap failed at 'Failed to make / slave: Operation not permitted'.
- The pinned original AppArmor file in GitHub contains 'deny mount'; upstream
  v0.49.0 seccomp permits mount only for CAP_SYS_ADMIN. Actual loaded kernel
  policy bytes remain unverified.
- Older isolated single-container Codex 0.164.0 Lab recorded a scoped mount
  positive workspace-write and negative outside-write/symlink denial.
  **This is NOT a production Agent functional test.**

## Candidate artifact integrity

Copied without edits from the reviewed PR #1 Lab:
- 'mochilab-openbot-workspace.apparmor', Git blob
  afd0d87e7a09e39afad12864fb988586ce95104e
- 'seccomp-workspace.json', Git blob
  4fa610c6303f4610844dc6ae0da5546030a77cbb

The current package's 'hooks/pre-start' is carried forward with existing pinned
upstream seccomp checks, original AppArmor enforcement and Umbrel dock redirect.
A new scoped profile (with distinct name) is hash-verified and loaded in
enforce mode. Candidate pre-start Git blob:
f0f6de6bea47df28595449c2f766a99c804aaab2

**Security tradeoff:** the proposed seccomp unconditionally allows 'mount',
'pivot_root', and 'umount2(MNT_DETACH)' to processes in THIS container.
AppArmor separately limits the mount/pivot locations and flags. The kernel
seccomp profile cannot constrain the syscall to a named process, user namespace
or target path. This is broader than the installed policy and is not a
confidentiality boundary among Agents in /data. Never add privileged mode,
CAP_SYS_ADMIN, docker socket mounts, or 'unconfined' as a workaround.

## Operator-only installation gates (do not skip)

Tools: 'tools/v3_compose_plan.py' and 'tools/v3_workspace_transaction.py'.
All commands in the following stages are for the **UmbrelOS Host**, not a
Portainer Docker-in-Docker terminal, Mac or OpenBot Agent.

1. **Read-only check while production runs**:
   a. Check out the exact reviewed PR commit and verify 'git rev-parse HEAD'.
   b. Run 'sudo python3 tools/v3_workspace_transaction.py --check'.
   c. If blocked, do not stage or weaken any check. This inspect includes
      real Docker labels/security/mounts, app baseline, effective override
      screening, exact artifact hashes and read-only AppArmor parsing.
   d. Output's 'EFFECTIVE_OVERRIDES=PARTIALLY_INSPECTED' is an explicit
      limitation. A separate effective Compose validation is needed before
      a production apply, using the actual files/environment.

2. **Independent backup**:
   a. Inspect the target disk's mount/source/filesystem/ownership and free
      space. Choose its exact HOST absolute path; never infer host path from
      Umbrel's /External virtual file-browser path.
   b. Obtain a work-free maintenance window. Stop *only* OpenBot via Umbrel's
      supported app lifecycle, then check every service has stopped.
      On this umbrelOS app-script, the stop action runs
      'docker compose rm --force --stop', which REMOVES the app containers
      while preserving the separately mounted app /data. V3 Stage now
      requires their absence, rather than trying to inspect a deleted
      saved container. Run the pinned --check while still running BEFORE
      stopping OpenBot; the stopped-only stage rechecks the installed
      Compose and pinned security artifacts.
   c. Run a final stopped-only 'sudo python3 ... --stage BACKUP_PARENT'.
      This asks for 'STAGE-V3' interactively. Before publishing any config,
      it checks separate physical block devices, filesystem support and
      free space, then copies complete /data with rsync -aHAX and checks
      contents using rsync -aHAXnci. This includes credentials, sessions,
      agents and keyrings: restrict the backup directory, never paste its
      files into chat. Physical possession of an unencrypted HDD can expose
      this backup.
   d. Config backups, original hashes, recovery journal and rollback
      manifest are in a private transaction directory. The script does not
      restore user data automatically and has NOT passed an app restore
      rehearsal. Backup copy integrity is not app restore success.
   e. If a condition or permission is unknown, abort instead of guessing.

**New safety checkpoint — BACKUP-ONLY before modifying policy:** After a
successfully verified `--backup-preflight` (while the app is running), obtain
owner permission for a maintenance window, stop OpenBot through the Umbrel
app UI, and use the reviewed `tools/v3_backup_only.py --backup-only
EXTERNAL_HDD_MOUNT` on the UmbrelOS Host. It requires an explicit typed
`BACKUP-V3` confirmation, all containers removed, and rechecks the original
on-disk Compose/Policy and independent writable disk. It then saves all
configuration plus /data to an independent private (0700) HDD directory,
checks exact configuration bytes and rsync checksum results, and reports
`RESULT=V3_BACKUP_ONLY_VERIFIED_COPY`. It does **not** stage or change policy.
The backup contains private OpenBot session material and is **not known to be
encrypted at rest**. Do not expose this folder through public Files or shares.
An interrupted copy has state `UNTRUSTED_INCOMPLETE` and is not usable as a
checkpoint. After backup success, perform an actual file-level restoration
rehearsal in an isolated directory before any security rollout. The full
OpenBot application restore remains unverified unless separately tested.
The later `--stage` currently makes a **second** independent safety copy;
it does not reuse the backup-only transaction.

**Isolated FILE-level Restore Rehearsal (no downtime):** After the
`BACKUP_ONLY_VERIFIED_COPY` result, reopen the original OpenBot using Umbrel's
normal lifecycle and confirm `ready`. Use the pinned
`tools/v3_restore_rehearsal.py --rehearse BACKUP_TRANSACTION` **on UmbrelOS
Host**, referring to the exact `BACKUP_TRANSACTION` printed by backup-only.
The helper requires a verified 0700 root-owned backup directory and a
checksum-valid 0600 manifest; it rejects unexpected backup paths, a
non-`BACKED_UP` manifest and tampered config files. It copies all backed-up
`config/` and `data/` into a newly-created root-private temporary folder on
the same independent external HDD, compares bytes/metadata with rsync
checksums, and cleans up **only that temporary scratch copy**. It never
modifies the backup, mounted original /data, production Compose or kernel
AppArmor/Seccomp. It runs while the production app is online. Result
`V3_FILE_RESTORE_REHEARSAL_PASS` establishes that the saved files can be
reconstructed and compared, **NOT** a full production application restore
or a Codex Workspace functional test. Disk must have enough spare space for
a second temporary data copy; no cleanup or format of other HDD folders.
If the helper fails, **do not stage V3** and preserve the original backup.

3. **Stage/rollback**:
   a. Only the two existing Compose 'security_opt' scalar tokens are
      changed. No template replacement or YAML reserialization.
   b. Two new policy artifacts are installed and the old pre-start is
      replaced by the hash-pinned candidate while keeping the old app
      profile and seccomp files. All existing services remain stopped.
   c. Stage journals and readbacks its changes. A crash leaves a recovery
      transaction: DO NOT START until recovery is reviewed.
   d. 'sudo python3 ... --rollback TRANSACTION_DIR' is stopped-only and
      refuses any unexpected third-party edits. It restores only changed
      configuration; the complete data backup remains untouched. An AppArmor
      profile already loaded in the host kernel may remain loaded but unused
      after config rollback; never unload a profile that a running process uses.

4. **Start and verify after separate explicit production authorization**:
   a. Start via Umbrel lifecycle. This runs the reviewed, hash-pinned
      pre-start Hook to load the distinct AppArmor profile. If the app
      does not start, stop and rollback from the recorded transaction.
   b. 'sudo python3 ... --verify' checks the requested running security
      options and original /data mount only. This is NOT a Codex test.
   c. Run the actual Codex Agent with Workspace only using disposable
      write canaries: inside workspace succeeds, a writable outside
      canary is denied, a symlink escape is denied. Also check startup,
      existing agents/data and UI. Never use real credentials as canaries.
   d. Test a restart separately. An Umbrel App Store update may overwrite
      the unmanaged runtime Compose and Hook: update persistence is NOT
      established. Future supported package update must be handled only
      after a clean functional test and recovery evidence.

## Safeguards and unresolved items

- No GitHub commit or CI success implies a production change.
- Data backup/restore on current UmbrelOS is NOT yet independently verified.
- A separate named AppArmor profile affects only future containers selecting
  it, but loading it changes host kernel policy and requires owner approval.
- Stage script cannot lock Umbrel's updater; schedule an exclusive maintenance
  window and recheck input files before each publish.
- Do not merge the Draft or perform stage/start with this candidate until
  read-only host precheck and explicit recovery/production security approval.
- CI tests are synthetic; GitHub Actions is not an UmbrelOS functional test.
