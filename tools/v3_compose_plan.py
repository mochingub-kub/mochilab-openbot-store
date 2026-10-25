#!/usr/bin/env python3
"""Read-only, fail-closed planner for Mochilab's Umbrel runtime Compose.

Never edits a file, changes a Docker container, reads credentials, or deploys
policies. Uses PyYAML's parser node character offsets to simulate only two
scalar substitutions without re-serializing YAML. No auto-install dependencies.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys


class Blocked(Exception):
    pass


def reject(why):
    raise Blocked(why)


def yaml_module():
    try:
        import yaml
    except ImportError:
        reject("PY_YAML_NOT_INSTALLED_NO_AUTO_INSTALL")
    return yaml


def validate_nodes(yaml, node):
    allowed = {f"tag:yaml.org,2002:{x}" for x in ("map", "seq", "str", "int", "bool", "null", "float")}
    if node.tag not in allowed:
        reject("UNSUPPORTED_YAML_TAG")
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for k, v in node.value:
            if not isinstance(k, yaml.ScalarNode) or k.tag != "tag:yaml.org,2002:str":
                reject("NON_STRING_OR_MERGED_YAML_KEY")
            if k.value in seen:
                reject("DUPLICATE_YAML_KEY")
            seen.add(k.value)
            validate_nodes(yaml, v)
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            validate_nodes(yaml, v)


def mapping(yaml, node, name):
    if not isinstance(node, yaml.MappingNode):
        reject("INVALID_MAPPING_" + name)
    return {k.value: v for k, v in node.value}


def scalar(yaml, node, name):
    if not isinstance(node, yaml.ScalarNode) or node.tag != "tag:yaml.org,2002:str":
        reject("INVALID_SCALAR_" + name)
    return node.value


def parse(yaml, source):
    try:
        events = list(yaml.parse(source, Loader=yaml.SafeLoader))
        for e in events:
            if isinstance(e, yaml.AliasEvent) or getattr(e, "anchor", None) is not None:
                reject("YAML_ALIASES_ANCHORS_NOT_SUPPORTED")
        docs = list(yaml.compose_all(source, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        reject("YAML_PARSE_FAILED")
    if len(docs) != 1 or docs[0] is None:
        reject("EXPECTED_EXACTLY_ONE_YAML_DOCUMENT")
    validate_nodes(yaml, docs[0])
    return docs[0]



def expect_false(yaml, node, field):
    if (
        not isinstance(node, yaml.ScalarNode)
        or node.tag != "tag:yaml.org,2002:bool"
        or node.value.lower() != "false"
    ):
        reject("INVALID_FALSE_" + field)


def check_umbrel_data_volume(yaml, node):
    """Validate original short bind or UmbrelOS's managed long bind mapping.

    UmbrelOS App.patchComposeFile() may redirect the source to APP_DATA_ROOT
    and replace a short volume with type/source/target/read_only/bind fields
    to prevent Docker silently creating a missing host directory.
    No host paths, mount source or credentials are printed by this validator.
    """
    if isinstance(node, yaml.ScalarNode):
        original = scalar(yaml, node, "VOLUME")
        if original not in (
            "${APP_DATA_DIR}/data:/data",
            "${APP_DATA_ROOT}:/data",
        ):
            reject("DATA_VOLUME_MAPPING_DRIFT")
        return

    longform = mapping(yaml, node, "VOLUME")
    if set(longform) != {"type", "source", "target", "read_only", "bind"}:
        reject("VOLUME_MAPPING_FIELDS_UNEXPECTED")
    if scalar(yaml, longform["type"], "VOLUME_TYPE") != "bind":
        reject("VOLUME_TYPE_DRIFT")
    if scalar(yaml, longform["source"], "VOLUME_SOURCE") != "${APP_DATA_ROOT}":
        reject("VOLUME_SOURCE_DRIFT")
    if scalar(yaml, longform["target"], "VOLUME_TARGET") != "/data":
        reject("VOLUME_TARGET_DRIFT")
    expect_false(yaml, longform["read_only"], "VOLUME_READ_ONLY")
    bind = mapping(yaml, longform["bind"], "VOLUME_BIND")
    if set(bind) != {"create_host_path"}:
        reject("VOLUME_BIND_OPTIONS_DRIFT")
    expect_false(yaml, bind["create_host_path"], "VOLUME_CREATE_HOST_PATH")


def compose_targets(yaml, source):
    root = mapping(yaml, parse(yaml, source), "ROOT")
    services = mapping(yaml, root.get("services"), "SERVICES")
    if set(services) != {"app_proxy", "landing", "openbot"}:
        reject("SERVICE_SET_DRIFT")
    for name in ("app_proxy", "landing", "openbot"):
        entry = mapping(yaml, services[name], "SERVICE_" + name)
        expected = f"mochilab-openbot_{name}_1"
        if scalar(yaml, entry.get("container_name"), "CONTAINER_NAME") != expected:
            reject("CONTAINER_NAME_DRIFT")
    openbot = mapping(yaml, services["openbot"], "OPENBOT")
    if scalar(yaml, openbot.get("image"), "IMAGE") != "ghcr.io/nightly-labs/openbot:0.49.0":
        reject("IMAGE_DRIFT")
    for key in ("privileged", "cap_add", "devices", "pid", "network_mode", "userns_mode"):
        if key in openbot:
            reject("UNREVIEWED_PRIVILEGE_KEY")
    vols = openbot.get("volumes")
    if not isinstance(vols, yaml.SequenceNode) or len(vols.value) != 1:
        reject("VOLUME_LAYOUT_DRIFT")
    check_umbrel_data_volume(yaml, vols.value[0])
    opts = openbot.get("security_opt")
    if not isinstance(opts, yaml.SequenceNode) or len(opts.value) != 3:
        reject("SECURITY_OPT_LAYOUT_DRIFT")
    found = {}
    for entry in opts.value:
        value = scalar(yaml, entry, "SECURITY_OPT")
        for prefix in ("apparmor=", "seccomp="):
            if value.startswith(prefix):
                if prefix in found:
                    reject("DUPLICATE_SECURITY_SELECTOR")
                found[prefix] = entry
        if value == "no-new-privileges:true":
            if "nnp" in found:
                reject("DUPLICATE_NNP")
            found["nnp"] = entry
    if set(found) != {"apparmor=", "seccomp=", "nnp"}:
        reject("MISSING_OR_UNKNOWN_SECURITY_OPTION")
    if found["apparmor="].value != "apparmor=mochilab-openbot":
        reject("APPARMOR_BASELINE_DRIFT")
    if found["seccomp="].value != "seccomp=${APP_DATA_DIR}/seccomp-0.49.0.json":
        reject("SECCOMP_BASELINE_DRIFT")
    return found


def simulate(source):
    yaml = yaml_module()
    found = compose_targets(yaml, source)
    changes = []
    for prefix, new in (
        ("apparmor=", "apparmor=mochilab-openbot-workspace"),
        ("seccomp=", "seccomp=${APP_DATA_DIR}/seccomp-workspace.json"),
    ):
        node = found[prefix]
        a, b = node.start_mark.index, node.end_mark.index
        token = source[a:b]
        if node.style is None:
            if token != node.value:
                reject("UNSUPPORTED_PLAIN_SCALAR_TOKEN")
            replacement = new
        elif node.style in ('"', "'"):
            if token != node.style + node.value + node.style:
                reject("COMPLEX_QUOTED_SCALAR_NOT_SUPPORTED")
            replacement = node.style + new + node.style
        else:
            reject("UNSUPPORTED_SCALAR_STYLE")
        changes.append((a, b, token, replacement))
    if changes[0][0] == changes[1][0]:
        reject("OVERLAPPING_PATCH_SPANS")
    patched = source
    for a, b, old, new in sorted(changes, reverse=True):
        if patched[a:b] != old:
            reject("PATCH_SPAN_CHANGED")
        patched = patched[:a] + new + patched[b:]
    try:
        before = yaml.safe_load(source)
        after = yaml.safe_load(patched)
    except yaml.YAMLError:
        reject("PATCH_YAML_PARSE_FAILED")
    if not isinstance(after, dict):
        reject("PATCH_STRUCTURE_UNEXPECTED")
    so = after["services"]["openbot"]["security_opt"]
    if set(so) != {
        "apparmor=mochilab-openbot-workspace",
        "seccomp=${APP_DATA_DIR}/seccomp-workspace.json",
        "no-new-privileges:true",
    }:
        reject("PATCH_SELECTORS_NOT_EXACT")
    # Revert only the two allowed values in the parsed candidate. The rest
    # of the semantic structure must be completely identical to the baseline.
    after["services"]["openbot"]["security_opt"] = before["services"]["openbot"]["security_opt"]
    if after != before:
        reject("UNAPPROVED_SEMANTIC_CHANGE")
    # The only byte changes can be the two scalar spans, not formatting or
    # umbrella-generated container_name, volumes, anchors, comments or keys.
    reverse = patched
    for a, b, old, new in sorted(changes):
        # Once an earlier replacement is restored, every remaining span has
        # exactly its original offset again.
        if reverse[a:a + len(new)] != new:
            reject("NON_REVERSIBLE_PATCH")
        reverse = reverse[:a] + old + reverse[a + len(new):]
    if reverse != source:
        reject("NON_TARGET_BYTES_CHANGED")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description="Read-only V3 Umbrel Compose semantic patch simulator")
    p.add_argument("--input", default="/home/umbrel/umbrel/app-data/mochilab-openbot/docker-compose.yml")
    args = p.parse_args(argv)
    try:
        path = Path(args.input)
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            reject("COMPOSE_NOT_SINGLE_REGULAR_FILE")
        if st.st_size > 1024 * 1024:
            reject("COMPOSE_TOO_LARGE")
        source = path.read_bytes().decode("utf-8")
        if not source.endswith("\n"):
            reject("COMPOSE_MISSING_TRAILING_NEWLINE")
        st2 = path.lstat()
        if (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size) != (st2.st_ino, st2.st_dev, st2.st_mtime_ns, st2.st_size):
            reject("COMPOSE_CHANGED_DURING_READ")
        digest = simulate(source)
        print("RESULT=V3_COMPOSE_READ_ONLY_PLAN_PASS")
        print("CURRENT_COMPOSE_SHA256=" + digest)
        print("ALLOWED_PATCHES=2_SECURITY_OPT_SCALARS_ONLY")
        print("OTHER_COMPOSE_BYTES_PRESERVED=YES_IN_MEMORY")
        print("EFFECTIVE_OVERRIDES=NOT_INSPECTED")
        print("POLICY_SAFETY=NOT_REVIEWED_FOR_PRODUCTION")
        print("HOST_FILES_CHANGED=NO")
        print("NEXT=REVIEW_EFFECTIVE_COMPOSE_AND_BUILD_APPLY_ROLLBACK")
        return 0
    except (Blocked, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else "COMPOSE_READ_FAILED"
        print("BLOCKED=" + reason, file=sys.stderr)
        print("HOST_FILES_CHANGED=NO", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
