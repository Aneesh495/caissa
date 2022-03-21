"""Read-only source-bound replay and independent fixed-sample recomputation."""
import argparse,hashlib,json,math,subprocess,sys
from pathlib import Path
import chess
import numpy as np
from verification.inference import infer

class Rejection(ValueError):pass

def load(path):
    def bad(value):raise Rejection('nonfinite JSON value '+value)
    return json.loads(Path(path).read_text(),parse_constant=bad)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_files(checkout):
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=checkout).decode().split('\0')
    suffixes={'.cpp','.hpp','.py','.ts','.toml','.lock','.yml','.yaml','.cai'}
    fixed={'CMakeLists.txt','Makefile','package.json','package-lock.json','tsconfig.json','docs/EXPERIMENT_PLAN.md'}
    return sorted(p for p in paths if p and (Path(p).suffix in suffixes or p in fixed or p.startswith('config/')) and not p.startswith(('results/','docs/images/')))

def source_check(bundle,checkout,expected):
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()
    if actual!=expected:raise Rejection('trusted checkout is not the expected executable source commit')
    source=load(bundle/'SOURCE_INPUTS.json')
    if source['commit']!=expected:raise Rejection('source commit mismatch')
    paths=source_files(checkout)
    if set(source['files'])!=set(paths):raise Rejection('source input inventory differs from trusted checkout')
    for path in paths:
        if sha(checkout/path)!=source['files'][path]:raise Rejection('trusted source bytes mismatch: '+path)

def terminal(board,reason,result):
    checks={'checkmate':board.is_checkmate(),'stalemate':board.is_stalemate(),'proven-dead-material':board.is_insufficient_material(),'fivefold':board.is_fivefold_repetition(),'seventy-five-move':board.is_seventyfive_moves(),'threefold-claim':board.is_repetition(3),'fifty-move-claim':board.halfmove_clock>=100 and bool(board.legal_moves)}
    if reason in checks:
        if not checks[reason]:raise Rejection('invalid terminal or draw claim: '+reason)
        expected=('0-1' if board.turn else '1-0') if reason=='checkmate' else '1/2-1/2'
        if result!=expected:raise Rejection('result colors disagree with replayed terminal position')
    elif reason=='ply-limit':
        if result!='*':raise Rejection('ply limit manufactured a completed draw')
    elif reason not in ['crash','illegal-move','time-loss','protocol-failure']:raise Rejection('unrecognized terminal provenance')

def replay_game(game):
    board=chess.Board(game['initial'])
    for ply,text in enumerate(game['moves']):
        move=chess.Move.from_uci(text)
        if move not in board.legal_moves:raise Rejection(f'illegal game move at ply {ply}')
        board.push(move)
    terminal(board,game['termination'],game['result'])
    if game['termination'] in ['crash','illegal-move','time-loss','protocol-failure']:
        culprit=game.get('culprit')
        if culprit not in ['white','black']:raise Rejection('forfeit culprit missing')
        if game['result']!=('0-1' if culprit=='white' else '1-0'):raise Rejection('forfeit awarded to wrong color')
        if not any('failure' in row or 'startup_failure' in row or 'move' in row for row in game['observations']):raise Rejection('forfeit lacks raw observation')
    return board

def independent_statistics(records):
    units={};wins=losses=draws=unfinished=0;seen=set();values=[]
    for pair in records:
        if pair['pair'] in seen:raise Rejection('duplicated arena pair identity')
        seen.add(pair['pair'])
        if len(pair['games'])!=2:raise Rejection('unfinished opening pair')
        scores=[]
        for reverse,game in enumerate(pair['games']):
            if game['reverse']!=reverse or game['candidate_color']!=('white' if reverse==0 else 'black'):raise Rejection('swapped result colors or pair ordering')
            replay_game(game)
            if game['result']=='*':unfinished+=1;continue
            score={'1-0':1.,'0-1':0.,'1/2-1/2':.5}[game['result']]
            if reverse:score=1-score
            wins+=score==1;losses+=score==0;draws+=score==.5;scores.append(score)
        if len(scores)==2:
            value=(scores[0]+scores[1])/2;values.append(value);units.setdefault(pair['opening_id'],[]).append(value)
    if not values:raise Rejection('empty match work')
    clusters=np.array([(sum(scores),len(scores)) for scores in units.values()],dtype=float);rng=np.random.default_rng(104729);samples=[]
    for _ in range(20000):
        chosen=clusters[rng.integers(len(clusters),size=len(clusters))];samples.append(float(chosen[:,0].sum()/chosen[:,1].sum()))
    lo,hi=np.quantile(samples,[.025,.975]);mean=sum(values)/len(values)
    if abs(float(hi)-float(lo))<1e-15:
        total=float(clusters[:,1].sum());squared_weights=sum((float(row[1])/total)**2 for row in clusters)
        radius=math.sqrt(math.log(2/.05)*squared_weights/2)
        lo=min(float(lo),max(0.,mean-radius));hi=max(float(hi),min(1.,mean+radius))
    return {'wins':int(wins),'draws':int(draws),'losses':int(losses),'games':int(wins+draws+losses),'unfinished_games':unfinished,'complete_pairs':len(values),'independent_opening_clusters':len(units),'score':mean,'score_95':[float(lo),float(hi)]}

