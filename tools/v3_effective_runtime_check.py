#!/usr/bin/env python3
"""Read-only check: resolved, currently running Umbrel OpenBot Docker footprint.

Inspects Docker objects but NEVER prints Config.Env, command arguments, logs,
Docker inspect raw JSON, token values, or mount source secrets.
This is a pre-rollout assessment, NOT a simulation of future Compose config.
"""
import json
from pathlib import Path
import sys
import v3_workspace_transaction as tx

PROJECT = "mochilab-openbot"
EXPECTED_NETWORK = "umbrel_main_network"
LANDING_IMAGE = (
    "ghcr.io/nginx/nginx-unprivileged:1.30.6-alpine@sha256:"
    "c8ce7718f0270acba1aecc2f3c8cb5cc8fed42b538c9bc9f2c389ca7c27fb42c"
)
OPENBOT_IMAGE = "ghcr.io/nightly-labs/openbot:0.49.0"


def check_mounts(service, obj):
    mounts = obj.get("Mounts") or []
    if len(mounts) != 1:
        tx.fail("UNEXPECTED_" + service.upper() + "_MOUNT_COUNT")
    mount = mounts[0]
    if mount.get("Type") != "bind":
        tx.fail("UNEXPECTED_" + service.upper() + "_MOUNT_TYPE")
    if service == "openbot":
        dest, source, writable = "/data", tx.APP / "data", True
    else:
        dest, source, writable = "/usr/share/nginx/html", tx.APP / "landing", False
    if mount.get("Destination") != dest or mount.get("RW") is not writable:
        tx.fail("UNEXPECTED_" + service.upper() + "_MOUNT_FLAGS")
    if not mount.get("Source") or Path(mount["Source"]).resolve() != source.resolve():
        tx.fail("UNEXPECTED_" + service.upper() + "_MOUNT_SOURCE")


def check_service(name, obj):
    state = obj.get("State") or {}
    if not state.get("Running") or state.get("Status") != "running":
        tx.fail("RUNTIME_SERVICE_NOT_RUNNING_" + name.upper())
    config = obj.get("Config") or {}
    labels = config.get("Labels") or {}
    if labels.get("com.docker.compose.project") != PROJECT or labels.get("com.docker.compose.service") != name:
        tx.fail("RUNTIME_COMPOSE_LABELS_INVALID")
    host = obj.get("HostConfig") or {}
    if host.get("Privileged") or host.get("CapAdd") or host.get("Devices"):
        tx.fail("RUNTIME_PRIVILEGE_EXPANSION_" + name.upper())
    if host.get("PidMode") == "host" or host.get("IpcMode") == "host" or host.get("NetworkMode") == "host":
        tx.fail("RUNTIME_SHARED_HOST_NAMESPACE_" + name.upper())
    if host.get("PortBindings"):
        tx.fail("RUNTIME_HOST_PORT_BINDING_" + name.upper())
    networks = (obj.get("NetworkSettings") or {}).get("Networks") or {}
    if set(networks) != {EXPECTED_NETWORK}:
        tx.fail("RUNTIME_NETWORK_ATTACHMENT_DRIFT_" + name.upper())
    check_mounts(name, obj)

    if name == "landing":
        if config.get("Image") != LANDING_IMAGE or config.get("User") != "101:101":
            tx.fail("LANDING_IMAGE_OR_UID_DRIFT")
        if not host.get("ReadonlyRootfs"):
            tx.fail("LANDING_ROOT_NOT_READ_ONLY")
        if "ALL" not in (host.get("CapDrop") or []):
            tx.fail("LANDING_CAPABILITIES_NOT_DROPPED")
        if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
            tx.fail("LANDING_NO_NEW_PRIVILEGES_MISSING")
        if "/tmp" not in (host.get("Tmpfs") or {}):
            tx.fail("LANDING_TMPFS_MISSING")
    else:
        if config.get("Image") != OPENBOT_IMAGE:
            tx.fail("OPENBOT_IMAGE_DRIFT")
        opts = host.get("SecurityOpt") or []
        if "no-new-privileges:true" not in opts or "apparmor=mochilab-openbot" not in opts:
            tx.fail("OPENBOT_SECURITY_FLAGS_DRIFT")
        if not any(x.startswith("seccomp=") for x in opts):
            tx.fail("OPENBOT_SECCOMP_MISSING")


def main_check():
    tx.owned_root()
    tx.check_installed()       # lossless candidate; validates generated runtime YAML
    tx.check_artifacts()       # pinned policy checks; no kernel policy load
    tx.check_live_baseline()   # OpenBot security + exactly one /data mount
    project_ids = tx.run(["docker", "ps", "-aq", "--filter",
                          "label=com.docker.compose.project=" + PROJECT]).splitlines()
    if len(project_ids) != 2:
        tx.fail("PROJECT_CONTAINER_COUNT_NOT_TWO")
    obj = json.loads(tx.run(["docker", "inspect"] + project_ids))
    if not isinstance(obj, list) or len(obj) != 2:
        tx.fail("DOCKER_INSPECT_COUNT_INVALID")
    services = {}
    for item in obj:
        label = (item.get("Config") or {}).get("Labels") or {}
        service = label.get("com.docker.compose.service")
        if service not in ("landing", "openbot") or service in services:
            tx.fail("UNEXPECTED_OR_DUPLICATE_PROJECT_SERVICE")
        services[service] = item
    if set(services) != {"openbot", "landing"}:
        tx.fail("MISSING_PROJECT_SERVICE")
    for service, item in services.items():
        check_service(service, item)
    print("RESULT=V3_EFFECTIVE_RUNNING_BASELINE_PASS_NO_WRITES")
    print("PROJECT_SERVICES=landing,openbot")
    print("NETWORK=" + EXPECTED_NETWORK)
    print("OPENBOT_POLICY=ORIGINAL_NOT_V3")
    print("OPENBOT_DATA_MOUNT=EXPECTED_READ_WRITE")
    print("LANDING_SECURITY=EXPECTED_READ_ONLY")
    print("HOST_PRIVILEGE_EXPANSION=NONE_OBSERVED")
    print("EFFECTIVE_COMPOSE_AFTER_V3_STAGE=NOT_TESTED")
    print("CODEX_WORKSPACE_FUNCTIONAL_TEST=NOT_RUN")
    print("BACKUP_AND_FILE_RESTORE_CHECKPOINT=OWNER_REPORTED_PASS")


def main():
    try:
        main_check()
    except (tx.Blocked, OSError, ValueError, KeyError, TypeError) as e:
        reason = str(e) if isinstance(e, tx.Blocked) else "RUNTIME_CHECK_UNEXPECTED_ERROR"
        print("BLOCKED=" + reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
