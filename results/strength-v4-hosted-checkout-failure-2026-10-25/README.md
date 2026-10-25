# Preserved hosted checkout failure

Correctness runs 40203647395 and 40204698873 failed on Linux and macOS before
the published original actor lineage controls could finish. The default shallow
checkout omitted compiled source commit 5803cc485420b19eb96dda2c29f81fcfc6b09b6b.
The independent native-input comparison consequently received exit 128 from
`git ls-tree`. Complete platform logs and their hashes are retained here.

The repair fetches that exact commit with depth one and a two-minute ceiling.
It retains the native-input comparison, original learning receipt, selected
checkpoint, frozen strength profile and saved match actor. The active strength
processes continue from their archived source. These failed hosted runs remain
failed; a later successful run is separate evidence.
