# Codex Workspace only: repair review, not a deployment

Status: PREPARED / BLOCKED_FOR_POLICY_VALIDATION. No runtime repair or security certification.

Target: OpenBot engine 0.49.0, Mochilab package 0.49.0-3 on UmbrelOS, Codex on Linux. Do not change any agent's model, account, access, Computer Use or Backup models as part of this patch. Existing Gemini/Antigravity agents are not migrated automatically. Use an owner-selected Codex agent for subsequent Workspace only tests.

## Evidence

Reviewed repository baseline: ace1bd751322c7724ffb9098acb6401c0cc5459b.

- Compose selects seccomp-0.49.0.json, AppArmor mochilab-openbot and no-new-privileges. The only OpenBot data mount is its own persistent /data; no Docker socket is mounted.
- The inspected installed seccomp has default errno EPERM. Its mount/umount2 rules require outer-container CAP_SYS_ADMIN, which the inspected process does not have; pivot_root is absent. The extra unconditional rule admits clone/unshare only.
- Unprivileged user namespace creation succeeds. Mount namespace setup and bubblewrap fail with Operation not permitted before the payload runs. Installed bubblewrap reports 0.9.0.
- The repository AppArmor policy explicitly contains `deny mount,`. The running process has label `mochilab-openbot (enforce)`. The complete loaded host policy has not been exported, so repository content alone does not prove its loaded byte-for-byte identity.
- Upstream v0.49.0 explicitly documents Codex Workspace only in containers as untested, with the same mount, pivot_root and AppArmor blockers.
- pre-start verifies the upstream seccomp Git blob and rewrites a modified copy. Editing the installed JSON by hand will not survive the hook.
- pre-start loads AppArmor only when the named enforce profile is absent. A future policy update must account for the already-loaded same-name profile; otherwise a new disk file can coexist with an old loaded policy.

Sources:
- https://github.com/nightly-labs/openbot/blob/v0.49.0/docs/docker.md#not-confirmed
- https://github.com/mochingub-kub/mochilab-openbot-store/blob/ace1bd751322c7724ffb9098acb6401c0cc5459b/mochilab-openbot/hooks/pre-start
- https://github.com/mochingub-kub/mochilab-openbot-store/blob/ace1bd751322c7724ffb9098acb6401c0cc5459b/mochilab-openbot/hooks/mochilab-openbot.apparmor
- https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c

## 2026-10-25 owner-run isolated baseline

On the UmbrelOS Host the owner executed the reviewed `tools/stage-workspace-bwrap.sh` using a disposable same-image container with no network, host binds, real `/data`, Docker socket or additional capabilities. The output was:

```text
LAB_SCOPE=DISPOSABLE_ONLY NETWORK=NONE HOST_BINDS=NONE NO_NEW_CAPABILITIES=YES
PRODUCTION_RESTART=NO APP_POLICY_CHANGE=NO DATA_CHANGE=NO
LOADED_APPARMOR_PROFILE_CONTENT=NOT_VERIFIED
UID=1000
APPARMOR=mochilab-openbot (enforce)
BWRAP_VERSION=bubblewrap 0.9.0
USERNS_EXIT=0
bwrap: Failed to make / slave: Operation not permitted
BWRAP_EXIT=1
RESULT=BASELINE_RECORDED; NO_POLICY_REPAIR
NOT_TESTED: actual Codex sandbox, writes, outside-denials, persistence
```

Interpretation: basic user namespaces work but bubblewrap's first mount propagation operation is rejected. `BASELINE_RECORDED` marks a successful diagnostic run; it does NOT mean that the Sandbox succeeded. In bubblewrap 0.9.0 source, the failing mount is `mount(NULL, "/", NULL, MS_SILENT | MS_SLAVE | MS_REC, NULL)`; later stages also require other mounts, `pivot_root` and `umount2`. The current seccomp default-deny profile cannot admit the mount without an outer CAP_SYS_ADMIN, and the repository AppArmor policy has `deny mount,`. It is not enough to change only the first mount operation.

An Umbrel MCP read of a bounded recent system journal found no `apparmor="DENIED"` / mount audit entries matching this test. That is NOT evidence that the loaded AppArmor policy allows mount; explicit denies can be silent, and loaded-profile bytes remain unverified.

