# Full data reconstruction

The saved `FINALIZATION.json` is a data-domain receipt. The independent archived verifier replayed 114791 original pairs, all 229582 completed games and 16522987 raw samples, then rebuilt and compared every exported row: 10578434 train, 1336496 validation and 1301363 test inputs. No new games were generated. Cross-split inputs were quarantined.

Original acquisition and the first recovery remain failed. This later authorized scope preserved those failures and completed in 7356.07 active seconds within its original 21600-active/86400-wall limits. The independent stage used 3524.69 child CPU seconds, 7305.77 active seconds and 7305.86 wall seconds. Those clocks include different owners and are not interchangeable.

`PAIR_HASHES.jsonl.gz` preserves the externally frozen pair inventory. Its decompressed SHA256 is `a68c2b878fb2fbf7fcc738096396fa952408053f283c0fcf6c2ec2bf4a22e774`. The raw multi-gigabyte games and arrays remain in the local source-bound corpus. These small public receipts and hashes alone do not let another machine independently replay absent raw data. Complete portable evidence publication remains a release requirement.

The unchanged original teacher is SHA256 `cd33e7f3f925bb522569c34283cc9f20c710d9e1bc50760bda62ccacbf2994ed`. The independent verifier source is commit `8066faba146e5296e0d2481b34e92ff5e5b280f1`. Learning uses frozen protocol v3 from `88937d913e5e97808a6e002bd8587c96633fc905`. Neither corpus size nor successful reconstruction establishes Elo or full acceptance.
