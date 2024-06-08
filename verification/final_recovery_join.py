"""Final recovery evidence composition, preserving strict historical admission."""

import ast
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import textwrap
import time


def require(value, reason):
    if not value:
        raise ValueError(reason)


def inspect(e):
    old, current, boundary = e['original'], e['current'], e['boundary']
    require(old['status'] == 'passed' and old['full_G11_saved_image_sample'] is True and old['full_gate'] is True and old['full_acceptance'] is False and old['source_commit'] == '6a63aaaa507646c87ef54b7aab1bea2b71eec1ea', 'original full independent recovery result missing or changed')
    require(e['archive']['archive_sha256'] == '7c8fa076cc3b759ccda1f065653a6b74e0277795ca20852fc49f3ffe84b087fa' and e['archive']['archive_bytes_verified'] == 297027567 and e['old_full_entry']['actual_exit'] == 2 and e['old_full_entry']['stderr'] == '' and len(e['old_full_entry']['pending_semantic_gates']) == 15, 'original full archive/entry relationship differs')
    components = old['original_component_reconstructions']
    require(components['arena']['actual_forced_exit'] == components['training']['actual_forced_exit'] == -9 and components['arena']['reconstructed_games'] == 4 and components['arena']['protected_committed_games'] == 1 and components['training']['checkpoint_pairs'] == 5 and components['training']['removed_tail_preserved'] is True and components['training']['test_arrays_opened'] is False, 'original arena/trainer recovery reconstruction incomplete')
    require(set(components['training']['exact_state_fields']) == {'model', 'optimizer', 'scheduler', 'sampler', 'torch_rng', 'numpy_rng', 'python_rng', 'device_rng', 'config', 'step', 'updates', 'initial_hash', 'current_hash', 'best_validation', 'untrained_validation', 'schema'}, 'original trainer state coverage incomplete')
    data = components['data']
    require(data['committed_sources'] == 32 and data['uncommitted_sources_at_kill'] == 52 and data['recovered_sources'] == 56 and data['exact_export_parity'] is True and data['original_labels_unchanged'] is True and data['final_splits'] == {'train': 5410, 'validation': 489, 'test': 952}, 'original data commit/export reconstruction incomplete')
    for key in ['engine_sha256', 'network_sha256', 'checkpoint_sha256', 'original_model_campaign_sha256', 'native_source_sha256', 'native_source_modes']:
        require(old['saved_native_source_binding'][key] == boundary[key], 'old/final native identity differs: '+key)
    require(boundary['engine_sha256'] == '1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897' and boundary['network_sha256'] == '52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7' and len(boundary['native_source_sha256']) == 69, 'saved deployment identity differs')
    require(e['current_native_hashes'] == boundary['native_source_sha256'] and e['current_native_modes'] == boundary['native_source_modes'], 'current native source or modes differ')
    source = e['runtime_scope']
    require(current['status'] == 'passed_current_arena_runtime_recovery' and current['product_source_commit'] == source['product_commit'] and current['scope_sha256'] == e['runtime_scope_sha256'] and current['profile_sha256'] == source['profile_sha256'], 'new native recovery result/source/scope differs')
    for key in ['engine_sha256', 'network_sha256']:
        require(current[key] == source[key] == boundary[key], 'current native actor differs: '+key)
    require(all(type(current[k]) is int and current[k] == v for k, v in {'actual_forced_exit': -9, 'game_journals': 4, 'pgn_files': 4, 'pairs': 2, 'completed_checkmates': 4, 'native_starts': 12, 'normal_native_exits': 12, 'applied_model_acknowledgements': 12, 'native_game_searches': 4}.items()), 'current native recovery endpoint incomplete')
    require(current['match_games'] == 0 and current['diagnostic_games'] == 4 and current['historical_samples_reexecuted'] is False and current['full_acceptance'] is False, 'current diagnostic scope or full-acceptance claim differs')
    require(e['protected_before'] == e['protected_after'] == current['protected_game_sha256'] == e['kill']['protected_game_sha256'] and type(e['kill']['actual_exit']) is int and e['kill']['actual_exit'] == -9, 'actual forced boundary or committed record differs')
    require(e['write_ledger']['closed'] is True and e['write_ledger'].get('failure') is None and e['write_ledger']['native_starts'] == 12 and e['write_ledger']['scope_sha256'] == e['runtime_scope_sha256'], 'current native storage/start ledger not closed cleanly')
    require(e['active_ledger']['closed'] is True and 0 < e['active_ledger']['active_seconds'] <= source['maximum_active_seconds'], 'current recovery active ledger open or exhausted')
    require(len(e['groups']) == 3 and [g['stage'] for g in e['groups']] == ['interrupted', 'resumed', 'independent'] and all(g['group_absent_after_reap'] is True for g in e['groups']), 'current process ownership/reap incomplete')
    require(e['owner']['closed'] is True and type(e['owner']['owner_exit']) is int and e['owner']['owner_exit'] == 0 and e['owner']['stderr_bytes'] == 0 and e['owner']['scope_sha256'] == e['runtime_scope_sha256'], 'actual current recovery owner failed or differs')
    for label, code in [('interrupted', -9), ('resumed', 0), ('independent', 0)]:
        stage = e['stages'][label]
        require(type(stage['exit']) is int and stage['exit'] == code and stage['cleanup_warnings'] == [] and stage['discarded_output_bytes'] == 0, 'actual recovery stage failed or cleanup differs')
    require(e['independent_result'] == current and e['campaign']['status'] == 'passed-current-arena-component' and e['campaign']['stages_started'] == 3, 'actual independent stage/result or owner closure differs')
    require(e['current_arena_hash'] == source['source_bindings']['arena/run.py'] and e['current_reader_hash'] == source['source_bindings']['verification/final_recovery.py'], 'current source differs from real recovery execution')
    for role, original in old['historical_producer_boundaries'].items():
        for name, digest in original['unchanged_producer_files'].items():
            actual = e['producer_hashes'][name]
            require(actual == (e['current_arena_hash'] if name == 'arena/run.py' else digest), 'unchanged recovery producer relationship differs: '+role)
            require(e['producer_modes'][name] == original['unchanged_producer_modes'][name], 'producer mode relationship differs')
    require(e['old_reader_hashes_match'] is True and e['coordinator_G11_AST_matches'] is True and e['changed_path_controls']['strict_original_G11_guard_unchanged'] is True and len(e['changed_path_controls']['controls']) == 8, 'historical reader/coordinator or new-path coverage differs')
    return {'status': 'passed_final_recovery_evidence_join', 'full_R09_complete': True, 'historical_full_G11_sample_reused_without_rerun': True, 'current_arena_runtime_accepted': True, 'current_recovery_native_starts': 12, 'diagnostic_games': 4, 'new_match_games': 0, 'native_starts_in_this_join': 0, 'native_files_and_modes': 69, 'engine_sha256': boundary['engine_sha256'], 'network_sha256': boundary['network_sha256'], 'current_runtime_product_commit': source['product_commit'], 'current_runtime_scope_sha256': e['runtime_scope_sha256'], 'strict_historical_source_guard_unchanged': True, 'current_G11_coordinator_branch_unchanged': True, 'whole_project_coordinator_executed': False, 'original_compiler_runtime_closure': False, 'historical_bulk_raw_reproduction': False, 'full_acceptance': False}


