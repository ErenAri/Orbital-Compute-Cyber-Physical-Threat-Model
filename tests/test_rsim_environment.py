from __future__ import annotations

import math

import numpy as np

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
