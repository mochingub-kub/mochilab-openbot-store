#!/usr/bin/env bash
# Mochilab: FINAL LAB GATE for parent/child AppArmor exec-domain isolation.
# Production parent DENY mount persists while /usr/bin/bwrap transitions into
# an isolated child policy. The whole Docker seccomp permits bwrap syscalls,
# but AppArmor parent must still block mount. No production policy change.
# Do not use this profile/JSON in production Docker Compose.
set -euo pipefail
if (( $# != 1 )) || [[ "$1" != --prepare && "$1" != --run ]]; then
  echo 'Usage: sudo bash tools/lab-codex-profile-split.sh --prepare|--run' >&2
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
lab_profile=mochilab-openbot-codex-split-lab
child_profile=mochilab-openbot-codex-split-bwrap-lab
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
bwrap_resolved=$(docker exec --user 1000:1000 "$prod" /bin/sh -c 'command -v bwrap' 2>/dev/null || true)
[[ "$bwrap_resolved" == /usr/bin/bwrap ]] || {
  echo "BLOCKED: bwrap is not /usr/bin/bwrap, actual=$bwrap_resolved" >&2; exit 2;
}
bwrap_owner=$(docker exec --user 1000:1000 "$prod" /usr/bin/stat -c %u /usr/bin/bwrap 2>/dev/null || true)
[[ "$bwrap_owner" == 0 ]] || {
  echo 'BLOCKED: bwrap executable not root-owned; cannot use as transition gate' >&2; exit 2;
}
echo 'SYSTEM_BWRAP=ROOT_OWNED_PATH_VERIFIED'
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
if grep -Fq "$lab_profile (" "$profiles" || grep -Fq "$child_profile (" "$profiles"; then
  echo 'BLOCKED: one of the Lab policies already loaded; inspect first' >&2; exit 2
fi
workdir=$(mktemp -d /tmp/mochilab-codex-split.XXXXXX)
lab_profile_file="$workdir/lab.apparmor"
lab_seccomp_file="$workdir/codex-split-lab-seccomp.json"
lab_log="$workdir/result.txt"
lab_container="mochilab-codex-split-$(date +%s)-${BASHPID}"
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
    if grep -Fq "$lab_profile (" "$profiles" || grep -Fq "$child_profile (" "$profiles"; then
      echo "WARNING: one of the Lab AppArmor profiles still loaded after unload attempt" >&2
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
python3 - "$seccomp_input" "$apparmor_input" "$lab_seccomp_file" "$lab_profile_file" "$lab_profile" "$child_profile" <<'PY'
import json
from pathlib import Path
import sys

seccomp_src, aa_src, seccomp_dst, aa_dst, parent, child = sys.argv[1:]
seccomp = json.loads(Path(seccomp_src).read_text())
assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"
assert seccomp["defaultErrnoRet"] == 1
assert isinstance(seccomp["syscalls"], list)
assert not any("pivot_root" in r.get("names", []) for r in seccomp["syscalls"])
# The OUTER Seccomp filter is still broad for this disposable test: Seccomp
# cannot inspect executable identity or paths. The parent AppArmor profile
# MUST deny mounts; only the separately labelled system bwrap may perform them.
seccomp["syscalls"].extend([
    {"names": ["mount"], "action": "SCMP_ACT_ALLOW",
     "comment": "LAB ONLY: child Bwrap syscall scope; do not deploy without review"},
    {"names": ["pivot_root"], "action": "SCMP_ACT_ALLOW",
     "comment": "LAB ONLY: child Bwrap syscall scope; do not deploy without review"},
    {"names": ["umount2"], "action": "SCMP_ACT_ALLOW",
     "args": [{"index": 1, "value": 2, "op": "SCMP_CMP_EQ"}],
     "comment": "LAB ONLY: child Bwrap unmount; MNT_DETACH only"}
])
Path(seccomp_dst).write_text(json.dumps(seccomp, indent=2) + "\n")

source = Path(aa_src).read_text()
assert source.count("profile mochilab-openbot flags=") == 1
assert source.count("  deny mount,\n") == 1
assert source.count("  userns create,\n") == 1
assert parent != child
assert "lab" in parent and "lab" in child
assert "  file,\n" in source
parent_aa = source.replace("mochilab-openbot", parent)
# Px gives an exact-path, fail-closed, secure-exec transition.
# The original deny mount stays in the parent unchanged.
parent_aa = parent_aa.replace(
    "  deny mount,\n",
    f"  /usr/bin/bwrap Px -> {child},\n\n  deny mount,\n",
    1,
)
assert "  deny mount,\n" in parent_aa
assert "  mount,\n" not in parent_aa
assert "/usr/bin/bwrap Px ->" in parent_aa
child_mounts = """  mount options=(rw,rslave,silent) -> /,
  mount options=(rw,rprivate,silent) -> /oldroot/,
  mount options=(rw,bind) /** -> /**,
  mount options=(rw,rbind) /** -> /**,
  remount options in (ro,rw,bind,nosuid,nodev,noexec,relatime,noatime,nodiratime,silent) /**,
  mount fstype=tmpfs options=(rw,nosuid,nodev) -> /**,
  mount fstype=proc options=(rw,nosuid,nodev,noexec) -> /**,
  mount fstype=devpts options=(rw,nosuid,noexec) -> /**,
  pivot_root,
"""
child_aa = source.replace("mochilab-openbot", child)
child_aa = child_aa.replace("  deny mount,\n", child_mounts, 1)
assert "  deny mount,\n" not in child_aa
assert "  pivot_root,\n" in child_aa
Path(aa_dst).write_text(parent_aa + "\n" + child_aa)
PY
# Parser-only check; neither --prepare nor parsing modifies kernel policy.
apparmor_parser -Q -T -K "$lab_profile_file" >/dev/null || {
  echo 'BLOCKED: Lab AppArmor rule unsupported by this host; nothing loaded' >&2; exit 2;
}
echo 'PARSER_CHECK=PASS CANDIDATE=PARENT_CHILD_APPARMOR_SPLIT_NOT_PRODUCTION'
echo 'LAB_ONLY=SECCOMP_SETUP_OPS; APPARMOR_PARENT_DENIES_MOUNT; CHILD_ONLY_ON_BWRAP_EXEC; NOT_DEPLOYED'
echo 'PRODUCTION_POLICY_UNCHANGED=YES PRODUCT_DATA_UNTOUCHED=YES'
if [[ "$mode" == --prepare ]]; then
  echo 'RESULT=LAB_POLICY_PARSE_ONLY; no Docker lab run, no loaded profile'
  exit 0
fi
[[ -t 0 ]] || {
  echo 'BLOCKED: --run requires interactive operator confirmation' >&2; exit 2;
}
echo 'Loads TWO temporary enforcing Lab AppArmor profiles: parent denies mount; system /usr/bin/bwrap transitions to child on exec.'
echo 'LAB ONLY: child has mount/pivot permissions; parent denies mounts; one Codex executable is read-only. No production data directory, auth, network, or Docker socket.'
echo 'Type RUN-SPLIT-LAB to authorize this disposable experiment.'
read -r answer
[[ "$answer" == RUN-SPLIT-LAB ]] || { echo 'CANCELLED: no host policy loaded'; exit 2; }
if grep -Fq "$lab_profile (" "$profiles" || grep -Fq "$child_profile (" "$profiles"; then
  echo 'BLOCKED: one of the Lab profiles appeared concurrently' >&2; exit 2
fi
# A unique profile, never the production apparmor profile.
profile_loaded=1
apparmor_parser -r -T -K "$lab_profile_file"
grep -Fxq "$lab_profile (enforce)" "$profiles" || {
  echo 'BLOCKED: parent profile not confirmed in enforce mode' >&2; exit 2;
}
grep -Fxq "$child_profile (enforce)" "$profiles" || {
  echo 'BLOCKED: child profile not confirmed in enforce mode' >&2; exit 2;
}
echo 'LAB_PROFILES=PARENT_AND_CHILD_LOADED_ENFORCE'
echo 'NETWORK=NONE HOST_DATA=NONE ONLY_READONLY_CODEX_BINARY_BIND=YES DOCKER_SOCKET=NONE'
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
    cat /proc/self/attr/current | grep -Fq "mochilab-openbot-codex-split-lab (enforce)" || {
      echo "PARENT_APPARMOR=NOT_ENFORCED"; exit 64;
    }
    echo "PARENT_APPARMOR=ENFORCED"
    printf "NETWORK=NONE, ONLY_READONLY_CODEX_EXECUTABLE_BIND=YES\n"
    mkdir -p /data/workspace /data/outside /data/codex-home
    printf outer > /data/outside/outside-canary.txt
    test -w /data/outside || { echo "OUTER_WRITE_CANARY=FAILED"; exit 60; }
    echo "OUTER_WRITE_CANARY=WRITABLE"
    /usr/local/bin/codex-lab --version || { echo "CODEX_BINARY=NOT_EXECUTABLE"; exit 61; }
    echo "CODEX_BINARY=EXECUTABLE"
    cd /data/workspace
    /usr/local/bin/codex-lab -c "sandbox_mode=\"workspace-write\"" \
      -c "features.use_legacy_landlock=false" \
      sandbox -- /bin/sh -c "
        if ! cat /proc/self/attr/current | grep -Fq mochilab-openbot-codex-split-bwrap-lab; then
          echo BWRAP_TRANSITION=FAILED
          exit 76
        fi
        echo BWRAP_TRANSITION=CONFIRMED
        printf native-codex-inside > /data/workspace/native-codex-created.txt || exit 71
        if (printf forbidden > /data/outside/native-codex-outside.txt) 2>/dev/null; then
          echo NATIVE_CODEX_OUTSIDE_WRITE=UNEXPECTED_ALLOWED
          exit 72
        fi
        echo NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED
      " || { echo "NATIVE_CODEX_SANDBOX_COMMAND=FAILED"; exit 73; }
    test -f /data/workspace/native-codex-created.txt || exit 74
    test ! -e /data/outside/native-codex-outside.txt || exit 75
    echo "NATIVE_CODEX_WORKSPACE_WRITE=PASS"
    echo "NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED"
    echo "NATIVE_CODEX_SANDBOX=PASS"
    echo "APPARMOR_SPLIT=PASS"
  ' >"$lab_log" 2>&1
rc=$?
set -e
cat "$lab_log"
if (( rc == 124 || rc == 137 )); then
  echo 'RESULT=CODEX_LAB_TIMEOUT; NOT A PASS'
elif (( rc != 0 )); then
  echo "RESULT=CODEX_LAB_FAILED code=$rc; see first error above; NOT A PASS"
elif grep -Fq 'NATIVE_CODEX_SANDBOX=PASS' "$lab_log" \
  && grep -Fq 'PARENT_APPARMOR=ENFORCED' "$lab_log" \
  && grep -Fq 'BWRAP_TRANSITION=CONFIRMED' "$lab_log" \
  && grep -Fq 'NATIVE_CODEX_WORKSPACE_WRITE=PASS' "$lab_log" \
  && grep -Fq 'NATIVE_CODEX_OUTSIDE_WRITE=BLOCKED' "$lab_log" \
  && grep -Fq 'OUTER_WRITE_CANARY=WRITABLE' "$lab_log"; then
  echo 'RESULT=CODEX_APPARMOR_PARENT_CHILD_SPLIT_AND_WRITE_CONTAINMENT_PASS'
  echo 'STILL_NOT_TESTED=OPENBOT_AGENT_PROVIDER_AUTH_AND_PRODUCTION_ROLLBACK_AND_RESTART'
else
  echo 'RESULT=CODEX_LAB_INCOMPLETE_OR_UNSAFE'
fi
echo 'NEXT=REVIEW_AND_RECORD_ONLY; NO_PRODUCTION_UPDATE'
