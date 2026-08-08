from __future__ import annotations

import numpy as np

from src.octm.rsim.thermal_bridge import repeated_trace, run_trace


def test_repeated_frozen_kernel_bridge_matches_monolithic_call() -> None:
    n = 1_001
    t = np.arange(n, dtype=float)
    power = 30_000.0 + 5_000.0 * np.sin(2.0 * np.pi * t / 173.0)
    flux = 100.0 + 50.0 * ((t % 500.0) < 310.0)
    reference = run_trace(power, flux)
    repeated = repeated_trace(power, flux)
    assert np.max(np.abs(reference.node_temperature_K - repeated.node_temperature_K)) <= 1e-10
    assert np.max(np.abs(reference.radiator_temperature_K - repeated.radiator_temperature_K)) <= 1e-10
