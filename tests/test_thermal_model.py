"""Scientific regression tests for the reconstructed TSM-01 plant."""

from __future__ import annotations

import numpy as np
import pytest

from thermal_model import (
    DEFAULT_PARAMETERS,
    measurement_step_mask,
    orbital_environment,
    simulate_thermal,
)


def _deterministic_release_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    params = DEFAULT_PARAMETERS
    n_steps = int(
        (params.warmup_orbits + params.measurement_orbits)
        * params.orbit_period_s
        / params.release_dt_s
    )
    step_time_s = np.arange(n_steps, dtype=np.float64) * params.release_dt_s
    environment, hot_mask = orbital_environment(step_time_s, params)
    cold_power_W = (
        params.diversified_average_compute_power_W
        - params.hot_fraction * params.compute_design_power_W
    ) / (1.0 - params.hot_fraction)
    phase_power_W = np.where(
        hot_mask,
        params.compute_design_power_W,
        cold_power_W,
    )
    return step_time_s, environment, phase_power_W


def test_fixed_forcing_reproduces_published_v044_convergence_row() -> None:
    """The retained deterministic dt=1 row anchors equation reconstruction."""

    params = DEFAULT_PARAMETERS
    step_time_s, environment, phase_power_W = _deterministic_release_forcing()
    flat_power_W = np.full(
        phase_power_W.shape,
        params.diversified_average_compute_power_W,
        dtype=np.float64,
    )
    nominal = simulate_thermal(flat_power_W, environment, params=params)
    phase = simulate_thermal(phase_power_W, environment, params=params)
    measure = measurement_step_mask(step_time_s, params=params)

    nominal_peak_C = float(np.max(nominal.node_temperature_K[1:][measure]) - 273.15)
    phase_peak_C = float(np.max(phase.node_temperature_K[1:][measure]) - 273.15)

    assert nominal_peak_C == pytest.approx(50.986481, abs=5e-7)
    assert phase_peak_C == pytest.approx(68.439837, abs=5e-7)
    assert phase_peak_C - nominal_peak_C == pytest.approx(17.453355, abs=5e-7)


def test_physical_realization_hash_excludes_workload_but_covers_environment() -> None:
    environment = np.array([150.0, 150.0, 40.0])
    first = simulate_thermal(np.array([1.0, 2.0, 3.0]), environment)
    paired = simulate_thermal(np.array([3.0, 2.0, 1.0]), environment)
    changed_environment = simulate_thermal(
        np.array([1.0, 2.0, 3.0]), np.array([150.0, 40.0, 40.0])
    )

    assert first.physical_realization_sha256 == paired.physical_realization_sha256
    assert (
        first.physical_realization_sha256
        != changed_environment.physical_realization_sha256
    )


@pytest.mark.parametrize(
    ("power", "environment", "message"),
    [
        ([1.0], [1.0, 2.0], "equal length"),
        ([1.0, np.nan], [1.0, 2.0], "finite"),
        ([[1.0]], [1.0], "one-dimensional"),
    ],
)
def test_forcing_validation(power: object, environment: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simulate_thermal(power, environment)
