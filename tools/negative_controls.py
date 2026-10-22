"""Rehash structurally valid mutations and run the real verifier as a subprocess."""
import argparse,hashlib,json,shutil,subprocess,sys
from pathlib import Path

def rehash(root):
    paths=sorted(p for p in root.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','VERIFICATION.json'])
    (root/'MANIFEST.json').write_text(json.dumps({'files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('evidence',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--checkout',type=Path,required=True);ap.add_argument('--expected-commit',required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False);results=[]
    for name in ['illegal-pv','swapped-result','network-output','false-draw','source-mismatch','missing-artifact','corrupt-artifact']:
        root=a.output/name;shutil.copytree(a.evidence,root)
        if name=='illegal-pv':
            p=root/'search.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()];rows[0]['pv']=['a1a8'];p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        elif name=='swapped-result':
            p=root/'arena-pairs.json';records=json.loads(p.read_text());found=False
            for pair in records:
                for game in pair['games']:
                    if game['termination']=='checkmate':game['result']='0-1' if game['result']=='1-0' else '1-0';found=True;break
                if found:break
            if not found:raise ValueError('negative control requires real decisive game')
            p.write_text(json.dumps(records)+'\n')
        elif name=='network-output':
            p=root/'network-probes.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()];rows[0]['native']+=37;p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        elif name=='false-draw':
            p=root/'draw-probes.json';rows=json.loads(p.read_text());rows[0]['moves']=[];rows[0]['termination']='threefold-claim';rows[0]['result']='1/2-1/2';p.write_text(json.dumps(rows)+'\n')
        elif name=='source-mismatch':
            p=root/'SOURCE_INPUTS.json';d=json.loads(p.read_text());d['commit']='0'*40;p.write_text(json.dumps(d)+'\n')
        elif name=='missing-artifact':(root/'network-probes.jsonl').unlink()
        elif name=='corrupt-artifact':(root/'network.cai').write_bytes(b'bad')
        if name not in ['missing-artifact','corrupt-artifact']:rehash(root)
        command=[sys.executable,'-m','verification.verify',str(root),'--checkout',str(a.checkout),'--expected-commit',a.expected_commit,'--profile','diagnostic']
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        try:reason=json.loads(result.stdout)['reason']
        except (json.JSONDecodeError,KeyError):raise ValueError('verifier did not produce a structured rejection: '+result.stdout+result.stderr)
        if result.returncode==0:raise ValueError('verifier accepted semantic mutation '+name)
        row={'control':name,'command':command,'exit':result.returncode,'reason':reason,'rehashes_recomputed':name not in ['missing-artifact','corrupt-artifact']};results.append(row);print(json.dumps(row),flush=True)
    (a.output/'CONTROLS.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
