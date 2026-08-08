"""Direct bridge to the frozen canonical v0.4.4 Numba integration kernel."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import platform
import sys
import time

import numba
import numpy as np

from src.octm.adapters.v044 import CANONICAL_SOURCE_SHA256, canonical_source_hashes
from src.octm.baselines.v044 import thermal_model as canonical


@dataclass(frozen=True, slots=True)
class ThermalBridgeResult:
    node_temperature_K: np.ndarray
    radiator_temperature_K: np.ndarray
    executed_compute_power_W: np.ndarray
    thermal_energy_balance_residual_J: float
    physical_realization_sha256: str


def _kernel_args(power: np.ndarray, flux: np.ndarray, dt_s: float, tn0: float, tr0: float):
    p = canonical.P
    return (
        power, flux, float(dt_s), float(p["C_node"]), float(p["C_rad"]),
        float(p["UA_loop"]), float(p["eps"]), float(p["A_rad"]),
        float(p["T_space"]), float(p["P_house"]), float(tn0), float(tr0),
        False, float(p["T_throttle"]), 0.0,
        float(p["shed_fraction"] * p["P_design"]), float(p["throttle_hysteresis_K"]),
    )


def _validate_trace(power_W: np.ndarray, flux_W_m2: np.ndarray, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
    power = np.ascontiguousarray(power_W, dtype=np.float64)
    flux = np.ascontiguousarray(flux_W_m2, dtype=np.float64)
    if power.ndim != 1 or power.size < 2 or flux.shape != power.shape:
        raise ValueError("thermal traces must be matching one-dimensional arrays with >=2 samples")
    if not np.all(np.isfinite(power)) or not np.all(np.isfinite(flux)):
        raise ValueError("thermal traces must be finite")
    if np.any(power < 0.0) or np.any(flux < 0.0) or not math.isfinite(dt_s) or dt_s <= 0.0:
        raise ValueError("thermal power/flux must be non-negative and dt positive")
    return power, flux


def _physical_hash(flux: np.ndarray, dt_s: float) -> str:
    payload = json.dumps(
        {"schema": "rsim-001.thermal-bridge.v1", "dt_s": dt_s,
         "samples": int(flux.size), "canonical_source_sha256": CANONICAL_SOURCE_SHA256},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload)
    digest.update(b"\x00")
    digest.update(np.asarray(flux, dtype="<f8").tobytes())
    return digest.hexdigest()


def thermal_residual_J(
    power_W: np.ndarray, flux_W_m2: np.ndarray,
    node_K: np.ndarray, radiator_K: np.ndarray, dt_s: float,
) -> float:
    """Cumulative residual over canonical state transitions (last sample is ZOH only)."""
    p = canonical.P
    tn = node_K[1:]
    tr = radiator_K[1:]
    d_stored = (
        p["C_node"] * (tn[1:] - tn[:-1])
        + p["C_rad"] * (tr[1:] - tr[:-1])
    )
    q_space = p["eps"] * canonical.SIGMA * p["A_rad"] * (
        tr[:-1] ** 4 - p["T_space"] ** 4
    )
    net = (
        power_W[:-1] + p["P_house"] + flux_W_m2[:-1] * p["A_rad"] - q_space
    ) * dt_s
    return float(math.fsum(float(v) for v in (d_stored - net)))


def run_trace(
    power_W: np.ndarray,
    flux_W_m2: np.ndarray,
    *,
    dt_s: float = 1.0,
    initial_node_temperature_K: float | None = None,
    initial_radiator_temperature_K: float | None = None,
) -> ThermalBridgeResult:
    """Run one monolithic call to the unchanged frozen kernel."""
    canonical_source_hashes()
    power, flux = _validate_trace(power_W, flux_W_m2, dt_s)
    p = canonical.P
    tn0 = p["Tn0"] if initial_node_temperature_K is None else initial_node_temperature_K
    tr0 = p["Tr0"] if initial_radiator_temperature_K is None else initial_radiator_temperature_K
    tn, tr, executed = canonical._integrate_kernel(*_kernel_args(power, flux, dt_s, tn0, tr0))
    node = np.concatenate(([tn[0]], np.asarray(tn, dtype=np.float64)))
    radiator = np.concatenate(([tr[0]], np.asarray(tr, dtype=np.float64)))
    return ThermalBridgeResult(
        node_temperature_K=node,
        radiator_temperature_K=radiator,
        executed_compute_power_W=np.asarray(executed, dtype=np.float64),
        thermal_energy_balance_residual_J=thermal_residual_J(power, flux, node, radiator, dt_s),
        physical_realization_sha256=_physical_hash(flux, dt_s),
    )


def one_step(
    requested_power_W: float, flux_W_m2: float, node_K: float, radiator_K: float,
    *, dt_s: float = 1.0,
) -> tuple[float, float]:
    power = np.array([requested_power_W, requested_power_W], dtype=np.float64)
    flux = np.array([flux_W_m2, flux_W_m2], dtype=np.float64)
    tn, tr, _ = canonical._integrate_kernel(*_kernel_args(power, flux, dt_s, node_K, radiator_K))
    return float(tn[1]), float(tr[1])


def repeated_trace(
    power_W: np.ndarray, flux_W_m2: np.ndarray, *, dt_s: float = 1.0,
) -> ThermalBridgeResult:
    """Run the coupled-simulation bridge as repeated frozen-kernel calls."""
    canonical_source_hashes()
    power, flux = _validate_trace(power_W, flux_W_m2, dt_s)
    p = canonical.P
    tn = np.empty(power.size, dtype=np.float64)
    tr = np.empty(power.size, dtype=np.float64)
    tn[0], tr[0] = p["Tn0"], p["Tr0"]
    for i in range(power.size - 1):
        tn[i + 1], tr[i + 1] = one_step(power[i], flux[i], tn[i], tr[i], dt_s=dt_s)
    node = np.concatenate(([tn[0]], tn))
    radiator = np.concatenate(([tr[0]], tr))
    return ThermalBridgeResult(
        node_temperature_K=node,
        radiator_temperature_K=radiator,
        executed_compute_power_W=np.asarray(power, dtype=np.float64).copy(),
        thermal_energy_balance_residual_J=thermal_residual_J(power, flux, node, radiator, dt_s),
        physical_realization_sha256=_physical_hash(flux, dt_s),
    )


def benchmark_bridge(*, intervals: int = 10_000, repeats: int = 5) -> dict[str, object]:
    """Equivalence/performance gate for the intended CLOSED_LOOP bridge."""
    if intervals < 10_000 or repeats < 1:
        raise ValueError("benchmark requires at least 10,000 intervals and one repeat")
    n = intervals + 1
    t = np.arange(n, dtype=np.float64)
    power = 30_000.0 + 4_000.0 * np.sin(2.0 * math.pi * t / 1_800.0)
    flux = 99.45 + 68.05 * ((t % 5_738.992815014798) < 3_602.3036663608896)
    # Untimed JIT warm-up.
    warm_start = time.perf_counter()
    one_step(power[0], flux[0], canonical.P["Tn0"], canonical.P["Tr0"])
    warmup_s = time.perf_counter() - warm_start
    reference = run_trace(power, flux)
    repeated = repeated_trace(power, flux)
    node_error = float(np.max(np.abs(reference.node_temperature_K - repeated.node_temperature_K)))
    radiator_error = float(np.max(np.abs(reference.radiator_temperature_K - repeated.radiator_temperature_K)))
    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        repeated_trace(power, flux)
        timings.append(time.perf_counter() - started)
    median_s = float(np.median(np.asarray(timings)))
    projected_s = median_s * (5_184_000 / intervals)
    equivalence_pass = node_error <= 1e-10 and radiator_error <= 1e-10
    performance_pass = projected_s <= 600.0
    return {
        "artifact_type": "rsim_001_thermal_bridge_benchmark",
        "intervals_per_trial": intervals,
        "repeats": repeats,
        "timings_s": timings,
        "median_10000_interval_time_s": median_s,
        "projected_closed_loop_intervals": 5_184_000,
        "projected_closed_loop_kernel_time_s": projected_s,
        "performance_limit_s": 600.0,
        "max_node_temperature_error_K": node_error,
        "max_radiator_temperature_error_K": radiator_error,
        "equivalence_tolerance_K": 1e-10,
        "equivalence_status": "PASS" if equivalence_pass else "FAIL",
        "performance_status": "PASS" if performance_pass else "FAIL",
        "status": "PASS" if equivalence_pass and performance_pass else "FAIL",
        "jit_warmup_s": warmup_s,
        "environment": {
            "python": sys.version.split()[0], "numpy": np.__version__,
            "numba": numba.__version__, "platform": platform.platform(),
        },
    }


__all__ = [
    "ThermalBridgeResult", "benchmark_bridge", "one_step", "repeated_trace",
    "run_trace", "thermal_residual_J",
]
