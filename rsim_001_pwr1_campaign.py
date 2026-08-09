"""RSIM-001-PWR1 reserve-aware admission challenge orchestration."""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from statistics import median
from typing import Any, Iterable, Sequence

import numpy as np

from rsim_001_campaign import (
    ROOT,
    canonical_grid,
    e0_mode_a_regression,
    generate_seed_workloads,
)
from src.octm.adapters.v044 import canonical_source_hashes
from src.octm.rsim.cosim import CLOSED_LOOP, POWER_CONSTRAINED, simulate
from src.octm.rsim.environment import (
    ENVIRONMENT_IDS,
    E1_REPRESENTATIVE_ANALYTIC_LEO,
    generate_environment,
)
from src.octm.rsim.fdir import CONTROLLER_LABEL, FDIRParameters
from src.octm.rsim.metrics import add_paired_deltas, run_metrics
from src.octm.rsim.power import DEFAULT_POWER_PARAMETERS, SYSTEM_POWER_DEFICIT
from src.octm.rsim.reserve import (
    A0_R_ARCHITECTURE_ID,
    ESSENTIAL_RESERVE_FEASIBLE,
    build_reserve_profile,
    time_until_next_generation,
)
from wrb_001_workloads import WORKLOAD_IDS


CAMPAIGN_ID = "RSIM-001-PWR1"
A0_M_LABEL = "A0-M_MYOPIC_ADMISSION"
OUTPUT_DIR = ROOT / "results" / CAMPAIGN_ID
A0_M_RUNS_PATH = ROOT / "results" / "RSIM-001-smoke" / "runs.jsonl"
MODES = (POWER_CONSTRAINED, CLOSED_LOOP)


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite value cannot enter an RSIM-001-PWR1 artifact")
    return value


def reserve_environment_inputs(environment_id: str, horizon: int = 43_200):
    base_time = np.arange(horizon, dtype=np.float64)
    environment = generate_environment(environment_id, base_time)
    padding = int(math.ceil(environment.period_s)) + 2
    extended_time = np.arange(horizon + padding, dtype=np.float64)
    extended = generate_environment(environment_id, extended_time)
    lookahead = time_until_next_generation(
        extended.solar_generation_W, horizon_length=horizon, dt_s=1.0
    )
    profile = build_reserve_profile(lookahead)
    if profile.architecture_condition != ESSENTIAL_RESERVE_FEASIBLE:
        raise RuntimeError(profile.architecture_condition)
    return environment, profile


def _sum_energy(values: np.ndarray, mask: np.ndarray) -> float:
    return float(math.fsum(float(value) for value in values[mask]))


