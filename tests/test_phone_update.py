"""One local replay; no phone, browser, CDP or real subprocess connections."""
import ast
import base64
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import tarfile
from types import SimpleNamespace
import zlib

import pytest

from scripts import phone_update as update

FIXTURE_TARGET = 'adb-FIXTURE001-example._adb-tls-connect._tcp'


def bionic_publisher(monkeypatch, *, failure=None):
    """Exercise the documented C ABI; emulate its filesystem result locally."""
    link = os.link
    calls = []
    class RenameAt2:
        def __call__(self, old_fd, old, new_fd, new, flags):
            assert (old_fd, new_fd, flags) == (-100, -100, 1)
            assert self.argtypes == [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            assert self.restype is ctypes.c_int
            calls.append((old, new))
            if failure is not None:
                ctypes.set_errno(failure)
                return -1
            try:
                source, target = Path(os.fsdecode(old)), Path(os.fsdecode(new))
                link(source, target)
                source.unlink()
            except OSError as error:
                ctypes.set_errno(error.errno)
                return -1
            return 0
    function = RenameAt2()
    def library(name, *, use_errno):
        assert name is None and use_errno is True
        return SimpleNamespace(renameat2=function)
    monkeypatch.setattr(ctypes, 'CDLL', library)
    monkeypatch.delattr(os, 'link')
    return calls


@pytest.fixture
def private_filesystem(tmp_path, monkeypatch):
    """Replay POSIX private modes/uid on the Windows development filesystem."""
    actual_stat, actual_lstat = Path.stat, Path.lstat
    actual_chmod, actual_replace, actual_link = os.chmod, os.replace, os.link
    modes = {}
    def key(path):
        return Path(path).as_posix()
    def metadata(path, original, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path.is_relative_to(tmp_path):
            fields = list(info)
            fields[0] = (info.st_mode & ~0o7777) | modes.get(key(path), 0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
            fields[4] = 123
            return os.stat_result(fields)
        return info
    def chmod(path, mode, *args, **kwargs):
        actual_chmod(path, mode, *args, **kwargs)
        modes[key(path)] = mode
    def replace(source, target, *args, **kwargs):
        actual_replace(source, target, *args, **kwargs)
        modes[key(target)] = modes.pop(key(source), 0o600)
    def link(source, target, *args, **kwargs):
        actual_link(source, target, *args, **kwargs)
        modes[key(target)] = modes.get(key(source), 0o600)
    monkeypatch.setattr(Path, 'stat', lambda path, *a, **k: metadata(path, actual_stat, *a, **k))
    monkeypatch.setattr(Path, 'lstat', lambda path, *a, **k: metadata(path, actual_lstat, *a, **k))
    monkeypatch.setattr(os, 'chmod', chmod)
    monkeypatch.setattr(os, 'replace', replace)
    monkeypatch.setattr(os, 'link', link)
    monkeypatch.setattr(update, 'PHONE_UID', 123)
    monkeypatch.setattr(update, 'NEW_FILE_PUBLISHER', None)
    monkeypatch.setattr(update, 'transaction_state', {'phase': 'not_started', 'source_writes': 0, 'restored': False})
    return modes


def test_source_transaction_accepts_new_files_and_preserves_private_modes(tmp_path, private_filesystem):
    repo = tmp_path / 'repo'
    (repo / 'app').mkdir(parents=True)
    (repo / 'scripts').mkdir()
    (repo / 'app/main.py').write_bytes(b'OLD = 1\n')
    old = update.path_metadata(repo / 'app/main.py')
    files = {'app/main.py': b'NEW = 2\n', 'app/work_bridge.py': b'VALUE = 3\n',
             'scripts/new_run.sh': b'#!/bin/sh\n:\n'}
    snapshot = {'app/main.py': old, 'app/work_bridge.py': {'exists': False},
                'scripts/new_run.sh': {'exists': False}}
    protected = repo / 'multimodal.env'
    protected.write_bytes(b'PRIVATE-FIXTURE\n')
    def guard(expected):
        return {'protected': hashlib.sha256(protected.read_bytes()).hexdigest()}
    receipt = update.update_sources(repo, tmp_path / 'backup', files, snapshot, guard,
                                    new_modes={'app/main.py': 0o600, 'app/work_bridge.py': 0o600,
                                               'scripts/new_run.sh': 0o700})
    assert receipt['source_writes'] == 3
    assert receipt['phase'] == 'source_prepared_send0'
    assert (repo / 'app/main.py').read_bytes() == b'NEW = 2\n'
    assert (repo / 'app/work_bridge.py').read_bytes() == b'VALUE = 3\n'
    assert (repo / 'scripts/new_run.sh').read_bytes() == b'#!/bin/sh\n:\n'
    assert update.path_metadata(repo / 'app/main.py')['mode'] == old['mode']
    assert update.path_metadata(repo / 'app/work_bridge.py')['mode'] == 0o600
    assert update.path_metadata(repo / 'scripts/new_run.sh')['mode'] == 0o700
    assert protected.read_bytes() == b'PRIVATE-FIXTURE\n'
    assert not (tmp_path / 'backup/source/app/work_bridge.py').exists()


@pytest.mark.parametrize('mode', [0o600, 0o700])
def test_exclusive_publication_uses_bionic_when_python_has_no_link_and_never_clobbers(tmp_path, private_filesystem, monkeypatch, mode):
    calls = bionic_publisher(monkeypatch)
    target = tmp_path / 'new.py'
    update.atomic_bytes(target, b'COMPLETE = 1\n', mode, exclusive=True)
    identity = update.file_identity(target)
    assert target.read_bytes() == b'COMPLETE = 1\n' and update.path_metadata(target)['mode'] == mode
    with pytest.raises(FileExistsError):
        update.atomic_bytes(target, b'FOREIGN = 2\n', 0o600, exclusive=True)
    assert target.read_bytes() == b'COMPLETE = 1\n' and update.file_identity(target) == identity
    assert len(calls) == 2 and {path.name for path in tmp_path.iterdir()} == {'new.py'}


@pytest.mark.parametrize('fault', [None, 'missing_symbol', 'filesystem_unsupported', 'python_not_implemented'])
def test_native_publication_probe_precedes_source_writes_and_restores_its_inventory(deployment, monkeypatch, fault):
    if fault == 'python_not_implemented':
        def unsupported(*args, **kwargs):
            raise NotImplementedError('PRIVATE-UNSUPPORTED')
        monkeypatch.setattr(os, 'link', unsupported)
    else:
        bionic_publisher(monkeypatch, failure=errno.ENOSYS if fault == 'filesystem_unsupported' else None)
        if fault == 'missing_symbol':
            monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: SimpleNamespace())
    wire, _, _, namespace = generated(deployment)
    replay_runtime(namespace, deployment, monkeypatch)
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    if fault:
        with pytest.raises((RuntimeError, OSError, NotImplementedError)) as failure:
            namespace['native_main']()
        public = namespace['public_failure'](failure.value)
        update.validate_public(public, 'update')
        assert public['source_writes'] == 0 and public['transaction_phase'] == 'not_started'
        assert not (deployment.home / 'rokid-backups/pre-source-fixture').exists()
        assert (deployment.repo / 'app/main.py').read_bytes() == b'OLD = 1\n'
        assert not (deployment.repo / 'app/work_bridge.py').exists()
        assert public['publication_probe']['complete'] is False
        assert public['original_failure']['stage'] == 'exclusive_publication_preflight'
        if fault == 'filesystem_unsupported':
            assert public['original_failure']['errno'] == errno.ENOSYS
    else:
        public = namespace['native_main']()
        update.validate_public(public, 'update')
        assert public['publication_probe'] == {'method': 'bionic_renameat2', 'parents_probed': 1, 'complete': True}
        assert public['source_writes'] == 7 and (deployment.repo / 'app/work_bridge.py').read_bytes() == b'VALUE = 3\n'
    assert not list(deployment.repo.rglob('.rokid-publish-probe-*'))


def test_publication_probe_rechecks_the_original_inventory_after_each_parent(tmp_path, private_filesystem, monkeypatch):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    (repo / 'scripts').mkdir()
    retained = repo / 'app/retained.py'
    retained.write_bytes(b'UNRELATED = 1\n')
    files = {'app/new.py': b'NEW = 2\n', 'scripts/new.sh': b'#!/bin/sh\n:\n'}
    original = update.inventory(repo)
    publisher, parents = os.link, []
    def publish(source, target):
        parent = Path(target).parent.parent
        if parent not in parents:
            parents.append(parent)
        publisher(source, target)
        retained.write_bytes(b'UNRELATED = 3\n')
    monkeypatch.setattr(os, 'link', publish)
    def guard(expected):
        return update.check_inventory(update.inventory(repo), original)
    with pytest.raises(RuntimeError, match='inventory_metadata_changed'):
        update.update_sources(repo, backup, files, {name: {'exists': False} for name in files}, guard,
                              new_modes={name: 0o600 for name in files})
    assert parents == [repo / 'app']
    assert update.transaction_state['source_writes'] == 0 and not backup.exists()
    assert not any((repo / name).exists() for name in files)
    assert retained.read_bytes() == b'UNRELATED = 3\n'
    assert not list(repo.rglob('.rokid-publish-probe-*'))


def test_later_parent_publication_failure_retains_its_stage_after_guard_changes_it(tmp_path, private_filesystem, monkeypatch):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    (repo / 'scripts').mkdir()
    files = {'app/new.py': b'NEW = 2\n', 'scripts/new.sh': b'#!/bin/sh\n:\n'}
    publisher, parents = os.link, []
    def publish(source, target):
        parent = Path(target).parent.parent
        if parent not in parents:
            parents.append(parent)
        if parent == repo / 'scripts':
            raise OSError(errno.ENOSYS, 'PRIVATE-LATER-PARENT-FAILURE')
        publisher(source, target)
    monkeypatch.setattr(os, 'link', publish)
    def guard(expected):
        update.stage = 'retained_browser_x11'
        return {'protected': 'stable'}
    with pytest.raises(OSError) as failure:
        update.update_sources(repo, backup, files, {name: {'exists': False} for name in files}, guard,
                              new_modes={'app/new.py': 0o600, 'scripts/new.sh': 0o700})
    assert parents == [repo / 'app', repo / 'scripts']
    public = update.public_failure(failure.value)
    assert public['original_failure'] == {'stage': 'exclusive_publication_preflight',
                                           'error_type': 'OSError', 'errno': errno.ENOSYS}
    assert public['publication_probe'] == {'method': 'os_link', 'parents_probed': 2, 'complete': False}
    assert public['source_writes'] == 0 and not backup.exists()
    assert not any((repo / name).exists() for name in files)
    assert not list(repo.rglob('.rokid-publish-probe-*'))
    assert 'PRIVATE' not in json.dumps(public)


@pytest.mark.parametrize('foreign', ['extra_name', 'same_name_foreign_inode'])
def test_publication_probe_never_cleans_up_unknown_entries(tmp_path, private_filesystem, monkeypatch, foreign):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    unknown = []
    def publish(source, target):
        path = Path(target).parent / ('foreign' if foreign == 'extra_name' else 'target')
        path.write_bytes(b'UNRELATED = 1\n')
        unknown.append((path, update.file_identity(path)))
        raise OSError(errno.ENOSYS, 'PRIVATE-PUBLISH-FAILURE')
    monkeypatch.setattr(os, 'link', publish)
    with pytest.raises(RuntimeError, match='publication_probe_cleanup_blocked') as failure:
        update.update_sources(repo, backup, {'app/new.py': b'NEW = 2\n'}, {'app/new.py': {'exists': False}},
                              lambda expected: {'protected': 'stable'}, new_modes={'app/new.py': 0o600})
    assert update.transaction_state['source_writes'] == 0 and not backup.exists()
    assert not (repo / 'app/new.py').exists()
    assert len(unknown) == 1
    path, identity = unknown[0]
    assert path.read_bytes() == b'UNRELATED = 1\n' and update.file_identity(path) == identity
    public = update.public_failure(failure.value)
    assert public['original_failure'] == {'stage': 'exclusive_publication_preflight',
                                           'error_type': 'OSError', 'errno': errno.ENOSYS}
    assert 'PRIVATE' not in json.dumps(public)


def test_publication_probe_removes_its_known_empty_directory_when_mode_setup_fails(tmp_path, private_filesystem, monkeypatch):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    chmod = os.chmod
    def fail_mode(path, mode, *args, **kwargs):
        if Path(path).name.startswith('.rokid-publish-probe-'):
            raise PermissionError(errno.EPERM, 'PRIVATE-MODE-FAILURE')
        return chmod(path, mode, *args, **kwargs)
    monkeypatch.setattr(os, 'chmod', fail_mode)
    with pytest.raises(PermissionError):
        update.update_sources(repo, backup, {'app/new.py': b'NEW = 2\n'}, {'app/new.py': {'exists': False}},
                              lambda expected: {'protected': 'stable'}, new_modes={'app/new.py': 0o600})
    assert update.transaction_state['source_writes'] == 0 and not backup.exists()
    assert not list(repo.rglob('.rokid-publish-probe-*'))


@pytest.mark.parametrize('foreign', [None, 'bytes', 'identity'])
def test_rollback_removes_only_this_transactions_unchanged_new_files(tmp_path, private_filesystem, foreign):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    (repo / 'scripts').mkdir()
    (repo / 'app/main.py').write_bytes(b'OLD = 1\n')
    (repo / 'app/last.py').write_bytes(b'OLD = 2\n')
    files = {'app/main.py': b'NEW = 3\n', 'app/new.py': b'NEW = 4\n',
             'scripts/new_run.sh': b'#!/bin/sh\n:\n', 'app/last.py': b'NEW = 5\n'}
    snapshot = {name: update.path_metadata(repo / name) for name in files}
    def fail_last(path, content, mode, **kwargs):
        if path == repo / 'app/last.py' and content == b'NEW = 5\n':
            if foreign == 'bytes':
                (repo / 'app/new.py').write_bytes(b'UNRELATED = 6\n')
            elif foreign == 'identity':
                other = repo / 'app/foreign.tmp'
                other.write_bytes(b'NEW = 4\n')
                os.replace(other, repo / 'app/new.py')
            raise OSError(errno.ENOSPC, 'PRIVATE-WRITE-FAILURE')
        update.atomic_bytes(path, content, mode, **kwargs)
    def guard(expected):
        update.stage = 'retained_browser_x11'
        return {'protected': 'stable'}
    with pytest.raises((RuntimeError, OSError)) as failure:
        update.update_sources(repo, backup, files, snapshot, guard,
                              new_modes={name: 0o600 for name in files}, write=fail_last)
    receipt = json.loads((backup / 'manifest.json').read_bytes())
    expected_failure = {'stage': 'atomic_source_update', 'error_type': 'OSError', 'errno': errno.ENOSPC}
    public = update.public_failure(failure.value)
    assert receipt['original_failure'] == public['original_failure'] == expected_failure
    assert public['stage'] != expected_failure['stage']
    assert 'PRIVATE' not in json.dumps(public) + json.dumps(receipt)
    if foreign is None:
        assert receipt['phase'] == 'rolled_back'
        assert (repo / 'app/main.py').read_bytes() == b'OLD = 1\n'
        assert (repo / 'app/last.py').read_bytes() == b'OLD = 2\n'
        assert not (repo / 'app/new.py').exists() and not (repo / 'scripts/new_run.sh').exists()
    else:
        assert receipt['phase'] == 'rollback_blocked'
        assert (repo / 'app/new.py').read_bytes() == (b'UNRELATED = 6\n' if foreign == 'bytes' else b'NEW = 4\n')
        assert (repo / 'scripts/new_run.sh').read_bytes() == b'#!/bin/sh\n:\n'


@pytest.fixture
def deployment(tmp_path, monkeypatch, private_filesystem):
    home, prefix, source, reports = (tmp_path / name for name in ('home', 'prefix', 'source', 'reports'))
    repo = home / 'rokid-server'
    repo.mkdir(parents=True)
    (home / 'rokid-backups').mkdir()
    source.mkdir()
    reports.mkdir()
    files = {'requirements-phone.txt': b'# same dependencies\n', 'constraints-phone.txt': b'# same pins\n',
             'app/main.py': b'NEW = 2\n', 'app/solvers/cdp.py': b'VALUE = 1\n',
             'app/work_bridge.py': b'VALUE = 3\n', 'app/binary.bin': b'\x00\x1a\r\n\xff',
             'scripts/runner.sh': b'#!/bin/sh\n:\n'}
    for name, data in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if name not in {'app/work_bridge.py', 'app/binary.bin'}:
            destination = repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'OLD = 1\n' if name == 'app/main.py' else data)
    (repo / 'app/retained.py').write_bytes(b'OLD_ONLY = 1\n')
    for path in ('multimodal.env', 'send0.env', 'requirements.txt', 'data/docscan.db', 'data/browser-state/submission.json',
                 'data/browser-state/chats.json'):
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b'PRIVATE-FIXTURE\n')
    service = prefix / 'var/service/sshd'
    (service / 'log/supervise').mkdir(parents=True)
    for name in ('down', 'run', 'log/run', 'log/supervise/pid', 'log/supervise/status'):
        (service / name).write_bytes(b'fixture\n')
    logger = prefix / 'share/termux-services/svlogger'
    logger.parent.mkdir(parents=True)
    logger.write_bytes(b'#!/bin/sh\n:\n')
    os.chmod(logger, 0o700)
    def tree(root):
        if not root.exists():
            return {'.': {'exists': False}}
        return {'.': update.path_metadata(root), **{path.relative_to(root).as_posix(): update.path_metadata(path)
                                                    for path in root.rglob('*')}}
    device = {'target': FIXTURE_TARGET, 'serial': 'FIXTURE001', 'model': 'F-51F', 'uid': 123}
    runtime = {'browser': {'pid': 12, 'starttime': 456, 'boot': '0' * 64},
               'x11': {'pid': 13, 'starttime': 457, 'boot': '0' * 64}, 'CDP_product': 'Chrome/999.1.2.3',
               'profile_directory': {'exists': True, 'type': 'directory', 'uid': 123, 'mode': 0o700, 'size': 1},
               'profile_lock': {'exists': True, 'type': 'symlink', 'uid': 123, 'mode': 0o777,
                                'size': 12, 'link_text': 'localhost-12'},
               'X11_socket_metadata': {}, 'ports': {'8000_open': False, '9222_open': True}}
    snapshot = {'read_only': True, 'UI_input_calls': 0, 'device': device,
                'source_paths': {name: update.path_metadata(repo / name) for name in files},
                'source_inventory': {name: tree(repo / name) for name in ('app', 'scripts')},
                'protected_paths': {(repo / name).as_posix(): update.path_metadata(repo / name) for name in
                    ('multimodal.env', 'send0.env', 'requirements.txt', *update.ROOT_FILES,
                     'data/docscan.db', 'data/docscan.db-wal', 'data/docscan.db-shm', 'data/docscan.db-journal',
                     'data/work-jobs.db', 'data/work-jobs.db-wal', 'data/work-jobs.db-shm', 'data/work-jobs.db-journal',
                     'data/browser-state/submission.json', 'data/browser-state/chats.json')},
                'service_inventory': tree(prefix / 'var/service'), 'boot_inventory': tree(home / '.termux/boot'),
                'git_inventory': tree(repo / '.git'), 'logger_target': {'path': logger.as_posix(), **update.path_metadata(logger)},
                'env_flags': {'send0.env': {'ROKID_CHATGPT_SEND_ENABLED': '0', 'ROKID_REAL_MODE': '1',
                                           'API_key_present': True}}, 'runtime': runtime,
                'parent_directories': {path.as_posix(): update.path_metadata(path) for path in (home, repo, home / 'rokid-backups')},
                'owned_process_inventory': {'exit_code': 0, 'producer_matches': []},
                'logger_package_owner': {'exit_code': 0, 'package': 'termux-services', 'path': logger.as_posix()}}
    snapshot_file = reports / 'snapshot.json'
    snapshot_file.write_text(json.dumps({'exit_code': 0, 'result': {'ok': True, 'public': snapshot}}), encoding='utf-8')
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], capture_output=True, check=True).stdout
    git('init', '-q')
    (source / '.gitattributes').write_bytes(b'* -text\n')
    git('add', '.')
    git('update-index', '--chmod=+x', 'scripts/runner.sh')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    commit = git('rev-parse', 'HEAD').decode().strip()
    archive = reports / 'source.tar'
    archive.write_bytes(git('archive', '--format=tar', commit, 'app', 'scripts', *sorted(update.ROOT_FILES)))
    manifest = {'schema': 2, 'device': device, 'source_commit': commit,
                'archive': {'file': archive.name, 'sha256': update.sha(archive), 'size': archive.stat().st_size,
                    'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                                      'mode': 0o755 if name.endswith('.sh') else 0o644} for name, data in files.items()}},
                'snapshot': {'file': snapshot_file.name, 'sha256': update.sha(snapshot_file)},
                'guard_env': 'send0.env', 'backup': 'pre-source-fixture'}
    manifest_file = reports / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    for name, value in {'ROOT': source, 'REPORTS': reports, 'PHONE_HOME': home, 'PHONE_PREFIX': prefix,
                        'PHONE_REPO': repo, 'PROFILE': repo / 'data/chromium-profile', 'LOGGER_TARGET': logger}.items():
        monkeypatch.setattr(update, name, value)
    return SimpleNamespace(repo=repo, home=home, prefix=prefix, source=source, reports=reports, files=files,
                           manifest=manifest, path=manifest_file, snapshot=snapshot, snapshot_path=snapshot_file, git=git)


def generated(deployment, action='update'):
    provenance = update.configure(deployment.path, update.sha(deployment.path))
    wire, commands, metadata = update.prepare(provenance, action)
    bootstrap = shlex.split(commands[-1][-1])[-1]
    encoded = next(n.value for n in ast.walk(ast.parse(bootstrap)) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str) and len(n.value) > 500)
    native = zlib.decompress(base64.b64decode(encoded)).decode()
    assert hashlib.sha256(native.encode()).hexdigest() == metadata['native_sha256']
    tree = ast.parse(native)
    tree.body.pop()
    namespace = {}
    exec(compile(tree, '<generated-update-definitions>', 'exec'), namespace)
    # This replay already emulates POSIX uid/mode. Render its local Windows
    # paths as the native POSIX code does, without relaxing production inputs.
    class NativePath(type(Path())):
        def __str__(self):
            return super().__str__().replace('\\', '/')
    namespace['Path'] = NativePath
    for name in ('PHONE_HOME', 'PHONE_PREFIX', 'PHONE_REPO', 'PROFILE', 'LOGGER_TARGET'):
        namespace[name] = NativePath(namespace[name])
    return wire, commands, metadata, namespace


