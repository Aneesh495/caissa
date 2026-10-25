import hashlib
import json
import random
import statistics
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import chess
from arena.client import UciClient
from tools.campaign_process import Campaign, atomic
from tools.performance import info, replay

root=Path.cwd()
if "--child" in sys.argv:
    output=Path(sys.argv[2]);models=root/"models/residual-prefix-diagnostic.cai"
    binaries={"previous":root/"build-tactical/caissa","incremental":root/"build-search-context/caissa"}
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    inputs={str(p):sha(p) for p in [*binaries.values(),models,Path(__file__)]}
    cases=json.loads((root/"config/performance.json").read_text())["positions"]
    randomizer=random.Random(86028181)
    board=chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");opening=board.fen();history=[];seen={board.board_fen()+str(board.turn)}
    for ply in range(64):
        choices=[]
        for move in board.legal_moves:
            if board.is_capture(move):continue
            board.push(move);identity=board.board_fen()+str(board.turn)
            if identity not in seen and not board.is_game_over(claim_draw=True):choices.append(move)
            board.pop()
        if not choices:raise ValueError("finite quiet-history fixture exhausted")
        move=randomizer.choice(choices);board.push(move);history.append(move.uci());seen.add(board.board_fen()+str(board.turn))
        if ply+1 in (16,64):cases.append({"id":"quiet-history-"+str(ply+1),"fen":opening,"moves":history.copy(),"resulting_fen":board.fen()})
    config={"inputs":inputs,"positions":cases,"nodes":50000,"repeats":3,"threads":1,"hash_mib":16,"paired_order_seed":86028181,"wall_seconds":240,"host_load":"full original-data verifier running; no claimed isolated performance or Elo gain","search_keys_change_tt_layout":True,"full_acceptance":False}
    atomic(output/"COST_CONFIG.json",config);started=time.time();rows=[]
    with ExitStack() as stack,(output/"cost-observations.jsonl").open("x") as stream:
        clients={}
        for label,binary in binaries.items():
            for mode,weight in [("classical",0),("mixture",10),("neural",100)]:
                options={"Threads":1,"Hash":16,"Search Stats":True,"Evaluation Cache":True,"Tactical Generation":True}
                if weight:options.update({"EvalFile":str(models),"Use Neural":True,"Neural Weight":weight})
                clients[label,mode]=stack.enter_context(UciClient([str(binary)],options,warmup_nodes=1))
        for repeat in range(3):
            for case in cases:
                for mode in ["classical","mixture","neural"]:
                    labels=list(binaries);randomizer.shuffle(labels)
                    for label in labels:
                        if time.time()-started>=240:raise TimeoutError("cumulative paired cost wall deadline")
                        client=clients[label,mode];client.send("ucinewgame");client.send("isready");client.until("readyok",5)
                        best,elapsed,lines=client.play(case["fen"],case.get("moves",[]),nodes=50000)
                        observed=info(lines);replay(case.get("resulting_fen",case["fen"]),best,observed["pv"])
                        row={"repeat":repeat,"position":case["id"],"engine":label,"mode":mode,"bestmove":best,"roundtrip_ms":elapsed,"observed":observed,"request":client.last_request,"uci":lines}
                        rows.append(row);stream.write(json.dumps(row,separators=(",",":"))+"\n");stream.flush()
                        atomic(output/"COST_PROGRESS.json",{"searches":len(rows),"expected":180,"seconds":time.time()-started})
    if inputs!={str(p):sha(p) for p in [*binaries.values(),models,Path(__file__)]}:raise ValueError("cost input changed")
    ratios={}
    for mode in ["classical","mixture","neural"]:
        paired={}
        for row in rows:
            if row["mode"]==mode:paired.setdefault((row["repeat"],row["position"]),{})[row["engine"]]=row
        values=[p["incremental"]["roundtrip_ms"]/p["previous"]["roundtrip_ms"] for p in paired.values()]
        ratios[mode]={"median_incremental_over_previous_ms":statistics.median(values),"all_ratios":values}
    atomic(output/"COST_SUMMARY.json",{"status":"passed","searches":len(rows),"seconds":time.time()-started,"ratios":ratios,"raw_sha256":sha(output/"cost-observations.jsonl"),"full_acceptance":False,"scope":"Different history hashes change TT bucket layout and selective traversal; these are cost observations, not identical-tree proof or an Elo estimate"})
    raise SystemExit(0)
base=root/"runs/search-context-core"
origin=json.loads((base/"COMMANDS.jsonl").read_text().splitlines()[0])["utc_unix"]
deadline=origin+1800
campaign=Campaign(base/"measurements",{"scope":"lookup scaling and paired fixed-node cost under ongoing data replay; no strength inference","original_deadline_unix":deadline},deadline-time.time(),absolute_deadline=deadline)
try:
    campaign.run("compile-lookup-benchmark",["/usr/bin/clang++","-std=c++23","-O3","-DNDEBUG","-DCAISSA_NETWORK_WIDTH=64","-Iinclude","benchmarks/search_context.cpp","build-search-context/libcaissa_core.a","-pthread","-o",str(base/"search-context-bench")],90)
    campaign.run("lookup-benchmark",[str(base/"search-context-bench")],180)
    campaign.run("paired-engine-cost",[sys.executable,str(Path(__file__).resolve()),"--child",str(campaign.output)],240)
    campaign.close("passed cost observations; no Elo estimate")
except BaseException as error:
    campaign.close("failed",{"type":type(error).__name__,"reason":str(error)})
    raise
