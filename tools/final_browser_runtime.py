"""One finite fresh served-build/browser/native acceptance owner."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import parallel_storage_quota as storage


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BrowserQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        require(path == path.resolve() and path.is_relative_to(self.output), 'browser writer escaped its scope')
        name = str(path.relative_to(self.output));canonical = name[:-4] if name.endswith('.tmp') else name
        root = {'WRITER.lock', 'CONFIG.json', 'COMMANDS.jsonl', 'PROGRESS.json', 'CAMPAIGN.json', 'ACTIVE_USAGE.json', 'RUNTIME_CONFIG.json', 'BUILD.json', 'BROWSER.json', 'NETWORK.json', 'ASSETS.json', 'ERRORS.json', 'service.log', 'build.log', 'build.json', 'capture.log', 'capture.json', 'independent.log', 'independent.json', 'FINAL_BROWSER.json', 'FAILED-final-browser.json', 'GROUPS.json', 'NATIVE_WRITER_USAGE.json'}
        product = re.fullmatch(r'product/(?:web/(?:index\.html|style\.css)|dist/(?:web/app|analysis-service/(?:native|server|telemetry))\.js(?:\.map)?)', canonical)
        screenshot = re.fullmatch(r'(?:classical|neural)-(?:1366|375)/(?:import|keyboard-edit|analysis|restored)\.png', canonical)
        independent = canonical in {'independent/FINAL_BROWSER.json', 'independent/CONTROLS.json'}
        require(canonical in root or product or screenshot or independent, 'unknown final browser writer destination: '+name)
        immutable = product or screenshot or canonical in {'BUILD.json', 'BROWSER.json', 'NETWORK.json', 'ASSETS.json', 'ERRORS.json', 'RUNTIME_CONFIG.json'}
        if immutable:require(not (self.output/canonical).exists(), 'committed final browser evidence is immutable')
        return 'control', ('FAILED-'+name if canonical.startswith('FAILED-') else name)


def load(path):
    scope = json.loads(Path(path).read_text())
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'], 'fresh browser scope is not live')
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and sha(scope['interpreter']) == scope['interpreter_sha256'], 'browser Python runtime differs')
    for name, expected in scope['source_bindings'].items():require(not Path(name).is_symlink() and sha(name) == expected, 'browser source/input/runtime changed: '+name)
    return scope


def execute(path):
    scope = load(path)
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint
    lease = HostLease(ROOT/'runs');output = Path(scope['output']);quota = BrowserQuota({**scope, 'scope_sha256': sha(path)});quota.create()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0));resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2));quota.install()
    campaign, active, groups = None, [None], []
    original_popen = subprocess.Popen
    allowed = [
        [scope['node'], '--require', scope['process_preload'], str(ROOT/'tools/final_browser_build.mjs'), str(path)],
        [scope['node'], '--require', scope['process_preload'], str(ROOT/'tools/final_browser_capture.mjs'), str(output)],
        [sys.executable, '-B', '-P', str(Path(__file__).resolve()), '--scope', str(path), '--independent'],
    ]
    launched = []
    def spawn(command, *args, **kwargs):
        require(command in allowed and command not in launched, 'only the three final browser stages are admitted')
        launched.append(command)
        ceiling = 1024**2 if command == allowed[0] else 4*1024**2
        kwargs['preexec_fn'] = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (ceiling, ceiling))
        process = original_popen(command, *args, **kwargs);active[0] = process
        require(os.getpgid(process.pid) == process.pid, 'browser stage does not own its process group')
        return process
    subprocess.Popen = spawn
    last_storage, native_peak = [0], [0]
    def guard(force=False):
        lease.check();state = quota.read();require(state.get('failure') is None, 'browser storage failure latched')
        temp = output/'native-tmp'
        usage = 0
        if temp.exists():
            usage = footprint([temp])['charged_bytes'];native_peak[0] = max(native_peak[0], usage)
            require(usage <= scope['native_temp_bytes'], 'owned Chromium temporary allowance exhausted')
        traces = [*output.glob('*-*/trace.zip'), output/'failed-trace.zip']
        trace_used = sum(p.stat().st_size for p in traces if p.exists())
        require(trace_used <= scope['native_trace_bytes'], 'prepaid trace allowance exhausted')
        compiler_root = output/'product/dist'
        compiler_used = footprint([compiler_root])['charged_bytes'] if compiler_root.exists() else 0
        require(compiler_used <= scope['compiler_writer_bytes'], 'prepaid compiler output exhausted')
        if force or time.monotonic()-last_storage[0] >= 10:
            actual = footprint([ROOT, *map(Path, scope['external_paths'])])
            remaining = scope['control_bytes']-state['control_used']+scope['outside_control_bytes']+max(0, scope['native_temp_bytes']-usage)+max(0, scope['native_trace_bytes']-trace_used)+max(0, scope['compiler_writer_bytes']-compiler_used)
            storage.check_admission(actual['charged_bytes'], shutil.disk_usage(ROOT).used, 0, remaining, scope['reserve_bytes'])
            last_storage[0] = time.monotonic()
    def reap(label):
        pid = active[0].pid
        try:os.killpg(pid, 0)
        except ProcessLookupError:groups.append({'stage': label, 'pid': pid, 'group_absent_after_reap': True})
        else:raise ValueError('final browser owned process group survived')
    def collect(label):
        raw = (output/(label+'.log')).read_text();total = 0
        for line in raw.splitlines():
            value = json.loads(line)
            if 'artifact' not in value:continue
            data = base64.b64decode(value['data'], validate=True);total += len(data)
            require(len(data) <= 2*1024**2 and total <= 5*1024**2, 'decoded browser artifact allowance exhausted')
            target = output/value['artifact'];quota.classify(target);target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
    try:
        guard(True)
        campaign = Campaign(output, {'schema': 'caissa-final-served-browser-owner-v1', 'scope_sha256': sha(path), 'source_commit': scope['product_commit'], 'engine_sha256': scope['engine_sha256'], 'network_sha256': scope['network_sha256'], 'match_games': 0}, scope['maximum_active_seconds'], absolute_deadline=scope['deadline_unix'], resource_guard=guard)
        atomic(output/'ACTIVE_USAGE.json', {'closed': False, 'active_seconds': 0, 'maximum_active_seconds': scope['maximum_active_seconds']})
        env = {**lease.environment(), 'CAISSA_FINAL_SCOPE': str(path), 'TMPDIR': str(output/'native-tmp'), 'TMP': str(output/'native-tmp'), 'TEMP': str(output/'native-tmp')}
        (output/'native-tmp').mkdir()
        campaign.run('build', allowed[0], 60, maximum_output_bytes=2*1024**2, cwd=ROOT, env={**env, 'CAISSA_FINAL_ROLE': 'build'}, pass_fds=(lease.stream.fileno(),));reap('build');collect('build')
        for name in ['index.html', 'style.css']:
            target = output/'product/web'/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes((ROOT/'web'/name).read_bytes())
        for mode in ['classical', 'neural']:
            for width in [1366, 375]:(output/f'{mode}-{width}').mkdir()
        atomic(output/'RUNTIME_CONFIG.json', {k: scope[k] for k in ['engine', 'network', 'playwright_module', 'process_preload', 'chromium']})
        campaign.run('capture', allowed[1], 280, maximum_output_bytes=8*1024**2, cwd=ROOT, env={**env, 'CAISSA_FINAL_ROLE': 'browser'}, pass_fds=(lease.stream.fileno(),));reap('capture');collect('capture')
        atomic(output/'GROUPS.json', groups);atomic(output/'NATIVE_WRITER_USAGE.json', {'native_temp_peak_bytes': native_peak[0], 'native_temp_allowance': scope['native_temp_bytes'], 'trace_bytes': sum(p.stat().st_size for p in output.glob('*-*/trace.zip')), 'trace_allowance': scope['native_trace_bytes']})
        campaign.run('independent', allowed[2], 60, maximum_output_bytes=65536, cwd=ROOT, env=env, pass_fds=(lease.stream.fileno(),));reap('independent')
        atomic(output/'GROUPS.json', groups)
        result = json.loads((output/'independent/FINAL_BROWSER.json').read_text());require(result['full_R10_complete'] is True and result['full_acceptance'] is False, 'final browser reader did not accept its declared scope')
        atomic(output/'FINAL_BROWSER.json', result);campaign.close('passed-final-browser-domain')
    except BaseException as error:
        if output.exists():atomic(output/'FAILED-final-browser.json', {'reason': str(error), 'full_acceptance': False})
        if campaign is not None:campaign.close('failed', {'reason': str(error)})
        raise
    finally:
        subprocess.Popen = original_popen
        if campaign is not None:atomic(output/'ACTIVE_USAGE.json', {'closed': True, 'active_seconds': time.monotonic()-campaign.start, 'maximum_active_seconds': scope['maximum_active_seconds']})
        quota.uninstall();quota.update(lambda state: state.update(closed=True));lease.close()


def independent(path):
    scope = load(path)
    from tools.host_lease import inherited
    from tools.campaign_process import atomic
    require(inherited(ROOT/'runs/TIMED_STRENGTH.lock'), 'final browser reader lacks inherited host lease')
    quota = BrowserQuota({**scope, 'scope_sha256': sha(path)});quota.install()
    subprocess.Popen = lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError('final browser reader admits no subprocess'))
    from verification.final_browser import verify
    result, controls = verify(Path(scope['output']), {**scope, 'scope_sha256': sha(path)})
    (Path(scope['output'])/'independent').mkdir()
    atomic(Path(scope['output'])/'independent/FINAL_BROWSER.json', result);atomic(Path(scope['output'])/'independent/CONTROLS.json', controls)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--scope', type=Path, required=True);parser.add_argument('--independent', action='store_true');args = parser.parse_args()
    independent(args.scope.resolve()) if args.independent else execute(args.scope.resolve())
