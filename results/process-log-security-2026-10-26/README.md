# Process log security correction

GitGuardian incident 39027204 refers to the `authorization-refusal.log` SHA-256
entry at line 11 of `results/systems-startup-2026-10-26/MANIFEST.json` in commit
c5f9f85d37ad1b86521c59533c6bab8dc87c5ef6. Recomputing the original committed log
and the current log produces that exact checksum. This alert is a false positive.
No credential rotation or history change is indicated by that checksum.

A separate review found Antigravity local CSRF and host bridge session values
inside process command arguments in the public saved-v4 performance host log.
Those values matched a live local process at inspection. Their external service
scope was not established. No credential was tested against an endpoint.

The current public log now omits all process command lines and arguments. Its
29 observations retain the exact timestamps, load, process IDs, parent IDs,
states and CPU values. The original raw log and original manifest are retained
privately. Original performance receipts and measured results are unchanged.
The public transformation is explicit in `PUBLIC_REDACTION.json`; it is not
represented as an original raw capture. Existing Git history still contains the
old values, so current-tree redaction is not revocation.

Future HostGuard publication uses the same metadata-only projection after its
unchanged competing-work classification. Three focused tests verify real guard
refusal without argument publication, unknown-field removal, exact raw-input
preservation, and existing-file/symlink refusal. No engine, training, match,
compiler, browser or closed-domain producer was executed for this correction.

The affected local Antigravity session must be replaced. No application was
terminated and no Git history was rewritten during this correction. GitGuardian
has not been marked resolved automatically.
