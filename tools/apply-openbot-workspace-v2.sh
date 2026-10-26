#!/usr/bin/env bash
# V2 retired: strict hash of UmbrelOS-managed docker-compose.yml is invalid.
# Never stage this candidate as it replaces the live generated Compose file.
printf 'BLOCKED=V2_RETIRED_UMBREL_RUNTIME_COMPOSE_REQUIRES_SEMANTIC_PATCH\n' >&2
exit 2
# Mochilab OpenBot Workspace only -- UmbrelOS 2.x compatible manual checkpoints.
# This script NEVER starts/stops apps itself. Lifecycle is through Umbrel MCP only.
# --check     read-only inspection while OpenBot is RUNNING
# --stage     off-line backup and config install while OpenBot is STOPPED
# --verify    native Codex synthetic containment test after MCP start
# --rollback <backup> restore original config while OpenBot is STOPPED
set -Eeuo pipefail
umask 077
if (( $# < 1 )); then echo 'BLOCKED=MODE_REQUIRED'; exit 2; fi
MODE="$1"
case "$MODE" in
  --check|--stage|--verify) (( $# == 1 )) || { echo 'BLOCKED=EXTRA_ARGUMENTS'; exit 2; };;
  --rollback) (( $# == 2 )) || { echo 'BLOCKED=ROLLBACK_PATH_REQUIRED'; exit 2; };;
  *) echo 'BLOCKED=UNKNOWN_MODE'; exit 2;;
esac

APP_ID=mochilab-openbot
ROOT=/home/umbrel/umbrel
APP="$ROOT/app-data/$APP_ID"
DATA="$APP/data"
EXTERNAL="$ROOT/external/mochi-external"
SOURCE="$(cd -- "$(dirname -- "$0")/../deploy/workspace-only" && pwd -P)"
OLD_COMPOSE=70dcead64b8e499f45cd63fbad89165926f19212
OLD_HOOK=3c981033751a830e72e48c18227a3e236d64a38c
OLD_AA=fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a
OLD_SECCOMP=6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418
NEW_COMPOSE=2304568c73393c4d885b10a12ab4b323df3af57a
NEW_HOOK=564e4ddbae114120dccc92516b4342d417fbf963
NEW_AA=afd0d87e7a09e39afad12864fb988586ce95104e
NEW_SECCOMP=4fa610c6303f4610844dc6ae0da5546030a77cbb
BACKUP=""
CONFIG_MODIFIED=0

fail() { echo "BLOCKED=$1" >&2; exit 2; }
require() { command -v "$1" >/dev/null 2>&1 || fail "MISSING_COMMAND_$1"; }
hash_file() { git hash-object -- "$1"; }
verify_file() {
  [[ -f "$1" && ! -L "$1" ]] || fail "FILE_MISSING_OR_SYMLINK:$(basename "$1")"
  [[ "$(hash_file "$1")" == "$2" ]] || fail "FILE_HASH_DRIFT:$(basename "$1")"
}
check_original() {
  verify_file "$APP/docker-compose.yml" "$OLD_COMPOSE"
  verify_file "$APP/hooks/pre-start" "$OLD_HOOK"
  verify_file "$APP/hooks/mochilab-openbot.apparmor" "$OLD_AA"
  verify_file "$APP/seccomp-0.49.0.json" "$OLD_SECCOMP"
}
check_staged() {
  verify_file "$APP/docker-compose.yml" "$NEW_COMPOSE"
  verify_file "$APP/hooks/pre-start" "$NEW_HOOK"
  verify_file "$APP/hooks/mochilab-openbot-workspace.apparmor" "$NEW_AA"
  verify_file "$APP/seccomp-workspace.json" "$NEW_SECCOMP"
}
check_candidate() {
  verify_file "$SOURCE/docker-compose.yml" "$NEW_COMPOSE"
  verify_file "$SOURCE/pre-start" "$NEW_HOOK"
  verify_file "$SOURCE/mochilab-openbot-workspace.apparmor" "$NEW_AA"
  verify_file "$SOURCE/seccomp-workspace.json" "$NEW_SECCOMP"
  apparmor_parser -Q -T -K "$SOURCE/mochilab-openbot-workspace.apparmor" >/dev/null || fail APPARMOR_CANDIDATE_PARSE_FAILED
}
container_id() {
  docker ps -q --filter "label=com.docker.compose.project=$APP_ID" \
    --filter 'label=com.docker.compose.service=openbot' | head -n 1
}
check_running_original() {
  local id actual_data
  id=$(container_id)
  [[ -n "$id" ]] || fail OPENBOT_NOT_RUNNING
  [[ "$(docker inspect -f '{{.AppArmorProfile}}' "$id")" == mochilab-openbot ]] || fail APPARMOR_BASELINE_DRIFT
  [[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$id")" == false ]] || fail PRIVILEGED_BASELINE
  [[ "$(docker inspect -f '{{json .HostConfig.CapAdd}}' "$id")" == null ]] || fail ADDITIONAL_CAPABILITIES_FOUND
  actual_data=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$id")
  [[ "$(realpath -e "$actual_data")" == "$DATA" ]] || fail DATA_BIND_SOURCE_DRIFT
}
check_stopped() {
  [[ -z "$(container_id)" ]] || fail OPENBOT_STILL_RUNNING_USE_UMBREL_MCP_STOP
  [[ -z "$(docker ps -q --filter "label=com.docker.compose.project=$APP_ID")" ]] || fail OTHER_OPENBOT_SERVICE_STILL_RUNNING
}
check_external() {
  [[ -d "$EXTERNAL" && ! -L "$EXTERNAL" ]] || fail EXTERNAL_DRIVE_MISSING
  mountpoint -q "$EXTERNAL" || fail EXTERNAL_DRIVE_NOT_MOUNTED
  [[ "$(findmnt -T "$EXTERNAL" -no TARGET)" == "$EXTERNAL" ]] || fail EXTERNAL_MOUNT_DRIFT
  local fs bytes free
  fs=$(findmnt -T "$EXTERNAL" -no FSTYPE)
  [[ "$fs" == ext4 || "$fs" == xfs || "$fs" == btrfs ]] || fail EXTERNAL_FILESYSTEM_CANNOT_PRESERVE_LINUX_PERMISSIONS
  [[ "$(stat -c %d "$EXTERNAL")" != "$(stat -c %d "$DATA")" ]] || fail BACKUP_NOT_INDEPENDENT_DISK
  bytes=$(du -sb -- "$DATA" | cut -f1)
  free=$(df -B1 --output=avail "$EXTERNAL" | tail -n 1 | tr -d ' ')
  [[ "$bytes" =~ ^[0-9]+$ && "$free" =~ ^[0-9]+$ ]] || fail SPACE_INSPECTION_UNAVAILABLE
  (( free > bytes + bytes / 3 + 1073741824 )) || fail EXTERNAL_SPACE_NOT_ENOUGH
  echo "DATA_SIZE_BYTES=$bytes"
  echo "EXTERNAL_FREE_BYTES=$free"
  echo 'INDEPENDENT_EXTERNAL_MOUNT=PASS'
}
check_backup_config() {
  [[ -f "$BACKUP/created.by-mochilab-workspace-v2" ]] || return 1
  [[ "$(hash_file "$BACKUP/config/docker-compose.yml")" == "$OLD_COMPOSE" ]] || return 1
  [[ "$(hash_file "$BACKUP/config/pre-start")" == "$OLD_HOOK" ]] || return 1
  [[ "$(hash_file "$BACKUP/config/mochilab-openbot.apparmor")" == "$OLD_AA" ]] || return 1
  [[ "$(hash_file "$BACKUP/config/seccomp-0.49.0.json")" == "$OLD_SECCOMP" ]] || return 1
}
restore_config() {
  check_backup_config || return 1
  cp -a -- "$BACKUP/config/docker-compose.yml" "$APP/docker-compose.yml"
  cp -a -- "$BACKUP/config/pre-start" "$APP/hooks/pre-start"
  cp -a -- "$BACKUP/config/mochilab-openbot.apparmor" "$APP/hooks/mochilab-openbot.apparmor"
  cp -a -- "$BACKUP/config/seccomp-0.49.0.json" "$APP/seccomp-0.49.0.json"
  check_original
}
on_stage_exit() {
  local rc="$?"
  trap - EXIT
  if (( CONFIG_MODIFIED == 1 )); then
    echo "STAGE_ERROR=ATTEMPT_RESTORE_CONFIG code=$rc" >&2
    if restore_config; then echo 'ORIGINAL_CONFIG_RESTORED=PASS'; else echo 'CRITICAL=MANUAL_CONFIG_RECOVERY_REQUIRED' >&2; fi
  fi
  if [[ -n "$BACKUP" ]]; then echo "RECOVERY_COPY_LOCATION=$BACKUP"; fi
  echo 'OPENBOT_REMAINS_STOPPED=YES'
  exit "$rc"
}
if (( EUID != 0 )); then fail USE_SUDO_UMBREL_HOST; fi
for tool in docker git realpath stat findmnt mountpoint du df rsync apparmor_parser; do require "$tool"; done
[[ -d "$APP" && -d "$DATA" && ! -L "$DATA" ]] || fail APP_ROOT_DATA_MISSING
[[ "$(realpath -e "$APP")" == "$APP" ]] || fail APP_ROOT_UNEXPECTED
[[ "$(realpath -e "$DATA")" == "$DATA" ]] || fail DATA_SYMLINK_UNEXPECTED

case "$MODE" in
  --check)
    check_original
    check_running_original
    [[ ! -e "$APP/hooks/mochilab-openbot-workspace.apparmor" && ! -e "$APP/seccomp-workspace.json" ]] || fail NEW_ARTIFACT_EXISTS
    check_candidate
    check_external
    echo 'APP_BASELINE=PASS'
    echo 'CANDIDATE_POLICY_PARSE=PASS'
    echo 'PRODUCTION_CHANGE=NONE'
    echo 'RESULT=PRECHECK_PASS_NEXT_UMBREL_MCP_STOP'
    ;;
  --stage)
    check_stopped
    check_original
    [[ ! -e "$APP/hooks/mochilab-openbot-workspace.apparmor" && ! -e "$APP/seccomp-workspace.json" ]] || fail NEW_ARTIFACT_EXISTS
    check_candidate
    check_external
    BACKUP=$(mktemp -d "$EXTERNAL/.mochilab-openbot-workspace-v2.XXXXXXXX")
    chmod 0700 "$BACKUP"
    mkdir -m 0700 "$BACKUP/config" "$BACKUP/data"
    echo mochilab-openbot-workspace-v2 > "$BACKUP/created.by-mochilab-workspace-v2"
    cp -a -- "$APP/docker-compose.yml" "$BACKUP/config/docker-compose.yml"
    cp -a -- "$APP/hooks/pre-start" "$BACKUP/config/pre-start"
    cp -a -- "$APP/hooks/mochilab-openbot.apparmor" "$BACKUP/config/mochilab-openbot.apparmor"
    cp -a -- "$APP/seccomp-0.49.0.json" "$BACKUP/config/seccomp-0.49.0.json"
    check_backup_config || fail BACKUP_CONFIG_FAILED
    echo 'BACKUP_CONFIG=VERIFIED'
    # OpenBot must already be stopped by Umbrel MCP. Copy remains off-line.
    rsync -aHAX --numeric-ids -- "$DATA/" "$BACKUP/data/" >/dev/null || fail BACKUP_COPY_FAILED
    differences=$(rsync -aHAXnc --delete --itemize-changes --numeric-ids -- "$DATA/" "$BACKUP/data/")
    [[ -z "$differences" ]] || fail BACKUP_CHECKSUM_VERIFICATION_FAILED
    sync
    echo 'OFFLINE_DATA_COPY=CHECKSUM_VERIFIED'
    trap on_stage_exit EXIT
    CONFIG_MODIFIED=1
    cp -a -- "$SOURCE/docker-compose.yml" "$APP/docker-compose.yml"
    cp -a -- "$SOURCE/pre-start" "$APP/hooks/pre-start"
    cp -a -- "$SOURCE/mochilab-openbot-workspace.apparmor" "$APP/hooks/mochilab-openbot-workspace.apparmor"
    cp -a -- "$SOURCE/seccomp-workspace.json" "$APP/seccomp-workspace.json"
    chmod 0755 "$APP/hooks/pre-start"
    chmod 0644 "$APP/hooks/mochilab-openbot-workspace.apparmor" "$APP/seccomp-workspace.json" "$APP/docker-compose.yml"
    check_staged
    CONFIG_MODIFIED=0
    trap - EXIT
    echo "RECOVERY_COPY_LOCATION=$BACKUP"
    echo 'OPENBOT_REMAINS_STOPPED=YES'
    echo 'RESULT=STAGED_NEXT_UMBREL_MCP_START'
    ;;
  --verify)
    check_staged
    id=$(container_id)
    [[ -n "$id" ]] || fail NEW_OPENBOT_NOT_RUNNING
    [[ "$(docker inspect -f '{{.AppArmorProfile}}' "$id")" == mochilab-openbot-workspace ]] || fail NEW_APPARMOR_NOT_ENFORCED
    [[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$id")" == false ]] || fail PRIVILEGED_CONTAINER
    opts=$(docker inspect -f '{{json .HostConfig.SecurityOpt}}' "$id")
    [[ "$opts" == *'no-new-privileges:true'* && "$opts" == *'apparmor=mochilab-openbot-workspace'* && "$opts" == *'seccomp='* ]] || fail SECURITY_OPTS_WRONG
    [[ "$(docker inspect -f '{{json .HostConfig.CapDrop}}' "$id")" == *ALL* ]] || fail CAP_DROP_MISSING
    # No LLM calls/credentials. Test only synthetic files inside current app /data.
    docker exec -i --user 1000:1000 "$id" /bin/bash -se <<'CODEX_TEST'
