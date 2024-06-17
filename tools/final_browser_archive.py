"""Retain one exact existing browser archive's positive raw evidence locally."""

import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(path):
    os.umask(0o077)
    started = time.monotonic()
    path = Path(path).resolve();scope = json.loads(path.read_text())
    root, output = Path(scope['root']), path.parent
    require(scope['status'] == 'admitted' and time.time() < scope['deadline_unix'] and not (output/'STARTED.json').exists(), 'one fresh browser archive inspection required')
    lease = (root/'runs/TIMED_STRENGTH.lock').open('r+')
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90));resource.setrlimit(resource.RLIMIT_CORE, (0, 0));resource.setrlimit(resource.RLIMIT_FSIZE, (16*1024**2, 16*1024**2))
    def stop(*_):
        raise TimeoutError('browser archive inspection deadline exhausted')
    signal.signal(signal.SIGALRM, stop);signal.setitimer(signal.ITIMER_REAL, min(180, scope['deadline_unix']-time.time()))
    command = ['gh', 'api', 'repos/Aneesh495/caissa/actions/artifacts/12698952186/zip']
    commands, destinations, raw_budget = [], set(), [0]
    def audit(event, args):
        if event.startswith('socket.') or event in {'os.system', 'os.posix_spawn', 'os.exec', 'os.link', 'os.symlink'}:
            raise RuntimeError('only the exact owned browser archive fetch is admitted')
        if event == 'subprocess.Popen':
            require(args[1] == command and not commands, 'only one pinned browser archive fetch admitted');commands.append(command)
        if event == 'open':
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in 'wax+') or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                if isinstance(name, int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), 'only owned archive pipe descriptors admitted')
                else:
                    target = Path(name).absolute()
                    require(target == target.resolve() and target.is_relative_to(output), 'browser archive output escaped namespace')
                    require(target.parent == output and target.suffix == '.json' or target.is_relative_to(output/'raw'), 'unknown browser archive destination')
                    require(str(target) not in destinations and not target.exists(), 'browser archive outputs are immutable')
                    destinations.add(str(target));require(len(destinations) <= 64, 'browser archive file inventory exhausted')
    sys.addaudithook(audit)
    (output/'STARTED.json').write_text(json.dumps({'unix': time.time()})+'\n')
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope['interpreter_sha256'], 'browser archive interpreter differs')
    for name, digest in scope['source_bindings'].items():
        require(not (root/name).is_symlink() and hashlib.sha256((root/name).read_bytes()).hexdigest() == digest, 'browser archive input differs: '+name)
    expected = scope['artifact']
    require(expected['id'] == 12698952186 and expected['bytes'] == 9678582 and expected['sha256'] == 'd3804aafd849ca9afd2376f078d4d90bb60e5e2195e08b2f9f5385ff38a99f6e', 'browser archive pin changed')
    buffer, digest, size = io.BytesIO(), hashlib.sha256(), 0
    env = dict(os.environ, GH_NO_UPDATE_NOTIFIER='1', GH_NO_EXTENSION_UPDATE_NOTIFIER='1', GH_PROMPT_DISABLED='1')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    error_digest, error_count = hashlib.sha256(), [0]
    def drain():
        while block := process.stderr.read(16384):error_digest.update(block);error_count[0] += len(block)
    reader = threading.Thread(target=drain, daemon=True);reader.start()
    try:
        while block := process.stdout.read(65536):
            size += len(block);require(size <= expected['bytes'] <= 16*1024**2, 'browser archive compressed byte ceiling exhausted')
            digest.update(block);buffer.write(block)
        require(process.wait(timeout=10) == 0 and size == expected['bytes'] and digest.hexdigest() == expected['sha256'], 'browser archive actual transport/digest differs')
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(process.pid, signal.SIGKILL);process.wait(timeout=2)
        reader.join(timeout=2);require(not reader.is_alive(), 'browser archive stderr pipe survived')
        process.stdout.close();process.stderr.close()
        (output/'TRANSPORT.json').write_text(json.dumps({'exit': process.returncode, 'stderr_bytes': error_count[0], 'stderr_sha256': error_digest.hexdigest()})+'\n')
    require(error_count[0] == 0, 'browser archive transport emitted unexpected stderr')
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        entries = archive.infolist();names = [e.filename for e in entries]
        require(0 < len(entries) <= 10000 and len(set(names)) == len(names), 'browser archive entry inventory differs')
        require(all(not e.filename.startswith('/') and '..' not in Path(e.filename).parts and not stat.S_ISLNK(e.external_attr >> 16) and not e.flag_bits & 1 for e in entries), 'unsafe browser archive member')
        def selected(suffix):
            found = [e for e in entries if e.filename.endswith(suffix)]
            require(len(found) == 1 and found[0].file_size <= 1024**2, 'compact browser result missing or ambiguous: '+suffix)
            return json.loads(archive.read(found[0]))
        controls = selected('component/CONTROLS.json')
        require(controls['status'] == 'passed' and controls['full_G12_certified'] is False and len(controls['controls']) == 17, 'actual old browser control inventory differs')
        positive = next(c for c in controls['controls'] if c['case'] == 'real-browser-reconstruction')
        require(positive['actual_exit'] == 0 and positive['observed']['component_pass'] is True and positive['observed']['contexts'] == 4, 'actual independent browser result differs')
        found = [e for e in entries if e.filename.endswith('component/positive/CONFIG.json')]
        require(len(found) == 1, 'positive original browser prefix missing or ambiguous')
        prefix = found[0].filename[:-len('CONFIG.json')]
        members = [e for e in entries if e.filename.startswith(prefix) and not e.is_dir()]
        require(0 < len(members) <= 40 and sum(e.file_size for e in members) <= 28*1024**2, 'original positive browser evidence exceeds prepaid local ceiling')
        pins = {};raw_root = output/'raw';raw_root.mkdir()
        for entry in members:
            name = entry.filename[len(prefix):]
            require(name and entry.file_size <= 16*1024**2, 'positive browser member exceeds file bound')
            target = raw_root/name;target.parent.mkdir(parents=True, exist_ok=True)
            raw = archive.read(entry);require(len(raw) == entry.file_size, 'positive browser member length differs')
            raw_budget[0] += max(len(raw), 4096)+4096
            require(raw_budget[0] <= 32*1024**2, 'positive browser physical reservation exhausted')
            target.write_bytes(raw);pins[name] = hashlib.sha256(raw).hexdigest()
        manifest = json.loads((raw_root/'MANIFEST.json').read_text())
        require(manifest['files'] == {name: sha for name, sha in pins.items() if name != 'MANIFEST.json'}, 'original positive raw manifest differs')
        original_config = json.loads((raw_root/'CONFIG.json').read_text())
        require(original_config['source_commit'] == '7e699e200d2cb89a87c4d1c21c784244a2f96481' and original_config['engine_sha256'] == '1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897' and original_config['network_sha256'] == '52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7', 'original positive browser source/actor differs')
        (output/'ORIGINAL_CONTROLS.json').write_text(json.dumps(controls, indent=2)+'\n')
        result = {'status': 'passed_pinned_browser_archive_inspection', 'artifact_id': expected['id'], 'archive_bytes': size, 'archive_sha256': digest.hexdigest(), 'archive_staged_on_filesystem': False, 'raw_positive_files': len(pins), 'raw_positive_sha256': pins, 'raw_reserved_bytes': raw_budget[0], 'historical_independent_result': positive, 'browser_executions': 0, 'native_starts': 0, 'old_controls_reexecuted': 0, 'full_R10_complete': False, 'full_acceptance': False, 'elapsed_seconds': time.monotonic()-started}
        (output/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({k: result[k] for k in ['status', 'archive_bytes', 'raw_positive_files', 'browser_executions', 'native_starts', 'full_R10_complete', 'elapsed_seconds']}))
    buffer.close()


if __name__ == '__main__':main(sys.argv[1])
