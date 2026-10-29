"""Independent raw current-arena interruption, journals and native-session reader."""

import hashlib
import json
from pathlib import Path

from verification.match_journals import verify as journals


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(scope, output):
    root, output = Path(scope['root']), Path(output)
    profile = json.loads((root/'config/final-recovery-runtime-v1.json').read_text())
    require(profile['pairs'] == 2 and profile['nodes'] == 2000 and profile['required_native_starts'] == profile['required_normal_native_exits'] == 12 and profile['required_forced_exit'] == -9 and profile['required_game_journals'] == profile['required_completed_outcomes'] == 4, 'recovery endpoint was weakened')
    config = json.loads((output/'INPUT.json').read_text())
    identity = json.loads((output/'arena/CONFIG.json').read_text())
    require(identity['config'] == config and config['profile'] == 'recovery-diagnostic-v2' and config['pairs'] == 2 and config['nodes'] == 2000 and config['max_plies'] == 64 and 'power_wait' not in config, 'current recovery configuration differs')
    expected_options = {'EvalFile': scope['network'], **profile['options']}
    for role in ['candidate', 'opponent']:
        actor, bound = config[role], identity['executables'][role]
        require(actor['command'] == [scope['engine']] and actor['options'] == expected_options and bound['executable'] == scope['engine_sha256'] and bound['network_sha256'] == scope['network_sha256'], 'current recovery actor/model/options differ')
    require(sha(scope['engine']) == scope['engine_sha256'] and sha(scope['network']) == scope['network_sha256'], 'saved recovery inputs changed')
    kill = json.loads((output/'KILL.json').read_text())
    boundary = json.loads((output/'BOUNDARY.json').read_text())
    require(type(kill['actual_exit']) is int and kill['actual_exit'] == -9 and type(kill['signal']) is int and kill['signal'] == 9 and kill['owned_stage_pid'] == boundary['owned_stage_pid'] == boundary['owned_group'] and type(boundary['signal_monotonic_ns']) is int and kill['reaped_monotonic_ns'] > boundary['signal_monotonic_ns'], 'actual owned SIGKILL or reap witness differs')
    before, protected = output/'before/000000-0.json', output/'arena/games/000000-0.json'
    require(sha(before) == sha(protected) == kill['protected_game_sha256'] == boundary['barrier']['game_sha256'], 'committed current recovery game changed')
    for name, text in [('000000-0.pgn.tmp', '[Event "torn'), ('000000-1.json.tmp', '{"torn":')]:
        require((output/'partial-before'/name).read_text() == text and not (output/'arena/games'/name).exists(), 'torn write was missing or retained as authoritative output')
    for stage, code, reason in [('interrupted', -9, 'nonzero-exit'), ('resumed', 0, 'completed')]:
        actual = json.loads((output/(stage+'.json')).read_text())
        require(type(actual['exit']) is int and actual['exit'] == code and actual['reason'] == reason and actual['cleanup_warnings'] == [] and actual['discarded_output_bytes'] == 0 and sha(output/(stage+'.log')) == actual['log_sha256'], 'actual current arena stage/log differs')
    groups = json.loads((output/'GROUPS.json').read_text())
    require([g['stage'] for g in groups] == ['interrupted', 'resumed'] and all(g['group_absent_after_reap'] is True for g in groups), 'owned arena process groups survived')
    checked = journals(output/'arena', maximum_seconds=20)
    require(checked['game_journals'] == checked['pgn_files'] == 4 and checked['pairs'] == 2, 'current recovery journal inventory incomplete')
    games = [json.loads(p.read_text()) for p in sorted((output/'arena/games').glob('*.json'))]
    require(len(games) == 4 and all(g['result'] in {'1-0', '0-1'} and g['termination'] == 'checkmate' and g['culprit'] is None and g['observations'] for g in games), 'current recovery diagnostic failed a completed checkmate endpoint')
    sessions = sorted((output/'native').iterdir())
    require([p.name for p in sessions] == [f'session-{i:02d}.json' for i in range(1, 13)], 'current recovery native session inventory differs')
    network_identity = Path(scope['network']).read_bytes()[40:104].decode('ascii')
    commands = ['setoption name '+name+' value '+(str(value).lower() if type(value) is bool else str(value)) for name, value in expected_options.items()]
    native_searches = 0
    for index, path in enumerate(sessions, 1):
        session = json.loads(path.read_text())
        label = 'interrupted' if index <= 4 else 'resumed'
        group = next(g['pid'] for g in groups if g['stage'] == label)
        require(session['index'] == index and session['stage'] == label and session['owning_group'] == group and session['native_exit'] == 0 and session['forced_cleanup'] is False and session['stderr_bytes'] == 0 and session['stderr_sha256'] == hashlib.sha256(b'').hexdigest(), 'native current recovery exit, stderr or ownership differs')
        require(session['engine_sha256'] == scope['engine_sha256'] and session['network_sha256'] == scope['network_sha256'], 'native recovery identity differs')
        wire = session['wire']
        require(wire[0] == {'send': 'uci'} and wire[1]['until'] == 'uciok' and wire[1]['received'][-1] == 'uciok', 'native recovery handshake absent')
        require([w.get('send') for w in wire[2:2+len(commands)]] == commands and wire[2+len(commands)] == {'send': 'isready'}, 'actual applied recovery options differ')
        ready = wire[3+len(commands)]
        require(ready['until'] == 'readyok' and ready['received'][-1] == 'readyok', 'recovery options readiness absent')
        received = [line for w in wire for line in w.get('received', [])]
        require([line for line in received if line.startswith('info string network ')] == ['info string network '+network_identity] and not any(line.startswith('info string error') for line in received), 'recovery model acknowledgement missing, duplicate or wrong')
        require(wire[-2:] == [{'send': 'stop'}, {'send': 'quit'}], 'native recovery did not quit normally')
        go = [w['send'] for w in wire if 'send' in w and w['send'].startswith('go ')]
        require(go and go[0] == 'go nodes 1' and all(command == 'go nodes 2000' for command in go[1:]), 'recovery search budget differs')
        native_searches += len(go)-1
    ledger = json.loads(Path(scope['ledger']).read_text())
    require(ledger['native_starts'] == 12 and ledger.get('failure') is None and ledger['scope_sha256'] == scope['scope_sha256'], 'actual recovery native start ledger differs')
    return {'status': 'passed_current_arena_runtime_recovery', 'product_source_commit': scope['product_commit'], 'scope_sha256': scope['scope_sha256'], 'profile_sha256': scope['profile_sha256'], 'engine_sha256': scope['engine_sha256'], 'network_sha256': scope['network_sha256'], 'actual_forced_exit': -9, 'protected_game_sha256': sha(before), 'game_journals': 4, 'pgn_files': 4, 'pairs': 2, 'completed_checkmates': 4, 'native_starts': 12, 'normal_native_exits': 12, 'applied_model_acknowledgements': 12, 'native_game_searches': native_searches, 'arena_groups_absent_after_reap': True, 'journal_reader': checked, 'match_games': 0, 'diagnostic_games': 4, 'historical_samples_reexecuted': False, 'full_R09_complete': False, 'full_acceptance': False, 'scope': 'New current-source arena interruption/resumption component only; historical training/data and final combined evidence remain separate.'}
