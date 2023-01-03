"""Independent complete board/history and integer-network state oracle.

Uses python-chess for state evolution and network bytes for sparse sums and
dense inference. Does not import any native producer, search or training code.
"""

import chess
import numpy as np

from verification.classical import evaluate as classical
from verification.network_bytes import feature_indices

MASK = (1 << 64) - 1


def mix(value):
    value = (value + 0x9E3779B97F4A7C15) & MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
    return value ^ (value >> 31)


def hexadecimal(value):
    return f"{value:016x}"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def same_type(left, right):
    if type(left) is not type(right):
        return False
    return (
        not isinstance(right, list)
        or len(left) == len(right)
        and all(same_type(a, b) for a, b in zip(left, right, strict=True))
    )


class Shadow:
    def __init__(self, network):
        self.network = network
        self.reset(chess.STARTING_FEN, False)

    def reset(self, fen, chess960=False):
        self.board = chess.Board(fen, chess960=chess960)
        require(self.board.is_valid(), "restoration oracle invalid reset board")
        self.synthetic = 0
        self.stack = []
        self.history = [self.repetition_key()]

    def rights(self):
        result = []
        for color in [chess.WHITE, chess.BLACK]:
            king = self.board.king(color)
            rights = [64, 64]
            for square in chess.scan_forward(
                self.board.castling_rights & self.board.occupied_co[color]
            ):
                wing = 1 if chess.square_file(square) > chess.square_file(king) else 0
                require(
                    rights[wing] == 64, "restoration duplicate oracle castling wing"
                )
                rights[wing] = square
            result.append(rights)
        return result

    def key(self):
        value = 0 if self.board.turn else mix(10000)
        for square, piece in self.board.piece_map().items():
            code = piece.piece_type + (0 if piece.color else 8)
            value ^= mix(code * 64 + square)
        for color, rights in enumerate(self.rights()):
            for wing, square in enumerate(rights):
                if square != 64:
                    value ^= mix(11000 + color * 128 + wing * 64 + square)
        if self.board.ep_square is not None:
            value ^= mix(12000 + self.board.ep_square)
        return value

    def repetition_key(self):
        value = self.key()
        if self.board.ep_square is not None and not self.board.has_legal_en_passant():
            value ^= mix(12000 + self.board.ep_square)
        return value

    def push(self, text):
        before = (len(self.history), self.synthetic)
        if text == "null":
            require(not self.board.is_check(), "restoration oracle null while checked")
            half, full = self.board.halfmove_clock, self.board.fullmove_number
            self.board.push(chess.Move.null())
            # Synthetic nulls change turn/EP only. They do not advance game
            # clocks or append real repetition observations in this contract.
            self.board.halfmove_clock, self.board.fullmove_number = half, full
            self.synthetic += 1
        else:
            move = self.board.parse_uci(text)
            require(move in self.board.legal_moves, "restoration oracle illegal move")
            self.board.push(move)
            self.history.append(self.repetition_key())
        self.stack.append(before)

    def pop(self):
        require(self.stack, "restoration oracle undo at root")
        size, self.synthetic = self.stack.pop()
        self.board.pop()
        del self.history[size:]

    def check(self, actual):
        require(
            isinstance(actual, dict) and "error" not in actual,
            "native restoration request rejected",
        )
        board = self.board
        fen = board.fen(shredder=board.chess960, en_passant="fen")
        rights = self.rights()
        key, repetition = self.key(), self.repetition_key()
        count = min(len(self.history), board.halfmove_clock + 1)
        polynomial, power = 0, 1
        for value in reversed(self.history[-count:]):
            polynomial = (polynomial + value * power) & MASK
            power = (power * 0x9E3779B185EBCA87) & MASK
        search = key ^ mix(
            polynomial
            ^ mix(board.halfmove_clock + 20000)
            ^ ((count * 0xD6E8FEB86659FD93) & MASK)
        )
        if self.synthetic:
            search ^= mix(30000 + self.synthetic)
        placement = [0] * 64
        for square, piece in board.piece_map().items():
            placement[square] = piece.piece_type + (0 if piece.color else 8)
        features = feature_indices(fen)
        absolute = features if board.turn else features[::-1]
        accumulator = self.network.embedding[absolute].sum(axis=1) + self.network.bias0
        baseline = classical(fen)
        neural = int(
            self.network.evaluate_features(
                features[None, ...], np.array([baseline], dtype=np.int64)
            )[0]
        )
        numerator = neural * 10 + baseline * 90
        blended = (abs(numerator) // 100) * (-1 if numerator < 0 else 1)
        expected = {
            "fen": fen,
            "chess960": board.chess960,
            "key": hexadecimal(key),
            "recomputed_key": hexadecimal(key),
            "repetition_key": hexadecimal(repetition),
            "search_key": hexadecimal(search),
            "synthetic_depth": self.synthetic,
            "halfmove": board.halfmove_clock,
            "fullmove": board.fullmove_number,
            "side": 0 if board.turn else 1,
            "ep": board.ep_square if board.ep_square is not None else 64,
            "depth": len(self.stack),
            "coherent": True,
            "board": placement,
            "rights": rights,
            "occupied": [
                hexadecimal(int(board.occupied_co[color]))
                for color in [chess.WHITE, chess.BLACK]
            ],
            "bitboards": [
                [hexadecimal(0)]
                + [hexadecimal(int(board.pieces(kind, color))) for kind in range(1, 7)]
                for color in [chess.WHITE, chess.BLACK]
            ],
            "history": [hexadecimal(value) for value in self.history],
            "repetitions": sum(value == repetition for value in self.history[-count:]),
            "accumulator": accumulator.tolist(),
            "buckets": [
                ((board.king(color) ^ (0 if color else 56)) // 16) * 4
                + ((board.king(color) ^ (0 if color else 56)) % 8) // 2
                for color in [chess.WHITE, chess.BLACK]
            ],
            "accumulator_key": hexadecimal(key),
            "full_refresh_equal": True,
            "baseline": baseline,
            "scalar": blended,
            "native": blended,
            "refreshed": blended,
        }
        require(
            set(actual) == set(expected), "restoration state field inventory differs"
        )
        for field, value in expected.items():
            observed = actual[field]
            require(
                same_type(observed, value),
                "restoration state wire type differs: " + field,
            )
            if observed != value:
                raise ValueError("independent restoration state differs: " + field)
        return expected


def state_commands(rule, count):
    """Predeclared reachable command schedule, not native move generation."""
    import random

    rng = random.Random(rule["seed"])
    board = None
    for index in range(count):
        reset = (
            board is None
            or not any(board.legal_moves)
            or len(board.move_stack) >= rule["maximum_game_ply"]
        )
        if reset:
            epoch = index // rule["maximum_game_ply"]
            fixture = rule["fixtures"][epoch % len(rule["fixtures"])]
            board = chess.Board(fixture["fen"], chess960=fixture["chess960"])
            yield {
                "kind": "reset",
                "index": index,
                "fen": fixture["fen"],
                "chess960": fixture["chess960"],
            }
        prefix = fixture.get("prefix", [])
        forced = (
            prefix[len(board.move_stack)]
            if len(board.move_stack) < len(prefix)
            else None
        )
        if index % rule["null_every"] == 0 and not board.is_check():
            yield {"kind": "null", "index": index}
        legal = sorted(board.uci(move) for move in board.legal_moves)
        move = forced if forced is not None else legal[rng.randrange(len(legal))]
        require(move in legal, "restoration forced fixture move absent")
        yield {"kind": "trial", "index": index, "move": move}
        board.push_uci(move)
