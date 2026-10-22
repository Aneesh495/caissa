"""Choose a saved seed using validation only; retain every seed and checkpoint."""
import argparse,json,math,shutil
from pathlib import Path
import torch
from training.corpus import atomic_json,digest
from training.model import CaissaNet,export_network,state_hash

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',nargs='+',type=Path,required=True);ap.add_argument('--dataset',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--require-full',action='store_true');a=ap.parse_args()
    if not 3<=len(a.runs)<=10:ap.error('three to ten independently seeded runs required')
    manifest=json.loads((a.dataset/'DATASET.json').read_text());dataset_sha=digest(a.dataset/'DATASET.json')
    full=manifest['splits']['train']>=10000000 and manifest['counts']['completed_games']>=100000 and manifest.get('functional_deduplication',False)
    if a.require_full and not full:raise ValueError('full unique-training/game/functional-split requirements are not met')
    seeds=set();reference=None;rows=[]
    for folder in a.runs:
        summary=json.loads((folder/'SUMMARY.json').read_text());config=json.loads((folder/'CONFIG.json').read_text());seed=config['seed']
        if seed in seeds:raise ValueError('training seeds are not independent identities')
        seeds.add(seed)
        if config['dataset_sha256']!=dataset_sha:raise ValueError('seed used different dataset bytes')
        numerical={key:value for key,value in config.items() if key!='seed'}
        if reference is None:reference=numerical
        elif reference!=numerical:raise ValueError('seed runs have different training budgets or numerical contracts')
        state=torch.load(folder/'best.pt',map_location='cpu',weights_only=False);last=torch.load(folder/'last.pt',map_location='cpu',weights_only=False)
        if last['step']!=config['steps'] or last['updates']!=config['steps']:raise ValueError('a seed did not complete its declared real updates')
        if not math.isfinite(summary['best_validation']) or state['best_validation']!=summary['best_validation']:raise ValueError('invalid selected validation loss')
        if summary.get('test_accessed') is not False:raise ValueError('test selection policy violated')
        model=CaissaNet(version=2 if config.get('network_contract','').startswith('v2') else 1,width=config.get('width',64));model.load_state_dict(state['model'],strict=True)
        if any(not torch.isfinite(p).all() for p in model.parameters()):raise ValueError('nonfinite trained parameters')
        if state_hash(model)!=state['current_hash'] or state['current_hash']==state['initial_hash']:raise ValueError('checkpoint parameter change proof differs')
        if a.require_full and not summary['improved']:raise ValueError('seed did not improve over random initialization')
        rows.append({'seed':seed,'folder':str(folder),'validation_loss':summary['best_validation'],'untrained_validation':summary['untrained_validation'],'checkpoint_sha256':digest(folder/'best.pt'),'step':state['step'],'completed_updates':last['updates']})
    selected=min(rows,key=lambda item:(item['validation_loss'],item['seed']));a.output.mkdir(parents=True,exist_ok=False)
    checkpoint=Path(selected['folder'])/'best.pt';saved=torch.load(checkpoint,map_location='cpu',weights_only=False);config=saved['config']
    model=CaissaNet(version=2 if config.get('network_contract','').startswith('v2') else 1,width=config.get('width',64));model.load_state_dict(saved['model'])
    exported=export_network(model,a.output/'selected.cai',digest(checkpoint));shutil.copy2(checkpoint,a.output/'selected.pt')
    record={'profile':'full-data-selection-unverified' if full else 'diagnostic','criterion':'lowest saved validation loss; seed breaks exact ties','test_accessed':False,'dataset_sha256':dataset_sha,'training_positions':manifest['splits']['train'],'all_seeds':rows,'selected':selected,'network':exported}
    atomic_json(a.output/'SELECTION.json',record);print(json.dumps(record))
if __name__=='__main__':main()
