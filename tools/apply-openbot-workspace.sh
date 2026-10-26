#!/usr/bin/env bash
# Mochilab OpenBot Workspace-only scoped production change.
# UmbrelOS HOST ONLY. No app update, format, network or host privilege changes.
# --check (read only), --apply (offline backup/app recreate/self-test),
# --rollback BACKUP_DIRECTORY (restore original config only).
set -Eeuo pipefail
echo 'BLOCKED=V1_UNSUPPORTED_ON_UMBRELOS_2_USE_TOOLS_APPLY_OPENBOT_WORKSPACE_V2_SH' >&2
exit 2
umask 077
MODE="$1"
APP_ID=mochilab-openbot
ROOT=/home/umbrel/umbrel
APP="$ROOT/app-data/$APP_ID"
DATA="$APP/data"
EXTERNAL="$ROOT/external/mochi-external"
APP_SCRIPT="$ROOT/scripts/app"
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../deploy/workspace-only" && pwd -P)"
OLD_COMPOSE=70dcead64b8e499f45cd63fbad89165926f19212
OLD_HOOK=3c981033751a830e72e48c18227a3e236d64a38c
OLD_PROFILE=fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a
OLD_SECCOMP=6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418
NEW_COMPOSE=2304568c73393c4d885b10a12ab4b323df3af57a
NEW_HOOK=564e4ddbae114120dccc92516b4342d417fbf963
NEW_PROFILE=afd0d87e7a09e39afad12864fb988586ce95104e
NEW_SECCOMP=4fa610c6303f4610844dc6ae0da5546030a77cbb
BACKUP=""
NEEDS_ROLLBACK=0

fail() { printf 'BLOCKED=%s\n' "$1" >&2; exit 2; }
sha() { git hash-object -- "$1"; }
check_file() {
  [[ -f "$1" && ! -L "$1" ]] || fail "MISSING_OR_SYMLINK_FILE"
  [[ "$(sha "$1")" == "$2" ]] || fail "FILE_HASH_DRIFT"
}
require() { command -v "$1" >/dev/null 2>&1 || fail "MISSING_PROGRAM_$1"; }
backup_config_ok() {
  [[ -f "$BACKUP/config/docker-compose.yml" && -f "$BACKUP/config/pre-start" ]] || return 1
  [[ "$(sha "$BACKUP/config/docker-compose.yml")" == "$OLD_COMPOSE" ]] || return 1
  [[ "$(sha "$BACKUP/config/pre-start")" == "$OLD_HOOK" ]] || return 1
  [[ "$(sha "$BACKUP/config/mochilab-openbot.apparmor")" == "$OLD_PROFILE" ]] || return 1
  [[ "$(sha "$BACKUP/config/seccomp-0.49.0.json")" == "$OLD_SECCOMP" ]] || return 1
}
running_id() {
  docker ps -q --filter "label=com.docker.compose.project=$APP_ID" \
    --filter "label=com.docker.compose.service=openbot" | head -n 1
}
rollback_config() {
  echo 'ROLLBACK=RESTORE_ORIGINAL_CONFIG'
  if ! backup_config_ok; then echo 'CRITICAL=ROLLBACK_CONFIG_BACKUP_INVALID' >&2; return 1; fi
  "$APP_SCRIPT" stop "$APP_ID" >/dev/null 2>&1 || true
  cp -a -- "$BACKUP/config/docker-compose.yml" "$APP/docker-compose.yml"
  cp -a -- "$BACKUP/config/pre-start" "$APP/hooks/pre-start"
  cp -a -- "$BACKUP/config/mochilab-openbot.apparmor" "$APP/hooks/mochilab-openbot.apparmor"
  cp -a -- "$BACKUP/config/seccomp-0.49.0.json" "$APP/seccomp-0.49.0.json"
  check_file "$APP/docker-compose.yml" "$OLD_COMPOSE"
  check_file "$APP/hooks/pre-start" "$OLD_HOOK"
  "$APP_SCRIPT" start "$APP_ID" >/dev/null || return 1
  local id
  id=$(running_id)
  [[ -n "$id" && "$(docker inspect -f '{{.AppArmorProfile}}' "$id")" == mochilab-openbot ]] || return 1
  echo 'ROLLBACK=ORIGINAL_PROFILE_RUNNING'
  echo 'DATA_VOLUME=NOT_MODIFIED_OR_RESTORED'
}
on_exit() {
  local rc="$?"
  trap - EXIT
  if (( NEEDS_ROLLBACK == 1 )); then
    echo "APPLY_FAILED=ATTEMPTING_AUTOMATIC_CONFIG_ROLLBACK code=$rc" >&2
    if rollback_config; then echo 'AUTOMATIC_ROLLBACK=PASS'; else echo 'CRITICAL=ROLLBACK_REQUIRES_MANUAL_RECOVERY' >&2; fi
    echo "BACKUP_DIRECTORY=$BACKUP"
  fi
  exit "$rc"
}
[[ $EUID -eq 0 ]] || fail USE_SUDO_ON_UMBREL_HOST
[[ "$MODE" == --check || "$MODE" == --apply || "$MODE" == --rollback ]] || fail INVALID_MODE
for cmd in docker git findmnt mountpoint stat realpath du df rsync apparmor_parser timeout; do require "$cmd"; done
[[ -d "$APP" && -d "$DATA" && -x "$APP_SCRIPT" ]] || fail UMBREL_APP_ROOT_OR_APP_SCRIPT_NOT_FOUND
[[ "$(realpath -e "$APP")" == "$APP" ]] || fail APP_PATH_UNEXPECTED
[[ -d "$EXTERNAL" && ! -L "$EXTERNAL" ]] || fail EXTERNAL_MISSING
mountpoint -q "$EXTERNAL" || fail EXTERNAL_NOT_MOUNTED
[[ "$(findmnt -T "$EXTERNAL" -no TARGET)" == "$EXTERNAL" ]] || fail EXTERNAL_MOUNT_TARGET_UNEXPECTED
fs=$(findmnt -T "$EXTERNAL" -no FSTYPE)
[[ "$fs" == ext4 || "$fs" == xfs || "$fs" == btrfs ]] || fail EXTERNAL_PERMISSIONS_FILESYSTEM_UNSUPPORTED
[[ "$(stat -c %d "$EXTERNAL")" != "$(stat -c %d "$DATA")" ]] || fail BACKUP_NOT_ON_INDEPENDENT_FILESYSTEM

