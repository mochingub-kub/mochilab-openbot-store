#!/usr/bin/env bash
# Mochilab / UmbrelOS OpenBot: READ-ONLY backup preflight.
# Run on UmbrelOS Host SSH, not Portainer or an OpenBot Agent.
# No data writes, app lifecycle changes, disk changes or credentials.
set -euo pipefail

die() { printf 'BLOCKED: %s\n' "$*" >&2; exit 2; }
if (( $# != 0 && $# != 2 )); then
  die 'Usage: sudo bash tools/preflight-openbot-backup.sh [--candidate /actual/host/mount/path]'
fi
if (( $# == 2 )) && [[ "$1" != "--candidate" ]]; then
  die 'Only --candidate /actual/host/mount/path is supported'
fi
if (( EUID != 0 )); then die 'Run with sudo on the UmbrelOS Host'; fi
for cmd in docker realpath findmnt df lsblk stat du basename; do
  command -v "$cmd" >/dev/null || die "Missing read-only utility: $cmd"
done

container=mochilab-openbot_openbot_1
docker container inspect "$container" >/dev/null 2>&1 || die 'Expected OpenBot Docker container not found'
state=$(docker inspect --format '{{.State.Running}}' "$container")
image=$(docker inspect --format '{{.Config.Image}}' "$container")
privileged=$(docker inspect --format '{{.HostConfig.Privileged}}' "$container")
added_caps=$(docker inspect --format '{{json .HostConfig.CapAdd}}' "$container")
profile=$(docker inspect --format '{{.AppArmorProfile}}' "$container")
[[ "$image" == "ghcr.io/nightly-labs/openbot:0.49.0" ]] || die 'Current OpenBot image is not 0.49.0; stop'
[[ "$privileged" == false && "$added_caps" == null && "$profile" == "mochilab-openbot" ]] ||
  die 'Live container security baseline differs from reviewed configuration'
data_mount=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$container")
data_type=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}{{end}}{{end}}' "$container")
[[ "$data_type" == bind && "$data_mount" == /* && -d "$data_mount" ]] ||
  die 'Live /data is not expected bind mount'
data=$(realpath -e -- "$data_mount") || die 'Cannot resolve mounted /data'
[[ "$data" != / && "$(basename -- "$data")" == data ]] ||
  die 'Unexpected /data source; manual inspection required'

echo "PRODUCTION_RUNNING=$state PRODUCTION_IMAGE=$image"
echo "SECURITY_PROFILE=$profile ADDITIONAL_CAPABILITIES=NONE"
echo "DATA_SOURCE=$data"
du -sh -- "$data" | sed 's/^/DATA_SIZE=/'
for rel in ".config/OpenBot/openbot.db" ".local/share/keyrings" ".config/openbot-container" "OpenBot/Agents" "OpenBot/Shared"; do
  if [[ -e "$data/$rel" ]]; then
    printf 'RECOVERY_COMPONENT=%s PRESENT\n' "$rel"
  else
    printf 'RECOVERY_COMPONENT=%s NOT_FOUND_OR_DIFFERENT_LAYOUT\n' "$rel"
  fi
done
echo "DATA_FILESYSTEM:"
findmnt -T "$data" -n -o TARGET,SOURCE,FSTYPE,MAJ:MIN || die 'Cannot inspect data filesystem'
echo "AVAILABLE_BLOCK_DEVICES_AND_MOUNTPOINTS:"
lsblk -e 7 -o NAME,TRAN,TYPE,SIZE,FSTYPE,MOUNTPOINTS
echo "BACKUP_TOOL_AVAILABILITY:"
for cmd in gpg age tar sha256sum sqlite3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "TOOL=$cmd PRESENT"
  else
    echo "TOOL=$cmd MISSING"
  fi
done

if (( $# == 2 )); then
  [[ "$2" == /* && -d "$2" ]] || die 'Candidate must be an existing absolute HOST directory'
  candidate=$(realpath -e -- "$2") || die 'Cannot resolve candidate'
  [[ "$candidate" != / && "$candidate" != "$data" && "$candidate" != "$data/"* ]] ||
    die 'Candidate is root or within OpenBot original data'
  src_device=$(findmnt -T "$data" -n -o MAJ:MIN) || die 'Cannot identify source filesystem'
  dst_device=$(findmnt -T "$candidate" -n -o MAJ:MIN) || die 'Cannot identify destination filesystem'
  [[ -n "$src_device" && -n "$dst_device" && "$src_device" != "$dst_device" ]] ||
    die 'Candidate shares source filesystem or identity is unknown'
  echo "CANDIDATE=$candidate"
  echo "CANDIDATE_FILESYSTEM:"
  findmnt -T "$candidate" -n -o TARGET,SOURCE,FSTYPE,MAJ:MIN || die 'Cannot inspect candidate filesystem'
  df -h -- "$candidate" | sed 's/^/CANDIDATE_SPACE=/'
  echo 'CANDIDATE_SEPARATE_FILESYSTEM=YES (physical disk, health and encryption still require review)'
else
  echo 'CANDIDATE_NOT_SELECTED: Umbrel Files /External paths may not match Linux Host mount paths.'
fi

echo 'RESULT=READ_ONLY_PREFLIGHT_COMPLETE'
echo 'NOT_DONE: destination health/encryption, stopped-app backup, integrity verification, isolated restore, merge, upgrade'
