import fcntl,hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
work=Path(__file__).resolve().parent
config=json.loads((work/"QUEUE.json").read_text())
lock=(work/"QUEUE.lock").open("a")
fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def record(value):
 value={"observed_unix":time.time(),"pid":os.getpid(),**value}
 target=work/"QUEUE_PROGRESS.json";temp=target.with_suffix(".tmp")
 temp.write_text(json.dumps(value)+"\n");temp.replace(target)
if sha(__file__)!=config["queue_source_sha256"]:raise ValueError("queued source changed")
print(json.dumps({"status":"waiting-for-original-heuristic-owner","pid":os.getpid()}),flush=True)
while time.time()<config["wait_deadline_unix"]:
 for name,pin in config["pins"].items():
  if sha(root/name)!=pin:raise ValueError("queued source or authorization changed: "+name)
 usage=json.loads((root/"runs/full-heuristics-strength-v1/ACTIVE_USAGE.json").read_text())
 try:
  command=subprocess.run(["ps","-p","32106","-o","command="],capture_output=True,text=True,timeout=3).stdout
  expected_owner_alive="heuristics_log_continuation.py" in command
 except (OSError,subprocess.SubprocessError):
  expected_owner_alive=True
 if usage.get("closed") is True and not expected_owner_alive:
  record({"status":"launching-original-parallel-attempt4","scope_wait_closed":True})
  log=os.open(root/"runs/full-parallel-strength-v1-bounded-continuation-owner.log",os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
  os.dup2(log,1);os.dup2(log,2);os.close(log);os.chdir(root)
  executable=str(root/".venv/bin/python")
  os.execv(executable,[executable,"-B","-P",str(root/"tools/parallel_bounded_continuation.py")])
 record({"status":"waiting-for-original-heuristic-owner","scope_wait_closed":False,"heuristic_ledger_closed":usage.get("closed"),"expected_owner_alive":expected_owner_alive})
 time.sleep(min(5,max(0,config["wait_deadline_unix"]-time.time())))
record({"status":"wait-window-exhausted-no-games-launched","scope_wait_closed":True})
raise SystemExit(2)
