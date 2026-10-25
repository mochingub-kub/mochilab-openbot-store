# Mochilab OpenBot: use Codex now without changing Workspace only

Updated: 2026-10-25.
Status: PRACTICAL GITHUB WORKFLOW / LOCAL WORKSPACE COMMANDS BLOCKED.
Scope: OpenBot package 0.49.0-3 (engine 0.49.0) on UmbrelOS.

## Verified boundaries
- The owner reproduced Bubblewrap failures in disposable no-network lab containers. Initial mount propagation and the tmpfs mount both progressed under transient, separate lab-only policies, but the next newroot bind mount was denied.
- One lab run reported `LAB_PROFILE_CLEANUP=CONFIRMED_REMOVED`. No repaired policy was installed into Production. The owner subsequently passed an isolated real-Codex 0.164.0 synthetic inside-write/outside-write test. This is NOT an actual OpenBot Agent production test.
- OpenBot was most recently `ready`, and Codex has completed conversations. Existing OpenBot agents previously created Draft PR #1 through their authorized GitHub workflow.
- A GitHub API tool running via OpenBot's connector is a distinct authorization boundary from the local Codex command sandbox. It is NOT proof that local files are isolated or that remote repositories are safe from unrelated changes.

## Use today: scoped GitHub draft PR workflow

Keep the existing Codex agent's **Workspace only** level. Do not switch it to Full access or enable Computer Use.

Use only GitHub connector tools for source changes that can be made without running local code. Work in a new branch and a Draft PR; never push directly to main, merge, publish a release or deploy automatically. Avoid secrets and production data. Do not ask the agent to use shell, patch local app files, change Docker security settings, run installation steps, or falsely claim that tests ran.

Suggested agent instruction:

> Work only on the selected GitHub repository and make changes through authorized GitHub tools. Create a separate branch and Draft PR. Do not use local shell or write local OpenBot files while Workspace only is blocked. Do not merge, deploy, change credentials, agent permissions, Docker policy or host configuration. Report files changed, assumptions, actual checks, and any tests not run. Stop before unsafe changes.

The OpenBot built-in GitHub connection is shared among agents on that server. Confirm GitHub App installation has access only to the specifically intended repositories; API permissions are distinct from the agent's local Workspace only setting. Protect default branches and require review.

This workflow can draft and review repository changes NOW. It cannot execute arbitrary shell commands inside the local restricted Workspace, build/test with an installed Docker sandbox, administer UmbrelOS, or certify read isolation.

## Continue repair without a privilege shortcut

A working Bubblewrap container is only the first positive test. A future reviewed security design must have:
1. Host-specific analysis and testing of namespace, mount and root-switch requirements in a disposable staging environment.
2. Enforced, narrow security policy that does not rely on privileged mode, host CAP_SYS_ADMIN, unconfined policy, extra host mounts or Full access.
3. Actual Codex restricted inside-write success, outside-write failure with a writable baseline, and separate synthetic cross-agent read checks.
4. Verified independent complete backup and rollback of the OpenBot /data unit (including metadata/session dependencies) before any app recreation/update.
5. Repeatable results after controlled restart and reviewed update. Do not claim ready without this evidence.

Keep TOOLBOX blocked until read isolation is separately validated. Preserve agent identities, model/effort, routines, account setup and Computer Use settings.

## Upgrade gate

The engine 0.50.0 release exists but its published Docker documentation still describes Workspace only in a container as untested. Do not treat the version bump as the runtime repair. The owner's requested app upgrade remains a separate checkpoint AFTER the stated safety, backup and validation gates; no production app update is part of this documentation PR.
