from __future__ import annotations

import math

import numpy as np
import pytest

from src.octm.rsim.environment import (
    DEFAULT_E1, E0_CANONICAL, E1_REPRESENTATIVE_ANALYTIC_LEO, generate_environment,
)


def test_frozen_e1_geometry_and_component_values() -> None:
    assert DEFAULT_E1.period_s == 5738.992815014798
    assert DEFAULT_E1.eclipse_duration_s == 2136.6891486539084
    assert DEFAULT_E1.sunlit_fraction == 0.6276891751695983
    time = np.arange(43_200, dtype=float)
    trace = generate_environment(E1_REPRESENTATIVE_ANALYTIC_LEO, time)
    assert np.all(np.isfinite(trace.absorbed_flux_W_m2))
    assert float(trace.direct_solar_W_m2.max()) == 68.05
    assert math.isclose(float(trace.albedo_W_m2.max()), 40.0134, abs_tol=1e-12)
    assert np.all(trace.earth_IR_W_m2 == 99.45)
    assert float(trace.absorbed_flux_W_m2.min()) == 99.45
    assert float(trace.absorbed_flux_W_m2.max()) <= 207.5134 + 1e-12
    assert trace.metadata["not_tuned_to_E0"] is True


def test_e0_is_exact_canonical_square_wave() -> None:
    trace = generate_environment(E0_CANONICAL, np.arange(10_800, dtype=float))
    assert set(np.unique(trace.absorbed_flux_W_m2)) == {40.0, 150.0}
    assert trace.period_s == 5400.0
    assert np.array_equal(trace.illumination, trace.hot_mask)


def test_array_and_radiator_orientation_are_distinct() -> None:
    assert DEFAULT_E1.solar_array_incidence_factor == 1.0
    assert DEFAULT_E1.radiator_solar_incidence_factor == 0.25
    assert DEFAULT_E1.radiator_solar_absorptivity != DEFAULT_E1.radiator_IR_absorptivity


def test_e1_zero_and_unit_phase_offsets_are_exactly_equivalent() -> None:
    time = np.arange(43_200, dtype=np.float64)
    historical = generate_environment(E1_REPRESENTATIVE_ANALYTIC_LEO, time)
    zero = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO, time, phase_offset_fraction=0.0
    )
    unit = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO, time, phase_offset_fraction=1.0
    )
    for name in (
        "illumination", "direct_solar_W_m2", "albedo_W_m2",
        "earth_IR_W_m2", "absorbed_flux_W_m2", "solar_generation_W",
    ):
        assert np.array_equal(getattr(historical, name), getattr(zero, name))
        assert np.array_equal(getattr(historical, name), getattr(unit, name))
    assert historical.physical_realization_sha256 == zero.physical_realization_sha256
    assert historical.physical_realization_sha256 == unit.physical_realization_sha256


def test_e1_phase_offset_shifts_all_geometry_consistently() -> None:
    time = np.arange(5_000, dtype=np.float64)
    offset = 0.125
    shifted = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO, time, phase_offset_fraction=offset
    )
    translated = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO,
        time + offset * DEFAULT_E1.period_s,
    )
    assert np.array_equal(shifted.illumination, translated.illumination)
    for name in (
        "direct_solar_W_m2", "albedo_W_m2", "earth_IR_W_m2",
        "absorbed_flux_W_m2", "solar_generation_W",
    ):
        assert np.allclose(getattr(shifted, name), getattr(translated, name), atol=1e-12, rtol=0.0)


def test_phase_offset_is_rejected_for_e0() -> None:
    with pytest.raises(ValueError, match="defined for E1 only"):
        generate_environment(
            E0_CANONICAL, np.arange(10, dtype=np.float64),
            phase_offset_fraction=0.125,
        )


@pytest.mark.parametrize("offset", np.arange(8, dtype=float) / 8.0)
def test_e1_component_bounds_and_declared_eclipse_duration_are_phase_invariant(offset: float) -> None:
    time = np.arange(math.ceil(DEFAULT_E1.period_s), dtype=np.float64)
    trace = generate_environment(
        E1_REPRESENTATIVE_ANALYTIC_LEO, time,
        phase_offset_fraction=float(offset),
    )
    assert trace.metadata["eclipse_duration_s"] == DEFAULT_E1.eclipse_duration_s
    assert np.all((trace.direct_solar_W_m2 >= 0.0) & (trace.direct_solar_W_m2 <= 68.05))
    assert np.all((trace.albedo_W_m2 >= 0.0) & (trace.albedo_W_m2 <= 40.0134 + 1e-12))
    assert np.all(trace.earth_IR_W_m2 == 99.45)
    assert np.all((trace.absorbed_flux_W_m2 >= 99.45) & (trace.absorbed_flux_W_m2 <= 207.5134 + 1e-12))
    assert set(np.unique(trace.solar_generation_W)).issubset({0.0, DEFAULT_E1.solar_bus_power_W})
