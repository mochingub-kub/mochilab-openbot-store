#!/usr/bin/env python3
"""Mochilab OpenBot V3: fail-closed, stopped-only configuration transaction.

Not an Umbrel app updater. Never stops/starts containers, manages accounts,
reads secret values, edits /data, or modifies Docker daemon settings.
Stage requires explicit administrator approval and a verified independent copy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from v3_compose_plan import Blocked, plan_candidate

APP = Path("/home/umbrel/umbrel/app-data/mochilab-openbot")
SERVICE = "mochilab-openbot_openbot_1"
PROJECT = "mochilab-openbot"
STAGED = {
    "hooks/mochilab-openbot-workspace.apparmor": "afd0d87e7a09e39afad12864fb988586ce95104e",
    "seccomp-workspace.json": "4fa610c6303f4610844dc6ae0da5546030a77cbb",
    "hooks/pre-start": "f0f6de6bea47df28595449c2f766a99c804aaab2",
}
ORIGINAL = {
    "hooks/pre-start": "3c981033751a830e72e48c18227a3e236d64a38c",
    "hooks/mochilab-openbot.apparmor": "fc27398ef8a2404f2c2f0ef7e6aaab411a9ec73a",
    "seccomp-0.49.0.json": "6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418",
}
NEW_ONLY = ("hooks/mochilab-openbot-workspace.apparmor", "seccomp-workspace.json")
BACKUP_CONFIG = (
    "docker-compose.yml", "docker-compose.umbreld.yml", "hooks/pre-start",
    "hooks/mochilab-openbot.apparmor", "seccomp-0.49.0.json",
)
MODIFIED = ("hooks/mochilab-openbot-workspace.apparmor", "seccomp-workspace.json",
            "hooks/pre-start", "docker-compose.yml")


def fail(reason):
    raise Blocked(reason)


def run(args, *, check=True, env=None):
    p = subprocess.run(args, check=False, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, text=True, env=env)
    if check and p.returncode:
        fail("COMMAND_FAILED_" + Path(args[0]).name.replace("-", "_").upper())
    return p.stdout.strip()


def git_sha(path):
    return run(["git", "hash-object", str(path)])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        fail("UNSAFE_FILE_" + path.name)
    return st


def owned_root():
    if os.geteuid() != 0:
        fail("RUN_AS_ROOT_ON_UMBREL_HOST")
    if APP.is_symlink() or APP.resolve(strict=True) != APP:
        fail("APP_ROOT_CHANGED")
    if not (APP / "data").is_dir() or (APP / "data").is_symlink():
        fail("DATA_ROOT_UNSAFE")
    for rel in BACKUP_CONFIG:
        regular(APP / rel)


def check_installed():
    owned_root()
    for rel, expected in ORIGINAL.items():
        if git_sha(APP / rel) != expected:
            fail("BASELINE_DRIFT_" + rel.replace("/", "_"))
    for rel in NEW_ONLY:
        if (APP / rel).exists() or (APP / rel).is_symlink():
            fail("V3_ARTIFACT_ALREADY_PRESENT_" + rel.replace("/", "_"))
    source = (APP / "docker-compose.yml").read_text(encoding="utf-8")
    # The planner validates full source including managed data-root volumes.
    before, candidate = plan_candidate(source)
    runtime = (APP / "docker-compose.umbreld.yml").read_text(encoding="utf-8")
    validate_umbreld_runtime_compose(source, runtime)
    # A third Compose file (umbrel-user-settings) and common Compose fragments
    # are separate effective-configuration gates, never silently ignored.
    if (APP / "docker-compose.umbrel-user-settings.yml").exists():
        fail("USER_SETTINGS_COMPOSE_REQUIRES_EXPLICIT_REVIEW")
    return source, before, candidate


def validate_umbreld_runtime_compose(source, runtime):
    """Validate Umbrel-generated runtime Compose, not a partial override.

    umbrelOS's app-script generates docker-compose.umbreld.yml from the
    package Compose with: yq 'del(.services.app_proxy)' docker-compose.yml.
    Fail closed on any other semantic difference. Do not print values.
    """
    import yaml
    from v3_compose_plan import parse

    # PyYAML safe_load alone silently accepts duplicate mapping keys.
    # Parse nodes first to reject duplicate/aliased/merged/unknown tags.
    parse(yaml, source)
    parse(yaml, runtime)
    original = yaml.safe_load(source)
    generated = yaml.safe_load(runtime)
    if not isinstance(original, dict) or not isinstance(generated, dict):
        fail("UMBRELD_RUNTIME_STRUCTURE_INVALID")
    services = original.get("services")
    if not isinstance(services, dict) or "app_proxy" not in services:
        fail("UMBRELD_SOURCE_PROXY_MISSING")
    expected = dict(original)
    expected_services = dict(services)
    del expected_services["app_proxy"]
    expected["services"] = expected_services
    if generated != expected:
        fail("UMBRELD_RUNTIME_COMPOSE_SEMANTIC_DRIFT")


def check_artifacts():
    base = Path(__file__).resolve().parent.parent / "deploy" / "workspace-v3"
    for rel, expected in STAGED.items():
        file = base / (rel.split("/")[-1])
        regular(file)
        if git_sha(file) != expected:
            fail("REVIEW_ARTIFACT_DRIFT_" + file.name)
    run(["apparmor_parser", "-Q", "-T", "-K", str(base / "mochilab-openbot-workspace.apparmor")])
    require_fresh_workspace_profile()
    return base


def require_fresh_workspace_profile(profiles=Path("/sys/kernel/security/apparmor/profiles")):
    """Never reload an unknown existing kernel policy with the candidate name."""
    if not profiles.is_file():
        fail("APPARMOR_KERNEL_PROFILE_LIST_UNAVAILABLE")
    try:
        names = profiles.read_text(encoding="utf-8").splitlines()
    except OSError:
        fail("APPARMOR_KERNEL_PROFILE_LIST_UNREADABLE")
    if any(line.startswith("mochilab-openbot-workspace (") for line in names):
        fail("WORKSPACE_PROFILE_ALREADY_LOADED_REQUIRES_REVIEW")


def docker_info():
    raw = run(["docker", "inspect", SERVICE])
    try:
        data = json.loads(raw)
        if len(data) != 1:
            fail("DOCKER_INSTANCE_COUNT_DRIFT")
        return data[0]
    except (ValueError, KeyError, TypeError, IndexError):
        fail("DOCKER_INSPECT_UNREADABLE")


def check_live_baseline(require_running=True):
    info = docker_info()
    if require_running and not info.get("State", {}).get("Running"):
        fail("PRODUCTION_NOT_RUNNING")
    if info.get("AppArmorProfile") != "mochilab-openbot":
        fail("APPARMOR_RUNTIME_DRIFT")
    hc = info.get("HostConfig", {})
    if hc.get("Privileged") or hc.get("CapAdd"):
        fail("CONTAINER_PRIVILEGE_DRIFT")
    opts = hc.get("SecurityOpt") or []
    if not any("apparmor=mochilab-openbot" == x for x in opts):
        fail("RUNTIME_APPARMOR_OPTION_DRIFT")
    if not any(x.startswith("seccomp=") for x in opts):
        fail("RUNTIME_SECCOMP_OPTION_UNKNOWN")
    if "no-new-privileges:true" not in opts:
        fail("RUNTIME_NO_NEW_PRIVILEGES_MISSING")
    labels = info.get("Config", {}).get("Labels") or {}
    if labels.get("com.docker.compose.project") != PROJECT or labels.get("com.docker.compose.service") != "openbot":
        fail("DOCKER_COMPOSE_LABEL_DRIFT")
    mounts = info.get("Mounts") or []
    if len(mounts) != 1 or mounts[0].get("Destination") != "/data" or not mounts[0].get("RW"):
        fail("RUNTIME_MOUNT_LAYOUT_DRIFT")
    if Path(mounts[0].get("Source", "")).resolve() != (APP / "data").resolve():
        fail("RUNTIME_DATA_SOURCE_DRIFT")
    if info.get("Config", {}).get("Image") != "ghcr.io/nightly-labs/openbot:0.49.0":
        fail("IMAGE_VERSION_DRIFT")


def check_stopped():
    """Require Umbrel's stopped-and-removed state, never a leftover container.

    In the inspected UmbrelOS app-script, "stop" runs:
      docker compose rm --force --stop
    This intentionally removes the app containers but preserves /data. Never
    infer that a stopped container remains inspectable after an Umbrel stop.
    """
    # docker ps -a detects running, paused, restarting and stopped containers.
    all_ids = run(["docker", "ps", "-aq", "--filter",
                   "label=com.docker.compose.project=" + PROJECT])
    if all_ids:
        fail("APP_CONTAINERS_STILL_PRESENT_AFTER_UMBREL_STOP")
    # An old or manually created same-name container without correct labels
    # must also block staging rather than being silently ignored.
    named = run(["docker", "inspect", "--format", "{{.Id}}", SERVICE],
                check=False)
    if named:
        fail("OPENBOT_NAMED_CONTAINER_STILL_PRESENT")
    return True


def external_backup_parent(parent):
    if not parent.is_dir() or parent.is_symlink() or parent.resolve() != parent:
        fail("BACKUP_PARENT_UNSAFE")
    mounted = run(["findmnt", "-T", str(parent), "-no", "TARGET,FSTYPE"])
    parts = mounted.split()
    if len(parts) != 2 or parts[0] == "/" or parts[1] not in ("ext4", "xfs", "btrfs"):
        fail("INDEPENDENT_MOUNT_NOT_VERIFIED")
    if parent.stat().st_dev == (APP / "data").stat().st_dev:
        fail("BACKUP_ON_SAME_FILESYSTEM")
    # A separate partition on the same NVMe is not an independent backup.
    backup_source = run(["findmnt", "-T", str(parent), "-no", "SOURCE"]).split("[")[0]
    data_source = run(["findmnt", "-T", str(APP / "data"), "-no", "SOURCE"]).split("[")[0]
    if not backup_source.startswith("/dev/") or not data_source.startswith("/dev/"):
        fail("BACKUP_BLOCK_DEVICE_UNVERIFIED")
    backup_parent = run(["lsblk", "-no", "PKNAME", backup_source])
    data_parent = run(["lsblk", "-no", "PKNAME", data_source])
    if not backup_parent or not data_parent or backup_parent == data_parent:
        fail("BACKUP_PHYSICAL_DISK_INDEPENDENCE_UNVERIFIED")
    bytes_used = int(run(["du", "-sb", str(APP / "data")]).split()[0])
    free = shutil.disk_usage(parent).free
    if free <= bytes_used * 1.35 + 1073741824:
        fail("BACKUP_INSUFFICIENT_SPACE")
    return bytes_used


def secure_dir(path):
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def manifest_save(transaction, obj):
    target = transaction / "manifest.json"
    content = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    atomic_publish(target, content, new=not target.exists(), mode=0o600)


def atomic_publish(target, content, *, new=False, mode=0o644):
    if not new:
        st = regular(target)
        old_attrs = {k: os.getxattr(target, k) for k in os.listxattr(target)}
    else:
        if target.exists() or target.is_symlink():
            fail("TARGET_ALREADY_EXISTS_" + target.name)
    fd, name = tempfile.mkstemp(prefix=".v3-", dir=str(target.parent))
    temp = Path(name)
    try:
        if not new:
            shutil.copystat(target, temp, follow_symlinks=False)
            os.chown(temp, st.st_uid, st.st_gid)
            os.chmod(temp, stat.S_IMODE(st.st_mode))
            if {k: os.getxattr(temp, k) for k in os.listxattr(temp)} != old_attrs:
                fail("FILE_METADATA_NOT_PRESERVED")
        else:
            os.chmod(temp, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        fd = -1
        os.replace(temp, target)
        directory = os.open(str(target.parent), os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()


def prepare_backup(parent, manifest, *, transaction=None):
    # The app is stopped throughout this operation. It never writes /data.
    external_backup_parent(parent)
    if transaction is None:
        transaction = parent / (".mochilab-openbot-v3-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4))
        secure_dir(transaction)
    secure_dir(transaction / "config")
    secure_dir(transaction / "data")
    for rel in BACKUP_CONFIG:
        source = APP / rel
        dest = transaction / "config" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["rsync", "-aHAX", "--numeric-ids", str(source), str(dest)])
        if digest(source.read_bytes()) != digest(dest.read_bytes()):
            fail("CONFIG_BACKUP_MISMATCH_" + source.name)
    run(["rsync", "-aHAX", "--numeric-ids", str(APP / "data") + "/", str(transaction / "data") + "/"])
    difference = run(["rsync", "-aHAXnci", "--delete", "--numeric-ids",
                      str(APP / "data") + "/", str(transaction / "data") + "/"])
    if difference:
        fail("DATA_BACKUP_CHECKSUM_MISMATCH")
    # Baseline may be changed by the Umbrel updater between inspection and copy.
    for rel in BACKUP_CONFIG:
        expected = manifest["original_sha256"][rel]
        if digest((APP / rel).read_bytes()) != expected or digest((transaction / "config" / rel).read_bytes()) != expected:
            fail("CONFIG_CHANGED_DURING_BACKUP")
    manifest["state"] = "BACKED_UP"
    manifest_save(transaction, manifest)
    return transaction


def safe_transaction(path):
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        fail("TRANSACTION_PATH_INVALID")
    if not path.name.startswith(".mochilab-openbot-v3-"):
        fail("TRANSACTION_ID_INVALID")
    st = path.stat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
        fail("TRANSACTION_OWNERSHIP_OR_PERMISSIONS_UNSAFE")
    regular(path / "manifest.json")
    m = json.loads((path / "manifest.json").read_text())
    if m.get("schema") != "mochilab-openbot-workspace-v3" or m.get("app") != str(APP):
        fail("TRANSACTION_MANIFEST_INVALID")
    for rel in BACKUP_CONFIG:
        regular(path / "config" / rel)
        if digest((path / "config" / rel).read_bytes()) != m["original_sha256"][rel]:
            fail("BACKUP_CONFIG_INTEGRITY_FAILED")
    return m


def restore(path):
    check_stopped()
    m = safe_transaction(path)
    if m["state"] not in ("BACKED_UP", "STAGING", "STAGED", "NEEDS_RECOVERY"):
        fail("TRANSACTION_STATE_NOT_RESTORABLE")
    # Refuse to overwrite changes made by anything other than this transaction.
    for rel in MODIFIED:
        target = APP / rel
        expected = m["new_sha256"][rel]
        original = m["original_sha256"].get(rel)
        if target.exists() or target.is_symlink():
            actual = digest(target.read_bytes()) if target.is_file() and not target.is_symlink() else None
            if actual not in (expected, original):
                fail("ROLLBACK_CONFLICT_" + rel.replace("/", "_"))
        elif original is not None:
            fail("ROLLBACK_EXISTING_FILE_MISSING_" + rel.replace("/", "_"))
    for rel in ("docker-compose.yml", "hooks/pre-start"):
        check_stopped()
        origin = path / "config" / rel
        atomic_publish(APP / rel, origin.read_bytes())
    for rel in NEW_ONLY:
        check_stopped()
        target = APP / rel
        if target.exists():
            if digest(target.read_bytes()) != m["new_sha256"][rel]:
                fail("ROLLBACK_NEW_FILE_CONFLICT")
            target.unlink()
    m["state"] = "ROLLED_BACK"
    manifest_save(path, m)
    print("RESULT=CONFIG_ROLLBACK_COMPLETE_APP_REMAINS_STOPPED")
    print("DATA_COPY_RETAINED_FOR_RECOVERY=YES")


def stage(parent):
    # The operator must have run --check while OpenBot was still running.
    # After an Umbrel stop, Docker removes the app containers, so the saved
    # runtime inspect object no longer exists. Verify on-disk config again.
    check_stopped()
    source, before, candidate = check_installed()
    artifact_dir = check_artifacts()
    size = external_backup_parent(parent)
    print("STAGE_REQUIRES_EXCLUSIVE_MAINTENANCE=YES")
    print("APP_STOPPED=YES DATA_BACKUP_SIZE_BYTES=" + str(size))
    if input("Type STAGE-V3 to back up and stage security config: ").strip() != "STAGE-V3":
        fail("OPERATOR_CONFIRMATION_MISSING")
    check_stopped()
    original = {rel: digest((APP / rel).read_bytes()) for rel in BACKUP_CONFIG}
    new_sha = {
        "docker-compose.yml": digest(candidate.encode()),
        "hooks/pre-start": digest((artifact_dir / "pre-start").read_bytes()),
        "hooks/mochilab-openbot-workspace.apparmor": digest((artifact_dir / "mochilab-openbot-workspace.apparmor").read_bytes()),
        "seccomp-workspace.json": digest((artifact_dir / "seccomp-workspace.json").read_bytes()),
    }
    m = {"schema": "mochilab-openbot-workspace-v3", "app": str(APP),
         "state": "PREPARING", "original_sha256": original,
         "new_sha256": new_sha, "compose_original_sha256": before,
         "data_restore_test": "NOT_RUN"}
    transaction = parent / (".mochilab-openbot-v3-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4))
    secure_dir(transaction)
    try:
        prepare_backup(parent, m, transaction=transaction)
    except Exception:
        print("BLOCKED=BACKUP_INCOMPLETE_NO_APP_MUTATION", file=sys.stderr)
        raise
    try:
        m["state"] = "STAGING"
        manifest_save(transaction, m)
        tasks = [
            ("hooks/mochilab-openbot-workspace.apparmor", (artifact_dir / "mochilab-openbot-workspace.apparmor").read_bytes(), True),
            ("seccomp-workspace.json", (artifact_dir / "seccomp-workspace.json").read_bytes(), True),
            ("hooks/pre-start", (artifact_dir / "pre-start").read_bytes(), False),
            ("docker-compose.yml", candidate.encode(), False),
        ]
        for rel, payload, new in tasks:
            check_stopped()
            if digest(payload) != new_sha[rel]:
                fail("STAGE_PAYLOAD_DRIFT")
            # Do not write over an updater/administrator edit detected mid-transaction.
            target = APP / rel
            if not new and digest(target.read_bytes()) != original[rel]:
                fail("BASELINE_CHANGED_BEFORE_PUBLISH")
            if new and (target.exists() or target.is_symlink()):
                fail("NEW_ARTIFACT_CONFLICT_BEFORE_PUBLISH")
            atomic_publish(target, payload, new=new)
        for rel in MODIFIED:
            if digest((APP / rel).read_bytes()) != new_sha[rel]:
                fail("STAGE_READBACK_MISMATCH")
        m["state"] = "STAGED"
        manifest_save(transaction, m)
    except Exception:
        m["state"] = "NEEDS_RECOVERY"
        manifest_save(transaction, m)
        print("WARNING=STAGING_INTERRUPTED_APP_MUST_REMAIN_STOPPED", file=sys.stderr)
        print("RECOVERY_TRANSACTION=" + str(transaction), file=sys.stderr)
        raise
    print("RESULT=V3_STAGED_NOT_FUNCTIONALLY_TESTED")
    print("RECOVERY_TRANSACTION=" + str(transaction))
    print("APP_REMAINS_STOPPED=YES")
    print("NEXT=REVIEW_AND_START_VIA_UMBREL_LIFECYCLE")


def verify():
    # Check new files and effective container security; no tool/model calls.
    owned_root()
    for rel, expected in STAGED.items():
        if git_sha(APP / rel) != expected:
            fail("STAGED_ARTIFACT_DRIFT_" + rel.replace("/", "_"))
    info = docker_info()
    if not info.get("State", {}).get("Running"):
        fail("RUNTIME_NOT_RUNNING")
    if info.get("AppArmorProfile") != "mochilab-openbot-workspace":
        fail("RUNTIME_WORKSPACE_APPARMOR_NOT_APPLIED")
    hc = info.get("HostConfig", {})
    if hc.get("Privileged") or hc.get("CapAdd"):
        fail("RUNTIME_PRIVILEGE_DRIFT")
    opts = hc.get("SecurityOpt") or []
    if "apparmor=mochilab-openbot-workspace" not in opts:
        fail("WORKSPACE_APPARMOR_OPTION_MISSING")
    if not any(x.startswith("seccomp=") for x in opts):
        fail("WORKSPACE_SECCOMP_OPTION_MISSING")
    if "no-new-privileges:true" not in opts:
        fail("RUNTIME_NNP_MISSING")
    mounts = info.get("Mounts") or []
    if len(mounts) != 1 or mounts[0].get("Destination") != "/data" or not mounts[0].get("RW"):
        fail("RUNTIME_MOUNT_DRIFT")
    if Path(mounts[0].get("Source", "")).resolve() != (APP / "data").resolve():
        fail("RUNTIME_DATA_SOURCE_DRIFT")
    print("RESULT=V3_CONTAINER_SECURITY_BASELINE_ONLY")
    print("BWRAP_AND_CODEX_WORKSPACE_FUNCTIONAL_TESTS=NOT_RUN")


def main():
    parser = argparse.ArgumentParser(description="Mochilab OpenBot V3 gated config transaction")
    p = parser.add_mutually_exclusive_group(required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--stage", metavar="INDEPENDENT_BACKUP_PARENT", type=Path)
    p.add_argument("--rollback", metavar="TRANSACTION_DIR", type=Path)
    p.add_argument("--verify", action="store_true")
    a = parser.parse_args()
    try:
        owned_root()
        if a.check:
            check_installed()
            check_artifacts()
            check_live_baseline()
            print("RESULT=V3_PRECHECK_PASS_NO_WRITES")
            print("PRODUCTION_DEPLOYED=NO")
            print("EFFECTIVE_OVERRIDES=PARTIALLY_INSPECTED")
            print("BACKUP_RESTORE_TEST=NOT_RUN")
        elif a.stage:
            stage(a.stage)
        elif a.rollback:
            restore(a.rollback)
        else:
            verify()
    except (Blocked, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print("BLOCKED=" + (str(e) if isinstance(e, Blocked) else "UNEXPECTED_VALIDATION_ERROR"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
