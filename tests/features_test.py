import random
import chess
import numpy as np
from training.features import features,input_identity
rng=random.Random(49979687);board=chess.Board()
for i in range(2000):
    if board.is_game_over() or board.ply()>150:board=chess.Board()
    fen=board.fen(en_passant='fen');mirror=board.mirror().fen(en_passant='fen')
    assert input_identity(fen)==input_identity(mirror)
    assert np.array_equal(np.sort(features(fen),axis=1),np.sort(features(mirror),axis=1))
    board.push(rng.choice(list(board.legal_moves)))
with_rights=chess.STARTING_FEN;without_rights=with_rights.replace(' KQkq ',' - ')
assert input_identity(with_rights)==input_identity(without_rights)
assert np.array_equal(features(with_rights),features(without_rights))
print('2000 normalized feature identities agree across color reflections and omitted state fields')
