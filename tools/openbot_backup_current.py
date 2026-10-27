#!/usr/bin/env python3
"""Fail-closed, stopped-only Umbrel OpenBot backup (no automatic deletion).

Run on the UmbrelOS host, never in Portainer. A backup is not a full app restore.
The app remains stopped after --backup; the operator must restart and test it.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

APP = Path('/home/umbrel/umbrel/app-data/mochilab-openbot')
PARENT = Path('/home/umbrel/umbrel/external/mochi-external')
PREFIX = '.mochilab-openbot-verified-'
SCHEMA = 'mochilab-openbot-stopped-full-tree-v1'
PROJECT = 'mochilab-openbot'
PINNED_BLOBS = {
    'hooks/mochilab-openbot-workspace.apparmor': 'afd0d87e7a09e39afad12864fb988586ce95104e',
    'seccomp-workspace.json': '4fa610c6303f4610844dc6ae0da5546030a77cbb',
    'seccomp-0.49.0.json': '6e42d0bd8e904f5ddddaf3c6c7c50f1dc2d72418',
}
REQUIRED_FILES = (
    'app-gateway.json', 'settings.yml', 'umbrel-app.yml',
    'docker-compose.yml', 'docker-compose.umbreld.yml',
    'hooks/pre-start', 'hooks/mochilab-openbot.apparmor',
    'hooks/mochilab-openbot-workspace.apparmor',
    'hooks/openbot-direct.html', 'landing/index.html',
    'seccomp-workspace.json', 'seccomp-0.49.0.json',
    'data/.config/OpenBot/openbot.db',
    'data/.config/openbot-container/keyring-password',
    'data/.local/share/keyrings/login.keyring',
)


class Blocked(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def run(args, *, check=True):
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and proc.returncode:
        raise Blocked('COMMAND_FAILED_' + Path(args[0]).name.upper())
    return proc.stdout.strip() if proc.returncode == 0 else ''


def git_blob(path):
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def strict_yaml(path):
    try:
        import yaml
    except ImportError:
        raise Blocked('PYYAML_REQUIRED') from None

    class Loader(yaml.SafeLoader):
        pass

    def unique_map(loader, node):
        result = {}
        for key_node, val_node in node.value:
            key = loader.construct_object(key_node, deep=True)
            require(isinstance(key, str) and key not in result, 'DUPLICATE_OR_INVALID_YAML_KEY')
            result[key] = loader.construct_object(val_node, deep=True)
        return result

    Loader.add_constructor('tag:yaml.org,2002:map', unique_map)
    try:
        raw = path.read_text(encoding='utf-8')
        events = list(yaml.parse(raw, Loader=Loader))
        require(not any(isinstance(e, yaml.AliasEvent) or getattr(e, 'anchor', None)
                        for e in events), 'YAML_ALIAS_OR_ANCHOR')
        obj = yaml.load(raw, Loader=Loader)
        require(isinstance(obj, dict), 'YAML_ROOT_INVALID')
        return obj
    except (yaml.YAMLError, UnicodeError, TypeError, ValueError):
        raise Blocked('YAML_PARSE_FAILED') from None


def check_app():
    require(APP.is_dir() and not APP.is_symlink() and APP.resolve() == APP,
            'APP_ROOT_UNEXPECTED')
    data_root = APP / 'data'
    require(data_root.is_dir() and not data_root.is_symlink() and data_root.resolve() == data_root,
            'DATA_ROOT_UNEXPECTED')
    require(APP.stat().st_dev == data_root.stat().st_dev, 'APP_DATA_MOUNT_CHANGED')
    for rel in REQUIRED_FILES:
        file = APP / rel
        require(file.is_file() and not file.is_symlink(), 'REQUIRED_FILE_MISSING_OR_LINKED')
    require((APP / 'data/OpenBot/Agents').is_dir(), 'AGENTS_MISSING')
    require((APP / 'data/OpenBot/Shared').is_dir(), 'SHARED_MISSING')
    for rel, expected in PINNED_BLOBS.items():
        require(git_blob(APP / rel) == expected, 'SECURITY_POLICY_CHANGED')

    manifest = strict_yaml(APP / 'umbrel-app.yml')
    compose = strict_yaml(APP / 'docker-compose.yml')
    require(manifest.get('id') == PROJECT, 'APP_ID_CHANGED')
    require(manifest.get('storage', {}).get('dataRoot') == 'data', 'DATA_ROOT_MANIFEST_CHANGED')
    package = str(manifest.get('version', ''))
    match = re.fullmatch(r'(\d+\.\d+\.\d+)-1', package)
    require(match is not None, 'APP_PACKAGE_VERSION_NOT_REVIEWED')
    services = compose.get('services', {})
    require(isinstance(services, dict) and set(services) == {'app_proxy', 'landing', 'openbot'},
            'COMPOSE_SERVICE_LAYOUT_CHANGED')
    engine = services['openbot']
    require(isinstance(engine, dict), 'COMPOSE_ENGINE_INVALID')
    require(engine.get('image') == 'ghcr.io/nightly-labs/openbot:' + match.group(1),
            'ENGINE_IMAGE_VERSION_MISMATCH')
    opt = engine.get('security_opt')
    require(isinstance(opt, list) and set(opt) == {
        'apparmor=mochilab-openbot-workspace',
        'seccomp=${APP_DATA_DIR}/seccomp-workspace.json',
        'no-new-privileges:true',
    }, 'SANDBOX_SECURITY_CHANGED')
    require(not any(k in engine for k in ('privileged', 'cap_add', 'devices', 'ports',
                                           'network_mode', 'pid', 'ipc', 'userns_mode')),
            'ENGINE_PRIVILEGE_OR_NETWORK_CHANGED')
    volume = engine.get('volumes')
    require(volume == ['${APP_DATA_DIR}/data:/data'] or
            volume == ['${APP_DATA_ROOT}:/data'] or
            volume == [{'type': 'bind', 'source': '${APP_DATA_ROOT}', 'target': '/data',
                        'read_only': False, 'bind': {'create_host_path': False}}],
            'ENGINE_VOLUME_LAYOUT_CHANGED')
    require(services['landing'].get('volumes') ==
            ['${APP_DATA_DIR}/landing:/usr/share/nginx/html:ro'],
            'LANDING_VOLUME_CHANGED')
    return package


def physical_disk(path):
    source = run(['findmnt', '-T', str(path), '-no', 'SOURCE']).split('[')[0]
    require(source.startswith('/dev/'), 'BLOCK_DEVICE_NOT_IDENTIFIED')
    disk = run(['lsblk', '-no', 'PKNAME', source]).strip()
    require(disk != '', 'PHYSICAL_DISK_NOT_IDENTIFIED')
    return disk


def check_storage():
    require(PARENT.is_dir() and not PARENT.is_symlink() and PARENT.resolve() == PARENT,
            'EXTERNAL_PATH_MISSING_OR_LINKED')
    require(run(['findmnt', '-T', str(PARENT), '-no', 'TARGET']) == str(PARENT),
            'EXTERNAL_NOT_MOUNT_ROOT')
    fstype = run(['findmnt', '-T', str(PARENT), '-no', 'FSTYPE'])
    require(fstype in {'ext4', 'xfs', 'btrfs'}, 'EXTERNAL_FILESYSTEM_UNEXPECTED')
    require('rw' in run(['findmnt', '-T', str(PARENT), '-no', 'OPTIONS']).split(','),
            'EXTERNAL_READ_ONLY')
    require(PARENT.stat().st_dev != APP.stat().st_dev, 'EXTERNAL_NOT_INDEPENDENT_FILESYSTEM')
    require(physical_disk(PARENT) != physical_disk(APP), 'EXTERNAL_NOT_INDEPENDENT_DISK')
    require(shutil.which('rsync') is not None, 'RSYNC_REQUIRED')
    source_bytes = int(run(['du', '-sb', str(APP)]).split()[0])
    require(shutil.disk_usage(PARENT).free >= int(source_bytes * 1.3) + 256 * 1024**2,
            'EXTERNAL_INSUFFICIENT_SPACE')
    return source_bytes


def check_stopped():
    state = json.loads(run(['umbreld', 'client', 'apps.state.query', '--appId', PROJECT]))
    require(state.get('state') == 'stopped', 'UMBREL_APP_NOT_STOPPED')
    running = run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + PROJECT])
    require(running == '', 'OPENBOT_CONTAINER_STILL_RUNNING')
    named = run(['docker', 'ps', '-q', '--filter', 'name=mochilab-openbot_openbot_1'])
    require(named == '', 'OPENBOT_NAMED_CONTAINER_STILL_RUNNING')


def inventory(root):
    """Hash all regular files and symlink targets; never follow symlinks."""
    result = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        for p in directory.iterdir():
            rel = p.relative_to(root).as_posix()
            st = p.lstat()
            record = {'mode': stat.S_IMODE(st.st_mode)}
            if stat.S_ISLNK(st.st_mode):
                record.update(kind='link', target=os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                record['kind'] = 'directory'
                stack.append(p)
            elif stat.S_ISREG(st.st_mode):
                record.update(kind='file', size=st.st_size, sha256=digest(p))
            else:
                raise Blocked('UNSUPPORTED_SPECIAL_FILE_IN_BACKUP')
            result[rel] = record
    return dict(sorted(result.items()))


def require_root():
    require(os.geteuid() == 0, 'UMBREL_HOST_ROOT_REQUIRED')


def snapshot_path(path):
    require(path.is_absolute() and path.parent == PARENT and
            re.fullmatch(r'\.mochilab-openbot-verified-\d{8}-\d{6}-[a-f0-9]{8}', path.name),
            'SNAPSHOT_NAME_OR_PATH_INVALID')
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            'SNAPSHOT_NOT_REAL_DIRECTORY')
    st = path.stat()
    require(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o700,
            'SNAPSHOT_ROOT_NOT_PRIVATE')
    return path


def verify_snapshot(path):
    snapshot_path(path)
    marker = path / 'manifest.json'
    require(marker.is_file() and not marker.is_symlink(), 'BACKUP_MANIFEST_MISSING')
    st = marker.stat()
    require(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o600,
            'BACKUP_MANIFEST_NOT_PRIVATE')
    require(st.st_size < 64 * 1024**2, 'BACKUP_MANIFEST_OVERSIZED')
    meta = json.loads(marker.read_text('utf-8'))
    require(meta.get('schema') == SCHEMA and meta.get('state') == 'FILE_CHECKSUM_VERIFIED'
            and meta.get('source') == str(APP), 'BACKUP_MANIFEST_INVALID')
    saved = meta.get('inventory')
    require(isinstance(saved, dict) and len(saved) > 20, 'BACKUP_INVENTORY_INCOMPLETE')
    for required in REQUIRED_FILES:
        require(required in saved, 'BACKUP_REQUIRED_FILE_MISSING')
    require(saved == inventory(path / 'app'), 'BACKUP_HASH_OR_METADATA_MISMATCH')
    return meta


def backup():
    require_root()
    version = check_app()
    nbytes = check_storage()
    check_stopped()
    print('SOURCE_BYTES=' + str(nbytes))
    print('VERSION=' + version)
    if input('Type BACKUP-OPENBOT (no deletion): ').strip() != 'BACKUP-OPENBOT':
        raise Blocked('OPERATOR_DECLINED')
    check_stopped()
    check_app()
    check_storage()
    name = PREFIX + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4)
    path = PARENT / name
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    destination = path / 'app'
    destination.mkdir(mode=0o700)
    try:
        run(['rsync', '-aHAX', '--numeric-ids', '--', str(APP) + '/', str(destination) + '/'])
        check_stopped()
        changed = run(['rsync', '-aHAXnci', '--delete', '--numeric-ids', '--',
                       str(APP) + '/', str(destination) + '/'])
        require(changed == '', 'BACKUP_SOURCE_COPY_DIFFERS')
        files = inventory(destination)
        require(files == inventory(APP), 'BACKUP_CONTENT_CHANGED_DURING_VERIFICATION')
        require(all(p in files for p in REQUIRED_FILES), 'BACKUP_MISSING_REQUIRED_FILES')
        metadata = {'schema': SCHEMA, 'state': 'FILE_CHECKSUM_VERIFIED',
                    'source': str(APP), 'package': version,
                    'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'source_bytes': nbytes, 'inventory': files,
                    'isolated_full_app_restore': False}
        marker = path / 'manifest.json'
        with marker.open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, indent=2, sort_keys=True)
            stream.write('\n')
        marker.chmod(0o600)
        verify_snapshot(path)
    except Exception:
        print('INCOMPLETE_SNAPSHOT_NEEDS_REVIEW=' + name, file=sys.stderr)
        raise
    print('RESULT=OPENBOT_CURRENT_FILE_BACKUP_VERIFIED')
    print('SNAPSHOT=' + name)
    print('APP_STILL_STOPPED=YES')
    print('FULL_APP_RESTORE_TEST=NOT_RUN')
    print('OLDER_BACKUPS_DELETED=NO')


def rehearse(path):
    require_root()
    check_app()
    check_storage()
    meta = verify_snapshot(path)
    require(shutil.disk_usage(PARENT).free >= int(meta['source_bytes'] * 1.3) + 256 * 1024**2,
            'RESTORE_SCRATCH_INSUFFICIENT_SPACE')
    with tempfile.TemporaryDirectory(prefix='.mochilab-openbot-restore-test-', dir=PARENT) as temp:
        scratch = Path(temp) / 'app'
        scratch.mkdir(mode=0o700)
        run(['rsync', '-aHAX', '--numeric-ids', '--', str(path / 'app') + '/', str(scratch) + '/'])
        require(inventory(scratch) == meta['inventory'], 'FILE_RESTORE_INTEGRITY_MISMATCH')
        db = scratch / 'data/.config/OpenBot/openbot.db'
        # This is a disposable copy. Never open or change the live or source database.
        connection = sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True)
        try:
            rows = connection.execute('PRAGMA quick_check').fetchall()
            require(rows == [('ok',)], 'SQLITE_INTEGRITY_FAILED')
        finally:
            connection.close()
    print('RESULT=ISOLATED_FILE_RESTORE_REHEARSAL_PASS')
    print('DATABASE_QUICK_CHECK=PASS')
    print('LIVE_APP_UNTOUCHED=YES')
    print('FULL_APP_RESTORE_TEST=NOT_RUN')
    print('RESTORE_SCRATCH_REMOVED=YES')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preflight', action='store_true')
    modes.add_argument('--backup', action='store_true')
    modes.add_argument('--verify', type=Path, metavar='SNAPSHOT')
    modes.add_argument('--rehearse', type=Path, metavar='SNAPSHOT')
    modes.add_argument('--inventory', action='store_true')
    args = parser.parse_args()
    try:
        require_root()
        if args.preflight:
            version = check_app()
            n = check_storage()
            print('RESULT=OPENBOT_CURRENT_PREFLIGHT_PASS_NO_WRITES')
            print('PACKAGE=' + version)
            print('SOURCE_BYTES=' + str(n))
            print('STOP_REQUIRED_FOR_BACKUP=YES')
        elif args.backup:
            backup()
        elif args.verify:
            verify_snapshot(args.verify)
            print('RESULT=OPENBOT_SNAPSHOT_CONTENT_VERIFIED')
            print('FULL_APP_RESTORE_TEST=NOT_RUN')
        elif args.rehearse:
            rehearse(args.rehearse)
        else:
            check_app()
            check_storage()
            snapshots = sorted(p.name for p in PARENT.iterdir()
                               if p.is_dir() and p.name.startswith('.mochilab-openbot-'))
            print('OPENBOT_BACKUP_DIRECTORY_COUNT=' + str(len(snapshots)))
            for name in snapshots:
                print('SNAPSHOT_NAME=' + name)
            print('NO_FILES_REMOVED=YES')
        return 0
    except (Blocked, OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError,
            json.JSONDecodeError) as error:
        message = str(error) if isinstance(error, Blocked) else 'CHECK_FAILED_NO_DETAILS_SHOWN'
        print('BLOCKED=' + message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
