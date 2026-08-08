"""Scientific and provenance tests for the canonical v0.4.4 adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.octm.adapters.v044 import (
    CANONICAL_SOURCE_SHA256,
    DEFAULT_PARAMETERS,
    canonical,
    canonical_source_hashes,
    measurement_step_mask,
    orbital_environment,
    simulate_thermal,
)
from verify_baseline_v044 import verify


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
    phase_power_W = np.where(hot_mask, params.compute_design_power_W, cold_power_W)
    return step_time_s, environment, phase_power_W


def test_canonical_source_hashes_and_import_path() -> None:
    assert canonical_source_hashes() == CANONICAL_SOURCE_SHA256
    module_path = Path(canonical.__file__).resolve().as_posix()
    assert module_path.endswith("src/octm/baselines/v044/thermal_model.py")
    assert "legacy/reconstructed_v044" not in module_path


def test_canonical_authoritative_pipeline_reproduces_scientific_result() -> None:
    result = verify()
    assert result["status"] == "PASS"
    assert result["numerical_comparison"]["scientific_semantic_equal"] is True
    assert result["numerical_comparison"]["max_absolute_numeric_difference"] == 0.0
    assert result["manifest_coverage"]["available_entries_all_match"] is True


def test_fixed_forcing_reproduces_published_v044_convergence_row() -> None:
    params = DEFAULT_PARAMETERS
    step_time_s, environment, phase_power_W = _deterministic_release_forcing()
    flat_power_W = np.full(
        phase_power_W.shape, params.diversified_average_compute_power_W, dtype=np.float64
    )
    nominal = simulate_thermal(flat_power_W, environment, params=params)
    phase = simulate_thermal(phase_power_W, environment, params=params)
    measure = measurement_step_mask(step_time_s, params=params)

    nominal_peak_C = float(np.max(nominal.node_temperature_K[1:][measure]) - 273.15)
    phase_peak_C = float(np.max(phase.node_temperature_K[1:][measure]) - 273.15)

    assert nominal_peak_C == pytest.approx(50.986481, abs=5e-7)
    assert phase_peak_C == pytest.approx(68.439837, abs=5e-7)
    assert phase_peak_C - nominal_peak_C == pytest.approx(17.453355, abs=5e-7)


def test_physical_realization_hash_excludes_workload() -> None:
    times = np.arange(3, dtype=np.float64)
    environment, _ = orbital_environment(times)
    first = simulate_thermal(np.array([1.0, 2.0, 3.0]), environment)
    paired = simulate_thermal(np.array([3.0, 2.0, 1.0]), environment)
    assert first.physical_realization_sha256 == paired.physical_realization_sha256
    assert first.metadata["canonical_module"].endswith("v044.thermal_model")


@pytest.mark.parametrize(
    ("power", "environment", "message"),
    [
        ([1.0], [1.0, 2.0], "lengths must match"),
        ([1.0, np.nan], [150.0, 150.0], "finite"),
        ([[1.0]], [150.0], "one-dimensional"),
    ],
)
def test_forcing_validation(power: object, environment: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simulate_thermal(power, environment)


def test_noncanonical_environment_is_rejected() -> None:
    with pytest.raises(ValueError, match="canonical v0.4.4 forcing"):
        simulate_thermal(np.ones(3), np.array([150.0, 40.0, 40.0]))
