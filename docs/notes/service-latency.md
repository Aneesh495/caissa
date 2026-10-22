# Local service and response ownership

`analysis-service/server.ts` binds only to loopback, checks a session token and origin, caps JSON at one MiB, and validates analysis resources. Position commands have a four-worker ceiling, five-second timeout and bounded response. Analysis has a two-process ceiling, finite time budget and output line limit. A full socket cancels the producer instead of queuing unbounded search updates.

`analysis-service/native.ts` owns each UCI child. Cancellation writes stop and quit, then kills a child that has not exited within 200 ms. Cleanup decrements the worker count once. Browser abort closes the stream and reaches that same cleanup path. UCI is responsible for joining its actual search workers before exiting. `tests/service_integration.mjs` exercises a real position, PGN variations, native analysis, stream cancellation, worker cleanup, bad input and token/origin rejection.

`web/app.ts` ties every incoming line to a selected node and request generation. Navigating a variation aborts the old stream and discards stale messages. Analysis sends the initial position plus the complete move path, preserving repetition context. Browser persistence stores exported PGN and a move path; restoration reparses through the native engine rather than trusting a cyclic or corrupt saved object graph.

The initial 10000-sequence UCI diagnostic measured stop p99 at 0.47 ms and maximum 16.29 ms. This is native protocol latency on that run, not HTTP latency and not a general service-level guarantee. A separate frozen full-load profile is pending.
