"""Clean-checkout diagnostic campaign with an explicit full-acceptance barrier."""
import argparse,json,re,subprocess,sys,time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run-id',required=True);ap.add_argument('--profile',choices=['diagnostic','full'],required=True);a=ap.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}',a.run_id):ap.error('invalid run identity')
    root=Path.cwd();out=root/'runs'/a.run_id
    if out.exists():raise ValueError('run identity already exists; evidence is immutable')
    if subprocess.check_output(['git','status','--porcelain'],text=True):raise ValueError('commit all source inputs before acceptance')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()[0]
    if remote!=commit:raise ValueError('hosted source differs from local source')
    if a.profile=='full':
        out.mkdir(parents=True);dataset=root/'data/full-prepared/DATASET.json';manifest=json.loads(dataset.read_text()) if dataset.exists() else None
        count=manifest['splits']['train'] if manifest else 0;games=manifest['counts']['completed_games'] if manifest else 0
        receipt={'profile':'full','status':'blocked','source_commit':commit,'full_acceptance':False,'observed_training_positions':count,'observed_completed_games':games,'required_training_positions':10000000,'required_completed_games':100000,'incomplete_gates':['G07 full learning','G08 neural strength','G09 full external strength','G10 full parallel profiles','G12 complete browser campaign','G13 frozen performance','G16 release audit'],'reason':'Full evidence and the complete full-profile verifier are not available. Diagnostic execution cannot substitute.'}
        (out/'ACCEPTANCE.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));return 2
    source=root/'work'/('acceptance-'+a.run_id)
    if source.exists():raise ValueError('isolated source path already exists')
    source.parent.mkdir(exist_ok=True);subprocess.run(['git','clone','--quiet','--no-hardlinks','--local',str(root),str(source)],check=True)
    def run(command):subprocess.run(command,cwd=source,check=True,timeout=300)
    run(['cmake','-S','.','-B','build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release'])
    run(['cmake','--build','build','-j','4'])
    run([sys.executable,'-m','arena.run','config/arena-ci.json','runs/integration-arena','--workers','1'])
    run([sys.executable,'-m','arena.statistics','runs/integration-arena'])
    run([sys.executable,'-m','tools.evidence','--checkout',str(source),'--engine',str(source/'build/caissa'),'--network',str(source/'models/diagnostic-v2.cai'),'--arena',str(source/'runs/integration-arena'),'--output',str(out)])
    verification=[sys.executable,'-m','verification.verify',str(out),'--checkout',str(source),'--expected-commit',commit,'--profile','diagnostic'];run(verification)
    run([sys.executable,'-m','tools.negative_controls',str(out),str(root/'runs'/(a.run_id+'-negative')),'--checkout',str(source),'--expected-commit',commit])
    print(json.dumps({'status':'passed','profile':'diagnostic','full_acceptance':False,'source':commit,'evidence':str(out),'trusted_checkout':str(source),'verify':verification}));return 0
if __name__=='__main__':raise SystemExit(main())
