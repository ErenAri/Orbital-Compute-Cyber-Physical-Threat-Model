"""Orchestration and artifacts for the non-authoritative RSIM-001 smoke run."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence

import numpy as np

from src.octm.adapters.v044 import canonical_source_hashes
from src.octm.rsim.cosim import CLOSED_LOOP, POWER_CONSTRAINED, SIMULATION_MODES, THERMAL_ONLY, simulate
from src.octm.rsim.environment import (
    DEFAULT_E1, E0_CANONICAL, E1_REPRESENTATIVE_ANALYTIC_LEO,
    ENVIRONMENT_IDS, generate_environment,
)
from src.octm.rsim.fdir import CONTROLLER_LABEL, FDIRParameters
from src.octm.rsim.metrics import add_paired_deltas, aggregate_smoke, build_special_analyses, run_metrics
from src.octm.rsim.power import DEFAULT_POWER_PARAMETERS
from src.octm.rsim.thermal_bridge import benchmark_bridge, run_trace
from wrb_001_campaign import electrical_power_availability
from wrb_001_workloads import WORKLOAD_IDS, WorkloadConfig, generate_workloads


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "experiments" / "RSIM-001" / "config.json"
OUTPUT_DIR = ROOT / "results" / "RSIM-001-smoke"
CAMPAIGN_ID = "RSIM-001-smoke"
ARCHITECTURE_ID = "A0_CROSS_ENVIRONMENT_NOMINAL_FEASIBLE"


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
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value cannot enter an RSIM artifact")
        return value
    if isinstance(value, Path):
        try:
            return value.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("machine-local path cannot enter an RSIM artifact") from exc
    return value


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    dt_s = 1.0
    time_s = np.arange(43_200, dtype=np.float64) * dt_s
    mask = (time_s >= 10_800.0) & (time_s < 43_200.0)
    e0 = generate_environment(E0_CANONICAL, time_s)
    availability = electrical_power_availability(time_s, 5_400.0)
    return time_s, mask, e0.hot_mask, availability


def generate_seed_workloads(seed: int):
    time_s, mask, hot, availability = canonical_grid()
    workloads = generate_workloads(
        seed=seed, time_s=time_s, measurement_mask=mask, dt_s=1.0,
        hot_mask=hot, power_availability=availability, config=WorkloadConfig(),
    )
    if tuple(workloads) != WORKLOAD_IDS:
        raise RuntimeError("WRB workload ordering changed")
    return workloads


def verify_baseline_gate() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "verify_baseline_v044.py"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"canonical baseline verification failed:\n{result.stdout}\n{result.stderr}")
    report = json.loads((ROOT / "results" / "baseline_v044_verification.json").read_text(encoding="utf-8"))
    manifest = report["byte_level_release_artifact_verification"]
    science = report["scientific_numerical_reproduction"]["comparison"]
    gate = {
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
        gate["manifest_status"] == "PASS"
        and gate["manifest_entries_passed"] == gate["manifest_entry_count"] == 15
        and gate["scientific_status"] == "PASS"
        and gate["scientific_values_matched"] == gate["scientific_values_total"] == 364
        and gate["max_scientific_difference"] == 0.0
    ):
        raise RuntimeError(f"canonical baseline hard gate failed: {gate}")
    return gate


def e0_mode_a_regression(seeds: Sequence[int] = tuple(range(10))) -> dict[str, Any]:
    authoritative = {
        (int(row["seed"]), row["workload_id"]): row
        for row in (
            json.loads(line) for line in
            (ROOT / "results" / "WRB-001" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        )
        if int(row["seed"]) in seeds
    }
    time_s, mask, _, _ = canonical_grid()
    environment = generate_environment(E0_CANONICAL, time_s)
    peak_node_error = peak_radiator_error = 0.0
    observed: dict[tuple[int, str], tuple[float, float]] = {}
    for seed in seeds:
        for workload in generate_seed_workloads(int(seed)).values():
            result = run_trace(workload.power_W, environment.absorbed_flux_W_m2)
            node_peak = float(np.max(result.node_temperature_K[1:][mask]))
            radiator_peak = float(np.max(result.radiator_temperature_K[1:][mask]))
            expected = authoritative[(int(seed), workload.workload_id)]
            peak_node_error = max(peak_node_error, abs(node_peak - expected["peak_node_temperature_K"]))
            peak_radiator_error = max(
                peak_radiator_error, abs(radiator_peak - expected["peak_radiator_temperature_K"])
            )
            observed[(int(seed), workload.workload_id)] = (node_peak, radiator_peak)
    delta_error = 0.0
    for key, peaks in observed.items():
        seed, workload_id = key
        reference_peak = observed[(seed, "constant_reference")][0]
        expected_delta = authoritative[key]["delta_peak_temperature_vs_reference_K"]
        delta_error = max(delta_error, abs((peaks[0] - reference_peak) - expected_delta))
    status = "PASS" if max(peak_node_error, peak_radiator_error, delta_error) <= 1e-10 else "FAIL"
    result = {
        "status": status, "seed_count": len(seeds), "run_count": len(observed),
        "max_peak_node_temperature_error_K": peak_node_error,
        "max_peak_radiator_temperature_error_K": peak_radiator_error,
        "max_delta_peak_temperature_error_K": delta_error,
        "tolerance_K": 1e-10,
    }
    if status != "PASS":
        raise RuntimeError(f"E0 Mode-A WRB regression failed: {result}")
    return result


def _make_row(seed: int, workload: Any, environment: Any, mode: str, result: Any, mask: np.ndarray) -> dict[str, Any]:
    metrics = run_metrics(result, environment, mask, dt_s=1.0, power_params=DEFAULT_POWER_PARAMETERS)
    warnings: list[str] = []
    if environment.environment_id == E1_REPRESENTATIVE_ANALYTIC_LEO:
        warnings.extend([
            "E1 is a fixed-wall-clock representative environment challenge, not a periodic/steady-state result",
            "E1 radiator incidence and Earth-view factors are ASSUMED_EXPLORATORY",
            "E1 albedo is a bounded analytic approximation, not a flight environment model",
        ])
    if result.invariant_results.get("initialization_domination_flag"):
        warnings.append("battery initialization-domination diagnostic flagged")
    row: dict[str, Any] = {
        "record_type": "run", "schema_version": "rsim-001-smoke.1",
        "campaign_id": CAMPAIGN_ID, "architecture_id": ARCHITECTURE_ID,
        "scientific_scope": "non-authoritative representative architecture challenge; not attack or spacecraft validation",
        "model_version": "TSM-01-v0.4.4-canonical-with-RSIM-wrapper-v1",
        "git_commit": _git_commit(), "seed": seed,
        "workload_id": workload.workload_id, "workload_label": workload.label,
        "environment_id": environment.environment_id, "mode": mode, "dt_s": 1.0,
        "simulation_duration_s": 43_200.0,
        "environment_period_s": environment.period_s,
        "environment_orbits_elapsed": 43_200.0 / environment.period_s,
        "measurement_start_s": 10_800.0, "measurement_end_s_exclusive": 43_200.0,
        "measurement_window_basis": "canonical_wrb_wall_clock",
        "requested_workload_trace_sha256": workload.trace_sha256,
        "physical_realization_sha256": environment.physical_realization_sha256,
        "workload_allowed_inputs": list(workload.allowed_inputs),
        "fdir_controller": CONTROLLER_LABEL if mode == CLOSED_LOOP else None,
        "fdir_latency_s": 30.0 if mode == CLOSED_LOOP else None,
        "valid_run": bool(workload.valid_run and result.valid_run),
        "invalid_reason": workload.invalid_reason or result.invalid_reason,
        "invariants": result.invariant_results,
        "assumption_dominance_warnings": warnings,
    }
    row.update(metrics)
    return row


def run_smoke(*, seeds: Sequence[int] = tuple(range(10))) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    time_s, mask, _, _ = canonical_grid()
    environments = {eid: generate_environment(eid, time_s) for eid in ENVIRONMENT_IDS}
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for seed in seeds:
        workloads = generate_seed_workloads(int(seed))
        for workload in workloads.values():
            for environment_id in ENVIRONMENT_IDS:
                environment = environments[environment_id]
                for mode in SIMULATION_MODES:
                    result = simulate(
                        workload.power_W, environment, mode=mode, dt_s=1.0,
                        fdir_params=FDIRParameters(latency_s=30.0),
                    )
                    rows.append(_make_row(int(seed), workload, environment, mode, result, mask))
    add_paired_deltas(rows)
    elapsed_s = time.perf_counter() - started
    aggregates = aggregate_smoke(rows)
    invalid = [
        {"seed": r["seed"], "workload_id": r["workload_id"],
         "environment_id": r["environment_id"], "mode": r["mode"],
         "reason": r["invalid_reason"]}
        for r in rows if not r["valid_run"]
    ]
    invariant_names = sorted({name for row in rows for name in row["invariants"]})
    invariant_summary = {
        name: {
            "pass_count": sum(
                bool(r["invariants"][name]) for r in rows if name in r["invariants"]
            ),
            "evaluated_run_count": sum(name in r["invariants"] for r in rows),
            "status": (
                "DIAGNOSTIC" if name == "initialization_domination_flag"
                else ("PASS" if all(bool(r["invariants"].get(name)) for r in rows) else "FAIL")
            ),
        }
        for name in invariant_names
    }
    summary = {
        "artifact_type": "rsim_001_smoke_summary",
        "schema_version": "rsim-001-smoke.1", "campaign_id": CAMPAIGN_ID,
        "authoritative_scientific_result": False, "attack_validation": False,
        "spacecraft_validation": False, "automatic_classification": None,
        "git_commit": _git_commit(), "run_count": len(rows),
        "valid_run_count": len(rows) - len(invalid), "invalid_run_count": len(invalid),
        "seeds": list(seeds), "workloads": list(WORKLOAD_IDS),
        "environments": list(ENVIRONMENT_IDS), "modes": list(SIMULATION_MODES),
        "runtime_s": elapsed_s, "aggregate_table": aggregates,
        "aggregate_interpretation": "diagnostic all-run medians; invalid runs are retained and counted, not treated as authoritative valid statistics",
        "special_analyses": build_special_analyses(aggregates),
        "invalid_runs": invalid,
        "interpretation_rule": "temperature changes in constrained modes must be reported with executed-energy denial",
        "assumption_dominance_warning_count": sum(bool(r["assumption_dominance_warnings"]) for r in rows),
    }
    invariants = {
        "artifact_type": "rsim_001_smoke_invariants",
        "run_count": len(rows), "results": invariant_summary,
        "maximum_absolute_cumulative_electrical_residual_J": max(
            (float(r.get("maximum_absolute_cumulative_electrical_residual_J") or 0.0) for r in rows),
            default=0.0,
        ),
        "all_required_invariants_pass": all(
            item["status"] == "PASS" for name, item in invariant_summary.items()
            if name != "initialization_domination_flag"
        ),
    }
    return _json_safe(rows), _json_safe(summary), _json_safe(invariants)


def write_outputs(
    rows: list[dict[str, Any]], summary: dict[str, Any], invariants: dict[str, Any],
    benchmark: dict[str, Any], gates: dict[str, Any], *, output_dir: Path = OUTPUT_DIR,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "runs.jsonl"
    csv_path = output_dir / "runs.csv"
    summary_path = output_dir / "summary.json"
    invariants_path = output_dir / "invariants.json"
    benchmark_path = output_dir / "thermal_bridge_benchmark.json"
    gates_path = output_dir / "hard_gates.json"
    jsonl_path.write_text("".join(
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
            ) for key in fields
        })
    csv_path.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
    artifacts = {
        summary_path: summary, invariants_path: invariants,
        benchmark_path: benchmark, gates_path: gates,
    }
    for path, payload in artifacts.items():
        path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
    return {path.name: _sha256(path) for path in [jsonl_path, csv_path, *artifacts]}


__all__ = [
    "e0_mode_a_regression", "generate_seed_workloads", "run_smoke",
    "verify_baseline_gate", "write_outputs",
]
