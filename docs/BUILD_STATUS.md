# Build status

Status: implemented development system; full acceptance incomplete; no release and no final absolute Elo.

The native rules, classical evaluation, PVS search, bounded UCI, Chess960, PGN variations, quantized incremental neural evaluator, original selfplay/training, paired arena, independent diagnostic verifier, loopback analysis service and browser board execute. Classical remains the default because the diagnostic neural contribution failed.

The core maintains its ordered reversible-history score fingerprint incrementally. Its source-bound 16 Release and 16 ASan/UBSan cases passed, including a million-transition context reconstruction and sixty mailbox-minimax comparisons. Independent transport reproduced 180 paired cost observations. The loaded-host median runtime ratios were 0.942 classical and 0.957 neural mixture against the previous original executable. [Evidence and limits](notes/search-context.md) distinguish search cost from unmeasured playing strength. No final absolute Elo exists.

The browser can now display optional native search counters and bounded position samples. Actual one/four-thread streams, a 10000-node inspection parity case, ten malformed telemetry controls, cancellation, terminal zero-work output, stale-position clearing and a 390-pixel keyboard/browser flow passed. [The inspection study](notes/search-inspection.md) preserves the original driver timeout and source-bound development evidence. This does not replace the final release browser or strength campaigns.

[The data coverage report](notes/data-coverage.md) scanned every exported input, bound all six array hashes and plotted raw corpus and split distributions. It reports 13216293 unique usable input rows, including 10578434 training rows, with closely matched fixed-bin marginals across splits. This is data-only analysis; full original-data reconstruction, learned validation improvement and playing strength remain separate gates.

The later [full independent reconstruction](../results/full-data-2026-10-25/README.md) passed the data domain: 229582 completed original games, 16522987 raw observations and every exported training/validation/test row. The frozen three-seed learning campaign is running under protocol v3. Data passing does not imply learned-loss or strength passing. [The heuristic study](notes/heuristic-ablations.md) also completed 1056 searches, 528 independent fixed-node replays and twelve rehashed semantic controls; its loaded-host work/depth observations cannot establish Elo.

The subsequent [PVS-off LMR recovery repair](notes/lmr-window-recovery.md) passed all seventeen Release and seventeen ASan/UBSan cases and 48 default-PVS old/new parity pairs. The original failed regression, first parity-driver failure and three remaining selective-oracle discrepancies are retained. This development binary is distinct from the immutable full-model campaign binary.

| Gate | Current evidence | Remaining work |
|---|---|---|
| G01 Rules | 20 exact perft fixtures; multiple independent 100000-position comparisons | Bind final campaign to release source |
| G02 Restoration | Million-transition diagnostic passed; trained-network refresh checks passed | Final selected model/source campaign |
| G03 Draw history | Native claim/automatic/mate/history tests and independent draw replay | Final bundle |
| G04 Protocol | 10000 sequences independently replayed, stop p99 8.47 ms; six rehashed semantic controls rejected; unread-output bound test | Repeat and bind final executable |
| G05 Search | Independent tiny minimax, bounds and mate tests; exhaustive neural cutoff controls; 1056 heuristic queries and 528 fixed-node replays | Full heuristic strength ablations |
| G06 Network | 100000 diagnostic residual probes independently replayed; maximum float64 error 12.20 cp; seven altered-evidence controls and a real failed-bound control | Final full-data selected model must pass the frozen32 cp raw and clamped error endpoints |
| G07 Learning | Full data reconstruction passed: 229582 games and 10578434 distinct training inputs; original failed acquisition/recovery and negative pilots retained | Three full seeds are running; validation-only selection and independent learned-loss verification follow |
| G08 Neural contribution | Failed diagnostic: 4W/8D/84L against classical | Required 4000-game full positive contribution |
| G09 External strength | Warm short diagnostics include 0W/0D/48L against unrestricted Stockfish 19 | Required 2000-game campaign across three settings/opponents |
| G10 Parallel systems | Root sharing, cancellation and race-instrumented native checks | Frozen 1/2/4/8 profiles and strength comparisons |
| G11 Recovery | SIGKILL training/corpus/arena recovery tests executed | Source-bound replay of recovery records |
| G12 Browser | Fresh-origin import, native analysis/cancel, keyboard variation, 390px viewport, service restart/export and malformed FEN exercised | Repeat against final release source |
| G13 Performance | Auditable 640-search four-evaluator 1/2/4/8 pilot; 5097 RSS and 2000 latency samples independently reconstructed; 16 native scalar probes and 13 rehashed controls | Final selected model under controlled host load |
| G14 Semantic verifier | Rehashed semantic controls rejected; separate data, learning, strength and protocol checkers execute | Remaining full campaign schema and independent checks |
| G15 Reproduction | Clean source diagnostic passed; Linux/macOS CI passes | Full saved-model/game/report reproduction |
| G16 Release | Blocked by incomplete and failed full gates | All required gates and final identity audit |

Host: Apple arm64, 8 logical CPU cores, 16 GiB memory. CPU training uses two threads. The native executable does not consult external engines. Stockfish is used only by the separate external arena.

The initial 8-hour generation ceiling was not enforced and elapsed wall time exceeded it. Resumed process duration and monotonic active duration differ on this host. Neither is a measured CPU-hour total. Protocol changes and incomplete timing records must remain visible; the earlier campaign cannot be described as having met that ceiling.

The larger diagnostic preparation has 2181990 training positions from 65272 completed games. Its older split predates functional-input reflection screening, so it cannot satisfy the full data gate. A later v2 preparation independently replays games, quarantines cross-split functional equivalents and excludes frozen study/opening inputs.

The legacy 500-node data generator was stopped after a quality audit found that only 18.53% of a 400-game pilot's samples completed a search depth. The replacement original teacher uses 2000 nodes and seeded root ordering. Its 400-game pilot completed a depth for 98.30% of samples and passed complete independent dataset reconstruction. The new full corpus is separate. Its confirmation deadline expired. The consumer later screened 229582 games and 10578434 training inputs, and arrays were subsequently exported under a separately approved six-hour recovery. That first six-hour reconstruction also expired during host sleep. Its old journal-OFF scratch index is malformed and cannot be resumed. A later WAL-backed, externally pinned continuation passed the complete data reconstruction in 7356.07 active seconds within its unchanged 21600-active/86400-wall limits. No new games were generated and the original failures remain failed. [The failure](ACQUISITION_TIMEOUT.md), [separate fixed-prefix finalization](FIXED_PREFIX_FINALIZATION.md) and [full data receipt](../results/full-data-2026-10-25/FINALIZATION.json) preserve those distinct outcomes. [The counted acquisition protocol](../config/data-generation-v5.json) remains immutable. Data is now verified, while learned-model and strength acceptance remain pending.

The saved `models/diagnostic-v2.cai` is original diagnostic data, not a release-strength model. No full pass, final Elo or Stockfish parity claim follows from the current measurements.

[Durable full-data replay](DURABLE_DATA_REPLAY.md) preserves both failed budgets and the human-directed continuation. [Native race evidence](notes/tactical-races.md) distinguishes the completed 15-case producer from the interrupted 13-case independent replay.
