"""Replay original games, split lineages, and quarantine cross-split transpositions."""
import argparse,hashlib,json,math,sqlite3,time
from pathlib import Path
import chess
import numpy as np
from training.corpus import atomic_json,digest
from training.model import features

def verify_game(g):
    b=chess.Board();samples={s['ply']:s for s in g['positions']}
    if len(samples)!=len(g['positions']):raise ValueError('duplicate ply record')
    for ply,text in enumerate(g['moves']):
        if ply in samples and samples[ply]['fen']!=b.fen(en_passant='fen'):raise ValueError('sample does not match independent replay')
        m=chess.Move.from_uci(text)
        if m not in b.legal_moves:raise ValueError(f'illegal corpus move {text} at ply {ply}')
        b.push(m)
    reason=g['termination'];result=g['result']
    if not g['complete']:
        if result!='*' or reason!='ply-limit':raise ValueError('unfinished result provenance')
        return False
    legal_reason={'checkmate':b.is_checkmate(),'stalemate':b.is_stalemate(),'fivefold':b.is_fivefold_repetition(),'seventy-five-move':b.is_seventyfive_moves(),'proven-dead-material':b.is_insufficient_material(),'threefold-claim':b.is_repetition(3),'fifty-move-claim':b.halfmove_clock>=100 and bool(b.legal_moves)}
    if not legal_reason.get(reason,False):raise ValueError('incorrect terminal/draw claim '+reason)
    expected=('0-1' if b.turn else '1-0') if reason=='checkmate' else '1/2-1/2'
    if result!=expected:raise ValueError('result color inconsistent with replay')
    return True

def canonical(fen):
    b=chess.Board(fen);return ' '.join(b.fen(en_passant='legal').split()[:4])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('corpus',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    db=sqlite3.connect(a.output/'identities.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA cache_size=-131072')
    db.execute('CREATE TABLE positions (id BLOB PRIMARY KEY, split INTEGER, fen TEXT, outcome REAL, teacher REAL, game TEXT, family TEXT) WITHOUT ROWID')
    counts={'games':0,'completed_games':0,'unfinished_games':0,'raw_positions':0,'within_split_duplicates':0,'cross_split_conflicts':0};hist={'ply':{},'clock':{},'material':{},'outcome':{},'teacher':{}}
    source=hashlib.sha256();start=time.monotonic()
    for path in sorted(a.corpus.glob('*/*.json')):
        raw=path.read_bytes();source.update(hashlib.sha256(raw).digest());pair=json.loads(raw)
        for g in pair['games']:
            counts['games']+=1
            if not verify_game(g):counts['unfinished_games']+=1;continue
            counts['completed_games']+=1;family=hashlib.sha256(' '.join(g['moves'][:8]).encode()).hexdigest();bucket=int(family[:8],16)%10;split=1 if bucket==0 else 2 if bucket==1 else 0
            white={'1-0':1.,'0-1':0.,'1/2-1/2':.5}[g['result']];game=f"{g['pair']}:{g['reverse']}"
            for s in g['positions']:
                counts['raw_positions']+=1;identity=hashlib.sha256(canonical(s['fen']).encode()).digest()
                row=db.execute('SELECT split FROM positions WHERE id=?',(identity,)).fetchone()
                if row:
                    if row[0]==split:counts['within_split_duplicates']+=1
                    elif row[0]!=-1:db.execute('UPDATE positions SET split=-1 WHERE id=?',(identity,));counts['cross_split_conflicts']+=1
                    continue
                stm=s['fen'].split()[1];outcome=white if stm=='w' else 1-white;teacher=float(s['score_stm'])
                if not math.isfinite(teacher) or abs(teacher)>30000:raise ValueError('invalid original-teacher score')
                db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?)',(identity,split,s['fen'],outcome,teacher,game,family))
                for key,value in [('ply',s['ply']//10*10),('clock',int(s['fen'].split()[4])//10*10),('material',sum(c.isalpha() for c in s['fen'].split()[0])),('outcome',outcome),('teacher',max(-2000,min(2000,int(teacher//100*100))))]:
                    label=str(value);hist[key][label]=hist[key].get(label,0)+1
        if counts['games']%200==0:db.commit();print(json.dumps(counts),flush=True)
    db.commit();sizes={}
    for split,name in [(0,'train'),(1,'validation'),(2,'test')]:
        n=db.execute('SELECT count(*) FROM positions WHERE split=?',(split,)).fetchone()[0];sizes[name]=n
        if n==0:raise ValueError('empty required split '+name)
        x=np.lib.format.open_memmap(a.output/f'{name}-features.npy',mode='w+',dtype=np.uint16,shape=(n,2,32))
        y=np.lib.format.open_memmap(a.output/f'{name}-targets.npy',mode='w+',dtype=np.float32,shape=(n,2))
        with (a.output/f'{name}-identities.jsonl').open('w') as ids:
            for i,(identity,fen,outcome,teacher,game,family) in enumerate(db.execute('SELECT id,fen,outcome,teacher,game,family FROM positions WHERE split=? ORDER BY id',(split,))):
                x[i]=features(fen);y[i]=[outcome,teacher];ids.write(json.dumps({'id':identity.hex(),'game':game,'family':family})+'\n')
        x.flush();y.flush();del x,y
    counts['distinct_usable_positions']=sum(sizes.values());counts['quarantined_positions']=db.execute('SELECT count(*) FROM positions WHERE split=-1').fetchone()[0]
    manifest={'schema':'caissa-dataset-v1','corpus_config':json.loads((a.corpus/'CONFIG.json').read_text()),'corpus_content_sha256':source.hexdigest(),'counts':counts,'splits':sizes,'histograms':hist,'seconds':time.monotonic()-start,'files':{p.name:digest(p) for p in a.output.glob('*.npy')}}
    atomic_json(a.output/'DATASET.json',manifest);db.close();print(json.dumps({k:v for k,v in manifest.items() if k not in ['histograms','files']}))
if __name__=='__main__':main()
