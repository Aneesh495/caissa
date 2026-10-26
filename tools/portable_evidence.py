"""Own one original-byte archive and independent restore within a fixed scope."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.evidence_volumes import pack
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard
from tools.host_lease import HostLease
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.bundle import digest_text
from verification.source import PRODUCT, require, snapshot, verify_checkout

PARENT_DEADLINE = 1793150297.974828


def execute(args):
    root = Path.cwd().resolve()
    digest_text(args.input_sha256)
    require(
        type(args.input_bytes) is int and 0 < args.input_bytes <= 8 * 1024**3,
        "portable original size outside bound",
    )
    original = args.input.resolve()
    require(
        not args.input.is_symlink()
        and original.is_file()
        and original.stat().st_size == args.input_bytes,
        "portable original input metadata differs",
    )
    output = root / "runs/portable-evidence-v1" / args.input_sha256
    require(
        not output.exists(), "this original-byte packing scope already exists; no reset"
    )
    require(
        time.time() + 2700 <= PARENT_DEADLINE,
        "portable scope cannot fit original parent deadline",
    )
    source = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": args.expected_commit,
        "files": snapshot(root, args.expected_commit, PRODUCT),
    }
    verify_checkout(root, source, args.expected_commit, PRODUCT)
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, timeout=10
        ),
        "commit portable codec before collecting observations",
    )
    if args.check_only:
        return {
            "status": "metadata admitted; original bytes not yet hashed",
            "scope_created": False,
            "input_bytes": args.input_bytes,
            "input_sha256": args.input_sha256,
            "full_acceptance": False,
        }
    lease = HostLease(root / "runs")
    scope = power = campaign = None
    try:
        bindings = {
            "source_commit": args.expected_commit,
            "input_sha256": args.input_sha256,
            "input_bytes": args.input_bytes,
            "input_path": str(original),
            "parent_deadline_unix": PARENT_DEADLINE,
        }
        scope = RecoveryScope(
            output,
            bindings,
            2700,
            output / "empty-input-accounting",
            10,
            20,
            maximum_active_seconds=2700,
        )
        power = PowerGuard(POLICY if sys.platform == "darwin" else None)
        power.start(output)

        host = HostGuard(output, scope, power)

        def guard():
            lease.check()
            host.check()

        guard()
        atomic(output / "SOURCE_INPUTS.json", source)
        atomic(
            output / "PLAN.json",
            {
                **bindings,
                "maximum_seconds": 2700,
                "maximum_attempts": 1,
                "maximum_additional_bytes": 20 * 1024**3,
                "minimum_free_bytes": 10 * 1024**3,
                "power_policy": "battery allowed; power state recorded",
                "host_policy": "exclusive Caissa lease; unrelated compiler work allowed for untimed byte transport",
                "semantic_verification_required": True,
            },
        )
        archive_source(root, output / "source", args.expected_commit, source["files"])

        def progress(count, volumes):
            atomic(
                output / "PACK_PROGRESS.json",
                {
                    "phase": "packing",
                    "original_bytes_encoded": count,
                    "complete_volumes": volumes,
                    "declared_original_bytes": args.input_bytes,
                },
            )

        packed = pack(
            original,
            output / "artifact",
            args.input_sha256,
            args.input_bytes,
            guard,
            progress,
        )
        atomic(output / "ENCODING.json", packed)
        campaign = Campaign(
            output / "execution",
            bindings,
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=guard,
        )
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('verification.evidence_volumes',run_name='__main__')"
        campaign.run(
            "independent-byte-reconstruction",
            [
                sys.executable,
                "-B",
                "-P",
                "-c",
                launcher,
                str(output / "source"),
                str(output / "artifact/VOLUMES.json"),
                "--expected-index-sha256",
                packed["index_sha256"],
                "--expected-original-sha256",
                args.input_sha256,
                "--expected-original-bytes",
                str(args.input_bytes),
                "--output",
                str(output / "reconstructed/original.raw"),
                "--maximum-seconds",
                str(min(900, max(1, int(scope.remaining())))),
            ],
            scope.remaining(),
            cwd=root,
            env=lease.environment(),
            pass_fds=(lease.stream.fileno(),),
        )
        raw = (output / "execution/independent-byte-reconstruction.log").read_bytes()
        result = json.loads(raw)
        require(
            result["status"] == "passed"
            and result["raw_sha256"] == args.input_sha256
            and result["raw_bytes"] == args.input_bytes
            and result["semantic_verification_required"] is True,
            "independent portable reconstruction failed",
        )
        receipt = {
            **bindings,
            "status": "lossless volume reconstruction passed",
            "index_sha256": packed["index_sha256"],
            "independent_sha256": hashlib.sha256(raw).hexdigest(),
            "volumes": packed["volumes"],
            "gzip_bytes": packed["gzip_bytes"],
            "scope_closed": True,
            "semantic_verification_required": True,
            "full_acceptance": False,
        }
        campaign.close("passed byte reconstruction only", receipt)
        atomic(output / "PORTABLE.json", receipt)
        return receipt
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        if output.exists():
            atomic(
                output / "FAILED.json",
                {
                    "reason": str(error),
                    "observed_unix": time.time(),
                    "full_acceptance": False,
                },
            )
        raise
    finally:
        if power is not None:
            power.close()
        if scope is not None:
            scope.close()
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--input-bytes", type=int, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(execute(args)))


if __name__ == "__main__":
    main()
