# Certified neural stand-pat cutoffs

`Neural Bounds` is an experimental UCI option, disabled by default. It can avoid
the dense neural layers when a conservative evaluation lower bound already
reaches the quiescence beta threshold outside check. All principal evaluations
remain exact. The original classical comparison remains available unchanged.

The final hidden layer has sixteen integer activations, each between zero and
the format's clipping ceiling. Its output is affine. At network load, summing
each negative output weight times the ceiling gives a raw lower endpoint;
summing each positive weight gives an upper endpoint. Bias, signed rounding,
the residual classical score, mate clamp and percentage mixture are monotone,
so applying them preserves the enclosure. Products and intermediate sums use
64-bit arithmetic. A stale incremental accumulator is rejected before any
shortcut is attempted.

The search uses a shortcut only if the lower endpoint reaches beta. It returns
that lower endpoint as a fail-high. It cannot publish it as an exact principal
score. Bound values can still change selective search order and later windows;
mathematical validity does not imply identical fixed-node play or improved Elo.

The development campaign enumerated all 65536 final-layer corners for twenty
networks. Eighteen synthetic networks force an endpoint in formats 1, 2 and 3,
including maximum allowed signed biases, int16 weight extremes, mate clamping
and seven mixture percentages. All 35840 native interval observations and 2240
independent byte-interpreter comparisons passed. Two trained networks each
passed 100000 incremental transitions. With the option off, 3840 evaluation
comparisons and 32 fixed-node searches matched the preceding executable.

Separate exhaustive mailbox search trees compared bounded and exact evaluation
in 64 cases, including promotions, check and draw-clock boundaries. They visited
16816 reference quiescence nodes and exercised 1562 certified cutoffs. These are
bounded correctness examples, not a general proof of selective search strength.

A fixed-node cost profile ran 120 searches across eight frozen positions, three
repeats and five evaluator settings, with randomized setting order. The searched
corpus and preparation continued on the same host. For the ten-percent mixture,
26877 evaluations took the shortcut and 310410 executed dense inference. Median
paired round-trip time was 0.791 times the exact mixture's time, with individual
ratios from 0.283 to 3.020 under load. The mixture still took 7.24 aggregate
seconds versus 2.55 for classical. At full neural weight, only twelve shortcuts
occurred and median ratio was 0.996. This profile establishes neither an isolated
speedup nor an Elo gain. The option remains off pending strength evidence.

The first arithmetic campaign's five checks all exited successfully, but its
wrapper then called an absent `finish` method instead of `close`. Its raw journal
and owner failure are retained. A later audit checked all five recorded exits
and log hashes. It did not manufacture an original campaign completion record.