Next gate: review the exact permitted mount operations under a disposable **distinct** AppArmor lab profile, if and only if the operator approves a temporary host policy load and has a rollback. A staging-only experiment is not production approval. Any candidate must keep no host bind mounts, no production data, no network, no privileged/CAP_SYS_ADMIN and no unconfined security settings. Do not merge this PR or update production until Codex Workspace only functionality and positive/negative filesystem isolation tests pass.
## Strict first-mount AppArmor/Seccomp Lab

After the owner reproduced the baseline with `BWRAP_EXIT=1` and `Failed to make / slave`, the next investigative experiment is only the FIRST bubblewrap mount propagation syscall. This is not a repair candidate for production.

`tools/lab-bwrap-first-mount.sh` generates in `/tmp` a derived Seccomp policy with exactly one added conditional mount exception (syscall `mount`, flags index 3 equals `MS_SILENT | MS_SLAVE | MS_REC`, decimal 573440) and a distinct AppArmor lab profile named `mochilab-openbot-bwrap-first-mount-lab`. It replaces the original `deny mount` only in that transient lab profile with `mount options=(rslave,silent) /,`. The production profile is never rewritten, replaced, or removed.

These rules have different scopes: Seccomp cannot check mount target path or user namespace, so the first rule still has kernel attack-surface implications, even in the disposable container. AppArmor can check path/flags, but behavior must be verified against the exact host parser/kernel. Because both policy layers apply, a denial by either remains effective. Neither rule is a complete confinement system or proof of agent isolation.

Operator sequence on the **UmbrelOS Host** (not Portainer or an OpenBot agent), from the reviewed Draft PR branch:

```sh
git -C /tmp/mochilab-openbot-workspace-review pull --ff-only
sudo bash /tmp/mochilab-openbot-workspace-review/tools/lab-bwrap-first-mount.sh --prepare
sudo bash /tmp/mochilab-openbot-workspace-review/tools/lab-bwrap-first-mount.sh --run
```

Review `tools/lab-bwrap-first-mount.sh` before running `--run`. The `--prepare` mode verifies baseline file hashes and only parses the proposed AppArmor profile; it neither loads it nor launches a container. The `--run` mode REQUIRES interactive confirmation `RUN-LAB`, loads a separately named AppArmor profile in enforce mode, runs a bounded disposable Docker container with no network/host bind mounts/real `/data`/Docker socket, and attempts to remove only its own lab container and lab AppArmor profile afterward. Do not run if active work or if host security profile management is under maintenance.

Check the post-run presence of `mochilab-openbot-bwrap-first-mount-lab` in `/sys/kernel/security/apparmor/profiles` when warned about cleanup. **Never remove `mochilab-openbot`**, only the distinct lab name. On an unexpected failure, stop and preserve the displayed warning; do not try to repair the host by broadening privileges.

Expected evidence: if output advances from `Failed to make / slave` to `Failed to mount tmpfs`, the first operation probably passed and the next is blocked. That is diagnostic progress, not Workspace only success. A parse failure means syntax/kernel compatibility unverified; do not force-load a profile. If the result stays on `/ slave`, investigate AppArmor matching and syscall details instead of broadening the rule blindly.

Version note: OpenBot upstream v0.50.0 was released 2026-10-25, but upgrading the engine is separate from repairing the 0.49.0 sandbox. A production engine/package update remains withheld until this lab validation, complete positive/negative Codex tests, independent complete `/data` backup, operator review, and an approved controlled upgrade. Do not run the app update tool as an implicit step in these experiments.
## Second controlled mount experiment: tmpfs

The owner ran the first-mount lab on the UmbrelOS Host and obtained `PARSER_CHECK=PASS`, `LAB_PROFILE=LOADED_ENFORCE`, `USERNS_EXIT=0`, and `bwrap: Failed to mount tmpfs: Operation not permitted` (`RESULT=FIRST_MOUNT_ADVANCED_TO_TMPFS`). That is proof the first mount advanced to the next operation; it is not a working sandbox.

Bubblewrap 0.9.0 source shows the next operation is `mount("tmpfs", "/tmp", "tmpfs", MS_NODEV | MS_NOSUID, NULL)` immediately after the propagation mount. The separate `tools/lab-bwrap-tmpfs.sh` preserves the previous exact flags-only seccomp rule, and adds only `mount(flags=6)` for tmpfs plus the lab AppArmor rule `mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /tmp/,`. It is a **lab-only hypothesis**. Whether the host AppArmor policy accepts this precise rule and whether the kernel allows the syscall are not known until run.

