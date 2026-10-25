"""Bind G06 to full raw probes and execute the independent numerical reader.

Admission alone never certifies numerical correctness. The bounded child must
replay the saved executable, integer bytes and selected floating checkpoint.
"""

import hashlib
import math
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from verification.bundle import strict_json
from verification.source import require


class NumericalEndpointFailure(ValueError):
    def __init__(self, reason, observed):
        super().__init__(reason)
        self.observed = observed


def admit(bundle, inputs):
    domain = inputs["domains"]["G06"]
    arguments = domain["numerical"]
    keys = {"profile", "config", "summary", "positions", "observations", "checkpoint"}
    require(
        isinstance(arguments, dict) and set(arguments) == keys,
        "G06 requires the exact six numerical artifact references",
    )
    paths = {key: bundle.reference(arguments[key]) for key in keys}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        len(set(paths.values())) == len(keys) and set(paths.values()) <= declared,
        "G06 numerical artifacts must be distinct and declared",
    )
    require(
        arguments["checkpoint"]["sha256"] == inputs["network"]["checkpoint_sha256"],
        "G06 float checkpoint differs from validation-only deployment selection",
    )
    protocol = bundle.json(bundle.reference(inputs["protocol"]))
    config = bundle.json(paths["config"])
    summary = bundle.json(paths["summary"])
    rule = protocol["network"]
    require(
        config.get("schema") == "caissa-network-audit-v2"
        and config.get("trained") is True
        and config.get("generator")
        == "standard-legal-walk-v1; terminal-or-ply>240-or-random<0.01 reset",
        "G06 lacks the trained seeded numerical observation contract",
    )
    require(
        type(config.get("probes")) is int
        and 100000 <= config["probes"] <= 1000000
        and type(rule.get("probes")) is int
        and config["probes"] == rule["probes"]
        and type(config.get("probe_seed")) is int
        and type(rule.get("probe_seed")) is int
        and config["probe_seed"] == rule["probe_seed"],
        "G06 requires the complete frozen 100000-probe sample and seed",
    )
    profile = bundle.json(paths["profile"])
    numerical_rule = profile["network"]
    require(
        profile.get("status") == "frozen"
        and profile.get("schema")
        in {
            "caissa-precision-profile-v1",
            "caissa-experiment-protocol-v3",
            "caissa-experiment-protocol-v4",
        }
        and all(
            type(numerical_rule.get(k)) is type(rule[k])
            and numerical_rule[k] == rule[k]
            for k in [
                "format",
                "width",
                "scale",
                "clip",
                "probes",
                "probe_seed",
                "maximum_float_error_cp",
                "error_contract",
                "neural_weight",
            ]
        ),
        "G06 numerical profile differs from frozen deployment semantics",
    )
    if rule["format"] == 4:
        require(
            numerical_rule.get("training_format") == 3
            and numerical_rule.get("export_contract")
            == config.get("export_contract")
            == "v3-float-to-v4-q4096-same-activation-ceiling-v1"
            and type(config.get("export_format")) is int
            and config["export_format"] == 4,
            "G06 q4096 replay lacks its original same-parameter export contract",
        )
    if profile["schema"] == "caissa-precision-profile-v1":
        require(
            profile.get("checkpoint_sha256") == inputs["network"]["checkpoint_sha256"],
            "G06 numerical profile changed the selected float checkpoint",
        )
    tolerance = config.get("maximum_error_cp")
    require(
        type(tolerance) in {int, float}
        and math.isfinite(tolerance)
        and 0 < tolerance <= 32
        and tolerance == rule["maximum_float_error_cp"]
        and config.get("error_contract")
        == rule.get("error_contract")
        == "unclamped-quantization-and-clamped-inference",
        "G06 frozen numerical error bound or unclamped contract differs",
    )
    require(
        type(config.get("maximum_seconds")) in {int, float}
        and math.isfinite(config["maximum_seconds"])
        and 1 <= config["maximum_seconds"] <= 3600,
        "G06 producer duration must retain its finite original ceiling",
    )
    identities = {
        "engine_sha256": inputs["engine"]["sha256"],
        "network_sha256": inputs["network"]["artifact"]["sha256"],
        "checkpoint_sha256": inputs["network"]["checkpoint_sha256"],
    }
    require(
        all(config.get(k) == v and summary.get(k) == v for k, v in identities.items()),
        "G06 producer inputs differ from the deployed engine or selected model",
    )
    require(
        config.get("positions_sha256") == arguments["positions"]["sha256"]
        and summary.get("positions_sha256") == arguments["positions"]["sha256"]
        and summary.get("probes_sha256") == arguments["observations"]["sha256"],
        "G06 raw positions or observation identities differ",
    )
    require(
        type(summary.get("probes")) is int
        and summary["probes"] == config["probes"]
        and type(summary.get("probe_seed")) is int
        and summary["probe_seed"] == config["probe_seed"],
        "G06 producer sample summary differs from its frozen configuration",
    )
    return paths, config, identities


