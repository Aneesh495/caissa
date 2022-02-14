"""Cross-language feature/inference checks using held-out reachable probes."""
import argparse,hashlib,json,random,subprocess,time
from pathlib import Path
import chess
import numpy as np
import torch
from training.model import CaissaNet,features,integer_reference,export_network

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');ap.add_argument('--network',type=Path,required=True);ap.add_argument('--checkpoint',type=Path);ap.add_argument('--untrained-seed',type=int);ap.add_argument('--probes',type=int,default=100000);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if not 1<=a.probes<=1000000:ap.error('probe count out of bounds')
    a.output.mkdir(parents=True,exist_ok=False);torch.set_num_threads(2)
    if a.checkpoint:
        state=torch.load(a.checkpoint,map_location='cpu',weights_only=False);model=CaissaNet(version=2 if state["config"].get("network_contract","").startswith("v2") else 1);model.load_state_dict(state['model'])
    elif a.untrained_seed is not None:torch.manual_seed(a.untrained_seed);model=CaissaNet(version=int.from_bytes(a.network.read_bytes()[8:12],"little"))
    else:ap.error('provide saved checkpoint or explicitly labeled untrained seed')
    model.eval();rng=random.Random(67867967);b=chess.Board();fens=[]
    for i in range(a.probes):
        if b.is_game_over() or b.ply()>240 or rng.random()<.01:b=chess.Board()
        fens.append(b.fen(en_passant='fen'));moves=list(b.legal_moves)
        if moves:b.push(rng.choice(moves))
    p=subprocess.Popen([a.engine,'--net-probe',str(a.network)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    errors=[];start=time.monotonic()
    try:
        with (a.output/'probes.jsonl').open('w') as log,torch.inference_mode():
            for offset in range(0,len(fens),512):
                batch=fens[offset:offset+512];x=np.stack([features(fen) for fen in batch]);expected=integer_reference(a.network,x);floating=model(torch.from_numpy(x)).numpy()*400
                for fen,integer,flt in zip(batch,expected,floating):
                    p.stdin.write(fen+'\n');p.stdin.flush();line=p.stdout.readline()
                    if not line:raise RuntimeError('native probe terminated')
                    native=json.loads(line)
                    if native['scalar']!=int(integer) or native['native']!=int(integer):raise ValueError('native/reference inference mismatch')
                    error=abs(float(flt)-int(integer));errors.append(error)
                    log.write(json.dumps({'fen':fen,'scalar':native['scalar'],'native':native['native'],'reference':int(integer),'float':float(flt),'error_cp':error})+'\n')
                if offset%10240==0:print(f'{offset+len(batch)} probes complete',flush=True)
    finally:
        p.stdin.close();p.wait(timeout=5)
    e=np.array(errors);summary={'status':'parity-passed-error-bound-not-yet-frozen','probes':len(errors),'float_quantized_cp':{'mean':float(e.mean()),'p99':float(np.quantile(e,.99)),'max':float(e.max())},'seconds':time.monotonic()-start,'network_sha256':hashlib.sha256(a.network.read_bytes()).hexdigest(),'trained':a.checkpoint is not None,'probes_sha256':hashlib.sha256((a.output/'probes.jsonl').read_bytes()).hexdigest()}
    (a.output/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
