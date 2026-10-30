"""Source-only phone update. Preview is PC-only; execution needs exact approval.

Retain the fixed visible browser/X11, SEND0, data, profile and Git metadata.
No application imports, services, APKs, browser input or browser start/stop.
"""
from __future__ import annotations

import argparse
import ast
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'data/device-setup/reports/venue-pc-20260930'
ADB = str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Android/Sdk/platform-tools/adb.exe')
DEFAULT_MANIFEST = REPORTS / 'phone-source-update-manifest-20261030.json'
TARGET = SERIAL = MODEL = ''
PHONE_UID = 0
EXECUTE_FLAG = '--execute-approved-source-update'
INSPECT_FLAG = '--inspect-readonly'
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_WIRE_BYTES = 32 * 1024 * 1024
WIRE_LENGTH = 0
SOURCE_COMMIT = NEW_ARCHIVE_SHA = SNAPSHOT_SHA = MANIFEST_SHA = ''
MANIFEST_CONTENT = SNAPSHOT_CONTENT = b''
ARCHIVE = SNAPSHOT = {}
GUARD_ENV = ''
PHONE_HOME = Path('/data/data/com.termux/files/home')
PHONE_PREFIX = Path('/data/data/com.termux/files/usr')
PHONE_REPO = PHONE_HOME / 'rokid-server'
PROFILE = PHONE_REPO / 'data/chromium-profile'
BOOT_SHA = ''
BROWSER_BINDING = {}
X11_BINDING = {}
BACKUP = PHONE_HOME / 'rokid-backups/unconfigured'
LOGGER_TARGET = PHONE_PREFIX / 'share/termux-services/svlogger'
ROOT_FILES = {'requirements-phone.txt', 'constraints-phone.txt'}
stage = 'native_input'
transaction_state = {'phase': 'not_started', 'source_writes': 0, 'restored': False}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(raw: str) -> bool:
    name = PurePosixPath(raw)
    return (bool(name.parts) and not name.is_absolute() and '..' not in name.parts
            and '\\' not in raw and '\0' not in raw and str(name) == raw
            and (name.parts[0] in {'app', 'scripts'} or raw in ROOT_FILES))


def load_bundle(content: bytes, expected_sha: str, expected_files: dict) -> dict[str, bytes]:
    if len(content) > MAX_BUNDLE_BYTES or hashlib.sha256(content).hexdigest() != expected_sha:
        raise RuntimeError('bundle_checksum_or_size')
    files = {}
    seen = set()
    directories = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:') as archive:
        for member in archive.getmembers():
            if not source_path(member.name) or member.name in seen:
                raise RuntimeError('unsafe_bundle_path')
            seen.add(member.name)
            if member.isdir():
                directories.add(member.name)
                continue  # metadata only; never extracted or created from tar
            if not member.isfile() or member.size < 0 or member.size > MAX_BUNDLE_BYTES:
                raise RuntimeError('unsafe_bundle_member')
            total += member.size
            if total > MAX_BUNDLE_BYTES:
                raise RuntimeError('bundle_total_size')
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError('unreadable_bundle_member')
            data = stream.read()
            expected = expected_files.get(member.name)
            if (not isinstance(expected, dict) or set(expected) != {'sha256', 'size', 'mode'}
                    or type(expected['size']) is not int or type(expected['mode']) is not int
                    or expected['mode'] not in {0o644, 0o755} or member.size != expected['size']
                    or hashlib.sha256(data).hexdigest() != expected['sha256']
                    or (member.mode & ~0o020) != expected['mode']):
                raise RuntimeError('bundle_manifest_mismatch')
            if member.name.endswith('.py'):
                compile(data, member.name, 'exec')
            if member.name.endswith('.sh') and b'\r' in data:
                raise RuntimeError('non_LF_shell')
            files[member.name] = data
    if not files or set(files) != set(expected_files) or not ROOT_FILES.issubset(files):
        raise RuntimeError('bundle_scope')
    parents = {str(parent) for name in files for parent in PurePosixPath(name).parents if str(parent) != '.'}
    if not directories.issubset(parents):
        raise RuntimeError('unexpected_bundle_directory')
    return files


def plain(path: Path) -> None:
    # Same no-symlink policy as the immutable source preparer.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RuntimeError('symlink_path')
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise RuntimeError('special_path')


def sync_directories(directory: Path) -> None:
    if os.name != 'posix':
        return
    for parent in (directory, *directory.parents):
        if not parent.is_relative_to(PHONE_HOME):
            break
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_bytes(path: Path, content: bytes, mode: int, *, exclusive: bool = False) -> None:
    # The preparer's file-fsync, atomic replace and directory-fsync method.
    plain(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.rokid-deploy-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.chmod(temporary, mode)
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)  # Atomic no-clobber publication of a complete private file.
        else:
            os.replace(temporary, path)
        sync_directories(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)  # only this call's own temporary


