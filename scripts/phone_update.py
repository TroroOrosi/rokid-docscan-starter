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
import zlib

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'data/device-setup/reports/venue-pc-20260930'
ADB = str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Android/Sdk/platform-tools/adb.exe')
DEFAULT_MANIFEST = REPORTS / 'phone-source-update-manifest-20261004.json'
TARGET = SERIAL = MODEL = ''
PHONE_UID = 0
EXECUTE_FLAG = '--execute-approved-source-update'
INSPECT_FLAG = '--inspect-readonly'
NEW_ARCHIVE = 'venue-phone-c9deb74-20261003-source.tar'
OLD_ARCHIVE = 'venue-phone-67f8576.tar'
NEW_ARCHIVE_SHA = '21d770bd7eab68c33813cdd4a973dcdb5c9df6381a2816bd6d7ebb4f3d0ec290'
OLD_ARCHIVE_SHA = ''
SOURCE_COMMIT = 'c9deb74eb3f4d95a7c2ce6d56b52bcc28d49d137'
SOURCE_HEAD = 'b94be6ef5d4af8ec41c73922b87b4d0e1f071ee6'
PHONE_HOME = Path('/data/data/com.termux/files/home')
PHONE_PREFIX = Path('/data/data/com.termux/files/usr')
PHONE_REPO = PHONE_HOME / 'rokid-server'
PROFILE = PHONE_REPO / 'data/chromium-profile'
HELPER = PHONE_HOME / 'rokid-deploy-67f8576-20261001/phone-deploy-20261001.py'
HELPER_SHA = CDP_SHA = BOOT_SHA = LOGGER_SHA = PRESERVED_SHA = ''
BROWSER_BINDING = {}
X11_BINDING = {}
BACKUP = PHONE_HOME / 'rokid-backups/pre-c9deb74-source-20261004'
LOGGER_TARGET = PHONE_PREFIX / 'share/termux-services/svlogger'
LOGGER_LEAVES = {PHONE_PREFIX / 'var/service' / name / 'log/run'
                 for name in ('ssh-agent', 'sshd', 'tx11', 'tx11-xfce4')}
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


def load_bundle(content: bytes, expected_sha: str) -> dict[str, bytes]:
    if len(content) > 2 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != expected_sha:
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
            if not member.isfile() or member.size < 0 or member.size > 2 * 1024 * 1024:
                raise RuntimeError('unsafe_bundle_member')
            total += member.size
            if total > 2 * 1024 * 1024:
                raise RuntimeError('bundle_total_size')
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError('unreadable_bundle_member')
            data = stream.read()
            if member.name.endswith('.py'):
                compile(data, member.name, 'exec')
            if member.name.endswith('.sh') and b'\r' in data:
                raise RuntimeError('non_LF_shell')
            files[member.name] = data
    if len(files) != 79 or not ROOT_FILES.issubset(files):
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


def atomic_bytes(path: Path, content: bytes, mode: int) -> None:
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
        os.replace(temporary, path)
        sync_directories(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)  # only this call's own temporary


def source_hashes(repo: Path, names) -> dict[str, str]:
    result = {}
    for name in names:
        if not source_path(name):
            raise RuntimeError('unsafe_source_path')
        path = repo / name
        plain(path)
        if not path.is_file():
            raise RuntimeError('missing_source')
        result[name] = sha(path)
    return result