def verify(bundle, inputs, output):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    paths, config, identities = admit(bundle, inputs)
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G06 replay must preserve the original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    staged = {}
    for key, filename, maximum in [
        ("config", "CONFIG.json", 4 * 1024**2),
        ("summary", "SUMMARY.json", 4 * 1024**2),
        ("positions", "POSITIONS.fen", 256 * 1024**2),
        ("observations", "probes.jsonl", 512 * 1024**2),
        ("checkpoint", "selected.pt", 128 * 1024**2),
        ("profile", "NUMERICAL_PROFILE.json", 4 * 1024**2),
    ]:
        staged[key] = raw / filename
        bundle.copy(paths[key], staged[key], maximum)
    for key, reference, filename, maximum in [
        ("engine", inputs["engine"], "caissa", 64 * 1024**2),
        ("network", inputs["network"]["artifact"], "selected.cai", 4 * 1024**2),
        ("protocol", inputs["protocol"], "PROTOCOL.json", 4 * 1024**2),
    ]:
        staged[key] = output / filename
        bundle.copy(bundle.reference(reference), staged[key], maximum)
    staged["engine"].chmod(0o755)
    bundle.tick()
    remaining = min(
        bundle.monotonic_deadline - time.monotonic(), bundle.wall_deadline - time.time()
    )
    require(remaining > 1, "G06 original cumulative replay deadline exhausted")
    # Bound tensor loading, native replay and FP64 work from outside the child.
    # Importing PyTorch in the admission process would evade this outer bound.
    code = Path(__file__).resolve().parents[1]
    launcher = (
        "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
        "runpy.run_module('verification.numerical',run_name='__main__')"
    )
    command = [
        sys.executable,
        "-P",
        "-c",
        launcher,
        str(code),
        str(raw),
        "--engine",
        str(staged["engine"]),
        "--network",
        str(staged["network"]),
        "--checkpoint",
        str(staged["checkpoint"]),
        "--protocol",
        str(staged["profile"]),
        "--expected-network-sha256",
        identities["network_sha256"],
        "--expected-checkpoint-sha256",
        identities["checkpoint_sha256"],
        "--require-full",
        "--max-seconds",
        str(min(3600, remaining)),
        "--inherit-process-group",
    ]
    campaign = Campaign(
        output / "execution",
        {
            "gate": "G06",
            **identities,
            "reader_sha256": hashlib.sha256(
                (code / "verification/numerical.py").read_bytes()
            ).hexdigest(),
            "full_acceptance": False,
        },
        remaining,
        absolute_deadline=bundle.wall_deadline,
        resource_guard=bundle.tick,
    )
    try:
        failure = None
        try:
            record = campaign.run(
                "independent", command, remaining, maximum_output_bytes=4 * 1024**2
            )
        except StageFailure as error:
            record, failure = error.record, error
        log = output / "execution/independent.log"
        result = strict_json(log.read_bytes())
        if failure is not None:
            observed = result.get("observed", {})
            if (
                record["exit"] == 1
                and record["reason"] == "nonzero-exit"
                and result.get("reason") == "frozen numerical error bound failed"
                and observed.get("status") == "failed-frozen-error-bound"
                and observed.get("probes") == config["probes"]
                and all(observed.get(k) == v for k, v in identities.items())
            ):
                campaign.close("failed-numerical-endpoint", observed)
                atomic(output / "NUMERICAL.json", result)
                raise NumericalEndpointFailure(result["reason"], observed)
            raise ValueError(
                "G06 independent numerical process failed; inspect preserved execution"
            ) from failure
        require(
            result.get("status") == "passed"
            and result.get("probes") == config["probes"]
            and result.get("scope") == "full G06 numerical probe sample"
            and result.get("native_replay", {}).get("exit") == 0
            and all(result.get(k) == v for k, v in identities.items()),
            "G06 numerical reader did not complete the actual full sample",
        )
        bundle.tick()
        result.update(gate="G06", full_gate=True, full_acceptance=False)
        campaign.close("passed", result)
        atomic(output / "NUMERICAL.json", result)
        return result
    finally:
        if not campaign.closed:
            campaign.close("failed")
