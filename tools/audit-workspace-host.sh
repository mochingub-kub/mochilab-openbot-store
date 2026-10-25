#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -d "$1" ]]; then
  echo 'Usage: audit-workspace-host.sh /verified/installed/app-directory' >&2
  exit 2
fi
app_package_dir=$(cd -- "$1" && pwd -P)
command -v docker >/dev/null || { echo 'BLOCKED: host Docker CLI unavailable' >&2; exit 2; }
printf 'Read-only inspection. No environment values or credentials are requested.\n'
docker inspect --format 'Image={{.Config.Image}} User={{.Config.User}} Privileged={{.HostConfig.Privileged}} SecurityOpt={{json .HostConfig.SecurityOpt}} CapAdd={{json .HostConfig.CapAdd}} CapDrop={{json .HostConfig.CapDrop}}' mochilab-openbot_openbot_1
docker inspect --format '{{range .Mounts}}Type={{.Type}} Source={{.Source}} Destination={{.Destination}} RW={{.RW}}{{println}}{{end}}' mochilab-openbot_openbot_1
for relative_file in docker-compose.yml seccomp-0.49.0.json hooks/pre-start hooks/mochilab-openbot.apparmor; do
  policy_file="$app_package_dir/$relative_file"
  if [[ -r "$policy_file" ]]; then
    sha256sum -- "$policy_file"
  else
    printf 'UNKNOWN: cannot read %s\n' "$relative_file"
  fi
done
if [[ -r "$app_package_dir/hooks/mochilab-openbot.apparmor" ]]; then
  grep -nE 'deny mount|userns|profile |umount|ptrace' "$app_package_dir/hooks/mochilab-openbot.apparmor" || true
fi
docker exec --user 1000:1000 mochilab-openbot_openbot_1 /bin/sh -c '
  id
  uname -r
  bwrap --version
  cat /proc/self/attr/current
  grep -E "^(CapEff|CapBnd|NoNewPrivs|Seccomp):" /proc/self/status
'
printf 'NOT_RUN: mount payload, Codex functional tests, host policy load, restart/update tests.\n'
