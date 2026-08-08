"""Compare retained reconstructed WRB-001 results with canonical results."""

from __future__ import annotations

from argparse import ArgumentParser
import json
import math
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _difference(old: float | None, new: float | None) -> dict[str, float | None]:
    if old is None or new is None:
        return {"absolute": None, "relative": None}
    absolute = float(new) - float(old)
    relative = absolute / abs(float(old)) if float(old) != 0.0 else None
    return {"absolute": absolute, "relative": relative}


def _metric(summary: dict[str, Any], workload: str, name: str) -> dict[str, Any]:
    return summary["workload_summaries"][workload]["metrics"][name]


def compare(reconstructed_dir: Path, canonical_dir: Path) -> dict[str, Any]:
    old = json.loads((reconstructed_dir / "summary.json").read_text(encoding="utf-8"))
    new = json.loads((canonical_dir / "summary.json").read_text(encoding="utf-8"))
    workloads: dict[str, Any] = {}
    for workload in new["workload_order"]:
        old_group = old["workload_summaries"][workload]
        new_group = new["workload_summaries"][workload]
        old_delta = _metric(old, workload, "delta_peak_temperature_vs_reference_K")
        new_delta = _metric(new, workload, "delta_peak_temperature_vs_reference_K")
        old_peak = _metric(old, workload, "peak_node_temperature_K")
        new_peak = _metric(new, workload, "peak_node_temperature_K")
        old_median = old_delta.get("median")
        new_median = new_delta.get("median")
        workloads[workload] = {
            "reconstructed_median_delta_T_K": old_median,
            "canonical_median_delta_T_K": new_median,
            "delta_T_difference": _difference(old_median, new_median),
            "delta_T_distribution_K": {
                "reconstructed": {"p05": old_delta.get("p05"), "p95": old_delta.get("p95")},
                "canonical": {"p05": new_delta.get("p05"), "p95": new_delta.get("p95")},
            },
            "peak_temperature_distribution_K": {
                "reconstructed": {
                    "median": old_peak.get("median"), "p05": old_peak.get("p05"), "p95": old_peak.get("p95")
                },
                "canonical": {
                    "median": new_peak.get("median"), "p05": new_peak.get("p05"), "p95": new_peak.get("p95")
                },
            },
            "counts": {
                "reconstructed_valid": old_group["n_valid"],
                "reconstructed_invalid": old_group["n_invalid"],
                "canonical_valid": new_group["n_valid"],
                "canonical_invalid": new_group["n_invalid"],
            },
        }

    old_energy = [
        abs(float(line["relative_energy_error"]))
        for line in map(json.loads, (reconstructed_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines())
        if line["valid_run"]
    ]
    new_energy = [
        abs(float(line["relative_energy_error"]))
        for line in map(json.loads, (canonical_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines())
        if line["valid_run"]
    ]
    result = {
        "artifact_type": "wrb_001_migration_comparison",
        "reconstructed_results": str(reconstructed_dir.as_posix()),
        "canonical_results": str(canonical_dir.as_posix()),
        "workloads": workloads,
        "r_benign_distributions": {
            "reconstructed": old["benign_shaped_ratio_vs_constant_reference"],
            "canonical": new["benign_shaped_ratio_vs_constant_reference"],
            "versus_diversified_reconstructed": old["benign_shaped_ratio_vs_diversified"],
            "versus_diversified_canonical": new["benign_shaped_ratio_vs_diversified"],
        },
        "classification": {
            "reconstructed": old["classification"]["label"],
            "canonical": new["classification"]["label"],
            "changed": old["classification"]["label"] != new["classification"]["label"],
        },
        "energy_match_statistics": {
            "reconstructed_max_absolute_relative_error": max(old_energy, default=None),
            "canonical_max_absolute_relative_error": max(new_energy, default=None),
            "canonical_all_finite": all(math.isfinite(value) for value in new_energy),
        },
    }
    return result


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--reconstructed", type=Path, default=ROOT / "results" / "WRB-001-reconstructed")
    parser.add_argument("--canonical", type=Path, default=ROOT / "results" / "WRB-001")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results" / "WRB-001" / "migration_comparison.json"
    )
    args = parser.parse_args()
    result = compare(args.reconstructed, args.canonical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    os.replace(temporary, args.output)
    print(json.dumps(result["classification"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
