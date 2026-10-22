"""Generate a frozen fixture using only the external oracle, never Caissa."""
import chess,json,random
from pathlib import Path

def count(board,depth):
    if depth==0:return 1
    if depth==1:return board.legal_moves.count()
    n=0
    for move in board.legal_moves:
        board.push(move);n+=count(board,depth-1);board.pop()
    return n
rng=random.Random(49979687)
fens=[chess.STARTING_FEN,'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1','8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1','r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1','rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8','r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10']
rows=[]
for i,fen in enumerate(fens):
    b=chess.Board(fen);depth=4 if i==0 else 3
    rows.append({'id':f'standard-{i}','fen':fen,'chess960':False,'depth':depth,'nodes':count(b,depth)})
for i in range(14):
    variant=i%3==0;b=chess.Board.from_chess960_pos(rng.randrange(960)) if variant else chess.Board()
    for ply in range(5+i*5):
        moves=list(b.legal_moves)
        if not moves:break
        b.push(rng.choice(moves))
    rows.append({'id':f'reachable-{i}','fen':b.fen(en_passant='fen'),'chess960':variant,'depth':3,'nodes':count(b,3)})
Path('config/perft.json').write_text(json.dumps({'oracle':'chess '+chess.__version__,'seed':49979687,'positions':rows},indent=2)+'\n')