if [[ "$MODE" == --rollback ]]; then
  [[ "$#" -eq 2 ]] || fail ROLLBACK_REQUIRES_BACKUP_DIRECTORY
  BACKUP=$(realpath -e "$2") || fail BACKUP_NOT_FOUND
  case "$BACKUP" in "$EXTERNAL"/.mochilab-openbot-workspace-rollback.*) ;; *) fail ROLLBACK_DIRECTORY_NOT_OWNED ;; esac
  [[ -f "$BACKUP/rollback.marker" ]] || fail ROLLBACK_MARKER_MISSING
  backup_config_ok || fail ROLLBACK_CONFIG_INVALID
  rollback_config
  exit
fi
[[ "$#" -eq 1 ]] || fail EXCESS_ARGUMENTS
for spec in \
  "docker-compose.yml:$OLD_COMPOSE" \
  "hooks/pre-start:$OLD_HOOK" \
  "hooks/mochilab-openbot.apparmor:$OLD_PROFILE" \
  "seccomp-0.49.0.json:$OLD_SECCOMP"; do
  rel="${spec%%:*}"
  expected="${spec##*:}"
  check_file "$APP/$rel" "$expected"
done
[[ ! -e "$APP/hooks/mochilab-openbot-workspace.apparmor" && ! -e "$APP/seccomp-workspace.json" ]] || fail WORKSPACE_ARTIFACT_ALREADY_PRESENT
check_file "$SOURCE/docker-compose.yml" "$NEW_COMPOSE"
check_file "$SOURCE/pre-start" "$NEW_HOOK"
check_file "$SOURCE/mochilab-openbot-workspace.apparmor" "$NEW_PROFILE"
check_file "$SOURCE/seccomp-workspace.json" "$NEW_SECCOMP"
apparmor_parser -Q -T -K "$SOURCE/mochilab-openbot-workspace.apparmor" >/dev/null || fail APPARMOR_PARSE_FAILED
id=$(running_id)
[[ -n "$id" ]] || fail NO_RUNNING_OPENBOT_CONTAINER
[[ "$(docker inspect -f '{{.AppArmorProfile}}' "$id")" == mochilab-openbot ]] || fail ORIGINAL_PROFILE_CHANGED
[[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$id")" == false ]] || fail PRIVILEGED_CONTAINER
[[ "$(docker inspect -f '{{json .HostConfig.CapAdd}}' "$id")" == null ]] || fail EXTRA_CAPABILITIES_FOUND
opts=$(docker inspect -f '{{json .HostConfig.SecurityOpt}}' "$id")
[[ "$opts" == *'apparmor=mochilab-openbot'* && "$opts" == *'no-new-privileges:true'* && "$opts" == *'seccomp='* ]] || fail SECURITY_OPT_DRIFT
actual_data=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$id")
[[ "$actual_data" == "$DATA" ]] || fail LIVE_DATA_MOUNT_DRIFT
data_bytes=$(du -sb -- "$DATA" | cut -f1)
free_bytes=$(df -B1 --output=avail "$EXTERNAL" | tail -n 1 | tr -d ' ')
[[ "$data_bytes" =~ ^[0-9]+$ && "$free_bytes" =~ ^[0-9]+$ ]] || fail DISK_SIZE_UNAVAILABLE
(( free_bytes > data_bytes + data_bytes / 3 + 1073741824 )) || fail INSUFFICIENT_EXTERNAL_BACKUP_CAPACITY
echo 'APP_BASELINE=PINNED_VERIFIED'
echo 'SCOPED_APPARMOR_PARSE=PASS'
echo 'EXTERNAL_BACKUP=SEPARATE_MOUNT_PERMISSIONS_SUPPORTED'
echo "DATA_BYTES=$data_bytes"
echo "EXTERNAL_AVAILABLE_BYTES=$free_bytes"
echo 'PRODUCTION_CHANGE=NONE_YET'
if [[ "$MODE" == --check ]]; then echo 'RESULT=PRECHECK_PASS'; exit 0; fi

