# Build status

Status: implemented development system; full acceptance incomplete; no release and no final absolute Elo.

October 28, 2026: the original parent deadline has expired. The local minimal
retention cleanup is complete, and the dedicated bulk Drive archive was deleted.
Older raw-artifact availability statements below are historical. See
[current retention and execution limits](ARTIFACT_RETENTION.md).

The frozen v4 strength sequence is closed. All 2000 external games passed
independent replay. The neural sample failed: 4000 games were attempted, 3997
finished and three reached the original 512-ply limit. Those records are retained,
and the required neural gain remains unmet. No strength sample is being retrained
or restarted.

The original heuristic schedule is closed with 3000 game attempts, 2999 finished
games and 1500 pair records. Thirty-nine comparisons independently passed; the
table-milliseconds-100 comparison failed on one original unfinished game.
[The original-sample result](../results/heuristics-original-2026-10-27/STATUS.md)
preserves that failure without replacement games. The multicore sample initially
stopped for storage cleanup after its fourth start, with 262 game records and 131
pair records retained unchanged. A separately recorded human continuation later
admitted one fifth owner. That owner is now closed incomplete at the unchanged
cumulative active-time cap, with 1110 of 1200 attempts, 555 pairs and five accepted
comparisons. The sixth comparison remains incomplete, with no additional match
time or replacement start admitted. No full systems result is certified.

The [complete original-data and learning audit](../results/g07-full-audit-2026-10-26/README.md)
is closed passed: all 114791 pairs, 229582 original games, 16522987 observations,
three splits and 240 original checkpoints were independently reconstructed or
evaluated. Validation-only seed 73, step 2750 remains selected. Original input
preparation failures and the separately approved repair are preserved.

The native rules, classical evaluation, PVS search, bounded UCI, Chess960, PGN variations, quantized incremental neural evaluator, original selfplay/training, paired arena, independent diagnostic verifier, loopback analysis service and browser board execute. Classical remains the default; both earlier diagnostics and the completed full original neural comparison lost strength.

The core maintains its ordered reversible-history score fingerprint incrementally. Its source-bound 16 Release and 16 ASan/UBSan cases passed, including a million-transition context reconstruction and sixty mailbox-minimax comparisons. Independent transport reproduced 180 paired cost observations. The loaded-host median runtime ratios were 0.942 classical and 0.957 neural mixture against the previous original executable. [Evidence and limits](notes/search-context.md) distinguish search cost from unmeasured playing strength. No final absolute Elo exists.

The browser can now display optional native search counters and bounded position samples. Actual one/four-thread streams, a 10000-node inspection parity case, ten malformed telemetry controls, cancellation, terminal zero-work output, stale-position clearing and a 390-pixel keyboard/browser flow passed. [The inspection study](notes/search-inspection.md) preserves the original driver timeout and source-bound development evidence. This does not replace the final release browser or strength campaigns.

[The data coverage report](notes/data-coverage.md) scanned every exported input, bound all six array hashes and plotted raw corpus and split distributions. It reports 13216293 unique usable input rows, including 10578434 training rows, with closely matched fixed-bin marginals across splits. This is data-only analysis; full original-data reconstruction, learned validation improvement and playing strength remain separate gates.

The later [full independent reconstruction](../results/full-data-2026-10-25/README.md) passed the data domain: 229582 completed original games, 16522987 raw observations and every exported training/validation/test row. All three protocol-v3 seeds then completed 20000 updates each. Independent learning verification evaluated all 240 checkpoints without opening test arrays and confirmed validation-loss improvement over initialization. Validation selected seed 73 at step 2750. Its numerical gate failed at 57.055664 cp maximum error against the frozen 32 cp limit; exact integer parity and 1000000 selected-model restoration transitions passed. The fixed 4000-game neural comparison completed at -61.97 Elo versus classical, with a 95% interval of [-71.25,-52.87], and failed its gain endpoint. The frozen 2000 external games also completed with that same original candidate and passed independent replay. Against unrestricted Stockfish19, the measured difference was -392.39 Elo with95% interval[-438.13,-353.45]. No absolute rating is established. [Model receipts](../results/full-model-v3-2026-10-25/MANIFEST.json) preserve these distinct outcomes. [The heuristic study](notes/heuristic-ablations.md) also completed 1056 searches, 528 independent fixed-node replays and twelve rehashed semantic controls; its loaded-host work/depth observations cannot establish Elo.

