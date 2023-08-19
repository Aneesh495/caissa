# Portable raw evidence volumes

The volume codec preserves one externally identified original byte stream.
It writes 16 MiB raw slices into separately hashed gzip files and records both
compressed and raw byte identities in `VOLUMES.json`. No game result, model,
checkpoint, score or source receipt is interpreted or edited by the encoder.
Each compressed file stays below the raw slice size plus 64 KiB.

The independent decoder requires externally supplied index and original-stream
hashes and the exact original byte count. It rejects missing, extra, reordered,
linked, oversized or corrupted volumes. Every decoded slice has its own byte
ceiling and checksum. The decoder streams into a new partial file and publishes
the final file only after the entire original hash matches. Existing destinations
are never replaced, and failed partial output remains evidence of that attempt.

`tools.portable_evidence` owns actual large-file packing. Its output path is
derived from the complete original SHA256, so renaming an output cannot create
another budget for that input. One committed-source scope allows 2,700 combined
wall/active seconds, one attempt, 20 GiB additional storage and a 10 GiB reserve,
inside the unchanged parent project deadline. It saves the original source,
input declaration and progress before independently restoring every byte.
It requires the exclusive host lease. Large packing and decoding must wait for
decisive timed games to release the host.

This is a transport format, not a release or a scientific acceptance receipt.
A successful decode still needs its original chess, learning, numerical or
strength verifier. Old failed experiments retain the same failed outcomes after
transport. Implementing the codec does not mean that the full raw corpus,
5.349 GB state journal or checkpoints have been packaged or distributed.
