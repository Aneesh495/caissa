# Build status

Status: implemented development system; full acceptance incomplete; no release and no final absolute Elo.

The native rules, classical evaluation, PVS search, bounded UCI, Chess960, PGN variations, quantized incremental neural evaluator, original selfplay/training, paired arena, independent diagnostic verifier, loopback analysis service and browser board execute. Classical remains the default because the diagnostic neural contribution failed.

| Gate | Current evidence | Remaining work |
|---|---|---|
| G01 Rules | 20 exact perft fixtures; multiple independent 100000-position comparisons | Bind final campaign to release source |
| G02 Restoration | Million-transition diagnostic passed; trained-network refresh checks passed | Final selected model/source campaign |
| G03 Draw history | Native claim/automatic/mate/history tests and independent draw replay | Final bundle |
| G04 Protocol | 10000 sequences independently replayed, stop p99 8.47 ms; six rehashed semantic controls rejected; unread-output bound test | Repeat and bind final executable |
| G05 Search | Independent tiny minimax, bounds and mate tests; exhaustive neural cutoff controls | Full heuristic strength ablations |
| G06 Network | 100000 diagnostic residual probes independently replayed; maximum float64 error 12.20 cp; seven altered-evidence controls and a real failed-bound control | Final full-data selected model must pass the frozen32 cp raw and clamped error endpoints |
| G07 Learning | Original diagnostic seeds complete; all three mixture-aware strong-teacher small pilots overfit and are retained as failed; full searched corpus exceeded its confirmation deadline and stopped | 10 million distinct training inputs after screening; three full runs |
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

The legacy 500-node data generator was stopped after a quality audit found that only 18.53% of a 400-game pilot's samples completed a search depth. The replacement original teacher uses 2000 nodes and seeded root ordering. Its 400-game pilot completed a depth for 98.30% of samples and passed complete independent dataset reconstruction. The new full corpus is separate. Its confirmation deadline expired. The consumer later screened 229582 games and 10578434 training inputs, and arrays were subsequently exported under a separately approved six-hour recovery. That first six-hour reconstruction also expired during host sleep. Its old journal-OFF scratch index is malformed and cannot be resumed. A new WAL-backed, externally pinned continuation was implemented and tested; active continuation uses the separately declared v2 clock contract. No full pass follows from the export. [The failure](ACQUISITION_TIMEOUT.md) and [separate fixed-prefix finalization](FIXED_PREFIX_FINALIZATION.md) preserve that boundary. [The counted acquisition protocol](../config/data-generation-v5.json) preserves cumulative budgets and requires at least ten million actual screened training inputs. Its scheduling amendment bounds preparation backlog. Generation, preparation and small diagnostic recovery tests do not yet pass the full learning gate.

The saved `models/diagnostic-v2.cai` is original diagnostic data, not a release-strength model. No full pass, final Elo or Stockfish parity claim follows from the current measurements.

[Durable full-data replay](DURABLE_DATA_REPLAY.md) preserves both failed budgets and the human-directed continuation. [Native race evidence](notes/tactical-races.md) distinguishes the completed 15-case producer from the interrupted 13-case independent replay.