Seccomp cannot match source, fstype, target, or namespace; allowing flags=6 affects ALL processes in this disposable container and may not be appropriate for production. No production security artifact, hook, compose or agent permission is changed. A successful tmpfs mount still leaves bind mounts, `pivot_root`, `umount2`, and full Codex isolation untested.

### Operator checkpoint (UmbrelOS Host SSH only; idle maintenance window)

Review the new script in the Draft PR and run each command separately:

```sh
git -C /tmp/mochilab-openbot-workspace-review pull --ff-only
less /tmp/mochilab-openbot-workspace-review/tools/lab-bwrap-tmpfs.sh
sudo bash /tmp/mochilab-openbot-workspace-review/tools/lab-bwrap-tmpfs.sh --prepare
```

Only if `PARSER_CHECK=PASS` and the operator accepts transient loading of a **distinct** host AppArmor profile, execute:

```sh
sudo bash /tmp/mochilab-openbot-workspace-review/tools/lab-bwrap-tmpfs.sh --run
```

Confirm by typing `RUN-LAB` only when no Agents are busy. This is a temporary host security-policy load despite no production app restart or profile replacement. The script attempts to unload its own lab profile automatically. If it displays WARNING or BLOCKED, stop and check for the distinct lab profile name; never remove or change the production `mochilab-openbot` profile. Never paste secrets.

An output of `RESULT=TMPFS_ADVANCED_TO_NEWROOT_BIND` means another operation was reached, not a passed sandbox. Keep PR in draft. Do not upgrade the engine or app package until security and functional gates are satisfied.
## Lab script correction: invalid Docker container name (25 Oct 2026)

Operator result: the first+tmpfs AppArmor candidate parsed successfully and the distinct lab profile loaded in enforce mode. **Docker refused to create the disposable container** with `Invalid container name (mochilab-bwrap-tmpfs-1792941442-$)`, Docker exit 125. This is not evidence about whether the tmpfs rule is correct. No tmpfs Bubblewrap execution took place.

Root cause is a packaging typo in `tools/lab-bwrap-tmpfs.sh`: the generated container name ended with a literal `$` instead of a process ID. The fix uses `${BASHPID}` for a numeric suffix, validates the name before loading AppArmor, and confirms profile cleanup visibly after the trial. The production app files/policy remain untouched.

**Safety checkpoint before retesting:** administrator must confirm the previous lab profile name `mochilab-openbot-bwrap-tmpfs-lab` is NOT loaded and no `mochilab-bwrap-tmpfs` disposable Docker container remains. A clean shell prompt does not prove profile unloading; the previous trap attempted removal but printed no success marker. If either remains, stop and inspect before continuing. Do not remove `mochilab-openbot` (the production profile).

After verifying cleanup and pulling the corrected Draft PR branch, rerun `--prepare`, then `--run` only with interactive administrator confirmation and no active Agent tasks. A future successful `--run` still requires review of the actual new mount operation and actual Codex functional tests; this patch does not touch Production or enable app upgrade.
## AppArmor parser-only grammar checkpoint

Following the owner's Lab proof that mount propagation and tmpfs passed but bubblewrap v0.9.0 failed at `setting up newroot bind: Operation not permitted`, the next low-risk checkpoint is a **parser-only** validation of a hypothetical recursive bind rule. This does not grant new mount privileges or assert the security of the candidate.

`tools/check-bwrap-rbind-grammar.sh` reads the existing installed OpenBot AppArmor policy, constructs a uniquely named transient profile under `/tmp`, and uses `apparmor_parser -Q -T -K` to parse it **without kernel loading**. It does not run Docker, restart an app, stop an agent, touch `/data`, modify an installed profile, or broaden Linux capabilities. It deletes the temporary test profile after execution. The script intentionally does not print policy contents, credentials, or secret paths.

On the UmbrelOS Host SSH:

```sh
git -C /tmp/mochilab-openbot-workspace-review pull --ff-only
bash -n /tmp/mochilab-openbot-workspace-review/tools/check-bwrap-rbind-grammar.sh
sudo bash /tmp/mochilab-openbot-workspace-review/tools/check-bwrap-rbind-grammar.sh
```