The subsequent [PVS-off LMR recovery repair](notes/lmr-window-recovery.md) passed all seventeen Release and seventeen ASan/UBSan cases and 48 default-PVS old/new parity pairs. The original failed regression, first parity-driver failure and three remaining selective-oracle discrepancies are retained. This development binary is distinct from the immutable full-model campaign binary.

[Deferred neural state](../results/deferred-neural-2026-10-25/README.md) now skips unused sparse-transformer work. Nineteen cases in Release/ASan/UBSan/TSan, one million tree operations and 144 exact search pairs per mode passed on Linux/macOS. Independent raw reconstruction confirmed all 1440 runtime queries and eight semantic rejection controls. At the selected mixture with caching, median wall time fell 8.93% on Linux and 7.03% on macOS against the archived executable. Other groups include neutral/slower outcomes. The new option stays experimental/off, no new strength result follows, and the original full neural failure remains failed.

[The separate v4 strength sequence](STRENGTH_V4.md) used the exact saved 1ff
executable, q4096 network 52d, validation-selected checkpoint C76 and ten-percent
mixture. Lazy Neural was enabled in both match actors. Its external sample is
complete and independently passed; its neural sample remains failed/incomplete.
The completed-game neural diagnostic is -63.86 relative Elo against unchanged
classical evaluation, with a 95% interval of [-73.80, -54.07]. It is not a certified
full-sample result. The original q1024 model and match failures remain unchanged.

The [current core identity join](../results/final-core-identity-join-2026-10-28/README.md) distinguishes earlier actor receipts from the saved1ff image. It executes no semantic samples and certifies no new gate. The maintained [remaining-work list](REMAINING_WORK.md) and [prospective rating design](RATING_BENCHMARK_DESIGN.md) record the current next actions.

