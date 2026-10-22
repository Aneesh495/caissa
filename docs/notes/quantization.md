# Integer contract

Network v1 uses little-endian fields, dimensions and feature version, 64 ASCII hexadecimal training-identity bytes, payload length and CRC32. `Network::load` rejects length, dimensions, feature/scaling/clip versions, extensions, checksum and out-of-contract biases before search. CRC32 detects corruption; the artifact manifest must additionally bind the entire file with SHA256 for provenance.

Transformer rows and dense weights are signed int16. Biases are int32 with absolute value at most 2^20. Transformer scale is 64; dense biases use scale 4096. Accumulators remain int32. With at most 32 pieces, their absolute bound is `2^20 + 32*32768 = 2097152`, safely within signed int32. Activations are clipped to integer [0,127].

The first dense dot has 128 products, bounding the magnitude by `128*127*32768 + 2^20 = 533725184`. The second has 32 and the last has 16. Native kernels widen each signed product to int32 and reduce through int64. A pair in AVX2's multiply-add is bounded by `2*127*32768`, so its intermediate cannot overflow. Inputs to these kernels are activation vectors, not unrestricted signed int16 arrays.

After each hidden dot, divide by 64 with nearest rounding, ties away from zero, then clip to [0,127]. The output numerator is multiplied by 400 in int64 and divided by 4096 with the same signed rounding. The final score is clipped below the mate range. `training/model.py::integer_reference` independently interprets the bytes and uses NumPy int64 arithmetic.

AArch64 includes NEON as an architectural baseline. x86-64 dispatch checks AVX2 at runtime and retains scalar fallback. SIMD agreement does not establish floating/quantized agreement: that separate probe records the actual error distribution. Quantized-aware training is intended to reduce that error. The final permitted bound must be frozen before held-out acceptance.

## Revised v2 contract

Version 2 retains the feature map and dimensions, uses scale 1024 and activation clip 2047, and permits biases through 2^28. Transformer magnitude is at most `2^28 + 32*32768 = 269484032`, within int32. The largest dense sum is bounded by `128*2047*32768 + 2^28 = 8854175744`, requiring the existing int64 reduction. Each SIMD multiply-add pair stays below 134152192, within int32. The output product and centipawn rescaling remain within int64. A v1 file keeps its original scaling when loaded; incompatible version/scale pairs are rejected.

The q1024 diagnostic trained from random initialization and observed maximum floating/integer error 11.37 cp over 100000 reachable probes, versus 168.69 cp for the earlier trained v1 network. Raw probes are separate run artifacts. This arithmetic improvement does not establish an Elo gain. Version 2 is a new numerical campaign; v1 results are retained.
