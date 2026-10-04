"""One local replay; no phone, browser, CDP or real subprocess connections."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
from types import SimpleNamespace
import zlib

import pytest

from app.solvers import cdp
from scripts import phone_update as update


def test_source_transaction_and_public_boundary(tmp_path, monkeypatch, capsys):
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)  # Python 3.10 compatibility
    # CI has no ignored/private artifacts; the separate manifest preview pins those.
    original = {'requirements-phone.txt': b'# requirements\n', 'constraints-phone.txt': b'# constraints\n',
                'app/main.py': b'VERSION = 1\n', 'scripts/phone_env.sh': b':\n',
                **{f'app/fixture{i:03d}.py': b'VALUE = 1\n' for i in range(75)}}
    new = {name: content + b'# updated\n' for name, content in original.items()}
    reports = tmp_path / 'reports'
    reports.mkdir()
    for name, payload in ((update.OLD_ARCHIVE, original), (update.NEW_ARCHIVE, new)):
        with tarfile.open(reports / name, 'w:') as archive:
            for directory in ('app', 'scripts'):
                member = tarfile.TarInfo(directory)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            for path, data in payload.items():
                member = tarfile.TarInfo(path)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    old_content = (reports / update.OLD_ARCHIVE).read_bytes()
    old_pin = hashlib.sha256(old_content).hexdigest()
    monkeypatch.setattr(update, 'NEW_ARCHIVE_SHA', update.sha(reports / update.NEW_ARCHIVE))
    assert update.load_bundle(old_content, old_pin) == original
    assert update.load_bundle((reports / update.NEW_ARCHIVE).read_bytes(), update.NEW_ARCHIVE_SHA) == new
    old_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
    binding = {'pid': 12, 'uid': 123, 'starttime': 456, 'boot_id_sha256': '0' * 64}
    x11 = {**binding, 'pid': 13, 'starttime': 457}
    target = 'adb-FIXTURE001-example._adb-tls-connect._tcp'
    proof = {'results': [{'exit_code': 0}, {'exit_code': 0, 'stdout': 'FIXTURE001\n', 'command': ['adb', '-s', target]},
                         {'exit_code': 0, 'stdout': 'F-51F\n'}, {'exit_code': 0, 'stdout': json.dumps({
                             'authentication_verified': True, 'model_and_effort_verified': True,
                             'browser_binding': binding, 'x11_binding': x11})}]}
    proof_path = reports / 'auth.json'
    proof_path.write_text(json.dumps(proof), encoding='utf-8')
    manifest = {'schema': 1, 'device': {'target': target, 'serial': 'FIXTURE001', 'model': 'F-51F', 'uid': 123},
                'browser': binding, 'x11': x11, 'auth_report': 'auth.json', 'pins': {
                    'boot': '0' * 64, 'helper': '0' * 64, 'cdp': '0' * 64, 'logger': '0' * 64,
                    'preserved': '0' * 64, 'old_archive': old_pin, 'new_archive': update.NEW_ARCHIVE_SHA,
                    'auth_report': update.sha(proof_path)}}
    manifest_path = reports / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(update, 'REPORTS', reports)
    provenance = update.configure(manifest_path, update.sha(manifest_path))
    request, commands, metadata = update.prepare(provenance)
    bootstrap = shlex.split(commands[-1][-1])[-1]
    encoded = next(n.value for n in ast.walk(ast.parse(bootstrap)) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str) and len(n.value) > 500)
    native = zlib.decompress(base64.b64decode(encoded)).decode()
    assert hashlib.sha256(native.encode()).hexdigest() == metadata['native_sha256']
    assert metadata['wire_characters'] < 32767 and metadata['approval_received'] is False
    assert len(commands) == 4 and len(json.loads(request)['old_hashes']) == 79
    # Execute the real generated definitions, excluding only the device entry call.
    tree = ast.parse(native)
    root_files = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'ROOT_FILES' for t in n.targets))
    assert isinstance(root_files, ast.Set) and [n.value for n in root_files.elts] == sorted(update.ROOT_FILES)
    tree.body.pop()
    ns = {}
    exec(compile(tree, '<generated-phone-update-definitions>', 'exec'), ns)
    assert ast.dump(ast.parse(ast.get_source_segment(native, next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'update_sources')))) == ast.dump(
                        ast.parse(ast.get_source_segment(Path(update.__file__).read_text(), next(n for n in
                                  ast.parse(Path(update.__file__).read_text()).body
                                  if isinstance(n, ast.FunctionDef) and n.name == 'update_sources'))))

    golden_sha = '24744f87ec1567c53f38ed9bdbc66f938638c1675081d9ce09e003f5e4289dc9'
    assert hashlib.sha256(b'{"fixture": true}').hexdigest() == golden_sha
    guard_definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'native_guard')
    comparison = next(n.test for n in guard_definition.body if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Compare) and any(isinstance(c, ast.Name)
                          and c.id == 'PRESERVED_SHA' for c in n.test.comparators))
    assert eval(compile(ast.Expression(comparison), '<actual-native-preserved-comparison>', 'eval'), ns,
                {'snapshot': {'fixture': True}, 'PRESERVED_SHA': golden_sha}) is False

    native_main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'native_main')
    browser_assignment = next(n for n in native_main.body if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == 'browser' for t in n.targets))
    transport_calls = []
    def fixture_http(url, timeout_s):
        transport_calls.append(('http', url, timeout_s))
        return {'webSocketDebuggerUrl': 'ws://fixture.invalid/browser'}
    def fixture_connection(url, *, timeout_s):
        transport_calls.append(('connection', url, timeout_s))
        return SimpleNamespace(close=lambda: transport_calls.append(('client_close',)))
    with monkeypatch.context() as transport:
        transport.setattr(cdp, '_http_json', fixture_http)
        transport.setattr(cdp, '_Connection', fixture_connection)
        browser = eval(compile(ast.Expression(browser_assignment.value), '<actual-native-cdp-connect>', 'eval'),
                       {'cdp': vars(cdp)})
        assert isinstance(browser, cdp.Browser)
        disconnect = next(n.finalbody[0].value for n in native_main.body if isinstance(n, ast.Try))
        eval(compile(ast.Expression(disconnect), '<actual-native-client-disconnect>', 'eval'), {'browser': browser})
    assert transport_calls == [('http', 'http://127.0.0.1:9222/json/version', 8),
                               ('connection', 'ws://fixture.invalid/browser', 8), ('client_close',)]

    def layout(name):
        repo = tmp_path / name
        for path, content in original.items():
            destination = repo / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        for path in ('data/chromium-profile/state', '.git/HEAD', 'multimodal.env'):
            destination = repo / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'private-fixture-unchanged')
        return repo

    quiet_prefix = tmp_path / 'quiet-prefix'
    for service in ('cupsd', 'ssh-agent', 'sshd', 'tx11', 'tx11-xfce4'):
        directory = quiet_prefix / 'var/service' / service
        (directory / 'log').mkdir(parents=True)
        for name in ('down', 'run', 'log/run'):
            (directory / name).write_bytes(b'# fixture\n')
    actual_stat, actual_read, actual_iterdir = Path.stat, Path.read_bytes, Path.iterdir
    process_case = {'fault': 'ok'}
    ps_calls = []

    def own_stat(path, *args, **kwargs):
        if path.parent == Path('/proc'):
            if path.name == '1':
                raise PermissionError('foreign-process-private-error')
            return SimpleNamespace(st_uid=124 if process_case['fault'] == 'owner' else 123)
        info = actual_stat(path, *args, **kwargs)
        if path.is_relative_to(quiet_prefix):
            fields = list(info)
            fields[4] = 123
            return ns['os'].stat_result(fields)
        return info

    def own_cmdline(path):
        if path.parent.parent == Path('/proc'):
            if path.parent.name == '14':
                raise FileNotFoundError('ps-already-exited')
            if process_case['fault'] == 'permission':
                raise PermissionError('own-process-private-error')
            return b'uvicorn\0' if process_case['fault'] == 'blocked' else b'chrome\0'
        return actual_read(path)

    def proc_inventory(path):
        return iter([path / '1']) if path == Path('/proc') else actual_iterdir(path)

    def owned_ps(command, **kwargs):
        ps_calls.append(command)
        assert command == ['/system/bin/ps', '-u', '123', '-o', 'UID,PID']
        assert kwargs == {'capture_output': True, 'timeout': 5, 'check': False}
        stdout = b'UID PID\n123 45\n123 12\n123 13\n123 14\n'
        stdout = {'malformed': b'UID PID\n123 invalid\n', 'header': b'USER PID\n123 45\n',
                  'duplicate': stdout + b'123 12\n', 'uid': stdout + b'124 15\n',
                  'missing': b'UID PID\n123 45\n123 12\n'}.get(process_case['fault'], stdout)
        return SimpleNamespace(returncode=1 if process_case['fault'] == 'failed' else 0,
                               stdout=stdout, stderr=b'private-ps-error' if process_case['fault'] == 'stderr' else b'')

    with monkeypatch.context() as processes:
        processes.setitem(ns, 'PHONE_PREFIX', quiet_prefix)
        processes.setitem(ns, 'LOGGER_LEAVES', set())
        processes.setattr(Path, 'stat', own_stat)
        processes.setattr(Path, 'read_bytes', own_cmdline)
        processes.setattr(Path, 'iterdir', proc_inventory)
        processes.setattr(ns['os'], 'getpid', lambda: 45)
        processes.setattr(ns['subprocess'], 'run', owned_ps)
        snapshot = ns['quiet_services']({'plain': ns['plain']})
        assert set(snapshot) == {'cupsd', 'ssh-agent', 'sshd', 'tx11', 'tx11-xfce4'}
        assert ps_calls == [['/system/bin/ps', '-u', '123', '-o', 'UID,PID']]
        for fault in ('blocked', 'permission', 'owner', 'malformed', 'header', 'duplicate', 'uid',
                      'missing', 'failed', 'stderr'):
            process_case['fault'] = fault
            ns['transaction_state'] = {'phase': 'not_started', 'source_writes': 0, 'restored': False}
            repo = layout('quiet-' + fault)
            backup = tmp_path / ('quiet-' + fault + '-backup')
            with pytest.raises((RuntimeError, PermissionError)) as failure:
                ns['update_sources'](repo, backup, new, old_hashes,
                                     lambda expected: ns['quiet_services']({'plain': ns['plain']}))
            assert not backup.exists() and ns['source_hashes'](repo, original) == old_hashes
            assert ns['transaction_state']['source_writes'] == 0
            assert 'private' not in json.dumps(ns['public_failure'](failure.value))

    git_repo = layout('git-transition')
    git_root = git_repo / '.git'
    (git_root / 'HEAD').unlink()
    git_root.rmdir()  # Only the newly created local fixture; no phone or repository metadata.
    git_calls = 0

    def git_stat(path, *args, **kwargs):
        info = actual_stat(path, *args, **kwargs)
        if path.is_relative_to(git_root):
            fields = list(info)
            fields[4] = 123
            fields[0] = (fields[0] & ~0o777) | 0o700
            return ns['os'].stat_result(fields)
        return info

    def changed_git_guard(expected):
        nonlocal git_calls
        git_calls += 1
        if git_calls == 2:
            git_root.mkdir()
            (git_root / 'HEAD').write_bytes(b'fixture-third-party-metadata')
        return {'git_metadata_sha256': ns['git_metadata_digest']()}

    with monkeypatch.context() as git:
        git.setitem(ns, 'PHONE_REPO', git_repo)
        git.setattr(Path, 'stat', git_stat)
        assert ns['git_metadata_digest']() is None
        ns['transaction_state'] = {'phase': 'not_started', 'source_writes': 0, 'restored': False}
        with pytest.raises(RuntimeError):
            ns['update_sources'](git_repo, tmp_path / 'git-transition-backup', new, old_hashes, changed_git_guard)
        assert isinstance(ns['git_metadata_digest'](), str) and git_root.is_dir()
        assert ns['source_hashes'](git_repo, original) == old_hashes
        assert ns['transaction_state']['source_writes'] == 0

    stable = {'owner': 'fixture', 'private': 'unchanged'}
    def guard(expected):
        return stable
    repo = layout('success')
    before = {p: (repo / p).read_bytes() for p in ('data/chromium-profile/state', '.git/HEAD', 'multimodal.env')}
    receipt = ns['update_sources'](repo, tmp_path / 'ok-backup', new, old_hashes, guard)
    assert receipt['phase'] == 'source_prepared_send0' and receipt['source_writes'] == 79
    assert ns['source_hashes'](repo, new) == {k: hashlib.sha256(v).hexdigest() for k, v in new.items()}
    assert all((repo / p).read_bytes() == content for p, content in before.items())
    assert len(list((tmp_path / 'ok-backup/source').rglob('*.*'))) >= 79
    assert not (tmp_path / 'ok-backup/protected').exists()
    returned = next(n for n in ast.walk(next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                                            and n.name == 'native_main')) if isinstance(n, ast.Return))
    completion = eval(compile(ast.Expression(returned.value), '<actual-native-public-return>', 'eval'), ns,
                      {'phase': 'source_prepared_send0', 'writes': 79,
                       'receipt_sha': ns['sha'](tmp_path / 'ok-backup/manifest.json'), 'stage': 'complete'})
    update.validate_public(completion, 'update')
    for counter in ('source_files', 'source_writes', 'GPT_submissions', 'Input_calls'):
        for invalid in (False, float(completion[counter])):
            with pytest.raises(RuntimeError):
                update.validate_public({**completion, counter: invalid}, 'update')
    with pytest.raises(RuntimeError):
        update.validate_public({**completion, 'private_unknown': 'must-not-be-logged'}, 'update')
    with pytest.raises(RuntimeError):
        update.configure(manifest_path, '0' * 64)
    with pytest.raises(RuntimeError, match='transaction_already_exists'):
        ns['update_sources'](repo, tmp_path / 'ok-backup', new, old_hashes, guard)
    for changed_by_third_party in (False, True):
        ns['transaction_state'] = {'phase': 'not_started', 'source_writes': 0, 'restored': False}
        repo = layout('changed' if changed_by_third_party else 'restore')
        backup = tmp_path / ('changed-backup' if changed_by_third_party else 'restore-backup')
        calls = 0

        def fail_midway(path, content, mode):
            nonlocal calls
            if path.is_relative_to(repo):
                calls += 1
                if calls == 4:
                    if changed_by_third_party:
                        (repo / next(iter(original))).write_bytes(b'foreign-change')
                    raise OSError('private-error-must-not-be-output')
            ns['atomic_bytes'](path, content, mode)

        with pytest.raises((OSError, RuntimeError)):
            ns['update_sources'](repo, backup, new, old_hashes, guard, write=fail_midway)
        saved = json.loads((backup / 'manifest.json').read_bytes())
        assert saved['phase'] == ('rollback_blocked' if changed_by_third_party else 'rolled_back')
        if not changed_by_third_party:
            assert ns['source_hashes'](repo, original) == old_hashes
        else:
            assert (repo / next(iter(original))).read_bytes() == b'foreign-change'
    for kind in ('unknown', 'unsafe', 'precondition'):
        repo = layout(kind)
        paths, hashes = dict(new), dict(old_hashes)
        if kind == 'unknown':
            (repo / next(iter(original))).write_bytes(b'unknown-old')
        if kind == 'unsafe':
            paths['../multimodal.env'] = paths.pop(next(iter(paths)))
            hashes['../multimodal.env'] = hashes.pop(next(iter(hashes)))

        def precondition(expected):
            if kind == 'precondition':
                raise RuntimeError('owner_changed')
            return stable

        with pytest.raises(RuntimeError):
            ns['update_sources'](repo, tmp_path / (kind + '-backup'), paths, hashes, precondition)
        assert not (tmp_path / (kind + '-backup')).exists()
    for member_name, member_type in (('../outside', tarfile.REGTYPE), ('app/link', tarfile.SYMTYPE)):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:') as archive:
            member = tarfile.TarInfo(member_name)
            member.type = member_type
            archive.addfile(member)
        data = buffer.getvalue()
        with pytest.raises(RuntimeError):
            ns['load_bundle'](data, hashlib.sha256(data).hexdigest())

    # One host timeout: attempted row 4 and all completed identity rows survive.
    calls = []
    ns['transaction_state'] = {'phase': 'source_prepared_send0', 'source_writes': 79, 'restored': False}
    ns['stage'] = 'source_update_final_guard'
    receipt_failure = ns['public_failure'](OSError('private-receipt-read-error'))
    update.validate_public(receipt_failure, 'update')

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 4:
            raise subprocess.TimeoutExpired(command, 180, output=b'private-output')
        stdout = (f'List of devices attached\n{target} device model:F_51F\n' if len(calls) == 1
                  else 'FIXTURE001\n' if len(calls) == 2 else 'F-51F\n')
        return SimpleNamespace(returncode=0, stdout=stdout.encode(), stderr=b'')

    monkeypatch.setattr(update.subprocess, 'run', fake_run)
    def receipt_read_failure(command, **kwargs):
        if len(calls) == 3:
            calls.append(command)
            return SimpleNamespace(returncode=2, stdout=json.dumps(receipt_failure).encode(), stderr=b'')
        return fake_run(command, **kwargs)

    monkeypatch.setattr(update.subprocess, 'run', receipt_read_failure)
    assert update.execute(request, commands, metadata) == 2
    stored = json.loads(next(reports.glob('phone-source-update-*.json')).read_bytes())
    assert stored['results'][-1]['public_result'] == receipt_failure
    assert stored['results'][-1]['exit_code'] == 2 and receipt_failure['source_writes'] == 79
    assert receipt_failure['transaction_phase'] == 'source_prepared_send0' and receipt_failure['restored'] is False
    calls.clear()
    monkeypatch.setattr(update.subprocess, 'run', fake_run)
    assert update.execute(request, commands, metadata) == 2
    saved = next(value for p in reports.glob('phone-source-update-*.json')
                 if (value := json.loads(p.read_bytes()))['execution']['error_type'] == 'TimeoutExpired')
    assert len(saved['results']) == 4 and saved['results'][-1] == {'command': commands[-1], 'exit_code': None}
    assert saved['execution']['native_attempts'] == 1 and saved['execution']['error_type'] == 'TimeoutExpired'
    assert saved['invocation_flag'] == update.EXECUTE_FLAG and saved['read_only'] is False
    assert 'private-output' not in json.dumps(saved) and len(calls) == 4
    assert update.main([]) == 0 and len(calls) == 4
    for invalid_flag in ('--execute-approved-source', '--execute'):
        with pytest.raises(SystemExit):
            update.main([invalid_flag])
    assert len(calls) == 4
    assert 'private-error-must-not-be-output' not in capsys.readouterr().out
