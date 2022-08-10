"""Bounded, cached interpretation of network bytes without training imports."""

import hashlib
import struct
import zlib
from pathlib import Path

import chess
import numpy as np


def feature_indices(fen):
    board = chess.Board(fen)
    pieces = board.piece_map()
    if len(pieces) > 32 or any(board.king(color) is None for color in [True, False]):
        raise ValueError("invalid independent feature placement")
    result = np.full((2, 32), 12288, dtype=np.int64)
    for row, perspective in enumerate([board.turn, not board.turn]):
        king = board.king(perspective)
        oriented_king = king if perspective else king ^ 56
        bucket = (oriented_king // 16) * 4 + (oriented_king % 8) // 2
        for column, (square, piece) in enumerate(pieces.items()):
            channel = piece.piece_type - 1 + (0 if piece.color == perspective else 6)
            oriented_square = square if perspective else square ^ 56
            result[row, column] = (bucket * 12 + channel) * 64 + oriented_square
    return result


def signed_round(values, divisor):
    magnitude = (np.abs(values) + divisor // 2) // divisor
    return np.where(values < 0, -magnitude, magnitude)


class QuantizedNetwork:
    def __init__(self, path):
        path = Path(path)
        if not 120 <= path.stat().st_size <= 4 * 1024 * 1024:
            raise ValueError("independent network byte ceiling or truncation")
        raw = path.read_bytes()
        version, feature, count, width, h1, h2, scale, clip = struct.unpack_from(
            "<8I", raw, 8
        )
        if raw[:8] != f"CAISSAN{version}".encode() or version not in [1, 2, 3]:
            raise ValueError("network magic/version mismatch")
        if (feature, count, h1, h2) != (1, 12288, 32, 16) or width not in [32, 64, 128]:
            raise ValueError("unsupported independent network layout")
        if (version, scale, clip) not in [
            (1, 64, 127),
            (2, 1024, 2047),
            (3, 1024, 2047),
        ]:
            raise ValueError("unsupported numerical contract")
        length, checksum, reserved = struct.unpack_from("<QII", raw, 104)
        expected = (
            count * width * 2
            + width * 4
            + 32 * width * 4
            + 32 * 4
            + 16 * 32 * 2
            + 16 * 4
            + 16 * 2
            + 4
        )
        if (
            length != len(raw) - 120
            or length != expected
            or reserved != (1 if version == 3 else 0)
            or checksum != zlib.crc32(raw[120:])
        ):
            raise ValueError("network payload integrity or layout")
        identity = raw[40:104].decode("ascii")
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("invalid training identity in independent network")
        offset = 120

        def take(dtype, shape):
            nonlocal offset
            itemsize = np.dtype(dtype).itemsize
            size = int(np.prod(shape))
            value = (
                np.frombuffer(raw, dtype=dtype, count=size, offset=offset)
                .astype(np.int64)
                .reshape(shape)
            )
            offset += size * itemsize
            if dtype == "<i4" and np.abs(value).max(initial=0) > (
                1 << (20 if version == 1 else 28)
            ):
                raise ValueError("network bias exceeds independent arithmetic bound")
            return value

        embedding = take("<i2", (count, width))
        self.embedding = np.concatenate(
            [embedding, np.zeros((1, width), dtype=np.int64)]
        )
        self.bias0 = take("<i4", (width,))
        self.layers = []
        for rows, columns in [(32, width * 2), (16, 32), (1, 16)]:
            self.layers.append((take("<i2", (rows, columns)), take("<i4", (rows,))))
        if offset != len(raw):
            raise ValueError("trailing independent network bytes")
        self.version, self.width, self.scale, self.clip = version, width, scale, clip
        self.identity = identity
        self.sha256 = hashlib.sha256(raw).hexdigest()

    def evaluate_features(self, features, baseline=None, clip_output=True):
        features = np.asarray(features)
        if (
            features.ndim != 3
            or features.shape[1:] != (2, 32)
            or features.dtype.kind not in "iu"
            or len(features) > 4096
            or features.min(initial=0) < 0
            or features.max(initial=0) > 12288
        ):
            raise ValueError("independent inference feature batch outside bounds")
        activations = (self.embedding[features].sum(axis=2) + self.bias0).clip(
            0, self.clip
        )
        activations = activations.reshape(len(features), self.width * 2)
        for index, (weights, biases) in enumerate(self.layers):
            values = activations @ weights.T + biases
            if index < 2:
                activations = signed_round(values, self.scale).clip(0, self.clip)
            else:
                scores = signed_round(values[:, 0] * 400, self.scale * self.scale)
        if self.version == 3:
            baseline = np.asarray(baseline)
            if (
                baseline.shape != (len(features),)
                or baseline.dtype.kind not in "iu"
                or np.abs(baseline).max(initial=0) > 29871
            ):
                raise ValueError(
                    "independent residual baseline absent or out of contract"
                )
            scores = scores + baseline
        return scores.clip(-29871, 29871) if clip_output else scores

    def infer(self, fen):
        baseline = None
        if self.version == 3:
            from verification.classical import evaluate

            baseline = np.array([evaluate(fen)], dtype=np.int64)
        return int(self.evaluate_features(feature_indices(fen)[None, ...], baseline)[0])
