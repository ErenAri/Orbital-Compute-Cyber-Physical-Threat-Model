"""RSIM-001 run metrics and non-authoritative smoke aggregation."""

from __future__ import annotations

from collections import defaultdict
import math
from statistics import median
from typing import Any, Iterable

import numpy as np

from .cosim import CoSimulationResult, THERMAL_ONLY, trace_sha256
from .environment import EnvironmentTrace
from .power import PowerParameters


def run_metrics(
    result: CoSimulationResult,
    environment: EnvironmentTrace,
    measurement_mask: np.ndarray,
    *,
    dt_s: float,
    power_params: PowerParameters,
) -> dict[str, Any]:
    mask = np.asarray(measurement_mask, dtype=bool)
    requested = result.requested_compute_W[mask]
    executed = result.executed_compute_W[mask]
    denied = requested - executed
    node = result.node_temperature_K[1:][mask]
    radiator = result.radiator_temperature_K[1:][mask]
    requested_energy = float(math.fsum(float(v) for v in requested) * dt_s)
    executed_energy = float(math.fsum(float(v) for v in executed) * dt_s)
    denied_energy = float(math.fsum(float(v) for v in denied) * dt_s)
    hot = environment.hot_mask[mask]
    hot_requested = float(math.fsum(float(v) for v in requested[hot]) * dt_s)
    hot_executed = float(math.fsum(float(v) for v in executed[hot]) * dt_s)
    values: dict[str, Any] = {
        "requested_mean_compute_power_W": float(np.mean(requested)),
        "executed_mean_compute_power_W": float(np.mean(executed)),
        "requested_compute_energy_J": requested_energy,
        "executed_compute_energy_J": executed_energy,
        "compute_energy_denied_J": denied_energy,
        "compute_energy_denied_fraction": denied_energy / requested_energy if requested_energy else 0.0,
        "peak_requested_compute_power_W": float(np.max(requested)),
        "peak_executed_compute_power_W": float(np.max(executed)),
        "peak_node_temperature_K": float(np.max(node)),
        "peak_radiator_temperature_K": float(np.max(radiator)),
        "time_above_project_throttle_threshold_s": float(
            np.count_nonzero(node >= 348.15) * dt_s
        ),
        "thermal_throttle_event_count": int(result.fdir_event_count),
        "time_thermally_throttled_s": float(np.count_nonzero(result.fdir_shedding[mask]) * dt_s),
        "hot_phase_requested_energy_fraction": hot_requested / requested_energy if requested_energy else None,
        "hot_phase_executed_energy_fraction": hot_executed / executed_energy if executed_energy else None,
        "executed_workload_trace_sha256": trace_sha256(result.executed_compute_W),
        "thermal_energy_balance_residual_J": result.thermal_energy_balance_residual_J,
    }
    if result.mode == THERMAL_ONLY:
        values.update({
            "initial_battery_SOC": None, "final_battery_SOC": None,
            "minimum_battery_SOC": None, "maximum_battery_SOC": None,
            "battery_energy_throughput_J": None, "solar_energy_generated_J": None,
            "battery_energy_discharged_J": None, "battery_energy_charged_J": None,
            "electrical_energy_curtailed_J": None, "electrical_unserved_energy_J": None,
            "electrical_energy_balance_residual_J": None,
            "electrical_energy_balance_tolerance_J": None,
            "maximum_absolute_cumulative_electrical_residual_J": None,
        })
    else:
        assert result.battery_SOC is not None
        assert result.battery_removed_power_W is not None
        assert result.battery_stored_power_W is not None
        assert result.curtailment_W is not None
        assert result.unserved_housekeeping_W is not None
        assert result.electrical_balance_residual_J is not None
        cumulative = np.cumsum(result.electrical_balance_residual_J, dtype=np.float64)
        values.update({
            "initial_battery_SOC": float(result.battery_SOC[0]),
            "final_battery_SOC": float(result.battery_SOC[-1]),
            "minimum_battery_SOC": float(np.min(result.battery_SOC)),
            "maximum_battery_SOC": float(np.max(result.battery_SOC)),
            "battery_energy_throughput_J": float(np.sum(
                result.battery_removed_power_W + result.battery_stored_power_W
            ) * dt_s),
            "solar_energy_generated_J": float(np.sum(environment.solar_generation_W) * dt_s),
            "battery_energy_discharged_J": float(np.sum(result.battery_removed_power_W) * dt_s),
            "battery_energy_charged_J": float(np.sum(result.battery_stored_power_W) * dt_s),
            "electrical_energy_curtailed_J": float(np.sum(result.curtailment_W) * dt_s),
            "electrical_unserved_energy_J": float(np.sum(result.unserved_housekeeping_W) * dt_s),
            "electrical_energy_balance_residual_J": float(cumulative[-1]),
            "maximum_absolute_cumulative_electrical_residual_J": float(np.max(np.abs(cumulative))),
            "electrical_energy_balance_tolerance_J": result.electrical_balance_tolerance_J,
        })
    return values


def add_paired_deltas(rows: list[dict[str, Any]]) -> None:
    references = {
        (row["seed"], row["environment_id"], row["mode"]): row
        for row in rows if row["workload_id"] == "constant_reference"
    }
    for row in rows:
        reference = references[(row["seed"], row["environment_id"], row["mode"])]
        row["delta_peak_temperature_vs_reference_K"] = (
            row["peak_node_temperature_K"] - reference["peak_node_temperature_K"]
        )


def _median(values: Iterable[float | int | None]) -> float | None:
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(median(finite)) if finite else None


