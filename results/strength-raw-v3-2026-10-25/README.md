# Complete original strength journals

This archive contains all 6000 original fixed-sample strength games: 4000
neural-versus-classical games and 2000 external-comparator games. It preserves
15008 files and 2668894520 raw bytes, including every pair JSON, game JSON,
PGN, actor configuration and statistical summary. The failed neural result is
preserved without filtering or replacement.

The deterministic gzip/tar archive is 380020404 bytes split into ten ordered
parts of at most 40 MiB. Its SHA256 is
`158dfc20d14ceede3551387f91c7d06199771693360a275f0d387aeea3b991d8`.
`ARCHIVE.json` records every part's size/hash and the hash of `RAW_INDEX.json`.
The index binds every decompressed file to its original bytes. A separate
streaming decode rehashed every archived byte and confirmed all paths, sizes,
counts and digests. The actual successful proof is `PACK_VERIFICATION.json`.

From this directory, verify the joined archive before extracting it into a new
directory:

```sh
cat all-strength-raw.tar.gz.part-* | shasum -a 256
mkdir decoded
cat all-strength-raw.tar.gz.part-* | tar -xzf - -C decoded
```

The top-level directories are `neural`, `external-0`, `external-1` and
`external-2`. Their saved absolute runtime paths describe the original machine;
they must be rebound explicitly when reproducing a campaign. They are not
instructions to overwrite paths on another machine.

[The neural report](../full-neural-v3-2026-10-25/README.md) retains its failed
gain endpoint, source/model identities and independent rejection.
[The external report](../full-external-v3-2026-10-25/README.md) gives the full
relative-strength estimates and uncertainty. No absolute Elo is inferred.
Caissa's saved original executable and network are available with those
reports; the external Stockfish binary remains a separately pinned dependency.

Packaging began only after both timed owners exited. Its separately bounded
600-second read/archive phase finished in 30.24 seconds. No game, inference,
source change, model selection or original scientific budget was restarted.
Portable match journals do not complete the remaining corpus/checkpoint or
whole-project reproduction gates.
