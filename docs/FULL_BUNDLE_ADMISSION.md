# Full evidence admission and remaining semantic replay

G03 now accepts `driver: draw-history-v1` with distinct declared `draw_history`
references named `profile`, `config`, `summary` and `observations`.
[The draw-history adapter](DRAW_HISTORY_REPLAY.md) independently reconstructs
every fixed and seeded history, intended/current claims, automatic outcomes,
null suppression, conservative dead material and hash context, then reexecutes
the pinned saved program. It requires equal-FEN history witnesses and all six
terminal outcomes. Other semantic domains remain independently required.

The full entry point checks committed product source, immutable artifact relationships and original experiment lineage before domain replay. G01 rules, G02 restoration, G03 draw history, G04 protocol, G05 search, G06 numerical probes, G08/G09 strength journals and G13 performance adapters are implemented. G07 has an original-learning component and a separate full data/learning audit; its full-entry joint adapter remains incomplete. G11 has the historical source/saved-image recovery join, G12 has a browser component and G14 has the combined semantic audit. G10 systems, G15 complete reproduction, G16 release audit and complete campaign coordination remain unfinished. A component is not automatically a full gate, and historical sample acceptance does not bind later product source. Full verification still returns nonzero with `full_acceptance: false`. Passing metadata, existing receipts or admission controls cannot certify a release.

## Source identity

[Source verification](../verification/source.py) obtains path modes, blob identities and sizes from the externally selected Git commit, checks aggregate bounds before retrieving contents, and compares SHA256 values with both the bundle declaration and actual checkout bytes. An edited checkout at an unchanged HEAD is rejected even if the bundle is rehashed to match the edits. Symbolic links and nonregular selected Git objects are rejected.

`caissa-source-v1` preserves the exact historical inventory used by the retained data, learning and native experiments. `caissa-source-v2` additionally includes browser HTML/CSS, native `.h` headers, CMake includes and JavaScript integration tests. New diagnostic bundles use the second policy; historical bundles keep the first. Full bundles require the product policy explicitly. No historical source hash or experiment scope changes.

## Artifact and input contracts

[Bundle reads](../verification/bundle.py) use bounded metadata, streaming SHA256, regular-file checks, no-follow component traversal and before/after file identity checks. JSON rejects duplicate keys, named nonfinite constants and overflowed numeric literals. Inventory validation rejects missing, additional, aliased or linked artifacts. Metadata read after manifest validation must retain the verified bytes. The default admission deadline is 600 seconds, with a hard maximum of 3600; one artifact is capped at 8 GiB, the total inventory at 20 GiB and 500000 files. These are read-only admission limits, not renewed generation, training or match budgets.

`FULL_INPUTS.json` has schema `caissa-full-inputs-v1`. Its SHA256 must be supplied separately through `--expected-inputs-sha256`. Referenced files use exact `{path, sha256}` pairs in the verified manifest.

| Input | Independent relationship checks |
|---|---|
| `source_commit` and `SOURCE_INPUTS.json` | Externally trusted commit, product inventory, Git blobs and actual checkout agree |
| Optional `native_source_binding` | Recompute the [tracked native source/input boundary](NATIVE_SOURCE_BINDING.md), preserve the original compiled source and learning failures, and leave all runtime gates required |
| `engine` | Exact saved artifact; runtime domains name the same SHA256 |
| `network` | Original residual formats 3/4, 64/32/16 architecture, wire length/CRC, classical contract 1, ten-percent mixture and selected float-checkpoint identity |
| `protocol` | Frozen experiment, at least 2000 neural pairs and 1000 external pairs across at least three settings, at least 50 Elo gain and positive 95-percent lower endpoint |
| `dataset.metadata` | Frozen dataset identity, distinct-input/game floors, functional screening, original teacher and target-column semantics |
| `heldout` | Exact study/opening bytes screened by data preparation |
| `learning.selection` and seed configs/indexes | Every frozen seed, completed budgets, recorded loss improvement, retained selected/final checkpoint identities, validation-only minimum and the same deployed float checkpoint |
| `domains` | Exactly G01 through G16, source identity, required runtime/model identities and declared raw artifacts |

Format 4 changes the integer encoding of the selected float checkpoint. Admission requires the same real activation cap by exact integer cross-multiplication. It does not select another seed, infer strength from loss or bless the original failed numerical gate.

```sh
.venv/bin/python -m verification.verify EVIDENCE \
  --checkout TRUSTED_CHECKOUT --expected-commit TRUSTED_SOURCE_COMMIT \
  --profile full --expected-inputs-sha256 TRUSTED_FULL_INPUTS_SHA256
```

Equivalently, pass `EVIDENCE_INPUTS_SHA256` to `make verify PROFILE=full`. A consistent declaration returns status `incomplete`, exit 2 and the remaining semantic gates; contradictory inputs return a structured rejection and exit 1. Saved `status: passed` flags cannot enable full acceptance. The full entry point defers while the selected checkout's timed-match owner holds the host. Tests use isolated synthetic metadata fixtures and never run their intentionally nonexecutable runtime artifact.

## Controls and packaging

