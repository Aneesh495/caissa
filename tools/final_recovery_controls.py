"""Missing current-arena continuation controls; no chess actors or old samples."""

import ast
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(value, reason):
    if not value:
        raise ValueError(reason)


def inactive_tree(raw):
    """Remove only the independently enumerated optional power-wait additions."""
    tree = ast.parse(raw)

    class Inactive(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name in {"game", "pair"}:
                require(node.args.args[-1].arg == "power_wait" and isinstance(node.args.defaults[-1], ast.Constant) and node.args.defaults[-1].value is None, "changed optional argument")
                node.args.args.pop()
                node.args.defaults.pop()
            return self.generic_visit(node)

        def visit_If(self, node):
            if ast.unparse(node.test) == "power_wait is not None":
                require(not node.orelse and len(node.body) == 1 and ast.unparse(node.body[0]) in {"power_wait.before_work(force=True)", "power_wait.before_work()"}, "unrecognized optional search branch")
                return None
            if ast.unparse(node.test) == "'power_wait' in config":
                require(ast.unparse(node) == "if 'power_wait' in config:\n    from arena.power_wait import PowerWait\n    power_wait = PowerWait(a.output, config['power_wait'])\n    power_wait.before_work()\nelif (a.output / 'POWER_WAIT_POLICY.json').exists():\n    raise ValueError('cannot remove the saved power wait policy on resume')", "unrecognized optional policy branch")
                return None
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if ast.unparse(node) == "power_wait = None":
                return None
            return self.generic_visit(node)

        def visit_Call(self, node):
            if ast.unparse(node.func) in {"game", "pool.submit"} and node.args and isinstance(node.args[-1], ast.Name) and node.args[-1].id == "power_wait":
                node.args.pop()
            return self.generic_visit(node)

    return ast.dump(Inactive().visit(tree), include_attributes=False)


def main(path):
    os.umask(0o077)
    start = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    output = path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and scope["native_chess_starts"] == 0 and not (output / "STARTED.json").exists(), "one fresh current-source control invocation required")
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))

    def stop(*_):
        raise TimeoutError("current recovery control deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(30, scope["deadline_unix"] - time.time()))
    destinations, commands = set(), []

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink"}:
            raise RuntimeError("recovery controls prohibit network, raw processes and links")
        if event == "subprocess.Popen":
            command = args[1]
            allowed = command == ["git", "cat-file", "--batch"] or len(command) == 7 and command[:6] == ["git", "ls-tree", "-r", "-l", "-z", "--full-tree"] and command[-1] in scope["git_commits"]
            require(allowed and len(commands) < 16, "only bounded read-only Git inspection admitted")
            commands.append(command)
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                if isinstance(name, int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "only owned Git pipe descriptors admitted")
                else:
                    p = Path(name).absolute()
                    require(p == p.resolve() and p.is_relative_to(output), "recovery fixture write escaped namespace")
                    destinations.add(str(p))
                    require(len(destinations) <= 64, "finite recovery fixture inventory exhausted")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "recovery control interpreter differs")
    for name, sha in scope["source_bindings"].items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, "recovery control source/input differs: " + name)
    import arena.run as arena
    import chess
    import chess.pgn
    from arena.power_wait import PowerWait
    from training.corpus import atomic_json
    from verification.recovery_join import source_boundaries
    checks = []
    rule = json.loads((ROOT / "config/recovery-join-v1.json").read_text())
    origins = json.loads((ROOT / "config/recovery-join-artifacts-v1.json").read_text())
    try:
        source_boundaries(ROOT, scope["product_commit"], rule, origins)
    except ValueError as error:
        require(str(error).endswith("producer footprint differs from original forced-recovery evidence: arena"), "unexpected current G11 source refusal")
        checks.append("actual_strict_G11_guard_rejects_changed_current_arena")
    else:
        raise ValueError("historical recovery source guard unexpectedly accepted current arena")
    current = (ROOT / "arena/run.py").read_text()
    original = (output / "ORIGINAL_ARENA.py").read_text()
    require(inactive_tree(current) == ast.dump(ast.parse(original), include_attributes=False), "inactive current arena differs beyond optional power additions")
    checks.append("inactive_power_path_AST_matches_original_without_relaxing_G11_guard")
    forged = current.replace('return record\n', 'return {}\n', 1)
    require(inactive_tree(forged) != ast.dump(ast.parse(original), include_attributes=False), "unrelated recovery edit hidden by optional-path comparison")
    checks.append("unrelated_committed_record_change_does_not_compare_equal")
    fixture = output / "fixture"
    (fixture / "games").mkdir(parents=True)
    (fixture / "pairs").mkdir()
    fen = "7k/5K2/6Q1/8/8/8/8/8 w - - 0 1"
    board = chess.Board(fen)
    mate = None
    for move in list(board.legal_moves):
        b = board.copy(); b.push(move)
        if b.is_checkmate():mate = move.uci();break
    require(mate is not None, "synthetic fixture lacks mate")
    protected = {"profile": "new-current-recovery-controls", "schema": "caissa-arena-game-v1", "pair": 0, "reverse": 0, "opening_id": "new-synthetic-mate", "candidate_color": "white", "initial": fen, "opening_plies": 0, "moves": [mate], "result": "1-0", "termination": "checkmate", "culprit": None, "observations": [], "warmup_ms": [], "uci_handshakes": []}
    actor = {"name": "synthetic control", "command": [str(output / "synthetic-input")], "options": {}}
    (output / "synthetic-input").write_text("not an executable; never launched\n")
    cfg = {"candidate": actor, "opponent": copy.deepcopy(actor), "max_plies": 64, "nodes": 1, "pairs": 1}
    opening = {"id": "new-synthetic-mate", "fen": fen, "moves": []}
    protected_path = fixture / "games/000000-0.json"
    atomic_json(protected_path, protected)
    protected_hash = hashlib.sha256(protected_path.read_bytes()).hexdigest()
    calls = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            calls.append("start"); self.warmup_ms = 0; self.handshake = []; self.last_request = "synthetic request"
        def play(self, *_args, **_kwargs):
            calls.append("play"); return mate, 0, []
        def close(self):calls.append("close")

    class Gate:
        def before_work(self, *, force=False):calls.append("gate-force" if force else "gate-move")

    arena.UciClient = Client
    require(arena.game(cfg, opening, 0, 0, fixture, power_wait=Gate()) == protected and calls == [], "committed record restarted engine or entered power wait")
    pgn = chess.pgn.read_game(io.StringIO(protected_path.with_suffix('.pgn').read_text()))
    require(pgn.end().board().is_checkmate() and pgn.headers['Result'] == '1-0' and hashlib.sha256(protected_path.read_bytes()).hexdigest() == protected_hash, "committed record or reconstructed legal PGN differs")
    checks.append("current_committed_game_unchanged_PGN_reconstructed_without_start_or_wait")
    pair = arena.pair(cfg, opening, 0, fixture, power_wait=Gate())
    require(len(pair["games"]) == 2 and pair["games"][0] == protected and pair["games"][1]["termination"] == 'checkmate' and calls == ['gate-force','start','start','gate-move','play','close','close'], "current partial pair continuation or exact power call order differs")
    prior_calls = list(calls)
    require(arena.pair(cfg, opening, 0, fixture, power_wait=Gate()) == pair and calls == prior_calls and hashlib.sha256(protected_path.read_bytes()).hexdigest() == protected_hash, "committed pair reran work or rewrote protected game")
    checks.append("current_partial_pair_fills_missing_reverse_and_then_reuses_commit")

    class Exhausted:
        def before_work(self, **_kwargs):raise ValueError("synthetic finite power deadline exhausted")

    try:arena.game(cfg, opening, 1, 0, fixture, power_wait=Exhausted())
    except ValueError as error:require(str(error) == 'synthetic finite power deadline exhausted', 'wrong power failure')
    else:raise ValueError('exhausted power gate accepted')
    require(calls == prior_calls and not (fixture / 'games/000001-0.json').exists(), 'power failure started actor or committed outcome')
    checks.append('power_deadline_failure_prevents_start_and_authoritative_commit')
    policy_root = output / 'policy';policy_root.mkdir();clock=[0.0]
    policy={'mode':'wait-between-moves-v1','deadline_unix':60.0}
    gate=PowerWait(policy_root, policy, clock=lambda:clock[0], observer=lambda:{'ac_power':True}, sleeper=lambda _:None)
    try:PowerWait(policy_root,{**policy,'deadline_unix':61.0},clock=lambda:clock[0])
    except ValueError as error:require(str(error)=='original power wait policy or deadline changed','wrong policy rejection')
    else:raise ValueError('changed power policy accepted')
    clock[0]=60.0
    try:gate.before_work()
    except ValueError as error:require(str(error)=='power wait reached original deadline','wrong deadline rejection')
    else:raise ValueError('expired real PowerWait accepted')
    require(json.loads((policy_root/'POWER_WAIT_PROGRESS.json').read_text())['state']=='deadline-exhausted','deadline failure not persisted')
    checks.append('actual_PowerWait_preserves_deadline_and_rejects_policy_change')
    main_root=output/'removed-policy';main_root.mkdir();atomic_json(main_root/'POWER_WAIT_POLICY.json',policy)
    cfg['openings']=str(output/'OPENINGS.json');atomic_json(Path(cfg['openings']),{'openings':[opening]});atomic_json(output/'INPUT.json',cfg)
    sys.argv=['arena.run',str(output/'INPUT.json'),str(main_root),'--workers','1']
    try:arena.main()
    except ValueError as error:require(str(error)=='cannot remove the saved power wait policy on resume','wrong removed-policy refusal')
    else:raise ValueError('removed saved policy accepted')
    require(calls==prior_calls,'removed policy reached native startup')
    checks.append('actual_main_rejects_removed_saved_policy_before_actor_probe')
    result={'status':'passed_current_arena_recovery_controls_only','controls':checks,'read_only_git_commands':len(commands),'native_chess_starts':0,'real_games':0,'synthetic_new_game_fixtures':1,'historical_producers_or_closed_samples_rerun':False,'strict_original_G11_guard_unchanged':True,'full_R09_complete':False,'full_acceptance':False,'elapsed_seconds':time.monotonic()-start}
    (output/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main(sys.argv[1])