def test_prepare_verifies_the_fixed_git_blobs_and_frames_ascii_without_an_eof_read(deployment):
    wire, commands, metadata, namespace = generated(deployment)
    assert wire.isascii() and not set(wire) - set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
    request = json.loads(base64.b64decode(wire, validate=True))
    assert base64.b64decode(request['archive'], validate=True) == (deployment.reports / 'source.tar').read_bytes()
    assert metadata['source_files'] == 7 and metadata['git_blob_comparison_performed'] is True
    assert metadata['approval_received'] is False and metadata['actual_runtime_executions'] == 0
    class NoEofStream:
        def __init__(self):
            self.position = 0
        def read(self, count):
            assert 0 < count <= len(wire) - self.position
            result = wire[self.position:self.position + min(count, 7)]
            self.position += len(result)
            return result
    assert namespace['read_request'](NoEofStream(), len(wire)) == request
    assert namespace['load_bundle'](base64.b64decode(request['archive']),
                                   deployment.manifest['archive']['sha256'],
                                   deployment.manifest['archive']['files']) == deployment.files


@pytest.mark.parametrize('fault', [None, 'backslash', 'other_root', 'traversal', 'logger_target', 'logger_owner'])
def test_host_prepares_a_native_posix_snapshot_without_rewriting_its_paths(deployment, monkeypatch, fault):
    """The phone reports POSIX absolute keys even when the preparer is Windows."""
    native_home = PurePosixPath('/data/data/com.termux/files/home')
    native_prefix = PurePosixPath('/data/data/com.termux/files/usr')
    native_repo = native_home / 'rokid-server'
    logger = native_prefix / 'share/termux-services/svlogger'
    original_repo = deployment.repo
    deployment.snapshot['protected_paths'] = {
        str(native_repo / Path(name).relative_to(original_repo).as_posix()): row
        for name, row in deployment.snapshot['protected_paths'].items()}
    deployment.snapshot['logger_target']['path'] = str(logger)
    deployment.snapshot['logger_package_owner']['path'] = str(logger)
    deployment.snapshot['parent_directories'] = {
        str(native_home / Path(name).relative_to(deployment.home).as_posix()): row
        for name, row in deployment.snapshot['parent_directories'].items()}
    for name, value in {'PHONE_HOME': native_home, 'PHONE_PREFIX': native_prefix,
                        'PHONE_REPO': native_repo, 'PROFILE': native_repo / 'data/chromium-profile',
                        'LOGGER_TARGET': logger}.items():
        monkeypatch.setattr(update, name, Path(value))
    if fault in {'backslash', 'other_root', 'traversal'}:
        name = next(iter(deployment.snapshot['protected_paths']))
        changed = (name.replace('/', '\\') if fault == 'backslash' else
                   name.replace('/rokid-server/', '/unrelated/' if fault == 'other_root'
                                else '/rokid-server/../rokid-server/', 1))
        deployment.snapshot['protected_paths'][changed] = deployment.snapshot['protected_paths'].pop(name)
    elif fault in {'logger_target', 'logger_owner'}:
        section = 'logger_target' if fault == 'logger_target' else 'logger_package_owner'
        deployment.snapshot[section]['path'] = str(logger).replace('/', '\\')
    if fault:
        reason = 'snapshot_service_or_inventory_scope' if fault.startswith('logger') else 'snapshot_protected_scope'
        with pytest.raises(RuntimeError, match=reason):
            repin(deployment)
        return
    provenance = repin(deployment)
    wire, commands, metadata = update.prepare(provenance)
    request = json.loads(base64.b64decode(wire, validate=True))
    snapshot = json.loads(base64.b64decode(request['snapshot'], validate=True))['result']['public']
    assert snapshot == deployment.snapshot
    assert all(name.startswith('/data/data/com.termux/files/home/rokid-server/')
               and '\\' not in name for name in snapshot['protected_paths'])
    assert snapshot['logger_target']['path'] == str(logger)
    assert metadata['source_files'] == 7 and metadata['git_blob_comparison_performed'] is True
    assert metadata['actual_runtime_executions'] == 0
    assert 'HOME=/data/data/com.termux/files/home' in commands[-1][-1]
    assert 'PREFIX=/data/data/com.termux/files/usr' in commands[-1][-1]


