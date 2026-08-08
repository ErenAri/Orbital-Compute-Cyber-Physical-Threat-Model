"""Deterministic reconstruction of the frozen OCTM TSM-01 thermal plant.

The authoritative v0.4.4 source archive is not present in this workspace.  This
module therefore reconstructs only the thermal plant described by the retained
v0.4.4 release artefacts; it does not attempt to recreate the historical random
workload generators.  The reconstructed equations are the standard two-node
lumped heat balances described in the release document::

    C_node dT_node/dt = P_compute + P_housekeeping
                         - UA (T_node - T_radiator)

    C_radiator dT_radiator/dt = UA (T_node - T_radiator)
                                + A q_environment
                                - eps sigma A (T_radiator**4 - T_space**4)

The input forcing sample at index ``i`` is held constant over
``[time_s[i], time_s[i + 1])`` and Forward Euler evaluates both heat balances
from the state at ``time_s[i]``.  This left-endpoint convention, the documented
Appendix A parameters, and a hot phase beginning at orbit phase zero reproduce
the published v0.4.4 deterministic fixed-forcing check at ``dt=1 s``:

* flat 30 kW peak: 50.986481 C;
* phase-shaped peak: 68.439837 C;
* peak difference: 17.453355 K.

That reproduction is evidence for the reconstructed plant and phase convention;
it is not evidence that the missing stochastic v0.4.4 implementation has been
recovered byte-for-byte.  All stochastic realisations are deliberately outside
this module.  The simulator consumes explicit arrays and never consults global
or hidden random state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

MODEL_VERSION = "TSM-01-v0.4.4-reconstructed-plant"
PHYSICAL_REALIZATION_HASH_SCHEMA = "octm.tsm01.physical-realization.v1"


def _finite_float(value: Any, name: str) -> float:
    """Return ``value`` as a finite float or raise a useful validation error."""

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real scalar") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class ThermalParameters:
    """Frozen TSM-01 v0.4.4 baseline parameters.

    Values are project assumptions from Appendix A, not flight-calibrated
    spacecraft properties.  Fields used only by experiment construction or
    reporting are kept alongside the plant parameters so callers do not need to
    duplicate baseline constants.  Only parameters that affect the plant are
    included in :meth:`evolution_parameters` and the physical-realisation hash.
    """

    node_heat_capacity_J_K: float = 3.6e5
    radiator_heat_capacity_J_K: float = 2.25e5
    loop_conductance_W_K: float = 3_000.0
    radiator_area_m2: float = 100.0
    radiator_emissivity: float = 0.85
    housekeeping_power_W: float = 2_000.0
    space_sink_temperature_K: float = 3.0
    stefan_boltzmann_W_m2_K4: float = 5.670374419e-8

    orbit_period_s: float = 5_400.0
    hot_fraction: float = 0.62
    environmental_flux_hot_W_m2: float = 150.0
    environmental_flux_cold_W_m2: float = 40.0

    initial_node_temperature_K: float = 320.0
    initial_radiator_temperature_K: float = 305.0
    release_dt_s: float = 1.0
    warmup_orbits: int = 2
    measurement_orbits: int = 6

    diversified_average_compute_power_W: float = 30_000.0
    compute_design_power_W: float = 40_000.0
    throttle_threshold_K: float = 348.15  # 75 C project-assumed threshold
    model_hazard_threshold_K: float = 363.15  # 90 C project-assumed threshold

    def __post_init__(self) -> None:
        positive_fields = (
            "node_heat_capacity_J_K",
            "radiator_heat_capacity_J_K",
            "loop_conductance_W_K",
            "radiator_area_m2",
            "space_sink_temperature_K",
            "stefan_boltzmann_W_m2_K4",
            "orbit_period_s",
            "initial_node_temperature_K",
            "initial_radiator_temperature_K",
            "release_dt_s",
            "diversified_average_compute_power_W",
            "compute_design_power_W",
            "throttle_threshold_K",
            "model_hazard_threshold_K",
        )
        nonnegative_fields = (
            "housekeeping_power_W",
            "environmental_flux_hot_W_m2",
            "environmental_flux_cold_W_m2",
        )

        for name in positive_fields:
            value = _finite_float(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)

        for name in nonnegative_fields:
            value = _finite_float(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)

        emissivity = _finite_float(self.radiator_emissivity, "radiator_emissivity")
        if not 0.0 <= emissivity <= 1.0:
            raise ValueError("radiator_emissivity must be in [0, 1]")
        object.__setattr__(self, "radiator_emissivity", emissivity)

        hot_fraction = _finite_float(self.hot_fraction, "hot_fraction")
        if not 0.0 <= hot_fraction <= 1.0:
            raise ValueError("hot_fraction must be in [0, 1]")
        object.__setattr__(self, "hot_fraction", hot_fraction)

        for name in ("warmup_orbits", "measurement_orbits"):
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) != value or int(value) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            object.__setattr__(self, name, int(value))

    def evolution_parameters(self) -> dict[str, float]:
        """Return the parameters that can change the unprotected trajectory."""

        return {
            "node_heat_capacity_J_K": self.node_heat_capacity_J_K,
            "radiator_heat_capacity_J_K": self.radiator_heat_capacity_J_K,
            "loop_conductance_W_K": self.loop_conductance_W_K,
            "radiator_area_m2": self.radiator_area_m2,
            "radiator_emissivity": self.radiator_emissivity,
            "housekeeping_power_W": self.housekeeping_power_W,
            "space_sink_temperature_K": self.space_sink_temperature_K,
            "stefan_boltzmann_W_m2_K4": self.stefan_boltzmann_W_m2_K4,
        }

    def as_metadata(self) -> dict[str, float | int]:
        """Return a JSON-serialisable copy of all baseline parameters."""

        return asdict(self)


DEFAULT_PARAMETERS = ThermalParameters()


@dataclass(frozen=True, slots=True)
class ThermalSimulationResult:
    """Trajectories and provenance returned by :func:`simulate_thermal`.

    Temperature and time arrays contain ``N + 1`` state-boundary samples;
    forcing and heat-flow arrays contain ``N`` interval samples.  Arrays are
    owned by the result and marked read-only to prevent accidental mutation of
    an authoritative run after its provenance hash has been recorded.
    """

    time_s: FloatArray
    node_temperature_K: FloatArray
    radiator_temperature_K: FloatArray
    compute_power_W: FloatArray
    environmental_flux_W_m2: FloatArray
    loop_heat_flow_W: FloatArray
    radiator_rejection_W: FloatArray
    absorbed_environmental_power_W: FloatArray
    dt_s: float
    physical_realization_sha256: str
    metadata: Mapping[str, Any]

    @property
    def n_steps(self) -> int:
        return int(self.compute_power_W.size)

    @property
    def duration_s(self) -> float:
        return self.n_steps * self.dt_s


def _forcing_array(values: ArrayLike, name: str) -> FloatArray:
    """Validate and take ownership of a one-dimensional forcing array."""

    try:
        array = np.array(values, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a one-dimensional numeric array") from exc
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if array.size == 0:
        raise ValueError(f"{name} must contain at least one sample")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    if np.any(array < 0.0):
        raise ValueError(f"{name} must contain only non-negative values")
    return array


def _readonly(array: FloatArray | BoolArray) -> FloatArray | BoolArray:
    array.setflags(write=False)
    return array


def orbital_environment(
    time_s: ArrayLike,
    params: ThermalParameters = DEFAULT_PARAMETERS,
) -> tuple[FloatArray, BoolArray]:
    """Return the documented two-level absorbed flux and hot-phase indicator.

    Orbit phase zero is the beginning of the hot interval.  Samples exactly at
    ``hot_fraction * orbit_period_s`` are cold.  ``time_s`` is normally the
    array of interval start times used to construct a forcing realization.
    """

    try:
        times = np.asarray(time_s, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("time_s must be a one-dimensional numeric array") from exc
    if times.ndim != 1:
        raise ValueError("time_s must be one-dimensional")
    if not np.all(np.isfinite(times)):
        raise ValueError("time_s must contain only finite values")

    phase_s = np.mod(times, params.orbit_period_s)
    hot_mask = phase_s < params.hot_fraction * params.orbit_period_s
    flux = np.where(
        hot_mask,
        params.environmental_flux_hot_W_m2,
        params.environmental_flux_cold_W_m2,
    ).astype(np.float64, copy=False)
    return flux, hot_mask


def measurement_step_mask(
    step_time_s: ArrayLike,
    *,
    params: ThermalParameters = DEFAULT_PARAMETERS,
    warmup_orbits: int | None = None,
    measurement_orbits: int | None = None,
    campaign_start_time_s: float = 0.0,
) -> BoolArray:
    """Select forcing intervals in the period-relative measurement window.

    The returned mask is aligned with interval forcing samples, not the ``N+1``
    state-boundary array.  For a simulation result use
    ``result.node_temperature_K[1:][mask]`` for end-of-step temperatures.
    """

    try:
        times = np.asarray(step_time_s, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("step_time_s must be a one-dimensional numeric array") from exc
    if times.ndim != 1:
        raise ValueError("step_time_s must be one-dimensional")
    if not np.all(np.isfinite(times)):
        raise ValueError("step_time_s must contain only finite values")

    warmup = params.warmup_orbits if warmup_orbits is None else warmup_orbits
    measure = params.measurement_orbits if measurement_orbits is None else measurement_orbits
    for value, name in ((warmup, "warmup_orbits"), (measure, "measurement_orbits")):
        if isinstance(value, bool) or int(value) != value or int(value) < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    start = _finite_float(campaign_start_time_s, "campaign_start_time_s")
    elapsed_s = times - start
    measurement_start_s = int(warmup) * params.orbit_period_s
    measurement_stop_s = measurement_start_s + int(measure) * params.orbit_period_s
    return (elapsed_s >= measurement_start_s) & (elapsed_s < measurement_stop_s)


def _physical_realization_sha256(
    environmental_flux_W_m2: FloatArray,
    *,
    params: ThermalParameters,
    dt_s: float,
    start_time_s: float,
    initial_node_temperature_K: float,
    initial_radiator_temperature_K: float,
) -> str:
    """Hash only the shared plant/environment realization, never the workload."""

    descriptor = {
        "schema": PHYSICAL_REALIZATION_HASH_SCHEMA,
        "n_steps": int(environmental_flux_W_m2.size),
        "dt_s": dt_s,
        "start_time_s": start_time_s,
        "initial_node_temperature_K": initial_node_temperature_K,
        "initial_radiator_temperature_K": initial_radiator_temperature_K,
        "evolution_parameters": params.evolution_parameters(),
        "environment_encoding": "contiguous-little-endian-float64",
    }
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            descriptor,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    digest.update(b"\x00")
    canonical_environment = np.ascontiguousarray(
        environmental_flux_W_m2, dtype=np.dtype("<f8")
    )
    digest.update(canonical_environment.tobytes(order="C"))
    return digest.hexdigest()


def simulate_thermal(
    compute_power_W: ArrayLike,
    environmental_flux_W_m2: ArrayLike,
    *,
    dt_s: float | None = None,
    params: ThermalParameters = DEFAULT_PARAMETERS,
    initial_node_temperature_K: float | None = None,
    initial_radiator_temperature_K: float | None = None,
    start_time_s: float = 0.0,
) -> ThermalSimulationResult:
    """Integrate TSM-01 from explicit workload and environment realizations.

    Args:
        compute_power_W: Compute-only power held over each integration interval.
            The fixed housekeeping load is added by the plant.
        environmental_flux_W_m2: Absorbed environmental heat flux held over the
            same intervals.  Its length must exactly match ``compute_power_W``.
        dt_s: Forward-Euler step.  Defaults to the documented 1 s release step.
        params: Frozen v0.4.4 baseline parameters (or an explicit sensitivity
            case).  No parameter is sampled inside this function.
        initial_node_temperature_K: Optional explicit initial state; otherwise
            the Appendix A value in ``params`` is used.
        initial_radiator_temperature_K: Optional explicit initial state.
        start_time_s: Absolute time label for the first state.  Environment is
            already precomputed, so this does not implicitly alter forcing.

    Returns:
        A :class:`ThermalSimulationResult`.  Its physical-realisation SHA-256
        covers the effective plant parameters, initial state, time geometry and
        environmental flux, but intentionally excludes compute power.  Paired
        workloads should therefore have identical hashes.

    Raises:
        ValueError: If forcing geometry or values are invalid.
        FloatingPointError: If an integration step leaves the finite,
            positive-absolute-temperature domain.
    """

    power = _forcing_array(compute_power_W, "compute_power_W")
    environment = _forcing_array(
        environmental_flux_W_m2, "environmental_flux_W_m2"
    )
    if power.shape != environment.shape:
        raise ValueError(
            "compute_power_W and environmental_flux_W_m2 must have equal length"
        )

    step_s = params.release_dt_s if dt_s is None else _finite_float(dt_s, "dt_s")
    if step_s <= 0.0:
        raise ValueError("dt_s must be greater than zero")
    start_s = _finite_float(start_time_s, "start_time_s")
    node_initial_K = (
        params.initial_node_temperature_K
        if initial_node_temperature_K is None
        else _finite_float(initial_node_temperature_K, "initial_node_temperature_K")
    )
    radiator_initial_K = (
        params.initial_radiator_temperature_K
        if initial_radiator_temperature_K is None
        else _finite_float(
            initial_radiator_temperature_K, "initial_radiator_temperature_K"
        )
    )
    if node_initial_K <= 0.0 or radiator_initial_K <= 0.0:
        raise ValueError("initial temperatures must be greater than absolute zero")

    n_steps = int(power.size)
    time_s = start_s + np.arange(n_steps + 1, dtype=np.float64) * step_s
    node_temperature_K = np.empty(n_steps + 1, dtype=np.float64)
    radiator_temperature_K = np.empty(n_steps + 1, dtype=np.float64)
    loop_heat_flow_W = np.empty(n_steps, dtype=np.float64)
    radiator_rejection_W = np.empty(n_steps, dtype=np.float64)
    absorbed_environmental_power_W = environment * params.radiator_area_m2

    node_temperature_K[0] = node_initial_K
    radiator_temperature_K[0] = radiator_initial_K

    # Local scalar bindings keep the sequential Euler loop inexpensive while
    # preserving the exact documented operation order used by the benchmark.
    node_capacity = params.node_heat_capacity_J_K
    radiator_capacity = params.radiator_heat_capacity_J_K
    conductance = params.loop_conductance_W_K
    area = params.radiator_area_m2
    emissivity_sigma_area = (
        params.radiator_emissivity
        * params.stefan_boltzmann_W_m2_K4
        * area
    )
    sink_fourth = params.space_sink_temperature_K**4
    housekeeping = params.housekeeping_power_W

    node_K = node_initial_K
    radiator_K = radiator_initial_K
    for index in range(n_steps):
        loop_W = conductance * (node_K - radiator_K)
        rejection_W = emissivity_sigma_area * (radiator_K**4 - sink_fourth)
        next_node_K = node_K + step_s * (
            power[index] + housekeeping - loop_W
        ) / node_capacity
        next_radiator_K = radiator_K + step_s * (
            loop_W + absorbed_environmental_power_W[index] - rejection_W
        ) / radiator_capacity

        if (
            not math.isfinite(next_node_K)
            or not math.isfinite(next_radiator_K)
            or next_node_K <= 0.0
            or next_radiator_K <= 0.0
        ):
            raise FloatingPointError(
                "thermal integration left the finite positive-temperature "
                f"domain at step {index}"
            )

        loop_heat_flow_W[index] = loop_W
        radiator_rejection_W[index] = rejection_W
        node_temperature_K[index + 1] = next_node_K
        radiator_temperature_K[index + 1] = next_radiator_K
        node_K = next_node_K
        radiator_K = next_radiator_K

    realization_sha256 = _physical_realization_sha256(
        environment,
        params=params,
        dt_s=step_s,
        start_time_s=start_s,
        initial_node_temperature_K=node_initial_K,
        initial_radiator_temperature_K=radiator_initial_K,
    )
    metadata: Mapping[str, Any] = MappingProxyType(
        {
            "model_version": MODEL_VERSION,
            "model_status": "project-generated parametric model; not a digital twin",
            "reconstruction_status": (
                "thermal plant reconstructed from retained v0.4.4 release artefacts; "
                "historical stochastic source was unavailable"
            ),
            "integrator": "Forward Euler",
            "forcing_convention": "left endpoint, piecewise constant over each step",
            "state_alignment": "N+1 interval-boundary samples",
            "n_steps": n_steps,
            "duration_s": n_steps * step_s,
            "start_time_s": start_s,
            "end_time_s": start_s + n_steps * step_s,
            "parameters": params.as_metadata(),
            "physical_realization_hash_schema": PHYSICAL_REALIZATION_HASH_SCHEMA,
        }
    )

    for array in (
        time_s,
        node_temperature_K,
        radiator_temperature_K,
        power,
        environment,
        loop_heat_flow_W,
        radiator_rejection_W,
        absorbed_environmental_power_W,
    ):
        _readonly(array)

    return ThermalSimulationResult(
        time_s=time_s,
        node_temperature_K=node_temperature_K,
        radiator_temperature_K=radiator_temperature_K,
        compute_power_W=power,
        environmental_flux_W_m2=environment,
        loop_heat_flow_W=loop_heat_flow_W,
        radiator_rejection_W=radiator_rejection_W,
        absorbed_environmental_power_W=absorbed_environmental_power_W,
        dt_s=step_s,
        physical_realization_sha256=realization_sha256,
        metadata=metadata,
    )


__all__ = [
    "DEFAULT_PARAMETERS",
    "MODEL_VERSION",
    "PHYSICAL_REALIZATION_HASH_SCHEMA",
    "ThermalParameters",
    "ThermalSimulationResult",
    "measurement_step_mask",
    "orbital_environment",
    "simulate_thermal",
]
