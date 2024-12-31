# Two-minute Caissa demo

## Before presenting

Download and extract the release for your platform. With Node.js 24, open a
terminal in the extracted directory and start the local board.

```sh
./build/caissa --version
node dist/analysis-service/server.js
```

The engine should print `Caissa 0.1.0`. Open the board at
[127.0.0.1:8765](http://127.0.0.1:8765). Once extracted, the engine and board
run locally without an internet connection. [Release downloads](https://github.com/Aneesh495/caissa/releases/tag/v0.1.0)

## Live walkthrough

1. Paste this position into **FEN** and click **Load**. It is White to move
   on move 28 from the release match against unrestricted Stockfish 19,
   opening `caissa-opening-0004`, with Caissa playing White.

   ```text
   2Nr1k1n/5p1p/6p1/2PN1Q2/3P3P/4P1P1/P4P2/R3K2R w KQ - 0 28
   ```

2. Set **Time** to **1 second**, **Threads** to **1**, and **Lines** to **3**.
   Enable **Inspect search counters and sample positions**, then click
   **Analyze position**. Look for `#3`, meaning mate in three. One line starts
   with `f5f6` and continues **Qf6 Kg8 Nde7+ Kf8 Qxh8#**.
3. Under **Search inspection**, show visited nodes and transposition-table
   hits. Click **Play line** next to a mate line to add those moves to the
   board. The status should read **Checkmate**.
4. Open **Import or export PGN** under **Game & variations** and click
   **Export current tree**. The PGN includes the starting FEN and played line.

## Terminal fallback

From the extracted release, run the same position directly through the engine.

```sh
./build/caissa --search 6 '2Nr1k1n/5p1p/6p1/2PN1Q2/3P3P/4P1P1/P4P2/R3K2R w KQ - 0 28'
```

The depth-six search reports `f5f6` as its best move and prints the principal
variation as JSON. The [live analysis screenshot](images/release-analysis.png)
shows the browser result.

## What to say about the results

Caissa ships a classical evaluator and includes its trained neural evaluator
as an experiment. Classical won the direct comparison. The released engine's
192-game test produced a relative Elo estimate under fixed match conditions.
Against unrestricted Stockfish 19 it was −286 Elo, with a 95% interval of
−394 to −206, including four Stockfish time forfeits. The match report
includes the forfeit sensitivity and instructions to replay the games.
[Strength report](RELEASE_STRENGTH.md) · [Model card](MODEL_CARD.md)
