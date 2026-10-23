# Sharing a residual baseline during inference

A residual network adds its learned correction to classical evaluation. A partial neural mixture also needs classical evaluation. Previously `Network::evaluate` computed the residual baseline and `search.cpp` computed it again for the mixture. The combined evaluation now obtains it once, clamps the complete neural score, then applies the same percentage and truncation rule. Computing the mixture before clamping would change extreme scores and was deliberately avoided.

The default weight is still 100 within the evaluator, and the UCI default remains classical. A zero mixture skips neural arithmetic. The API and probe command reject percentages outside zero through one hundred before narrowing unsigned command values. This includes large values that could otherwise wrap into a small signed integer.

[Observed parity](../../results/blend-optimization-2026-10-22/PARITY.json) covers 3840 comparisons against the frozen earlier executable with independent classical scores, weights 0/10/25/50/100 and two synthetic extreme-bias models. Thirty-two 10000-node searches returned identical best moves, depths, scores and PVs. Separate absolute and residual networks each passed 100000 make/unmake and refresh transitions; scalar/native/reference checks and the native test suite also passed.

The hot-start-position microbenchmark compared the combined evaluator with the former expression. Under concurrent data and learning work, four of five native measurements were lower and one reversed. Median observed times were about 6.916 microseconds combined and 7.656 microseconds for the former expression. [Every timing row](../../results/blend-optimization-2026-10-22/microbench.json) retains the load qualification. Sequential timing under variable host load does not establish a stable production speedup or an Elo gain.

```sh
build/caissa --eval-bench models/residual-prefix-diagnostic.cai 100000 10
build/caissa --net-probe models/residual-prefix-diagnostic.cai 10
```

The probe accepts FEN lines on stdin. Omitting the percentage retains the existing full-neural numerical contract. Sources: [network](../../src/network.cpp), [search integration](../../src/search.cpp), [comparisons](../../tests/blend_contract.py), [restoration checks](../../tests/network_test.cpp).
