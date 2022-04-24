"""Replay, lineage splitting, functional-input deduplication and held-out screening."""
import argparse,hashlib,json,math,sqlite3,time
from pathlib import Path
import chess
import numpy as np
from training.corpus import atomic_json,digest
from training.features import features,input_identity

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
    ap=argparse.ArgumentParser();ap.add_argument('corpus',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--studies',type=Path,default=Path('config/studies.json'));ap.add_argument('--openings',type=Path,default=Path('config/strength-openings.json'));a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    heldout=set();heldout_families=set();heldout_inputs={}
    for source in [a.studies,a.openings]:
        if not source.exists():continue
        heldout_inputs[str(source)]=digest(source);document=json.loads(source.read_text())
        for item in document.get('positions',[]):heldout.add(input_identity(chess.Board(item['fen'],chess960=item.get('chess960',False)).fen(en_passant='fen')))
        for opening in document.get('openings',[]):
            board=chess.Board(opening.get('fen',chess.STARTING_FEN));path=[]
            heldout.add(input_identity(board.fen(en_passant='fen')))
            for text in opening['moves']:
                board.push_uci(text);path.append(text);heldout.add(input_identity(board.fen(en_passant='fen')))
            if len(path)>=8:heldout_families.add(hashlib.sha256(' '.join(path[:8]).encode()).hexdigest())
    db=sqlite3.connect(a.output/'identities.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA cache_size=-131072')
    db.execute('CREATE TABLE positions (input BLOB PRIMARY KEY, position_id BLOB, split INTEGER, fen TEXT, outcome REAL, teacher_cp REAL, teacher_probability REAL, n INTEGER, min_outcome REAL, max_outcome REAL, game TEXT, family TEXT) WITHOUT ROWID')
    db.execute('CREATE TABLE lineage (input BLOB, game TEXT, n INTEGER, first_ply INTEGER, last_ply INTEGER, PRIMARY KEY(input,game)) WITHOUT ROWID')
    counts={'games':0,'completed_games':0,'unfinished_games':0,'raw_positions':0,'within_split_duplicates':0,'feature_equivalent_duplicates':0,'cross_split_conflicts':0,'heldout_samples':0,'heldout_games':0,'teacher_depth_zero_samples':0}
    hist={key:{} for key in ['ply','clock','material','phase','outcome','teacher','search_depth']};source_hash=hashlib.sha256();start=time.monotonic();source_pairs=[]
    for path in sorted(a.corpus.glob('*/*.json')):
        raw=path.read_bytes();source_hash.update(hashlib.sha256(raw).digest());pair=json.loads(raw);source_pairs.append({'pair':pair['pair'],'sha256':hashlib.sha256(raw).hexdigest()})
        if pair.get('schema')!='caissa-selfplay-v1':raise ValueError('unsupported corpus journal')
        for g in pair['games']:
            counts['games']+=1
            if not verify_game(g):counts['unfinished_games']+=1;continue
            counts['completed_games']+=1;family=hashlib.sha256(' '.join(g['moves'][:8]).encode()).hexdigest()
            if family in heldout_families:counts['heldout_games']+=1;continue
            bucket=int(family[:8],16)%10;split=1 if bucket==0 else 2 if bucket==1 else 0
            white={'1-0':1.,'0-1':0.,'1/2-1/2':.5}[g['result']];game=f"{g['pair']}:{g['reverse']}"
            for s in g['positions']:
                counts['raw_positions']+=1;identity=input_identity(s['fen']);position_id=hashlib.sha256(canonical(s['fen']).encode()).digest()
                if identity in heldout:counts['heldout_samples']+=1;continue
                stm=s['fen'].split()[1];outcome=white if stm=='w' else 1-white;teacher=float(s['score_stm'])
                if not math.isfinite(teacher) or abs(teacher)>30000:raise ValueError('invalid original-teacher score')
                probability=1/(1+math.exp(-max(-60.,min(60.,teacher/400))))
                row=db.execute('SELECT split,position_id FROM positions WHERE input=?',(identity,)).fetchone()
                if row:
                    if row[1]!=position_id:counts['feature_equivalent_duplicates']+=1
                    if row[0]==split:
                        counts['within_split_duplicates']+=1
                        db.execute('UPDATE positions SET outcome=outcome+?,teacher_cp=teacher_cp+?,teacher_probability=teacher_probability+?,n=n+1,min_outcome=min(min_outcome,?),max_outcome=max(max_outcome,?) WHERE input=?',(outcome,teacher,probability,outcome,outcome,identity))
                    elif row[0]!=-1:db.execute('UPDATE positions SET split=-1 WHERE input=?',(identity,));counts['cross_split_conflicts']+=1
                else:db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,position_id,split,s['fen'],outcome,teacher,probability,1,outcome,outcome,game,family))
                db.execute('INSERT INTO lineage VALUES(?,?,?,?,?) ON CONFLICT(input,game) DO UPDATE SET n=n+1,last_ply=excluded.last_ply',(identity,game,1,s['ply'],s['ply']))
                if s['depth']==0:counts['teacher_depth_zero_samples']+=1
                board_part=s['fen'].split()[0];phase=min(24,sum({'n':1,'b':1,'r':2,'q':4}.get(piece.lower(),0) for piece in board_part))
                for key,value in [('ply',s['ply']//10*10),('clock',int(s['fen'].split()[4])//10*10),('material',sum(c.isalpha() for c in board_part)),('phase',phase),('outcome',outcome),('teacher',max(-2000,min(2000,int(teacher//100*100)))),('search_depth',s['depth'])]:
                    label=str(value);hist[key][label]=hist[key].get(label,0)+1
        if counts['games']%200==0:db.commit();print(json.dumps(counts),flush=True)
    db.commit();sizes={}
    for split,name in [(0,'train'),(1,'validation'),(2,'test')]:
        n=db.execute('SELECT count(*) FROM positions WHERE split=?',(split,)).fetchone()[0];sizes[name]=n
        if n==0:raise ValueError('empty required split '+name)
        x=np.lib.format.open_memmap(a.output/f'{name}-features.npy',mode='w+',dtype=np.uint16,shape=(n,2,32));y=np.lib.format.open_memmap(a.output/f'{name}-targets.npy',mode='w+',dtype=np.float32,shape=(n,3))
        with (a.output/f'{name}-identities.jsonl').open('w') as ids:
            for i,(identity,position_id,fen,outcome,teacher,probability,count,game,family) in enumerate(db.execute('SELECT input,position_id,fen,outcome,teacher_cp,teacher_probability,n,game,family FROM positions WHERE split=? ORDER BY input',(split,))):
                x[i]=features(fen);y[i]=[outcome/count,teacher/count,probability/count]
                contributors=[{'game':g,'count':c,'first_ply':first,'last_ply':last} for g,c,first,last in db.execute('SELECT game,n,first_ply,last_ply FROM lineage WHERE input=? ORDER BY game',(identity,))]
                ids.write(json.dumps({'input_id':identity.hex(),'position_id':position_id.hex(),'first_game':game,'first_family':family,'observations':count,'contributors':contributors})+'\n')
        x.flush();y.flush();del x,y
    counts['distinct_usable_positions']=sum(sizes.values());counts['quarantined_inputs']=db.execute('SELECT count(*) FROM positions WHERE split=-1').fetchone()[0];counts['mixed_outcome_inputs']=db.execute('SELECT count(*) FROM positions WHERE min_outcome<max_outcome AND split>=0').fetchone()[0]
    atomic_json(a.output/'SOURCE_PAIRS.json',source_pairs)
    manifest={'schema':'caissa-dataset-v2','corpus_config':json.loads((a.corpus/'CONFIG.json').read_text()),'corpus_content_sha256':source_hash.hexdigest(),'source_pairs_sha256':digest(a.output/'SOURCE_PAIRS.json'),'input_identity':'side-to-move normalized placement; rights/EP/clocks excluded; color reflection collapsed','functional_deduplication':True,'target_columns':['mean_outcome_stm','mean_original_teacher_cp','mean_original_teacher_win_probability'],'ordering':'input SHA256','heldout_inputs':heldout_inputs,'counts':counts,'splits':sizes,'histograms':hist,'seconds':time.monotonic()-start,'files':{p.name:digest(p) for p in a.output.glob('*.npy')}}
    atomic_json(a.output/'DATASET.json',manifest);db.close();print(json.dumps({k:v for k,v in manifest.items() if k not in ['histograms','files']}))
if __name__=='__main__':main()
