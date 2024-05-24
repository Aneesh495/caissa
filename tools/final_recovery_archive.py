"""Inspect one pinned existing recovery ZIP in bounded memory, retaining metadata."""

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
    start = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    root, output = Path(scope["root"]), path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite archive inspection required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))

    def stop(*_):
        raise TimeoutError("pinned recovery archive inspection deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(180, scope["deadline_unix"]-time.time()))
    command = ["gh", "api", "repos/Aneesh495/caissa/actions/artifacts/12657018104/zip"]
    commands, destinations = [], set()

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink"}:
            raise RuntimeError("only the pinned owned GitHub download pipe admitted")
        if event == "subprocess.Popen":
            require(args[1] == command and not commands, "only one pinned archive fetch admitted")
            commands.append(command)
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode,str) and any(c in mode for c in "wax+")) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if writing:
                if isinstance(name,int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "only owned pipe descriptors admitted")
                else:
                    p = Path(name).absolute()
                    require(p == p.resolve() and p.parent == output and p.suffix == '.json', "archive inspection write escaped metadata namespace")
                    destinations.add(str(p))
                    require(len(destinations) <= 12, "metadata file inventory exhausted")

    sys.addaudithook(audit)
    (output/'STARTED.json').write_text(json.dumps({'unix':time.time()})+'\n')
    require(str(Path(sys.executable).resolve()) == scope['interpreter'] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope['interpreter_sha256'], 'archive interpreter differs')
    for name,sha in scope['source_bindings'].items():
        require(not (root/name).is_symlink() and hashlib.sha256((root/name).read_bytes()).hexdigest() == sha, 'archive input binding differs: '+name)
    expected = scope['artifact']
    require(expected['id'] == 12657018104 and expected['bytes'] == 297027567 and expected['sha256'] == '7c8fa076cc3b759ccda1f065653a6b74e0277795ca20852fc49f3ffe84b087fa', 'original archive pin changed')
    buffer, digest, size = io.BytesIO(), hashlib.sha256(), 0
    environment = dict(os.environ, GH_NO_UPDATE_NOTIFIER='1', GH_NO_EXTENSION_UPDATE_NOTIFIER='1', GH_PROMPT_DISABLED='1')
    stderr_digest, stderr_prefix, stderr_size = hashlib.sha256(), bytearray(), [0]
    def drain_stderr():
        while block := process.stderr.read(16384):
            stderr_digest.update(block)
            stderr_size[0] += len(block)
            if len(stderr_prefix) < 65536:
                stderr_prefix.extend(block[:65536-len(stderr_prefix)])

    process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment,start_new_session=True)
    stderr_reader = threading.Thread(target=drain_stderr, daemon=True)
    stderr_reader.start()
    try:
        while block := process.stdout.read(65536):
            size += len(block)
            require(size <= expected['bytes'] <= scope['maximum_archive_memory_bytes'], 'bounded in-memory ZIP ceiling exceeded')
            digest.update(block); buffer.write(block)
        require(process.wait(timeout=10)==0 and size==expected['bytes'] and digest.hexdigest()==expected['sha256'], 'original archive transport/length/digest differs')
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        stderr_reader.join(timeout=2)
        require(not stderr_reader.is_alive(), 'owned archive stderr pipe did not close')
        process.stdout.close()
        process.stderr.close()
        (output/'TRANSPORT.json').write_text(json.dumps({'exit':process.returncode,'stderr_bytes':stderr_size[0],'stderr_sha256':stderr_digest.hexdigest(),'stderr_retained_prefix':stderr_prefix.decode('utf-8', errors='replace'),'stderr_prefix_limit_bytes':65536},indent=2)+'\n')
    require(stderr_size[0] == 0, 'original archive transport emitted unexpected stderr; private receipt retained')
    buffer.seek(0)
    retained = {}
    with zipfile.ZipFile(buffer) as archive:
        entries=archive.infolist();names=[e.filename for e in entries]
        require(0<len(entries)<=100000 and len(names)==len(set(names)), 'ZIP central inventory duplicated or excessive')
        for e in entries:
            require(not e.filename.startswith('/') and '..' not in Path(e.filename).parts and not stat.S_ISLNK(e.external_attr >> 16), 'unsafe archive member')
        def selected(suffix):
            found=[e for e in entries if e.filename.endswith(suffix)]
            require(len(found)==1 and 0<found[0].file_size<=262144 and not found[0].flag_bits&1, 'compact recovery reader result missing, ambiguous or excessive: '+suffix)
            raw=archive.read(found[0]);require(len(raw)==found[0].file_size,'selected metadata length differs')
            retained[suffix]={'archive_path':found[0].filename,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
            return json.loads(raw)
        full=selected('positive-full-entry-RESULT.json')
        require(full['exit']==2 and full['stderr']=='' and full['observed']['full_acceptance'] is False,'original full-entry actual exit or stderr differs')
        g11=full['observed']['verified_semantic_gates']['G11']
        require(g11['status']=='passed' and g11['gate']=='G11' and g11['full_G11_saved_image_sample'] is True and g11['source_commit']=='6a63aaaa507646c87ef54b7aab1bea2b71eec1ea','actual independent full-G11 result differs')
        require(g11['new_acquisition'] is False and g11['new_training'] is False and g11['new_strength_games']==0,'historical component scope differs')
        controls=selected('JOIN_CONTROLS.json');require(len(controls)==9,'original source/full-entry control count differs')
        (output/'ORIGINAL_G11.json').write_text(json.dumps(g11,indent=2)+'\n')
        (output/'ORIGINAL_CONTROLS.json').write_text(json.dumps(controls,indent=2)+'\n')
        (output/'ORIGINAL_FULL_ENTRY.json').write_text(json.dumps({'actual_exit':full['exit'],'stderr':full['stderr'],'full_acceptance':False,'pending_semantic_gates':full['observed']['pending_semantic_gates'],'full_entry_artifact_sha256':retained['positive-full-entry-RESULT.json']['sha256']},indent=2)+'\n')
    buffer.close()
    result={'status':'passed_pinned_historical_independent_recovery_inspection','artifact_id':expected['id'],'archive_bytes_verified':size,'archive_sha256':digest.hexdigest(),'archive_staged_on_filesystem':False,'retained_metadata':retained,'original_G11_sha256':hashlib.sha256((output/'ORIGINAL_G11.json').read_bytes()).hexdigest(),'original_G11_saved_image_sample':True,'old_samples_reexecuted':False,'new_native_starts':0,'games':0,'full_R09_complete':False,'full_acceptance':False,'elapsed_seconds':time.monotonic()-start}
    (output/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main(sys.argv[1])
