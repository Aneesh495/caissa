"""Retain a finished game when its color-reversed partner is interrupted."""
import argparse,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
from training.corpus import digest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    binary=a.output/'engine';shutil.copy2(a.engine,binary)
    config={'profile':'recovery-diagnostic','candidate':{'name':'Caissa A','command':[str(binary)],'options':{'Threads':1,'Hash':1}},'opponent':{'name':'Caissa B','command':[str(binary)],'options':{'Threads':1,'Hash':1}},'openings':'config/openings.json','pairs':2,'nodes':2000,'max_plies':512,'warmup_nodes':1}
    cfg=a.output/'config.json';cfg.write_text(json.dumps(config));campaign=a.output/'arena';cmd=[sys.executable,'-m','arena.run',str(cfg),str(campaign),'--workers','1']
    with (a.output/'interrupted.log').open('w') as log:
        process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);deadline=time.monotonic()+30
        while not list((campaign/'games').glob('*.json')):
            if process.poll() is not None:raise ValueError('arena ended before forced interruption')
            if time.monotonic()>deadline:os.killpg(process.pid,signal.SIGKILL);raise TimeoutError('arena produced no completed game')
            time.sleep(.005)
        saved={str(p.relative_to(campaign)):digest(p) for p in (campaign/'games').glob('*.json')};os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
    # Simulate the exact crash window between committed JSON and derived PGN.
    first=next((campaign/'games').glob('*.json'));first.with_suffix('.pgn').unlink(missing_ok=True)
    with (a.output/'resumed.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
    for relative,sha in saved.items():
        if digest(campaign/relative)!=sha:raise ValueError('completed game changed on arena resume')
    games=list((campaign/'games').glob('*.json'));pairs=list((campaign/'pairs').glob('*.json'))
    if len(games)!=4 or len(pairs)!=2 or any(not p.with_suffix('.pgn').exists() for p in games):raise ValueError('arena lost or duplicated games/PGNs')
    result={'status':'passed','forced_signal':'SIGKILL','completed_before':len(saved),'completed_after':len(games),'pairs_after':len(pairs),'completed_bytes_preserved':True,'missing_derived_pgn_repaired':True};(a.output/'RECOVERY.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