Expected output: `RESULT=RBIND_RULE_GRAMMAR_ACCEPTED`. This only establishes AppArmor *syntax*, not that the kernel grants the real bind operation, nor that the overall nested Codex bubblewrap is safe. Stop if the source profile layout changed or parsing fails. Do not use these grammar candidate rules in Production. Continue with a separate, reviewed and explicitly consented Lab test or seek an upstream-supported container sandbox path.
## Security decision

Do not replace the blockers with a generic unconditional mount allow and call it safe. Conventional seccomp syscall-argument rules cannot establish that a process is currently inside a particular user/mount namespace, or inspect mount path strings. An unconditional allow applies to every process in this container. Kernel capability checks remain relevant but are not a substitute for reviewing the expanded attack surface.

AppArmor explicit deny rules take precedence over matching allows. Appending an allow while keeping `deny mount,` cannot repair this. Removing that deny and allowing every mount would discard an existing boundary. Rules must be designed from the actual mount operations/flags/filesystem types/targets and the host kernel/AppArmor features. Paths and flags alone must not be described as proof of namespace-specific authority.

The repository's broad `file,` permission and the app-owned /data mount also mean a working write sandbox is not proof of read confidentiality. Shared, other-agent data, provider sessions and browser data require separate checks. No real credential content should be read for those tests.

If a sufficiently narrow policy cannot be demonstrated on this exact host, keep Workspace only command execution BLOCKED and consider an administrator-managed isolated instance/VM as a separately approved design. Do not silently move workload, grant host access or introduce a new service.

## Work the maintainer can prepare now

This PR adds read-only host audit and a gated functional test script, with no active security-policy, Compose, hook, image or app-version change. Neither script runs automatically. Do not wire either into pre-start or give AI agents a host executor.

Run `tools/audit-workspace-host.sh /verified/path/to/installed/app` from the administrator's host terminal. It inspects selected Docker security fields and policy files, not environment variables or credentials. Capture current host kernel/AppArmor versions and matching denial logs through the administrator's authorized tools. Do not publish raw system logs or unrelated host paths without review.

Before a security-policy patch can be promoted:
1. Capture the exact installed Codex sandbox invocation and its required syscalls on a disposable staging copy with dummy data, same kernel, Docker, AppArmor and image. Never execute a second copy against the live /data identity.
2. Trace namespace creation, mount/umount2/pivot_root and any additional rejected operations. Do not allow unrelated syscalls from the upstream CAP_SYS_ADMIN block.
3. Prepare an OpenBot-specific reviewed seccomp artifact and AppArmor policy. Account for explicit denies and existing proc/sys restrictions. Keep default-deny seccomp and enforced AppArmor, no-new-privileges and host mount boundaries.
4. Test positive operations and intended negative controls in staging. Record residual kernel exposure; a successful mount alone is not isolation proof.
5. Review before changing production. No privileged, CAP_SYS_ADMIN grant, unconfined policy, --no-sandbox or Full access escape hatch.

The actual policy amendment is deliberately NOT INCLUDED until those observations exist. These documents and tools are a repair-preparation patch, not a complete runtime repair.

## Isolated baseline probe (new, no runtime changes)

The operator can test the current DENIED Bubblewrap baseline using tools/stage-workspace-bwrap.sh on the UmbrelOS HOST. This does not change the app, profile or any agent setting. The script launches one disposable container using the *exact immutable locally present image ID* and pinned current policies, with no network, no host bind mount, no production /data, no Docker socket, a read-only filesystem and temporary in-memory /data and /tmp. It is resource- and time-limited.

Steps (run from the UmbrelOS Host, NOT inside Portainer or an OpenBot agent):

    git clone --depth 1 --branch review/codex-workspace-only-preparation https://github.com/mochingub-kub/mochilab-openbot-store.git /tmp/mochilab-openbot-workspace-review
    less /tmp/mochilab-openbot-workspace-review/tools/stage-workspace-bwrap.sh
    sudo bash /tmp/mochilab-openbot-workspace-review/tools/stage-workspace-bwrap.sh

Inspect the script before execution. This test creates a disposable Docker container and consumes some resources, so run it while agents are idle. It does not load AppArmor or change any host policy. Its baseline denial is evidence for the current configuration only. A successful bwrap probe is NOT a Codex Workspace only functional test or security certification.

