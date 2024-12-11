# Caissa quick start

Extract the release archive and open a terminal in the extracted directory.
The engine supports standard chess and Chess960. It uses classical evaluation
by default and runs offline.

## UCI engine

Add `build/caissa` as a UCI engine in your chess GUI. To use it from a terminal,
start `./build/caissa` and enter these commands one at a time.

```text
uci
isready
position startpos moves e2e4 e7e5
go nodes 10000
quit
```

Wait for `uciok`, `readyok` and `bestmove` before sending the next command.
Run `./build/caissa --perft 4` for a quick installation check. The expected
result is `197281`.

## Local analysis board

With Node.js 24 installed, run `node dist/analysis-service/server.js` from the
extracted directory. Open [the local board](http://127.0.0.1:8765) to import a
PGN or FEN, edit variations and analyze a position. Press Ctrl+C in the
terminal to stop the service.

## Experimental evaluator

The bundled original network was weaker than the classical evaluator in
controlled games. To try the trained ten-percent blend in a UCI session, load
these settings after `uciok`.

```text
setoption name EvalFile value models/experimental-v4.cai
setoption name Neural Weight value 10
setoption name Use Neural value true
isready
```

The [Caissa repository](https://github.com/Aneesh495/caissa) has source,
match records, the model card and benchmark limitations.
