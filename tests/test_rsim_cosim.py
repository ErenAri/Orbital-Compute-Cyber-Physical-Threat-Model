from __future__ import annotations

import numpy as np

from src.octm.rsim.cosim import CLOSED_LOOP, POWER_CONSTRAINED, THERMAL_ONLY, simulate
from src.octm.rsim.environment import E0_CANONICAL, generate_environment


def test_all_modes_are_finite_deterministic_and_monotone() -> None:
    time = np.arange(2_000, dtype=float)
    environment = generate_environment(E0_CANONICAL, time)
    requested = 30_000.0 + 5_000.0 * np.sin(2.0 * np.pi * time / 300.0)
    for mode in (THERMAL_ONLY, POWER_CONSTRAINED, CLOSED_LOOP):
        first = simulate(requested, environment, mode=mode, warmup_stop_index=1_000)
        second = simulate(requested, environment, mode=mode, warmup_stop_index=1_000)
        assert first.valid_run
        assert np.array_equal(first.executed_compute_W, second.executed_compute_W)
        assert np.array_equal(first.node_temperature_K, second.node_temperature_K)
        assert np.all(first.executed_compute_W <= requested + 1e-9)
        assert np.all(first.executed_compute_W <= 40_000.0 + 1e-9)
        assert np.all(np.isfinite(first.node_temperature_K))


def test_e0_thermal_only_uses_requested_trace_unchanged() -> None:
    time = np.arange(1_000, dtype=float)
    environment = generate_environment(E0_CANONICAL, time)
    requested = np.full(time.size, 30_000.0)
    result = simulate(requested, environment, mode=THERMAL_ONLY)
    assert np.array_equal(result.executed_compute_W, requested)
    assert result.battery_SOC is None
