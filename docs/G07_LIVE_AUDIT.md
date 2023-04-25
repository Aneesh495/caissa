# Complete original-learning audit

`verification.g07_audit` runs the independent original-data and learning readers
and joins their actual live results. Saved success flags are insufficient. The
data reader reconstructs the fixed 114,791 original pairs and every prepared
row. The learning reader checks all three original seeds and 240 checkpoints,
including their initialization, optimizer/configuration provenance and
validation-only selection. Test arrays remain excluded from model selection.

The original q1024 learning receipt and export remain original observations.
The q4096 deployment joins through the same selected floating checkpoint.
Neither encoding errors nor failed strength observations are converted into
successful learning receipts. Passing G07 cannot certify neural gain, external
strength, another gate or a release.

The prospectively frozen plan pins code, dataset, checkpoint, deployment,
input manifests and the single output `runs/full-g07-audit-v1`. One attempt
has an eight-hour cumulative wall/active ceiling, 40 GiB additional output and
a 10 GiB free reserve, inside the existing parent deadline. The data component
retains its own six-hour and 20 GiB limits. Learning has at most one hour and
the existing 20 GiB bundle limit. A failure leaves its scope and raw outputs
in place; another directory cannot reset this audit.

A real inherited host file lock excludes new timed work throughout both
components. The audit also waits for the frozen strength sequence to settle,
so it cannot take the brief lock gap between neural and external phases.
An exhausted failed strength domain can still release independent audit work.
Recoverable strength failures retain priority.

Readers execute from a saved source tree checked against externally pinned Git
blobs. Later unrelated commits may advance the live checkout without changing
that archive. Ordinary live-checkout verification still requires its exact
HEAD and bytes. Nested readers share their campaign's process group so an
outer timeout can stop the complete owned computation.

Hosted controls use rehashed plans, original-result metadata relationships,
real source archives, actual host-lock inheritance and a forced nested timeout.
The real data replay in these controls contains only 50 original CI pairs.
It is an implementation check and certifies no full G07 sample.