| Gate | Current evidence | Remaining work |
|---|---|---|
| G01 Rules | New saved1ff full100000-position/96589-unique sample and20perft fixtures passed independent fresh native replay; original c82 evidence remains unchanged | Final full-bundle/coordinator and compiler/runtime relationships; component proof is in results/final-saved-actor-rules-2026-10-28 |
| G02 Restoration | New saved1ff/52d full1000000-pair sample passed independent typed-state/native replay; all3040911requests and1040911full-state checks completed, both native exits zero | Final source/coordinator and original compiler/runtime relationships; component proof is in results/final-saved-actor-restoration-2026-10-28; retired bulk historical inputs remain unavailable |
| G03 Draw history | New saved1ff/52d full92-history/2195-observation producer and independent fresh native replay passed; original c82 evidence remains unchanged | Final full-bundle/coordinator and compiler/runtime relationships; component proof is in results/final-saved-actor-draw-2026-10-28 |
| G04 Protocol | New saved1ff full10000ordinary+100ponder sequences passed independent transcript replay; stop p99 .235042ms; original c82 evidence remains unchanged | Final full-bundle/coordinator and compiler/runtime relationships; component proof is in results/final-saved-actor-protocol-2026-10-28 |
| G05 Search | Full5803/1ff semantics passed; new current-source metadata join matches all69native inputs to that actor | Final compiler/runtime/full-bundle joins and dedicated strength ablations; metadata is not a new semantic pass |
| G06 Network | New saved1ff/52d/C76 full100000-probe numerical sample and independent float64/native replay passed; maximum error10.39459cp<unchanged32cp; original q1024failure remains failed | Final full-bundle/coordinator, compiler/runtime and source/model/strength joins; component proof is in results/final-saved-actor-numerical-2026-10-28 |
| G07 Learning | Full joined replay passed: all114791pairs/229582games/16522987observations and240original checkpoints; unchanged validation-only seed73step2750 | Final source binding and portable bulk corpus/checkpoint reproduction remain required |
| G08 Neural contribution | Original q1024 full sample failed gain. V4 recorded4000attempts but only3997finished; three512-ply-limit records made independent acceptance fail. Completed-game diagnostic -63.86relativeElo95[-73.80,-54.07] | Required +50 gain and positive lower bound remain unmet; no reclassification or game replay |
| G09 External strength | V4 all2000games independently passed; final source/actor/settings/report join now closes R07. All2000retained PGN outcomes/color pairs match; unrestricted SF19 subset56W/2D/608L, -411.50relativeElo95[-460.14,-370.68] at100ms | Full coordinator and original compiler/runtime relationships; retired per-move JSON/pair journals prevent current full raw reproduction. No absolute/default-classical/human rating |
| G10 Parallel systems | Original1110/1200attempts and five accepted comparisons remain closed. Final R03 thread/runtime relationships passed:4000active-stop checks,64instrumented searches and exact-neural p99 .386750ms; preserved earlier failures remain failed | Sixth comparison and full matrix/coordinator remain incomplete, with no extra match time or restart; finite race observations do not prove universal race absence |
| G11 Recovery | Final R09 recovery accepted; new actual full-entry integration also accepts its original/current raw, source, actor, exit and closure relationships without replaying the sample | R12 remains open for the other domains and complete decision logic. Actual full entry exits2/incomplete; strict historical G11 branch and all original failures remain unchanged |
| G12 Browser | Final R10 acceptance passed; new actual full-entry integration accepts retained raw served-build/native/browser evidence and explicitly binds the .cjs helper;15new rejection cases and1failed/missing-gate preservation case passed across both adapters | Fourteen other gates remain pending in the actual partial coordinator invocation. Old failed owners and historical reader flags stay preserved; original compiler/runtime, strength, reproduction and release gates remain open |
| G13 Performance | Exact1ff/52d sample640searches/4581RSS/2000readiness/16independent fixed-node searches passed; final R11 source/actor/deployment/real-exit relationships checked | Whole-project coordinator and original compiler/runtime closure remain open. Descriptive performance rates and memory rows do not certify race safety or playing strength |
| G14 Semantic verifier | Combined saved-image semantic sample passed at1deecce/run40329511266 with16rehashed semantic rejections and7full-entry cases/platform | Final all-domain source/compiler/runtime relationships and complete campaign coordination; other failed gates stay failed |
| G15 Reproduction | Historical raw G02 reconstruction passed; large historical corpora/checkpoints/raw archives were later deliberately retired. New compiler-attribution builds passed only their component | Full historical reproduction is unavailable where original inputs are missing. Original saved1ff compiler/runtime closure and clean saved-actor reproduction remain unproven |
| G16 Release | Blocked by incomplete and failed full gates | All required gates and final identity audit |

The [final core runtime evidence join](../results/final-core-runtime-join-2026-10-28/README.md) closes R05: G01-G06 now identify the same saved1ff actor and matching69-file native source boundary, with real independent runtime completion and14new rejection controls checked. Full coordinator integration and original compiler/runtime provenance remain separate open work.

[The complete original neural comparison](../results/full-neural-v3-2026-10-25/README.md) preserves its failed gain endpoint and exact runtime. [The full external comparison](../results/full-external-v3-2026-10-25/README.md) completed all2000 games and independent replay. [The historical6000-game raw publication](../results/strength-raw-v3-2026-10-25/README.md) passed a complete decode/hash proof at publication. Later [minimal retention](ARTIFACT_RETENTION.md) retired bulk inputs, so that receipt is not a claim of current complete raw availability. [Source/full-input admission](../results/full-admission-2026-10-25/README.md) and [rules-adapter controls](../results/rules-replay-2026-10-25/README.md) passed on both hosted platforms without certifying missing full semantic work. Classical remains the default; the completed comparisons retain their original candidate and do not inherit the new encoding.