def _make_row(
    seed: int,
    workload: Any,
    environment: Any,
    mode: str,
    result: Any,
    mask: np.ndarray,
) -> dict[str, Any]:
    metrics = run_metrics(
        result, environment, mask, dt_s=1.0,
        power_params=DEFAULT_POWER_PARAMETERS,
    )
    assert result.reserve_profile is not None
    assert result.reserve_active is not None
    assert result.reserve_limited_compute is not None
    assert result.reserve_denied_compute_W is not None
    assert result.instantaneous_denied_compute_W is not None
    assert result.fdir_denied_compute_W is not None
    instantaneous_J = _sum_energy(result.instantaneous_denied_compute_W, mask)
    reserve_J = _sum_energy(result.reserve_denied_compute_W, mask)
    fdir_J = _sum_energy(result.fdir_denied_compute_W, mask)
    attributed_total_J = instantaneous_J + reserve_J + fdir_J
    if not math.isclose(
        attributed_total_J, metrics["compute_energy_denied_J"],
        abs_tol=1e-6, rel_tol=0.0,
    ):
        raise RuntimeError("compute-denial attribution does not close")
    warnings: list[str] = []
    if environment.environment_id == E1_REPRESENTATIVE_ANALYTIC_LEO:
        warnings.extend([
            "E1 is a fixed-wall-clock representative environment challenge, not a periodic/steady-state result",
            "E1 radiator incidence and Earth-view factors are ASSUMED_EXPLORATORY",
            "E1 albedo is a bounded analytic approximation, not a flight environment model",
        ])
    if result.invariant_results["warmup_power_deficit_flag"]:
        warnings.append("warmup mandatory-housekeeping power deficit observed")
    row: dict[str, Any] = {
        "record_type": "run",
        "schema_version": "rsim-001-pwr1.1",
        "campaign_id": CAMPAIGN_ID,
        "architecture_id": A0_R_ARCHITECTURE_ID,
        "architecture_condition": result.reserve_profile.architecture_condition,
        "architecture_comparison_baseline": A0_M_LABEL,
        "scientific_scope": (
            "non-authoritative reserve-aware admission challenge; unchanged A0 hardware; "
            "not attack or spacecraft validation"
        ),
        "git_commit": _git_commit(),
        "seed": seed,
        "workload_id": workload.workload_id,
        "workload_label": workload.label,
        "environment_id": environment.environment_id,
        "mode": mode,
        "dt_s": 1.0,
        "simulation_duration_s": 43_200.0,
        "measurement_start_s": 10_800.0,
        "measurement_end_s_exclusive": 43_200.0,
        "requested_workload_trace_sha256": workload.trace_sha256,
        "physical_realization_sha256": environment.physical_realization_sha256,
        "fdir_controller": CONTROLLER_LABEL if mode == CLOSED_LOOP else None,
        "fdir_latency_s": 30.0 if mode == CLOSED_LOOP else None,
        "valid_run": bool(workload.valid_run and result.valid_run),
        "invalid_reason": workload.invalid_reason or result.invalid_reason,
        "warmup_power_deficit_flag": bool(
            result.invariant_results["warmup_power_deficit_flag"]
        ),
        "compute_denied_due_instantaneous_power_J": instantaneous_J,
        "compute_denied_due_battery_reserve_J": reserve_J,
        "compute_denied_due_fdir_J": fdir_J,
        "electrical_unserved_compute_energy_J": metrics["compute_energy_denied_J"],
        # Controller-status fields are full-trace diagnostic maxima/booleans;
        # the aggregation basis is serialized explicitly to prevent ambiguity.
        "essential_reserve_J": float(np.max(result.reserve_profile.essential_reserve_J)),
        "protected_battery_SOC_equivalent": float(np.max(
            result.reserve_profile.protected_battery_SOC_equivalent
        )),
        "time_until_next_generation_s": float(np.max(
            result.reserve_profile.time_until_next_generation_s
        )),
        "reserve_active": bool(np.any(result.reserve_active)),
        "reserve_limited_compute": bool(np.any(result.reserve_limited_compute)),
        "reserve_denied_compute_W": float(np.max(result.reserve_denied_compute_W)),
        "reserve_active_time_s": float(np.count_nonzero(result.reserve_active)),
        "reserve_limited_compute_time_s": float(np.count_nonzero(
            result.reserve_limited_compute
        )),
        "controller_status_aggregation": {
            "essential_reserve_J": "maximum_over_full_trace",
            "protected_battery_SOC_equivalent": "maximum_over_full_trace",
            "time_until_next_generation_s": "maximum_over_full_trace",
            "reserve_active": "any_over_full_trace",
            "reserve_limited_compute": "any_over_full_trace",
            "reserve_denied_compute_W": "maximum_over_full_trace",
        },
        "invariants": result.invariant_results,
        "assumption_dominance_warnings": warnings,
    }
    row.update(metrics)
    return row


def _median(values: Iterable[float | int | None]) -> float | None:
    finite = [float(value) for value in values if value is not None]
    return float(median(finite)) if finite else None


def _aggregate(rows: list[dict[str, Any]], architecture: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["environment_id"], row["mode"], row["workload_id"])].append(row)
    output: list[dict[str, Any]] = []
    for (environment_id, mode, workload_id), members in sorted(groups.items()):
        output.append({
            "architecture": architecture,
            "environment_id": environment_id,
            "mode": mode,
            "workload_id": workload_id,
            "run_count": len(members),
            "valid_run_count": sum(bool(row["valid_run"]) for row in members),
            "system_power_deficit_run_count": sum(
                row["invalid_reason"] == SYSTEM_POWER_DEFICIT for row in members
            ),
            "executed_compute_energy_J_median": _median(
                row["executed_compute_energy_J"] for row in members
            ),
            "compute_energy_denied_J_median": _median(
                row["compute_energy_denied_J"] for row in members
            ),
            "compute_denied_due_battery_reserve_J_median": _median(
                row.get("compute_denied_due_battery_reserve_J") for row in members
            ),
            "compute_denied_due_fdir_J_median": _median(
                row.get("compute_denied_due_fdir_J") for row in members
            ),
            "minimum_battery_SOC_median": _median(
                row["minimum_battery_SOC"] for row in members
            ),
            "final_battery_SOC_median": _median(
                row["final_battery_SOC"] for row in members
            ),
            "peak_node_temperature_K_median": _median(
                row["peak_node_temperature_K"] for row in members
            ),
            "delta_peak_temperature_vs_W0_K_median": _median(
                row["delta_peak_temperature_vs_reference_K"] for row in members
            ),
            "thermal_throttle_event_count_median": _median(
                row["thermal_throttle_event_count"] for row in members
            ),
            "time_thermally_throttled_s_median": _median(
                row["time_thermally_throttled_s"] for row in members
            ),
        })
    return output


