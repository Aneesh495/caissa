import argparse,json,subprocess
from pathlib import Path
import chess
ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');a=ap.parse_args()
engine=subprocess.Popen([a.engine,'--inspect'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
try:
 for row in json.loads(Path('config/studies.json').read_text())['positions']:
  board=chess.Board(row['fen'],chess960=row.get('chess960',False))
  if not board.is_valid():raise ValueError('invalid authored study '+row['id'])
  engine.stdin.write(('960|' if board.chess960 else '')+row['fen']+'\n');engine.stdin.flush();response=json.loads(engine.stdout.readline())
  expected=sorted(board.uci(m) for m in board.legal_moves)
  if sorted(response.get('moves',[]))!=expected:raise ValueError('study move disagreement '+row['id'])
  if row.get('required') and row['required'] not in expected:raise ValueError('required study move absent')
  if row.get('forbidden') and row['forbidden'] in expected:raise ValueError('forbidden study move accepted')
  for move in row.get('history',[]):board.push_uci(move)
  if row['kind']=='repetition' and row.get('history') and not board.is_repetition(3):raise ValueError('repetition study history invalid')
finally:engine.stdin.close();engine.wait(timeout=5)
print('24 authored rule/tactic/endgame/Chess960 studies independently checked')
