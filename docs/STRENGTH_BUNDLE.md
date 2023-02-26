# Full strength domain replay

G08 and G09 accept the `strength-journals-v1` adapter. Their `strength.campaigns`
array contains one neural comparison or the three external settings, in frozen
order. Each descriptor contains one exact `config` artifact reference. Its
parent directory must hold CONFIG.json, PROTOCOL.json, SUMMARY.json, every
paired JSON record, every separate game JSON and every PGN. All these files
must be present in both the immutable manifest and that domain's artifacts.
Missing, extra, linked, changed or undeclared journals reject the domain.

The adapter stages pinned bytes outside the evidence directory, reconciles
pair/game/PGN files, and independently replays moves, claims, request budgets,
timings and PVs. It then recomputes counts, clustered bootstrap intervals and
relative Elo using the existing full strength verifier. G08 retains the
4000-game sample, identical classical actor, at least50 Elo neural gain and
strictly positive95% lower bound. G09 retains all2000 games across the three
frozen settings and never produces an absolute rating from their option names.
The caller's original wall and active deadline also bounds bootstrap work.

Saved pass receipts cannot discharge either gate. A negative neural endpoint
preserves its independently observed statistics in STRENGTH.json and remains
failed. The full report retains that failed endpoint and can continue to G09;
it never lists the negative result as a verified gate. Even successful G08/G09
replay leaves whole-project acceptance false
while other domains are pending.

Hosted controls stage the four actual native CI games, reject seven artifact
and sample mutations, invoke the actual full CLI against a rehashed false pass
receipt, and interrupt bootstrap with the caller's original deadline. These
small controls passed on Linux and macOS in correctness run40213009686 at
sourcebf91c5d. [Complete platform logs and identities](../results/strength-bundle-2026-10-25/VERIFICATION.json)
retain the actual ten-control results. They do not certify a full strength sample. Full-size positive replay
still requires the completed frozen campaign. Local timed matches continue
from their original archived owner and verifier code.
