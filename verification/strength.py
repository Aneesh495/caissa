"""Independent campaign replay, resource checks and evaluator-contribution gate."""

import argparse
import json
import math
from pathlib import Path

import chess
import chess.pgn

from verification.verify import Rejection, independent_statistics, load, replay_game
from verification.dataset import digest


class StrengthFailure(Rejection):
    def __init__(self, reason, observed):
        super().__init__(reason)
        self.observed = observed


def elo(score):
    if score <= 0:
        return "-infinity"
    if score >= 1:
        return "+infinity"
    return 400 * math.log10(score / (1 - score))


def principal_variations(board, lines):
    for line in lines:
        if not isinstance(line, str) or len(line) > 16384:
            raise Rejection("arena contains an oversized or malformed protocol line")
        if line.startswith("info depth ") and " pv " in line:
            replay = board.copy(stack=False)
            for text in line.split(" pv ", 1)[1].split():
                try:
                    move = chess.Move.from_uci(text)
                except ValueError as error:
                    raise Rejection(
                        "arena principal variation has malformed notation"
                    ) from error
                if move not in replay.legal_moves:
                    raise Rejection(
                        "arena principal variation is illegal from its actual root"
                    )
                replay.push(move)


def validate_observations(game, config, require_requests=False):
    board = chess.Board(game["initial"])
    observations = {}
    for row in game["observations"]:
        if "ply" in row:
            if row["ply"] in observations:
                raise Rejection("duplicate arena observation at the same ply")
            observations[row["ply"]] = row
    for ply, text in enumerate(game["moves"]):
        if ply >= game["opening_plies"]:
            row = observations.pop(ply, None)
            if row is None or row.get("move") != text:
                raise Rejection("played move has no matching raw protocol observation")
            elapsed = row.get("milliseconds")
            if (
                not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed)
                or elapsed < 0
            ):
                raise Rejection("invalid arena move duration")
            if "milliseconds" in config and elapsed > config[
                "milliseconds"
            ] + config.get("transport_allowance_ms", 100):
                raise Rejection(
                    "over-budget move was silently accepted instead of a time loss"
                )
            request = row.get("request")
            if require_requests and request is None:
                raise Rejection("full match lacks actual UCI budget/history requests")
            if request is not None:
                expected_position = (
                    "position fen "
                    + game["initial"]
                    + (" moves " + " ".join(game["moves"][:ply]) if ply else "")
                )
                expected_go = (
                    f"go nodes {config['nodes']}"
                    if "nodes" in config
                    else f"go movetime {config['milliseconds']}"
                )
                if (
                    request["position"] != expected_position
                    or request["go"] != expected_go
                ):
                    raise Rejection(
                        "recorded UCI budget/history differs from actual match position"
                    )
                measured = (
                    request["completed_monotonic_ns"] - request["started_monotonic_ns"]
                ) / 1e6
                if measured < 0 or abs(measured - elapsed) > 1e-9:
                    raise Rejection(
                        "arena duration disagrees with raw request timestamps"
                    )
            lines = row.get("uci", [])
            if (
                not lines
                or not lines[-1].startswith("bestmove ")
                or lines[-1].split()[1] != text
            ):
                raise Rejection("arena best move disagrees with raw UCI output")
            principal_variations(board, lines)
        move = chess.Move.from_uci(text)
        if move not in board.legal_moves:
            raise Rejection("illegal move in arena transcript")
        board.push(move)
    reason = game["termination"]
    if reason == "time-loss":
        row = observations.pop(len(game["moves"]), None)
        if row is None or row.get("milliseconds", 0) <= config[
            "milliseconds"
        ] + config.get("transport_allowance_ms", 100):
            raise Rejection("time-loss result lacks an actual over-budget observation")
        if game["culprit"] != ("white" if board.turn else "black"):
            raise Rejection("time loss assigned to the wrong actor")
    elif reason == "illegal-move":
        row = observations.pop(len(game["moves"]), None)
        if row is None:
            raise Rejection("illegal-move loss has no attempted move")
        try:
            attempted = chess.Move.from_uci(row["move"])
        except ValueError:
            attempted = None
        if attempted is not None and attempted in board.legal_moves:
            raise Rejection("legal move falsely declared illegal")
    elif reason == "protocol-failure":
        row = observations.pop(len(game["moves"]), None)
        if row is None or not row.get("failure"):
            raise Rejection("protocol forfeit lacks the raw failure")
    elif reason == "crash":
        if not any(
            row.get("startup_failure") and row.get("color") == game["culprit"]
            for row in game["observations"]
        ):
            raise Rejection("startup crash lacks actor-specific evidence")
    if observations:
        raise Rejection("unexpected observation beyond the completed game")


