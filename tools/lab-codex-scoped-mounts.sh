#!/usr/bin/env bash
# Mochilab: LIMITED-MOUNT target/pivot-root real Codex 0.164.0 Lab only.
# Uses the same disposable no-network/no-host-data setup that passed earlier.
# Replaces broad AppArmor mount/pivot rules with narrowly scoped targets.
# Do not use this profile/JSON in production Docker Compose.
set -euo pipefail
if (( $# != 1 )) || [[ "$1" != --prepare && "$1" != --run ]]; then
  echo 'Usage: sudo bash tools/lab-codex-scoped-mounts.sh --prepare|--run' >&2
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
lab_profile=mochilab-openbot-codex-scoped-lab
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
# Only a specifically installed and observed Codex v0.164.0 executable is bind mounted.
# A SINGLE executable file is not the production /data directory or auth store.
codex_bin="$mounted_data/.config/OpenBot/provider-runtimes/codex/linux-x64/0.164.0/bin/codex"
[[ -f "$codex_bin" && ! -L "$codex_bin" ]] || {
  echo 'BLOCKED: expected installed Codex binary missing/not a regular file' >&2; exit 2;
}
[[ "$(realpath -e "$codex_bin")" == "$codex_bin" ]] || {
  echo 'BLOCKED: codex binary path resolves unexpectedly' >&2; exit 2;
}
[[ "$(stat -c %s "$codex_bin")" == 308139304 ]] || {
  echo 'BLOCKED: expected installed Codex binary size changed; review the runtime version' >&2; exit 2;
}
printf 'CODEX_BINARY_VERIFIED_PATH=YES VERSION_FOLDER=0.164.0 SIZE_BYTES=308139304\n'
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
workdir=$(mktemp -d /tmp/mochilab-codex-scoped.XXXXXX)
lab_profile_file="$workdir/lab.apparmor"
lab_seccomp_file="$workdir/codex-scoped-lab-seccomp.json"
lab_log="$workdir/result.txt"
lab_container="mochilab-codex-scoped-$(date +%s)-${BASHPID}"
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
# Scoped path/flag policy adapted from the Bubblewrap AppArmor abstraction,
# https://github.com/roddhjav/apparmor.d/blob/main/apparmor.d/abstractions/bwrap
# and Codex/Bubblewrap 0.9 behavior. Not approved for Production.
mount_rules = """  mount options=(rw,rslave,silent) -> /,
  mount options=(rw,rprivate,silent) -> /oldroot/,
  mount options=(rw,rbind) /tmp/newroot/ -> /tmp/newroot/,
  mount options=(rw,rbind) /** -> /newroot/{,**},
  mount options=(rw,bind) /** -> /newroot/{,**},
  mount options=(rw,rbind) /oldroot/proc/ -> /proc/,
  mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /tmp/,
  mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /newroot/{,**},
  mount fstype=devpts options=(rw,nosuid,noexec) devpts -> /newroot/dev/pts/,
  mount fstype=proc options=(rw,nosuid,nodev,noexec) proc -> /newroot/proc/,
  remount /newroot/{,**},
  pivot_root oldroot=/tmp/oldroot/ /tmp/,
  pivot_root oldroot=/newroot/ /newroot/,
"""
assert "  mount,\n" not in mount_rules
assert "  pivot_root,\n" not in mount_rules
aa = aa.replace("  deny mount,\n", mount_rules, 1)
assert "  deny mount,\n" not in aa
assert "  mount,\n" not in aa
assert "  pivot_root,\n" not in aa
assert "  pivot_root oldroot=/tmp/oldroot/ /tmp/,\n" in aa
Path(apparmor_dst).write_text(aa)
PY
# Parser-only check; neither --prepare nor parsing modifies kernel policy.
apparmor_parser -Q -T -K "$lab_profile_file" >/dev/null || {
  echo 'BLOCKED: Lab AppArmor rule unsupported by this host; nothing loaded' >&2; exit 2;
}
echo 'PARSER_CHECK=PASS CANDIDATE=SCOPED_BWRAP_MOUNT_LAB_NOT_PRODUCTION'
echo 'LAB_ONLY=SECCOMP_MOUNT_PIVOT_UMOUNT; APPARMOR=SCOPED_MOUNTS_AND_PIVOTS; NOT_DEPLOYED'
echo 'PRODUCTION_POLICY_UNCHANGED=YES PRODUCT_DATA_UNTOUCHED=YES'
if [[ "$mode" == --prepare ]]; then
  echo 'RESULT=LAB_POLICY_PARSE_ONLY; no Docker lab run, no loaded profile'
  exit 0
fi
[[ -t 0 ]] || {
  echo 'BLOCKED: --run requires interactive operator confirmation' >&2; exit 2;
}
echo 'Loads ONE temporary enforce-mode AppArmor Lab profile with scoped mount targets and pivot-root paths.'
echo 'Lab-only syscalls are expanded but AppArmor mount targets are scoped; no production data, network, credentials or Docker socket.'
echo 'Type RUN-SCOPED-LAB to authorize this disposable experiment.'
read -r answer
[[ "$answer" == RUN-SCOPED-LAB ]] || { echo 'CANCELLED: no host policy loaded'; exit 2; }
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
timeout --signal=TERM --kill-after=5s 75s docker run --rm --pull never \
  --name "$lab_container" --label "mochilab.lab-owner=$lab_container" \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --memory 768m --cpus 1 --pids-limit 96 \
  --tmpfs /tmp:rw,nosuid,nodev,size=96m,mode=1777 \
  --tmpfs /data:rw,nosuid,nodev,size=48m,uid=1000,gid=1000,mode=0755 \
  --mount "type=bind,source=$codex_bin,target=/usr/local/bin/codex-lab,readonly" \
  --env HOME=/data --env CODEX_HOME=/data/codex-home \
  --security-opt "seccomp=$lab_seccomp_file" \
  --security-opt "apparmor=$lab_profile" \
  --security-opt no-new-privileges:true \
  --entrypoint /bin/sh "$image" -c '
    set -eu
    printf "UID="; id -u
    printf "APPARMOR="; cat /proc/self/attr/current
    printf "NETWORK=NONE, ONLY_READONLY_CODEX_EXECUTABLE_BIND=YES\n"
    mkdir -p /data/workspace /data/outside /data/codex-home
    printf outer > /data/outside/outside-canary.txt
    ln -s /data/outside /data/workspace/escape-link
    test -w /data/outside || { echo "OUTER_WRITE_CANARY=FAILED"; exit 60; }
    echo "OUTER_WRITE_CANARY=WRITABLE"
    /usr/local/bin/codex-lab --version || { echo "CODEX_BINARY=NOT_EXECUTABLE"; exit 61; }
    echo "CODEX_BINARY=EXECUTABLE"
    cd /data/workspace
    /usr/local/bin/codex-lab -c "sandbox_mode=\"workspace-write\"" \
      -c "features.use_legacy_landlock=false" \
      sandbox -- /bin/sh -c "
        printf native-codex-inside > /data/workspace/native-codex-created.txt || exit 71
        if (printf bad > /data/workspace/escape-link/escape-attempt.txt) 2>/dev/null; then
          echo SYMLINK_ESCAPE=UNEXPECTED_ALLOWED
          exit 76
        fi
        echo SYMLINK_ESCAPE=BLOCKED
        if (printf forbidden > /data/outside/native-codex-outside.txt) 2>/dev/null; then
          echo NATIVE_CODEX_OUTSIDE_WRITE=UNEXPECTED_ALLOWED
          exit 72
        fi
        echo NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED
      " || { echo "NATIVE_CODEX_SANDBOX_COMMAND=FAILED"; exit 73; }
    test -f /data/workspace/native-codex-created.txt || exit 74
    test ! -e /data/outside/native-codex-outside.txt || exit 75
    test ! -e /data/outside/escape-attempt.txt || exit 77
    echo "NATIVE_CODEX_WORKSPACE_WRITE=PASS"
    echo "NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED"
    echo "NATIVE_CODEX_SANDBOX=PASS"
    echo "NARROW_MOUNT_RULES=ENFORCED"
  ' >"$lab_log" 2>&1
rc=$?
set -e
cat "$lab_log"
if (( rc == 124 || rc == 137 )); then
  echo 'RESULT=CODEX_LAB_TIMEOUT; NOT A PASS'
elif (( rc != 0 )); then
  echo "RESULT=CODEX_LAB_FAILED code=$rc; see first error above; NOT A PASS"
elif grep -Fq 'NATIVE_CODEX_SANDBOX=PASS' "$lab_log" \
  && grep -Fq 'SYMLINK_ESCAPE=BLOCKED' "$lab_log" \
  && grep -Fq 'NATIVE_CODEX_WORKSPACE_WRITE=PASS' "$lab_log" \
  && grep -Fq 'NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED' "$lab_log" \
  && grep -Fq 'OUTER_WRITE_CANARY=WRITABLE' "$lab_log"; then
  echo 'RESULT=REAL_CODEX_0_164_0_SCOPED_MOUNTS_WORKSPACE_PASS'
  echo 'STILL_NOT_TESTED=OPENBOT_AGENT_PROVIDER_AUTH_OR_PRODUCTION_POLICY'
else
  echo 'RESULT=CODEX_LAB_INCOMPLETE_OR_UNSAFE'
fi
echo 'NEXT=REVIEW_AND_RECORD_ONLY; NO_PRODUCTION_UPDATE'
