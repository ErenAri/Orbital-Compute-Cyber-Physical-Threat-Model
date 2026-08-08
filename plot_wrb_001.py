"""Generate WRB-001 figures strictly from machine-readable run records."""

from __future__ import annotations

from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
import csv

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from wrb_001_workloads import WORKLOAD_IDS


ROOT = Path(__file__).resolve().parent
DEFAULT_RUNS = ROOT / "results" / "WRB-001" / "runs.csv"
DEFAULT_OUTPUT_DIR = ROOT / "results" / "WRB-001" / "figures"
SHORT_LABELS = {
    "constant_reference": "W0 Constant",
    "diversified_stochastic": "W1 Diversified",
    "bursty_benign": "W2 Bursty",
    "queue_driven_benign": "W3 Queue",
    "power_aware_benign": "W4 Power-aware",
    "phase_shaped_candidate": "W5 Phase-shaped",
}


def _optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def read_runs(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    numeric_fields = (
        "seed",
        "relative_energy_error",
        "peak_node_temperature_K",
        "delta_peak_temperature_vs_reference_K",
        "r_benign",
        "r_benign_vs_diversified",
    )
    parsed: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = dict(row)
        for field in numeric_fields:
            item[field] = _optional_float(row[field])
        item["valid_run"] = row["valid_run"].lower() == "true"
        parsed.append(item)
    return parsed


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        metadata={"Software": "OCTM WRB-001 deterministic plotter"},
    )
    plt.close(fig)


def plot_delta_distribution(rows: list[dict[str, object]], output_dir: Path) -> Path:
    groups = [
        [
            float(row["delta_peak_temperature_vs_reference_K"])
            for row in rows
            if row["valid_run"]
            and row["workload_id"] == workload_id
            and row["delta_peak_temperature_vs_reference_K"] is not None
        ]
        for workload_id in WORKLOAD_IDS
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.boxplot(groups, tick_labels=[SHORT_LABELS[item] for item in WORKLOAD_IDS], showfliers=False)
    jitter_rng = np.random.default_rng(20260808)
    for index, values in enumerate(groups, start=1):
        x = index + jitter_rng.uniform(-0.10, 0.10, size=len(values))
        ax.scatter(x, values, s=10, alpha=0.35, color="#2c6e91", edgecolors="none")
    ax.axhline(0.0, color="#333333", linewidth=0.8)
    ax.set_ylabel("Paired peak-temperature delta vs W0 (K)")
    ax.set_title("WRB-001 workload timing sensitivity across paired seeds")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    path = output_dir / "delta_peak_temperature_by_workload.png"
    _save(fig, path)
    return path


def plot_peak_distribution(rows: list[dict[str, object]], output_dir: Path) -> Path:
    groups = [
        [
            float(row["peak_node_temperature_K"]) - 273.15
            for row in rows
            if row["valid_run"]
            and row["workload_id"] == workload_id
            and row["peak_node_temperature_K"] is not None
        ]
        for workload_id in WORKLOAD_IDS
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.boxplot(
        groups,
        tick_labels=[SHORT_LABELS[item] for item in WORKLOAD_IDS],
        showfliers=False,
    )
    jitter_rng = np.random.default_rng(20260809)
    for index, values in enumerate(groups, start=1):
        x = index + jitter_rng.uniform(-0.10, 0.10, size=len(values))
        ax.scatter(x, values, s=10, alpha=0.35, color="#4c956c", edgecolors="none")
    for label in ax.get_xticklabels():
        label.set_rotation(20)
        label.set_horizontalalignment("right")
    ax.set_ylabel("Peak node temperature (deg C)")
    ax.set_title("WRB-001 peak-temperature distributions")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    path = output_dir / "peak_node_temperature_by_workload.png"
    _save(fig, path)
    return path


def plot_energy_quality(rows: list[dict[str, object]], output_dir: Path) -> Path:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["relative_energy_error"] is not None:
            grouped[str(row["workload_id"])].append(abs(float(row["relative_energy_error"])) * 100.0)
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    for index, workload_id in enumerate(WORKLOAD_IDS):
        values = np.asarray(grouped[workload_id], dtype=float)
        floor_values = np.maximum(values, 1e-14)
        ax.scatter(
            np.full(values.size, index) + np.linspace(-0.12, 0.12, max(values.size, 1))[: values.size],
            floor_values,
            s=11,
            alpha=0.5,
        )
    ax.axhline(0.1, color="#a23e48", linestyle="--", linewidth=1.2, label="0.1% acceptance limit")
    ax.axhline(0.01, color="#d18b47", linestyle=":", linewidth=1.2, label="0.01% preferred")
    ax.set_yscale("log")
    ax.set_xticks(range(len(WORKLOAD_IDS)), [SHORT_LABELS[item] for item in WORKLOAD_IDS], rotation=20)
    ax.set_ylabel("Absolute sampled-energy error (%)")
    ax.set_title("WRB-001 energy-matching quality")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2, which="both")
    fig.tight_layout()
    path = output_dir / "energy_match_quality.png"
    _save(fig, path)
    return path


def plot_ratio_distribution(rows: list[dict[str, object]], output_dir: Path) -> Path:
    primary = [
        float(row["r_benign"])
        for row in rows
        if row["workload_id"] == "power_aware_benign" and row["r_benign"] is not None
    ]
    historical = [
        float(row["r_benign_vs_diversified"])
        for row in rows
        if row["workload_id"] == "power_aware_benign"
        and row["r_benign_vs_diversified"] is not None
    ]
    combined = np.asarray(primary + historical, dtype=float)
    if combined.size == 0:
        raise ValueError("no valid benign/shaped ratios are available for plotting")
    low, high = float(np.min(combined)), float(np.max(combined))
    padding = max(0.01, (high - low) * 0.08)
    bins = np.linspace(low - padding, high + padding, 24)
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    ax.hist(primary, bins=bins, alpha=0.60, label="W4/W5 deltas vs W0", color="#2c6e91")
    ax.hist(historical, bins=bins, alpha=0.45, label="W4/W5 deltas vs W1", color="#d18b47")
    ax.set_xlabel("Per-seed benign/shaped ratio")
    ax.set_ylabel("Seed count")
    ax.set_title("WRB-001 benign/shaped ratio distribution")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    path = output_dir / "benign_shaped_ratio_distribution.png"
    _save(fig, path)
    return path


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Generate WRB-001 figures from runs.csv")
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = read_runs(args.runs)
    paths = [
        plot_delta_distribution(rows, args.output_dir),
        plot_peak_distribution(rows, args.output_dir),
        plot_energy_quality(rows, args.output_dir),
        plot_ratio_distribution(rows, args.output_dir),
    ]
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
