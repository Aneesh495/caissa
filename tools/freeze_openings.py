"""Freeze diverse original legal opening pairs, without evaluator filtering."""
import argparse,hashlib,json,random
from pathlib import Path
import chess

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--count',type=int,default=1000);ap.add_argument('--seed',type=int,default=982451653);a=ap.parse_args()
    if a.output.exists():raise ValueError('opening manifest already exists')
    bases=json.loads(Path('config/openings.json').read_text())['openings'];rng=random.Random(a.seed);seen=set();families=set();rows=[];attempts=0
    while len(rows)<a.count:
        attempts+=1
        if attempts>a.count*100:raise ValueError('cannot obtain requested distinct legal openings')
        base=bases[rng.randrange(len(bases))];board=chess.Board();moves=list(base['moves'])
        for text in moves:board.push_uci(text)
        target=rng.randrange(max(8,len(moves)),13)
        while len(moves)<target:
            legal=list(board.legal_moves)
            if not legal:break
            move=legal[rng.randrange(len(legal))];moves.append(board.uci(move));board.push(move)
        if len(moves)<8 or board.is_game_over() or board.is_check():continue
        identity=' '.join(board.fen(en_passant='legal').split()[:4]);family=hashlib.sha256(' '.join(moves[:8]).encode()).hexdigest()
        if identity in seen or family in families:continue
        seen.add(identity);families.add(family);rows.append({'id':f'caissa-opening-{len(rows):04d}','moves':moves,'family_sha256':family,'final_fen':board.fen(en_passant='fen')})
    a.output.write_text(json.dumps({'schema':'caissa-openings-v1','seed':a.seed,'count':len(rows),'provenance':'Original seeded legal extensions of manually specified common starts; no score or result filtering','attempts':attempts,'openings':rows},indent=2)+'\n');print(json.dumps({'openings':len(rows),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}))
if __name__=='__main__':main()
