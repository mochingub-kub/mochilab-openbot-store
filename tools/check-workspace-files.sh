#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || ! -d "$1" || ! -d "$2" ]]; then
  echo 'Usage: check-workspace-files.sh WORKSPACE OUTSIDE_CANARY_DIR [SYNTHETIC_READ_CANARY ...]' >&2
  exit 2
fi
workspace_root=$(cd -- "$1" && pwd -P)
outside_dir=$(cd -- "$2" && pwd -P)
case "$outside_dir/" in
  "$workspace_root/"*) echo 'INVALID: outside target is inside workspace' >&2; exit 2 ;;
esac
if [[ ! -f "$outside_dir/APPROVED_SYNTHETIC_CANARY" ]]; then
  echo 'INVALID: administrator approval marker missing' >&2
  exit 2
fi
shift 2
own_probe=$(mktemp -d "$workspace_root/workspace-check.XXXXXX")
printf 'SYNTHETIC_WORKSPACE_CHECK\n' > "$own_probe/inside.txt"
grep -qx 'SYNTHETIC_WORKSPACE_CHECK' "$own_probe/inside.txt"
printf 'PASS: own workspace read/write; artifact=%s\n' "$own_probe/inside.txt"
outside_probe="$outside_dir/denial-probe.${own_probe##*/}"
if (set -o noclobber; printf 'SYNTHETIC_OUTSIDE_WRITE\n' > "$outside_probe") 2> "$own_probe/outside-error.txt"; then
  printf 'FAIL: outside write succeeded; synthetic artifact=%s\n' "$outside_probe"
  exit 1
fi
printf 'OBSERVED: outside write failed; error artifact=%s\n' "$own_probe/outside-error.txt"
printf 'REQUIRES_REVIEW: verify sandbox denial and administrator writable-baseline; this alone is not PASS.\n'
for canary in "$@"; do
  if [[ ! -f "$canary" || -L "$canary" || "${canary##*/}" != APPROVED_SYNTHETIC_READ_CANARY ]]; then
    echo 'INVALID: read probes must be supplied regular synthetic marker files' >&2
    exit 2
  fi
  if head -c 1 -- "$canary" > /dev/null 2>/dev/null; then
    printf 'READABLE: %s\n' "$canary"
  else
    printf 'BLOCKED: %s\n' "$canary"
  fi
done
printf 'NOT_TESTED: all real credentials and other files; restart/update persistence.\n'
