# Build status

Status: implemented development system; full acceptance incomplete; no release and no final absolute Elo.

The native rules, classical evaluation, PVS search, bounded UCI, Chess960, PGN variations, quantized incremental neural evaluator, original selfplay/training, paired arena, independent diagnostic verifier, loopback analysis service and browser board execute. Classical remains the default because the diagnostic neural contribution failed.

| Gate | Current evidence | Remaining work |
|---|---|---|
| G01 Rules | 20 exact perft fixtures; multiple independent 100000-position comparisons | Bind final campaign to release source |
| G02 Restoration | Million-transition diagnostic passed; trained-network refresh checks passed | Final selected model/source campaign |
| G03 Draw history | Native claim/automatic/mate/history tests and independent draw replay | Final bundle |
| G04 Protocol | 10000 adversarial sequences, stop p99 below 50 ms; unread-output bound test | Final supported-load campaign |
| G05 Search | Independent tiny minimax, bounds and mate tests | Full heuristic strength ablations |
| G06 Network | 100000 v2 probes bit-identical; maximum observed float error 11.37 cp | Freeze and test final-model error bound |
| G07 Learning | Original corpus generating; three 20000-update diagnostic seed runs completed | 10 million distinct training inputs after screening; three full runs |
| G08 Neural contribution | Failed diagnostic: 4W/8D/84L against classical | Required 4000-game full positive contribution |
| G09 External strength | Warm short diagnostics include 0W/0D/48L against unrestricted Stockfish 19 | Required 2000-game campaign across three settings/opponents |
| G10 Parallel systems | Root sharing, cancellation and race-instrumented native checks | Frozen 1/2/4/8 profiles and strength comparisons |
| G11 Recovery | SIGKILL training/corpus/arena recovery tests executed | Source-bound replay of recovery records |
| G12 Browser | Live import, analysis, variation edit and export exercised | Complete fresh/constrained/keyboard campaign |
| G13 Performance | Evaluator and protocol timings recorded | Complete frozen scalar/optimized resource profiles |
| G14 Semantic verifier | Rehashed illegal PV, swapped colors, wrong inference and false draw rejected | Full campaign schema and independent checks |
| G15 Reproduction | Clean source diagnostic passed; Linux/macOS CI passes | Full saved-model/game/report reproduction |
| G16 Release | Blocked by incomplete and failed full gates | All required gates and final identity audit |

Host: Apple arm64, 8 logical CPU cores, 16 GiB memory. CPU training uses two threads. The native executable does not consult external engines. Stockfish is used only by the separate external arena.

The initial 8-hour generation ceiling was not enforced and elapsed wall time exceeded it. Resumed process duration and monotonic active duration differ on this host. Neither is a measured CPU-hour total. Protocol changes and incomplete timing records must remain visible; the earlier campaign cannot be described as having met that ceiling.

The larger diagnostic preparation has 2181990 training positions from 65272 completed games. Its older split predates functional-input reflection screening, so it cannot satisfy the full data gate. A later v2 preparation independently replays games, quarantines cross-split functional equivalents and excludes frozen study/opening inputs.

The saved `models/diagnostic-v2.cai` is original diagnostic data, not a release-strength model. No full pass, final Elo or Stockfish parity claim follows from the current measurements.
