import hashlib,json,runpy,sys
from pathlib import Path
p=Path(sys.argv[sys.argv.index("--plan")+1]);raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()==sys.argv[sys.argv.index("--expected-plan-sha256")+1]
for name,value in json.loads(raw)["frozen_source_files"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==value
sys.path.insert(0,str(Path(__file__).parent/"source"))
runpy.run_module("tools.publish_evidence",run_name="__main__")