def path_metadata(path: Path) -> dict:
    """lstat without opening directories, links, sockets or FIFOs."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'exists': False}
    row = {'exists': True, 'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode), 'size': info.st_size}
    if stat.S_ISREG(info.st_mode):
        row.update(type='file', sha256=sha(path))
    elif stat.S_ISDIR(info.st_mode):
        row['type'] = 'directory'
    elif stat.S_ISLNK(info.st_mode):
        row.update(type='symlink', link_text=os.readlink(path))
    elif stat.S_ISSOCK(info.st_mode):
        row['type'] = 'socket'
    elif stat.S_ISFIFO(info.st_mode):
        row['type'] = 'fifo'
    else:
        raise RuntimeError('unsupported_metadata_type')
    return row


def source_metadata(repo: Path, names) -> dict:
    result = {}
    for name in names:
        if not source_path(name):
            raise RuntimeError('unsafe_source_path')
        path = repo / name
        plain(path)
        row = path_metadata(path)
        if row['exists'] and (row['type'] != 'file' or row['uid'] != PHONE_UID or row['mode'] & 0o022):
            raise RuntimeError('unsafe_source_metadata')
        result[name] = row
    return result


def file_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def update_sources(repo: Path, backup: Path, files: dict[str, bytes], previous_sources: dict,
                   guard, *, new_modes: dict[str, int], write=atomic_bytes) -> dict:
    """One transaction. An existing/partial journal is never resumed or overwritten."""
    global stage
    if (not files or set(files) != set(previous_sources) or set(files) != set(new_modes)
            or any(type(mode) is not int or mode not in {0o600, 0o700} for mode in new_modes.values())):
        raise RuntimeError('source_scope')
    plain(repo)
    plain(backup)
    if backup.exists():
        raise RuntimeError('transaction_already_exists')
    stage = 'source_update_preflight'
    before = guard(previous_sources)
    if source_metadata(repo, files) != previous_sources:
        raise RuntimeError('unknown_old_source')
    previous = {}
    for name, data in files.items():
        private_directory((repo / name).parent)
        row = previous_sources[name]
        previous[name] = {'before': row, 'after': {
            'exists': True, 'type': 'file', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
            'mode': row['mode'] if row['exists'] else new_modes[name], 'uid': PHONE_UID}}
    needed = sum(len(data) + previous_sources[name].get('size', 0) for name, data in files.items()) + 16 * 1024 * 1024
    if shutil.disk_usage(repo).free < needed:
        raise RuntimeError('backup_space')
    os.umask(0o077)
    backup.mkdir(parents=True, mode=0o700)
    receipt = {'phase': 'backing_up', 'source_bundle_commit': SOURCE_COMMIT,
               'snapshot_sha256': SNAPSHOT_SHA, 'archive_sha256': NEW_ARCHIVE_SHA,
               'sources': previous,
               'protected_and_owner': before, 'source_writes': 0,
               'phone_git_metadata_updated': False}
    journal = backup / 'manifest.json'

    def save():
        write(journal, json.dumps(receipt, sort_keys=True).encode(), 0o600)

    save()
    for name in files:
        if not previous_sources[name]['exists']:
            continue
        target = backup / 'source' / name
        write(target, (repo / name).read_bytes(), 0o600)
        if sha(target) != previous_sources[name]['sha256']:
            raise RuntimeError('backup_checksum')
    if source_metadata(repo, files) != previous_sources or guard(previous_sources) != before:
        raise RuntimeError('pre_update_state_changed')
    receipt['phase'] = 'applying'
    transaction_state['phase'] = 'applying'
    save()
    created = {}
    try:
        stage = 'atomic_source_update'
        for name, payload in files.items():
            # No private root or whole app/scripts tree is renamed.
            plain(repo / name)
            if path_metadata(repo / name) != previous_sources[name]:
                raise RuntimeError('source_changed_during_update')
            row = previous[name]
            if row['before']['exists']:
                write(repo / name, payload, row['after']['mode'])
            else:
                write(repo / name, payload, row['after']['mode'], exclusive=True)
                created[name] = file_identity(repo / name)
                row['created_identity'] = list(created[name])
            receipt['source_writes'] += 1
            transaction_state['source_writes'] = receipt['source_writes']
            save()
        stage = 'source_update_final_guard'
        expected_sources = {name: row['after'] for name, row in previous.items()}
        if source_metadata(repo, files) != expected_sources or guard(expected_sources) != before:
            raise RuntimeError('post_update_state_changed')
        receipt['phase'] = 'source_prepared_send0'
        save()
        transaction_state['phase'] = receipt['phase']
        return receipt
    except BaseException:
        stage = 'source_transaction_restore_preflight'
        try:
            current = source_metadata(repo, files)
            for name, row in previous.items():
                if current[name] not in (row['before'], row['after']):
                    raise RuntimeError('unknown_partial_source')
                if (not row['before']['exists'] and current[name]['exists']
                        and (name not in created or file_identity(repo / name) != created[name])):
                    raise RuntimeError('unknown_created_source')
            if guard(current) != before:
                raise RuntimeError('restore_owner_or_protected_changed')
            for name in files:
                if not previous_sources[name]['exists']:
                    continue
                target = backup / 'source' / name
                plain(target)
                if sha(target) != previous_sources[name]['sha256']:
                    raise RuntimeError('restore_backup_changed')
            stage = 'restore_this_transaction_sources'
            for name, row in previous.items():
                plain(repo / name)
                current_row = path_metadata(repo / name)
                if current_row not in (row['before'], row['after']):
                    raise RuntimeError('source_changed_before_restore')
                if row['before']['exists']:
                    write(repo / name, (backup / 'source' / name).read_bytes(), row['before']['mode'])
                elif current_row['exists']:
                    if name not in created or file_identity(repo / name) != created[name]:
                        raise RuntimeError('created_source_changed_before_restore')
                    (repo / name).unlink()
                    sync_directories((repo / name).parent)
            if source_metadata(repo, files) != previous_sources or guard(previous_sources) != before:
                raise RuntimeError('restore_verification_failed')
            receipt['phase'] = 'rolled_back'
            transaction_state.update(phase='rolled_back', restored=True)
        except BaseException:
            receipt['phase'] = 'rollback_blocked'
            transaction_state['phase'] = 'rollback_blocked'
            save()
            raise
        save()
        raise


def normalized_metadata(row: dict, *, dynamic: bool = False) -> dict:
    result = dict(row)
    if result.get('type') != 'file':
        result.pop('size', None)
    if dynamic and result.get('type') == 'file':
        result.pop('size', None)
        result.pop('sha256', None)
    return result


def inventory(root: Path) -> dict:
    plain(root)
    result = {'.': path_metadata(root)}
    if not result['.']['exists']:
        return result
    if result['.']['type'] != 'directory':
        raise RuntimeError('inventory_root_type')
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            result[path.relative_to(root).as_posix()] = path_metadata(path)
    return result


def check_inventory(actual: dict, expected: dict, *, service: bool = False) -> dict:
    if set(actual) != set(expected):
        raise RuntimeError('inventory_path_set_changed')
    stable = {}
    for name, row in actual.items():
        dynamic = (service and 'supervise' in PurePosixPath(name).parts
                   and PurePosixPath(name).name in {'pid', 'stat', 'status'})
        stable[name] = normalized_metadata(row, dynamic=dynamic)
        if stable[name] != normalized_metadata(expected[name], dynamic=dynamic):
            raise RuntimeError('inventory_metadata_changed')
    return stable


def private_directory(path: Path) -> None:
    plain(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != PHONE_UID or info.st_mode & 0o022:
        raise RuntimeError('private_directory_owner')


def process_binding(pid: int) -> tuple[dict, list[str]]:
    if type(pid) is not int or pid <= 0 or sha(Path('/proc/sys/kernel/random/boot_id')) != BOOT_SHA:
        raise RuntimeError('process_boot_or_pid')
    process = Path('/proc') / str(pid)
    if process.stat().st_uid != PHONE_UID:
        raise RuntimeError('process_owner_changed')
    start = int((process / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    arguments = [part.decode('utf-8', 'replace') for part in (process / 'cmdline').read_bytes().split(b'\0') if part]
    return {'pid': pid, 'starttime': start, 'boot': BOOT_SHA}, arguments


def retained_owner(browser) -> dict:
    global stage
    stage = 'retained_browser_x11'
    runtime = SNAPSHOT['runtime']
    plain(PROFILE)
    if normalized_metadata(path_metadata(PROFILE)) != normalized_metadata(runtime['profile_directory']):
        raise RuntimeError('private_profile_changed')
    lock = PROFILE / 'SingletonLock'
    if normalized_metadata(path_metadata(lock)) != normalized_metadata(runtime['profile_lock']):
        raise RuntimeError('profile_lock_changed')
    allowed_sockets = {str(PHONE_PREFIX / 'tmp'), str(PHONE_PREFIX / 'tmp/.X11-unix'),
                       str(PHONE_PREFIX / 'tmp/.X11-unix/X1')}
    if set(runtime['X11_socket_metadata']) != allowed_sockets:
        raise RuntimeError('x11_socket_scope')
    for name, expected in runtime['X11_socket_metadata'].items():
        if normalized_metadata(path_metadata(Path(name))) != normalized_metadata(expected):
            raise RuntimeError('x11_socket_metadata')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(1)
        if connection.connect_ex(str(PHONE_PREFIX / 'tmp/.X11-unix/X1')) != 0:
            raise RuntimeError('x11_unreachable')
    for port, opened in ((8000, False), (9222, True)):
        with socket.socket() as connection:
            connection.settimeout(1)
            if (connection.connect_ex(('127.0.0.1', port)) == 0) != opened:
                raise RuntimeError('api_or_cdp_port')
    binding, arguments = process_binding(BROWSER_BINDING['pid'])
    if (binding != BROWSER_BINDING or any(a.startswith('--headless') for a in arguments)
            or '--user-data-dir=' + str(PROFILE) not in arguments
            or '--remote-debugging-address=127.0.0.1' not in arguments
            or '--remote-debugging-port=9222' not in arguments
            or os.readlink(lock).rsplit('-', 1)[-1] != str(binding['pid'])):
        raise RuntimeError('visible_browser_owner')
    x11, _ = process_binding(X11_BINDING['pid'])
    if x11 != X11_BINDING:
        raise RuntimeError('x11_owner')
    if browser is not None:
        version = browser._connection.send('Browser.getVersion')
        processes = browser._connection.send('SystemInfo.getProcessInfo')
        if not isinstance(version, dict) or version.get('product') != runtime['CDP_product']:
            raise RuntimeError('browser_version')
        if not isinstance(processes, dict) or not isinstance(processes.get('processInfo'), list):
            raise RuntimeError('cdp_process_shape')
        matches = [row for row in processes['processInfo'] if isinstance(row, dict) and row.get('type') == 'browser']
        if len(matches) != 1 or type(matches[0].get('id')) is not int or matches[0]['id'] != binding['pid']:
            raise RuntimeError('cdp_browser_owner')
    if (process_binding(binding['pid'])[0] != binding or process_binding(x11['pid'])[0] != x11
            or normalized_metadata(path_metadata(lock)) != normalized_metadata(runtime['profile_lock'])):
        raise RuntimeError('owner_changed')
    return {'browser': binding, 'x11': x11}


def quiet_services() -> dict:
    global stage
    stage = 'quiet_services'
    root = PHONE_PREFIX / 'var/service'
    services = check_inventory(inventory(root), SNAPSHOT['service_inventory'], service=True)
    for name, row in services.items():
        if name != '.' and '/' not in name and row.get('type') == 'directory':
            if services.get(name + '/down', {}).get('type') != 'file':
                raise RuntimeError('service_not_disabled')
        if row.get('type') == 'symlink':
            if (not name.endswith('/log/run') or row.get('link_text') != str(LOGGER_TARGET)
                    or (root / name).resolve(strict=True) != LOGGER_TARGET):
                raise RuntimeError('service_logger_link')
    expected_logger = {key: value for key, value in SNAPSHOT['logger_target'].items() if key != 'path'}
    plain(LOGGER_TARGET)
    if path_metadata(LOGGER_TARGET) != expected_logger:
        raise RuntimeError('service_logger_target')
    owner = subprocess.run([str(PHONE_PREFIX / 'bin/dpkg-query'), '-S', str(LOGGER_TARGET)],
                           capture_output=True, text=True, timeout=5, check=False)
    if owner.returncode != 0 or owner.stdout.strip() != 'termux-services: ' + str(LOGGER_TARGET):
        raise RuntimeError('service_logger_package')
    blocked = {'uvicorn', 'watch_glasses.py', 'watch_reply.py', 'run_exam_deck.py', 'live_one.py',
               'live_image.py', 'probe_send.py', 'phone_serve.sh', 'phone_watch.sh',
               'app.main', 'app.main:app', 'app.work_mcp', 'work_mcp.py'}
    processes = subprocess.run(['/system/bin/ps', '-u', str(PHONE_UID), '-o', 'UID,PID,ARGS'],
                               capture_output=True, timeout=5, check=False)
    if processes.returncode != 0 or processes.stderr:
        raise RuntimeError('process_snapshot_failed')
    rows = processes.stdout.decode('utf-8').splitlines()
    if not rows or rows[0].split()[:2] != ['UID', 'PID']:
        raise RuntimeError('process_snapshot_shape')
    seen = set()
    for row in rows[1:]:
        fields = row.split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise RuntimeError('process_snapshot_shape')
        uid, pid = int(fields[0]), int(fields[1])
        if uid != PHONE_UID or pid <= 0 or pid in seen:
            raise RuntimeError('process_snapshot_owner_or_duplicate')
        seen.add(pid)
        if pid != os.getpid() and {PurePosixPath(word).name for word in fields[2].split()} & blocked:
            raise RuntimeError('api_watch_or_producer_active')
    if not {os.getpid(), BROWSER_BINDING['pid'], X11_BINDING['pid']} <= seen:
        raise RuntimeError('process_snapshot_incomplete')
    return services


def native_guard(expected_sources: dict, browser=None) -> dict:
    global stage
    stage = 'protected_source_env'
    if source_metadata(PHONE_REPO, expected_sources) != expected_sources:
        raise RuntimeError('unexpected_source_metadata')
    parents = {}
    required_parents = {str(PHONE_HOME), str(PHONE_REPO), str(PHONE_HOME / 'rokid-backups')}
    if set(SNAPSHOT['parent_directories']) != required_parents:
        raise RuntimeError('parent_directory_scope')
    for name, row in SNAPSHOT['parent_directories'].items():
        private_directory(Path(name))
        actual = normalized_metadata(path_metadata(Path(name)))
        if actual != normalized_metadata(row):
            raise RuntimeError('parent_directory_changed')
        parents[name] = actual
    protected = {}
    for name, row in SNAPSHOT['protected_paths'].items():
        path = Path(name)
        if not path.is_relative_to(PHONE_REPO) or path == PHONE_REPO:
            raise RuntimeError('protected_scope')
        plain(path)
        protected[name] = path_metadata(path)
        if protected[name] != row:
            raise RuntimeError('protected_bytes_changed')
    source_inventory = {}
    for root_name in ('app', 'scripts'):
        expected = dict(SNAPSHOT['source_inventory'][root_name])
        for name, row in expected_sources.items():
            parts = PurePosixPath(name).parts
            if parts[0] != root_name:
                continue
            relative = '/'.join(parts[1:])
            if row['exists']:
                expected[relative] = row
            else:
                expected.pop(relative, None)
        check_inventory(inventory(PHONE_REPO / root_name), expected)
        source_inventory[root_name] = hashlib.sha256(json.dumps(SNAPSHOT['source_inventory'][root_name], sort_keys=True).encode()).hexdigest()
    boot = check_inventory(inventory(PHONE_HOME / '.termux/boot'), SNAPSHOT['boot_inventory'])
    git = check_inventory(inventory(PHONE_REPO / '.git'), SNAPSHOT['git_inventory'])
    env = PHONE_REPO / GUARD_ENV
    if protected.get(str(env), {}).get('mode') != 0o600:
        raise RuntimeError('private_env_changed')
    validation = ('set -a; . "$1"; test "$ROKID_CHATGPT_SEND_ENABLED" = 0 && '
                  'test "$ROKID_REAL_MODE" = 1 && test "$ROKID_DATA_DIR" = "$2" && '
                  'test -n "${ROKID_API_KEY:-}" && '
                  'test "${ROKID_BROWSER_PROFILE:-$2/chromium-profile}" = "$2/chromium-profile"')
    checked = subprocess.run([str(PHONE_PREFIX / 'bin/bash'), '--noprofile', '--norc', '-c', validation,
                              'private-env-check', str(env), str(PHONE_REPO / 'data')],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if checked.returncode != 0:
        raise RuntimeError('private_send0')
    services = quiet_services()
    owner = retained_owner(browser)
    return {'protected': protected, 'parents': parents, 'services': services, 'boot': boot, 'git': git,
            'source_inventory': source_inventory, **owner}


def native_main() -> dict:
    global stage
    request = read_request(sys.stdin.buffer, WIRE_LENGTH)
    if not isinstance(request, dict) or set(request) != {'action', 'archive', 'manifest', 'snapshot'} or request['action'] not in {'inspect', 'update'}:
        raise RuntimeError('request_shape')
    manifest_content = base64.b64decode(request['manifest'], validate=True)
    if hashlib.sha256(manifest_content).hexdigest() != MANIFEST_SHA:
        raise RuntimeError('request_manifest_changed')
    set_configuration(json.loads(manifest_content), base64.b64decode(request['snapshot'], validate=True))
    if os.name != 'posix' or os.getuid() != PHONE_UID:
        raise RuntimeError('phone_uid')
    content = base64.b64decode(request['archive'], validate=True)
    if len(content) != ARCHIVE['size']:
        raise RuntimeError('archive_size')
    files = load_bundle(content, NEW_ARCHIVE_SHA, ARCHIVE['files'])
    old_sources = SNAPSHOT['source_paths']
    native_guard(old_sources)
    plain(BACKUP)
    private_directory(BACKUP.parent)
    if BACKUP.exists():
        raise RuntimeError('transaction_already_exists')
    stage = 'existing_cdp_connect'
    cdp = runpy.run_path(str(PHONE_REPO / 'app/solvers/cdp.py'))
    browser = cdp['connect_over_cdp']('http://127.0.0.1:9222', timeout_s=8)
    try:
        def guard(expected):
            return native_guard(expected, browser)
        guard(old_sources)
        if request['action'] == 'update':
            receipt = update_sources(PHONE_REPO, BACKUP, files, old_sources, guard,
                new_modes={name: 0o700 if row['mode'] & 0o111 else 0o600 for name, row in ARCHIVE['files'].items()})
            receipt_sha, writes, phase = sha(BACKUP / 'manifest.json'), receipt['source_writes'], 'source_prepared_send0'
        else:
            receipt_sha, writes, phase = None, 0, 'source_update_readonly_preflight'
        stage = 'complete'
        return {'phase': phase, 'stage': stage, 'source_files': len(files), 'source_writes': writes,
                'source_bundle_commit': SOURCE_COMMIT, 'archive_sha256': NEW_ARCHIVE_SHA,
                'receipt_sha256': receipt_sha, 'protected_bytes_unchanged': True,
                'browser_x11_retained': True, 'phone_git_metadata_updated': False,
                'SEND_enabled': False, 'solver_verified': False,
                'browser_launch_attempts': 0, 'browser_close_attempts': 0,
                'services_changed': 0, 'APK_installs': 0, 'Input_calls': 0, 'GPT_submissions': 0}
    finally:
        browser._connection.close()  # Disconnect this client; do not close the browser.


def public_failure(error: Exception) -> dict:
    allowed = {'AssertionError', 'CdpError', 'RuntimeError', 'ValueError', 'TypeError',
               'OSError', 'FileNotFoundError', 'PermissionError', 'JSONDecodeError',
               'TimeoutExpired', 'TimeoutError', 'SyntaxError'}
    kind = type(error).__name__
    return {'phase': 'source_update_stopped', 'stage': stage,
            'error_type': kind if kind in allowed else 'other',
            'transaction_phase': transaction_state['phase'],
            'source_writes': transaction_state['source_writes'], 'restored': transaction_state['restored']}


def is_sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and not set(value) - set('0123456789abcdef')


def artifact_name(value, suffix: str = '') -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 160 and value.endswith(suffix)
            and value not in {'.', '..'} and all(c.isascii() and (c.isalnum() or c in '._-') for c in value))


def validate_device(device: dict) -> None:
    if (not isinstance(device, dict) or set(device) != {'target', 'serial', 'model', 'uid'}
            or type(device['uid']) is not int or device['uid'] <= 0
            or not all(isinstance(device[k], str) and device[k].isascii() and 0 < len(device[k]) <= 256
                       and not any(c.isspace() for c in device[k]) for k in ('target', 'serial', 'model'))
            or not device['serial'].isalnum() or not device['target'].startswith('adb-' + device['serial'] + '-')
            or not device['target'].endswith('._adb-tls-connect._tcp')):
        raise RuntimeError('manifest_device')


def set_configuration(value: dict, snapshot_content: bytes) -> None:
    global TARGET, SERIAL, MODEL, PHONE_UID, BROWSER_BINDING, X11_BINDING, BOOT_SHA
    global SOURCE_COMMIT, NEW_ARCHIVE_SHA, SNAPSHOT_SHA, ARCHIVE, SNAPSHOT, GUARD_ENV, BACKUP
    if (not isinstance(value, dict) or set(value) !=
            {'schema', 'device', 'source_commit', 'archive', 'snapshot', 'guard_env', 'backup'}
            or type(value['schema']) is not int or value['schema'] != 2):
        raise RuntimeError('manifest_schema')
    device, archive, pin = value['device'], value['archive'], value['snapshot']
    validate_device(device)
    commit = value['source_commit']
    if (not isinstance(commit, str) or len(commit) != 40 or set(commit) - set('0123456789abcdef')
            or not isinstance(archive, dict) or set(archive) != {'file', 'sha256', 'size', 'files'}
            or not artifact_name(archive['file'], '.tar') or not is_sha(archive['sha256'])
            or type(archive['size']) is not int or not 0 < archive['size'] <= MAX_BUNDLE_BYTES
            or not isinstance(archive['files'], dict) or not ROOT_FILES.issubset(archive['files'])
            or not isinstance(pin, dict) or set(pin) != {'file', 'sha256'}
            or not artifact_name(pin['file'], '.json') or not is_sha(pin['sha256'])
            or hashlib.sha256(snapshot_content).hexdigest() != pin['sha256']
            or not artifact_name(value['backup']) or not artifact_name(value['guard_env'], '.env')):
        raise RuntimeError('manifest_source_or_snapshot')
    for name, row in archive['files'].items():
        if (not source_path(name) or not isinstance(row, dict) or set(row) != {'sha256', 'size', 'mode'}
                or not is_sha(row['sha256']) or type(row['size']) is not int or not 0 <= row['size'] <= MAX_BUNDLE_BYTES
                or type(row['mode']) is not int or row['mode'] not in {0o644, 0o755}):
            raise RuntimeError('manifest_archive_file')
    snapshot_report = json.loads(snapshot_content)
    if (not isinstance(snapshot_report, dict) or type(snapshot_report.get('exit_code')) is not int
            or snapshot_report['exit_code'] != 0 or snapshot_report.get('result', {}).get('ok') is not True):
        raise RuntimeError('snapshot_report_failed')
    snapshot = snapshot_report['result'].get('public')
    needed = {'device', 'source_paths', 'source_inventory', 'protected_paths', 'service_inventory',
              'boot_inventory', 'git_inventory', 'logger_target', 'env_flags', 'runtime',
              'parent_directories', 'owned_process_inventory', 'logger_package_owner'}
    if (not isinstance(snapshot, dict) or not needed.issubset(snapshot) or snapshot.get('read_only') is not True
            or type(snapshot.get('UI_input_calls')) is not int or snapshot['UI_input_calls'] != 0
            or snapshot['device'] != device or set(snapshot['source_paths']) != set(archive['files'])):
        raise RuntimeError('snapshot_scope_or_device')
    required_protected = {'multimodal.env', value['guard_env'], 'requirements.txt', *ROOT_FILES,
                          'data/browser-state/submission.json', 'data/browser-state/chats.json',
                          *(name + suffix for name in ('data/docscan.db', 'data/work-jobs.db')
                            for suffix in ('', '-wal', '-shm', '-journal'))}
    if set(snapshot['protected_paths']) != {(PHONE_REPO / name).as_posix() for name in required_protected}:
        raise RuntimeError('snapshot_protected_scope')
    if (set(snapshot['source_inventory']) != {'app', 'scripts'}
            or snapshot['logger_target'].get('path') != LOGGER_TARGET.as_posix()
            or snapshot['logger_package_owner'].get('exit_code') != 0
            or snapshot['logger_package_owner'].get('package') != 'termux-services'
            or snapshot['logger_package_owner'].get('path') != LOGGER_TARGET.as_posix()
            or snapshot['owned_process_inventory'].get('exit_code') != 0
            or snapshot['owned_process_inventory'].get('producer_matches') != []):
        raise RuntimeError('snapshot_service_or_inventory_scope')
    for row in snapshot['source_paths'].values():
        if row == {'exists': False}:
            continue
        if (not isinstance(row, dict) or set(row) != {'exists', 'type', 'sha256', 'size', 'mode', 'uid'}
                or row['exists'] is not True or row['type'] != 'file' or row['uid'] != device['uid']
                or not is_sha(row['sha256']) or type(row['size']) is not int or row['size'] < 0
                or type(row['mode']) is not int or not 0 <= row['mode'] <= 0o777 or row['mode'] & 0o022):
            raise RuntimeError('snapshot_source_metadata')
    for name in ROOT_FILES:
        if snapshot['source_paths'][name].get('sha256') != archive['files'][name]['sha256']:
            raise RuntimeError('dependency_file_change_out_of_scope')
    flags = snapshot['env_flags'].get(value['guard_env'], {})
    if (flags.get('ROKID_CHATGPT_SEND_ENABLED') != '0' or flags.get('ROKID_REAL_MODE') != '1'
            or flags.get('API_key_present') is not True):
        raise RuntimeError('snapshot_send0_env')
    runtime = snapshot['runtime']
    for binding in (runtime['browser'], runtime['x11']):
        if (not isinstance(binding, dict) or set(binding) != {'pid', 'starttime', 'boot'}
                or any(type(binding[k]) is not int or binding[k] <= 0 for k in ('pid', 'starttime'))
                or not is_sha(binding['boot'])):
            raise RuntimeError('snapshot_owner_binding')
    if (runtime['browser']['pid'] == runtime['x11']['pid'] or runtime['browser']['boot'] != runtime['x11']['boot']
            or not isinstance(runtime['CDP_product'], str) or not runtime['CDP_product'].startswith('Chrome/')
            or runtime['ports'] != {'8000_open': False, '9222_open': True}):
        raise RuntimeError('snapshot_runtime')
    TARGET, SERIAL, MODEL, PHONE_UID = (device[k] for k in ('target', 'serial', 'model', 'uid'))
    SOURCE_COMMIT, NEW_ARCHIVE_SHA, SNAPSHOT_SHA = commit, archive['sha256'], pin['sha256']
    ARCHIVE, SNAPSHOT = archive, snapshot
    BROWSER_BINDING, X11_BINDING, BOOT_SHA = runtime['browser'], runtime['x11'], runtime['browser']['boot']
    GUARD_ENV, BACKUP = value['guard_env'], PHONE_HOME / 'rokid-backups' / value['backup']


def configure(manifest: Path, manifest_sha: str) -> dict:
    """The pinned manifest names both a fixed commit and a fresh snapshot."""
    global MANIFEST_SHA, MANIFEST_CONTENT, SNAPSHOT_CONTENT
    plain(manifest)
    if (not is_sha(manifest_sha) or not manifest.resolve().is_relative_to(REPORTS.resolve())
            or manifest.stat().st_size > 1024 * 1024 or sha(manifest) != manifest_sha):
        raise RuntimeError('untrusted_local_manifest')
    content = manifest.read_bytes()
    value = json.loads(content)
    name = value.get('snapshot', {}).get('file') if isinstance(value, dict) else None
    if not artifact_name(name, '.json'):
        raise RuntimeError('snapshot_artifact_path')
    path = REPORTS / name
    plain(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise RuntimeError('snapshot_artifact_size')
    snapshot_content = path.read_bytes()
    set_configuration(value, snapshot_content)
    MANIFEST_SHA, MANIFEST_CONTENT, SNAPSHOT_CONTENT = manifest_sha, content, snapshot_content
    return {'manifest_sha256': manifest_sha, 'snapshot_sha256': SNAPSHOT_SHA}


def read_request(stream, count: int) -> dict:
    if type(count) is not int or not 0 < count <= MAX_WIRE_BYTES:
        raise RuntimeError('request_size')
    parts, remaining = [], count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk or not isinstance(chunk, bytes):
            raise RuntimeError('truncated_request')
        parts.append(chunk)
        remaining -= len(chunk)
    return json.loads(base64.b64decode(b''.join(parts), validate=True))


def verify_git_archive(files: dict[str, bytes]) -> None:
    def git(*args, input=None):
        result = subprocess.run(['git', '-C', str(ROOT), *args], input=input,
                                capture_output=True, timeout=30, check=False)
        if result.returncode != 0:
            raise RuntimeError('fixed_commit_unavailable')
        return result.stdout
    if git('rev-parse', '--verify', SOURCE_COMMIT + '^{commit}').decode('ascii').strip() != SOURCE_COMMIT:
        raise RuntimeError('fixed_commit_not_commit')
    listing = git('ls-tree', '-r', '-l', '-z', SOURCE_COMMIT, '--', 'app', 'scripts', *sorted(ROOT_FILES))
    entries = []
    for record in listing.split(b'\0'):
        if not record:
            continue
        header, raw_name = record.split(b'\t', 1)
        mode, kind, oid, size = header.split()
        name = raw_name.decode('utf-8')
        expected = ARCHIVE['files'].get(name)
        if (kind != b'blob' or mode not in {b'100644', b'100755'} or name not in files
                or expected is None or int(size) != expected['size']
                or int(mode, 8) & 0o777 != expected['mode']):
            raise RuntimeError('archive_git_path_size_or_mode')
        entries.append((name, oid, int(size)))
    if len(entries) != len(files) or {entry[0] for entry in entries} != set(files):
        raise RuntimeError('archive_git_path_set')
    output = io.BytesIO(git('cat-file', '--batch', input=b''.join(oid + b'\n' for _, oid, _ in entries)))
    for name, oid, size in entries:
        if output.readline().split() != [oid, b'blob', str(size).encode('ascii')]:
            raise RuntimeError('archive_git_blob_header')
        if output.read(size) != files[name] or output.read(1) != b'\n':
            raise RuntimeError('archive_git_blob_bytes')
    if output.read(1):
        raise RuntimeError('archive_git_blob_extra')


def prepare(provenance: dict, action: str = 'update') -> tuple[bytes, list[list[str]], dict]:
    """PC-only fixed-commit proof and compilation; execution is separate."""
    if not TARGET or action not in {'inspect', 'update'}:
        raise RuntimeError('unconfigured_prepare')
    archive_path = REPORTS / ARCHIVE['file']
    plain(archive_path)
    if archive_path.stat().st_size != ARCHIVE['size']:
        raise RuntimeError('archive_size')
    content = archive_path.read_bytes()
    files = load_bundle(content, NEW_ARCHIVE_SHA, ARCHIVE['files'])
    verify_git_archive(files)
    request = base64.b64encode(json.dumps({'action': action, 'archive': base64.b64encode(content).decode('ascii'),
        'manifest': base64.b64encode(MANIFEST_CONTENT).decode('ascii'),
        'snapshot': base64.b64encode(SNAPSHOT_CONTENT).decode('ascii')}, sort_keys=True).encode('ascii'))
    if len(request) > MAX_WIRE_BYTES:
        raise RuntimeError('request_size')
    functions = {'sha', 'source_path', 'load_bundle', 'plain', 'sync_directories', 'atomic_bytes',
        'path_metadata', 'source_metadata', 'file_identity', 'update_sources',
        'normalized_metadata', 'inventory', 'check_inventory', 'process_binding', 'private_directory',
        'retained_owner', 'quiet_services', 'native_guard', 'native_main', 'public_failure', 'is_sha', 'artifact_name',
        'validate_device', 'set_configuration', 'read_request'}
    constants = ('PHONE_HOME', 'PHONE_PREFIX', 'PHONE_REPO', 'PROFILE', 'LOGGER_TARGET', 'ROOT_FILES',
                 'MAX_BUNDLE_BYTES', 'MAX_WIRE_BYTES', 'MANIFEST_SHA')
    tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    body = '\n'.join(ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
    for name in constants:
        item = globals()[name]
        literal = 'Path(' + repr(item.as_posix()) + ')' if isinstance(item, Path) else (
            '{' + ','.join(repr(value) for value in sorted(item)) + '}' if isinstance(item, set) else repr(item))
        body += '\n' + name + ' = ' + literal
    body += "\nWIRE_LENGTH = " + str(len(request))
    body += "\nstage = 'native_input'\ntransaction_state = {'phase':'not_started','source_writes':0,'restored':False}\n"
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in functions]
    if len(definitions) != len(functions):
        raise RuntimeError('native_definition_scope')
    body += '\n\n'.join(ast.unparse(n) for n in definitions)
    body += '\ntry:\n print(json.dumps(native_main(),sort_keys=True))\nexcept Exception as error:\n print(json.dumps(public_failure(error),sort_keys=True))\n sys.exit(2)\n'
    compile(body, '<phone-source-update>', 'exec')
    encoded = base64.b64encode(zlib.compress(body.encode(), 9)).decode()
    bootstrap = "import base64,zlib;exec(compile(zlib.decompress(base64.b64decode(" + repr(encoded) + ")), '<phone-source-update>', 'exec'))"
    prefix = ('run-as com.termux /system/bin/env HOME=' + PHONE_HOME.as_posix() + ' PREFIX=' + PHONE_PREFIX.as_posix()
              + ' PATH=' + (PHONE_PREFIX / 'bin').as_posix() + ':/system/bin:/system/xbin TMPDIR=' + (PHONE_PREFIX / 'tmp').as_posix()
              + ' ' + (PHONE_PREFIX / 'bin/python').as_posix() + ' -B -I -c ')
    commands = [[ADB, 'devices', '-l'], [ADB, '-s', TARGET, 'shell', 'getprop', 'ro.serialno'],
                [ADB, '-s', TARGET, 'shell', 'getprop', 'ro.product.model'],
                [ADB, '-s', TARGET, 'shell', '-T', prefix + shlex.quote(bootstrap)]]
    wire = len(subprocess.list2cmdline(commands[-1]))
    if wire >= 32767:
        raise RuntimeError('windows_command_limit')
    metadata = {'phase': 'pc_source_update_prepared', 'approval_received': False, 'actual_runtime_executions': 0,
        'action': action, 'source_files': len(files), 'archive_sha256': NEW_ARCHIVE_SHA,
        'source_bundle_commit': SOURCE_COMMIT, 'git_blob_comparison_performed': True,
        'native_sha256': hashlib.sha256(body.encode()).hexdigest(), 'native_bytes': len(body.encode()),
        'bootstrap_sha256': hashlib.sha256(bootstrap.encode()).hexdigest(), 'bootstrap_bytes': len(bootstrap.encode()),
        'wire_characters': wire, 'request_sha256': hashlib.sha256(request).hexdigest(), 'request_bytes': len(request),
        'host_rows': 4, 'phone_git_metadata_updated': False, 'planned_services_changes': 0,
        'planned_APK_installs': 0, 'planned_Input_calls': 0, 'planned_GPT_submissions': 0,
        'planned_browser_starts_or_closes': 0, 'profile_normal_browser_writes_allowed': True,
        'unknown_partial_update_auto_resume': False, **provenance}
    return request, commands, metadata


def validate_public(result: dict, action: str) -> None:
    if not isinstance(result, dict):
        raise RuntimeError('native_public_shape')
    failure_keys = {'phase', 'stage', 'error_type', 'transaction_phase', 'source_writes', 'restored'}
    if result.get('phase') == 'source_update_stopped':
        if (set(result) != failure_keys or result['transaction_phase'] not in
                {'not_started', 'applying', 'rolled_back', 'rollback_blocked', 'source_prepared_send0'}
                or type(result['source_writes']) is not int or not 0 <= result['source_writes'] <= len(ARCHIVE['files'])
                or type(result['restored']) is not bool):
            raise RuntimeError('native_failure_shape')
        labels = {'native_input', 'existing_cdp_connect', 'protected_source_env',
                  'quiet_services', 'retained_browser_x11', 'source_update_preflight', 'atomic_source_update',
                  'source_update_final_guard', 'source_transaction_restore_preflight', 'restore_this_transaction_sources', 'complete'}
        if (result['stage'] not in labels or result['error_type'] not in
                {'AssertionError', 'CdpError', 'RuntimeError', 'ValueError', 'TypeError', 'OSError',
                 'FileNotFoundError', 'PermissionError', 'JSONDecodeError', 'TimeoutExpired', 'TimeoutError', 'SyntaxError', 'other'}):
            raise RuntimeError('native_failure_enum')
        return
    counters = ('browser_launch_attempts', 'browser_close_attempts', 'services_changed', 'APK_installs', 'Input_calls', 'GPT_submissions')
    keys = {'phase', 'stage', 'source_files', 'source_writes', 'source_bundle_commit', 'archive_sha256',
            'receipt_sha256', 'protected_bytes_unchanged', 'browser_x11_retained', 'phone_git_metadata_updated',
            'SEND_enabled', 'solver_verified', *counters}
    expected_phase = 'source_prepared_send0' if action == 'update' else 'source_update_readonly_preflight'
    if (set(result) != keys or result['phase'] != expected_phase or result['stage'] != 'complete'
            or type(result['source_files']) is not int or result['source_files'] != len(ARCHIVE['files'])
            or type(result['source_writes']) is not int or result['source_writes'] != (len(ARCHIVE['files']) if action == 'update' else 0)
            or result['source_bundle_commit'] != SOURCE_COMMIT or result['archive_sha256'] != NEW_ARCHIVE_SHA
            or result['protected_bytes_unchanged'] is not True or result['browser_x11_retained'] is not True
            or any(result[k] is not False for k in ('phone_git_metadata_updated', 'SEND_enabled', 'solver_verified'))
            or any(type(result[k]) is not int or result[k] != 0 for k in counters)
            or (not is_sha(result['receipt_sha256']) if action == 'update' else result['receipt_sha256'] is not None)):
        raise RuntimeError('native_completion_contract')


def dispatch_native(command: list[str], request: bytes):
    """One process/input; bounded waits keep the original 180-second deadline."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 180
    pending_input = request
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, 180)
            try:
                stdout, stderr = process.communicate(input=pending_input, timeout=min(5, remaining))
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                pending_input = None  # communicate resumes its existing buffered input; no new process/send.
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def execute(request: bytes, commands: list[list[str]], metadata: dict) -> int:
    """One dispatch only; even a failed/timeout call retains its attempted argv."""
    results = []
    execution = {'phase': 'host_identity', 'native_attempts': 0, 'error_type': None}
    try:
        for index, command in enumerate(commands):
            row = {'command': command, 'exit_code': None}
            results.append(row)
            if index == 3:
                execution.update(phase='native_dispatch', native_attempts=1)
            output = dispatch_native(command, request) if index == 3 else subprocess.run(
                command, capture_output=True, timeout=15, check=False)
            row.update(exit_code=output.returncode, stdout_bytes=len(output.stdout), stderr_bytes=len(output.stderr))
            if index == 3:
                result = json.loads(output.stdout)
                validate_public(result, metadata['action'])
                row['public_result'] = result  # only the exact allowlisted shape, never raw output
                if output.returncode != 0 or result['phase'] == 'source_update_stopped':
                    raise RuntimeError('native_stopped')
            else:
                if output.returncode != 0:
                    raise RuntimeError('identity_command_failed')
                text = output.stdout.decode('utf-8').strip()
                if index == 0:
                    entries = [line.split() for line in text.splitlines() if line.strip() and not line.startswith('List of devices')]
                    if len(entries) != 1 or entries[0][:2] != [TARGET, 'device']:
                        raise RuntimeError('sole_transport_identity')
                elif text != (SERIAL if index == 1 else MODEL):
                    raise RuntimeError('serial_or_model_identity')
                row['identity_verified'] = True
        execution['phase'] = 'complete'
    except Exception as error:
        kind = type(error).__name__
        execution['error_type'] = kind if kind in {'RuntimeError', 'TimeoutExpired', 'OSError', 'FileNotFoundError', 'JSONDecodeError', 'UnicodeDecodeError'} else 'other'
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    report = REPORTS / ('phone-source-update-' + stamp + '.json')
    record = {'invocation_flag': INSPECT_FLAG if metadata['action'] == 'inspect' else EXECUTE_FLAG,
              'read_only': metadata['action'] == 'inspect', 'preparation_metadata': metadata,
              'execution': execution, 'results': results}
    with report.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
    print(json.dumps({'phase': execution['phase'], 'error_type': execution['error_type'],
                      'native_attempts': execution['native_attempts'], 'report': str(report),
                      'report_sha256': sha(report)}, sort_keys=True))
    return 0 if execution['phase'] == 'complete' else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(EXECUTE_FLAG, action='store_true')
    group.add_argument(INSPECT_FLAG, action='store_true')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    if args.manifest_sha256 is None:
        if args.execute_approved_source_update or args.inspect_readonly:
            parser.error('--manifest-sha256 is required')
        print(json.dumps({'phase': 'pc_manifest_required', 'default_manifest': str(args.manifest),
                          'device_commands': 0, 'approval_received': False, 'actual_runtime_executions': 0}))
        return 0
    try:
        provenance = configure(args.manifest, args.manifest_sha256)
        action = 'inspect' if args.inspect_readonly else 'update'
        request, commands, metadata = prepare(provenance, action)
        if args.execute_approved_source_update or args.inspect_readonly:
            return execute(request, commands, metadata)
        print(json.dumps(metadata, sort_keys=True))
        return 0
    except Exception as error:
        kind = type(error).__name__
        print(json.dumps({'phase': 'pc_preparation_stopped', 'error_type': kind if kind in
                          {'RuntimeError', 'OSError', 'FileNotFoundError', 'ValueError', 'TypeError', 'JSONDecodeError', 'SyntaxError'} else 'other'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