def load_frozen_a0m_rows() -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in A0_M_RUNS_PATH.read_text(encoding="utf-8").splitlines()
    ]
    return [row for row in rows if row["mode"] in MODES]


def build_comparison(
    a0m_rows: list[dict[str, Any]],
    a0r_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    old = _aggregate(a0m_rows, A0_M_LABEL)
    new = _aggregate(a0r_rows, A0_R_ARCHITECTURE_ID)
    old_index = {
        (row["environment_id"], row["mode"], row["workload_id"]): row
        for row in old
    }
    new_index = {
        (row["environment_id"], row["mode"], row["workload_id"]): row
        for row in new
    }
    comparisons = []
    for key in sorted(old_index):
        left = old_index[key]
        right = new_index[key]
        comparisons.append({
            "environment_id": key[0],
            "mode": key[1],
            "workload_id": key[2],
            "A0M": left,
            "A0R": right,
            "A0R_minus_A0M": {
                name: right[name] - left[name]
                for name in (
                    "valid_run_count", "system_power_deficit_run_count",
                    "executed_compute_energy_J_median", "compute_energy_denied_J_median",
                    "minimum_battery_SOC_median", "final_battery_SOC_median",
                    "peak_node_temperature_K_median",
                    "delta_peak_temperature_vs_W0_K_median",
                    "thermal_throttle_event_count_median",
                    "time_thermally_throttled_s_median",
                )
                if left[name] is not None and right[name] is not None
            },
            "attribution_note": (
                "A0-M denial causes were not separately serialized and are not reinterpreted; "
                "A0-R reserve and FDIR attribution is an additive admission waterfall"
            ),
        })
    return {
        "artifact_type": "rsim_001_pwr1_a0m_a0r_comparison",
        "schema_version": "rsim-001-pwr1.1",
        "campaign_id": CAMPAIGN_ID,
        "frozen_A0M_runs_path": "results/RSIM-001-smoke/runs.jsonl",
        "frozen_A0M_runs_sha256": _sha256(A0_M_RUNS_PATH),
        "A0M_run_count": len(a0m_rows),
        "A0R_run_count": len(a0r_rows),
        "A0M_system_power_deficit_run_count": sum(
            row["invalid_reason"] == SYSTEM_POWER_DEFICIT for row in a0m_rows
        ),
        "A0R_system_power_deficit_run_count": sum(
            row["invalid_reason"] == SYSTEM_POWER_DEFICIT for row in a0r_rows
        ),
        "comparisons": comparisons,
        "classification": None,
    }


def run_pwr1(
    *, seeds: Sequence[int] = tuple(range(10)),
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _, mask, _, _ = canonical_grid()
    environment_inputs = {
        environment_id: reserve_environment_inputs(environment_id)
        for environment_id in ENVIRONMENT_IDS
    }
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for seed in seeds:
        workloads = generate_seed_workloads(int(seed))
        for workload in workloads.values():
            for environment_id in ENVIRONMENT_IDS:
                environment, reserve_profile = environment_inputs[environment_id]
                for mode in MODES:
                    result = simulate(
                        workload.power_W,
                        environment,
                        mode=mode,
                        dt_s=1.0,
                        fdir_params=FDIRParameters(latency_s=30.0),
                        reserve_time_until_next_generation_s=(
                            reserve_profile.time_until_next_generation_s
                        ),
                    )
                    rows.append(_make_row(
                        int(seed), workload, environment, mode, result, mask
                    ))
    add_paired_deltas(rows)
    elapsed_s = time.perf_counter() - started
    frozen_a0m = load_frozen_a0m_rows()
    comparison = build_comparison(frozen_a0m, rows)
    invariant_names = sorted({name for row in rows for name in row["invariants"]})
    invariant_results = {
        name: {
            "pass_count": sum(bool(row["invariants"][name]) for row in rows),
            "evaluated_run_count": len(rows),
            "status": (
                "DIAGNOSTIC" if name == "warmup_power_deficit_flag"
                else "PASS" if all(bool(row["invariants"][name]) for row in rows)
                else "FAIL"
            ),
        }
        for name in invariant_names
    }
    aggregates = _aggregate(rows, A0_R_ARCHITECTURE_ID)
    summary = {
        "artifact_type": "rsim_001_pwr1_summary",
        "schema_version": "rsim-001-pwr1.1",
        "campaign_id": CAMPAIGN_ID,
        "authoritative_scientific_result": False,
        "attack_validation": False,
        "spacecraft_validation": False,
        "automatic_classification": None,
        "git_commit": _git_commit(),
        "run_count": len(rows),
        "valid_run_count": sum(bool(row["valid_run"]) for row in rows),
        "invalid_run_count": sum(not bool(row["valid_run"]) for row in rows),
        "system_power_deficit_run_count": comparison["A0R_system_power_deficit_run_count"],
        "warmup_power_deficit_run_count": sum(
            bool(row["warmup_power_deficit_flag"]) for row in rows
        ),
        "seeds": list(seeds),
        "workloads": list(WORKLOAD_IDS),
        "environments": list(ENVIRONMENT_IDS),
        "modes": list(MODES),
        "runtime_s": elapsed_s,
        "architecture_condition": ESSENTIAL_RESERVE_FEASIBLE,
        "hardware_change_from_A0M": False,
        "changed_architectural_dimension": "compute admission with future housekeeping reserve",
        "aggregate_table": aggregates,
        "interpretation_rule": (
            "temperature changes must be reported with total and attributed compute denial; "
            "no SAFE/VULNERABLE/attack-success classification"
        ),
    }
    invariants = {
        "artifact_type": "rsim_001_pwr1_invariants",
        "schema_version": "rsim-001-pwr1.1",
        "campaign_id": CAMPAIGN_ID,
        "run_count": len(rows),
        "results": invariant_results,
        "all_required_invariants_pass": all(
            item["status"] == "PASS"
            for name, item in invariant_results.items()
            if name != "warmup_power_deficit_flag"
        ),
        "maximum_absolute_cumulative_electrical_residual_J": max(
            float(row["maximum_absolute_cumulative_electrical_residual_J"])
            for row in rows
        ),
    }
    return tuple(map(_json_safe, (rows, summary, comparison, invariants)))  # type: ignore[return-value]


def write_outputs(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    comparison: dict[str, Any],
    invariants: dict[str, Any],
    *,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": output_dir / "runs.jsonl",
        "csv": output_dir / "runs.csv",
        "summary": output_dir / "summary.json",
        "comparison": output_dir / "comparison_A0M_A0R.json",
        "invariants": output_dir / "invariants.json",
    }
    paths["jsonl"].write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    ), encoding="utf-8", newline="\n")
    scalar_fields = [key for key, value in rows[0].items() if not isinstance(value, (dict, list))]
    complex_fields = [key for key, value in rows[0].items() if isinstance(value, (dict, list))]
    fields = scalar_fields + complex_fields
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: (
                json.dumps(row[key], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if isinstance(row[key], (dict, list)) else row[key]
            )
            for key in fields
        })
    paths["csv"].write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
    for key, payload in (
        ("summary", summary), ("comparison", comparison), ("invariants", invariants)
    ):
        paths[key].write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
    return {path.name: _sha256(path) for path in paths.values()}


