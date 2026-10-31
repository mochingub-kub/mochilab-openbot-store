#!/usr/bin/env bash
# READ-ONLY parser experiment for Mochilab's next bubblewrap issue.
# Does not load/replace an AppArmor policy or run any Docker container.
set -euo pipefail
if (( $# != 0 )); then echo 'Usage: sudo bash tools/check-bwrap-rbind-grammar.sh' >&2; exit 2; fi
if (( EUID != 0 )); then echo 'BLOCKED: run using sudo on the UmbrelOS Host' >&2; exit 2; fi
command -v apparmor_parser >/dev/null || { echo 'BLOCKED: apparmor_parser unavailable' >&2; exit 2; }
command -v python3 >/dev/null || { echo 'BLOCKED: python3 unavailable' >&2; exit 2; }
command -v mktemp >/dev/null || { echo 'BLOCKED: mktemp unavailable' >&2; exit 2; }
source=/home/umbrel/umbrel/app-data/mochilab-openbot/hooks/mochilab-openbot.apparmor
[[ -r "$source" ]] || { echo 'BLOCKED: current installed AppArmor file is not readable' >&2; exit 2; }
tempfile=$(mktemp /tmp/mochilab-rbind-grammar.XXXXXX)
cleanup() { rm -f -- "$tempfile"; }
trap cleanup EXIT
python3 - "$source" "$tempfile" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])
old_name = "profile mochilab-openbot flags="
assert source.count(old_name) == 1, "unexpected production profile structure"
assert source.count("  deny mount,\n") == 1, "unexpected production mount policy"
assert "  mount options=(rslave,silent) /,\n" not in source, "unexpected original rule"
source = source.replace(old_name, "profile mochilab-bwrap-rbind-parse-only flags=", 1)
source = source.replace(
    "  deny mount,\n",
    "  mount options=(rslave,silent) /,\n"
    "  mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /tmp/,\n"
    "  mount options=(rw,rbind,silent) /tmp/newroot/ -> /tmp/newroot/,\n",
    1,
)
out.write_text(source)
PY
# -Q explicitly skips loading kernel policy.
apparmor_parser -Q -T -K "$tempfile" >/dev/null
echo 'RESULT=RBIND_RULE_GRAMMAR_ACCEPTED'
echo 'APPARMOR_LOADED=NO DOCKER_CONTAINER_STARTED=NO PRODUCTION_CHANGED=NO'
echo 'NOT_TESTED=SECCOMP_RUNTIME_OR_BWRAP_OR_WRITE_ISOLATION'