def replay_runtime(namespace, deployment, monkeypatch):
    """Real source/protected guards; process/CDP edges are local fixtures."""
    actual_getpid = os.getpid
    def run(command, **kwargs):
        if command[0].endswith('dpkg-query'):
            return SimpleNamespace(returncode=0, stdout='termux-services: ' + update.LOGGER_TARGET.as_posix() + '\n', stderr='')
        if command[0] == '/system/bin/ps':
            return SimpleNamespace(returncode=0,
                stdout=f'UID PID ARGS\n123 {actual_getpid()} python\n123 12 chromium\n123 13 x11\n123 99 runsv sshd/log\n'.encode(), stderr=b'')
        assert command[0].endswith('bash') and kwargs['stdout'] == subprocess.DEVNULL
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', run)
    namespace['retained_owner'] = lambda browser: {name: deployment.snapshot['runtime'][name] for name in ('browser', 'x11')}
    namespace['sync_directories'] = lambda directory: None  # Directory fsync needs the Android/POSIX filesystem.
    namespace['os'] = SimpleNamespace(**{**vars(os), 'name': 'posix', 'getuid': lambda: 123})
    calls = []
    browser = SimpleNamespace(_connection=SimpleNamespace(close=lambda: calls.append('client_disconnect')))
    def connect(url, *, timeout_s):
        calls.append((url, timeout_s))
        return browser
    namespace['runpy'] = SimpleNamespace(run_path=lambda path: {'connect_over_cdp': connect})
    return calls


