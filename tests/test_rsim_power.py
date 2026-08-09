from __future__ import annotations

import math

from src.octm.rsim.power import DEFAULT_POWER_PARAMETERS, SYSTEM_POWER_DEFICIT, step_power_system


def test_charge_and_discharge_balance_and_direction() -> None:
    p = DEFAULT_POWER_PARAMETERS
    charge = step_power_system(
        battery_energy_J=0.5 * p.battery_energy_capacity_J,
        solar_generation_W=50_000.0, requested_compute_W=10_000.0,
        fdir_limit_W=math.inf, dt_s=1.0,
    )
    assert charge.battery_charge_bus_W > 0.0
    assert charge.next_battery_energy_J > 0.5 * p.battery_energy_capacity_J
    assert abs(charge.balance_residual_J) < 1e-6
    discharge = step_power_system(
        battery_energy_J=0.5 * p.battery_energy_capacity_J,
        solar_generation_W=0.0, requested_compute_W=30_000.0,
        fdir_limit_W=math.inf, dt_s=1.0,
    )
    assert discharge.battery_discharge_bus_W == 32_000.0
    assert discharge.next_battery_energy_J < 0.5 * p.battery_energy_capacity_J
    assert abs(discharge.balance_residual_J) < 1e-6


def test_housekeeping_priority_and_explicit_deficit() -> None:
    p = DEFAULT_POWER_PARAMETERS
    at_minimum = p.minimum_energy_J
    result = step_power_system(
        battery_energy_J=at_minimum, solar_generation_W=1_000.0,
        requested_compute_W=40_000.0, fdir_limit_W=math.inf, dt_s=1.0,
    )
    assert not result.valid
    assert result.invalid_reason == SYSTEM_POWER_DEFICIT
    assert result.executed_compute_W == 0.0
    assert result.unserved_housekeeping_W == 1_000.0


def test_power_admission_never_exceeds_request_or_design() -> None:
    p = DEFAULT_POWER_PARAMETERS
    result = step_power_system(
        battery_energy_J=p.initial_energy_J, solar_generation_W=0.0,
        requested_compute_W=8_000.0, fdir_limit_W=12_000.0, dt_s=1.0,
    )
    assert result.executed_compute_W == 8_000.0
    assert result.executed_compute_W <= result.power_feasible_compute_W
