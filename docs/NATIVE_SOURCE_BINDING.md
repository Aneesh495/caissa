# Saved native source and input boundary

`verification.runtime_binding` independently joins the original frozen v4
profile, saved executable, selected network and unchanged original learning
receipt to a separately trusted committed checkout. It executes no native code
and performs no model inference. The caller supplies the expected profile hash
and exact product commit.

The original compiled source commit remains explicit. Its tracked native input
inventory must exactly match the product commit: CMakeLists.txt, every tracked
file under src/, include/, apps/ and cmake/, plus C/C++ headers, source, assembly
and CMake files elsewhere. Added, removed, edited, linked or mode-changed inputs
fail admission. The live checkout must agree with Git, including native file
modes, and ordinary untracked native inputs fail admission. The checker also
validates the original wire architecture, lattice, payload length, CRC, selected
checkpoint, classical contract and unchanged ten percent blend. Original failed
learning endpoints are carried into the report.

This establishes a tracked source and saved input relationship. It does not
establish the compiler invocation, compiler environment, ignored or external
build dependencies, reproducible binary output, runtime behavior, playing
strength or external source originality. Those remain separate requirements.
The report explicitly keeps runtime replay, compiler attribution and external
source comparison required. Its full gate and full acceptance fields stay false.

Full input bundles may provide `native_source_binding` with exactly two ordinary
path/SHA references: `observation` and `learning_receipt`. Full admission recomputes
the entire observation from the trusted checkout and actual saved inputs. A
rehashed false pass, omitted original failure or changed source map is rejected.
All existing sixteen gate identities and semantic replay requirements remain in
force. This boundary never rewrites an old receipt to a later source commit.

The targeted manual workflow tests only this new metadata boundary. Its fixture
engine is intentionally nonexecutable. It uses real temporary Git histories and
the published original network/learning receipt, with changed fixture actor
metadata clearly isolated from all frozen strength profiles. These controls do
not rerun native, browser, learning or strength campaigns and do not certify G14.