G01 can use `driver: rules-v1` and a `rules` object containing exact references named `profile`, `fixtures`, `summary` and `observations`. Include those references in the gate's raw `artifacts` inventory and supply `--replay-output` outside the bundle, or `VERIFY_REPLAY_DIR` to Make. The [rules checker](../verification/rules.py) reconstructs every position in the frozen reachable walk, computes legal sets and check state through python-chess, and reexecutes the exact copied native program. It also recomputes all twenty perft totals through the external oracle before checking native perft. The native inspection route compares the independently authored mailbox and bitboard generators internally.

The [frozen profile](../config/rules-replay-v1.json) retains 100000 comparisons and twenty fixtures. A diagnostic prefix cannot set `full_gate: true`. The [real-core controls](../tests/rules_replay.py) use 512 positions, all twenty perft fixtures and rehashed mutations of move sets, reachable-walk identity, sequence indices, perft totals, completed work and engine identity. Full-entry controls additionally reject the prefix before full replay and reject writing verification output into its original evidence. The full100000-position final-source campaign remains required; these controls do not substitute for it.

G04 can use `driver: protocol-v2` and `uci_transcript` references named `config`, `summary`, `transcript` and `stderr`. All four must be distinct declared raw artifacts. The externally pinned engine must match the transcript campaign, and the original evidence stays read-only. An external replay directory receives byte-verified copies. The independent protocol state machine reconstructs every search/stop/ponder lifecycle, legal PV, thread/search-mode inventory and latency endpoint. Its original bundle wall/active deadline remains enforced during transcript reconstruction. Fewer than 10000 ordinary sequences cannot pass, regardless of a saved success flag. This checker reconstructs recorded transport evidence; it does not create fresh timing observations.

G02 can use `driver: restoration-v1` and `restoration` references named `profile`, `config`, `summary` and `observations`. Its [checker](RESTORATION_REPLAY.md) requires one million actual make/unmake pairs, independently reconstructs complete board/history/hash/neural state and reexecutes every command through the exact copied program. Native model/source identities remain pinned, saved wire types are checked recursively and output stays outside the bundle. The1280-pair development prefix cannot pass G02. Complete raw state replay remains distinct from the data, numerical and neural-strength gates.

[Actual native controls](../tests/protocol_bundle.py) produce 32 ordinary sequences and all100 ponder sequences, then verify the prefix independently. Six full-entry mutations reject a short sample, omitted raw file, aliased files, changed engine, falsely raised counts and an output directory inside the evidence. Neither this prefix nor earlier-source protocol results satisfy the final executable's G04 gate.

[Source controls](../tests/source_binding.py) use a real temporary Git repository and the source-verifier subprocess to check edited native/browser bytes with and without rehashed declarations, omitted assets, a source symlink and a mismatched commit. [Full-input controls](../tests/full_bundle.py) rehash ordinary manifests and the external input pin after changes to selected checkpoints, mixtures, seeds, held-out bytes, runtime identities, CRC and the Elo endpoint. Test-based selection is rejected. A fixture claiming every receipt passed must still return all sixteen semantic gates as incomplete. [Integrity controls](../tests/bundle_integrity.py) cover parser limits, aliased paths, changed verified metadata, links and nonblocking rejection of a FIFO. These controls establish rejection behavior; they are not full experiment results.

The full readiness command finds the dataset by the frozen protocol's exact metadata identity rather than reading an obsolete directory and reporting zero positions. It reports observed metadata counts, retained model failures and unknown data explicitly. [Readiness controls](../tests/acceptance_readiness.py) ensure a larger unrelated dataset is never selected. Actual array reconstruction, checkpoint inference and games still need their domain evidence.

Release packaging requires the same external input identity in the current private audit. Once every full gate passes, it copies the exact verified engine and selected evaluator, records their identities and declared mixture, and retains the source archive. It cannot substitute the older diagnostic model directory for the selected runtime. Packaging remains blocked by incomplete full verification and acceptance.

G14 uses `driver: semantic-audit-v1` with one exact `semantic_audit.config`
reference and its complete declared raw witness inventory. The
[combined semantic audit](SEMANTIC_AUDIT.md) reconstructs actual PVs, paired game
results, selected-network inference and draw histories, then rejects sixteen
consistently rehashed forgeries. It requires a separate replay output and the
exact saved image/source relationship before admitting the G14 sample. A
different portability image remains a component. All other gates and the full
project result remain independent.

G05 uses `driver: search-semantics-v1` and four distinct declared
`search_semantics` references: `profile`, `config`, `summary`, `observations`.
[The independent search adapter](SEARCH_SEMANTICS.md) reconstructs exhaustive
minimax and root move values through an external board and classical oracle,
checks real table bounds and mate normalization, records selective ablations
and reexecutes every saved request through the exact native image. All frozen
work and its original ceilings are required. A saved score, opaque native test
pass or partial prefix cannot replace that reconstruction. Its actual positive
full entry leaves the other fifteen semantic gates incomplete.

G11 uses `driver: forced-recovery-join-v1` with an exact `recovery_join.config`
reference and the complete joined raw inventory. The [historical recovery
join](RECOVERY_JOIN.md) independently selects the pinned original arena,
trainer and data archives, reconstructs their contents and compares producer
bytes/modes to their historical sources. macOS also performs a distinct saved-image
resumption after these checks. Historical producer reruns and a different native
image cannot substitute for this join. The source6a63aaaa sample passed in
run40336617662; it leaves fifteen other full gates incomplete. Subsequent source
changes still require final all-domain binding and do not inherit full acceptance.
