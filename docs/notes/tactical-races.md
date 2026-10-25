# Instrumented native race replay

A separate current-core build used ThreadSanitizer, RelWithDebInfo and the active 64-wide network format. All 15 native CTest cases passed, including exact evaluation-cache and tactical-generation cases. The same instrumented build passed 10000 incremental transitions for each of the two retained original diagnostic networks. The complete producer campaign took 129.83 seconds within its declared 1200-second scope.

The independent checker compares the archived source inventory with trusted Git blobs, checks separate instrumentation flags and linked runtime hooks, and invokes every native case directly. It writes separate logs so the original CTest records remain immutable. The original source is commit `e74e64e6e55f15b8b75e1c4162ac843e0b528272`.

Independent replay completed 13 cases before host sleep consumed the stage wall allowance. It did not finish the final cache/tactical cases or repeat the transition sample. Process-group cleanup then raised an actual PermissionError and obscured the final child exit record. The raw journal, exception and partial outputs remain retained. Its 1200-second budget is exhausted and was not renewed. This is incomplete independent race evidence, even though the original producer completed all cases.

The process controller now records denied cleanup separately. A genuine timeout or exit 7 remains the primary failure. A zero-exit parent with denied cleanup is failed explicitly. Three synthetic denial cases and the existing process lifecycle controls passed. No successful cleanup or whole-project race claim follows from the interrupted replay.

[Native source identities, actual instrumentation, complete producer logs, partial independent replay and cleanup controls](../../results/tactical-races-2026-10-24/) preserve the boundary. Final selected-model race and parallel strength measurements remain required.
