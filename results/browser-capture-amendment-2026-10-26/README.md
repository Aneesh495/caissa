# Original native browser capture amendment

Normal UI completion now drains the original SSE response to EOF and releases controls without aborting the finished request. Explicit Cancel and navigation still abort and reap native workers. The independent browser/PV reader is unchanged.

First corrected run40423146013 failed on both platforms. The UI reached completion, but Playwright response.finished stayed pending until the failed harness closed the browser. A single bounded remote metadata diagnosis40423610628 inspected both pinned failure archives without competing local decoding or a new browser execution. The original failed Mac archive also confirms all12analysis captures lacked complete bestmove bodies. Exact decoded job logs, original scope, source and ZIP identities remain retained.

The second recorder observes a [clone of the actual browser Response](https://fetch.spec.whatwg.org/#dom-response-clone) to EOF. It forwards the original fetch arguments and Response unchanged, records bounded raw UTF-8 bytes, and never uses route interception, response substitution or replay. Canceled reads remain aborted observations.

The later direct human autonomy instruction authorizes this explicit finite amendment. Numeric bounds were agent-chosen before execution: two main hosted executions,900seconds each per platform, within one fixed hour and the original parent deadline. The one additional metadata-only execution is capped at120seconds and shares the unchanged1800second cumulative platform ceiling. Old four browser failures and expired limits remain unchanged.

Status: second main execution charged, not yet verified. This is not a component pass, full G12 acceptance or a release. No local compiler/browser/native work has run during the timed heuristic lease.
