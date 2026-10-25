#!/usr/bin/env bash
# Mochilab: first mount policy experiment, ONLY disposable Docker lab.
# Intentionally does not enable full bubblewrap/Codex workspace execution.
# Do not use this profile/JSON in production Docker Compose.
set -euo pipefail
if (( $# != 1 )) || [[ "$1" != --prepare && "$1" != --run ]]; then
  echo 'Usage: sudo bash tools/lab-bwrap-first-mount.sh --prepare|--run' >&2
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
lab_profile=mochilab-openbot-bwrap-first-mount-lab
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
workdir=$(mktemp -d /tmp/mochilab-first-mount.XXXXXX)
lab_profile_file="$workdir/lab.apparmor"
lab_seccomp_file="$workdir/first-mount-seccomp.json"
lab_log="$workdir/result.txt"
lab_container="mochilab-bwrap-first-$(date +%s)-$$"
profile_loaded=0
cleanup() {
  # The owned lab container is the only Docker object this script may remove.
  if docker container inspect "$lab_container" >/dev/null 2>&1; then
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
    profile_loaded=0
  fi
  rm -rf -- "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - "$seccomp_input" "$apparmor_input" "$lab_seccomp_file" "$lab_profile_file" "$lab_profile" <<'PY'
import json
import pathlib
import sys

seccomp_src, apparmor_src, seccomp_dst, apparmor_dst, label = sys.argv[1:]
seccomp = json.loads(pathlib.Path(seccomp_src).read_text())
assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"
assert seccomp["defaultErrnoRet"] == 1
assert isinstance(seccomp["syscalls"], list)
# Bitwise exact MS_SILENT | MS_SLAVE | MS_REC from bubblewrap v0.9.0.
flags = 32768 | 524288 | 16384
assert flags == 573440
seccomp["syscalls"].append({
    "names": ["mount"],
    "action": "SCMP_ACT_ALLOW",
    "args": [{"index": 3, "value": flags, "op": "SCMP_CMP_EQ"}],
    "comment": "LAB ONLY: first bwrap mount propagation, not a production exception",
})
pathlib.Path(seccomp_dst).write_text(json.dumps(seccomp, indent=2) + "\n")

aa = pathlib.Path(apparmor_src).read_text()
assert aa.count("profile mochilab-openbot flags=") == 1
assert aa.count("  deny mount,\n") == 1
aa = aa.replace("mochilab-openbot", label)
aa = aa.replace("  deny mount,\n", "  mount options=(rslave,silent) /,\n")
assert "  deny mount,\n" not in aa
assert "  mount,\n" not in aa
pathlib.Path(apparmor_dst).write_text(aa)
PY
# Parser-only check; neither --prepare nor parsing modifies kernel policy.
apparmor_parser -Q -T -K "$lab_profile_file" >/dev/null || {
  echo 'BLOCKED: Lab AppArmor rule unsupported by this host; nothing loaded' >&2; exit 2;
}
echo 'PARSER_CHECK=PASS CANDIDATE=FIRST_MOUNT_ONLY (NOT COMPLETE)'
echo 'SECCOMP_ONLY=mount(flags=0x8c000) LAB_APPARMOR_ONLY=mount(rslave,silent) to root'
echo 'PRODUCTION_POLICY_UNCHANGED=YES PRODUCT_DATA_UNTOUCHED=YES'
if [[ "$mode" == --prepare ]]; then
  echo 'RESULT=LAB_POLICY_PARSE_ONLY; no Docker lab run, no loaded profile'
  exit 0
fi
[[ -t 0 ]] || {
  echo 'BLOCKED: --run requires interactive operator confirmation' >&2; exit 2;
}
echo 'This loads a NEW, temporary AppArmor lab profile into the HOST kernel.'
echo 'It does not replace production profile. Type RUN-LAB to continue.'
read -r answer
[[ "$answer" == RUN-LAB ]] || { echo 'CANCELLED: no host policy loaded'; exit 2; }
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
timeout --signal=TERM --kill-after=5s 50s docker run --rm --pull never \
  --name "$lab_container" --network none --read-only --user 1000:1000 \
  --memory 512m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /data:rw,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --security-opt "seccomp=$lab_seccomp_file" \
  --security-opt "apparmor=$lab_profile" \
  --security-opt no-new-privileges:true \
  --entrypoint /bin/sh "$image" -c '
    printf "UID="; id -u
    printf "APPARMOR="; cat /proc/self/attr/current
    unshare --user --map-root-user /usr/bin/id >/dev/null 2>&1
    printf "USERNS_EXIT=%s\n" "$?"
    bwrap --unshare-user --unshare-pid --ro-bind / / --proc /proc --dev /dev /bin/true
    printf "BWRAP_EXIT=%s\n" "$?"
    exit 0
  ' >"$lab_log" 2>&1
rc=$?
set -e
cat "$lab_log"
if (( rc == 124 || rc == 137 )); then
  echo 'RESULT=LAB_TIMEOUT; no verdict'
elif (( rc != 0 )); then
  echo "RESULT=LAB_CONTAINER_ERROR code=$rc"
elif grep -Fq 'Failed to make / slave' "$lab_log"; then
  echo 'RESULT=FIRST_MOUNT_STILL_DENIED; inspect effective AppArmor rule'
elif grep -Fq 'Failed to mount tmpfs' "$lab_log"; then
  echo 'RESULT=FIRST_MOUNT_ADVANCED_TO_TMPFS; NOT A FULL SANDBOX PASS'
elif grep -Fq 'BWRAP_EXIT=0' "$lab_log"; then
  echo 'RESULT=MINIMAL_BWRAP_SUCCESS; NEGATIVE_WRITE_TESTS_STILL_REQUIRED'
else
  echo 'RESULT=NEXT_BLOCKER_UNKNOWN; preserve redacted log'
fi
echo 'NEXT=REVIEW_AND_RECORD_ONLY; NO_PRODUCTION_UPDATE'
