# Reproduction and acceptance scope

Native prerequisites: a C++23 compiler, CMake >=3.25 and Ninja. Lab prerequisites: uv with Python 3.12.14 and Node 24. The lockfiles define Python and TypeScript dependencies. Graphviz is needed only to regenerate diagrams.

```sh
make bootstrap
make test
make lab-test
make perft
make demo
```

The analysis board listens on `http://127.0.0.1:8765`. It analyzes with the original native engine and classical evaluation by default. A finite demonstration needs no training, reference engine or tablebase download. `models/diagnostic-v2.cai` is a saved original diagnostic network, explicitly enabled through UCI:

```text
uci
setoption name EvalFile value models/diagnostic-v2.cai
setoption name Use Neural value true
position startpos moves e2e4 e7e5
go nodes 10000
```

To regenerate a small original training demonstration:

```sh
make selfplay CORPUS=data/demo PAIRS=200
make train CORPUS=data/demo DATASET=data/demo-prepared TRAIN_DIR=runs/demo-training
make export-net TRAIN_DIR=runs/demo-training
make arena ARENA_DIR=runs/demo-match
make strength-report ARENA_DIR=runs/demo-match
```

Existing corpus, checkpoint and match paths resume only when their configuration and input identities agree. A changed source executable requires a new match/corpus run identity. A smaller run is diagnostic even when all its commands succeed.

After committing and pushing source, run an isolated diagnostic campaign:

```sh
make acceptance RUN_ID=local-diagnostic-001 PROFILE=diagnostic
```

This clones the exact committed source into `work/`, builds there, runs real native mate-fixture integration games, saves an executable/network bundle, independently replays it and executes rehashed semantic negative controls. The mate fixtures are synthetic integration workloads, not strength evidence. The printed verification command includes a trusted checkout and expected source commit. The verifier never derives its trusted commit from the bundle's own declaration.

```sh
make verify PROFILE=diagnostic EVIDENCE=runs/local-diagnostic-001 CHECKOUT=work/acceptance-local-diagnostic-001 SOURCE_COMMIT=YOUR_TRUSTED_SOURCE_COMMIT
```

Full acceptance is incomplete. `make acceptance RUN_ID=full-attempt-001 PROFILE=full` writes a metadata-readiness receipt and returns nonzero. It finds the actual dataset by the frozen protocol's identity and preserves recorded model failures. The full verifier cannot certify a diagnostic bundle or saved pass flags. [Full-bundle admission](FULL_BUNDLE_ADMISSION.md) additionally requires an externally supplied `EVIDENCE_INPUTS_SHA256` and product-source inventory. The [full data reconstruction](../results/full-data-2026-10-25/README.md), three-seed learning and subsequent precision/instrumentation checks passed their separate domains; full strength, final systems/browser/performance evidence, complete semantic adapters and the release audit remain pending. `make release` requires independently verified full evidence, the same external input identity and a current maintainer audit; no release is available.

A finite three-seed pipeline with independent data, checkpoint, native-network and mutation checks is available through `make learning-audit RUN_ID=learning-demo-001`. [Bounded campaign execution](BOUNDED_CAMPAIGNS.md) states its deadlines, diagnostic scope and manually dispatched Linux workflow.
