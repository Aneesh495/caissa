# Source and full-input admission controls

Both platforms passed the actual source-verifier and full-input CLI controls at source `42d659b39261857dc4c436090e59fe18cc2a2440`, [workflow 40174077710](https://github.com/Aneesh495/caissa/actions/runs/40174077710). Each platform recorded eight source controls, fifteen full-input cases, thirteen artifact-integrity cases and the metadata-readiness check. Ordinary native rules, original-engine analysis/cancellation and diagnostic semantic verification also completed.

The complete downloaded job artifacts are retained as `linux/RAW.zip` and `macos/RAW.zip`; [archive identities](ARCHIVES.json) pin their original GitHub digests. Compact reports preserve actual commands, exits and reasons. These cases use synthetic metadata fixtures, with an intentionally nonexecutable runtime in the full-input fixture. They prove admission and rejection behavior, not full data, neural, strength or systems acceptance. Every report keeps `full_acceptance: false`.

[Actual full-readiness output](ACTUAL_READINESS.json) correctly reports 10578434 training inputs and 229582 completed games from the frozen data identity. It retains the original q1024 model's numerical failures and returns blocked rather than certifying a full pass. [Historical compatibility](LEGACY_SOURCES.json) confirms exact source mappings for the original 184-file data, 194-file learning and 200-file match inputs. No historical scope or receipt was rewritten.

The local metadata helper initially failed because its project import path was missing. [The failed campaign](LOCAL_FAILED_CAMPAIGN.json), command journal and [initial error](LOCAL_INITIAL_FAILURE.log) are retained. The corrected [metadata-only recovery](LOCAL_RECOVERY_CAMPAIGN.json) ran inside the original 180-second deadline. This was a local harness error before the historical read; no old experiment was rerun. Independent hosted source controls passed afterward.

[The contract](../../docs/FULL_BUNDLE_ADMISSION.md) describes the implemented source, artifact and experiment-lineage relationships and the remaining semantic adapters. These controls cannot make the complete full verifier or release gate pass.
