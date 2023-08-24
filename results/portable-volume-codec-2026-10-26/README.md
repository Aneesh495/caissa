# Portable evidence codec controls

Linux and macOS passed all 23 controls in the targeted workflow. A synthetic
35,717,120-byte input was encoded into three real gzip volumes and independently
reconstructed against the external original-byte identity. A published original
game journal also retained its exact byte identity. Neither test substitutes for
packaging the complete corpus, state journal or trained checkpoints.

Measured peak Python allocations were below 3.83 MB for encoding and 3.34 MB
for decoding. These are `tracemalloc` measurements during codec operation, not
process RSS or a guarantee about every full-size workload. Rehashed malformed
schema, path, order, byte count, compressed/decoded checksum, CRC, truncation,
decompression-overflow and symlink cases were rejected through the actual CLI.
Existing destinations were preserved. A changing original and an incorrect
external original identity could not publish a final archive index.

The actual large-file owner also refused a competing host lease before creating
its scope or starting compression. No local codec execution ran alongside the
decisive heuristic games. This development scope is closed after one hosted
execution on each platform. Complete raw packaging, distribution and semantic
reproduction remain pending. No release or full G15 pass is established.
