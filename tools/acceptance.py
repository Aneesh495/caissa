"""Clean-checkout diagnostic campaign with an explicit full-acceptance barrier."""

import argparse, json, re, subprocess, sys, time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--profile", choices=["diagnostic", "full"], required=True)
    ap.add_argument("--protocol", default="config/protocol-v3.json")
    ap.add_argument("--dataset", type=Path)
    a = ap.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", a.run_id):
        ap.error("invalid run identity")
    root = Path.cwd()
    out = root / "runs" / a.run_id
    if out.exists():
        raise ValueError("run identity already exists; evidence is immutable")
    if subprocess.check_output(["git", "status", "--porcelain"], text=True, timeout=10):
        raise ValueError("commit all source inputs before acceptance")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()
    remote = subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/heads/main"], text=True, timeout=15
    ).split()[0]
    if remote != commit:
        raise ValueError("hosted source differs from local source")
    if a.profile == "full":
        from tools.full_readiness import inspect

        out.mkdir(parents=True)
        receipt = {"source_commit": commit, **inspect(root, a.protocol, a.dataset)}
        (out / "ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt))
        return 2
    source = root / "work" / ("acceptance-" + a.run_id)
    if source.exists():
        raise ValueError("isolated source path already exists")
    source.parent.mkdir(exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--local",
            str(root),
            str(source),
        ],
        check=True,
        timeout=120,
    )

    def run(command):
        subprocess.run(command, cwd=source, check=True, timeout=300)

    run(
        ["cmake", "-S", ".", "-B", "build", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"]
    )
    run(["cmake", "--build", "build", "-j", "4"])
    run(
        [
            sys.executable,
            "-m",
            "arena.run",
            "config/arena-ci.json",
            "runs/integration-arena",
            "--workers",
            "1",
        ]
    )
    run([sys.executable, "-m", "arena.statistics", "runs/integration-arena"])
    run(
        [
            sys.executable,
            "-m",
            "tools.evidence",
            "--checkout",
            str(source),
            "--engine",
            str(source / "build/caissa"),
            "--network",
            str(source / "models/diagnostic-v2.cai"),
            "--arena",
            str(source / "runs/integration-arena"),
            "--output",
            str(out),
        ]
    )
    verification = [
        sys.executable,
        "-m",
        "verification.verify",
        str(out),
        "--checkout",
        str(source),
        "--expected-commit",
        commit,
        "--profile",
        "diagnostic",
    ]
    run(verification)
    run(
        [
            sys.executable,
            "-m",
            "tools.negative_controls",
            str(out),
            str(root / "runs" / (a.run_id + "-negative")),
            "--checkout",
            str(source),
            "--expected-commit",
            commit,
        ]
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "profile": "diagnostic",
                "full_acceptance": False,
                "source": commit,
                "evidence": str(out),
                "trusted_checkout": str(source),
                "verify": verification,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