@pytest.mark.parametrize('action', ['inspect', 'update'])
def test_generated_entry_preserves_source_extras_private_state_and_existing_runtime(deployment, monkeypatch, action):
    wire, commands, metadata, namespace = generated(deployment, action)
    calls = replay_runtime(namespace, deployment, monkeypatch)
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    result = namespace['native_main']()
    update.validate_public(result, action)
    assert result['source_files'] == 7 and result['source_writes'] == (7 if action == 'update' else 0)
    assert calls == [('http://127.0.0.1:9222', 8), 'client_disconnect']
    assert (deployment.repo / 'app/retained.py').read_bytes() == b'OLD_ONLY = 1\n'
    assert all(update.path_metadata(Path(path)) == row for path, row in deployment.snapshot['protected_paths'].items())
    assert not (deployment.repo / '.git').exists() and not (deployment.home / '.termux/boot').exists()
    if action == 'update':
        assert all((deployment.repo / name).read_bytes() == data for name, data in deployment.files.items())
        assert update.path_metadata(deployment.repo / 'app/work_bridge.py')['mode'] == 0o600
    else:
        assert not (deployment.repo / 'app/work_bridge.py').exists()
        assert not (deployment.home / 'rokid-backups/pre-source-fixture').exists()


@pytest.mark.parametrize('changed', ['database', 'ledger', 'old_only', 'service', 'boot', 'git'])
def test_current_protected_or_inventory_changes_stop_before_any_source_write(deployment, monkeypatch, changed):
    wire, commands, metadata, namespace = generated(deployment)
    calls = replay_runtime(namespace, deployment, monkeypatch)
    path = {'database': deployment.repo / 'data/docscan.db',
            'ledger': deployment.repo / 'data/browser-state/chats.json',
            'old_only': deployment.repo / 'app/retained.py',
            'service': deployment.prefix / 'var/service/sshd/run',
            'boot': deployment.home / '.termux/boot/new.sh', 'git': deployment.repo / '.git/HEAD'}[changed]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'UNRELATED-CHANGE\n')
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    with pytest.raises(RuntimeError):
        namespace['native_main']()
    assert not calls and (deployment.repo / 'app/main.py').read_bytes() == b'OLD = 1\n'
    assert not (deployment.repo / 'app/work_bridge.py').exists()
    assert not (deployment.home / 'rokid-backups/pre-source-fixture').exists()