set -Eeuo pipefail
codex=/data/.config/OpenBot/provider-runtimes/codex/linux-x64/0.164.0/bin/codex
[[ -x "$codex" ]] || { echo 'FAIL=CODEX_RUNTIME_NOT_AVAILABLE'; exit 71; }
testroot=$(mktemp -d /data/.mochilab-sandbox-check.XXXXXXXX)
trap 'rm -rf -- "$testroot"' EXIT
mkdir -p "$testroot/workspace" "$testroot/outside" "$testroot/home"
printf baseline > "$testroot/outside/base"
[[ -w "$testroot/outside" ]] || exit 72
ln -s "$testroot/outside" "$testroot/workspace/escape"
cd "$testroot/workspace"
HOME="$testroot/home" CODEX_HOME="$testroot/home" "$codex" \
  -c 'sandbox_mode="workspace-write"' -c 'features.use_legacy_landlock=false' \
  sandbox -- /bin/sh -c "
    printf allowed > '$testroot/workspace/inside' || exit 73
    if (printf forbidden > '$testroot/outside/direct') 2>/dev/null; then exit 74; fi
    if (printf forbidden > '$testroot/workspace/escape/symlink') 2>/dev/null; then exit 75; fi
    echo 'NATIVE_CODEX_DENIAL=PASS'
  "
[[ -f "$testroot/workspace/inside" ]] || exit 76
[[ ! -e "$testroot/outside/direct" && ! -e "$testroot/outside/symlink" ]] || exit 77
echo 'NATIVE_CODEX_SYNTHETIC_WORKSPACE=PASS'
CODEX_TEST
    echo 'RESULT=PRODUCTION_NATIVE_TEST_PASS_AGENT_UI_NOT_TESTED'
    ;;
  --rollback)
    check_stopped
    BACKUP=$(realpath -e "$2") || fail BACKUP_PATH_MISSING
    case "$BACKUP" in "$EXTERNAL"/.mochilab-openbot-workspace-v2.*) ;; *) fail ROLLBACK_PATH_OUTSIDE_OWNED_PREFIX;; esac
    check_backup_config || fail BACKUP_CONFIG_INTEGRITY_FAILED
    # Keep candidate files inactive. Never overwrite or delete source /data.
    restore_config
    echo 'ORIGINAL_CONFIG_RESTORED=PASS'
    echo 'OPENBOT_REMAINS_STOPPED=YES'
    echo 'RESULT=ROLLBACK_CONFIG_NEXT_UMBREL_MCP_START'
    ;;
esac
