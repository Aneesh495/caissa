# Contributing

Build and run `make lab-test` before changing chess behavior. Keep new production logic original and source-linked. Do not import engine source, evaluation constants, networks or external teacher labels. Record dependency provenance and license changes.

A legal-move change needs independent reachable-position comparisons and targeted rule fixtures. State changes need exact undo/hash/accumulator checks. Search heuristics need off switches, exact-tree checks where applicable and matched strength experiments. Preserve the unchanged classical baseline for evaluator comparisons.

Network changes require a new compatible contract, arithmetic bounds, rejection tests, native/reference agreement and a frozen float-error endpoint. Dataset changes require independent replay, game/family lineage and functional-input duplicate screening. Model selection must never consult test arrays or match results to choose among predeclared seeds.

Use new immutable run identities when executable, model, configuration or openings change. Keep negative results and failures. Publish relative uncertainty with the actual resource conditions. Do not infer Elo from speed, a README claim or an opponent option name.

For service/browser work, run `npm run build` and `node tests/service_integration.mjs` against a live local service. Verify cancellation, stale messages, keyboard input and the exported variation. Keep protocol input, output and worker ownership bounded.

Commit focused changes with the executed checks. Documentation must describe observed behavior and explicitly distinguish diagnostic from full acceptance. Release requires full independent verification, not a manually edited pass flag.
