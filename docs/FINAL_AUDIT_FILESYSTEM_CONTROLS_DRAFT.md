# External audit receipt filesystem controls

Status: prepared source, unexecuted. No fixture directory, receipt-shaped file,
link, FIFO, scope, owner, import, test or verifier was created or run. Actual
acceptance remains eleven domains and five pending. Renewal is still pending.

[The new control source](../tests/final_audit_trust_filesystem.py) prepares
18 cases: two synthetic preservation cases and sixteen rejections. It has no
CLI, runs nothing on import and must receive an empty owned fixture directory
inside this project's work or runs output from a future admitted owner.

## Intended checks

| Group | Cases |
| --- | --- |
| Preservation | Exact private regular-file bytes and immutable decoded identity; absent optional receipt stays absent |
| Arguments and placement | Missing expected digest, missing path, inside-bundle placement, private-namespace escape and relative traversal |
| Content and limits | Changed external digest, empty file, more than 8 KiB, caller pass fields |
| Filesystem identity | Public mode, final/parent symlink, hardlink alias, FIFO and directory |
| Read stability | A real descriptor's file changes after reading and before the loader's final fstat |

The read-stability case synchronizes an actual one-byte append inside the
fixture read. It retains the real file descriptor and real before/after stats;
it does not fake a stat result or depend on thread timing. The expected error
must be the changed-during-read check. Other cases require the intended boundary
message or no-follow OS error, preventing an unrelated setup failure from counting
as rejection. Fixture setup failures must fail the owner.

These are synthetic receipt-shaped bytes, not an independently accepted audit.
The actual audit reader and full coordinator are never called. A later component
pass cannot establish a real audit, full-entry integration, compiler/runtime
closure, rating or release acceptance.

## Future admission requirements

No invocation is admitted now. After direct human renewal, a separate finite
scope must bind the exact control/loader/Bundle/Python sources, owned output,
time, complete existing external-path inventory and storage guards before running.
Do not call this module inline as an expiry bypass.

The fixture source bounds regular payload writes to 32 KiB and 24 created
regular-file names. The outer guard must additionally account for metadata,
links, retained output, owner descriptors and required reserve. It must permit
only these bounded synthetic operations inside the owned fixture root:

- Two symlinks to other synthetic fixtures in that same root.
- One hardlink alias to a synthetic fixture, with no external target.
- One FIFO and the enumerated directories.
- One public-mode fixture during its case, restored to 0600 afterward.
- A one-byte append to the single declared mutable changing-file fixture.

The source retains all fixtures. It uses no temporary directory elsewhere,
cleanup deletion, native actor, child process, dependency install or network.
The existing guards do not implicitly admit these link/mode mutations. A real
future scope needs their exact namespace/count allowance and actual writer wiring.
No existing closed scope, sample or control should be reopened for this work.

The earlier 23 projection and nine receipt policy cases remain prepared, with
zero executed. Adding these 18 gives 50 prepared cases, all unexecuted. The
separate 24-case G14 relationship draft also remains unexecuted. Actual rehashed
Bundle forgery tests, designated full-entry wiring and audit collector/checker
implementation remain outstanding.
