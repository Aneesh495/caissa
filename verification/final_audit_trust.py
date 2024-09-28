"""Unexecuted external audit-root admission, with no built-in accepted root.

The expected receipt digest must come from the independently recorded future
entry scope, not FULL_INPUTS, a domain descriptor or a bundle manifest. This is
an evidence trust input, not permission to execute an owner or experiment.
"""

from dataclasses import dataclass
import hashlib
import os
import stat
from pathlib import Path

from verification.bundle import Bundle, digest_text, strict_json
from verification.source import relative_path, require


@dataclass(frozen=True)
class AuditTrust:
    scope_path: str
    scope_sha256: str
    result_sha256: str
    owner_closed_sha256: str
    source_commit: str
    source_inventory_sha256: str
    receipt_sha256: str

    @property
    def work(self):
        return self.scope_path.removesuffix("SCOPE.json")


def decode_external_trust(raw, expected_receipt_sha256, expected_commit, source_inventory_sha256):
    require(len(raw) <= 8192 and hashlib.sha256(raw).hexdigest()
            == digest_text(expected_receipt_sha256), "external audit receipt identity differs")
    doc = strict_json(raw)
    require(isinstance(doc, dict) and set(doc) == {
        "schema", "scope_path", "scope_sha256", "result_sha256", "owner_closed_sha256",
        "source_commit", "source_inventory_sha256"
    } and doc["schema"] == "caissa-final-audit-external-trust-v1",
            "external audit receipt schema or extra pass fields differ")
    scope_path = relative_path(doc["scope_path"])
    require(scope_path.startswith("work/") and scope_path.endswith("/SCOPE.json"),
            "external audit scope must name an actual bounded work scope")
    require(doc["source_commit"] == expected_commit
            and doc["source_inventory_sha256"] == digest_text(source_inventory_sha256),
            "external audit receipt names stale audited source")
    for key in ("scope_sha256", "result_sha256", "owner_closed_sha256"):
        digest_text(doc[key])
    return AuditTrust(scope_path, doc["scope_sha256"], doc["result_sha256"],
                      doc["owner_closed_sha256"], expected_commit,
                      source_inventory_sha256, expected_receipt_sha256)


def load_external_trust(checkout, evidence_root, name, expected_receipt_sha256,
                        expected_commit, source_inventory_sha256):
    require((name is None) == (expected_receipt_sha256 is None),
            "external audit receipt path and trusted digest must be supplied together")
    if name is None:
        return None
    name = relative_path(name)
    require(name.startswith((".agent-local/", "work/")),
            "external audit receipt must stay in attributed private project metadata")
    root = Path(checkout).resolve()
    path = root / name
    require(not path.resolve().is_relative_to(Path(evidence_root).resolve()),
            "audit receipt cannot be supplied inside its evidence bundle")
    # Existing Bundle traversal rejects linked components and nonregular files.
    # Read only this separately pinned receipt; no new manifest or output exists.
    with Bundle(root, maximum_seconds=5) as trusted:
        stream, before = trusted.open(name)
        with stream:
            require(before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600
                    and 0 < before.st_size <= 8192,
                    "external audit receipt is linked, public or excessive")
            raw = stream.read(8193)
            after = os.fstat(stream.fileno())
        require(len(raw) == before.st_size and Bundle.stamp(before) == Bundle.stamp(after),
                "external audit receipt changed during read")
        trusted.tick()
    return decode_external_trust(raw, expected_receipt_sha256, expected_commit,
                                 source_inventory_sha256)
