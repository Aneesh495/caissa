# Real browser integration

`tools.browser_campaign` drives production routes in Chromium at 1280 and 390
pixels. Each viewport starts with a fresh browser context. It imports a PGN,
adds c4 with the keyboard, promotes that branch, exports the real tree, flips
the board, analyzes, cancels, changes position, rejects malformed FEN, restarts
the service and restores the selected line from browser storage. Screenshots,
Playwright traces, actual HTTP bodies and DOM observations are retained.

Analysis normally uses the unchanged classical evaluator. A server started
with `CAISSA_NETWORK=/absolute/path/to/selected-v4.cai` opts into the original
experimental ten-percent neural blend. The room labels that mode explicitly.
The native service loads the original network before enabling it, uses deferred
neural state and returns its actual network identity in the session and stream.
There is no training or model selection in a browser run.

Changing position or starting another search clears old lines and counters.
Stopping a search retains the last completed lines for that position. The
campaign checks actual worker reaping and rejects a previous service token
after restart.

Run only on an idle host:

```sh
npm ci --ignore-scripts
npm run build
npx playwright install --with-deps chromium
python -m tools.browser_campaign --engine build/caissa \
  --network results/precision-v4-2026-10-25/selected-v4.cai \
  --output runs/browser-component
```

The owner acquires the existing exclusive host lease and fixes a 240-second
wall/active ceiling, 256 MiB additional-output ceiling and 10 GiB reserve. An
existing output is never overwritten or resumed. The evidence is a bounded
integration component, not a full project acceptance receipt.

`verification.browser` independently reconstructs rendered pieces from FEN,
all edited/exported PGN branches with python-chess, every recorded complete
native principal variation and best move, selected-network identities and
actual neural-evaluation counters. It verifies the complete artifact inventory,
viewport dimensions, focus, stale-state clearing, persistence and cleanup.
Rehashed semantic forgeries exercise its real CLI. The full-bundle adapter
stages exact raw files and keeps G12 pending until final-source binding and
fresh final execution are complete. A saved success flag or screenshot alone
does not pass the gate.

The trace API captures browser operations and network activity; assertions are
recorded separately in our observations and independently reconstructed. See
the [Playwright tracing contract](https://playwright.dev/docs/api/class-tracing).
