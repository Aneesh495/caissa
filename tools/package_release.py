"""Package only a fully verified source/evidence pair and maintainer audit."""
import argparse,hashlib,json,subprocess,sys,tarfile,tempfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--commit',required=True);ap.add_argument('--audit',type=Path,default=Path('.agent-local/release-audit.json'));a=ap.parse_args()
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=a.commit:raise ValueError('release source commit mismatch')
    if subprocess.check_output(['git','status','--porcelain'],text=True):raise ValueError('release source must be clean')
    subprocess.run([sys.executable,'-m','verification.verify',str(a.evidence),'--checkout','.','--expected-commit',a.commit,'--profile','full'],check=True)
    if not a.audit.exists():raise ValueError('maintainer release audit is missing')
    audit=json.loads(a.audit.read_text())
    if audit.get('commit')!=a.commit or audit.get('status')!='passed':raise ValueError('maintainer release audit is incomplete or stale')
    remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()[0]
    if remote!=a.commit:raise ValueError('published source is not the verified source')
    output=Path('dist');output.mkdir(exist_ok=True);target=output/f'caissa-{a.commit[:12]}.tar.gz'
    if target.exists():raise ValueError('release package already exists')
    with tempfile.TemporaryDirectory(prefix='release-',dir=output) as folder:
        root=Path(folder)/'caissa';root.mkdir();(root/'bin').mkdir()
        import shutil
        shutil.copy2(a.evidence/'bin/caissa',root/'bin/caissa');shutil.copy2('LICENSE',root/'LICENSE');shutil.copytree('models',root/'models')
        metadata={'source_commit':a.commit,'evidence_manifest_sha256':hashlib.sha256((a.evidence/'MANIFEST.json').read_bytes()).hexdigest(),'profile':'full'};(root/'RELEASE.json').write_text(json.dumps(metadata,indent=2)+'\n')
        with (root/'source.tar').open('wb') as stream:subprocess.run(['git','archive','--format=tar',a.commit],stdout=stream,check=True)
        with tarfile.open(target,'w:gz') as archive:archive.add(root,arcname='caissa')
    print(json.dumps({'package':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'published':False}))
if __name__=='__main__':main()
