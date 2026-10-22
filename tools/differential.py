"""Three-way reachable-position legality audit; chess is an isolated oracle."""
import argparse, hashlib, json, random, subprocess, time
from pathlib import Path
import chess

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--engine',default='build/caissa')
    ap.add_argument('--positions',type=int,default=100000)
    ap.add_argument('--seed',type=int,default=1729)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if not 1<=args.positions<=10000000: ap.error('bounded position count required')
    args.output.mkdir(parents=True,exist_ok=False)
    rng=random.Random(args.seed);seen=set();start=time.monotonic();games=0
    engine=subprocess.Popen([args.engine,'--inspect'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    try:
        with (args.output/'observations.jsonl').open('w') as log:
            board=chess.Board()
            for i in range(args.positions):
                if board.is_game_over() or board.ply()>300 or rng.random()<0.015:
                    games+=1
                    board=chess.Board.from_chess960_pos(rng.randrange(960)) if games%4==0 else chess.Board()
                fen=board.fen(en_passant='fen')
                engine.stdin.write(('960|' if board.chess960 else '')+fen+'\n');engine.stdin.flush()
                line=engine.stdout.readline()
                if not line: raise RuntimeError('engine exited before responding')
                response=json.loads(line)
                expected=sorted(board.uci(m) for m in board.legal_moves)
                actual=sorted(response.get('moves',[]))
                row={'i':i,'fen':fen,'chess960':board.chess960,'expected':expected,'actual':actual,'check_expected':board.is_check(),'check_actual':response.get('check')}
                log.write(json.dumps(row,separators=(',',':'))+'\n')
                if actual!=expected or response.get('check')!=board.is_check():
                    raise RuntimeError(f'move/check mismatch at {i}: {row}')
                seen.add((board.chess960,board.board_fen(),board.turn,board.castling_rights,board.ep_square if board.has_legal_en_passant() else None))
                if expected: board.push_uci(rng.choice(expected))
                if (i+1)%10000==0: print(f'{i+1} compared; {len(seen)} unique; {time.monotonic()-start:.1f}s',flush=True)
        summary={'status':'passed','requested':args.positions,'completed':args.positions,'unique':len(seen),'seed':args.seed,'oracle':'chess '+chess.__version__,'seconds':time.monotonic()-start,'engine_sha256':hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),'observations_sha256':hashlib.sha256((args.output/'observations.jsonl').read_bytes()).hexdigest()}
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary))
    finally:
        engine.stdin.close()
        try: engine.wait(timeout=5)
        except subprocess.TimeoutExpired: engine.kill();engine.wait()
if __name__=='__main__': main()
