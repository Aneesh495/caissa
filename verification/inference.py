"""Scalar saved-network interpretation, independent of training and C++."""

from verification.network_bytes import QuantizedNetwork


def infer(path, fen):
    return QuantizedNetwork(path).infer(fen)
