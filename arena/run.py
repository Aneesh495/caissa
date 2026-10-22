"""Color-paired matches with per-game recovery and independent legal replay."""
import argparse,concurrent.futures,hashlib,json,time
from pathlib import Path
import chess,chess.pgn
from arena.client import UciClient,EngineFailure
from training.corpus import atomic_json,digest

def finish_reason(board):
    if board.is_checkmate():return 'checkmate',('0-1' if board.turn else '1-0')
    if board.is_stalemate():return 'stalemate','1/2-1/2'
    if board.is_insufficient_material():return 'proven-dead-material','1/2-1/2'
    if board.is_seventyfive_moves():return 'seventy-five-move','1/2-1/2'
    if board.is_fivefold_repetition():return 'fivefold','1/2-1/2'
    if board.is_repetition(3):return 'threefold-claim','1/2-1/2'
    if board.halfmove_clock>=100:return 'fifty-move-claim','1/2-1/2'
    return None

def write_pgn(record,actors,path):
    pgn=chess.pgn.Game();pgn.setup(chess.Board(record['initial']))
    pgn.headers.update({'Event':'Caissa '+record.get('profile','diagnostic')+' arena','White':actors[0]['name'],'Black':actors[1]['name'],'Result':record['result'],'Termination':record['termination'],'OpeningId':record['opening_id']});node=pgn
    for text in record['moves']:node=node.add_variation(chess.Move.from_uci(text))
    temp=path.with_suffix('.pgn.tmp');temp.write_text(str(pgn)+'\n');temp.replace(path.with_suffix('.pgn'))

def game(config,opening,pair,reverse,root):
    path=root/'games'/f'{pair:06d}-{reverse}.json'
    if path.exists():
        record=json.loads(path.read_text());actors=[config['candidate'],config['opponent']] if reverse==0 else [config['opponent'],config['candidate']]
        if not path.with_suffix('.pgn').exists():write_pgn(record,actors,path)
        return record
    board=chess.Board(opening.get('fen',chess.STARTING_FEN));initial=board.fen(en_passant='fen');moves=[]
    for text in opening['moves']:
        move=chess.Move.from_uci(text)
        if move not in board.legal_moves:raise ValueError('illegal opening manifest')
        board.push(move);moves.append(text)
    candidate_white=reverse==0;actors=[config['candidate'],config['opponent']] if candidate_white else [config['opponent'],config['candidate']]
    clients=[];observations=[];termination='ply-limit';result='*';culprit=None
    try:
        for color,actor in enumerate(actors):
            try:clients.append(UciClient(actor['command'],actor['options'],warmup_nodes=config.get('warmup_nodes',0)))
            except EngineFailure as e:
                culprit='white' if color==0 else 'black';termination='crash';result='0-1' if color==0 else '1-0';observations.append({'startup_failure':str(e),'color':culprit});break
        if len(clients)==2:
            while len(moves)<config['max_plies']:
                state=finish_reason(board)
                if state:termination,result=state;break
                color=0 if board.turn else 1;client=clients[color]
                try:
                    text,elapsed,lines=client.play(initial,moves,nodes=config.get('nodes'),milliseconds=config.get('milliseconds'))
                    observation={'ply':len(moves),'move':text,'milliseconds':elapsed,'uci':lines};observations.append(observation)
                    if 'milliseconds' in config and elapsed>config['milliseconds']+config.get('transport_allowance_ms',100):
                        culprit='white' if color==0 else 'black';termination='time-loss';result='0-1' if color==0 else '1-0';break
                    try:move=chess.Move.from_uci(text)
                    except ValueError:move=None
                    if move is None or move not in board.legal_moves:
                        culprit='white' if color==0 else 'black';termination='illegal-move';result='0-1' if color==0 else '1-0';break
                    board.push(move);moves.append(text)
                except EngineFailure as e:
                    observations.append({'ply':len(moves),'failure':str(e)});culprit='white' if color==0 else 'black';termination='protocol-failure';result='0-1' if color==0 else '1-0';break
    finally:
        for client in clients:client.close()
    record={'profile':config.get('profile','unclassified'),'schema':'caissa-arena-game-v1','pair':pair,'reverse':reverse,'opening_id':opening['id'],'candidate_color':'white' if candidate_white else 'black','initial':initial,'opening_plies':len(opening['moves']),'moves':moves,'result':result,'termination':termination,'culprit':culprit,'observations':observations,'warmup_ms':[c.warmup_ms for c in clients]}
    atomic_json(path,record)
    write_pgn(record,actors,path);return record

def pair(config,opening,identity,root):
    path=root/'pairs'/f'{identity:06d}.json'
    if path.exists():return json.loads(path.read_text())
    games=[game(config,opening,identity,reverse,root) for reverse in [0,1]];record={'schema':'caissa-arena-pair-v1','pair':identity,'opening_id':opening['id'],'games':games};atomic_json(path,record);return record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('config',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--workers',type=int,default=2);a=ap.parse_args()
    if not 1<=a.workers<=4:ap.error('workers outside [1,4]')
    config=json.loads(a.config.read_text());openings=json.loads(Path(config['openings']).read_text())['openings']
    if not 1<=config['pairs']<=100000 or not 64<=config['max_plies']<=1024:raise ValueError('campaign resource bounds')
    if ('nodes' in config)==('milliseconds' in config):raise ValueError('select exactly one budget')
    identities={}
    for role in ['candidate','opponent']:
        actor=config[role];actor['command'][0]=str(Path(actor['command'][0]).resolve());identities[role]={'executable':digest(actor['command'][0]),'command':actor['command'],'options':actor['options']}
        if actor['options'].get('Use Neural'):
            net=Path(actor['options']['EvalFile']).resolve();actor['options']['EvalFile']=str(net);identities[role]['network_sha256']=digest(net)
    identity={'config':config,'executables':identities,'openings_sha256':digest(config['openings'])}
    a.output.mkdir(parents=True,exist_ok=True);(a.output/'games').mkdir(exist_ok=True);(a.output/'pairs').mkdir(exist_ok=True)
    cfg=a.output/'CONFIG.json'
    if cfg.exists() and json.loads(cfg.read_text())!=identity:raise ValueError('resume source, model, workload or configuration mismatch')
    atomic_json(cfg,identity);start=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending=iter(range(config['pairs']));active={}
        def submit():
            i=next(pending,None)
            if i is not None:active[pool.submit(pair,config,openings[i%len(openings)],i,a.output)]=i
        for _ in range(a.workers):submit()
        completed=0
        while active:
            ready,_=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED)
            for future in ready:active.pop(future);future.result();completed+=1;submit()
            if completed%10==0 or not active:print(json.dumps({'pairs':completed,'requested':config['pairs'],'seconds':time.monotonic()-start}),flush=True)
    for role,actor in [('candidate',config['candidate']),('opponent',config['opponent'])]:
        if digest(actor['command'][0])!=identities[role]['executable']:raise ValueError('executable changed during campaign')
if __name__=='__main__':main()