[[ -t 0 ]] || fail REQUIRES_INTERACTIVE_SSH
echo 'Will stop ONLY OpenBot, copy its entire /data to a NEW private external folder,'
echo 'apply scoped AppArmor/Seccomp with no-new-privileges, and recreate OpenBot.'
echo 'Any startup or native sandbox failure triggers the original-config rollback.'
echo 'Type APPLY-OPENBOT-WORKSPACE to proceed:'
read -r approval
[[ "$approval" == APPLY-OPENBOT-WORKSPACE ]] || fail CANCELLED
BACKUP=$(mktemp -d "$EXTERNAL/.mochilab-openbot-workspace-rollback.XXXXXXXX")
chmod 0700 "$BACKUP"
mkdir -m 0700 "$BACKUP/config"
printf '%s\n' 'mochilab-openbot-workspace-rollback-v1' > "$BACKUP/rollback.marker"
cp -a -- "$APP/docker-compose.yml" "$BACKUP/config/docker-compose.yml"
cp -a -- "$APP/hooks/pre-start" "$BACKUP/config/pre-start"
cp -a -- "$APP/hooks/mochilab-openbot.apparmor" "$BACKUP/config/mochilab-openbot.apparmor"
cp -a -- "$APP/seccomp-0.49.0.json" "$BACKUP/config/seccomp-0.49.0.json"
backup_config_ok || fail ORIGINAL_CONFIG_BACKUP_MISMATCH
NEEDS_ROLLBACK=1
trap on_exit EXIT
echo 'CHECKPOINT=ORIGINAL_CONFIG_COPIED'
timeout --signal=TERM --kill-after=15s 180s "$APP_SCRIPT" stop "$APP_ID" >/dev/null
echo 'CHECKPOINT=OPENBOT_STOPPED_FOR_CONSISTENT_COPY'
mkdir -m 0700 "$BACKUP/data"
rsync -aHAX --numeric-ids -- "$DATA/" "$BACKUP/data/" >/dev/null
changes=$(rsync -aHAXnc --delete --itemize-changes --numeric-ids -- "$DATA/" "$BACKUP/data/")
[[ -z "$changes" ]] || fail OFFLINE_DATA_BACKUP_VERIFICATION_FAILED
sync
echo 'OFFLINE_OPENBOT_DATA_COPY=VERIFIED_WITH_RSYNC_CHECKSUM'
cp -a -- "$SOURCE/docker-compose.yml" "$APP/docker-compose.yml"
cp -a -- "$SOURCE/pre-start" "$APP/hooks/pre-start"
cp -a -- "$SOURCE/mochilab-openbot-workspace.apparmor" "$APP/hooks/mochilab-openbot-workspace.apparmor"
cp -a -- "$SOURCE/seccomp-workspace.json" "$APP/seccomp-workspace.json"
chmod 0755 "$APP/hooks/pre-start"
chmod 0644 "$APP/hooks/mochilab-openbot-workspace.apparmor" "$APP/seccomp-workspace.json" "$APP/docker-compose.yml"
check_file "$APP/docker-compose.yml" "$NEW_COMPOSE"
check_file "$APP/hooks/pre-start" "$NEW_HOOK"
check_file "$APP/hooks/mochilab-openbot-workspace.apparmor" "$NEW_PROFILE"
check_file "$APP/seccomp-workspace.json" "$NEW_SECCOMP"
echo 'CHECKPOINT=NEW_POLICIES_INSTALLED'
timeout --signal=TERM --kill-after=15s 180s "$APP_SCRIPT" start "$APP_ID" >/dev/null
new_id=$(running_id)
[[ -n "$new_id" && "$(docker inspect -f '{{.AppArmorProfile}}' "$new_id")" == mochilab-openbot-workspace ]] || fail NEW_CONTAINER_PROFILE_NOT_ENFORCED
new_opts=$(docker inspect -f '{{json .HostConfig.SecurityOpt}}' "$new_id")
[[ "$new_opts" == *'apparmor=mochilab-openbot-workspace'* && "$new_opts" == *'no-new-privileges:true'* && "$new_opts" == *'seccomp='* ]] || fail NEW_CONTAINER_SECURITY_OPTS_INVALID
[[ "$(docker inspect -f '{{json .HostConfig.CapDrop}}' "$new_id")" == *ALL* ]] || fail NEW_CONTAINER_CAP_DROP_MISSING
echo 'CHECKPOINT=NEW_CONTAINER_SECURITY_OPTIONS_VERIFIED'