def hard_gates() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rsim-pwr1-baseline-") as directory:
        output = Path(directory) / "baseline.json"
        completed = subprocess.run(
            [sys.executable, "verify_baseline_v044.py", "--output", str(output)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0 or not output.exists():
            raise RuntimeError(
                f"read-only canonical baseline gate failed:\n{completed.stdout}\n{completed.stderr}"
            )
        report = json.loads(output.read_text(encoding="utf-8"))
    manifest = report["byte_level_release_artifact_verification"]
    science = report["scientific_numerical_reproduction"]["comparison"]
    baseline = {
        "manifest_status": manifest["status"],
        "manifest_entries_passed": manifest["available_entry_count"],
        "manifest_entry_count": manifest["manifest_entry_count"],
        "scientific_status": report["scientific_numerical_reproduction"]["status"],
        "scientific_values_matched": science["matched_numeric_value_count"],
        "scientific_values_total": science["numeric_value_count"],
        "max_scientific_difference": science["max_absolute_numeric_difference"],
        "canonical_source_sha256": canonical_source_hashes(),
    }
    if not (
        baseline["manifest_status"] == "PASS"
        and baseline["manifest_entries_passed"] == baseline["manifest_entry_count"] == 15
        and baseline["scientific_status"] == "PASS"
        and baseline["scientific_values_matched"] == baseline["scientific_values_total"] == 364
        and baseline["max_scientific_difference"] == 0.0
    ):
        raise RuntimeError(f"canonical baseline hard gate failed: {baseline}")
    return {
        "baseline": baseline,
        "e0_mode_a_wrb_regression": e0_mode_a_regression(),
    }


__all__ = [
    "CAMPAIGN_ID", "OUTPUT_DIR", "build_comparison", "hard_gates",
    "reserve_environment_inputs", "run_pwr1", "write_outputs",
]