def test_dynamic_logger_status_is_not_a_source_or_service_configuration_change(deployment, monkeypatch):
    wire, commands, metadata, namespace = generated(deployment, 'inspect')
    replay_runtime(namespace, deployment, monkeypatch)
    (deployment.prefix / 'var/service/sshd/log/supervise/status').write_bytes(b'normal-runtime-transition\n')
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    assert namespace['native_main']()['source_writes'] == 0


@pytest.mark.parametrize('expires', [False, True])
def test_native_dispatch_waits_in_bounded_intervals_without_sending_twice(monkeypatch, expires):
    calls = []
    class Process:
        returncode = None
        def communicate(self, input=None, timeout=None):
            calls.append(('communicate', input, timeout))
            if len(calls) == 2:
                raise subprocess.TimeoutExpired('fixture', timeout, output=b'PRIVATE-PARTIAL')
            self.returncode = 0
            return b'PUBLIC', b''
        def poll(self):
            return self.returncode
        def kill(self):
            calls.append(('kill',))
            self.returncode = -9
    process = Process()
    def popen(command, **kwargs):
        calls.append(('spawn', command))
        assert kwargs == {'stdin': subprocess.PIPE, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
        return process
    monkeypatch.setattr(subprocess, 'Popen', popen)
    clock = iter([0, 0, 181 if expires else 5, 5])
    monkeypatch.setattr(update, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    if expires:
        with pytest.raises(subprocess.TimeoutExpired):
            update.dispatch_native(['LOCAL-FIXTURE'], b'ASCII-REQUEST')
        assert ('kill',) in calls
    else:
        result = update.dispatch_native(['LOCAL-FIXTURE'], b'ASCII-REQUEST')
        assert result.stdout == b'PUBLIC'
    assert sum(row[0] == 'spawn' for row in calls) == 1
    assert sum(row[:2] == ('communicate', b'ASCII-REQUEST') for row in calls) == 1
    assert all(row[2] <= 5 for row in calls if row[0] == 'communicate')


def repin(deployment):
    deployment.snapshot_path.write_text(json.dumps({'exit_code': 0, 'result': {'ok': True,
        'public': deployment.snapshot}}), encoding='utf-8')
    deployment.manifest['snapshot']['sha256'] = update.sha(deployment.snapshot_path)
    deployment.path.write_text(json.dumps(deployment.manifest), encoding='utf-8')
    return update.configure(deployment.path, update.sha(deployment.path))


def test_manifest_cannot_omit_an_existing_database_from_preservation(deployment):
    deployment.snapshot['protected_paths'].pop((deployment.repo / 'data/docscan.db').as_posix())
    with pytest.raises(RuntimeError, match='protected_scope'):
        repin(deployment)


def test_consistently_forged_archive_and_manifest_cannot_replace_fixed_commit_blobs(deployment):
    path = deployment.reports / 'source.tar'
    entries = []
    with tarfile.open(path, 'r:') as original:
        for member in original:
            entries.append((member, original.extractfile(member).read() if member.isfile() else None))
    with tarfile.open(path, 'w:') as forged:
        for member, content in entries:
            if member.name == 'app/main.py':
                content = b'FORGED = 9\n'
                member.size = len(content)
                deployment.manifest['archive']['files'][member.name].update(
                    size=len(content), sha256=hashlib.sha256(content).hexdigest())
            forged.addfile(member, io.BytesIO(content) if content is not None else None)
    deployment.manifest['archive'].update(sha256=update.sha(path), size=path.stat().st_size)
    with pytest.raises(RuntimeError, match='archive_git_'):
        update.prepare(repin(deployment))
    assert (deployment.repo / 'app/main.py').read_bytes() == b'OLD = 1\n'


@pytest.mark.parametrize('name, kind', [('../outside', tarfile.REGTYPE), ('app/link', tarfile.SYMTYPE),
                                       ('app/fifo', tarfile.FIFOTYPE), ('app/../outside', tarfile.REGTYPE)])
def test_unsafe_archives_never_extract_or_create_any_member(deployment, name, kind):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:') as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        archive.addfile(member)
    content = output.getvalue()
    with pytest.raises(RuntimeError):
        update.load_bundle(content, hashlib.sha256(content).hexdigest(), deployment.manifest['archive']['files'])
    assert not (deployment.repo / 'app/link').exists() and not (deployment.home / 'outside').exists()


@pytest.mark.parametrize('mode', [0o600, 0o444])
def test_archive_permissions_must_match_git_intent_except_export_group_write(deployment, mode):
    output = io.BytesIO()
    with tarfile.open(deployment.reports / 'source.tar', 'r:') as original:
        with tarfile.open(fileobj=output, mode='w:') as archive:
            for member in original:
                content = original.extractfile(member).read() if member.isfile() else None
                if member.name == 'app/main.py':
                    member.mode = mode
                archive.addfile(member, io.BytesIO(content) if content is not None else None)
    content = output.getvalue()
    with pytest.raises(RuntimeError, match='bundle_manifest_mismatch'):
        update.load_bundle(content, hashlib.sha256(content).hexdigest(), deployment.manifest['archive']['files'])


def test_new_source_publication_never_overwrites_a_racing_foreign_file(tmp_path, private_filesystem):
    repo, backup = tmp_path / 'repo', tmp_path / 'backup'
    (repo / 'app').mkdir(parents=True)
    def race(path, content, mode, **kwargs):
        if path == repo / 'app/new.py':
            path.write_bytes(b'FOREIGN = 1\n')
        update.atomic_bytes(path, content, mode, **kwargs)
    with pytest.raises(RuntimeError):
        update.update_sources(repo, backup, {'app/new.py': b'NEW = 2\n'}, {'app/new.py': {'exists': False}},
            lambda expected: {'stable': True}, new_modes={'app/new.py': 0o600}, write=race)
    assert (repo / 'app/new.py').read_bytes() == b'FOREIGN = 1\n'
    assert json.loads((backup / 'manifest.json').read_bytes())['phase'] == 'rollback_blocked'


@pytest.mark.parametrize('count', [86, 87])
def test_current_source_archive_installs_without_an_old_archive_or_fixed_count(deployment, monkeypatch, count):
    for number in range(count - 7):
        name, data = f'app/extra_{number:03d}.py', f'VALUE = {number}\n'.encode()
        (deployment.source / name).write_bytes(data)
        deployment.files[name] = data
        deployment.snapshot['source_paths'][name] = {'exists': False}
        deployment.manifest['archive']['files'][name] = {'sha256': hashlib.sha256(data).hexdigest(),
                                                        'size': len(data), 'mode': 0o644}
    # Keep the runner's index-only executable bit while staging these new app files.
    deployment.git('-c', 'core.fileMode=true', 'add', 'app')
    deployment.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'more source')
    commit = deployment.git('rev-parse', 'HEAD').decode().strip()
    path = deployment.reports / 'source.tar'
    path.write_bytes(deployment.git('archive', '--format=tar', commit, 'app', 'scripts', *sorted(update.ROOT_FILES)))
    deployment.manifest['source_commit'] = commit
    deployment.manifest['archive'].update(sha256=update.sha(path), size=path.stat().st_size)
    repin(deployment)
    wire, commands, metadata, namespace = generated(deployment)
    replay_runtime(namespace, deployment, monkeypatch)
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    result = namespace['native_main']()
    update.validate_public(result, 'update')
    assert result['source_files'] == result['source_writes'] == count
    assert all((deployment.repo / name).read_bytes() == data for name, data in deployment.files.items())


@pytest.mark.parametrize('change', ['hash', 'mode', 'uid', 'new_exists'])
def test_source_snapshot_difference_stops_before_backup_or_cdp(deployment, monkeypatch, private_filesystem, change):
    wire, commands, metadata, namespace = generated(deployment)
    calls = replay_runtime(namespace, deployment, monkeypatch)
    path = deployment.repo / ('app/work_bridge.py' if change == 'new_exists' else 'app/main.py')
    if change in {'hash', 'new_exists'}:
        path.write_bytes(b'UNRELATED = 9\n')
    elif change == 'mode':
        os.chmod(path, 0o700)
    else:
        real_lstat = Path.lstat
        def foreign_owner(candidate, *args, **kwargs):
            info = real_lstat(candidate, *args, **kwargs)
            if candidate.as_posix() == path.as_posix():
                fields = list(info)
                fields[4] = 124
                return os.stat_result(fields)
            return info
        monkeypatch.setattr(Path, 'lstat', foreign_owner)
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    with pytest.raises(RuntimeError):
        namespace['native_main']()
    assert not calls and not (deployment.home / 'rokid-backups/pre-source-fixture').exists()


@pytest.mark.parametrize('fault', ['producer', 'missing_owner', 'malformed', 'permission'])
def test_dynamic_owned_process_proof_refuses_producers_without_reading_unrelated_proc(deployment, monkeypatch, fault):
    wire, commands, metadata, namespace = generated(deployment, 'inspect')
    calls = replay_runtime(namespace, deployment, monkeypatch)
    ordinary_run = subprocess.run
    def run(command, **kwargs):
        result = ordinary_run(command, **kwargs)
        if command[0] == '/system/bin/ps':
            if fault == 'producer':
                result.stdout += b'123 98 python -m app.work_mcp\n'
            elif fault == 'missing_owner':
                result.stdout = result.stdout.replace(b'123 12 chromium\n', b'')
            elif fault == 'malformed':
                result.stdout += b'123 invalid opaque\n'
            else:
                result.returncode, result.stderr = 1, b'PRIVATE-PROCESS-ERROR'
        return result
    monkeypatch.setattr(subprocess, 'run', run)
    namespace['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(wire)))
    with pytest.raises(RuntimeError):
        namespace['native_main']()
    assert not calls and not (deployment.home / 'rokid-backups/pre-source-fixture').exists()


@pytest.mark.parametrize('fault', ['identity', 'timeout', 'malformed', 'private_failure'])
def test_host_dispatch_keeps_the_attempt_and_publishes_only_allowed_evidence(deployment, monkeypatch, capsys, fault):
    wire, commands, metadata, namespace = generated(deployment)
    calls = []
    def identities(command, **kwargs):
        calls.append(command)
        index = len(calls) - 1
        output = [f'List of devices attached\n{FIXTURE_TARGET} device\n', 'FIXTURE001\n', 'F-51F\n'][index]
        if fault == 'identity' and index == 1:
            output = 'DIFFERENT\n'
        return SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b'')
    def dispatch(command, request):
        calls.append(command)
        assert request == wire
        if fault == 'timeout':
            raise subprocess.TimeoutExpired(command, 180, output=b'PRIVATE-OUTPUT')
        if fault == 'malformed':
            return SimpleNamespace(returncode=2, stdout=b'PRIVATE-OUTPUT', stderr=b'PRIVATE-ERROR')
        namespace['stage'] = 'source_update_final_guard'
        namespace['transaction_state'] = {'phase': 'source_prepared_send0', 'source_writes': 7, 'restored': False}
        failure = namespace['public_failure'](OSError('PRIVATE-ERROR'))
        return SimpleNamespace(returncode=2, stdout=json.dumps(failure).encode(), stderr=b'')
    monkeypatch.setattr(subprocess, 'run', identities)
    monkeypatch.setattr(update, 'dispatch_native', dispatch)
    assert update.execute(wire, commands, metadata) == 2
    report = json.loads(next(deployment.reports.glob('phone-source-update-*.json')).read_bytes())
    assert report['execution']['native_attempts'] == (0 if fault == 'identity' else 1)
    assert len(report['results']) == (2 if fault == 'identity' else 4)
    assert len(calls) == (2 if fault == 'identity' else 4)
    if fault == 'timeout':
        assert report['results'][-1] == {'command': commands[-1], 'exit_code': None}
    if fault == 'private_failure':
        assert report['results'][-1]['public_result']['source_writes'] == 7
    assert 'PRIVATE' not in json.dumps(report) and 'PRIVATE' not in capsys.readouterr().out
    assert update.main([]) == 0
    for flag in ('--execute-approved-source', '--execute'):
        with pytest.raises(SystemExit):
            update.main([flag])
    assert len(calls) == (2 if fault == 'identity' else 4)


@pytest.mark.parametrize('fault', [None, 'version', 'late_owner', 'profile'])
def test_retained_browser_uses_the_snapshot_product_and_fences_owner_changes(deployment, fault):
    runtime = deployment.snapshot['runtime']
    for name, kind, mode in [('tmp', 'directory', 0o700), ('tmp/.X11-unix', 'directory', 0o1777),
                              ('tmp/.X11-unix/X1', 'socket', 0o777)]:
        runtime['X11_socket_metadata'][(deployment.prefix / name).as_posix()] = {
            'exists': True, 'type': kind, 'uid': 123, 'mode': mode}
    repin(deployment)
    wire, commands, metadata, namespace = generated(deployment)
    namespace['set_configuration'](deployment.manifest, deployment.snapshot_path.read_bytes())
    profile = deployment.repo / 'data/chromium-profile'
    profile.mkdir()
    original_metadata = namespace['path_metadata']
    def path_metadata(path):
        if path.as_posix() == profile.as_posix():
            return {**runtime['profile_directory'], 'uid': 124 if fault == 'profile' else 123}
        if path.as_posix() == (profile / 'SingletonLock').as_posix():
            return runtime['profile_lock']
        if str(path) in runtime['X11_socket_metadata']:
            return runtime['X11_socket_metadata'][str(path)]
        return original_metadata(path)
    namespace['path_metadata'] = path_metadata
    namespace['os'] = SimpleNamespace(**{**vars(os), 'readlink': lambda path: 'localhost-12'})
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *unused):
            return False
        def settimeout(self, seconds):
            assert seconds == 1
        def connect_ex(self, address):
            return 1 if address == ('127.0.0.1', 8000) else 0
    namespace['socket'] = SimpleNamespace(AF_UNIX=1, socket=lambda *args: Socket())
    process_reads = []
    def binding(pid):
        process_reads.append(pid)
        result = dict(runtime['browser' if pid == 12 else 'x11'])
        if fault == 'late_owner' and len(process_reads) > 2 and pid == 12:
            result['starttime'] += 1
        return result, ['--user-data-dir=' + profile.as_posix(), '--remote-debugging-address=127.0.0.1',
                        '--remote-debugging-port=9222']
    namespace['process_binding'] = binding
    protocol = []
    def send(method):
        protocol.append(method)
        return ({'product': 'Chrome/changed' if fault == 'version' else 'Chrome/999.1.2.3'}
                if method == 'Browser.getVersion' else {'processInfo': [{'type': 'browser', 'id': 12}]})
    browser = SimpleNamespace(_connection=SimpleNamespace(send=send))
    if fault:
        with pytest.raises(RuntimeError):
            namespace['retained_owner'](browser)
    else:
        assert namespace['retained_owner'](browser) == {'browser': runtime['browser'], 'x11': runtime['x11']}
    assert protocol == ([] if fault == 'profile' else ['Browser.getVersion', 'SystemInfo.getProcessInfo'])
