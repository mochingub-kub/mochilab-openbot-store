#!/usr/bin/env bash
# Read-only security inventory; avoids full embedded seccomp JSON and host paths.
set -euo pipefail
if [[ $# -ne 1 || ! -d "$1" ]]; then
  echo 'Usage: audit-workspace-host.sh /verified/installed/app-directory' >&2
  exit 2
fi
app_dir=$(cd -- "$1" && pwd -P)
command -v docker >/dev/null || { echo 'BLOCKED: host Docker unavailable' >&2; exit 2; }
container=mochilab-openbot_openbot_1
echo 'READ_ONLY: no credential or host path output'
docker inspect --format 'ImageID={{.Image}} User={{.Config.User}} Privileged={{.HostConfig.Privileged}} AppArmor={{.AppArmorProfile}} CapAdd={{json .HostConfig.CapAdd}} CapDrop={{json .HostConfig.CapDrop}}' "$container"
docker inspect --format '{{range .Mounts}}Type={{.Type}} Destination={{.Destination}} RW={{.RW}}{{println}}{{end}}' "$container"
for rel in docker-compose.yml seccomp-0.49.0.json hooks/pre-start hooks/mochilab-openbot.apparmor; do
  file="$app_dir/$rel"
  if [[ -r "$file" ]]; then
    hash=$(sha256sum -- "$file" | cut -d' ' -f1)
    printf 'FILE=%s SHA256=%s\n' "$rel" "$hash"
  else
    echo "UNKNOWN: cannot read $rel"
  fi
done
if [[ -r "$app_dir/hooks/mochilab-openbot.apparmor" ]]; then
  grep -nE 'deny mount|userns|profile |umount|ptrace' "$app_dir/hooks/mochilab-openbot.apparmor" || true
fi
docker exec --user 1000:1000 "$container" /bin/sh -c '
 id; uname -r; bwrap --version; cat /proc/self/attr/current
 grep -E "^(CapEff|CapBnd|NoNewPrivs|Seccomp):" /proc/self/status
'
echo 'NOT_RUN: bwrap mounted payload, policy load, Codex writes, restart/update'
