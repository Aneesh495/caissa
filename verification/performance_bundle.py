"""Stage exact G13 observations and independently reconstruct the full sample.

Metadata admission never certifies performance. Native replay runs in the
bounded owner's process group so timeout cleanup includes its saved engine.
"""

import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from verification.bundle import strict_json
from verification.draw_history import typed_equal
from verification.source import require

FILES = {
    "config": "CONFIG.json",
    "summary": "SUMMARY.json",
    "sessions": "SESSIONS.json",
    "measurements": "measurements.jsonl",
    "memory": "memory.jsonl",
    "latency": "latency.jsonl",
    "correctness": "correctness.json",
    "profile": "PROFILE.json",
}


def admit(bundle, inputs):
    domain = inputs["domains"]["G13"]
    arguments = domain["performance"]
    require(
        isinstance(arguments, dict) and set(arguments) == set(FILES),
        "G13 requires its exact eight performance artifact references",
    )
    paths = {key: bundle.reference(ref) for key, ref in arguments.items()}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        len(set(paths.values())) == len(FILES) and set(paths.values()) <= declared,
        "G13 performance inputs must be distinct and declared",
    )
    config = bundle.json(paths["config"])
    summary = bundle.json(paths["summary"])
    profile = bundle.json(paths["profile"])
    require(
        config.get("schema") == "caissa-performance-run-v2"
        and summary.get("schema") == "caissa-performance-summary-v2",
        "G13 requires actual raw v2 performance observations",
    )
    require(
        config.get("profile") == "full-performance-unverified"
        and config.get("exact_optimizations") is True
        and config.get("lazy_neural") is True,
        "G13 cannot promote a diagnostic or different deployment runtime",
    )
    require(
        config.get("engine_sha256") == inputs["engine"]["sha256"]
        and config.get("network_sha256") == inputs["network"]["artifact"]["sha256"],
        "G13 program/network differs from the full deployment",
    )
    require(
        config.get("config_sha256") == arguments["profile"]["sha256"]
        and typed_equal(config.get("config"), profile),
        "G13 position/resource profile differs from its frozen identity",
    )
    require(
        profile.get("schema") == "caissa-performance-v1"
        and typed_equal(profile.get("threads"), [1, 2, 4, 8])
        and type(profile.get("milliseconds")) is int
        and profile["milliseconds"] == 250
        and type(profile.get("repeats")) is int
        and 5 <= profile["repeats"] <= 20
        and type(profile.get("latency_samples")) is int
        and 1000 <= profile["latency_samples"] <= 10000
        and type(profile.get("hash_mib")) is int
        and profile["hash_mib"] == 16
        and isinstance(profile.get("positions"), list)
        and 8 <= len(profile["positions"]) <= 100
        and type(config.get("cpu_count")) is int
        and config["cpu_count"] >= 8,
        "G13 full thread/workload or supported host sample is incomplete",
    )
    duration, start, deadline = (
        config.get(k) for k in ["maximum_seconds", "started_unix", "deadline_unix"]
    )
    import math

    require(
        all(
            type(v) in (int, float) and math.isfinite(v)
            for v in [duration, start, deadline]
        )
        and 1 <= duration <= 3600
        and deadline == start + duration,
        "G13 producer cumulative deadline is invalid",
    )
    raw = {
        key: filename
        for key, filename in FILES.items()
        if key not in {"config", "summary", "profile"}
    }
    require(
        isinstance(summary.get("files"), dict)
        and set(summary["files"]) == set(raw.values()),
        "G13 raw performance inventory is missing or extra",
    )
    for key, filename in raw.items():
        require(
            summary["files"][filename] == arguments[key]["sha256"],
            "G13 raw observation digest differs from its summary",
        )
    return paths, config, profile


def verify(bundle, inputs, output):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    paths, config, profile = admit(bundle, inputs)
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G13 replay must preserve original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    stamps = {}
    for key, name in FILES.items():
        cap = (
            128 if key == "measurements" else 32 if key in {"memory", "latency"} else 4
        ) * 1024**2
        bundle.copy(paths[key], raw / name, cap)
        stamps[name] = bundle.stamp((raw / name).stat())
    for name, ref, cap in [
        ("caissa", inputs["engine"], 64 * 1024**2),
        ("selected.cai", inputs["network"]["artifact"], 4 * 1024**2),
    ]:
        bundle.copy(bundle.reference(ref), raw / name, cap)
        stamps[name] = bundle.stamp((raw / name).stat())
    (raw / "caissa").chmod(0o755)
    # Mode is changed intentionally on the owned executable copy only.
    stamps["caissa"] = bundle.stamp((raw / "caissa").stat())
    remaining = min(
        1800,
        bundle.monotonic_deadline - time.monotonic(),
        bundle.wall_deadline - time.time(),
    )
    require(remaining > 1, "G13 original cumulative replay deadline exhausted")
    code = Path(__file__).resolve().parents[1]
    launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('verification.performance',run_name='__main__')"
    command = [
        sys.executable,
        "-P",
        "-c",
        launcher,
        str(code),
        str(raw),
        "--engine",
        str(raw / "caissa"),
        "--network",
        str(raw / "selected.cai"),
        "--config",
        str(raw / "PROFILE.json"),
        "--expected-config-sha256",
        inputs["domains"]["G13"]["performance"]["profile"]["sha256"],
        "--maximum-seconds",
        str(max(1, int(remaining))),
        "--require-full",
        "--replay-output",
        str(output / "NATIVE_REPLAY.jsonl"),
        "--inherit-process-group",
    ]
    campaign = Campaign(
        output / "execution",
        {
            "gate": "G13",
            "engine_sha256": config["engine_sha256"],
            "network_sha256": config["network_sha256"],
        },
        remaining,
        absolute_deadline=bundle.wall_deadline,
        resource_guard=bundle.tick,
    )
    try:
        try:
            campaign.run(
                "independent", command, remaining, maximum_output_bytes=4 * 1024**2
            )
        except StageFailure as error:
            raise ValueError(
                "G13 independent performance replay failed; inspect preserved execution"
            ) from error
        result = strict_json((output / "execution/independent.log").read_bytes())
        expected = (
            4 * len(profile["threads"]) * profile["repeats"] * len(profile["positions"])
        )
        require(
            result.get("status") == "passed"
            and result.get("scope") == "full performance workload replay"
            and result.get("timed_searches") == expected
            and result.get("independent_fixed_node_searches")
            == 2 * len(profile["positions"])
            and result.get("latency_samples") == 2 * profile["latency_samples"]
            and result.get("engine_sha256") == config["engine_sha256"]
            and result.get("network_sha256") == config["network_sha256"],
            "G13 reader did not reconstruct the complete declared sample",
        )
        for name, stamp in stamps.items():
            require(
                bundle.stamp((raw / name).stat()) == stamp,
                "G13 staged performance evidence changed during replay",
            )
        bundle.tick()
        result.update(
            gate="G13",
            full_gate=True,
            full_acceptance=False,
            parallel_strength_and_race_evidence_required_for_G10=True,
        )
        atomic(output / "PERFORMANCE.json", result)
        campaign.close("passed-full-performance-domain", result)
        return result
    finally:
        campaign.close("failed unless already completed")
