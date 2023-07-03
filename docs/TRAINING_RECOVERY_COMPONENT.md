# Training recovery component

A checkpoint pointer commits an optimizer state. Observation output can reach
disk before that pointer. Resuming now preserves the committed journal prefix,
durably stores the uncommitted or torn suffix, then resumes from the committed
model, optimizer, scheduler, sampler and random states. It rejects a journal
that is missing any observation already covered by the pointer.

The fixed diagnostic uses the original published 56-pair data fixture. It
performs 100 optimizer updates in an uninterrupted reference and an interrupted
copy. A diagnostic-only barrier stops the latter after observation 40 but before
checkpoint 40 commits. The controller captures pointer 20 and its exact bytes,
records a real SIGKILL and bounded reap, appends a deliberately torn journal
fragment, and resumes. The full learning and strength configurations cannot
enable this barrier. No selected checkpoint, original learning receipt or match
record is changed; these diagnostic weights are never exported for playing.

The independent reader checks the exact removed bytes and committed prefix,
all five checkpoint pairs including optimizer moments and random states,
independent sampler draws, validation graphs, classical baseline samples,
validation-only best pointers and the complete raw inventory. It imports no
trainer and performs no gradients. Rehashed forgeries use its actual CLI.

This is one G11 component. Original-data/split recovery and final source/image
binding remain required, and every failed experiment remains failed. The new
manual hosted workflow runs only this component, preserving closed browser and
learning scopes. Its dependencies retain the project's PyTorch 2.8.0 version;
Linux uses the documented [CPU-only wheel source](https://pytorch.org/get-started/previous-versions/#v280).
