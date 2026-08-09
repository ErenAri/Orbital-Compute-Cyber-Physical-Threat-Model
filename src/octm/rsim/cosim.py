"""RSIM-001 causal spacecraft-wrapper co-simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from src.octm.baselines.v044 import thermal_model as canonical
from .environment import EnvironmentTrace
from .fdir import FDIRParameters, FDIRState, fdir_decision
from .power import DEFAULT_POWER_PARAMETERS, PowerParameters, step_power_system
from .reserve import (
    ESSENTIAL_RESERVE_FEASIBLE,
    ReserveProfile,
    build_reserve_profile,
    require_feasible_reserve,
    step_reserve_aware_power_system,
)
from .thermal_bridge import one_step, run_trace, thermal_residual_J


THERMAL_ONLY = "THERMAL_ONLY"
POWER_CONSTRAINED = "POWER_CONSTRAINED"
CLOSED_LOOP = "CLOSED_LOOP"
SIMULATION_MODES = (THERMAL_ONLY, POWER_CONSTRAINED, CLOSED_LOOP)


@dataclass(frozen=True, slots=True)
class CoSimulationResult:
    mode: str
    requested_compute_W: np.ndarray
    power_feasible_compute_W: np.ndarray
    fdir_limit_W: np.ndarray
    executed_compute_W: np.ndarray
    node_temperature_K: np.ndarray
    radiator_temperature_K: np.ndarray
    battery_SOC: np.ndarray | None
    battery_charge_bus_W: np.ndarray | None
    battery_discharge_bus_W: np.ndarray | None
    battery_stored_power_W: np.ndarray | None
    battery_removed_power_W: np.ndarray | None
    curtailment_W: np.ndarray | None
    unserved_housekeeping_W: np.ndarray | None
    electrical_balance_residual_J: np.ndarray | None
    fdir_shedding: np.ndarray
    fdir_event_count: int
    fdir_recovery_count: int
    thermal_energy_balance_residual_J: float
    electrical_balance_tolerance_J: float | None
    valid_run: bool
    invalid_reason: str | None
    invariant_results: dict[str, bool]
    reserve_profile: ReserveProfile | None = None
    reserve_active: np.ndarray | None = None
    reserve_limited_compute: np.ndarray | None = None
    reserve_denied_compute_W: np.ndarray | None = None
    instantaneous_denied_compute_W: np.ndarray | None = None
    fdir_denied_compute_W: np.ndarray | None = None


def trace_sha256(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values, dtype="<f8")
    digest = hashlib.sha256(b"rsim-001.trace.v1\x00")
    digest.update(array.tobytes())
    return digest.hexdigest()


def _initialization_dominated(
    soc: np.ndarray,
    unserved_W: np.ndarray,
    *,
    warmup_stop: int,
    period_s: float,
    dt_s: float,
    params: PowerParameters,
) -> bool:
    if np.any(unserved_W[:warmup_stop] > 1e-9):
        return True
    required = int(math.ceil(period_s / dt_s))
    bound = (
        np.isclose(soc[: warmup_stop + 1], params.minimum_SOC, atol=1e-12, rtol=0.0)
        | np.isclose(soc[: warmup_stop + 1], params.maximum_SOC, atol=1e-12, rtol=0.0)
    )
    longest = current = 0
    for value in bound:
        current = current + 1 if bool(value) else 0
        longest = max(longest, current)
    return longest >= required


def simulate(
    requested_compute_W: np.ndarray,
    environment: EnvironmentTrace,
    *,
    mode: str,
    dt_s: float = 1.0,
    fdir_params: FDIRParameters = FDIRParameters(),
    power_params: PowerParameters = DEFAULT_POWER_PARAMETERS,
    warmup_stop_index: int = 10_800,
    reserve_time_until_next_generation_s: np.ndarray | None = None,
) -> CoSimulationResult:
    """Run one mode using canonical left-endpoint/Forward-Euler order."""

    requested = np.ascontiguousarray(requested_compute_W, dtype=np.float64)
    flux = np.asarray(environment.absorbed_flux_W_m2, dtype=np.float64)
    solar = np.asarray(environment.solar_generation_W, dtype=np.float64)
    if mode not in SIMULATION_MODES:
        raise ValueError(f"unknown simulation mode: {mode}")
    if requested.ndim != 1 or requested.shape != flux.shape or requested.shape != solar.shape:
        raise ValueError("requested workload and environment arrays must match")
    if requested.size < 2 or not np.all(np.isfinite(requested)) or np.any(requested < 0.0):
        raise ValueError("requested workload must be finite, non-negative, and have >=2 samples")
    if np.any(requested > power_params.compute_design_power_W + 1e-9):
        raise ValueError("requested workload exceeds the frozen design limit")
    power_params.validate()
    fdir_params.validate()
    n = requested.size
    design = power_params.compute_design_power_W
    reserve_profile: ReserveProfile | None = None
    if reserve_time_until_next_generation_s is not None:
        if mode == THERMAL_ONLY:
            raise ValueError("reserve-aware admission is not applicable to THERMAL_ONLY")
        lookahead = np.asarray(reserve_time_until_next_generation_s, dtype=np.float64)
        if lookahead.shape != requested.shape:
            raise ValueError("reserve look-ahead must match the requested workload")
        reserve_profile = build_reserve_profile(lookahead, params=power_params)
        require_feasible_reserve(reserve_profile)

    if mode == THERMAL_ONLY:
        thermal = run_trace(requested, flux, dt_s=dt_s)
        invariant_results = {
            "finite_state": bool(
                np.all(np.isfinite(thermal.node_temperature_K))
                and np.all(np.isfinite(thermal.radiator_temperature_K))
            ),
            "executed_le_requested": True,
            "executed_le_design": bool(np.all(requested <= design + 1e-9)),
            "no_hidden_clipping": True,
            "soc_within_bounds": True,
            "battery_never_creates_energy": True,
            "housekeeping_priority": True,
            "electrical_balance_closes": True,
            "fdir_never_increases_power": True,
        }
        valid = all(invariant_results.values())
        return CoSimulationResult(
            mode=mode,
            requested_compute_W=requested.copy(),
            power_feasible_compute_W=np.full(n, design),
            fdir_limit_W=np.full(n, design),
            executed_compute_W=requested.copy(),
            node_temperature_K=thermal.node_temperature_K,
            radiator_temperature_K=thermal.radiator_temperature_K,
            battery_SOC=None,
            battery_charge_bus_W=None,
            battery_discharge_bus_W=None,
            battery_stored_power_W=None,
            battery_removed_power_W=None,
            curtailment_W=None,
            unserved_housekeeping_W=None,
            electrical_balance_residual_J=None,
            fdir_shedding=np.zeros(n, dtype=bool),
            fdir_event_count=0,
            fdir_recovery_count=0,
            thermal_energy_balance_residual_J=thermal.thermal_energy_balance_residual_J,
            electrical_balance_tolerance_J=None,
            valid_run=valid,
            invalid_reason=None if valid else "INVARIANT_FAILURE",
            invariant_results=invariant_results,
        )

    feasible = np.empty(n, dtype=np.float64)
    fdir_limit = np.full(n, design, dtype=np.float64)
    executed = np.empty(n, dtype=np.float64)
    charge = np.empty(n, dtype=np.float64)
    discharge = np.empty(n, dtype=np.float64)
    stored = np.empty(n, dtype=np.float64)
    removed = np.empty(n, dtype=np.float64)
    curtail = np.empty(n, dtype=np.float64)
    unserved = np.empty(n, dtype=np.float64)
    residual = np.empty(n, dtype=np.float64)
    reserve_active = np.zeros(n, dtype=bool) if reserve_profile is not None else None
    reserve_limited = np.zeros(n, dtype=bool) if reserve_profile is not None else None
    reserve_denied = np.zeros(n, dtype=np.float64) if reserve_profile is not None else None
    instantaneous_denied = np.zeros(n, dtype=np.float64) if reserve_profile is not None else None
    fdir_denied = np.zeros(n, dtype=np.float64) if reserve_profile is not None else None
    shedding_trace = np.zeros(n, dtype=bool)
    soc = np.empty(n + 1, dtype=np.float64)
    energy = power_params.initial_energy_J
    soc[0] = power_params.initial_SOC
    invalid_reason: str | None = None
    state = FDIRState()
    event_count = recovery_count = 0

    node_left = np.empty(n, dtype=np.float64)
    radiator_left = np.empty(n, dtype=np.float64)
    node_left[0] = float(canonical.P["Tn0"])
    radiator_left[0] = float(canonical.P["Tr0"])

    for i in range(n):
        enabled = mode == CLOSED_LOOP
        decision = fdir_decision(
            # POWER_CONSTRAINED has no thermal feedback.  Its full executed
            # trace is integrated monolithically after electrical admission,
            # so no unread/uninitialised future thermal state may enter FDIR.
            node_temperature_K=(node_left[i] if enabled else float(canonical.P["Tn0"])),
            time_s=i * dt_s,
            requested_compute_W=requested[i], state=state,
            enabled=enabled, params=fdir_params,
        )
        state = decision.state
        event_count += int(decision.activated)
        recovery_count += int(decision.recovered)
        shedding_trace[i] = state.shedding
        fdir_limit[i] = min(design, decision.power_limit_W)
        if reserve_profile is None:
            step = step_power_system(
                battery_energy_J=energy, solar_generation_W=solar[i],
                requested_compute_W=requested[i], fdir_limit_W=decision.power_limit_W,
                dt_s=dt_s, params=power_params,
            )
        else:
            reserve_step = step_reserve_aware_power_system(
                battery_energy_J=energy, solar_generation_W=solar[i],
                requested_compute_W=requested[i], fdir_limit_W=decision.power_limit_W,
                time_until_next_generation_s=(
                    reserve_profile.time_until_next_generation_s[i]
                ),
                dt_s=dt_s, params=power_params,
            )
            step = reserve_step.power
            assert reserve_active is not None
            assert reserve_limited is not None
            assert reserve_denied is not None
            assert instantaneous_denied is not None
            assert fdir_denied is not None
            reserve_active[i] = reserve_step.reserve_active
            reserve_limited[i] = reserve_step.reserve_limited_compute
            reserve_denied[i] = reserve_step.reserve_denied_compute_W
            instantaneous_denied[i] = reserve_step.instantaneous_denied_compute_W
            fdir_denied[i] = reserve_step.fdir_denied_compute_W
        feasible[i] = step.power_feasible_compute_W
        executed[i] = step.executed_compute_W
        charge[i] = step.battery_charge_bus_W
        discharge[i] = step.battery_discharge_bus_W
        stored[i] = step.battery_stored_power_W
        removed[i] = step.battery_removed_power_W
        curtail[i] = step.curtailment_W
        unserved[i] = step.unserved_housekeeping_W
        residual[i] = step.balance_residual_J
        energy = step.next_battery_energy_J
        soc[i + 1] = energy / power_params.battery_energy_capacity_J
        if not step.valid and invalid_reason is None:
            invalid_reason = step.invalid_reason
        if i < n - 1:
            if mode == CLOSED_LOOP:
                node_left[i + 1], radiator_left[i + 1] = one_step(
                    executed[i], flux[i], node_left[i], radiator_left[i], dt_s=dt_s
                )

    if mode == POWER_CONSTRAINED:
        thermal = run_trace(executed, flux, dt_s=dt_s)
        node = thermal.node_temperature_K
        radiator = thermal.radiator_temperature_K
        thermal_residual = thermal.thermal_energy_balance_residual_J
    else:
        node = np.concatenate(([node_left[0]], node_left))
        radiator = np.concatenate(([radiator_left[0]], radiator_left))
        thermal_residual = thermal_residual_J(executed, flux, node, radiator, dt_s)

    cumulative_balance = np.cumsum(residual, dtype=np.float64)
    finite = bool(all(np.all(np.isfinite(a)) for a in (
        executed, feasible, node, radiator, soc, charge, discharge, curtail, residual,
    )))
    soc_ok = bool(
        np.all(soc >= power_params.minimum_SOC - 1e-12)
        and np.all(soc <= power_params.maximum_SOC + 1e-12)
    )
    electrical_energy_scale_J = float(
        (np.sum(solar, dtype=np.float64) + np.sum(removed, dtype=np.float64)) * dt_s
    )
    balance_tolerance_J = max(1e-4, 1e-12 * electrical_energy_scale_J)
    balance_ok = bool(np.max(np.abs(cumulative_balance)) <= balance_tolerance_J)
    battery_direction_ok = bool(
        np.all((charge <= 1e-12) | (stored >= -1e-12))
        and np.all((discharge <= 1e-12) | (removed >= discharge - 1e-12))
    )
    invariant_results = {
        "finite_state": finite,
        "executed_le_requested": bool(np.all(executed <= requested + 1e-9)),
        "executed_le_design": bool(np.all(executed <= design + 1e-9)),
        "no_hidden_clipping": bool(np.all(curtail >= -1e-9) and np.all(requested - executed >= -1e-9)),
        "soc_within_bounds": soc_ok,
        "battery_never_creates_energy": battery_direction_ok,
        "housekeeping_priority": bool(np.all((unserved <= 1e-9) | (executed <= 1e-9))),
        "electrical_balance_closes": balance_ok,
        "fdir_never_increases_power": bool(np.all(executed <= requested + 1e-9)),
    }
    if reserve_profile is not None:
        assert reserve_denied is not None
        assert instantaneous_denied is not None
        assert fdir_denied is not None
        denied = requested - executed
        invariant_results.update({
            "essential_reserve_architecture_feasible": (
                reserve_profile.architecture_condition == ESSENTIAL_RESERVE_FEASIBLE
            ),
            "reserve_never_increases_power": bool(
                np.all(executed <= feasible + 1e-9)
            ),
            "compute_denial_attribution_closes": bool(np.allclose(
                instantaneous_denied + reserve_denied + fdir_denied,
                denied, atol=1e-9, rtol=0.0,
            )),
        })
    valid = invalid_reason is None and all(invariant_results.values())
    if invalid_reason is None and not valid:
        invalid_reason = "INVARIANT_FAILURE"
    if reserve_profile is None:
        # Historical A0-M compatibility diagnostic; it does not change validity.
        invariant_results["initialization_domination_flag"] = _initialization_dominated(
            soc, unserved, warmup_stop=warmup_stop_index, period_s=environment.period_s,
            dt_s=dt_s, params=power_params,
        )
    else:
        # A0-R uses the precise name for the actual condition being diagnosed.
        invariant_results["warmup_power_deficit_flag"] = bool(
            np.any(unserved[:warmup_stop_index] > 1e-9)
        )
    return CoSimulationResult(
        mode=mode,
        requested_compute_W=requested.copy(),
        power_feasible_compute_W=feasible,
        fdir_limit_W=fdir_limit,
        executed_compute_W=executed,
        node_temperature_K=node,
        radiator_temperature_K=radiator,
        battery_SOC=soc,
        battery_charge_bus_W=charge,
        battery_discharge_bus_W=discharge,
        battery_stored_power_W=stored,
        battery_removed_power_W=removed,
        curtailment_W=curtail,
        unserved_housekeeping_W=unserved,
        electrical_balance_residual_J=residual,
        fdir_shedding=shedding_trace,
        fdir_event_count=event_count,
        fdir_recovery_count=recovery_count,
        thermal_energy_balance_residual_J=thermal_residual,
        electrical_balance_tolerance_J=balance_tolerance_J,
        valid_run=valid,
        invalid_reason=invalid_reason,
        invariant_results=invariant_results,
        reserve_profile=reserve_profile,
        reserve_active=reserve_active,
        reserve_limited_compute=reserve_limited,
        reserve_denied_compute_W=reserve_denied,
        instantaneous_denied_compute_W=instantaneous_denied,
        fdir_denied_compute_W=fdir_denied,
    )


__all__ = [
    "CLOSED_LOOP", "POWER_CONSTRAINED", "SIMULATION_MODES", "THERMAL_ONLY",
    "CoSimulationResult", "simulate", "trace_sha256",
]
