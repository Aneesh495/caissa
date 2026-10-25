"""Render saved data-only observations without importing any training/model code."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    raw_bytes = args.profile.read_bytes()
    report = json.loads(raw_bytes)
    if (
        report["schema"] != "caissa-data-profile-v1"
        or report["model_evaluated"] is not False
    ):
        raise ValueError("expected data-only coverage observations")
    args.output.mkdir(parents=True, exist_ok=False)
    raw_labels = [
        ("material", "Piece count", 0.8),
        ("phase", "Tapered material phase (0 to 24)", 0.8),
        ("ply", "Game ply, ten-ply bins", 9),
        ("outcome", "Side-to-move outcome score", 0.18),
        ("clock", "Halfmove clock, ten-ply bins", 9),
        ("teacher", "Teacher cp bin starts, clipped at +/-2000", 90),
    ]
    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(2, 3, figsize=(13, 8), layout="constrained")
    for ax, (name, title, width) in zip(axes.flat, raw_labels):
        rows = sorted(
            (float(label), count)
            for label, count in report["raw_observation_histograms"][name].items()
        )
        total = sum(count for _, count in rows)
        ax.bar(
            [label for label, _ in rows],
            [count / total for _, count in rows],
            width=width,
            color="#356b55",
        )
        ax.set_xlabel(title)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(
        f"Caissa corpus coverage: {report['source_counts']['raw_positions']:,} raw observations\nRepeated inputs remain counted here; these are dataset statistics, not model strength",
        fontsize=14,
    )
    fig.savefig(args.output / "corpus-coverage.png", dpi=180)
    fig.savefig(args.output / "corpus-coverage.svg")
    plt.close(fig)
    titles = {
        "material": "Pieces per unique input",
        "phase": "Material phase per unique input",
        "outcome": "Mean outcome target",
        "teacher_cp": "Mean teacher cp, tails clipped +/-2000",
        "teacher_probability": "Mean teacher probability target",
        "absolute_target_disagreement": "Absolute outcome/teacher target disagreement",
    }
    fig, axes = plt.subplots(2, 3, figsize=(13, 8), layout="constrained")
    for ax, (name, title) in zip(axes.flat, titles.items()):
        for split, color in zip(
            ("train", "validation", "test"), ("#356b55", "#c17920", "#5f54b3")
        ):
            values = report["splits"][split]
            counts = values["histograms"][name]
            if sum(counts) != values["rows"]:
                raise ValueError("split histogram lost rows")
            ax.stairs(
                [count / values["rows"] for count in counts],
                report["bins"][name],
                label=split,
                color=color,
                linewidth=1.6,
            )
        ax.set_xlabel(title)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis="y", alpha=0.2)
    axes.flat[0].legend()
    fig.suptitle(
        "Caissa exported-input distributions by split\nEqual weight per deduplicated input; no neural model or model test score evaluated",
        fontsize=14,
    )
    fig.savefig(args.output / "split-distributions.png", dpi=180)
    fig.savefig(args.output / "split-distributions.svg")
    plt.close(fig)
    (args.output / "PLOTS.json").write_text(
        json.dumps(
            {
                "profile_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "matplotlib": matplotlib.__version__,
                "plots": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in args.output.iterdir()
                    if p.suffix in (".svg", ".png")
                },
                "full_acceptance": False,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
