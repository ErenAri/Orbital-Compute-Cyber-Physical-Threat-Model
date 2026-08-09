from __future__ import annotations

import math

import numpy as np
import pytest

from rsim_001_campaign import canonical_grid, e0_mode_a_regression, generate_seed_workloads
from src.octm.rsim.cosim import POWER_CONSTRAINED, simulate
from src.octm.rsim.environment import (
    DEFAULT_E1,
    E0_CANONICAL,
    E1_REPRESENTATIVE_ANALYTIC_LEO,
    generate_environment,
)
from src.octm.rsim.power import DEFAULT_POWER_PARAMETERS
from src.octm.rsim.reserve import (
    ESSENTIAL_RESERVE_INFEASIBLE,
    EssentialReserveInfeasibleError,
    build_reserve_profile,
    require_feasible_reserve,
    step_reserve_aware_power_system,
    time_until_next_generation,
)


def _extended_environment(environment_id: str, horizon: int = 43_200):
    period = 5_400.0 if environment_id == E0_CANONICAL else DEFAULT_E1.period_s
    extended_time = np.arange(horizon + math.ceil(period) + 2, dtype=np.float64)
    extended = generate_environment(environment_id, extended_time)
    base = generate_environment(environment_id, extended_time[:horizon])
    lookahead = time_until_next_generation(
        extended.solar_generation_W, horizon_length=horizon, dt_s=1.0
    )
    return base, lookahead, extended


def test_full_battery_eclipse_reserve_equals_housekeeping_requirement() -> None:
    p = DEFAULT_POWER_PARAMETERS
    lookahead_s = 1_234.0
    step = step_reserve_aware_power_system(
        battery_energy_J=p.maximum_energy_J,
        solar_generation_W=0.0,
        requested_compute_W=0.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=lookahead_s,
        dt_s=1.0,
    )
    assert step.essential_reserve_J == p.housekeeping_power_W * lookahead_s / p.discharge_efficiency


def test_reserve_decreases_monotonically_toward_eclipse_end() -> None:
    profile = build_reserve_profile(np.arange(100.0, -1.0, -1.0))
    assert np.all(np.diff(profile.essential_reserve_J) <= 0.0)
    assert profile.essential_reserve_J[-1] == 0.0


def test_compute_cannot_consume_protected_housekeeping_reserve() -> None:
    p = DEFAULT_POWER_PARAMETERS
    lookahead_s = 100.0
    protected = p.minimum_energy_J + p.housekeeping_power_W * lookahead_s / p.discharge_efficiency
    step = step_reserve_aware_power_system(
        battery_energy_J=protected,
        solar_generation_W=0.0,
        requested_compute_W=40_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=lookahead_s,
        dt_s=1.0,
    )
    assert step.power.valid
    assert step.power.executed_compute_W == 0.0
    assert step.reserve_denied_compute_W == 40_000.0
    assert step.power.unserved_housekeeping_W == 0.0
    next_protected = p.minimum_energy_J + p.housekeeping_power_W * (lookahead_s - 1.0) / p.discharge_efficiency
    assert step.power.next_battery_energy_J == pytest.approx(next_protected)


def test_housekeeping_remains_supplied_when_compute_is_denied() -> None:
    p = DEFAULT_POWER_PARAMETERS
    protected = p.minimum_energy_J + p.housekeeping_power_W * 10.0 / p.discharge_efficiency
    step = step_reserve_aware_power_system(
        battery_energy_J=protected,
        solar_generation_W=0.0,
        requested_compute_W=40_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=10.0,
        dt_s=1.0,
    )
    assert step.power.unserved_housekeeping_W == 0.0
    assert step.power.executed_compute_W == 0.0


def test_reserve_admission_is_workload_identity_independent() -> None:
    p = DEFAULT_POWER_PARAMETERS
    arguments = dict(
        battery_energy_J=p.minimum_energy_J + 5_000_000.0,
        solar_generation_W=0.0,
        requested_compute_W=30_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=500.0,
        dt_s=1.0,
    )
    w0_state = step_reserve_aware_power_system(**arguments)
    w5_state = step_reserve_aware_power_system(**arguments)
    assert w0_state == w5_state


