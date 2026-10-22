# Dependencies and research provenance

Native runtime: C++23 standard library and operating-system threads. Build: CMake >=3.25 and Ninja. Tested host at project creation: macOS arm64, Apple clang 21, CMake 4.0.3, 8 logical cores, 16 GiB unified RAM. Linux is a target requiring its own verification.

Training: Python 3.12.14, PyTorch 2.8.0 (BSD-3-Clause), NumPy 2.2.6 (BSD-3-Clause). The lockfile records transitive packages. Independent test oracle: python-chess/chess 1.11.2 (GPL-3.0-or-later), isolated from native runtime. No source or network weights from an external engine are included.

Research references, checked 2026-10-22:

- [FIDE laws](https://handbook.fide.com/chapter/e012023): legal moves, draw conditions, Chess960 castling.
- [UCI protocol documentation](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html): protocol interoperability. The older UCI-and-Commands URL returned 404.
- [NNUE principles](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html) and [architecture history](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue_architecture_history.html): attributed algorithmic context, not donated implementation.
- [Fishtest design](https://official-stockfish.github.io/docs/fishtest-wiki/Creating-my-first-test.html) and [statistics](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html): paired experiments and uncertainty.
- [python-chess API](https://python-chess.readthedocs.io/en/latest/core.html): independent standard/Chess960 oracle.

The user's existing Syzygy repository is a Haskell algebraic-geometry system. Caissa's optional tablebase terminology refers only to chess endgames. Existing Lockstep and VectorTick repositories are exchange and columnar-data systems; none supplies the chess core.
