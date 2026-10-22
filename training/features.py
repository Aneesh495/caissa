"""Pure feature identities shared by data preparation, without training imports."""

import hashlib
import numpy as np

FEATURES = 16 * 12 * 64
PIECES = "PNBRQKpnbrqk"


def features(fen):
    fields = fen.split()
    if len(fields) != 6:
        raise ValueError("FEN requires six fields")
    pieces = []
    r = 7
    f = 0
    kings = [None, None]
    for ch in fields[0]:
        if ch == "/":
            if f != 8:
                raise ValueError("rank width")
            r -= 1
            f = 0
        elif ch in "12345678":
            f += int(ch)
        else:
            if ch not in PIECES or not 0 <= r < 8 or not 0 <= f < 8:
                raise ValueError("bad piece")
            sq = r * 8 + f
            pc = PIECES.index(ch)
            pieces.append((pc, sq))
            if pc in (5, 11):
                kings[pc // 6] = sq
            f += 1
    if r != 0 or f != 8 or None in kings or len(pieces) > 32:
        raise ValueError("invalid board")
    output = np.full((2, 32), FEATURES, dtype=np.int64)
    for perspective in range(2):
        king = kings[perspective] ^ (56 if perspective else 0)
        bucket = ((king // 8) // 2) * 4 + (king % 8) // 2
        for i, (pc, sq) in enumerate(pieces):
            relative = int(pc // 6 != perspective)
            oriented = sq ^ (56 if perspective else 0)
            output[perspective, i] = (
                (bucket * 12 + relative * 6 + pc % 6) * 64
            ) + oriented
    if fields[1] == "b":
        output = output[[1, 0]]
    elif fields[1] != "w":
        raise ValueError("bad side")
    return output


def input_identity(fen):
    """Normalize the mover to white; castling, EP and clocks are absent inputs."""
    parts = fen.split()
    if len(parts) != 6 or parts[1] not in ["w", "b"]:
        raise ValueError("invalid input identity FEN")
    placement = parts[0]
    if parts[1] == "b":
        placement = "/".join(rank.swapcase() for rank in placement.split("/")[::-1])
    return hashlib.sha256(placement.encode("ascii")).digest()


def normalized_fen_from_features(row):
    """Recover the mover-oriented board; rule metadata is absent from inputs."""
    array = np.asarray(row)
    if array.shape != (2, 32):
        raise ValueError("feature row shape")
    cells = {}
    for feature in array[0]:
        index = int(feature)
        if index == FEATURES:
            continue
        if not 0 <= index < FEATURES:
            raise ValueError("feature outside contract")
        square = index % 64
        kind = (index // 64) % 12
        if square in cells:
            raise ValueError("duplicate occupied feature square")
        cells[square] = PIECES[kind]
    ranks = []
    for rank in range(7, -1, -1):
        pieces = []
        empty = 0
        for file in range(8):
            piece = cells.get(rank * 8 + file)
            if piece is None:
                empty += 1
            else:
                if empty:
                    pieces.append(str(empty))
                    empty = 0
                pieces.append(piece)
        if empty:
            pieces.append(str(empty))
        ranks.append("".join(pieces))
    fen = "/".join(ranks) + " w - - 0 1"
    if not np.array_equal(np.sort(features(fen), axis=1), np.sort(array, axis=1)):
        raise ValueError("feature perspectives are inconsistent")
    return fen
