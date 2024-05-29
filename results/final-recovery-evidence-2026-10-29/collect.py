"""Join actual retained recovery results and identify the current runtime gap."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import time


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(scope_path):
    started = time.monotonic()
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope['root']), scope_path.parent
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'] and not (output/'STARTED.json').exists(), 'one fresh metadata join required')
    lease = (root/'runs/TIMED_STRENGTH.lock').open('r+')
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def stop(*_):
        raise TimeoutError('recovery metadata join deadline exhausted')

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(20, scope['deadline_unix']-time.time()))
    destinations = set()

    def audit(event, args):
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.link', 'os.symlink'}:
            raise RuntimeError('recovery metadata join admits no child, network or link')
        if event == 'open':
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in 'wax+') or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                require(not isinstance(name, int), 'raw metadata descriptor rejected')
                path = Path(name).absolute()
                require(path == path.resolve() and path.parent == output and path.suffix == '.json', 'metadata write escaped join namespace')
                destinations.add(str(path))
                require(len(destinations) <= 8, 'metadata output inventory exhausted')

    sys.addaudithook(audit)
    (output/'STARTED.json').write_text(json.dumps({'unix': time.time()})+'\n')

    def raw(name):
        require(name in scope['source_bindings'], 'unbound recovery relationship input')
        p = root/name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 4*1024**2, 'nonregular or excessive recovery input')
        value = p.read_bytes()
        require(hashlib.sha256(value).hexdigest() == scope['source_bindings'][name], 'recovery input hash differs: '+name)
        return value

    def doc(name):
        return json.loads(raw(name))

    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope['interpreter_sha256'], 'recovery metadata interpreter differs')
    raw(str(Path(__file__).resolve().relative_to(root)))
    controls_root = 'work/final-recovery-controls-1-2026-10-28/'
    archive_root = 'work/final-recovery-archive-1-2026-10-29/'
    executions = {}
    for label, prefix in [('current_controls', controls_root), ('original_archive', archive_root)]:
        closed = doc(prefix+'CLOSED.json')
        require(closed['closed'] is True and type(closed['owner_exit']) is int and closed['owner_exit'] == 0 and closed['stderr_bytes'] == 0, 'recovery stage did not close cleanly')
        require(closed['scope_sha256'] == hashlib.sha256(raw(prefix+'SCOPE.json')).hexdigest(), 'recovery stage scope differs')
        for channel in ['stdout', 'stderr']:
            require(hashlib.sha256(raw(prefix+'owner.'+channel)).hexdigest() == closed[channel+'_sha256'], 'actual recovery stage log differs')
        executions[label] = {k: closed[k] for k in ['owner_exit', 'elapsed_seconds', 'scope_sha256', 'stdout_sha256', 'stderr_sha256']}
    archive, transport = doc(archive_root+'RESULT.json'), doc(archive_root+'TRANSPORT.json')
    require(archive['archive_bytes_verified'] == 297027567 and archive['archive_sha256'] == '7c8fa076cc3b759ccda1f065653a6b74e0277795ca20852fc49f3ffe84b087fa' and archive['archive_staged_on_filesystem'] is False and transport['exit'] == 0 and transport['stderr_bytes'] == 0, 'original recovery archive transport or full identity differs')
    original, full_entry = doc(archive_root+'ORIGINAL_G11.json'), doc(archive_root+'ORIGINAL_FULL_ENTRY.json')
    require(original['status'] == 'passed' and original['full_G11_saved_image_sample'] is True and original['full_gate'] is True and original['full_acceptance'] is False and full_entry['actual_exit'] == 2 and full_entry['stderr'] == '' and len(full_entry['pending_semantic_gates']) == 15, 'actual original G11/full-entry relationship differs')
    require(hashlib.sha256(raw(archive_root+'ORIGINAL_G11.json')).hexdigest() == archive['original_G11_sha256'], 'retained original independent result differs')
    components = original['original_component_reconstructions']
    require(components['arena']['actual_forced_exit'] == components['training']['actual_forced_exit'] == -9 and components['arena']['reconstructed_games'] == 4 and components['arena']['protected_committed_games'] == 1 and components['training']['checkpoint_pairs'] == 5 and components['training']['test_arrays_opened'] is False and components['data']['committed_sources'] == 32 and components['data']['uncommitted_sources_at_kill'] == 52 and components['data']['recovered_sources'] == 56 and components['data']['exact_export_parity'] is True, 'original full recovery reconstruction endpoint differs')
    boundary = doc('results/final-core-runtime-join-2026-10-28/BOUNDARY.json')
    native = original['saved_native_source_binding']
    require(native['native_source_sha256'] == boundary['native_source_sha256'] and native['native_source_modes'] == boundary['native_source_modes'] and len(native['native_source_sha256']) == 69, 'original/final native source boundary differs')
    for name, sha in native['native_source_sha256'].items():
        require(hashlib.sha256(raw(name)).hexdigest() == sha and ('100755' if (root/name).stat().st_mode & 0o111 else '100644') == native['native_source_modes'][name], 'current native source or mode differs')
    for key in ['engine_sha256', 'network_sha256', 'checkpoint_sha256', 'original_model_campaign_sha256']:
        require(native[key] == boundary[key], 'recovery actor lineage differs: '+key)
    resume = original['saved_native_resumption']
    require(resume['status'] == 'passed' and resume['actual_native_exit'] == 0 and resume['engine_sha256'] == native['engine_sha256'] and resume['game_journals'] == resume['pgn_files'] == 4 and resume['new_games_executed'] == 3, 'actual original saved-image resumption differs')
    changed = []
    for role, fields in original['historical_producer_boundaries'].items():
        for name, sha in fields['unchanged_producer_files'].items():
            mode = '100755' if (root/name).stat().st_mode & 0o111 else '100644'
            if hashlib.sha256(raw(name)).hexdigest() != sha or mode != fields['unchanged_producer_modes'][name]:
                changed.append((role, name))
    require(changed == [('arena', 'arena/run.py')], 'current recovery gap differs from inspected change')
    current = doc(controls_root+'RESULT.json')
    require(current['status'] == 'passed_current_arena_recovery_controls_only' and len(current['controls']) == 8 and current['native_chess_starts'] == current['real_games'] == 0 and current['strict_original_G11_guard_unchanged'] is True and current['full_R09_complete'] is False, 'new current-source control result differs')
    proof = doc('results/recovery-full-join-2026-10-26/PROOF.json')
    for name, sha in proof['source_files_sha256'].items():
        if name != 'verification/full_bundle.py':
            require(hashlib.sha256(raw(name)).hexdigest() == sha, 'original recovery reader changed')
    original_controls = doc(archive_root+'ORIGINAL_CONTROLS.json')
    require(len(original_controls) == 9, 'original recovery controls missing')
    result = {'status': 'passed_recovery_coverage_and_identity_audit_only', 'product_source_commit': scope['product_commit'], 'historical_G11_source_commit': original['source_commit'], 'original_archive_sha256': archive['archive_sha256'], 'original_archive_bytes': archive['archive_bytes_verified'], 'original_actual_full_entry_exit': 2, 'historical_full_G11_sample': True, 'matched_native_files_and_modes': 69, 'engine_sha256': native['engine_sha256'], 'network_sha256': native['network_sha256'], 'historical_original_controls': 9, 'new_current_source_controls': 8, 'current_producer_changes': changed, 'unchanged_original_recovery_reader': True, 'strict_original_reader_rejects_current_arena': True, 'executions': executions, 'remaining_required': ['Fresh prospective current-arena forced interruption, committed-record preservation and native resumption with independently checked journals and actual process ownership.', 'A final combined independent reader binding original training/data reconstruction, accepted saved-actor identity, current arena runtime and coordinator source.'], 'current_native_recovery_sample_passed': False, 'full_R09_complete': False, 'full_acceptance': False, 'new_native_starts': 0, 'new_games': 0, 'closed_semantic_samples_rerun': 0, 'elapsed_seconds': time.monotonic()-started}
    (output/'RECOVERY_COVERAGE.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'full_R09_complete': False, 'changed_producer_files': 1, 'new_native_starts': 0, 'elapsed_seconds': result['elapsed_seconds']}))


if __name__ == '__main__':
    main(sys.argv[1])