def test_identical_w0_w5_electrical_states_have_identical_admission_limits() -> None:
    p = DEFAULT_POWER_PARAMETERS
    arguments = dict(
        battery_energy_J=p.initial_energy_J,
        solar_generation_W=0.0,
        requested_compute_W=30_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=1_000.0,
        dt_s=1.0,
    )
    w0 = step_reserve_aware_power_system(**arguments)
    w5 = step_reserve_aware_power_system(**arguments)
    assert w0.power.power_feasible_compute_W == w5.power.power_feasible_compute_W
    assert w0.power.executed_compute_W == w5.power.executed_compute_W
    assert w0.power.executed_compute_W <= arguments["requested_compute_W"]


def test_reserve_step_conserves_energy_and_never_creates_it() -> None:
    p = DEFAULT_POWER_PARAMETERS
    step = step_reserve_aware_power_system(
        battery_energy_J=p.initial_energy_J,
        solar_generation_W=0.0,
        requested_compute_W=40_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=1_000.0,
        dt_s=1.0,
    )
    assert abs(step.power.balance_residual_J) < 1e-6
    assert step.power.next_battery_energy_J <= p.initial_energy_J
    assert p.minimum_energy_J <= step.power.next_battery_energy_J <= p.maximum_energy_J
    assert step.power.executed_compute_W <= 40_000.0


def test_reserve_partial_execution_never_exceeds_request() -> None:
    p = DEFAULT_POWER_PARAMETERS
    step = step_reserve_aware_power_system(
        battery_energy_J=p.minimum_energy_J,
        solar_generation_W=10_000.0,
        requested_compute_W=40_000.0,
        fdir_limit_W=math.inf,
        time_until_next_generation_s=0.0,
        dt_s=1.0,
    )
    assert step.power.valid
    assert step.power.executed_compute_W == 8_000.0
    assert step.power.executed_compute_W <= 40_000.0


def test_reserve_infeasible_architecture_fails_explicitly() -> None:
    profile = build_reserve_profile(np.array([100_000.0]))
    assert profile.architecture_condition == ESSENTIAL_RESERVE_INFEASIBLE
    with pytest.raises(EssentialReserveInfeasibleError, match=ESSENTIAL_RESERVE_INFEASIBLE):
        require_feasible_reserve(profile)


@pytest.mark.parametrize("environment_id", [E0_CANONICAL, E1_REPRESENTATIVE_ANALYTIC_LEO])
def test_environment_generation_transition_resets_lookahead(environment_id: str) -> None:
    _, lookahead, extended = _extended_environment(environment_id, horizon=10_800)
    rising = np.flatnonzero(
        (~extended.illumination[:-1]) & extended.illumination[1:]
    ) + 1
    transition = int(rising[rising < lookahead.size][0])
    assert lookahead[transition] == 0.0
    assert lookahead[transition - 1] == 1.0


@pytest.mark.parametrize("environment_id", [E0_CANONICAL, E1_REPRESENTATIVE_ANALYTIC_LEO])
def test_reserve_cosimulation_invariants(environment_id: str) -> None:
    environment, lookahead, _ = _extended_environment(environment_id)
    workload = generate_seed_workloads(0)["constant_reference"]
    result = simulate(
        workload.power_W,
        environment,
        mode=POWER_CONSTRAINED,
        reserve_time_until_next_generation_s=lookahead,
    )
    assert result.valid_run
    assert result.invariant_results["electrical_balance_closes"]
    assert result.invariant_results["soc_within_bounds"]
    assert result.invariant_results["housekeeping_priority"]
    assert result.invariant_results["compute_denial_attribution_closes"]
    assert np.all(result.executed_compute_W <= result.requested_compute_W + 1e-9)
    assert result.battery_SOC is not None
    assert np.min(result.battery_SOC) >= DEFAULT_POWER_PARAMETERS.minimum_SOC - 1e-12


def test_canonical_thermal_wrb_regression_is_unchanged() -> None:
    assert e0_mode_a_regression(seeds=(0,))["status"] == "PASS"
