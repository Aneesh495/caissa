"""Bounded UCI adversary with independent legality and raw latency records."""
import argparse,json,queue,random,subprocess,threading,time,hashlib,statistics
from pathlib import Path
import chess

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');ap.add_argument('--sequences',type=int,default=10000);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if not 1<=a.sequences<=100000:ap.error('sequence count outside bounds')
    a.output.mkdir(parents=True,exist_ok=False);rng=random.Random(32452843);lines=queue.Queue(maxsize=100000)
    p=subprocess.Popen([a.engine],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    def reader():
        for line in p.stdout:lines.put(line.rstrip('\n'))
        lines.put(None)
    threading.Thread(target=reader,daemon=True).start();latencies=[];total_start=time.monotonic()
    with (a.output/'transcript.jsonl').open('w') as log:
        def send(text):
            log.write(json.dumps({'send':text,'ns':time.monotonic_ns()})+'\n');p.stdin.write(text+'\n');p.stdin.flush()
        def until(prefix,timeout=5):
            deadline=time.monotonic()+timeout;captured=[]
            while True:
                line=lines.get(timeout=max(.001,deadline-time.monotonic()))
                if line is None:raise RuntimeError('unexpected engine EOF')
                log.write(json.dumps({'receive':line,'ns':time.monotonic_ns()})+'\n');captured.append(line)
                if line.startswith(prefix):return captured
                if time.monotonic()>deadline:raise TimeoutError(prefix)
        try:
            send('uci');until('uciok');send('setoption name Hash value 1');send('isready');until('readyok')
            board=chess.Board()
            for i in range(a.sequences):
                if i%71==0:board=chess.Board()
                if i%127==0:
                    send('setoption name Hash value 2');send('setoption name Hash value 1')
                if i%113==0:send('setoption name Threads value '+str(rng.choice([1,2,4,8])))
                if i%23==0:
                    for bad in ['setoption name Absent value true','go nodes -1','position fen garbage','setoption name Threads value 99','go movetime 999999999999999999999999999','position startpos moves a1a8']:
                        send(bad)
                send('position fen '+board.fen(en_passant='fen'));send('isready');until('readyok')
                send(rng.choice(['go infinite','go nodes 200','go movetime 50','go depth 5']))
                if i%3==0:time.sleep(.0005)
                start=time.monotonic_ns();send('stop');responses=until('bestmove');elapsed=(time.monotonic_ns()-start)/1e6;latencies.append(elapsed)
                for line in responses:
                    if line.startswith('info ') and ' pv ' in line:
                        replay=board.copy()
                        for word in line.split(' pv ',1)[1].split():
                            m=chess.Move.from_uci(word)
                            if m not in replay.legal_moves:raise RuntimeError('illegal PV: '+line)
                            replay.push(m)
                best=responses[-1].split()[1]
                if board.is_game_over(claim_draw=False):
                    # Native conservative dead detection may finish before the oracle.
                    if best!='0000' and chess.Move.from_uci(best) not in board.legal_moves:raise RuntimeError('terminal bestmove illegal')
                    board=chess.Board()
                else:
                    if best=='0000':raise RuntimeError('null bestmove in playable position')
                    m=chess.Move.from_uci(best)
                    if m not in board.legal_moves:raise RuntimeError('illegal bestmove '+best)
                    legal=list(board.legal_moves);board.push(rng.choice(legal))
                if (i+1)%1000==0:print(f'{i+1} sequences complete',flush=True)
            send('position startpos')
            for _ in range(100):
                send('go ponder depth 1');send('ponderhit');until('bestmove',timeout=1)
            send('X'*9000);send('isready');until('readyok');send('quit');p.wait(timeout=5)
        finally:
            if p.poll() is None:p.kill();p.wait()
    ordered=sorted(latencies);p99=ordered[min(len(ordered)-1,int(len(ordered)*.99))]
    result={'requested':a.sequences,'completed':len(latencies),'stop_ms':{'p50':statistics.median(latencies),'p95':ordered[int(len(ordered)*.95)],'p99':p99,'max':max(latencies)},'status':'passed' if p99<50 else 'failed','seconds':time.monotonic()-total_start,'engine_sha256':hashlib.sha256(Path(a.engine).read_bytes()).hexdigest()}
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return result['status']!='passed'
if __name__=='__main__':raise SystemExit(main())
