"""Workload-independent essential-load reserve admission for RSIM-001-PWR1."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .power import (
    DEFAULT_POWER_PARAMETERS,
    PowerParameters,
    PowerStepResult,
    SYSTEM_POWER_DEFICIT,
)


A0_R_ARCHITECTURE_ID = "A0-R_RESERVE_AWARE_ESSENTIAL_LOAD_ADMISSION"
ESSENTIAL_RESERVE_FEASIBLE = "ESSENTIAL_RESERVE_FEASIBLE"
ESSENTIAL_RESERVE_INFEASIBLE = "ESSENTIAL_RESERVE_INFEASIBLE"


class EssentialReserveInfeasibleError(ValueError):
    """Raised when even SOC_max cannot contain the required essential reserve."""

    condition = ESSENTIAL_RESERVE_INFEASIBLE


@dataclass(frozen=True, slots=True)
class ReserveProfile:
    time_until_next_generation_s: np.ndarray
    essential_reserve_J: np.ndarray
    protected_battery_energy_J: np.ndarray
    protected_battery_SOC_equivalent: np.ndarray
    architecture_condition: str


@dataclass(frozen=True, slots=True)
class ReservePowerStepResult:
    power: PowerStepResult
    essential_reserve_J: float
    protected_battery_energy_J: float
    protected_battery_SOC_equivalent: float
    time_until_next_generation_s: float
    reserve_active: bool
    reserve_limited_compute: bool
    reserve_denied_compute_W: float
    instantaneous_denied_compute_W: float
    fdir_denied_compute_W: float


def time_until_next_generation(
    solar_generation_W: np.ndarray,
    *,
    horizon_length: int,
    dt_s: float,
) -> np.ndarray:
    """Return exact look-ahead to the next positive-generation interval.

    ``solar_generation_W`` must include enough deterministic forecast padding
    beyond ``horizon_length`` to cover a trailing no-generation interval.
    Current positive-generation intervals have a zero look-ahead.
    """

    solar = np.asarray(solar_generation_W, dtype=np.float64)
    if solar.ndim != 1 or horizon_length <= 0 or solar.size < horizon_length:
        raise ValueError("solar forecast must cover the requested horizon")
    if not math.isfinite(dt_s) or dt_s <= 0.0 or np.any(~np.isfinite(solar)) or np.any(solar < 0.0):
        raise ValueError("solar forecast must be finite/non-negative and dt_s positive")
    output = np.empty(horizon_length, dtype=np.float64)
    next_positive: int | None = None
    for i in range(solar.size - 1, -1, -1):
        if solar[i] > 0.0:
            next_positive = i
        if i < horizon_length:
            if next_positive is None:
                raise ValueError("solar forecast padding does not reach the next generation interval")
            output[i] = 0.0 if solar[i] > 0.0 else (next_positive - i) * dt_s
    return output


def build_reserve_profile(
    time_until_next_generation_s: np.ndarray,
    *,
    params: PowerParameters = DEFAULT_POWER_PARAMETERS,
) -> ReserveProfile:
    """Construct the frozen housekeeping-only protected-energy profile."""

    params.validate()
    lookahead = np.asarray(time_until_next_generation_s, dtype=np.float64)
    if lookahead.ndim != 1 or lookahead.size == 0:
        raise ValueError("time-until-generation profile must be a non-empty vector")
    if np.any(~np.isfinite(lookahead)) or np.any(lookahead < 0.0):
        raise ValueError("time-until-generation values must be finite and non-negative")
    reserve = params.housekeeping_power_W * lookahead / params.discharge_efficiency
    protected = params.minimum_energy_J + reserve
    condition = (
        ESSENTIAL_RESERVE_FEASIBLE
        if bool(np.all(protected <= params.maximum_energy_J + 1e-9))
        else ESSENTIAL_RESERVE_INFEASIBLE
    )
    return ReserveProfile(
        time_until_next_generation_s=lookahead.copy(),
        essential_reserve_J=reserve,
        protected_battery_energy_J=protected,
        protected_battery_SOC_equivalent=protected / params.battery_energy_capacity_J,
        architecture_condition=condition,
    )


def require_feasible_reserve(profile: ReserveProfile) -> None:
    if profile.architecture_condition != ESSENTIAL_RESERVE_FEASIBLE:
        maximum = float(np.max(profile.protected_battery_SOC_equivalent))
        raise EssentialReserveInfeasibleError(
            f"{ESSENTIAL_RESERVE_INFEASIBLE}: protected SOC equivalent {maximum:.12g} "
            f"exceeds the declared maximum"
        )


def step_reserve_aware_power_system(
    *,
    battery_energy_J: float,
    solar_generation_W: float,
    requested_compute_W: float,
    fdir_limit_W: float,
    time_until_next_generation_s: float,
    dt_s: float,
    params: PowerParameters = DEFAULT_POWER_PARAMETERS,
) -> ReservePowerStepResult:
    """Advance one interval while protecting future housekeeping energy.

    Denial attribution is an additive admission waterfall: instantaneous
    hardware feasibility, then essential reserve, then FDIR.  Workload identity
    is intentionally absent from the interface.
    """

    params.validate()
    values = (
        battery_energy_J, solar_generation_W, requested_compute_W,
        time_until_next_generation_s, dt_s,
    )
    if any(not math.isfinite(value) for value in values) or dt_s <= 0.0:
        raise ValueError("reserve power-step inputs must be finite and dt_s positive")
    if not (math.isfinite(fdir_limit_W) or fdir_limit_W == math.inf):
        raise ValueError("FDIR limit must be finite or positive infinity")
    if min(solar_generation_W, requested_compute_W, fdir_limit_W, time_until_next_generation_s) < 0.0:
        raise ValueError("reserve power-step inputs must be non-negative")
    eps = 1e-9
    if not (params.minimum_energy_J - eps <= battery_energy_J <= params.maximum_energy_J + eps):
        raise ValueError("battery state is outside declared SOC bounds")

    reserve_J = (
        params.housekeeping_power_W * time_until_next_generation_s
        / params.discharge_efficiency
    )
    protected_J = params.minimum_energy_J + reserve_J
    if protected_J > params.maximum_energy_J + eps:
        raise EssentialReserveInfeasibleError(
            f"{ESSENTIAL_RESERVE_INFEASIBLE}: protected energy exceeds SOC_max"
        )

    available_internal_J = max(0.0, battery_energy_J - params.minimum_energy_J)
    available_discharge_bus_W = min(
        params.maximum_discharge_power_W,
        available_internal_J * params.discharge_efficiency / dt_s,
    )
    total_bus_available_W = solar_generation_W + available_discharge_bus_W
    unserved_housekeeping_W = max(0.0, params.housekeeping_power_W - total_bus_available_W)
    valid = unserved_housekeeping_W <= eps
    invalid_reason = None if valid else SYSTEM_POWER_DEFICIT

    instantaneous_feasible_compute_W = min(
        params.compute_design_power_W,
        max(0.0, total_bus_available_W - params.housekeeping_power_W),
    )
    housekeeping_from_battery_W = max(0.0, params.housekeeping_power_W - solar_generation_W)
    remaining_discharge_limit_W = max(
        0.0, params.maximum_discharge_power_W - housekeeping_from_battery_W
    )
    reserve_excess_internal_J = max(0.0, battery_energy_J - protected_J)
    reserve_compute_discharge_W = min(
        remaining_discharge_limit_W,
        reserve_excess_internal_J * params.discharge_efficiency / dt_s,
    )
    instantaneous_solar_compute_W = max(
        0.0, solar_generation_W - params.housekeeping_power_W
    )
    reserve_feasible_compute_W = min(
        params.compute_design_power_W,
        instantaneous_solar_compute_W + reserve_compute_discharge_W,
        instantaneous_feasible_compute_W,
    )

    after_instantaneous = min(requested_compute_W, instantaneous_feasible_compute_W)
    after_reserve = min(after_instantaneous, reserve_feasible_compute_W)
    executed = min(after_reserve, fdir_limit_W, params.compute_design_power_W) if valid else 0.0
    instantaneous_denied_W = requested_compute_W - after_instantaneous
    reserve_denied_W = after_instantaneous - after_reserve
    fdir_denied_W = after_reserve - executed
    if not valid:
        # With housekeeping unavailable, the instantaneous stage owns any
        # remaining compute denial and the later controllers do not act.
        instantaneous_denied_W = requested_compute_W
        reserve_denied_W = 0.0
        fdir_denied_W = 0.0

    actual_bus_load_W = (
        params.housekeeping_power_W + executed
        if valid else min(params.housekeeping_power_W, total_bus_available_W)
    )
    charge_bus_W = discharge_bus_W = stored_W = removed_W = 0.0
    curtailment_W = 0.0
    if solar_generation_W >= actual_bus_load_W:
        surplus_W = solar_generation_W - actual_bus_load_W
        capacity_charge_bus_W = max(
            0.0,
            (params.maximum_energy_J - battery_energy_J)
            / (params.charge_efficiency * dt_s),
        )
        charge_bus_W = min(surplus_W, params.maximum_charge_power_W, capacity_charge_bus_W)
        stored_W = params.charge_efficiency * charge_bus_W
        curtailment_W = surplus_W - charge_bus_W
        next_energy = battery_energy_J + stored_W * dt_s
    else:
        discharge_bus_W = actual_bus_load_W - solar_generation_W
        removed_W = discharge_bus_W / params.discharge_efficiency
        next_energy = battery_energy_J - removed_W * dt_s

    charge_loss_W = charge_bus_W - stored_W
    discharge_loss_W = removed_W - discharge_bus_W
    next_energy = min(params.maximum_energy_J, max(params.minimum_energy_J, next_energy))
    lhs_J = solar_generation_W * dt_s + battery_energy_J - next_energy
    rhs_J = (
        actual_bus_load_W + charge_loss_W + discharge_loss_W + curtailment_W
    ) * dt_s
    residual_J = lhs_J - rhs_J
    power = PowerStepResult(
        next_battery_energy_J=next_energy,
        power_feasible_compute_W=reserve_feasible_compute_W,
        executed_compute_W=executed,
        battery_charge_bus_W=charge_bus_W,
        battery_discharge_bus_W=discharge_bus_W,
        battery_stored_power_W=stored_W,
        battery_removed_power_W=removed_W,
        curtailment_W=curtailment_W,
        unserved_housekeeping_W=unserved_housekeeping_W,
        compute_denied_W=requested_compute_W - executed,
        charge_loss_W=charge_loss_W,
        discharge_loss_W=discharge_loss_W,
        balance_residual_J=residual_J,
        valid=valid,
        invalid_reason=invalid_reason,
    )
    return ReservePowerStepResult(
        power=power,
        essential_reserve_J=reserve_J,
        protected_battery_energy_J=protected_J,
        protected_battery_SOC_equivalent=protected_J / params.battery_energy_capacity_J,
        time_until_next_generation_s=time_until_next_generation_s,
        reserve_active=bool(reserve_J > eps),
        reserve_limited_compute=bool(reserve_denied_W > eps),
        reserve_denied_compute_W=reserve_denied_W,
        instantaneous_denied_compute_W=instantaneous_denied_W,
        fdir_denied_compute_W=fdir_denied_W,
    )


__all__ = [
    "A0_R_ARCHITECTURE_ID", "ESSENTIAL_RESERVE_FEASIBLE",
    "ESSENTIAL_RESERVE_INFEASIBLE", "EssentialReserveInfeasibleError",
    "ReservePowerStepResult", "ReserveProfile", "build_reserve_profile",
    "require_feasible_reserve", "step_reserve_aware_power_system",
    "time_until_next_generation",
]