Host: Apple arm64, 8 logical CPU cores, 16 GiB memory. CPU training uses two threads. The native executable does not consult external engines. Stockfish is used only by the separate external arena.

The initial 8-hour generation ceiling was not enforced and elapsed wall time exceeded it. Resumed process duration and monotonic active duration differ on this host. Neither is a measured CPU-hour total. Protocol changes and incomplete timing records must remain visible; the earlier campaign cannot be described as having met that ceiling.

The larger diagnostic preparation has 2181990 training positions from 65272 completed games. Its older split predates functional-input reflection screening, so it cannot satisfy the full data gate. A later v2 preparation independently replays games, quarantines cross-split functional equivalents and excludes frozen study/opening inputs.

The legacy 500-node data generator was stopped after a quality audit found that only 18.53% of a 400-game pilot's samples completed a search depth. The replacement original teacher uses 2000 nodes and seeded root ordering. Its 400-game pilot completed a depth for 98.30% of samples and passed complete independent dataset reconstruction. The new full corpus is separate. Its confirmation deadline expired. The consumer later screened 229582 games and 10578434 training inputs, and arrays were subsequently exported under a separately approved six-hour recovery. That first six-hour reconstruction also expired during host sleep. Its old journal-OFF scratch index is malformed and cannot be resumed. A later WAL-backed, externally pinned continuation passed the complete data reconstruction in 7356.07 active seconds within its unchanged 21600-active/86400-wall limits. No new games were generated and the original failures remain failed. [The failure](ACQUISITION_TIMEOUT.md), [separate fixed-prefix finalization](FIXED_PREFIX_FINALIZATION.md) and [full data receipt](../results/full-data-2026-10-25/FINALIZATION.json) preserve those distinct outcomes. [The counted acquisition protocol](../config/data-generation-v5.json) remains immutable. Data is now verified, while learned-model and strength acceptance remain pending.

The saved `models/diagnostic-v2.cai` is original diagnostic data, not a release-strength model. No full pass, final Elo or Stockfish parity claim follows from the current measurements.

[Durable full-data replay](DURABLE_DATA_REPLAY.md) preserves both failed budgets and the human-directed continuation. [Native race evidence](notes/tactical-races.md) distinguishes the completed 15-case producer from the interrupted 13-case independent replay.

[Full restoration development proof](../results/restoration-full-2026-10-25/README.md) retains the exact observed program, model, source/scope and stage exits. Its5.349GB raw state journal has an [exact independently decoded volume representation](../results/portable-g02-2026-10-26/README.md). All319volume bodies remain local; the public index alone is not a full download. [All four instrumented native archives](../results/native-state-sanitizers-2026-10-25/README.md) preserve the20-case transport checks before the later rules command. [The new draw-history sample](../results/draw-history-2026-10-25/README.md) includes its entire raw journal and original rejected fixtures. [The current rules/protocol samples](../results/native-checks-d2-2026-10-25/README.md) include all raw records and preserve the final controller bookkeeping failure after the four successful observation/replay stages. These identities do not automatically certify a later release.

[The intended-claim search repair](SEARCH_SEMANTICS.md) fixes the actual clock99 score of-552cp while preserving optional wins, reset moves, mate precedence and synthetic null suppression. Thirty-five focused cases and all22native tests passed. [The full G05evidence](../results/search-semantics-2026-10-25/README.md) retains every native response, independent per-move value, selective disagreement, negative mutation and full-entry exit. No evaluator, old match receipt or model selection changed, and no new Elo follows. [Earlier D2draw instrumentation](../results/draw-history-instrumentation-2026-10-25/README.md) passed all four sanitizer jobs; the later5803image has separate hosted checks.