def main(path):
    start = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    root, output = Path(scope['root']), path.parent
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'] and not (output/'STARTED.json').exists(), 'one new final recovery join invocation required')
    lease = (root/'runs/TIMED_STRENGTH.lock').open('r+')
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    def stop(*_):
        raise TimeoutError('final recovery join deadline exhausted')
    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(30, scope['deadline_unix']-time.time()))
    destinations = set()
    def audit(event, args):
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.link', 'os.symlink'}:
            raise RuntimeError('final recovery join admits no child, native actor, network or link')
        if event == 'open':
            name, mode, flags = args
            if isinstance(mode, str) and any(c in mode for c in 'wax+') or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                require(not isinstance(name, int), 'raw join descriptor rejected')
                target = Path(name).absolute()
                require(target == target.resolve() and target.parent == output and target.suffix == '.json', 'final recovery join write escaped')
                destinations.add(str(target));require(len(destinations) <= 8, 'join metadata inventory exhausted')
    sys.addaudithook(audit)
    (output/'STARTED.json').write_text(json.dumps({'unix': time.time()})+'\n')
    def raw(name):
        require(name in scope['source_bindings'], 'undeclared final recovery input')
        target = root/name
        require(target.is_file() and not target.is_symlink() and target.stat().st_size <= 4*1024**2, 'nonregular or excessive final recovery input')
        value = target.read_bytes()
        require(hashlib.sha256(value).hexdigest() == scope['source_bindings'][name], 'bound final recovery input changed: '+name)
        return value
    def doc(name):
        return json.loads(raw(name))
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope['interpreter_sha256'], 'final recovery interpreter differs')
    raw('verification/final_recovery_join.py')
    run = 'runs/final-current-recovery-2026-10-29/'
    work = 'work/final-recovery-runtime-1-2026-10-29/'
    old = 'results/final-recovery-evidence-2026-10-29/'
    original = doc(old+'ORIGINAL_G11.json')
    boundary = doc('results/final-core-runtime-join-2026-10-28/BOUNDARY.json')
    runtime_scope = doc(work+'SCOPE.json')
    producer_names = {name for role in original['historical_producer_boundaries'].values() for name in role['unchanged_producer_files']}
    def mode(name):
        return '100755' if (root/name).stat().st_mode & 0o111 else '100644'
    stages = {name: doc(run+name+'.json') for name in ['interrupted', 'resumed', 'independent']}
    for name, value in stages.items():
        require(hashlib.sha256(raw(run+name+'.log')).hexdigest() == value['log_sha256'], 'actual recovery stage log identity differs')
    owner = doc(work+'CLOSED.json')
    for channel in ['stdout', 'stderr']:
        require(hashlib.sha256(raw(work+'owner.'+channel)).hexdigest() == owner[channel+'_sha256'], 'actual recovery owner log identity differs')
    # Bind every raw file accepted by the real independent stage without a replay.
    for name in scope['raw_runtime_inventory']:
        raw(name)
    def g11_ast(raw_source):
        source = raw_source.decode()
        first = source.index('        domain = inputs["domains"]["G11"]')
        last = source.index('        domain = inputs["domains"]["G12"]', first)
        return ast.dump(ast.parse(textwrap.dedent(source[first:last])), include_attributes=False)
    historical_source = raw(scope['historical_coordinator'])
    proof = doc('results/recovery-full-join-2026-10-26/PROOF.json')
    require(hashlib.sha256(historical_source).hexdigest() == proof['source_files_sha256']['verification/full_bundle.py'], 'original coordinator bytes differ')
    readers = {name: digest for name, digest in proof['source_files_sha256'].items() if name != 'verification/full_bundle.py'}
    e = {'original': original, 'old_full_entry': doc(old+'ORIGINAL_FULL_ENTRY.json'), 'archive': doc('work/final-recovery-archive-1-2026-10-29/RESULT.json'), 'boundary': boundary, 'current': doc(run+'CURRENT_RECOVERY.json'), 'independent_result': doc(run+'independent/FINAL_RECOVERY.json'), 'runtime_scope': runtime_scope, 'runtime_scope_sha256': hashlib.sha256(raw(work+'SCOPE.json')).hexdigest(), 'current_native_hashes': {name: hashlib.sha256(raw(name)).hexdigest() for name in boundary['native_source_sha256']}, 'current_native_modes': {name: mode(name) for name in boundary['native_source_modes']}, 'protected_before': hashlib.sha256(raw(run+'before/000000-0.json')).hexdigest(), 'protected_after': hashlib.sha256(raw(run+'arena/games/000000-0.json')).hexdigest(), 'kill': doc(run+'KILL.json'), 'write_ledger': doc(work+'WRITE_USAGE.json'), 'active_ledger': doc(run+'ACTIVE_USAGE.json'), 'owner': owner, 'groups': doc(run+'GROUPS.json'), 'campaign': doc(run+'CAMPAIGN.json'), 'stages': stages, 'current_arena_hash': hashlib.sha256(raw('arena/run.py')).hexdigest(), 'current_reader_hash': hashlib.sha256(raw('verification/final_recovery.py')).hexdigest(), 'producer_hashes': {name: hashlib.sha256(raw(name)).hexdigest() for name in producer_names}, 'producer_modes': {name: mode(name) for name in producer_names}, 'old_reader_hashes_match': all(hashlib.sha256(raw(name)).hexdigest() == digest for name, digest in readers.items()), 'coordinator_G11_AST_matches': g11_ast(raw('verification/full_bundle.py')) == g11_ast(historical_source), 'changed_path_controls': doc(old+'CURRENT_CONTROLS.json')}
    result = inspect(e)
    controls = []
    for name, mutate in [('missing_trainer_rng', lambda x: x['original']['original_component_reconstructions']['training']['exact_state_fields'].remove('torch_rng')), ('changed_original_data_export', lambda x: x['original']['original_component_reconstructions']['data'].__setitem__('exact_export_parity', False)), ('changed_current_actor', lambda x: x['current'].__setitem__('engine_sha256', '0'*64)), ('missing_model_ack', lambda x: x['current'].__setitem__('applied_model_acknowledgements', 11)), ('rewritten_committed_game', lambda x: x.__setitem__('protected_after', '0'*64)), ('fake_forced_exit', lambda x: x['kill'].__setitem__('actual_exit', 0)), ('open_storage_ledger', lambda x: x['write_ledger'].__setitem__('closed', False)), ('changed_actual_stage_exit', lambda x: x['stages']['resumed'].__setitem__('exit', 1)), ('surviving_process_group', lambda x: x['groups'][0].__setitem__('group_absent_after_reap', False)), ('changed_current_arena', lambda x: x.__setitem__('current_arena_hash', '0'*64)), ('changed_native_source', lambda x: x['current_native_hashes'].__setitem__('src/search.cpp', '0'*64)), ('forged_full_acceptance', lambda x: x['current'].__setitem__('full_acceptance', True))]:
        forged = copy.deepcopy(e);mutate(forged)
        try:
            inspect(forged)
        except (ValueError, KeyError) as error:
            controls.append({'case': name, 'rejected': True, 'reason': str(error)})
        else:
            raise ValueError('forged final recovery relationship accepted: '+name)
    result.update(product_source_commit=scope['product_commit'], relationship_controls=len(controls), current_runtime_owner_elapsed_seconds=owner['elapsed_seconds'], current_runtime_active_seconds=e['active_ledger']['active_seconds'], input_manifest_pins=len(scope['source_bindings']), raw_runtime_files=len(scope['raw_runtime_inventory']), elapsed_seconds=time.monotonic()-start)
    (output/'RECOVERY_JOIN.json').write_text(json.dumps(result, indent=2)+'\n')
    (output/'CONTROLS.json').write_text(json.dumps(controls, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main(sys.argv[1])
