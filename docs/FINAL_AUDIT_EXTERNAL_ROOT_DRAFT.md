# External audit receipt draft

Status: prepared and unexecuted. No receipt file, audit result, accepted root,
scope, owner, import, test or verifier was created or run. The existing renewal
request is pending. Actual acceptance remains eleven domains and five pending.

The earlier in-source audit-root constant would change audited code when an
accepted result was installed. The new draft keeps trusted audit data separate
from the frozen source. This is a prepared design and implementation, with no
runtime or security acceptance yet.

## Explicit external trust input

[The receipt loader](../verification/final_audit_trust.py) accepts an optional
private project-relative path and a separately supplied expected SHA256. Both
must be present together. The expected digest must be fixed in the real future
entry admission before execution, after independently checking the actual closed
audit. It must not be copied from FULL_INPUTS, a domain declaration, MANIFEST,
a fixture builder or another file chosen by the evidence being verified.

The receipt pins the actual audit scope, independent result, owner closure,
audited source commit and source inventory. It contains no pass flag or execution
permission. The audit reader still checks the corresponding actual process,
log, source, input, area-coverage and closure relationships through Bundle reads.
The receipt digest alone does not establish any audit finding.

The file must be outside the evidence bundle, inside attributed private project
metadata, a single regular file with mode 0600, at most 8 KiB and stable during
the read. Existing no-follow Bundle traversal checks its components. Strict JSON
rejects duplicate keys, malformed hashes, unknown pass fields, escaped scope
paths and stale source identities. No file is written by the loader.

The projection's trusted outer invocation supplies this input. It is not read
from the bundle or accepted as a caller's all-green status map. Without it,
offered audit evidence rejects and the empty audit declaration stays unverified.
The explicit trust boundary is the separately admitted expected digest, just as
source commit and full-input identity are external verification inputs.

An owner must establish the receipt's legitimacy from a real independently
accepted audit before pinning it. Selecting an invented expected digest would
invalidate that admission. No such owner, receipt or admission exists now.

## Freeze order without a source exception

1. Finish all intended collector, checker, entry wiring and integration code.
   Complete the missing G14 join and commit any actual G14 trust roots first.
2. Freeze the final source commit and exact product inventory. Admit and perform
   the real independent audit on those bytes under fresh human authority.
3. If that audit is independently accepted, retain its local result and closure.
   Record its private external receipt without editing source or changing HEAD.
4. Admit the actual final entry with that exact source, receipt path and expected
   receipt digest among its fixed inputs. The audit-to-entry interval permits no
   source edits, Git commits or HEAD movement. Metadata scopes remain private.
5. Check the real entry process, decision, logs, groups and ledgers. Only after
   closure may sanitized derived proof be published. The report continues to
   identify the actual audited source commit; a later publication commit does
   not become an automatically verified target.

This avoids changing audited source to activate a root. The existing current
source, inventory and HEAD guards stay strict. Any code change requires a new
audit relationship decision, never a silent AST or source-policy exemption.
The ordering and loader still need admitted runtime verification.

## New controls and remaining work

[Nine new synthetic receipt cases](../tests/final_audit_trust_policy.py) are
prepared: eight rejections and one exact-identity/immutability case. They write
no receipt file and never represent their synthetic identities as real evidence.
Together with the earlier 23 prepared policy cases, 32 cases are planned and zero
have run. The separate G14 24-case draft also remains unexecuted.

The real loader still needs admitted filesystem controls for inside-bundle
placement, links, modes, changes during reading, missing path/digest pairs and
limits. Actual rehashed Bundle forgery and designated full-entry controls remain
required. No synthetic policy case substitutes for those relationships.

The real audit collector/checker and final entry wiring remain unfinished.
G14 acceptance is absent; original compiler/runtime closure, failed neural gain,
incomplete matrix and unavailable historical inputs remain separate blockers.
No scope, deadline, native/game start or exhausted parallel allowance is renewed
by this design. Do not run it through an alternate or inline launcher.
