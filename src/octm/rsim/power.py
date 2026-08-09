"""Transparent first-order RSIM-001 solar/battery bus model."""

from __future__ import annotations

from dataclasses import dataclass
import math


SYSTEM_POWER_DEFICIT = "SYSTEM_POWER_DEFICIT"


@dataclass(frozen=True, slots=True)
class PowerParameters:
    battery_energy_capacity_J: float = 102_818_124.44650389
    initial_SOC: float = 0.90
    minimum_SOC: float = 0.20
    maximum_SOC: float = 0.90
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    maximum_charge_power_W: float = 53_731.74872665535
    maximum_discharge_power_W: float = 42_000.0
    housekeeping_power_W: float = 2_000.0
    compute_design_power_W: float = 40_000.0

    def validate(self) -> None:
        if self.battery_energy_capacity_J <= 0.0:
            raise ValueError("battery capacity must be positive")
        if not (0.0 <= self.minimum_SOC <= self.initial_SOC <= self.maximum_SOC <= 1.0):
            raise ValueError("invalid SOC bounds/initial condition")
        if not (0.0 < self.charge_efficiency <= 1.0):
            raise ValueError("invalid charge efficiency")
        if not (0.0 < self.discharge_efficiency <= 1.0):
            raise ValueError("invalid discharge efficiency")
        values = (
            self.maximum_charge_power_W, self.maximum_discharge_power_W,
            self.housekeeping_power_W, self.compute_design_power_W,
        )
        if any(not math.isfinite(v) or v < 0.0 for v in values):
            raise ValueError("power limits must be finite and non-negative")

    @property
    def minimum_energy_J(self) -> float:
        return self.minimum_SOC * self.battery_energy_capacity_J

    @property
    def maximum_energy_J(self) -> float:
        return self.maximum_SOC * self.battery_energy_capacity_J

    @property
    def initial_energy_J(self) -> float:
        return self.initial_SOC * self.battery_energy_capacity_J


DEFAULT_POWER_PARAMETERS = PowerParameters()


@dataclass(frozen=True, slots=True)
class PowerStepResult:
    next_battery_energy_J: float
    power_feasible_compute_W: float
    executed_compute_W: float
    battery_charge_bus_W: float
    battery_discharge_bus_W: float
    battery_stored_power_W: float
    battery_removed_power_W: float
    curtailment_W: float
    unserved_housekeeping_W: float
    compute_denied_W: float
    charge_loss_W: float
    discharge_loss_W: float
    balance_residual_J: float
    valid: bool
    invalid_reason: str | None


def step_power_system(
    *,
    battery_energy_J: float,
    solar_generation_W: float,
    requested_compute_W: float,
    fdir_limit_W: float,
    dt_s: float,
    params: PowerParameters = DEFAULT_POWER_PARAMETERS,
) -> PowerStepResult:
    """Advance one interval with housekeeping priority and explicit losses."""

    params.validate()
    values = (battery_energy_J, solar_generation_W, requested_compute_W, dt_s)
    if any(not math.isfinite(v) for v in values) or dt_s <= 0.0:
        raise ValueError("power step inputs must be finite and dt_s positive")
    if not (math.isfinite(fdir_limit_W) or fdir_limit_W == math.inf):
        raise ValueError("FDIR limit must be finite or positive infinity")
    if solar_generation_W < 0.0 or requested_compute_W < 0.0 or fdir_limit_W < 0.0:
        raise ValueError("power step inputs must be non-negative")
    eps = 1e-9
    if not (params.minimum_energy_J - eps <= battery_energy_J <= params.maximum_energy_J + eps):
        raise ValueError("battery state is outside declared SOC bounds")

    available_internal_J = max(0.0, battery_energy_J - params.minimum_energy_J)
    available_discharge_bus_W = min(
        params.maximum_discharge_power_W,
        available_internal_J * params.discharge_efficiency / dt_s,
    )
    total_bus_available_W = solar_generation_W + available_discharge_bus_W
    unserved_housekeeping_W = max(0.0, params.housekeeping_power_W - total_bus_available_W)
    valid = unserved_housekeeping_W <= eps
    invalid_reason = None if valid else SYSTEM_POWER_DEFICIT
    compute_supply_after_house_W = max(0.0, total_bus_available_W - params.housekeeping_power_W)
    power_feasible_compute_W = min(params.compute_design_power_W, compute_supply_after_house_W)
    if valid:
        executed = min(
            requested_compute_W, power_feasible_compute_W,
            fdir_limit_W, params.compute_design_power_W,
        )
    else:
        executed = 0.0

    actual_bus_load_W = params.housekeeping_power_W + executed if valid else min(
        params.housekeeping_power_W, total_bus_available_W
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
    # solar + initial storage - final storage = served load + losses + curtailment
    lhs_J = solar_generation_W * dt_s + battery_energy_J - next_energy
    rhs_J = (
        actual_bus_load_W + charge_loss_W + discharge_loss_W + curtailment_W
    ) * dt_s
    residual_J = lhs_J - rhs_J
    return PowerStepResult(
        next_battery_energy_J=next_energy,
        power_feasible_compute_W=power_feasible_compute_W,
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


__all__ = [
    "DEFAULT_POWER_PARAMETERS", "PowerParameters", "PowerStepResult",
    "SYSTEM_POWER_DEFICIT", "step_power_system",
]
