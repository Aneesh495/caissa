"""One finite current-source recovery diagnostic, with owned native pipes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import runpy
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import parallel_storage_quota as storage


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RecoveryQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        require(path == path.resolve() and path.is_relative_to(self.output), 'recovery output escaped declared namespace')
        relative = str(path.relative_to(self.output))
        canonical = relative[:-4] if relative.endswith('.tmp') else relative
        root = {'WRITER.lock', 'CONFIG.json', 'COMMANDS.jsonl', 'PROGRESS.json', 'CAMPAIGN.json', 'ACTIVE_USAGE.json', 'INPUT.json', 'BOUNDARY.json', 'KILL.json', 'CURRENT_RECOVERY.json', 'FAILED-final-recovery.json', 'interrupted.log', 'interrupted.json', 'resumed.log', 'resumed.json', 'independent.log', 'independent.json', 'GROUPS.json'}
        valid = canonical in root
        valid |= canonical in {'arena/CONFIG.json', 'arena/PROTOCOL.json', 'arena/RECOVERY_READY.json', 'before/000000-0.json', 'partial-before/000000-0.pgn.tmp', 'partial-before/000000-1.json.tmp', 'independent/FINAL_RECOVERY.json', 'independent/CONTROLS.json'}
        # Preserved torn-write fixtures end in .tmp, and are not atomic writers.
        valid |= relative in {'partial-before/000000-0.pgn.tmp', 'partial-before/000000-1.json.tmp'}
        immutable = re.fullmatch(r'arena/(?:games/00000[01]-[01]\.(?:json|pgn)|pairs/00000[01]\.json)', canonical)
        native = re.fullmatch(r'native/session-(?:0[1-9]|1[0-2])\.json', canonical)
        valid |= bool(immutable or native)
        require(valid, 'unknown recovery evidence destination: '+relative)
        if immutable or native or canonical.startswith('before/'):
            require(not (self.output/canonical).exists(), 'committed recovery evidence is immutable')
        return 'control', ('FAILED-'+relative.replace('/', '-') if canonical.startswith('FAILED-') else relative)


def load_scope(path):
    scope = json.loads(Path(path).read_text())
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'], 'new current recovery scope is not live')
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and sha(scope['interpreter']) == scope['interpreter_sha256'], 'recovery interpreter differs')
    for name, expected in scope['source_bindings'].items():
        require(not (ROOT/name).is_symlink() and sha(ROOT/name) == expected, 'recovery source/input differs: '+name)
    return scope


def bootstrap(path, label):
    scope = load_scope(path)
    from tools.host_lease import inherited
    from tools.campaign_process import atomic
    require(inherited(ROOT/'runs/TIMED_STRENGTH.lock'), 'current recovery stage lost inherited lease')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2*1024**2, 2*1024**2))
    quota = RecoveryQuota({**scope, 'scope_sha256': sha(path)})
    quota.install()
    output = Path(scope['output'])
    original_popen = subprocess.Popen
    if label == 'independent':
        def forbidden(*_args, **_kwargs):
            raise ValueError('independent recovery reader admits no native or child process')
        subprocess.Popen = forbidden
        from verification.final_recovery import verify
        value = verify({**scope, 'scope_sha256': sha(path)}, output)
        (output/'independent').mkdir()
        atomic(output/'independent/FINAL_RECOVERY.json', value)
        print(json.dumps(value))
        return
    require(label in {'interrupted', 'resumed'}, 'unknown recovery stage')
    from arena.client import UciClient
    (output/'native').mkdir(exist_ok=True)

    def native_popen(command, *args, **kwargs):
        require(command == [scope['engine']] and sha(scope['engine']) == scope['engine_sha256'], 'only the exact saved recovery actor is admitted')
        def count(state):
            state['native_starts'] = state.get('native_starts', 0)+1
            if state['native_starts'] > 12:
                raise storage.StorageLimit('current recovery native start ceiling exhausted')
        index = quota.update(count)['native_starts']
        kwargs.update(start_new_session=False, stderr=subprocess.PIPE)
        process = original_popen(command, *args, **kwargs)
        require(os.getpgid(process.pid) == os.getpgrp(), 'recovery actor escaped owning stage group')
        process.recovery_index = index
        process.recovery_stderr_count = 0
        process.recovery_stderr_digest = hashlib.sha256()
        process.recovery_forced = False
        original_kill, original_terminate = process.kill, process.terminate
        def forced_kill():
            process.recovery_forced = True
            return original_kill()
        def forced_terminate():
            process.recovery_forced = True
            return original_terminate()
        process.kill, process.terminate = forced_kill, forced_terminate
        def drain():
            while block := process.stderr.read(16384):
                process.recovery_stderr_digest.update(block.encode())
                process.recovery_stderr_count += len(block.encode())
        process.recovery_stderr_reader = threading.Thread(target=drain, daemon=True)
        process.recovery_stderr_reader.start()
        return process

    subprocess.Popen = native_popen
    original_send, original_until, original_close = UciClient.send, UciClient.until, UciClient.close
    def send(client, text):
        original_send(client, text)
        client.__dict__.setdefault('recovery_wire', []).append({'send': text})
    def until(client, prefix, timeout):
        lines = original_until(client, prefix, timeout)
        client.__dict__.setdefault('recovery_wire', []).append({'until': prefix, 'received': lines})
        return lines
    def close(client):
        original_close(client)
        process = client.process
        if getattr(process, 'recovery_recorded', False):
            return
        process.recovery_stderr_reader.join(timeout=2)
        client.reader.join(timeout=2)
        require(not process.recovery_stderr_reader.is_alive() and not client.reader.is_alive(), 'native recovery pipes did not close')
        process.stderr.close()
        atomic(output/f'native/session-{process.recovery_index:02d}.json', {'stage': label, 'index': process.recovery_index, 'pid': process.pid, 'owning_group': os.getpgrp(), 'native_exit': process.returncode, 'forced_cleanup': process.recovery_forced, 'stderr_bytes': process.recovery_stderr_count, 'stderr_sha256': process.recovery_stderr_digest.hexdigest(), 'engine_sha256': scope['engine_sha256'], 'network_sha256': scope['network_sha256'], 'wire': client.recovery_wire})
        process.recovery_recorded = True
    UciClient.send, UciClient.until, UciClient.close = send, until, close
    arguments = ['arena.run', str(output/'INPUT.json'), str(output/'arena'), '--workers', '1']
    if label == 'interrupted':
        arguments += ['--recovery-barrier', str(output/'arena/RECOVERY_READY.json')]
    sys.argv = arguments
    runpy.run_module('arena.run', run_name='__main__')


def execute(path):
    scope = load_scope(path)
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, StageFailure, atomic
    from tools.storage_budget import footprint
    import shutil
    lease = HostLease(ROOT/'runs')
    output = Path(scope['output'])
    quota = RecoveryQuota({**scope, 'scope_sha256': sha(path)})
    quota.create()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2*1024**2, 2*1024**2))
    quota.install()
    campaign, current, killed = None, [None], [False]
    groups = []
    original_popen = subprocess.Popen
    base = [sys.executable, '-B', '-P', str(Path(__file__).resolve()), '--scope', str(path), '--stage']
    launched = []
    def stage_popen(command, *args, **kwargs):
        require(command and command[-1] in {'interrupted', 'resumed', 'independent'} and command == base+[command[-1]] and command[-1] not in launched and len(launched) < 3, 'only three declared Python stages admitted')
        launched.append(command[-1])
        process = original_popen(command, *args, **kwargs)
        require(os.getpgid(process.pid) == process.pid, 'recovery stage does not own its process group')
        current[0] = process
        return process
    subprocess.Popen = stage_popen

    def guard():
        lease.check()
        require(not quota.read().get('failure'), 'current recovery storage failure latched')
        if current[0] is not None and launched[-1] == 'interrupted' and not killed[0] and (output/'arena/RECOVERY_READY.json').exists():
            barrier = json.loads((output/'arena/RECOVERY_READY.json').read_text())
            committed = output/'arena/games/000000-0.json'
            require(barrier['pair'] == barrier['reverse'] == 0 and sha(committed) == barrier['game_sha256'], 'current recovery transaction boundary differs')
            require({p.name for p in (output/'arena/games').iterdir()} == {'000000-0.json'} and not list((output/'arena/pairs').iterdir()), 'forced interruption missed exact partial-pair boundary')
            require(len(list((output/'native').glob('session-*.json'))) == 4, 'first game native actors did not close before barrier')
            (output/'before').mkdir()
            (output/'before/000000-0.json').write_bytes(committed.read_bytes())
            atomic(output/'BOUNDARY.json', {'barrier': barrier, 'owned_stage_pid': current[0].pid, 'owned_group': os.getpgid(current[0].pid), 'signal_monotonic_ns': time.monotonic_ns()})
            os.killpg(current[0].pid, signal.SIGKILL)
            killed[0] = True

    def group_closed(label):
        pid = current[0].pid
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            groups.append({'stage': label, 'pid': pid, 'group_absent_after_reap': True})
        else:
            raise ValueError('owned recovery stage group survived reap')

    try:
        actual = footprint([ROOT, *map(Path, scope['external_paths'])])
        storage.check_admission(actual['charged_bytes'], shutil.disk_usage(ROOT).used, 0, scope['control_bytes']+scope['outside_control_bytes'], scope['reserve_bytes'])
        campaign = Campaign(output, {'schema': 'caissa-current-arena-recovery-owner-v1', 'scope_sha256': sha(path), 'engine_sha256': scope['engine_sha256'], 'network_sha256': scope['network_sha256'], 'match_games': 0}, scope['maximum_active_seconds'], absolute_deadline=scope['deadline_unix'], resource_guard=guard)
        atomic(output/'ACTIVE_USAGE.json', {'closed': False, 'active_seconds': 0, 'maximum_active_seconds': scope['maximum_active_seconds']})
        profile = json.loads((ROOT/'config/final-recovery-runtime-v1.json').read_text())
        options = {'EvalFile': scope['network'], **profile['options']}
        actors = {role: {'name': 'Caissa current recovery '+role, 'command': [scope['engine']], 'options': dict(options)} for role in ['candidate', 'opponent']}
        config = {'profile': 'recovery-diagnostic-v2', **actors, 'openings': str(ROOT/profile['openings']), **{k: profile[k] for k in ['pairs', 'nodes', 'max_plies', 'warmup_nodes']}}
        atomic(output/'INPUT.json', config)
        kwargs = {'maximum_output_bytes': 65536, 'cwd': ROOT, 'env': lease.environment(), 'pass_fds': (lease.stream.fileno(),)}
        try:
            campaign.run('interrupted', base+['interrupted'], 40, **kwargs)
        except StageFailure as error:
            require(killed[0] and error.record['exit'] == -9 and error.record['reason'] == 'nonzero-exit' and error.record['cleanup_warnings'] == [], 'actual current forced interruption differs')
        else:
            raise ValueError('current arena was not actually interrupted')
        group_closed('interrupted')
        atomic(output/'KILL.json', {'signal': 9, 'actual_exit': -9, 'owned_stage_pid': current[0].pid, 'reaped_monotonic_ns': time.monotonic_ns(), 'protected_game_sha256': sha(output/'before/000000-0.json')})
        (output/'partial-before').mkdir()
        for name, text in [('000000-0.pgn.tmp', '[Event "torn'), ('000000-1.json.tmp', '{"torn":')]:
            (output/'partial-before'/name).write_text(text)
            (output/'arena/games'/name).write_text(text)
        campaign.run('resumed', base+['resumed'], 40, **kwargs)
        group_closed('resumed')
        atomic(output/'GROUPS.json', groups)
        campaign.run('independent', base+['independent'], 30, **kwargs)
        group_closed('independent')
        atomic(output/'GROUPS.json', groups)
        result = json.loads((output/'independent/FINAL_RECOVERY.json').read_text())
        require(result['status'] == 'passed_current_arena_runtime_recovery' and result['native_starts'] == 12 and result['game_journals'] == 4 and result['full_acceptance'] is False, 'current recovery independent endpoint differs')
        atomic(output/'CURRENT_RECOVERY.json', result)
        campaign.close('passed-current-arena-component')
    except BaseException as error:
        if output.exists():
            atomic(output/'FAILED-final-recovery.json', {'reason': str(error), 'full_acceptance': False})
        if campaign is not None:
            campaign.close('failed', {'reason': str(error)})
        raise
    finally:
        subprocess.Popen = original_popen
        if campaign is not None:
            atomic(output/'ACTIVE_USAGE.json', {'closed': True, 'active_seconds': time.monotonic()-campaign.start, 'maximum_active_seconds': scope['maximum_active_seconds']})
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--stage', choices=['interrupted', 'resumed', 'independent'])
    args = parser.parse_args()
    if args.stage:
        bootstrap(args.scope.resolve(), args.stage)
    else:
        execute(args.scope.resolve())