def update_sources(repo: Path, backup: Path, files: dict[str, bytes], old_hashes: dict[str, str],
                   guard, write=atomic_bytes) -> dict:
    """One transaction. An existing/partial journal is never resumed or overwritten."""
    global stage
    if set(files) != set(old_hashes) or len(files) != 79:
        raise RuntimeError('source_scope')
    plain(repo)
    plain(backup)
    if backup.exists():
        raise RuntimeError('transaction_already_exists')
    stage = 'source_update_preflight'
    before = guard(old_hashes)
    if source_hashes(repo, files) != old_hashes:
        raise RuntimeError('unknown_old_source')
    previous = {name: {'sha256': old_hashes[name], 'mode': stat.S_IMODE((repo / name).stat().st_mode),
                       'new_sha256': hashlib.sha256(data).hexdigest()}
                for name, data in files.items()}
    needed = sum(len(data) + (repo / name).stat().st_size for name, data in files.items()) + 16 * 1024 * 1024
    if shutil.disk_usage(repo).free < needed:
        raise RuntimeError('backup_space')
    os.umask(0o077)
    backup.mkdir(parents=True, mode=0o700)
    receipt = {'phase': 'backing_up', 'source_bundle_commit': SOURCE_COMMIT,
               'reference_runtime_commit': SOURCE_HEAD, 'archive_sha256': NEW_ARCHIVE_SHA,
               'old_archive_sha256': OLD_ARCHIVE_SHA, 'sources': previous,
               'protected_and_owner': before, 'source_writes': 0,
               'phone_git_metadata_updated': False}
    journal = backup / 'manifest.json'

    def save():
        write(journal, json.dumps(receipt, sort_keys=True).encode(), 0o600)

    save()
    for name in files:
        target = backup / 'source' / name
        write(target, (repo / name).read_bytes(), 0o600)
        if sha(target) != old_hashes[name]:
            raise RuntimeError('backup_checksum')
    if guard(old_hashes) != before:
        raise RuntimeError('pre_update_state_changed')
    receipt['phase'] = 'applying'
    transaction_state['phase'] = 'applying'
    save()
    try:
        stage = 'atomic_source_update'
        for name, payload in files.items():
            # No private root or whole app/scripts tree is renamed.
            plain(repo / name)
            if (sha(repo / name) != old_hashes[name]
                    or stat.S_IMODE((repo / name).stat().st_mode) != previous[name]['mode']):
                raise RuntimeError('source_changed_during_update')
            write(repo / name, payload, previous[name]['mode'])
            receipt['source_writes'] += 1
            transaction_state['source_writes'] = receipt['source_writes']
            save()
        stage = 'source_update_final_guard'
        new_hashes = {name: row['new_sha256'] for name, row in previous.items()}
        if source_hashes(repo, files) != new_hashes or guard(new_hashes) != before:
            raise RuntimeError('post_update_state_changed')
        receipt['phase'] = 'source_prepared_send0'
        save()
        transaction_state['phase'] = receipt['phase']
        return receipt
    except BaseException:
        stage = 'source_transaction_restore_preflight'
        try:
            current = source_hashes(repo, files)
            if any(current[name] not in {row['sha256'], row['new_sha256']}
                   for name, row in previous.items()):
                raise RuntimeError('unknown_partial_source')
            if guard(current) != before:
                raise RuntimeError('restore_owner_or_protected_changed')
            for name in files:
                target = backup / 'source' / name
                plain(target)
                if sha(target) != old_hashes[name]:
                    raise RuntimeError('restore_backup_changed')
            stage = 'restore_this_transaction_sources'
            for name, row in previous.items():
                plain(repo / name)
                if (sha(repo / name) not in {row['sha256'], row['new_sha256']}
                        or stat.S_IMODE((repo / name).stat().st_mode) != row['mode']):
                    raise RuntimeError('source_changed_before_restore')
                write(repo / name, (backup / 'source' / name).read_bytes(), row['mode'])
            if source_hashes(repo, files) != old_hashes or guard(old_hashes) != before:
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