def verify_campaign(
    campaign,
    opening_file,
    expected_engine,
    expected_network=None,
    protocol=None,
    neural=False,
    require_full=False,
):
    campaign = Path(campaign)
    identity = load(campaign / "CONFIG.json")
    config = identity["config"]
    opening_document = load(opening_file)
    openings = opening_document["openings"]
    if identity["openings_sha256"] != digest(opening_file):
        raise Rejection("strength campaign uses different frozen openings")
    if not openings or len({row["id"] for row in openings}) != len(openings):
        raise Rejection("empty or duplicated opening identities")
    candidate = identity["executables"]["candidate"]
    opponent = identity["executables"]["opponent"]
    for role, actor in [("candidate", candidate), ("opponent", opponent)]:
        if (
            actor["options"] != config[role]["options"]
            or actor["command"] != config[role]["command"]
        ):
            raise Rejection(
                "arena actor configuration and executable identity disagree"
            )
    if candidate["executable"] != expected_engine:
        raise Rejection(
            "strength candidate executable differs from frozen native engine"
        )
    if neural:
        if opponent["executable"] != expected_engine:
            raise Rejection("neural comparison changed the search executable")
        if (
            candidate.get("network_sha256") != expected_network
            or candidate["options"].get("Use Neural") is not True
        ):
            raise Rejection(
                "neural comparison used different weights or disabled the network"
            )
        if opponent["options"].get("Use Neural", False) is not False:
            raise Rejection("classical control enabled a neural evaluator")
        removed = {"Use Neural", "EvalFile", "Scalar Neural", "Neural Weight"}
        left = {k: v for k, v in candidate["options"].items() if k not in removed}
        right = {k: v for k, v in opponent["options"].items() if k not in removed}
        if left != right:
            raise Rejection(
                "evaluator comparison changed unrelated search resources/options"
            )
    if require_full:
        if protocol is None:
            raise Rejection("full strength verification requires the frozen protocol")
        rules = protocol["matches"]
        if neural and (
            rules["neural_pairs"] < 2000
            or rules["minimum_neural_gain_elo"] < 50
            or rules["minimum_neural_lower_elo_exclusive"] < 0
        ):
            raise Rejection(
                "protocol weakens the mandatory neural contribution endpoint"
            )
        if (
            rules.get("confidence") != 0.95
            or rules.get("bootstrap_resamples") != 20000
            or rules.get("bootstrap_seed") != 104729
        ):
            raise Rejection("unsupported full statistical contract")
        if config.get("milliseconds") != rules["milliseconds"] or "nodes" in config:
            raise Rejection("full strength campaign changed its time budget")
        for actor in [candidate, opponent]:
            if (
                actor["options"].get("Threads") != rules["threads"]
                or actor["options"].get("Hash") != rules["hash_mib"]
            ):
                raise Rejection("full strength resources differ from protocol")
        if (
            config.get("warmup_nodes") != rules["warmup_nodes"]
            or config.get("transport_allowance_ms") != rules["transport_allowance_ms"]
            or config["max_plies"] != rules["maximum_plies"]
        ):
            raise Rejection("strength warmup, transport or adjudication budget changed")
        declarations = load(campaign / "PROTOCOL.json")
        for role in ["candidate", "opponent"]:
            if (
                declarations[role]["executable_sha256"]
                != identity["executables"][role]["executable"]
            ):
                raise Rejection("actual UCI preflight identity differs")
            declared = declarations[role]["declared_options"]
            options = identity["executables"][role]["options"]
            expected_commands = [
                (
                    f"setoption name {name}"
                    if declared.get(name, {}).get("type") == "button"
                    else f"setoption name {name} value {str(value).lower() if isinstance(value,bool) else value}"
                )
                for name, value in options.items()
            ]
            if declarations[role].get("configuration_commands") != expected_commands:
                raise Rejection(
                    "actual configured UCI options differ from declared resources"
                )
            if any(
                name not in declared
                for name in identity["executables"][role]["options"]
            ):
                raise Rejection(
                    "strength configuration requested an undeclared engine option"
                )
        if (
            neural
            and candidate["options"].get("Neural Weight", 100)
            != protocol["network"]["neural_weight"]
        ):
            raise Rejection("neural mixture differs from prospective protocol")
    paths = sorted((campaign / "pairs").glob("*.json"))
    if len(paths) != config["pairs"]:
        raise Rejection(
            "strength campaign has not completed its declared opening-pair sample"
        )
    failures = {}

    def records():
        for number, path in enumerate(paths):
            pair = load(path)
            opening = openings[number % len(openings)]
            if pair["pair"] != number or pair["opening_id"] != opening["id"]:
                raise Rejection("paired opening identity differs from frozen schedule")
            if len(pair["games"]) != 2:
                raise Rejection("strength opening lacks its reversed-color game")
            for reverse, game in enumerate(pair["games"]):
                expected_initial = chess.Board(
                    opening.get("fen", chess.STARTING_FEN)
                ).fen(en_passant="fen")
                if (
                    game["initial"] != expected_initial
                    or game["opening_id"] != opening["id"]
                    or game["pair"] != number
                    or game["reverse"] != reverse
                ):
                    raise Rejection(
                        "game identity/initial state differs from frozen pair"
                    )
                if (
                    game["opening_plies"] != len(opening["moves"])
                    or game["moves"][: len(opening["moves"])] != opening["moves"]
                ):
                    raise Rejection("game did not play its frozen opening prefix")
                validate_observations(game, config, require_full)
                if game["termination"] in [
                    "time-loss",
                    "crash",
                    "illegal-move",
                    "protocol-failure",
                ]:
                    failures[game["termination"]] = (
                        failures.get(game["termination"], 0) + 1
                    )
            yield pair

    computed = independent_statistics(records())
    saved = load(campaign / "SUMMARY.json")
    if require_full:
        if (
            saved.get("statistics_version") != 2
            or saved.get("bootstrap", {}).get("resamples")
            != protocol["matches"]["bootstrap_resamples"]
            or saved.get("bootstrap", {}).get("seed")
            != protocol["matches"]["bootstrap_seed"]
        ):
            raise Rejection("full statistical procedure differs from frozen protocol")
    for key, value in computed.items():
        actual = saved.get(key)
        if isinstance(value, float):
            if not isinstance(actual, (int, float)) or abs(value - actual) > 1e-12:
                raise Rejection(
                    "independently recomputed strength statistic differs: " + key
                )
        elif isinstance(value, list):
            if (
                not isinstance(actual, list)
                or len(value) != len(actual)
                or any(abs(a - b) > 1e-12 for a, b in zip(value, actual))
            ):
                raise Rejection("independently recomputed strength interval differs")
        elif actual != value:
            raise Rejection("independently recomputed strength count differs: " + key)
    if saved.get("failures") != failures:
        raise Rejection("strength report excluded or miscounted failures")
    computed["failures"] = failures
    computed["elo_difference"] = elo(computed["score"])
    computed["elo_95"] = [elo(score) for score in computed["score_95"]]

    def same_elo(left, right):
        if isinstance(left, str) or isinstance(right, str):
            return left == right
        return isinstance(left, (int, float)) and math.isclose(
            left, right, rel_tol=1e-12, abs_tol=1e-8
        )

    if (
        not same_elo(saved.get("elo_difference"), computed["elo_difference"])
        or not isinstance(saved.get("elo_95"), list)
        or len(saved["elo_95"]) != 2
        or any(
            not same_elo(left, right)
            for left, right in zip(saved["elo_95"], computed["elo_95"])
        )
    ):
        raise Rejection("strength Elo transform or endpoint censoring differs")
    if computed["unfinished_games"]:
        raise StrengthFailure(
            "declared strength sample contains unfinished games", computed
        )
    if require_full and neural:
        minimum = protocol["matches"]["neural_pairs"]
        if computed["complete_pairs"] < minimum:
            raise StrengthFailure(
                "full neural contribution sample is too small", computed
            )
        estimate, lower = computed["elo_difference"], computed["elo_95"][0]
        if (
            not (
                estimate == "+infinity"
                or isinstance(estimate, (int, float))
                and estimate >= protocol["matches"]["minimum_neural_gain_elo"]
            )
            or not isinstance(lower, (int, float))
            or lower <= protocol["matches"]["minimum_neural_lower_elo_exclusive"]
        ):
            raise StrengthFailure(
                "full neural contribution failed its predeclared Elo endpoint", computed
            )
    return {
        "status": "passed",
        "scope": (
            "full-neural-contribution"
            if require_full and neural
            else "independent-strength-replay"
        ),
        "full_acceptance": False,
        "statistics": computed,
        "candidate_identity": candidate,
        "opponent_identity": opponent,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--network-sha256")
    parser.add_argument(
        "--protocol", type=Path, default=Path("config/protocol-v2.json")
    )
    parser.add_argument("--neural", action="store_true")
    parser.add_argument("--require-full", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_campaign(
            args.campaign,
            args.openings,
            args.engine_sha256,
            args.network_sha256,
            load(args.protocol),
            args.neural,
            args.require_full,
        )
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, OSError) as error:
        result = {"status": "rejected", "reason": str(error), "full_acceptance": False}
        if isinstance(error, StrengthFailure):
            result["observed"] = error.observed
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
