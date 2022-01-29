"""Atomic paired selfplay journal with immutable configuration and restart checks."""
import argparse,concurrent.futures,hashlib,json,os,signal,subprocess,time
from pathlib import Path
SCHEMA='caissa-selfplay-v1'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def atomic_json(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:
        json.dump(value,f,separators=(',',':'));f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.replace(path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def run_pair(engine,root,pair,nodes,seed,timeout):
    folder=root/f'{pair//256:06d}';folder.mkdir(exist_ok=True)
    path=folder/f'{pair:09d}.json';pair_seed=(seed+pair*6364136223846793005)&((1<<64)-1)
    command=[engine,'--selfplay-pair',str(pair),str(pair_seed),str(nodes),str(16+(pair%9)*2)]
    start=time.monotonic();result=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError(f'pair {pair} failed: {result.stderr[-1000:]}')
    games=[json.loads(l) for l in result.stdout.splitlines()]
    if len(games)!=2 or [g['reverse'] for g in games]!=[0,1] or any(g['pair']!=pair for g in games):raise ValueError('paired output identity')
    for g in games:
        if g['complete']!=(g['result']!='*'):raise ValueError('completion/result disagreement')
        if not g['moves'] or not g['positions']:raise ValueError('empty useful work')
    item={'schema':SCHEMA,'pair':pair,'command':command,'exit':result.returncode,'seconds':time.monotonic()-start,'games':games}
    atomic_json(path,item);return pair,sum(g['complete'] for g in games),sum(len(g['positions']) for g in games)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--pairs',type=int,default=100);ap.add_argument('--nodes',type=int,default=500);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--seed',type=int,default=271828);ap.add_argument('--timeout',type=int,default=120);a=ap.parse_args()
    if not 1<=a.workers<=8 or not 1<=a.pairs<=500000:ap.error('resource bounds exceeded')
    a.output.mkdir(parents=True,exist_ok=True);engine=str(Path(a.engine).resolve());config={'schema':SCHEMA,'engine_sha256':digest(engine),'seed':a.seed,'nodes':a.nodes,'requested_pairs':a.pairs,'max_plies':512,'opening_policy':'random-16-to-32-plies; near-best-30cp-first-12-v1','outcome_perspective':'white','search_score_perspective':'side-to-move'}
    cfg=a.output/'CONFIG.json'
    if cfg.exists():
        if json.loads(cfg.read_text())!=config:raise ValueError('resume configuration or executable identity changed')
    else:atomic_json(cfg,config)
    done=set();completed=0;samples=0
    for path in sorted(a.output.glob('*/*.json')):
        record=json.loads(path.read_text());pair=record['pair']
        if record['schema']!=SCHEMA or pair in done or not 0<=pair<a.pairs or len(record['games'])!=2:raise ValueError('invalid completed pair journal')
        done.add(pair);completed+=sum(g['complete'] for g in record['games']);samples+=sum(len(g['positions']) for g in record['games'])
    start=time.monotonic();pending=iter(i for i in range(a.pairs) if i not in done)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        running={}
        def submit():
            pair=next(pending,None)
            if pair is not None:running[pool.submit(run_pair,engine,a.output,pair,a.nodes,a.seed,a.timeout)]=pair
        for _ in range(a.workers):submit()
        while running:
            finished,_=concurrent.futures.wait(running,return_when=concurrent.futures.FIRST_COMPLETED)
            for future in finished:
                running.pop(future);pair,complete,positions=future.result();done.add(pair);completed+=complete;samples+=positions;submit()
            if len(done)%25==0 or not running:
                summary={'status':'diagnostic' if len(done)<50000 else 'data-generated-unverified','pairs':len(done),'completed_games':completed,'positions_before_dedup':samples,'seconds_this_session':time.monotonic()-start,'workers':a.workers}
                atomic_json(a.output/'PROGRESS.json',summary);print(json.dumps(summary),flush=True)
    atomic_json(a.output/'SUMMARY.json',{'pairs':len(done),'completed_games':completed,'positions_before_dedup':samples,'config':config,'seconds_this_session':time.monotonic()-start})
if __name__=='__main__':main()
