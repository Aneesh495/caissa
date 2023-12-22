"""Read-only admission and boundary controls for the original-byte publisher."""

import argparse
import copy
import hashlib
import json
import tempfile
import time
from pathlib import Path

from tools.host_lease import HostLease
from tools.publish_evidence import admit, dependencies_closed, run


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    assert sha(args.plan) == args.expected_plan_sha256
    plan = json.loads(args.plan.read_text())
    protected = {name: sha(name) for name in plan["protected_metadata_files"]}
    cases = []
    root, _raw, index = admit(plan)
    assert len(index["volumes"]) == 319
    cases.append(
        {"case": "actual-original-index-and319member-metadata", "passed": True}
    )
    for field, replacement in [
        ("repository", "another/caissa"),
        ("branch", "main"),
        ("parent_deadline_unix", plan["parent_deadline_unix"] + 1),
        ("maximum_upload_seconds", 7201),
        ("maximum_upload_attempts", 3),
        ("minimum_write_interval_seconds", 0),
        ("base_commit", "invalid"),
        ("index_sha256", "0" * 64),
        ("original_sha256", "0" * 64),
        ("original_bytes", 1),
        ("gzip_bytes", 1),
        ("volume_count", 320),
        ("wait_deadline_unix", plan["wait_deadline_unix"] + 86400),
        ("frozen_source_files", {}),
    ]:
        forged = copy.deepcopy(plan)
        forged[field] = replacement
        try:
            admit(forged)
        except ValueError as error:
            cases.append({"case": "reject-changed-" + field, "reason": str(error)})
        else:
            raise AssertionError("hosting mutation accepted: " + field)
    with tempfile.TemporaryDirectory(prefix="caissa-hosting-admission-") as temporary:
        temporary = Path(temporary)
        linked = temporary / "linked"
        linked.symlink_to(root, target_is_directory=True)
        forged = copy.deepcopy(plan)
        forged["packet_root"] = str(linked)
        try:
            admit(forged)
        except ValueError:
            cases.append({"case": "linked-packet-rejected", "passed": True})
        else:
            raise AssertionError("linked hosting packet admitted")
        (temporary / "RESULT.json").write_text("{}\n")
        try:
            run(plan, temporary, check_only=True)
        except ValueError:
            cases.append(
                {"case": "closed-hosting-result-cannot-restart", "passed": True}
            )
        else:
            raise AssertionError("closed hosting result restarted")
    closed, owners = dependencies_closed(plan)
    cases.append(
        {"case": "actual-timed-dependency-state", "closed": closed, "owners": owners}
    )
    try:
        lease = HostLease(Path(plan["project"]) / "runs")
    except ValueError:
        cases.append(
            {"case": "actual-timed-host-lease-refuses-competing-work", "passed": True}
        )
    else:
        lease.close()
        cases.append(
            {"case": "actual-host-was-free-probe-released-without-work", "passed": True}
        )
    observed = run(plan, args.plan.parent, check_only=True)
    assert observed["body_hashing_upload_or_scope_started"] is False
    assert protected == {name: sha(name) for name in protected}
    assert not (args.plan.parent / "HOSTING_SCOPE.json").exists()
    result = {
        "status": "passed readonly admission",
        "cases": cases,
        "actual_admission": observed,
        "seconds": time.monotonic() - started,
        "old_portable_metadata_unchanged": True,
        "uploads_or_new_ref": False,
        "body_hashing_or_gzip_decode": False,
        "full_G15_certified": False,
    }
    (args.plan.parent / "PREFLIGHT_RESULT.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "cases": len(cases),
                "seconds": result["seconds"],
                "uploads_or_new_ref": False,
                "full_G15_certified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