# No LLM, network request, secrets, or real Agent workspace. Only generated test files.
docker exec -i --user 1000:1000 "$new_id" /bin/bash -se <<'CODEX_TEST'
set -euo pipefail
codex=/data/.config/OpenBot/provider-runtimes/codex/linux-x64/0.164.0/bin/codex
[[ -x "$codex" ]] || { echo 'CODEX_RUNTIME_MISSING'; exit 71; }
dir=$(mktemp -d /data/.mochilab-codex-test.XXXXXXXX)
trap 'rm -rf -- "$dir"' EXIT
mkdir "$dir/workspace" "$dir/outside" "$dir/home"
printf 'baseline' > "$dir/outside/baseline.txt"
[[ -w "$dir/outside" ]] || exit 72
ln -s "$dir/outside" "$dir/workspace/outside-link"
cd "$dir/workspace"
HOME="$dir/home" CODEX_HOME="$dir/home" "$codex" \
  -c 'sandbox_mode="workspace-write"' \
  -c 'features.use_legacy_landlock=false' \
  sandbox -- /bin/sh -c "
    printf 'okay' > '$dir/workspace/inside.txt' || exit 73
    if (printf 'bad' > '$dir/outside/forbidden.txt') 2>/dev/null; then exit 74; fi
    if (printf 'bad' > '$dir/workspace/outside-link/bypass.txt') 2>/dev/null; then exit 75; fi
    echo NATIVE_CODEX_DENIAL=PASS
  "
[[ -f "$dir/workspace/inside.txt" ]] || exit 76
[[ ! -e "$dir/outside/forbidden.txt" && ! -e "$dir/outside/bypass.txt" ]] || exit 77
echo 'NATIVE_CODEX_WORKSPACE=PASS'
CODEX_TEST
echo 'PRODUCTION_NATIVE_CODEX_SANDBOX=PASS'
NEEDS_ROLLBACK=0
trap - EXIT
echo "ROLLBACK_DIRECTORY=$BACKUP"
echo 'LIVE_OPENBOT_AGENT_UI_TEST=REQUIRED'
echo 'RESULT=PRODUCTION_POLICY_APPLIED_NATIVE_TEST_PASSED_AGENT_NOT_YET_VERIFIED'