def aggregate_smoke(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["environment_id"], row["mode"], row["workload_id"])].append(row)
    output: list[dict[str, Any]] = []
    for (environment_id, mode, workload_id), members in sorted(groups.items()):
        output.append({
            "environment_id": environment_id,
            "mode": mode,
            "workload_id": workload_id,
            "run_count": len(members),
            "valid_run_count": sum(bool(r["valid_run"]) for r in members),
            "invalid_run_count": sum(not bool(r["valid_run"]) for r in members),
            "requested_compute_energy_J_median": _median(r["requested_compute_energy_J"] for r in members),
            "executed_compute_energy_J_median": _median(r["executed_compute_energy_J"] for r in members),
            "compute_energy_denied_fraction_median": _median(r["compute_energy_denied_fraction"] for r in members),
            "peak_node_temperature_K_median": _median(r["peak_node_temperature_K"] for r in members),
            "delta_peak_temperature_vs_reference_K_median": _median(r["delta_peak_temperature_vs_reference_K"] for r in members),
            "minimum_battery_SOC_median": _median(r["minimum_battery_SOC"] for r in members),
            "final_battery_SOC_median": _median(r["final_battery_SOC"] for r in members),
            "thermal_throttle_event_count_median": _median(r["thermal_throttle_event_count"] for r in members),
            "time_thermally_throttled_s_median": _median(r["time_thermally_throttled_s"] for r in members),
        })
    return output


def build_special_analyses(aggregates: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the prerequested A-G smoke comparisons without classification."""
    index = {
        (row["environment_id"], row["mode"], row["workload_id"]): row
        for row in aggregates
    }
    workloads = sorted({row["workload_id"] for row in aggregates})
    environments = sorted({row["environment_id"] for row in aggregates})
    e0 = "E0_CANONICAL"
    e1 = "E1_REPRESENTATIVE_ANALYTIC_LEO"
    thermal_environment_comparison = []
    for workload in workloads:
        left = index[(e0, "THERMAL_ONLY", workload)]
        right = index[(e1, "THERMAL_ONLY", workload)]
        thermal_environment_comparison.append({
            "workload_id": workload,
            "E0_delta_peak_vs_W0_K": left["delta_peak_temperature_vs_reference_K_median"],
            "E1_delta_peak_vs_W0_K": right["delta_peak_temperature_vs_reference_K_median"],
            "E1_minus_E0_delta_peak_K": (
                right["delta_peak_temperature_vs_reference_K_median"]
                - left["delta_peak_temperature_vs_reference_K_median"]
            ),
            "E0_peak_node_temperature_K": left["peak_node_temperature_K_median"],
            "E1_peak_node_temperature_K": right["peak_node_temperature_K_median"],
            "materiality_assessment": "not assigned; no RSIM smoke materiality threshold is preregistered",
        })
    electrical_comparison = []
    fdir_comparison = []
    for environment in environments:
        for workload in workloads:
            thermal = index[(environment, "THERMAL_ONLY", workload)]
            power = index[(environment, "POWER_CONSTRAINED", workload)]
            closed = index[(environment, "CLOSED_LOOP", workload)]
            electrical_comparison.append({
                "environment_id": environment, "workload_id": workload,
                "power_constrained_executed_energy_J_median": power["executed_compute_energy_J_median"],
                "power_constrained_denied_fraction_median": power["compute_energy_denied_fraction_median"],
                "power_constrained_minus_thermal_only_peak_K": (
                    power["peak_node_temperature_K_median"] - thermal["peak_node_temperature_K_median"]
                ),
                "power_constraints_prevent_full_requested_trace": bool(
                    power["compute_energy_denied_fraction_median"] > 0.0
                    or power["invalid_run_count"] > 0
                ),
                "invalid_run_count": power["invalid_run_count"],
            })
            fdir_comparison.append({
                "environment_id": environment, "workload_id": workload,
                "closed_loop_executed_energy_J_median": closed["executed_compute_energy_J_median"],
                "closed_loop_denied_fraction_median": closed["compute_energy_denied_fraction_median"],
                "closed_loop_minus_power_constrained_peak_K": (
                    closed["peak_node_temperature_K_median"] - power["peak_node_temperature_K_median"]
                ),
                "closed_loop_minus_power_constrained_executed_energy_J": (
                    closed["executed_compute_energy_J_median"] - power["executed_compute_energy_J_median"]
                ),
                "throttle_events_median": closed["thermal_throttle_event_count_median"],
                "time_throttled_s_median": closed["time_thermally_throttled_s_median"],
                "fdir_intervenes": bool(
                    closed["thermal_throttle_event_count_median"] > 0.0
                    or closed["executed_compute_energy_J_median"]
                    < power["executed_compute_energy_J_median"] - 1e-6
                ),
            })
    focus = {
        workload: [row for row in aggregates if row["workload_id"] == workload]
        for workload in ("power_aware_benign", "phase_shaped_candidate")
    }
    return {
        "aggregation_basis": "all smoke runs including explicitly invalid runs; diagnostic medians only",
        "E0_mode_A_against_existing_WRB": "see hard_gates.json; exact regression",
        "E0_vs_E1_thermal_only": thermal_environment_comparison,
        "thermal_only_vs_power_constrained": electrical_comparison,
        "power_constrained_vs_closed_loop": fdir_comparison,
        "focus_workloads": focus,
        "classification": None,
    }


__all__ = [
    "add_paired_deltas", "aggregate_smoke", "build_special_analyses", "run_metrics",
]