def verify(bundle,checkout,expected,profile):
    source_check(bundle,checkout,expected);manifest=load(bundle/'MANIFEST.json')
    actual={str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','VERIFICATION.json']}
    if set(manifest['files'])!=actual:raise Rejection('missing or unexpected bundle artifact')
    for relative,expected_hash in manifest['files'].items():
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts or (bundle/path).is_symlink():raise Rejection('unsafe artifact path')
        if sha(bundle/path)!=expected_hash:raise Rejection('artifact corruption: '+relative)
    fixtures=load(checkout/'config/perft.json')['positions'];observed=load(bundle/'perft.json')
    if len(fixtures)!=20 or len(observed)!=20:raise Rejection('required perft workload missing')
    for expected_row,actual_row in zip(fixtures,observed):
        if expected_row['id']!=actual_row['id'] or expected_row['nodes']!=actual_row['actual']:raise Rejection('frozen perft result mismatch')
        command=[str(bundle/'bin/caissa'),'--perft',str(expected_row['depth']),expected_row['fen']]+(['960'] if expected_row['chess960'] else [])
        replay=subprocess.run(command,capture_output=True,text=True,timeout=60)
        if replay.returncode or int(replay.stdout)!=expected_row['nodes']:raise Rejection('independent native perft replay failed')
    acceptance=load(bundle/'ACCEPTANCE.json')
    trusted_model=checkout/'models/diagnostic-v2.cai'
    if profile=='diagnostic' and sha(bundle/'network.cai')!=sha(trusted_model):raise Rejection('network identity differs from trusted saved model')
    if profile!=acceptance['profile']:raise Rejection('profile mismatch; diagnostics cannot certify full acceptance')
    commands=[json.loads(l) for l in (bundle/'COMMANDS.jsonl').read_text().splitlines()]
    if not commands or any(c['exit']!=0 for c in commands if c['required']):raise Rejection('missing or failed required execution')
    search_rows=[json.loads(l) for l in (bundle/'search.jsonl').read_text().splitlines()]
    if len(search_rows)<4:raise Rejection('insufficient frozen search probes')
    for row in search_rows:
        board=chess.Board(row['fen'])
        for text in row['pv']:
            move=chess.Move.from_uci(text)
            if move not in board.legal_moves:raise Rejection('illegal principal variation')
            board.push(move)
        # Bounded replay uses the exact saved executable and fixed depth, never another engine.
        result=subprocess.run([str(bundle/'bin/caissa'),'--search',str(row['depth']),row['fen']],capture_output=True,text=True,timeout=10)
        if result.returncode:raise Rejection('saved native search replay failed')
        actual_search=json.loads(result.stdout)
        if actual_search['score']!=row['score'] or actual_search['bestmove']!=row['bestmove']:raise Rejection('search replay score or move mismatch')
    probes=[json.loads(l) for l in (bundle/'network-probes.jsonl').read_text().splitlines()]
    if len(probes)<32:raise Rejection('empty or insufficient network work')
    for row in probes:
        expected_output=infer(bundle/'network.cai',row['fen'])
        if row['native']!=expected_output or row['reference']!=expected_output:raise Rejection('network inference semantic mismatch')
    records=load(bundle/'arena-pairs.json');summary=load(bundle/'arena-summary.json');computed=independent_statistics(records)
    for key,value in computed.items():
        saved=summary.get(key)
        if isinstance(value,float):
            if not isinstance(saved,(int,float)) or abs(saved-value)>1e-12:raise Rejection('independent match statistic mismatch: '+key)
        elif isinstance(value,list):
            if not isinstance(saved,list) or len(saved)!=len(value) or any(abs(float(a)-float(b))>1e-12 for a,b in zip(saved,value)):raise Rejection('independent match interval mismatch: '+key)
        elif saved!=value:raise Rejection('independent match statistic mismatch: '+key)
    checks=load(bundle/'draw-probes.json')
    for game in checks:replay_game(game)
    if len(checks)<2:raise Rejection('draw probes missing')
    if profile=='full':
        # Full certification is intentionally unavailable until every raw domain campaign exists.
        raise Rejection('full campaign verifier is incomplete; diagnostic semantics cannot pass full gates')
    return {'status':'passed','scope':'diagnostic source identity and bounded semantic replay','full_acceptance':False,'search_probes':len(search_rows),'network_probes':len(probes),'arena_games':computed['games'],'source_commit':expected}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('evidence',type=Path);ap.add_argument('--checkout',type=Path,required=True);ap.add_argument('--expected-commit',required=True);ap.add_argument('--profile',choices=['full','diagnostic'],default='full');a=ap.parse_args()
    try:result=verify(a.evidence.resolve(),a.checkout.resolve(),a.expected_commit,a.profile);print(json.dumps(result));return 0
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as e:print(json.dumps({'status':'rejected','reason':str(e)}));return 1
if __name__=='__main__':raise SystemExit(main())
