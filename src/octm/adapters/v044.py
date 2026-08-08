"""WRB-001 adapter for the canonical, frozen OCTM/TSM-01 v0.4.4 model.

This module translates array-oriented WRB inputs into calls to the historical
``thermal_model.py`` API.  It does not duplicate or change the thermal
equations, parameters, environmental forcing, or Forward-Euler integration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.octm.baselines.v044 import thermal_model as canonical


MODEL_VERSION = "TSM-01-v0.4.4-canonical"
BASELINE_DIRECTORY = Path(canonical.__file__).resolve().parent
CANONICAL_SOURCE_SHA256 = {
    "thermal_model.py": "aec89d61be31c21a269dafcdb318dba4c72cf10037760dff489530f3f3591309",
    "run_all_v044.py": "78107b40e6dc155903c0d86d09c1af4027210cbda889debbb44c92154da99fec",
    "plot_results.py": "a2eb39aaa71da326b5c02196d58ba84f7d3865520ffabaf417d3672d6ba6dbf7",
    "requirements.txt": "f63cc3a968d2d6507e81cf710f8b20cb59a2445d6b4ab63c3d955ed6e39d193c",
    "README.md": "d0a27752c1ec5f86e054469267af43e552145131de5144d06780e3cc59fe1675",
}


@dataclass(frozen=True, slots=True)
class ThermalParameters:
    node_heat_capacity_J_K: float = float(canonical.P["C_node"])
    radiator_heat_capacity_J_K: float = float(canonical.P["C_rad"])
    loop_conductance_W_K: float = float(canonical.P["UA_loop"])
    radiator_area_m2: float = float(canonical.P["A_rad"])
    radiator_emissivity: float = float(canonical.P["eps"])
    housekeeping_power_W: float = float(canonical.P["P_house"])
    space_sink_temperature_K: float = float(canonical.P["T_space"])
    stefan_boltzmann_W_m2_K4: float = float(canonical.SIGMA)
    orbit_period_s: float = float(canonical.P["period"])
    hot_fraction: float = float(canonical.P["sunlit_frac"])
    environmental_flux_hot_W_m2: float = float(canonical.P["q_hot"])
    environmental_flux_cold_W_m2: float = float(canonical.P["q_cold"])
    initial_node_temperature_K: float = float(canonical.P["Tn0"])
    initial_radiator_temperature_K: float = float(canonical.P["Tr0"])
    release_dt_s: float = 1.0
    warmup_orbits: int = 2
    measurement_orbits: int = 6
    diversified_average_compute_power_W: float = float(canonical.P["P_avg"])
    compute_design_power_W: float = float(canonical.P["P_design"])
    throttle_threshold_K: float = float(canonical.P["T_throttle"])
    model_hazard_threshold_K: float = float(canonical.P["T_model_hazard"])

    def canonical_dict(self) -> dict[str, float]:
        """Return a fresh canonical parameter dictionary for the source API."""

        p = dict(canonical.P)
        p.update(
            A_rad=self.radiator_area_m2,
            eps=self.radiator_emissivity,
            C_node=self.node_heat_capacity_J_K,
            C_rad=self.radiator_heat_capacity_J_K,
            UA_loop=self.loop_conductance_W_K,
            P_house=self.housekeeping_power_W,
            P_design=self.compute_design_power_W,
            P_avg=self.diversified_average_compute_power_W,
            T_space=self.space_sink_temperature_K,
            q_hot=self.environmental_flux_hot_W_m2,
            q_cold=self.environmental_flux_cold_W_m2,
            T_throttle=self.throttle_threshold_K,
            T_model_hazard=self.model_hazard_threshold_K,
            period=self.orbit_period_s,
            sunlit_frac=self.hot_fraction,
            Tn0=self.initial_node_temperature_K,
            Tr0=self.initial_radiator_temperature_K,
        )
        return p


DEFAULT_PARAMETERS = ThermalParameters()


@dataclass(frozen=True, slots=True)
class ThermalSimulationResult:
    time_s: np.ndarray
    node_temperature_K: np.ndarray
    radiator_temperature_K: np.ndarray
    compute_power_W: np.ndarray
    environmental_flux_W_m2: np.ndarray
    loop_heat_flow_W: np.ndarray
    radiator_rejection_W: np.ndarray
    absorbed_environmental_power_W: np.ndarray
    dt_s: float
    physical_realization_sha256: str
    metadata: Mapping[str, Any]

    @property
    def n_steps(self) -> int:
        return int(self.compute_power_W.size)

    @property
    def duration_s(self) -> float:
        return self.n_steps * self.dt_s


def _array(values: Any, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(array)) or np.any(array < 0.0):
        raise ValueError(f"{name} must contain finite non-negative values")
    return np.ascontiguousarray(array)


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.ascontiguousarray(values).copy()
    result.setflags(write=False)
    return result


def canonical_source_hashes() -> dict[str, str]:
    """Hash the ingested canonical sources and fail on provenance drift."""

    actual = {
        name: hashlib.sha256((BASELINE_DIRECTORY / name).read_bytes()).hexdigest()
        for name in CANONICAL_SOURCE_SHA256
    }
    mismatches = {
        name: {"expected": CANONICAL_SOURCE_SHA256[name], "actual": digest}
        for name, digest in actual.items()
        if digest != CANONICAL_SOURCE_SHA256[name]
    }
    if mismatches:
        raise RuntimeError(f"canonical v0.4.4 source drift: {mismatches}")
    return actual


def orbital_environment(
    time_s: Any, params: ThermalParameters = DEFAULT_PARAMETERS
) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(time_s, dtype=np.float64)
    if times.ndim != 1 or not np.all(np.isfinite(times)):
        raise ValueError("time_s must be a finite one-dimensional array")
    p = params.canonical_dict()
    return _readonly(np.asarray(canonical.env_flux(times, p), dtype=np.float64)), _readonly(
        np.asarray(canonical.in_hot_phase(times, p), dtype=bool)
    )


def measurement_step_mask(
    step_time_s: Any,
    *,
    params: ThermalParameters = DEFAULT_PARAMETERS,
    warmup_orbits: int | None = None,
    measurement_orbits: int | None = None,
    campaign_start_time_s: float = 0.0,
) -> np.ndarray:
    times = np.asarray(step_time_s, dtype=np.float64)
    if times.ndim != 1 or not np.all(np.isfinite(times)):
        raise ValueError("step_time_s must be a finite one-dimensional array")
    warmup = params.warmup_orbits if warmup_orbits is None else int(warmup_orbits)
    measure = params.measurement_orbits if measurement_orbits is None else int(measurement_orbits)
    if warmup < 0 or measure < 0:
        raise ValueError("orbit counts must be non-negative")
    elapsed = times - float(campaign_start_time_s)
    start = warmup * params.orbit_period_s
    stop = start + measure * params.orbit_period_s
    return _readonly((elapsed >= start) & (elapsed < stop))


def _physical_hash(
    flux: np.ndarray,
    *,
    params: ThermalParameters,
    dt_s: float,
    start_time_s: float,
) -> str:
    descriptor = {
        "schema": "octm.tsm01.canonical-v044.physical-realization.v1",
        "canonical_thermal_model_sha256": CANONICAL_SOURCE_SHA256["thermal_model.py"],
        "parameters": params.canonical_dict(),
        "n_steps": int(flux.size),
        "dt_s": float(dt_s),
        "start_time_s": float(start_time_s),
    }
    digest = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(b"\x00")
    digest.update(np.asarray(flux, dtype="<f8").tobytes(order="C"))
    return digest.hexdigest()


def simulate_thermal(
    compute_power_W: Any,
    environmental_flux_W_m2: Any,
    *,
    dt_s: float | None = None,
    params: ThermalParameters = DEFAULT_PARAMETERS,
    initial_node_temperature_K: float | None = None,
    initial_radiator_temperature_K: float | None = None,
    start_time_s: float = 0.0,
) -> ThermalSimulationResult:
    """Run the canonical v0.4.4 ``simulate`` function for an explicit trace."""

    canonical_source_hashes()
    power = _array(compute_power_W, "compute_power_W")
    flux = _array(environmental_flux_W_m2, "environmental_flux_W_m2")
    if power.shape != flux.shape:
        raise ValueError("compute power and environmental flux lengths must match")
    step = params.release_dt_s if dt_s is None else float(dt_s)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("dt_s must be finite and positive")
    if initial_node_temperature_K is not None or initial_radiator_temperature_K is not None:
        params = ThermalParameters(
            **{
                field: getattr(params, field)
                for field in params.__dataclass_fields__
                if field not in {"initial_node_temperature_K", "initial_radiator_temperature_K"}
            },
            initial_node_temperature_K=(
                params.initial_node_temperature_K
                if initial_node_temperature_K is None
                else float(initial_node_temperature_K)
            ),
            initial_radiator_temperature_K=(
                params.initial_radiator_temperature_K
                if initial_radiator_temperature_K is None
                else float(initial_radiator_temperature_K)
            ),
        )
    p = params.canonical_dict()
    step_time = float(start_time_s) + np.arange(power.size, dtype=np.float64) * step
    expected_flux = np.asarray(canonical.env_flux(step_time, p), dtype=np.float64)
    if not np.array_equal(flux, expected_flux):
        raise ValueError("environmental flux does not match canonical v0.4.4 forcing")

    load_fn = canonical.trace_load(power, step)
    simulation = canonical.simulate(
        load_fn,
        p,
        duration=float(power.size * step),
        dt=step,
        seed=0,
    )
    # The compatibility result retains the prior N+1 shape contract.  Index 1:
    # is exactly the canonical left-endpoint state array, with no re-integration.
    canonical_node = np.asarray(simulation["Tn"], dtype=np.float64)
    canonical_radiator = np.asarray(simulation["Tr"], dtype=np.float64)
    node = np.concatenate(([canonical_node[0]], canonical_node))
    radiator = np.concatenate(([canonical_radiator[0]], canonical_radiator))
    loop = p["UA_loop"] * (canonical_node - canonical_radiator)
    rejection = p["eps"] * canonical.SIGMA * p["A_rad"] * (
        canonical_radiator**4 - p["T_space"] ** 4
    )
    time = float(start_time_s) + np.arange(power.size + 1, dtype=np.float64) * step
    return ThermalSimulationResult(
        time_s=_readonly(time),
        node_temperature_K=_readonly(node),
        radiator_temperature_K=_readonly(radiator),
        compute_power_W=_readonly(np.asarray(simulation["P"], dtype=np.float64)),
        environmental_flux_W_m2=_readonly(flux),
        loop_heat_flow_W=_readonly(loop),
        radiator_rejection_W=_readonly(rejection),
        absorbed_environmental_power_W=_readonly(flux * p["A_rad"]),
        dt_s=step,
        physical_realization_sha256=_physical_hash(
            flux, params=params, dt_s=step, start_time_s=float(start_time_s)
        ),
        metadata={
            "model_version": MODEL_VERSION,
            "adapter": "src.octm.adapters.v044",
            "canonical_module": canonical.__name__,
            "canonical_thermal_model_sha256": CANONICAL_SOURCE_SHA256["thermal_model.py"],
            "state_alignment": "result[1:] equals canonical left-endpoint state array",
        },
    )


__all__ = [
    "BASELINE_DIRECTORY",
    "CANONICAL_SOURCE_SHA256",
    "DEFAULT_PARAMETERS",
    "MODEL_VERSION",
    "ThermalParameters",
    "ThermalSimulationResult",
    "canonical",
    "canonical_source_hashes",
    "measurement_step_mask",
    "orbital_environment",
    "simulate_thermal",
]
