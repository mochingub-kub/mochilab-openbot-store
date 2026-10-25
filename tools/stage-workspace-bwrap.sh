#!/usr/bin/env bash
# Disposable Bubblewrap baseline. No production Docker app, data or policy edit.
set -euo pipefail
if (( $# != 0 )); then echo 'Usage: sudo bash tools/stage-workspace-bwrap.sh' >&2; exit 2; fi
if [[ "$EUID" -ne 0 ]]; then echo 'BLOCKED: use UmbrelOS Host sudo, not Portainer' >&2; exit 2; fi
for cmd in docker git timeout; do
  command -v "$cmd" >/dev/null || { echo "BLOCKED: missing $cmd" >&2; exit 2; }
done
prod=mochilab-openbot_openbot_1
[[ "$(docker inspect -f '{{.State.Running}}' "$prod" 2>/dev/null || true)" == true ]] || {
  echo 'BLOCKED: production container not running' >&2; exit 2;
}
image=$(docker inspect -f '{{.Image}}' "$prod")
[[ "$image" == sha256:* ]] || { echo 'BLOCKED: immutable image unavailable' >&2; exit 2; }
mounted_data=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$prod")
[[ "$mounted_data" == /* && -d "$mounted_data" && "$(basename -- "$mounted_data")" == data ]] || {
  echo 'BLOCKED: /data mount not recognized' >&2; exit 2;
}
app_root=$(dirname -- "$mounted_data")
[[ "$app_root" != / && -f "$app_root/docker-compose.yml" ]] || {
  echo 'BLOCKED: app folder not recognized' >&2; exit 2;
}
seccomp="$app_root/seccomp-0.49.0.json"
apparmor="$app_root/hooks/mochilab-openbot.apparmor"
[[ -f "$seccomp" && -f "$apparmor" ]] || { echo 'BLOCKED: policy file missing' >&2; exit 2; }
[[ "$(git hash-object "$seccomp")" == 6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418 ]] || {
  echo 'BLOCKED: seccomp differs from pinned upstream' >&2; exit 2;
}
[[ "$(git hash-object "$apparmor")" == fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a ]] || {
  echo 'BLOCKED: AppArmor differs from reviewed repository source' >&2; exit 2;
}
opts=$(docker inspect -f '{{json .HostConfig.SecurityOpt}}' "$prod")
[[ "$opts" == *'apparmor=mochilab-openbot'* && "$opts" == *'no-new-privileges:true'* && "$opts" == *'seccomp='* ]] || {
  echo 'BLOCKED: effective production security options changed' >&2; exit 2;
}
[[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$prod")" == false ]] || {
  echo 'BLOCKED: production Privileged changed' >&2; exit 2;
}
[[ "$(docker inspect -f '{{json .HostConfig.CapAdd}}' "$prod")" == null ]] || {
  echo 'BLOCKED: added Linux capabilities found' >&2; exit 2;
}
[[ "$(docker inspect -f '{{.AppArmorProfile}}' "$prod")" == mochilab-openbot ]] || {
  echo 'BLOCKED: loaded AppArmor label differs' >&2; exit 2;
}
lab="mochilab-bwrap-lab-$(date +%s)-$$"
cleanup() {
  if docker container inspect "$lab" >/dev/null 2>&1; then
    docker rm -f "$lab" >/dev/null 2>&1 || echo "WARNING: lab container left: $lab" >&2
  fi
}
trap cleanup EXIT INT TERM
echo 'LAB_SCOPE=DISPOSABLE_ONLY NETWORK=NONE HOST_BINDS=NONE NO_NEW_CAPABILITIES=YES'
echo 'PRODUCTION_RESTART=NO APP_POLICY_CHANGE=NO DATA_CHANGE=NO'
echo 'LOADED_APPARMOR_PROFILE_CONTENT=NOT_VERIFIED'
set +e
timeout --signal=TERM --kill-after=5s 50s docker run --rm --pull never \
  --name "$lab" --network none --read-only --user 1000:1000 \
  --memory 512m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --tmpfs /data:rw,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --security-opt "seccomp=$seccomp" \
  --security-opt apparmor=mochilab-openbot \
  --security-opt no-new-privileges:true \
  --entrypoint /bin/sh "$image" -c '
    printf "UID="; id -u
    printf "APPARMOR="; cat /proc/self/attr/current
    printf "BWRAP_VERSION="; bwrap --version
    unshare --user --map-root-user /usr/bin/id >/dev/null 2>&1
    printf "USERNS_EXIT=%s\n" "$?"
    bwrap --unshare-user --unshare-pid --ro-bind / / --proc /proc --dev /dev /bin/true
    printf "BWRAP_EXIT=%s\n" "$?"
    exit 0
  '
rc=$?
set -e
if (( rc == 124 || rc == 137 )); then echo 'RESULT=LAB_TIMEOUT; no verdict'; exit 2; fi
if (( rc != 0 )); then echo "RESULT=LAB_START_FAILED DockerExit=$rc"; exit 2; fi
echo 'RESULT=BASELINE_RECORDED; NO_POLICY_REPAIR'
echo 'NOT_TESTED: actual Codex sandbox, writes, outside-denials, persistence'
