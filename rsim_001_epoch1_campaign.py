"""RSIM-001-EPOCH1 relative orbital epoch robustness challenge."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable, Sequence

import numpy as np

from rsim_001_campaign import ROOT, canonical_grid, generate_seed_workloads
from rsim_001_pwr1_campaign import hard_gates
from src.octm.rsim.cosim import CLOSED_LOOP, POWER_CONSTRAINED, simulate
from src.octm.rsim.environment import (
    DEFAULT_E1,
    E0_CANONICAL,
    E1_REPRESENTATIVE_ANALYTIC_LEO,
    generate_environment,
)
from src.octm.rsim.fdir import CONTROLLER_LABEL, FDIRParameters
from src.octm.rsim.metrics import run_metrics
from src.octm.rsim.power import DEFAULT_POWER_PARAMETERS, SYSTEM_POWER_DEFICIT
from src.octm.rsim.reserve import (
    A0_R_ARCHITECTURE_ID,
    ESSENTIAL_RESERVE_FEASIBLE,
    build_reserve_profile,
    time_until_next_generation,
)
from wrb_001_workloads import WORKLOAD_IDS


CAMPAIGN_ID = "RSIM-001-EPOCH1"
OUTPUT_DIR = ROOT / "results" / CAMPAIGN_ID
PWR1_RUNS_PATH = ROOT / "results" / "RSIM-001-PWR1" / "runs.jsonl"
MODES = (POWER_CONSTRAINED, CLOSED_LOOP)
PHASE_OFFSETS = tuple(float(value) for value in np.arange(8) / 8.0)
PERCENTILES = (5, 25, 75, 95)


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


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
        raise ValueError("non-finite value cannot enter an EPOCH1 artifact")
    return value


def epoch_environment_inputs(phase_offset_fraction: float, horizon: int = 43_200):
    time = np.arange(horizon, dtype=np.float64)
    environment = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO,
        time,
        phase_offset_fraction=phase_offset_fraction,
    )
    padding = int(math.ceil(environment.period_s)) + 2
    extended = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO,
        np.arange(horizon + padding, dtype=np.float64),
        phase_offset_fraction=phase_offset_fraction,
    )
    lookahead = time_until_next_generation(
        extended.solar_generation_W, horizon_length=horizon, dt_s=1.0
    )
    reserve = build_reserve_profile(lookahead)
    if reserve.architecture_condition != ESSENTIAL_RESERVE_FEASIBLE:
        raise RuntimeError(reserve.architecture_condition)
    return environment, reserve


def _sum_energy(values: np.ndarray, mask: np.ndarray) -> float:
    return float(math.fsum(float(value) for value in values[mask]))


def _make_row(
    *,
    commit: str | None,
    seed: int,
    workload: Any,
    environment: Any,
    reserve_profile: Any,
    phase_offset_fraction: float,
    mode: str,
    result: Any,
    mask: np.ndarray,
) -> dict[str, Any]:
    metrics = run_metrics(
        result, environment, mask, dt_s=1.0,
        power_params=DEFAULT_POWER_PARAMETERS,
    )
    assert result.reserve_denied_compute_W is not None
    assert result.instantaneous_denied_compute_W is not None
    assert result.fdir_denied_compute_W is not None
    assert result.reserve_active is not None
    assert result.reserve_limited_compute is not None
    instantaneous_J = _sum_energy(result.instantaneous_denied_compute_W, mask)
    reserve_J = _sum_energy(result.reserve_denied_compute_W, mask)
    fdir_J = _sum_energy(result.fdir_denied_compute_W, mask)
    if not math.isclose(
        instantaneous_J + reserve_J + fdir_J,
        metrics["compute_energy_denied_J"],
        abs_tol=1e-6, rel_tol=0.0,
    ):
        raise RuntimeError("compute-denial attribution does not close")
    warnings = [
        "E1 is a fixed-wall-clock representative environment challenge, not a periodic/steady-state result",
        "E1 radiator incidence and Earth-view factors are ASSUMED_EXPLORATORY",
        "E1 albedo is a bounded analytic approximation, not a flight environment model",
        "epoch offsets are relative workload/environment alignments, not different spacecraft",
    ]
    if result.invariant_results["warmup_power_deficit_flag"]:
        warnings.append("warmup mandatory-housekeeping power deficit observed")
    row: dict[str, Any] = {
        "record_type": "run",
        "schema_version": "rsim-001-epoch1.1",
        "campaign_id": CAMPAIGN_ID,
        "architecture_id": A0_R_ARCHITECTURE_ID,
        "architecture_condition": reserve_profile.architecture_condition,
        "scientific_scope": (
            "non-authoritative relative E1 epoch sensitivity; unchanged A0-R hardware/controller; "
            "not attack, mission, or spacecraft validation"
        ),
        "git_commit": commit,
        "seed": seed,
        "workload_id": workload.workload_id,
        "workload_label": workload.label,
        "environment_id": environment.environment_id,
        "environment_phase_offset_fraction": phase_offset_fraction,
        "environment_phase_offset_deg": phase_offset_fraction * 360.0,
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
        "essential_reserve_J": float(np.max(reserve_profile.essential_reserve_J)),
        "protected_battery_SOC_equivalent": float(np.max(
            reserve_profile.protected_battery_SOC_equivalent
        )),
        "time_until_next_generation_s": float(np.max(
            reserve_profile.time_until_next_generation_s
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


def _rows_for_seed(seed_and_commit: tuple[int, str | None]) -> list[dict[str, Any]]:
    seed, commit = seed_and_commit
    _, mask, _, _ = canonical_grid()
    workloads = generate_seed_workloads(seed)
    environments = {
        offset: epoch_environment_inputs(offset) for offset in PHASE_OFFSETS
    }
    rows: list[dict[str, Any]] = []
    for workload in workloads.values():
        for offset in PHASE_OFFSETS:
            environment, reserve = environments[offset]
            for mode in MODES:
                result = simulate(
                    workload.power_W,
                    environment,
                    mode=mode,
                    dt_s=1.0,
                    fdir_params=FDIRParameters(latency_s=30.0),
                    reserve_time_until_next_generation_s=(
                        reserve.time_until_next_generation_s
                    ),
                )
                rows.append(_make_row(
                    commit=commit,
                    seed=seed,
                    workload=workload,
                    environment=environment,
                    reserve_profile=reserve,
                    phase_offset_fraction=offset,
                    mode=mode,
                    result=result,
                    mask=mask,
                ))
    return rows


def add_epoch_paired_deltas(rows: list[dict[str, Any]]) -> None:
    references = {
        (row["seed"], row["environment_phase_offset_fraction"], row["mode"]): row
        for row in rows if row["workload_id"] == "constant_reference"
    }
    for row in rows:
        reference = references[(
            row["seed"], row["environment_phase_offset_fraction"], row["mode"]
        )]
        row["delta_peak_temperature_vs_reference_K"] = (
            row["peak_node_temperature_K"] - reference["peak_node_temperature_K"]
        )


def _median(values: Iterable[float | int]) -> float:
    array = np.asarray(tuple(values), dtype=np.float64)
    return float(np.median(array))


def _distribution(values: Iterable[float]) -> dict[str, Any]:
    array = np.asarray(tuple(values), dtype=np.float64)
    if array.size == 0 or np.any(~np.isfinite(array)):
        raise ValueError("distribution input must be non-empty and finite")
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "std": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "p05": float(np.percentile(array, 5)),
        "p25": float(np.percentile(array, 25)),
        "p75": float(np.percentile(array, 75)),
        "p95": float(np.percentile(array, 95)),
        "std_definition": "sample standard deviation (ddof=1)",
        "percentile_method": "NumPy linear",
    }


def aggregate_by_epoch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(
            row["workload_id"], row["mode"],
            row["environment_phase_offset_fraction"],
        )].append(row)
    output = []
    for (workload, mode, offset), members in sorted(groups.items()):
        output.append({
            "workload_id": workload,
            "mode": mode,
            "environment_phase_offset_fraction": offset,
            "environment_phase_offset_deg": offset * 360.0,
            "run_count": len(members),
            "valid_count": sum(bool(row["valid_run"]) for row in members),
            "SYSTEM_POWER_DEFICIT_count": sum(
                row["invalid_reason"] == SYSTEM_POWER_DEFICIT for row in members
            ),
            "executed_compute_energy_J_median": _median(
                row["executed_compute_energy_J"] for row in members
            ),
            "compute_energy_denied_fraction_median": _median(
                row["compute_energy_denied_fraction"] for row in members
            ),
            "reserve_denied_compute_J_median": _median(
                row["compute_denied_due_battery_reserve_J"] for row in members
            ),
            "FDIR_denied_compute_J_median": _median(
                row["compute_denied_due_fdir_J"] for row in members
            ),
            "minimum_SOC_median": _median(row["minimum_battery_SOC"] for row in members),
            "final_SOC_median": _median(row["final_battery_SOC"] for row in members),
            "peak_node_temperature_K_median": _median(
                row["peak_node_temperature_K"] for row in members
            ),
            "peak_radiator_temperature_K_median": _median(
                row["peak_radiator_temperature_K"] for row in members
            ),
            "delta_peak_temperature_vs_W0_K_median": _median(
                row["delta_peak_temperature_vs_reference_K"] for row in members
            ),
            "thermal_throttle_event_count_median": _median(
                row["thermal_throttle_event_count"] for row in members
            ),
            "thermal_throttle_activating_run_count": sum(
                row["thermal_throttle_event_count"] > 0 for row in members
            ),
            "time_thermally_throttled_s_median": _median(
                row["time_thermally_throttled_s"] for row in members
            ),
        })
    return output


def build_epoch_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["workload_id"], row["mode"])].append(row)
    distributions = []
    for (workload, mode), members in sorted(grouped.items()):
        ordered = sorted(
            members,
            key=lambda row: (
                row["delta_peak_temperature_vs_reference_K"],
                row["environment_phase_offset_fraction"], row["seed"],
            ),
        )
        epoch_medians = []
        for offset in PHASE_OFFSETS:
            epoch_members = [
                row for row in members
                if row["environment_phase_offset_fraction"] == offset
            ]
            epoch_medians.append({
                "environment_phase_offset_fraction": offset,
                "environment_phase_offset_deg": offset * 360.0,
                "median_delta_peak_temperature_vs_W0_K": _median(
                    row["delta_peak_temperature_vs_reference_K"]
                    for row in epoch_members
                ),
            })
        minimum_median = min(
            epoch_medians,
            key=lambda item: item["median_delta_peak_temperature_vs_W0_K"],
        )
        maximum_median = max(
            epoch_medians,
            key=lambda item: item["median_delta_peak_temperature_vs_W0_K"],
        )
        def case(row: dict[str, Any]) -> dict[str, Any]:
            return {
                "seed": row["seed"],
                "environment_phase_offset_fraction": row["environment_phase_offset_fraction"],
                "environment_phase_offset_deg": row["environment_phase_offset_deg"],
                "delta_peak_temperature_vs_W0_K": row["delta_peak_temperature_vs_reference_K"],
                "peak_node_temperature_K": row["peak_node_temperature_K"],
                "compute_energy_denied_J": row["compute_energy_denied_J"],
                "reserve_denied_compute_J": row["compute_denied_due_battery_reserve_J"],
                "FDIR_denied_compute_J": row["compute_denied_due_fdir_J"],
                "thermal_throttle_event_count": row["thermal_throttle_event_count"],
            }
        distributions.append({
            "workload_id": workload,
            "mode": mode,
            "paired_seed_epoch_count": len(members),
            "delta_peak_temperature_vs_W0_K": _distribution(
                row["delta_peak_temperature_vs_reference_K"] for row in members
            ),
            "compute_energy_denied_J": _distribution(
                row["compute_energy_denied_J"] for row in members
            ),
            "reserve_denied_compute_J": _distribution(
                row["compute_denied_due_battery_reserve_J"] for row in members
            ),
            "FDIR_denied_compute_J": _distribution(
                row["compute_denied_due_fdir_J"] for row in members
            ),
            "any_delta_peak_temperature_vs_W0_le_zero": any(
                row["delta_peak_temperature_vs_reference_K"] <= 0.0
                for row in members
            ),
            "electrically_valid_at_every_epoch": all(
                bool(row["valid_run"]) for row in members
            ),
            "minimum_case": case(ordered[0]),
            "maximum_case": case(ordered[-1]),
            "minimum_median_epoch": minimum_median,
            "maximum_median_epoch": maximum_median,
            "per_epoch_delta_medians": epoch_medians,
        })
    per_epoch = aggregate_by_epoch(rows)
    return {
        "artifact_type": "rsim_001_epoch1_epoch_response",
        "schema_version": "rsim-001-epoch1.1",
        "campaign_id": CAMPAIGN_ID,
        "pairing": "same seed/workload requested trace across all eight E1 epoch offsets",
        "classification": None,
        "distribution_basis": "all 10 seed x 8 epoch paired observations, separately by workload and mode",
        "distributions": distributions,
        "per_epoch": per_epoch,
    }


def _load_pwr1_e1_rows() -> list[dict[str, Any]]:
    return [
        row for row in (
            json.loads(line)
            for line in PWR1_RUNS_PATH.read_text(encoding="utf-8").splitlines()
        )
        if row["environment_id"] == E1_REPRESENTATIVE_ANALYTIC_LEO
    ]


def offset_zero_reproduction(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = {
        (row["seed"], row["workload_id"], row["mode"]): row
        for row in rows if row["environment_phase_offset_fraction"] == 0.0
    }
    observed_seeds = {key[0] for key in observed}
    expected = {
        (row["seed"], row["workload_id"], row["mode"]): row
        for row in _load_pwr1_e1_rows()
        if row["seed"] in observed_seeds
    }
    excluded = {
        "schema_version", "campaign_id", "scientific_scope", "git_commit",
        "assumption_dominance_warnings", "architecture_comparison_baseline",
    }
    mismatches: list[dict[str, Any]] = []
    compared_field_count = 0
    for key in sorted(expected):
        left, right = expected[key], observed[key]
        common = sorted((set(left) & set(right)) - excluded)
        compared_field_count += len(common)
        for field in common:
            if left[field] != right[field]:
                mismatches.append({"case": list(key), "field": field})
    result = {
        "status": "PASS" if not mismatches and set(observed) == set(expected) else "FAIL",
        "matched_run_count": len(expected) - len({tuple(item["case"]) for item in mismatches}),
        "run_count": len(expected),
        "compared_field_count": compared_field_count,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "frozen_PWR1_runs_path": "results/RSIM-001-PWR1/runs.jsonl",
        "frozen_PWR1_runs_sha256": _sha256(PWR1_RUNS_PATH),
    }
    if result["status"] != "PASS":
        raise RuntimeError(f"offset-zero PWR1 reproduction failed: {result}")
    return result


def _environment_preflight() -> dict[str, Any]:
    time = np.arange(43_200, dtype=np.float64)
    zero = generate_environment(E1_REPRESENTATIVE_ANALYTIC_LEO, time)
    unit = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO, time, phase_offset_fraction=1.0
    )
    offset_one_equal = all(np.array_equal(getattr(zero, name), getattr(unit, name)) for name in (
        "illumination", "direct_solar_W_m2", "albedo_W_m2", "earth_IR_W_m2",
        "absorbed_flux_W_m2", "solar_generation_W",
    )) and zero.physical_realization_sha256 == unit.physical_realization_sha256
    traces = [
        generate_environment(
            E1_REPRESENTATIVE_ANALYTIC_LEO, time,
            phase_offset_fraction=offset,
        ) for offset in PHASE_OFFSETS
    ]
    bounds_pass = all(
        np.all((trace.direct_solar_W_m2 >= 0.0) & (trace.direct_solar_W_m2 <= 68.05))
        and np.all((trace.albedo_W_m2 >= 0.0) & (trace.albedo_W_m2 <= 40.0134 + 1e-12))
        and np.all(trace.earth_IR_W_m2 == 99.45)
        and np.all((trace.absorbed_flux_W_m2 >= 99.45) & (trace.absorbed_flux_W_m2 <= 207.5134 + 1e-12))
        for trace in traces
    )
    eclipse_duration_pass = all(
        trace.metadata["eclipse_duration_s"] == DEFAULT_E1.eclipse_duration_s
        for trace in traces
    )
    e0_default = generate_environment(E0_CANONICAL, time)
    e0_repeat = generate_environment(E0_CANONICAL, time, phase_offset_fraction=0.0)
    e0_unchanged = (
        np.array_equal(e0_default.absorbed_flux_W_m2, e0_repeat.absorbed_flux_W_m2)
        and e0_default.physical_realization_sha256 == e0_repeat.physical_realization_sha256
    )
    result = {
        "offset_one_equivalent_to_zero": offset_one_equal,
        "eclipse_duration_per_orbit_invariant": eclipse_duration_pass,
        "environmental_component_bounds_unchanged": bounds_pass,
        "phase_offset_changes_E1_only": e0_unchanged,
        "declared_eclipse_duration_s": DEFAULT_E1.eclipse_duration_s,
    }
    if not all(value for key, value in result.items() if key != "declared_eclipse_duration_s"):
        raise RuntimeError(f"environment epoch preflight failed: {result}")
    return result


def _workload_pairing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[int, str], set[str]] = defaultdict(set)
    offsets: dict[tuple[int, str], set[float]] = defaultdict(set)
    for row in rows:
        key = (row["seed"], row["workload_id"])
        groups[key].add(row["requested_workload_trace_sha256"])
        offsets[key].add(row["environment_phase_offset_fraction"])
    expected_pair_count = len({row["seed"] for row in rows}) * len(WORKLOAD_IDS)
    passed = all(len(groups[key]) == 1 and offsets[key] == set(PHASE_OFFSETS) for key in groups)
    result = {
        "status": "PASS" if passed and len(groups) == expected_pair_count else "FAIL",
        "paired_seed_workload_count": len(groups),
        "expected_paired_seed_workload_count": expected_pair_count,
        "unique_hash_count_per_pair": sorted({len(value) for value in groups.values()}),
        "offset_count_per_pair": sorted({len(value) for value in offsets.values()}),
    }
    if result["status"] != "PASS":
        raise RuntimeError(f"workload pairing failed: {result}")
    return result


def run_epoch1(
    *,
    seeds: Sequence[int] = tuple(range(10)),
    workers: int = 1,
    commit: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    commit = _git_commit() if commit is None else commit
    arguments = [(int(seed), commit) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            chunks = list(executor.map(_rows_for_seed, arguments))
    else:
        chunks = [_rows_for_seed(argument) for argument in arguments]
    rows = [row for chunk in chunks for row in chunk]
    rows.sort(key=lambda row: (
        row["seed"], WORKLOAD_IDS.index(row["workload_id"]),
        row["environment_phase_offset_fraction"], MODES.index(row["mode"]),
    ))
    add_epoch_paired_deltas(rows)
    pairing = _workload_pairing(rows)
    zero_reproduction = offset_zero_reproduction(rows)
    environment_preflight = _environment_preflight()
    epoch_response = build_epoch_response(rows)
    aggregate = aggregate_by_epoch(rows)
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
    invariant_results.update({
        "phase_offset_changes_E1_only": {
            "status": "PASS" if environment_preflight["phase_offset_changes_E1_only"] else "FAIL"
        },
        "workload_traces_byte_identical_across_offsets": {
            "status": pairing["status"]
        },
        "offset_zero_exactly_reproduces_PWR1_E1": {
            "status": zero_reproduction["status"]
        },
        "offset_one_equivalent_to_zero": {
            "status": "PASS" if environment_preflight["offset_one_equivalent_to_zero"] else "FAIL"
        },
        "eclipse_duration_per_orbit_phase_invariant": {
            "status": "PASS" if environment_preflight["eclipse_duration_per_orbit_invariant"] else "FAIL"
        },
        "environmental_component_bounds_unchanged": {
            "status": "PASS" if environment_preflight["environmental_component_bounds_unchanged"] else "FAIL"
        },
        "deterministic_rerun_identical": {"status": "NOT_EVALUATED"},
    })
    summary = {
        "artifact_type": "rsim_001_epoch1_summary",
        "schema_version": "rsim-001-epoch1.1",
        "campaign_id": CAMPAIGN_ID,
        "authoritative_scientific_result": False,
        "attack_validation": False,
        "spacecraft_validation": False,
        "automatic_classification": None,
        "git_commit": commit,
        "run_count": len(rows),
        "valid_run_count": sum(bool(row["valid_run"]) for row in rows),
        "invalid_run_count": sum(not bool(row["valid_run"]) for row in rows),
        "system_power_deficit_run_count": sum(
            row["invalid_reason"] == SYSTEM_POWER_DEFICIT for row in rows
        ),
        "warmup_power_deficit_run_count": sum(
            bool(row["warmup_power_deficit_flag"]) for row in rows
        ),
        "seeds": list(seeds),
        "workloads": list(WORKLOAD_IDS),
        "environment": E1_REPRESENTATIVE_ANALYTIC_LEO,
        "environment_phase_offsets_fraction": list(PHASE_OFFSETS),
        "environment_phase_offsets_deg": [offset * 360.0 for offset in PHASE_OFFSETS],
        "modes": list(MODES),
        "architecture_id": A0_R_ARCHITECTURE_ID,
        "hardware_change_from_PWR1": False,
        "changed_independent_variable": "relative E1 environment phase offset",
        "aggregate_by_epoch": aggregate,
        "offset_zero_reproduction": zero_reproduction,
        "workload_pairing": pairing,
        "interpretation_rule": (
            "epoch-response distributions only; no materiality threshold or "
            "ROBUST/CONDITIONAL/SAFE/VULNERABLE classification"
        ),
    }
    invariants = {
        "artifact_type": "rsim_001_epoch1_invariants",
        "schema_version": "rsim-001-epoch1.1",
        "campaign_id": CAMPAIGN_ID,
        "run_count": len(rows),
        "results": invariant_results,
        "workload_pairing": pairing,
        "offset_zero_reproduction": zero_reproduction,
        "environment_preflight": environment_preflight,
        "all_required_invariants_pass": all(
            item["status"] in {"PASS", "NOT_EVALUATED"}
            for name, item in invariant_results.items()
            if name != "warmup_power_deficit_flag"
        ),
        "maximum_absolute_cumulative_electrical_residual_J": max(
            float(row["maximum_absolute_cumulative_electrical_residual_J"])
            for row in rows
        ),
    }
    return tuple(map(_json_safe, (rows, summary, epoch_response, invariants)))  # type: ignore[return-value]


def mark_deterministic_rerun_pass(invariants: dict[str, Any]) -> None:
    invariants["results"]["deterministic_rerun_identical"] = {"status": "PASS"}


def reproducibility_payload(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    epoch_response: dict[str, Any],
    invariants: dict[str, Any],
) -> bytes:
    invariant_copy = json.loads(json.dumps(invariants))
    invariant_copy["results"].pop("deterministic_rerun_identical", None)
    payload = [rows, summary, epoch_response, invariant_copy]
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def write_outputs(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    epoch_response: dict[str, Any],
    invariants: dict[str, Any],
    *,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": output_dir / "runs.jsonl",
        "csv": output_dir / "runs.csv",
        "summary": output_dir / "summary.json",
        "epoch_response": output_dir / "epoch_response.json",
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
            ) for key in fields
        })
    paths["csv"].write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
    for key, payload in (
        ("summary", summary), ("epoch_response", epoch_response),
        ("invariants", invariants),
    ):
        paths[key].write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
    return {path.name: _sha256(path) for path in paths.values()}


__all__ = [
    "CAMPAIGN_ID", "OUTPUT_DIR", "PHASE_OFFSETS", "add_epoch_paired_deltas",
    "aggregate_by_epoch", "build_epoch_response", "epoch_environment_inputs",
    "hard_gates", "mark_deterministic_rerun_pass", "offset_zero_reproduction",
    "reproducibility_payload", "run_epoch1", "write_outputs",
]
