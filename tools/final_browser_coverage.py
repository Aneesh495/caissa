"""Audit final browser source/native coverage without rerunning old samples."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time
import zipfile


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(path):
    start = time.monotonic();path = Path(path).resolve();scope = json.loads(path.read_text());root, output = Path(scope['root']), path.parent
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'] and not (output/'STARTED.json').exists(), 'one new browser coverage audit required')
    lease = (root/'runs/TIMED_STRENGTH.lock').open('r+');fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30));resource.setrlimit(resource.RLIMIT_CORE, (0, 0));resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    def stop(*_):raise TimeoutError('browser coverage audit deadline exhausted')
    signal.signal(signal.SIGALRM, stop);signal.setitimer(signal.ITIMER_REAL, min(30, scope['deadline_unix']-time.time()))
    source = '7e699e200d2cb89a87c4d1c21c784244a2f96481'
    allowed = [['git', 'ls-tree', '-r', '-l', '-z', source, '--', *scope['browser_source_names']], ['git', 'cat-file', '--batch']]
    commands, destinations = [], set()
    def audit(event, args):
        if event.startswith('socket.') or event in {'os.system', 'os.posix_spawn', 'os.exec', 'os.link', 'os.symlink'}:raise RuntimeError('browser audit prohibits network and raw actors')
        if event == 'subprocess.Popen':
            require(args[1] in allowed and args[1] not in commands, 'only two bounded read-only Git commands admitted');commands.append(args[1])
        if event == 'open':
            name, mode, flags = args
            if isinstance(mode, str) and any(c in mode for c in 'wax+') or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if isinstance(name, int):require(stat.S_ISFIFO(os.fstat(name).st_mode), 'only owned Git pipe descriptors admitted')
                else:
                    target = Path(name).absolute();require(target == target.resolve() and target.parent == output and target.suffix == '.json', 'browser audit write escaped');destinations.add(str(target));require(len(destinations) <= 8, 'browser audit output inventory exhausted')
    sys.addaudithook(audit)
    (output/'STARTED.json').write_text(json.dumps({'unix': time.time()})+'\n')
    def raw(name):
        require(name in scope['source_bindings'], 'unbound browser audit input')
        target = root/name;require(target.is_file() and not target.is_symlink() and target.stat().st_size <= 16*1024**2, 'browser audit input missing or excessive')
        value = target.read_bytes();require(hashlib.sha256(value).hexdigest() == scope['source_bindings'][name], 'browser audit input changed: '+name);return value
    def doc(name):return json.loads(raw(name))
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope['interpreter_sha256'], 'browser audit interpreter differs')
    raw('tools/final_browser_coverage.py')
    archive = 'work/final-browser-archive-1-2026-10-29/';base = archive+'raw/'
    closed, inspection = doc(archive+'CLOSED.json'), doc(archive+'RESULT.json')
    require(closed['closed'] is True and closed['owner_exit'] == 0 and closed['stderr_bytes'] == 0 and closed['scope_sha256'] == hashlib.sha256(raw(archive+'SCOPE.json')).hexdigest(), 'browser archive owner failed or scope differs')
    for channel in ['stdout', 'stderr']:require(hashlib.sha256(raw(archive+'owner.'+channel)).hexdigest() == closed[channel+'_sha256'], 'actual browser archive owner log differs')
    require(inspection['archive_sha256'] == 'd3804aafd849ca9afd2376f078d4d90bb60e5e2195e08b2f9f5385ff38a99f6e' and inspection['archive_bytes'] == 9678582, 'accepted original browser archive differs')
    for name, digest in inspection['raw_positive_sha256'].items():require(hashlib.sha256(raw(base+name)).hexdigest() == digest, 'original positive browser evidence differs')
    selected = subprocess.run(allowed[0], cwd=root, capture_output=True, check=True, timeout=5).stdout;require(len(selected) <= 262144, 'browser source tree metadata exceeds bound')
    originals = {}
    for entry in selected.split(b'\0'):
        if entry:
            fields, name = entry.split(b'\t', 1);mode, kind, identity, size = fields.split();require(kind == b'blob' and mode in {b'100644', b'100755'}, 'original browser source contains a link');originals[name.decode()] = (mode.decode(), identity.decode(), int(size))
    require(set(originals) == set(scope['browser_source_names']), 'original browser source footprint missing')
    payload = subprocess.run(allowed[1], cwd=root, input=''.join(identity+'\n' for mode, identity, size in originals.values()).encode(), capture_output=True, check=True, timeout=5).stdout;require(len(payload) <= 1024**2, 'browser source content exceeds bound')
    position, bindings = 0, {}
    for name, (mode, identity, size) in originals.items():
        end = payload.index(b'\n', position);require(payload[position:end].split() == [identity.encode(), b'blob', str(size).encode()], 'original browser Git object differs')
        before = end+1;after = before+size;require(payload[after:after+1] == b'\n', 'truncated browser source object');data = payload[before:after];position = after+1
        require(raw(name) == data and ('100755' if (root/name).stat().st_mode & 0o111 else '100644') == mode, 'current browser producer/reader source or mode changed')
        bindings[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'mode': mode}
    require(position == len(payload), 'browser source objects have trailing data')
    boundary = doc('results/final-core-runtime-join-2026-10-28/BOUNDARY.json')
    for name, digest in boundary['native_source_sha256'].items():require(hashlib.sha256(raw(name)).hexdigest() == digest and ('100755' if (root/name).stat().st_mode & 0o111 else '100644') == boundary['native_source_modes'][name], 'final native source/mode differs')
    config, browser, network = doc(base+'CONFIG.json'), doc(base+'BROWSER.json'), doc(base+'NETWORK.json')
    require(config['source_commit'] == source and config['engine_sha256'] == boundary['engine_sha256'] == hashlib.sha256(raw('runs/full-parallel-strength-v1/bin/caissa')).hexdigest() and config['network_sha256'] == boundary['network_sha256'] == hashlib.sha256(raw('runs/full-parallel-strength-v1/inputs/selected.cai')).hexdigest(), 'browser and final saved actor identities differ')
    independent = inspection['historical_independent_result'];require(independent['actual_exit'] == 0 and independent['observed']['contexts'] == 4 and independent['observed']['reconstructed_board_states'] == 44 and independent['observed']['native_lines'] == 84 and independent['observed']['final_source_reexecution_required'] is True, 'original independent browser result missing or reclassified')
    contexts, assets = [], []
    for mode in ['classical', 'neural']:
        for width in [1280, 390]:
            rows = [row for row in browser['records'] if row['mode'] == mode and row['width'] == width]
            require(len(rows) == 14, 'original browser context is incomplete')
            requests = [row for row in network if row['mode'] == mode and row['width'] == width and row['url'] == '/api/analyze']
            complete = [row for row in requests if row.get('transport_complete') is True and 'event: bestmove' in row.get('body', '')]
            require(complete, 'completed original native response missing')
            contexts.append({'mode': mode, 'width': width, 'steps': [row['name'] for row in rows], 'completed_native_responses': len(complete), 'native_response_sha256': [hashlib.sha256(row['body'].encode()).hexdigest() for row in complete], 'cancel_workers_after': next(row['health'] for row in rows if row['name'] == 'cancel-reaped'), 'navigation_workers_after': next(row['health'] for row in rows if row['name'] == 'navigation-reaped')})
            trace = root/(base+f'{mode}-{width}/trace.zip')
            with zipfile.ZipFile(trace) as z:
                entries = z.infolist();require(len(entries) <= 10000 and sum(e.file_size for e in entries) <= 128*1024**2, 'browser trace exceeds original bounded inventory')
                for entry in entries:
                    if not entry.filename.endswith('.network'):continue
                    require(entry.file_size <= 16*1024**2, 'trace network metadata exceeds cap')
                    for line in z.read(entry).splitlines():
                        row = json.loads(line)
                        if row.get('type') != 'resource-snapshot':continue
                        value = row['snapshot'];route = value['request']['url'].removeprefix('http://127.0.0.1:18771')
                        if route not in {'/', '/style.css', '/app.js'} or value['response']['status'] != 200:continue
                        content = value['response']['content'];member = 'resources/'+content['_sha1'] if content.get('_sha1') else None
                        data = z.read(member) if member and member in z.namelist() else None
                        target = {'/': 'web/index.html', '/style.css': 'web/style.css', '/app.js': 'dist/web/app.js'}[route]
                        if data is not None:require(data == raw(target), 'served browser asset differs from current retained file')
                        assets.append({'mode': mode, 'width': width, 'route': route, 'response_body_retained': data is not None, 'sha256': hashlib.sha256(data).hexdigest() if data is not None else None})
    missing = [row for row in assets if row['route'] == '/app.js' and not row['response_body_retained']]
    require(len(missing) == 8, 'compiled browser capture gap differs from inspected original')
    result = {'status': 'passed_browser_source_and_archive_coverage_audit_only', 'product_source_commit': scope['product_commit'], 'historical_source_commit': source, 'browser_source_files_and_modes': bindings, 'final_native_files_and_modes': len(boundary['native_source_sha256']), 'engine_sha256': boundary['engine_sha256'], 'network_sha256': boundary['network_sha256'], 'archive_sha256': inspection['archive_sha256'], 'original_independent_result': independent, 'contexts': contexts, 'assets': assets, 'compiled_script_response_bodies_missing': len(missing), 'retained_local_app_js_sha256': hashlib.sha256(raw('dist/web/app.js')).hexdigest(), 'old_final_source_reexecution_requirement_preserved': True, 'browser_executions': 0, 'native_starts': 0, 'closed_controls_or_semantic_samples_reexecuted': 0, 'remaining': ['Capture and independently bind the actual served compiled JavaScript/current service build and final native/browser flows under a new finite final acceptance scope. Existing source identity and component passes do not supply missing JavaScript response bytes.'], 'full_R10_complete': False, 'full_acceptance': False, 'elapsed_seconds': time.monotonic()-start}
    (output/'BROWSER_COVERAGE.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'contexts': 4, 'source_files': len(bindings), 'missing_app_js_bodies': len(missing), 'full_R10_complete': False, 'elapsed_seconds': result['elapsed_seconds']}))


if __name__ == '__main__':main(sys.argv[1])
