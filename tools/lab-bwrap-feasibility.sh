#!/usr/bin/env bash
# Mochilab: ONE-SHOT nested Bubblewrap feasibility and write-containment lab.
# Derived from the verified OpenBot lab harness; compares with OpenClaw CI-only
# Codex Bubblewrap Docker security policy. NOT for production use.
# Do not use this profile/JSON in production Docker Compose.
set -euo pipefail
if (( $# != 1 )) || [[ "$1" != --prepare && "$1" != --run ]]; then
  echo 'Usage: sudo bash tools/lab-bwrap-feasibility.sh --prepare|--run' >&2
  exit 2
fi
mode="$1"
if (( EUID != 0 )); then
  echo 'BLOCKED: execute using sudo in UmbrelOS HOST SSH, never Portainer/agent' >&2
  exit 2
fi
umask 077
for cmd in docker git python3 timeout apparmor_parser mktemp; do
  command -v "$cmd" >/dev/null || { echo "BLOCKED: missing $cmd" >&2; exit 2; }
done
prod=mochilab-openbot_openbot_1
lab_profile=mochilab-openbot-bwrap-feasibility-lab
[[ "$(docker inspect -f '{{.State.Running}}' "$prod" 2>/dev/null || true)" == true ]] || {
  echo 'BLOCKED: OpenBot production container not running' >&2
  exit 2
}
image=$(docker inspect -f '{{.Image}}' "$prod")
[[ "$image" == sha256:* ]] || { echo 'BLOCKED: immutable image id missing' >&2; exit 2; }
[[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$prod")" == false ]] || {
  echo 'BLOCKED: production privilege setting changed' >&2; exit 2;
}
[[ "$(docker inspect -f '{{json .HostConfig.CapAdd}}' "$prod")" == null ]] || {
  echo 'BLOCKED: unexpected production extra capabilities' >&2; exit 2;
}
[[ "$(docker inspect -f '{{.AppArmorProfile}}' "$prod")" == mochilab-openbot ]] || {
  echo 'BLOCKED: production AppArmor profile changed' >&2; exit 2;
}
opts=$(docker inspect -f '{{json .HostConfig.SecurityOpt}}' "$prod")
[[ "$opts" == *'apparmor=mochilab-openbot'* && "$opts" == *'no-new-privileges:true'* && "$opts" == *'seccomp='* ]] || {
  echo 'BLOCKED: effective container security options changed' >&2; exit 2;
}
mounted_data=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$prod")
[[ "$mounted_data" == /* && -d "$mounted_data" && "$(basename -- "$mounted_data")" == data ]] || {
  echo 'BLOCKED: production /data location unexpected' >&2; exit 2;
}
app_dir=$(dirname -- "$mounted_data")
[[ "$app_dir" != / && -f "$app_dir/docker-compose.yml" ]] || {
  echo 'BLOCKED: app package directory unrecognized' >&2; exit 2;
}
seccomp_input="$app_dir/seccomp-0.49.0.json"
apparmor_input="$app_dir/hooks/mochilab-openbot.apparmor"
[[ -r "$seccomp_input" && -r "$apparmor_input" ]] || {
  echo 'BLOCKED: security source artifacts not readable' >&2; exit 2;
}
[[ "$(git hash-object "$seccomp_input")" == 6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418 ]] || {
  echo 'BLOCKED: upstream seccomp checksum mismatch' >&2; exit 2;
}
[[ "$(git hash-object "$apparmor_input")" == fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a ]] || {
  echo 'BLOCKED: reviewed AppArmor checksum mismatch' >&2; exit 2;
}
profiles=/sys/kernel/security/apparmor/profiles
[[ -r "$profiles" ]] || {
  echo 'BLOCKED: cannot inspect loaded AppArmor names' >&2; exit 2;
}
if grep -Fq "$lab_profile (" "$profiles"; then
  echo 'BLOCKED: lab policy already loaded; inspect it manually, do not replace' >&2; exit 2
fi
workdir=$(mktemp -d /tmp/mochilab-feasibility.XXXXXX)
lab_profile_file="$workdir/lab.apparmor"
lab_seccomp_file="$workdir/nested-bwrap-feasibility-seccomp.json"
lab_log="$workdir/result.txt"
lab_container="mochilab-bwrap-feasibility-$(date +%s)-${BASHPID}"
# Fail before loading any host policy if the disposable container name is invalid.
if [[ ! "$lab_container" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
  echo 'BLOCKED: invalid generated disposable lab container name' >&2
  exit 2
fi
profile_loaded=0
cleanup() {
  # The owned lab container is the only Docker object this script may remove.
  if docker container inspect "$lab_container" >/dev/null 2>&1; then
    owner=$(docker inspect -f '{{index .Config.Labels "mochilab.lab-owner"}}' "$lab_container" 2>/dev/null || true)
    if [[ "$owner" != "$lab_container" ]]; then
      echo "WARNING: refusing cleanup of non-owned container $lab_container" >&2
      return
    fi
    docker rm -f "$lab_container" >/dev/null 2>&1 || {
      echo "WARNING: disposable lab container still present: $lab_container" >&2
    }
  fi
  if (( profile_loaded == 1 )); then
    if docker container inspect "$lab_container" >/dev/null 2>&1; then
      echo "WARNING: cannot safely unload lab AppArmor while lab container remains" >&2
      echo "Lab policy source retained for manual rollback: $lab_profile_file" >&2
      return
    fi
    if ! apparmor_parser -R -T -K "$lab_profile_file"; then
      echo "WARNING: lab profile removal failed; inspect $lab_profile before manual cleanup" >&2
      echo "Lab policy source retained: $lab_profile_file" >&2
      return
    fi
    if grep -Fq "$lab_profile (" "$profiles"; then
      echo "WARNING: lab AppArmor profile still loaded after unload attempt" >&2
      echo "Lab policy source retained: $lab_profile_file" >&2
      return
    fi
    profile_loaded=0
    echo 'LAB_PROFILE_CLEANUP=CONFIRMED_REMOVED'
  fi
  rm -rf -- "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - "$seccomp_input" "$apparmor_input" "$lab_seccomp_file" "$lab_profile_file" "$lab_profile" <<'PY'
import json
from pathlib import Path
import sys

seccomp_src, apparmor_src, seccomp_dst, apparmor_dst, label = sys.argv[1:]
seccomp = json.loads(Path(seccomp_src).read_text())
assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"
assert seccomp["defaultErrnoRet"] == 1
assert isinstance(seccomp["syscalls"], list)
assert not any("pivot_root" in r.get("names", []) for r in seccomp["syscalls"])
# CI-only full setup allowances following the audited OpenClaw Docker test
# design, not a suggested rule set for the production OpenBot container.
# Seccomp cannot restrict mount/pivot_root by source/target paths or namespace.
seccomp["syscalls"].extend([
    {
        "names": ["mount"], "action": "SCMP_ACT_ALLOW",
        "comment": "DISPOSABLE LAB: userns-local Bubblewrap mounts; DO NOT DEPLOY",
    },
    {
        "names": ["pivot_root"], "action": "SCMP_ACT_ALLOW",
        "comment": "DISPOSABLE LAB: pivot root in userns; DO NOT DEPLOY",
    },
    {
        "names": ["umount2"], "action": "SCMP_ACT_ALLOW",
        "args": [{"index": 1, "value": 2, "op": "SCMP_CMP_EQ"}],
        "comment": "DISPOSABLE LAB: MNT_DETACH only; DO NOT DEPLOY",
    },
])
Path(seccomp_dst).write_text(json.dumps(seccomp, indent=2) + "\n")

aa = Path(apparmor_src).read_text()
assert aa.count("profile mochilab-openbot flags=") == 1
assert aa.count("  deny mount,\n") == 1
aa = aa.replace("mochilab-openbot", label)
# AppArmor CI-style container rules. Broader than production; retained only
# for ephemeral, non-networked, non-volume, non-root and capability-dropped Lab.
mount_rules = """  mount options=(rw,rslave,silent) -> /,
  mount options=(rw,rprivate,silent) -> /oldroot/,
  mount options=(rw,bind) /** -> /**,
  mount options=(rw,rbind) /** -> /**,
  remount options in (ro,rw,bind,nosuid,nodev,noexec,relatime,noatime,nodiratime,silent) /**,
  mount fstype=tmpfs options=(rw,nosuid,nodev) -> /**,
  mount fstype=proc options=(rw,nosuid,nodev,noexec) -> /**,
  mount fstype=devpts options=(rw,nosuid,noexec) -> /**,
  pivot_root,
"""
aa = aa.replace("  deny mount,\n", mount_rules, 1)
assert "  deny mount,\n" not in aa
assert "  mount,\n" not in aa
assert "  pivot_root,\n" in aa
Path(apparmor_dst).write_text(aa)
PY
# Parser-only check; neither --prepare nor parsing modifies kernel policy.
apparmor_parser -Q -T -K "$lab_profile_file" >/dev/null || {
  echo 'BLOCKED: Lab AppArmor rule unsupported by this host; nothing loaded' >&2; exit 2;
}
echo 'PARSER_CHECK=PASS CANDIDATE=FULL_BWRAP_SETUP_LAB_ONLY (NOT PRODUCTION)'
echo 'LAB_ONLY=mount+pivot_root+umount2(MNT_DETACH); APPARMOR=SCOPED_MOUNT_RULES_AND_PIVOT; NOT_PRODUCTION_SAFE'
echo 'PRODUCTION_POLICY_UNCHANGED=YES PRODUCT_DATA_UNTOUCHED=YES'
if [[ "$mode" == --prepare ]]; then
  echo 'RESULT=LAB_POLICY_PARSE_ONLY; no Docker lab run, no loaded profile'
  exit 0
fi
[[ -t 0 ]] || {
  echo 'BLOCKED: --run requires interactive operator confirmation' >&2; exit 2;
}
echo 'This loads a NEW temporary AppArmor profile into the HOST kernel for a disposable Docker Lab.'
echo 'Lab permits nested mount and pivot operations, but has no network, host binds, Docker socket or production data.'
echo 'Type RUN-LAB-FEASIBILITY to authorize this disposable experiment.'
read -r answer
[[ "$answer" == RUN-LAB-FEASIBILITY ]] || { echo 'CANCELLED: no host policy loaded'; exit 2; }
if grep -Fq "$lab_profile (" "$profiles"; then
  echo 'BLOCKED: lab profile appeared concurrently' >&2; exit 2
fi
# A unique profile, never the production apparmor profile.
apparmor_parser -r -T -K "$lab_profile_file"
profile_loaded=1
grep -Fxq "$lab_profile (enforce)" "$profiles" || {
  echo 'BLOCKED: lab profile not confirmed in enforce mode' >&2; exit 2;
}
echo 'LAB_PROFILE=LOADED_ENFORCE'
echo 'NETWORK=NONE HOST_DATA=NONE HOST_BINDS=NONE DOCKER_SOCKET=NONE'
echo 'EXTRA_CAPABILITIES=NONE HOST_POLICY_PRODUCTION=UNCHANGED'
set +e
timeout --signal=TERM --kill-after=5s 65s docker run --rm --pull never \
  --name "$lab_container" --label "mochilab.lab-owner=$lab_container" \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --memory 512m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /data:rw,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --security-opt "seccomp=$lab_seccomp_file" \
  --security-opt "apparmor=$lab_profile" \
  --security-opt no-new-privileges:true \
  --entrypoint /bin/sh "$image" -c '
    set -eu
    printf "UID="; id -u
    printf "APPARMOR="; cat /proc/self/attr/current
    printf "NETWORK=NONE; LAB_FILES_ONLY=YES\n"
    mkdir -p /data/workspace /data/outside
    printf "outer only\n" > /data/outside/outer-canary.txt
    test -w /data/outside || exit 60
    echo "OUTER_WRITE_CANARY=WRITABLE"
    if bwrap --unshare-user --unshare-pid --ro-bind / / --proc /proc --dev /dev /bin/true; then
      echo "BWRAP_WITH_PROC=PASS"
    else
      echo "BWRAP_WITH_PROC=FAILED_FALLBACK_WILL_BE_TESTED"
    fi
    if bwrap --unshare-user --unshare-pid --ro-bind / / \
      --bind /data/workspace /data/workspace --tmpfs /tmp --dev /dev \
      /bin/sh -c "
        printf inside > /data/workspace/inside-created.txt || exit 71
        if (printf forbidden > /data/outside/should-not-exist.txt) 2>/dev/null; then
          echo OUTSIDE_WRITE=UNEXPECTED_ALLOWED
          exit 72
        fi
        echo OUTSIDE_WRITE=BLOCKED
      "; then
      echo "BWRAP_WRITE_COMMAND=PASS"
    else
      echo "BWRAP_WRITE_COMMAND=FAIL"
      exit 73
    fi
    test -f /data/workspace/inside-created.txt || exit 74
    test ! -e /data/outside/should-not-exist.txt || exit 75
    echo "BWRAP_WRITE_CONTAINMENT=PASS"
    echo "LAB_RESULT=COMPLETE"
  ' >"$lab_log" 2>&1
rc=$?
set -e
cat "$lab_log"
if (( rc == 124 || rc == 137 )); then
  echo 'RESULT=LAB_TIMEOUT; NOT A PASS'
elif (( rc != 0 )); then
  echo "RESULT=LAB_FAILED code=$rc; see first error above; NOT A PASS"
elif grep -Fq 'BWRAP_WRITE_CONTAINMENT=PASS' "$lab_log" \
  && grep -Fq 'OUTER_WRITE_CANARY=WRITABLE' "$lab_log" \
  && grep -Fq 'OUTSIDE_WRITE=BLOCKED' "$lab_log"; then
  echo 'RESULT=DISPOSABLE_LAB_BWRAP_AND_WRITE_CONTAINMENT_PASS'
  echo 'STILL_NOT_TESTED=ACTUAL_CODEX_CLI_PRODUCTION_POLICY_OR_SECRETS_CONFIDENTIALITY'
else
  echo 'RESULT=LAB_EVIDENCE_INCOMPLETE_OR_UNSAFE'
fi
echo 'NEXT=REVIEW_AND_RECORD_ONLY; NO_PRODUCTION_UPDATE'
