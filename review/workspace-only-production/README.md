# OpenBot Workspace only — Production candidate review (NOT DEPLOYED)

Evidence: owner supplied an UmbrelOS SSH mobile screenshot showing `codex-cli 0.164.0`, `NATIVE_CODEX_SANDBOX=PASS`, `NATIVE_CODEX_WORKSPACE_WRITE=PASS`, `NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED`, `SYMLINK_ESCAPE=BLOCKED`, `NARROW_MOUNT_RULES=ENFORCED` and `LAB_PROFILE_CLEANUP=CONFIRMED_REMOVED`. The `RESULT=REAL_CODEX_0_164_0_SCOPED_MOUNTS_WORKSPACE_PASS` line was horizontally clipped in the mobile screenshot but corresponds to the successful branch in the reviewed Lab script. This proves a synthetic single-Container test; not any Production authorization or Agent behavior.

This folder contains *review-only* candidate artifacts, derived from the same effective AppArmor mount targets and Seccomp exceptions that passed the synthetic Lab. Nothing in the installed OpenBot app, UmbrelOS Host policy, Compose, AppArmor labels, users, runtime, credentials, or app data was modified by these GitHub files.

- `apparmor-review-only.profile`: distinct `mochilab-openbot-workspace-candidate` label to preserve the existing `mochilab-openbot` enforcing Profile. Mount rules apply to ALL processes bearing the candidate profile, not just `bwrap`. The original `deny mount,` has been replaced by a narrow allowlist of Bubblewrap-related paths and two pivot roots. This still adds mount/pivot capabilities relative to production.
- `seccomp-review-only.json`: exact upstream 0.49.0 default-ERRNO Seccomp baseline plus Lab-proven `mount`, `pivot_root`, `umount2(MNT_DETACH)` allows. **Seccomp does not inspect executable identity, mount path, namespace ownership, or the user request.** Every process in a future shared OpenBot container would receive these allow rules. This is a meaningful security change.
- Do NOT copy these files directly over pinned `hooks/mochilab-openbot.apparmor` or `seccomp-0.49.0.json`: the `hooks/pre-start` script currently hard-checks their content hashes and will refuse a modified AppArmor file or redownload the upstream Seccomp file.
- Deployment will require a separately reviewed service configuration and hook change to reference a new profile name and a distinct Seccomp path, plus a supported UmbrelOS app-recreate mechanism. Merely restarting the Docker process may not apply new Docker security options.
- Restrict main-app capabilities if feasible (`cap_drop: ALL`, matching synthetic Lab); verify it does not break the engine. The existing OpenBot v0.49.0-3 Compose does NOT set this for the `openbot` service.
- Do not disable no-new-privileges, do not use Docker privileged mode, host CAP_SYS_ADMIN, seccomp/appamor unconfined, host socket mounts, public exposure or broad host changes.
- Agent Workspace only is a **write** sandbox. Source documents say reading files outside workspace and network remain allowed. It is NOT a per-Agent secret confidentiality boundary. Other data under shared `/data` may be readable. This risk must be understood before enabling.
- Any planned Production apply needs a verified *minimal recovery copy* of the live current OpenBot `/data` plus original Compose/hook/policies, verified local rollback script, and scoped operator consent. This is a safety prerequisite for changing Production, NOT a request to build the future automated Backup System.
- Canary acceptance after authorized cutover: use a new test Agent with `Workspace only`, a disposable folder owned by UID 1000, a synthetic outside file writable in a baseline without Sandbox, and no secrets. Require positive inside-write, negative outside-write, denied symlink-write, working Codex prompt/response, normal OpenBot UI operations, persistent agent identities, and rollback readiness. Check after Umbrel restart and an update separately before long-term reliability claims.

Decision: This is a technically promising **candidate**, not a proven safe or complete Production patch. Preserve Draft PR status. The review gate stays closed until operator approves the precise Production impact and recovery plan.

## Pinned sources

- Original AppArmor blob: `fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a`
- Original OpenBot hook blob: `3c981033751a830e72e48c18227a3e236d64a38c`
- Original Compose blob: `70dcead64b8e499f45cd63fbad89165926f19212`
- Upstream v0.49.0 Seccomp blob: `6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418`
- Scoped native test script blob: `3e87fab22c47c009c840cfa1585fc261f0387610`
