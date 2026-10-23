# Bound acquisition to preparation capacity

[Protocol v5](../config/data-generation-v5.json) adds producer backpressure. It
retains the stronger original teacher, seed, nodes, maximum request, actual
screened-input target, minimum training/game counts, cumulative resource ceilings
and three-hour final confirmation deadline from v4. Earlier protocols and every
completed journal remain intact.

Generation was over 23000 pairs ahead of preparation. The final confirmation
must consume every committed pair, so an expanding backlog risks that existing
deadline even while both jobs make progress. New admission now pauses when
committed plus in-flight work exceeds preparation by 4096 pairs and resumes at
2048 or below. An existing larger backlog drains without discarding data. A
missing progress marker is zero confirmed preparation, not invented progress.
Waiting consumes the original wall ceiling. Preparation still has to confirm
the actual ten-million training-input minimum independently.

`training/corpus.py` publishes the dependency phase and observed preparation
counter while paused. It continues checking budgets and signals with bounded
waits. A pause is not acquisition completion. Teacher inputs, game outcomes,
label generation, full-match sample sizes and strength thresholds do not change.

The real recovery control withheld the consumer until 128 pairs were committed
and all native work drained. It gracefully interrupted and resumed the producer,
preserved all 128 completed pair hashes, then started actual preparation. The
consumer released backpressure and the unchanged 320-pair request completed.
Both sessions retained exactly the same wall origin and prior measured child
CPU total. Independent replay accepted all 640 original games and prepared
inputs. The 207.76-second control is diagnostic and does not satisfy the full
data gate.
