"""Opening-pair cluster bootstrap. Never treats paired games as independent."""
import argparse,json,math
from pathlib import Path
import numpy as np

def elo(score):
    if score<=0:return '-infinity'
    if score>=1:return '+infinity'
    return 400*math.log10(score/(1-score))

def summarize(records,resamples=20000,seed=104729):
    pairs=[];clusters={};wins=draws=losses=unfinished=0;failures={}
    seen=set()
    for row in records:
        identity=row['pair']
        if identity in seen:raise ValueError('duplicate opening pair')
        seen.add(identity)
        if len(row['games'])!=2 or sorted(g['candidate_color'] for g in row['games'])!=['black','white']:raise ValueError('missing color-reversed game')
        scores=[]
        for game in row['games']:
            if game['result']=='*':unfinished+=1;continue
            result=game['result'];white=1. if result=='1-0' else 0. if result=='0-1' else .5 if result=='1/2-1/2' else None
            if white is None:raise ValueError('unrecognized result')
            score=white if game['candidate_color']=='white' else 1-white;scores.append(score)
            wins+=score==1;draws+=score==.5;losses+=score==0
            if game['termination'] in ['crash','illegal-move','time-loss','protocol-failure']:failures[game['termination']]=failures.get(game['termination'],0)+1
        if len(scores)==2:
            value=sum(scores)/2;pairs.append(value);clusters.setdefault(row['opening_id'],[]).append(value)
    if not pairs:raise ValueError('no complete opening pairs')
    values=np.array(pairs);units=np.array([[sum(v),len(v)] for v in clusters.values()],dtype=float);rng=np.random.default_rng(seed);means=np.empty(resamples)
    for offset in range(0,resamples,256):
        n=min(256,resamples-offset);indices=rng.integers(0,len(units),size=(n,len(units)));draws_by_cluster=units[indices].sum(axis=1);means[offset:offset+n]=draws_by_cluster[:,0]/draws_by_cluster[:,1]
    lo,hi=np.quantile(means,[.025,.975]);mean=float(values.mean())
    return {'schema':'caissa-strength-v1','complete_pairs':len(pairs),'independent_opening_clusters':len(units),'games':wins+draws+losses,'wins':int(wins),'draws':int(draws),'losses':int(losses),'unfinished_games':unfinished,'score':mean,'score_95':[float(lo),float(hi)],'elo_difference':elo(mean),'elo_95':[elo(float(lo)),elo(float(hi))],'bootstrap':{'unit':'opening family containing color-reversed pairs','resamples':resamples,'seed':seed},'failures':failures,'complete_sample':unfinished==0}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('campaign',type=Path);a=ap.parse_args();records=[json.loads(p.read_text()) for p in sorted(a.campaign.glob('pairs/*.json'))];result=summarize(records);result['profile']=json.loads((a.campaign/'CONFIG.json').read_text())['config'].get('profile','unclassified');print(json.dumps(result,indent=2));(a.campaign/'SUMMARY.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
