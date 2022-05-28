"""Board-oracle interpretation of frozen original classical contract 1."""

import chess

MID = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 950,
}
END = {
    chess.PAWN: 120,
    chess.KNIGHT: 305,
    chess.BISHOP: 335,
    chess.ROOK: 525,
    chess.QUEEN: 920,
}
PHASE = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}


def center_distance(square):
    return abs(chess.square_file(square) * 2 - 7) + abs(
        chess.square_rank(square) * 2 - 7
    )


def relative_rank(square, color):
    return chess.square_rank(square) if color else 7 - chess.square_rank(square)


def truncated_division(numerator, denominator):
    magnitude = abs(numerator) // denominator
    return magnitude if numerator >= 0 else -magnitude


def evaluate(fen):
    board = chess.Board(fen)
    mid = {True: 0, False: 0}
    end = {True: 0, False: 0}
    phase = 0
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        pawns = list(board.pieces(chess.PAWN, color))
        enemy_pawns = list(board.pieces(chess.PAWN, enemy))
        king = board.king(color)
        target = board.king(enemy)
        if king is None or target is None:
            raise ValueError("classical reference requires both kings")
        ring = int(chess.BB_KING_ATTACKS[target]) | chess.BB_SQUARES[target]
        enemy_pawn_attacks = 0
        for pawn in enemy_pawns:
            enemy_pawn_attacks |= int(chess.BB_PAWN_ATTACKS[enemy][pawn])
        own_occupancy = int(board.occupied_co[color])
        units = attackers = 0
        for kind in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            occupied = list(board.pieces(kind, color))
            mid[color] += len(occupied) * MID[kind]
            end[color] += len(occupied) * END[kind]
            phase += len(occupied) * PHASE[kind]
            for square in occupied:
                rank = relative_rank(square, color)
                centrality = 14 - center_distance(square)
                controlled = int(board.attacks(square))
                if kind != chess.PAWN:
                    mobility = (
                        controlled & ~own_occupancy & ~enemy_pawn_attacks
                    ).bit_count()
                    factor = {
                        chess.KNIGHT: 4,
                        chess.BISHOP: 5,
                        chess.ROOK: 2,
                        chess.QUEEN: 1,
                    }[kind]
                    mid[color] += factor * (
                        mobility - (12 if kind == chess.QUEEN else 4)
                    )
                    end[color] += (factor + 1) * (mobility - 4)
                    hits = (controlled & ring).bit_count()
                    if hits:
                        attackers += 1
                        units += hits * (
                            5 if kind == chess.QUEEN else 3 if kind == chess.ROOK else 2
                        )
                file = chess.square_file(square)
                supported = any(
                    int(chess.BB_PAWN_ATTACKS[enemy][square]) & chess.BB_SQUARES[p]
                    for p in pawns
                )
                if kind == chess.PAWN:
                    mid[color] += rank * 5 + centrality * 2
                    end[color] += rank * 7
                    if not any(abs(chess.square_file(p) - file) == 1 for p in pawns):
                        mid[color] -= 14
                        end[color] -= 20
                    if sum(chess.square_file(p) == file for p in pawns) > 1:
                        mid[color] -= 9
                        end[color] -= 17
                    passed = not any(
                        abs(chess.square_file(p) - file) <= 1
                        and relative_rank(p, color) > rank
                        for p in enemy_pawns
                    )
                    if passed:
                        mid[color] += rank * rank * 2
                        end[color] += rank * rank * 5
                        distance = lambda king: max(
                            abs(chess.square_file(square) - chess.square_file(king)),
                            abs(chess.square_rank(square) - chess.square_rank(king)),
                        )
                        end[color] += rank * (distance(target) - distance(king)) * 2
                    if supported:
                        mid[color] += 8 + rank * 2
                        end[color] += 10 + rank * 3
                    next_square = square + (8 if color else -8)
                    if (
                        0 <= next_square < 64
                        and board.piece_at(next_square) is not None
                    ):
                        mid[color] -= 6
                        end[color] -= 9
                elif kind == chess.KNIGHT:
                    mid[color] += centrality * 6 - 36
                    end[color] += centrality * 4 - 24
                    if (
                        3 <= rank <= 5
                        and supported
                        and not enemy_pawn_attacks & chess.BB_SQUARES[square]
                    ):
                        mid[color] += 20
                elif kind == chess.BISHOP:
                    mid[color] += centrality * 2
                    end[color] += centrality * 3
                elif kind == chess.ROOK:
                    if not any(chess.square_file(p) == file for p in pawns):
                        mid[color] += 15
                        if not any(chess.square_file(p) == file for p in enemy_pawns):
                            mid[color] += 12
                    if rank == 6:
                        mid[color] += 20
                        end[color] += 30
                elif kind == chess.QUEEN:
                    end[color] += centrality * 2
                    if rank > 2:
                        mid[color] -= rank * 2
        if len(board.pieces(chess.BISHOP, color)) >= 2:
            mid[color] += 28
            end[color] += 45
        if center_distance(king) < 6:
            mid[color] -= 25
        end[color] += (14 - center_distance(king)) * 6
        king_rank = relative_rank(king, color)
        if king_rank <= 1:
            for file in range(
                max(0, chess.square_file(king) - 1),
                min(7, chess.square_file(king) + 1) + 1,
            ):
                shelter = any(
                    chess.square_file(p) == file
                    and king_rank < relative_rank(p, color) <= king_rank + 2
                    for p in pawns
                )
                if not shelter:
                    mid[color] -= 18
        if attackers >= 2:
            mid[enemy] -= min(250, units * attackers * 2)
    phase = min(24, max(0, phase))
    white = truncated_division(
        (mid[True] - mid[False]) * phase + (end[True] - end[False]) * (24 - phase), 24
    )
    relative = (white if board.turn else -white) + 12
    return min(29871, max(-29871, relative))
