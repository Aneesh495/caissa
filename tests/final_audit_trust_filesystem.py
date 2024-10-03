"""Unexecuted filesystem controls for a future admitted metadata-only owner.

Nothing runs on import. The caller must supply a new empty, owned fixture
directory inside this project and explicitly admit bounded synthetic links,
one FIFO and one mutable fixture. No real audit receipt or scope is created.
"""

import hashlib
import errno
import json
import os
from pathlib import Path
from unittest.mock import patch

from verification.bundle import Bundle
from verification.final_audit_trust import load_external_trust
from verification.source import require


ROOT = Path(__file__).resolve().parents[1]
SOURCE, INVENTORY = "1" * 40, "5" * 64


def run_controls(fixture_root):
    root = Path(fixture_root).absolute()
    require(root == root.resolve() and root.is_dir() and not any(root.iterdir())
            and any(root != ROOT / n and root.is_relative_to(ROOT / n)
                    for n in ("work", "runs")),
            "filesystem controls require an empty owned project fixture directory")
    work, evidence = root / "work", root / "evidence"
    work.mkdir()
    evidence.mkdir()
    doc = {"schema": "caissa-final-audit-external-trust-v1",
           "scope_path": "work/synthetic-audit-policy/SCOPE.json",
           "scope_sha256": "2" * 64, "result_sha256": "3" * 64,
           "owner_closed_sha256": "4" * 64,
           "source_commit": SOURCE, "source_inventory_sha256": INVENTORY}
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    charged, files, cases = [0], [], []

    def put(name, content=raw):
        charged[0] += len(content)
        require(charged[0] <= 32768 and len(files) < 24,
                "finite synthetic filesystem fixture ceiling exceeded")
        target = root / name
        with target.open("xb") as stream:
            stream.write(content)
        target.chmod(0o600)
        files.append(name)
        return target

    def load(name, expected=digest, *, bundle=evidence):
        return load_external_trust(root, bundle, name, expected, SOURCE, INVENTORY)

    def reject(name, callback, reason=None, allowed_errno=None):
        try:
            callback()
        except (ValueError, OSError, KeyError, TypeError) as error:
            if reason is not None:
                require(reason in str(error), "filesystem fault rejected for the wrong reason")
            if allowed_errno is not None:
                require(isinstance(error, OSError) and error.errno in allowed_errno,
                        "filesystem fault did not reach the no-follow OS boundary")
            cases.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new external-receipt filesystem fault accepted: " + name)

    # These bytes are synthetic policy fixtures. They never name a real accepted
    # audit output, and the full independent audit reader is never invoked.
    good = put("work/private.json")
    trust = load("work/private.json")
    require(trust.receipt_sha256 == digest and trust.source_commit == SOURCE
            and good.read_bytes() == raw, "private fixture identity or bytes changed")
    cases.append({"case": "private_regular_receipt_loads_exact_bytes",
                  "synthetic_fixture": True, "real_audit_accepted": False})
    require(load(None, None) is None, "absent external receipt did not stay absent")
    cases.append({"case": "absent_optional_receipt_stays_unverified",
                  "synthetic_fixture": True, "real_audit_accepted": False})

    reject("path_without_expected_digest", lambda: load("work/private.json", None),
           reason="supplied together")
    reject("digest_without_path", lambda: load(None, digest), reason="supplied together")
    inside = work / "inside-bundle"
    inside.mkdir()
    put("work/inside-bundle/receipt.json")
    reject("receipt_inside_evidence_bundle", lambda: load(
        "work/inside-bundle/receipt.json", bundle=inside), reason="inside its evidence bundle")
    reject("changed_external_digest", lambda: load("work/private.json", "0" * 64),
           reason="receipt identity differs")

    public = put("work/public-mode.json")
    public.chmod(0o644)
    reject("public_receipt_mode", lambda: load("work/public-mode.json"),
           reason="linked, public or excessive")
    public.chmod(0o600)  # Retained synthetic files contain no secrets.
    put("work/empty.json", b"")
    reject("empty_receipt", lambda: load("work/empty.json"), reason="linked, public or excessive")
    put("work/oversized.json", b"x" * 8193)
    reject("oversized_receipt", lambda: load("work/oversized.json"), reason="linked, public or excessive")

    final_link = work / "final-link.json"
    final_link.symlink_to("private.json")
    reject("final_component_symlink", lambda: load("work/final-link.json"),
           allowed_errno={errno.ELOOP, errno.ENOTDIR})
    parent = work / "real-parent"
    parent.mkdir()
    put("work/real-parent/receipt.json")
    (work / "linked-parent").symlink_to("real-parent", target_is_directory=True)
    reject("parent_component_symlink", lambda: load("work/linked-parent/receipt.json"),
           allowed_errno={errno.ELOOP, errno.ENOTDIR})
    hard = put("work/hard-source.json")
    os.link(hard, work / "hard-alias.json")
    reject("hardlinked_receipt", lambda: load("work/hard-alias.json"),
           reason="linked, public or excessive")
    os.mkfifo(work / "receipt-fifo", 0o600)
    reject("fifo_rejected_without_blocking", lambda: load("work/receipt-fifo"),
           reason="must be a regular file")
    (work / "receipt-directory").mkdir()
    reject("directory_not_receipt", lambda: load("work/receipt-directory"),
           reason="must be a regular file")
    reject("outside_private_metadata_namespace", lambda: load("other/receipt.json"),
           reason="attributed private project metadata")
    reject("escaped_relative_path", lambda: load("work/../private.json"),
           reason="safe canonical relative")
    flagged = json.dumps({**doc, "full_acceptance": True}).encode()
    put("work/caller-pass.json", flagged)
    reject("caller_pass_field_in_file", lambda: load(
        "work/caller-pass.json", hashlib.sha256(flagged).hexdigest()),
           reason="schema or extra pass fields")

    changing = put("work/changing.json")
    original_open = Bundle.open

    class MutatingRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, maximum):
            observed = self.stream.read(maximum)
            # A synchronized real size change occurs after the read and before
            # the loader's real fstat. No timing race or synthetic stamp is used.
            charged[0] += 1
            require(charged[0] <= 32768, "mutable fixture budget exhausted")
            with changing.open("ab") as output:
                output.write(b" ")
            return observed

    def intercept_open(bundle, name):
        stream, before = original_open(bundle, name)
        return (MutatingRead(stream), before) if name == "work/changing.json" else (stream, before)

    with patch.object(Bundle, "open", intercept_open):
        reject("changed_during_actual_descriptor_read", lambda: load("work/changing.json"),
               reason="changed during read")

    return {"status": "passed_new_synthetic_external_audit_filesystem_controls",
            "controls": len(cases), "cases": cases,
            "fixture_payload_bytes_written": charged[0], "regular_fixture_files": files,
            "synthetic_symlinks": 2, "synthetic_hardlink_aliases": 1, "synthetic_fifos": 1,
            "real_audit_receipts_created": 0, "actual_audit_accepted": False,
            "actual_full_entry_starts": 0, "full_acceptance": False}
