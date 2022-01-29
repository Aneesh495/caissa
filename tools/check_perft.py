import argparse,json,subprocess,time
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');a=ap.parse_args();start=time.monotonic()
for row in json.loads(Path('config/perft.json').read_text())['positions']:
    command=[a.engine,'--perft',str(row['depth']),row['fen']]
    if row['chess960']:command.append('960')
    result=subprocess.run(command,capture_output=True,text=True,timeout=60,check=True)
    if int(result.stdout)!=row['nodes']:raise SystemExit(f"perft mismatch {row['id']}: {result.stdout} != {row['nodes']}")
print(json.dumps({'positions':20,'status':'passed','seconds':time.monotonic()-start}))