Important alternate-path rejection: Codex 0.164.0 still has a legacy Landlock feature, but the tagged upstream README explicitly rejects it for filesystem-restricted policies because it cannot isolate app-server Unix sockets. Do not enable features.use_legacy_landlock as a fix. Source: https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/linux-sandbox/README.md

No candidate mount relaxation is in this PR. Further policy review and isolated tests are needed before any production change.
## Durable packaging requirements for the later reviewed policy patch

- Vendor versioned policy artifacts under hooks/, which this Umbrel updater copies. Do not rely on arbitrary new top-level directories being copied on update.
- Keep the exact upstream seccomp as a verified input and produce or vendor a separately named, reviewed derived artifact. Validate both hashes. Update Compose to select that derived artifact explicitly. Never edit the upstream file in place while pre-start restores its old hash.
- A host-only hook must parse AppArmor without kernel/cache mutation first, then deliberately replace only the named OpenBot policy when installing a changed reviewed artifact. Do not infer its content merely from its profile name. Consider that replacing a loaded same-name profile affects current processes; use an operator-controlled maintenance window.
- Atomically publish verified artifacts and fail closed on missing/mismatched artifacts. Preserve originals for rollback. Hooks must never evaluate agent-controlled files from /data as host code or policy.
- Version the package only when a reviewed policy change is ready. Pin image/version and hashes. On later engine updates, re-evaluate upstream seccomp, Codex/bwrap requirements and the host test matrix. Restart/update persistence remains unverified until actually tested.

## Administrator deployment responsibilities

The administrator, not an AI agent, edits/reviews host policy, loads AppArmor and recreates the affected container. Connected Umbrel tools expose root configuration as read-only and do not provide host command execution. This PR does not change that boundary.

Before deployment: inspect active and queued agent tasks; require idle, preserve IDs and agent settings, retain paused routine states, make and verify an independent consistent backup of the complete /data recovery unit including keyring/session material without exposing it. Save effective Compose, original policies, hashes and image identity. No data migration is required by this proposal.

Docker loads seccomp when a container is created; restarting only the OpenBot process is insufficient. Recreate only the app through supported Umbrel lifecycle controls, with the same persistent data and settings, after approval. Plan brief downtime. Do not restart the Docker daemon or other Mochilab apps.

## Functional acceptance after administrator installation

Use one explicitly selected existing Codex agent with Workspace only. Record provider/account/model/effort/access/Computer Use/backup/routine values before and after via native read_agent. There is no model switch in this preparation patch.

1. Minimal bubblewrap payload works in the repaired container without adding outer capabilities. Then test the actual Codex exec tool, not just a host docker-exec stand-in.
2. Through that actual restricted tool, run tools/check-workspace-files.sh with explicit synthetic locations supplied by the administrator. It writes only synthetic test material and reports a failure if an outside-workspace write unexpectedly succeeds. Inspect the real denial; a missing directory or ordinary file permissions is not proof of sandbox enforcement.
3. The administrator must provision an outside canary that the underlying UID can normally write, and verify it from the container outside the agent sandbox. The restricted command must fail there. Do not grant new host mounts for a test.
4. Separately test supplied synthetic readable canaries in Shared, a disposable other-agent location and a disposable credentials-like location. Log only READABLE/BLOCKED, never contents. Record that these probes do not certify all files in a class. Never read real credentials or ask a model to enumerate secrets.
5. Confirm default models/permissions/Computer Use/backups unchanged and team routines paused. Run DATA's exact fixture and BUILDER's validator cases only after the runtime gate passes.
6. With idle work and verified backup, repeat after container recreation, host restart and a reviewed package-update rehearsal. These checks require administrator action; do not claim persistence from static files.

No PRODUCTION_READY result until required positive/negative checks and company-data authorization pass. TOOLBOX remains BLOCKED pending effective read isolation, regardless of write-sandbox results.

## Rollback and remaining risks

For this preparation-only PR rollback has no runtime action: no production settings changed. For a future deployed policy, restore the saved reviewed original artifacts and effective configuration, reload only the named policy and recreate the affected app. Confirm unchanged /data and agent IDs. Never downgrade a migrated database; a security-policy rollback is distinct from restoring data or engine versions.

Risks include greater kernel surface from namespace/mount access, overly broad AppArmor rules, a stale loaded policy, dropped overrides on package updates, downtime/unfinished work during recreation, and read access across /data despite write restrictions. Mitigations need measured tests, not model assurances. Token cost/quota/savings are not measured by this repair work.