def process_binding(pid: int) -> tuple[dict, list[str]]:
    if type(pid) is not int or pid <= 0 or sha(Path('/proc/sys/kernel/random/boot_id')) != BOOT_SHA:
        raise RuntimeError('process_boot_or_pid')
    process = Path('/proc') / str(pid)
    start = int((process / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    arguments = [data.decode('utf-8', 'replace') for data in (process / 'cmdline').read_bytes().split(b'\0') if data]
    return {'pid': pid, 'uid': process.stat().st_uid, 'starttime': start,
            'boot_id_sha256': BOOT_SHA}, arguments


def snapshot_logger(leaf: Path, cache: dict) -> dict:
    if leaf not in LOGGER_LEAVES:
        raise RuntimeError('unexpected_logger_leaf')
    plain(leaf.parent)
    parent = leaf.parent.stat()
    link = leaf.lstat()
    if (not leaf.parent.is_dir() or parent.st_uid != PHONE_UID or stat.S_IMODE(parent.st_mode) != 0o700
            or not stat.S_ISLNK(link.st_mode) or link.st_uid != PHONE_UID or stat.S_IMODE(link.st_mode) != 0o777
            or os.readlink(leaf) != str(LOGGER_TARGET) or leaf.resolve(strict=True) != LOGGER_TARGET):
        raise RuntimeError('service_logger_link')
    plain(LOGGER_TARGET)
    if LOGGER_TARGET not in cache:
        info = LOGGER_TARGET.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != PHONE_UID
                or stat.S_IMODE(info.st_mode) != 0o700 or sha(LOGGER_TARGET) != LOGGER_SHA):
            raise RuntimeError('service_logger_target')
        owner = subprocess.run([str(PHONE_PREFIX / 'bin/dpkg-query'), '-S', str(LOGGER_TARGET)],
                               capture_output=True, text=True, timeout=5, check=False)
        if owner.returncode or owner.stdout.strip() != 'termux-services: ' + str(LOGGER_TARGET):
            raise RuntimeError('service_logger_package')
        cache[LOGGER_TARGET] = {'target': str(LOGGER_TARGET), 'target_sha256': LOGGER_SHA,
                                'target_uid': info.st_uid, 'target_mode': stat.S_IMODE(info.st_mode),
                                'target_package': 'termux-services'}
    return {'kind': 'symlink', 'link_text': str(LOGGER_TARGET), 'uid': link.st_uid, 'mode': stat.S_IMODE(link.st_mode),
            'parent_uid': parent.st_uid, 'parent_mode': stat.S_IMODE(parent.st_mode), **cache[LOGGER_TARGET]}


def private_directory(path: Path) -> None:
    plain(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != PHONE_UID or info.st_mode & 0o022:
        raise RuntimeError('private_directory_owner')


def retained_owner(browser) -> dict:
    global stage
    stage = 'retained_browser_x11'
    private_directory(PHONE_HOME)
    private_directory(PHONE_REPO)
    plain(PROFILE)
    info = PROFILE.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != PHONE_UID or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('private_profile')
    for path, mode, kind in ((PHONE_PREFIX / 'tmp', 0o700, stat.S_ISDIR),
                             (PHONE_PREFIX / 'tmp/.X11-unix', 0o1777, stat.S_ISDIR),
                             (PHONE_PREFIX / 'tmp/.X11-unix/X1', 0o777, stat.S_ISSOCK)):
        info = path.lstat()
        if info.st_uid != PHONE_UID or stat.S_IMODE(info.st_mode) != mode or not kind(info.st_mode):
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
            or '--remote-debugging-port=9222' not in arguments):
        raise RuntimeError('visible_browser_owner')
    lock = PROFILE / 'SingletonLock'
    info = lock.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != PHONE_UID or os.readlink(lock).rsplit('-', 1)[-1] != str(binding['pid']):
        raise RuntimeError('profile_lock_owner')
    x11, _ = process_binding(X11_BINDING['pid'])
    if x11 != X11_BINDING:
        raise RuntimeError('x11_owner')
    version = browser._connection.send('Browser.getVersion')
    processes = browser._connection.send('SystemInfo.getProcessInfo')
    if not isinstance(version, dict) or version.get('product') != 'Chrome/149.0.7827.155':
        raise RuntimeError('browser_version')
    if not isinstance(processes, dict) or not isinstance(processes.get('processInfo'), list):
        raise RuntimeError('cdp_process_shape')
    matches = [p for p in processes['processInfo'] if isinstance(p, dict) and p.get('type') == 'browser']
    if len(matches) != 1 or type(matches[0].get('id')) is not int or matches[0]['id'] != binding['pid']:
        raise RuntimeError('cdp_browser_owner')
    if process_binding(binding['pid'])[0] != binding or process_binding(x11['pid'])[0] != x11:
        raise RuntimeError('owner_changed')
    if os.readlink(lock).rsplit('-', 1)[-1] != str(binding['pid']):
        raise RuntimeError('lock_changed')
    return {'browser': binding, 'x11': x11}


def quiet_services(old) -> dict:
    global stage
    stage = 'quiet_services'
    root = PHONE_PREFIX / 'var/service'
    plain(root)
    if {p.name for p in root.iterdir()} != {'cupsd', 'ssh-agent', 'sshd', 'tx11', 'tx11-xfce4'}:
        raise RuntimeError('service_inventory')
    services, targets = {}, {}
    for service in root.iterdir():
        plain(service)
        info = service.stat()
        if not service.is_dir() or info.st_uid != PHONE_UID or not (service / 'down').is_file():
            raise RuntimeError('service_not_disabled')
        files = {}
        for name in ('down', 'run', 'log/run'):
            path = service / name
            if path in LOGGER_LEAVES:
                files[name] = snapshot_logger(path, targets)
            else:
                old['plain'](path)
                if path.exists():
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != PHONE_UID:
                        raise RuntimeError('service_file_owner')
                    files[name] = {'sha256': sha(path), 'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)}
        services[service.name] = {'uid': service.stat().st_uid,
                                  'mode': stat.S_IMODE(service.stat().st_mode), 'files': files}
    blocked = {'uvicorn', 'runsv', 'runsvdir', 'watch_glasses.py', 'watch_reply.py',
               'run_exam_deck.py', 'live_one.py', 'live_image.py', 'probe_send.py',
               'phone_serve.sh', 'phone_watch.sh'}
    process_list = subprocess.run(['/system/bin/ps', '-u', str(PHONE_UID), '-o', 'UID,PID'],
                                  capture_output=True, timeout=5, check=False)
    if type(process_list.returncode) is not int or process_list.returncode != 0 or process_list.stderr:
        raise RuntimeError('process_snapshot_failed')
    try:
        rows = process_list.stdout.decode('ascii').splitlines()
    except UnicodeDecodeError:
        raise RuntimeError('process_snapshot_shape') from None
    if not rows or rows[0].split() != ['UID', 'PID']:
        raise RuntimeError('process_snapshot_shape')
    pids = set()
    for row in rows[1:]:
        fields = row.split()
        if len(fields) != 2 or not all(field.isdigit() for field in fields):
            raise RuntimeError('process_snapshot_shape')
        uid, pid = map(int, fields)
        if uid != PHONE_UID or pid <= 0 or pid in pids:
            raise RuntimeError('process_snapshot_owner_or_duplicate')
        pids.add(pid)
    if not {os.getpid(), BROWSER_BINDING['pid'], X11_BINDING['pid']} <= pids:
        raise RuntimeError('process_snapshot_incomplete')
    for pid in sorted(pids):
        if pid == os.getpid():
            continue
        directory = Path('/proc') / str(pid)
        try:
            if directory.stat().st_uid != PHONE_UID:
                raise RuntimeError('process_owner_changed')
            names = {Path(a.decode('utf-8', 'replace')).name for a in (directory / 'cmdline').read_bytes().split(b'\0') if a}
        except FileNotFoundError:
            continue
        if names & blocked:
            raise RuntimeError('api_watch_or_supervisor_active')
    return services


def git_metadata_digest() -> str | None:
    root = PHONE_REPO / '.git'
    try:
        root.lstat()
    except FileNotFoundError:
        return None
    private_directory(root)
    records = {}
    for path in sorted(root.rglob('*')):
        plain(path)
        info = path.stat()
        if info.st_uid != PHONE_UID:
            raise RuntimeError('git_owner')
        records[path.relative_to(root).as_posix()] = {
            'mode': stat.S_IMODE(info.st_mode), 'sha256': sha(path) if path.is_file() else None}
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def native_guard(old, record: dict, browser, expected_sources: dict) -> dict:
    global stage
    stage = 'protected_source_env'
    old['require_phone']()
    protected = old['protected_hashes']()
    if protected != record['protected']:
        raise RuntimeError('protected_bytes_changed')
    env = old['ENV_COPY']
    plain(env)
    if sha(env) != record['env_copy_sha256'] or stat.S_IMODE(env.stat().st_mode) != 0o600:
        raise RuntimeError('private_env_changed')
    # Only the already pinned private copy is sourced; no values leave the process.
    validation = ('set -a; . "$1"; test "$ROKID_CHATGPT_SEND_ENABLED" = 0 && '
                  'test "$ROKID_DATA_DIR" = "$2" && test -n "${ROKID_API_KEY:-}" && '
                  'test "${ROKID_BROWSER_PROFILE:-$2/chromium-profile}" = "$2/chromium-profile"')
    check = subprocess.run([str(PHONE_PREFIX / 'bin/bash'), '--noprofile', '--norc', '-c', validation,
                            'private-env-check', str(env), str(PHONE_REPO / 'data')],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if check.returncode:
        raise RuntimeError('private_send0')
    if source_hashes(PHONE_REPO, expected_sources) != expected_sources:
        raise RuntimeError('unexpected_source_bytes')
    if any((PHONE_REPO / name).stat().st_uid != PHONE_UID for name in expected_sources):
        raise RuntimeError('source_owner')
    services = quiet_services(old)
    original = {name: row['new_sha256'] for name, row in record['sources'].items()}
    snapshot = {'protected': protected, 'env_sha256': sha(env), 'sources': original,
                'services': services, 'helper_sha256': sha(HELPER)}
    if hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest() != PRESERVED_SHA:
        raise RuntimeError('frozen_preservation_changed')
    owner = retained_owner(browser)
    return {'preserved_sha256': PRESERVED_SHA, 'git_metadata_sha256': git_metadata_digest(), **owner}


def native_main() -> dict:
    global stage
    if os.name != 'posix' or os.getuid() != PHONE_UID:
        raise RuntimeError('phone_uid')
    request = json.loads(sys.stdin.buffer.read(2 * 1024 * 1024 + 1))
    if not isinstance(request, dict) or set(request) != {'action', 'archive', 'old_hashes'} or request['action'] not in {'inspect', 'update'}:
        raise RuntimeError('request_shape')
    files = load_bundle(base64.b64decode(request['archive'], validate=True), NEW_ARCHIVE_SHA)
    old_hashes = request['old_hashes']
    if (not isinstance(old_hashes, dict) or set(old_hashes) != set(files)
            or any(not isinstance(value, str) or len(value) != 64 or set(value) - set('0123456789abcdef') for value in old_hashes.values())):
        raise RuntimeError('old_source_manifest_shape')
    stage = 'immutable_guard_code'
    plain(HELPER)
    cdp_source = PHONE_REPO / 'app/solvers/cdp.py'
    if sha(HELPER) != HELPER_SHA or sha(cdp_source) != CDP_SHA:
        raise RuntimeError('guard_code_changed')
    old = runpy.run_path(str(HELPER))
    plain(old['BACKUP'] / 'manifest.json')
    record = json.loads((old['BACKUP'] / 'manifest.json').read_text())
    if (record['commit'] != '67f8576' or record['phase'] != 'source_prepared_send0'
            or record['archive_sha256'] != OLD_ARCHIVE_SHA
            or {name: row['new_sha256'] for name, row in record['sources'].items()} != old_hashes):
        raise RuntimeError('original_receipt_changed')
    plain(BACKUP)
    private_directory(BACKUP.parent)
    if BACKUP.exists():
        raise RuntimeError('transaction_already_exists')
    stage = 'existing_cdp_connect'
    cdp = runpy.run_path(str(cdp_source))
    browser = cdp['connect_over_cdp']('http://127.0.0.1:9222', timeout_s=8)
    try:
        def guard(expected):
            return native_guard(old, record, browser, expected)

        guard(old_hashes)
        if request['action'] == 'update':
            receipt = update_sources(PHONE_REPO, BACKUP, files, old_hashes, guard)
            receipt_sha = sha(BACKUP / 'manifest.json')
            writes = receipt['source_writes']
            phase = 'source_prepared_send0'
        else:
            receipt_sha, writes, phase = None, 0, 'source_update_readonly_preflight'
        stage = 'complete'
        return {'phase': phase, 'stage': stage, 'source_files': 79, 'source_writes': writes,
                'source_bundle_commit': SOURCE_COMMIT, 'archive_sha256': NEW_ARCHIVE_SHA,
                'receipt_sha256': receipt_sha, 'protected_bytes_unchanged': True,
                'browser_x11_retained': True, 'phone_git_metadata_updated': False,
                'SEND_enabled': False, 'solver_verified': False,
                'browser_launch_attempts': 0, 'browser_close_attempts': 0,
                'services_changed': 0, 'APK_installs': 0, 'Input_calls': 0, 'GPT_submissions': 0}
    finally:
        browser._connection.close()  # CDP client socket only; not Browser.close protocol


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


def configure(manifest: Path, manifest_sha: str) -> dict:
    """Binding/private hashes stay in an ignored, explicitly SHA-pinned manifest."""
    global TARGET, SERIAL, MODEL, PHONE_UID, BROWSER_BINDING, X11_BINDING, BOOT_SHA
    global OLD_ARCHIVE_SHA, HELPER_SHA, CDP_SHA, LOGGER_SHA, PRESERVED_SHA
    plain(manifest)
    if (not is_sha(manifest_sha) or not manifest.resolve().is_relative_to(REPORTS.resolve())
            or manifest.stat().st_size > 32768 or sha(manifest) != manifest_sha):
        raise RuntimeError('untrusted_local_manifest')
    value = json.loads(manifest.read_bytes())
    if (not isinstance(value, dict) or set(value) != {'schema', 'device', 'browser', 'x11', 'pins', 'auth_report'}
            or type(value['schema']) is not int or value['schema'] != 1):
        raise RuntimeError('manifest_schema')
    device, pins = value['device'], value['pins']
    pin_keys = {'boot', 'helper', 'cdp', 'logger', 'preserved', 'old_archive', 'new_archive', 'auth_report'}
    if (not isinstance(device, dict) or set(device) != {'target', 'serial', 'model', 'uid'}
            or not isinstance(pins, dict) or set(pins) != pin_keys or not all(is_sha(pins[k]) for k in pins)
            or pins['new_archive'] != NEW_ARCHIVE_SHA or type(device['uid']) is not int or device['uid'] <= 0
            or not all(isinstance(device[k], str) and device[k].isascii() and 0 < len(device[k]) <= 256
                       and not any(c.isspace() for c in device[k]) for k in ('target', 'serial', 'model'))
            or not device['serial'].isalnum()
            or not device['target'].startswith('adb-' + device['serial'] + '-')
            or not device['target'].endswith('._adb-tls-connect._tcp')):
        raise RuntimeError('manifest_device_or_pins')
    for binding in (value['browser'], value['x11']):
        if (not isinstance(binding, dict) or set(binding) != {'pid', 'uid', 'starttime', 'boot_id_sha256'}
                or any(type(binding[k]) is not int or binding[k] <= 0 for k in ('pid', 'uid', 'starttime'))
                or binding['uid'] != device['uid'] or binding['boot_id_sha256'] != pins['boot']):
            raise RuntimeError('manifest_owner_binding')
    if value['browser']['pid'] == value['x11']['pid']:
        raise RuntimeError('manifest_distinct_owners')
    name = value['auth_report']
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
        raise RuntimeError('auth_report_path')
    proof = REPORTS / name
    plain(proof)
    if sha(proof) != pins['auth_report']:
        raise RuntimeError('auth_report_pin')
    rows = json.loads(proof.read_bytes())['results']
    result = json.loads(rows[-1]['stdout'])
    if (len(rows) != 4 or any(type(row['exit_code']) is not int or row['exit_code'] != 0 for row in rows)
            or result['authentication_verified'] is not True or result['model_and_effort_verified'] is not True
            or result['browser_binding'] != value['browser'] or result['x11_binding'] != value['x11']
            or rows[1]['stdout'].strip() != device['serial'] or rows[2]['stdout'].strip() != device['model']
            or rows[1]['command'][2] != device['target']):
        raise RuntimeError('auth_report_binding')
    TARGET, SERIAL, MODEL, PHONE_UID = (device[k] for k in ('target', 'serial', 'model', 'uid'))
    BROWSER_BINDING, X11_BINDING, BOOT_SHA = value['browser'], value['x11'], pins['boot']
    OLD_ARCHIVE_SHA, HELPER_SHA, CDP_SHA = (pins[k] for k in ('old_archive', 'helper', 'cdp'))
    LOGGER_SHA, PRESERVED_SHA = pins['logger'], pins['preserved']
    return {'manifest_sha256': manifest_sha, 'auth_report_sha256': pins['auth_report']}


def prepare(provenance: dict, action: str = 'update') -> tuple[bytes, list[list[str]], dict]:
    """PC-only: validate two fixed bundles and compile, without executing, native code."""
    if not TARGET or action not in {'inspect', 'update'}:
        raise RuntimeError('unconfigured_prepare')
    content = (REPORTS / NEW_ARCHIVE).read_bytes()
    files = load_bundle(content, NEW_ARCHIVE_SHA)
    original = load_bundle((REPORTS / OLD_ARCHIVE).read_bytes(), OLD_ARCHIVE_SHA)
    if set(files) != set(original):
        raise RuntimeError('old_new_path_set')
    old_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
    functions = {'sha', 'source_path', 'load_bundle', 'plain', 'sync_directories', 'atomic_bytes',
                 'source_hashes', 'update_sources', 'process_binding', 'snapshot_logger',
                 'private_directory', 'retained_owner', 'quiet_services', 'git_metadata_digest',
                 'native_guard', 'native_main', 'public_failure'}
    constants = ('PHONE_HOME', 'PHONE_PREFIX', 'PHONE_REPO', 'PROFILE', 'HELPER', 'HELPER_SHA', 'CDP_SHA',
                 'BOOT_SHA', 'BROWSER_BINDING', 'X11_BINDING', 'PHONE_UID', 'BACKUP', 'LOGGER_TARGET',
                 'LOGGER_LEAVES', 'LOGGER_SHA', 'PRESERVED_SHA', 'ROOT_FILES', 'OLD_ARCHIVE_SHA',
                 'NEW_ARCHIVE_SHA', 'SOURCE_COMMIT', 'SOURCE_HEAD')
    tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    body = '\n'.join(ast.unparse(n) for n in imports)
    for name in constants:
        item = globals()[name]
        if isinstance(item, Path):
            literal = 'Path(' + repr(item.as_posix()) + ')'
        elif name == 'LOGGER_LEAVES':
            literal = '{' + ','.join('Path(' + repr(p.as_posix()) + ')' for p in sorted(item)) + '}'
        elif name == 'ROOT_FILES':
            literal = '{' + ','.join(repr(value) for value in sorted(item)) + '}'
        else:
            literal = repr(item)
        body += '\n' + name + ' = ' + literal
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
    request = json.dumps({'action': action, 'archive': base64.b64encode(content).decode(),
                          'old_hashes': old_hashes}, sort_keys=True).encode()
    metadata = {'phase': 'pc_source_update_prepared', 'approval_received': False, 'actual_runtime_executions': 0,
                'action': action, 'source_files': 79, 'archive_sha256': NEW_ARCHIVE_SHA,
                'source_bundle_commit': SOURCE_COMMIT, 'reference_runtime_commit': SOURCE_HEAD,
                'git_blob_comparison_performed': False,
                'native_sha256': hashlib.sha256(body.encode()).hexdigest(), 'native_bytes': len(body.encode()),
                'bootstrap_sha256': hashlib.sha256(bootstrap.encode()).hexdigest(), 'bootstrap_bytes': len(bootstrap.encode()),
                'wire_characters': wire, 'request_sha256': hashlib.sha256(request).hexdigest(),
                'request_bytes': len(request), 'host_rows': 4, 'phone_git_metadata_updated': False,
                'planned_services_changes': 0, 'planned_APK_installs': 0, 'planned_Input_calls': 0,
                'planned_GPT_submissions': 0, 'planned_browser_starts_or_closes': 0,
                'profile_normal_browser_writes_allowed': True, 'unknown_partial_update_auto_resume': False, **provenance}
    return request, commands, metadata


def validate_public(result: dict, action: str) -> None:
    if not isinstance(result, dict):
        raise RuntimeError('native_public_shape')
    failure_keys = {'phase', 'stage', 'error_type', 'transaction_phase', 'source_writes', 'restored'}
    if result.get('phase') == 'source_update_stopped':
        if (set(result) != failure_keys or result['transaction_phase'] not in
                {'not_started', 'applying', 'rolled_back', 'rollback_blocked', 'source_prepared_send0'}
                or type(result['source_writes']) is not int or not 0 <= result['source_writes'] <= 79
                or type(result['restored']) is not bool):
            raise RuntimeError('native_failure_shape')
        labels = {'native_input', 'immutable_guard_code', 'existing_cdp_connect', 'protected_source_env',
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
            or type(result['source_files']) is not int or result['source_files'] != 79
            or type(result['source_writes']) is not int or result['source_writes'] != (79 if action == 'update' else 0)
            or result['source_bundle_commit'] != SOURCE_COMMIT or result['archive_sha256'] != NEW_ARCHIVE_SHA
            or result['protected_bytes_unchanged'] is not True or result['browser_x11_retained'] is not True
            or any(result[k] is not False for k in ('phone_git_metadata_updated', 'SEND_enabled', 'solver_verified'))
            or any(type(result[k]) is not int or result[k] != 0 for k in counters)
            or (not is_sha(result['receipt_sha256']) if action == 'update' else result['receipt_sha256'] is not None)):
        raise RuntimeError('native_completion_contract')


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
            output = subprocess.run(command, input=request if index == 3 else None,
                                    capture_output=True, timeout=180 if index == 3 else 15, check=False)
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
