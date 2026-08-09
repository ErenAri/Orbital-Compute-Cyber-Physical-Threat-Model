"""Frozen RSIM-001 representative orbital environment definitions.

E0 is the canonical v0.4.4 square-wave forcing.  E1 is a transparent,
component-based analytic LEO challenge environment; it is not a flight
environment model and is deliberately not tuned to reproduce E0.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from src.octm.baselines.v044 import thermal_model as canonical


E0_CANONICAL = "E0_CANONICAL"
E1_REPRESENTATIVE_ANALYTIC_LEO = "E1_REPRESENTATIVE_ANALYTIC_LEO"
ENVIRONMENT_IDS = (E0_CANONICAL, E1_REPRESENTATIVE_ANALYTIC_LEO)


@dataclass(frozen=True, slots=True)
class E1Parameters:
    earth_radius_m: float = 6_378_137.0
    altitude_m: float = 550_000.0
    earth_gravitational_parameter_m3_s2: float = 3.986004418e14
    beta_rad: float = 0.0
    solar_irradiance_W_m2: float = 1_361.0
    earth_bond_albedo: float = 0.294
    earth_IR_flux_W_m2: float = 234.0
    radiator_solar_absorptivity: float = 0.20
    radiator_IR_absorptivity: float = 0.85
    solar_array_incidence_factor: float = 1.0
    radiator_solar_incidence_factor: float = 0.25
    radiator_earth_view_factor: float = 0.50
    solar_bus_power_W: float = 53_731.74872665535

    @property
    def orbit_radius_m(self) -> float:
        return self.earth_radius_m + self.altitude_m

    @property
    def period_s(self) -> float:
        return 2.0 * math.pi * math.sqrt(
            self.orbit_radius_m**3 / self.earth_gravitational_parameter_m3_s2
        )

    @property
    def eclipse_fraction(self) -> float:
        if self.beta_rad != 0.0:
            raise ValueError("the frozen E1 eclipse-fraction expression requires beta=0")
        return math.asin(self.earth_radius_m / self.orbit_radius_m) / math.pi

    @property
    def sunlit_fraction(self) -> float:
        return 1.0 - self.eclipse_fraction

    @property
    def eclipse_duration_s(self) -> float:
        return self.period_s * self.eclipse_fraction

    def validate(self) -> None:
        if self.earth_radius_m <= 0.0 or self.altitude_m < 0.0:
            raise ValueError("invalid Earth/orbit geometry")
        if self.earth_gravitational_parameter_m3_s2 <= 0.0:
            raise ValueError("Earth gravitational parameter must be positive")
        if not (-math.pi / 2.0 <= self.beta_rad <= math.pi / 2.0):
            raise ValueError("beta angle is outside its declared range")
        bounded = {
            "earth_bond_albedo": self.earth_bond_albedo,
            "radiator_solar_absorptivity": self.radiator_solar_absorptivity,
            "radiator_IR_absorptivity": self.radiator_IR_absorptivity,
            "solar_array_incidence_factor": self.solar_array_incidence_factor,
            "radiator_solar_incidence_factor": self.radiator_solar_incidence_factor,
            "radiator_earth_view_factor": self.radiator_earth_view_factor,
        }
        for name, value in bounded.items():
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} is outside [0, 1]")
        positive = (
            self.solar_irradiance_W_m2,
            self.earth_IR_flux_W_m2,
            self.solar_bus_power_W,
        )
        if any(not math.isfinite(v) or v < 0.0 for v in positive):
            raise ValueError("E1 radiative/power parameters must be finite and non-negative")


DEFAULT_E1 = E1Parameters()


@dataclass(frozen=True, slots=True)
class EnvironmentTrace:
    environment_id: str
    time_s: np.ndarray
    illumination: np.ndarray
    hot_mask: np.ndarray
    direct_solar_W_m2: np.ndarray
    albedo_W_m2: np.ndarray
    earth_IR_W_m2: np.ndarray
    absorbed_flux_W_m2: np.ndarray
    solar_generation_W: np.ndarray
    period_s: float
    physical_realization_sha256: str
    metadata: dict[str, object]


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.ascontiguousarray(values).copy()
    result.setflags(write=False)
    return result


def _hash_trace(environment_id: str, period_s: float, flux: np.ndarray) -> str:
    descriptor = json.dumps(
        {"schema": "rsim-001.environment.v1", "environment_id": environment_id,
         "period_s": period_s, "sample_count": int(flux.size)},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(descriptor)
    digest.update(b"\x00")
    digest.update(np.asarray(flux, dtype="<f8").tobytes())
    return digest.hexdigest()


def generate_environment(
    environment_id: str,
    time_s: np.ndarray,
    *,
    e1: E1Parameters = DEFAULT_E1,
    phase_offset_fraction: float = 0.0,
) -> EnvironmentTrace:
    """Generate frozen E0 or E1 left-endpoint interval inputs."""

    time = np.asarray(time_s, dtype=np.float64)
    if time.ndim != 1 or time.size == 0 or not np.all(np.isfinite(time)):
        raise ValueError("time_s must be a non-empty finite one-dimensional array")
    if environment_id not in ENVIRONMENT_IDS:
        raise ValueError(f"unknown environment_id: {environment_id}")
    if not math.isfinite(phase_offset_fraction):
        raise ValueError("environment phase offset must be finite")
    normalized_phase_offset = float(phase_offset_fraction % 1.0)

    if environment_id == E0_CANONICAL:
        if normalized_phase_offset != 0.0:
            raise ValueError("environment phase offset is defined for E1 only")
        p = canonical.P
        hot = np.asarray(canonical.in_hot_phase(time, p), dtype=bool)
        illumination = hot.copy()
        flux = np.asarray(canonical.env_flux(time, p), dtype=np.float64)
        zeros = np.zeros_like(flux)
        solar = illumination.astype(np.float64) * e1.solar_bus_power_W
        period = float(p["period"])
        metadata: dict[str, object] = {
            "model": "canonical_v0.4.4_square_wave",
            "q_hot_W_m2": float(p["q_hot"]),
            "q_cold_W_m2": float(p["q_cold"]),
            "sunlit_fraction": float(p["sunlit_frac"]),
            "thermal_environment_status": "CANONICAL_V044",
            "solar_generation_status": "DERIVED_REPRESENTATIVE",
        }
        direct, albedo, earth_ir = zeros, zeros, flux
    else:
        e1.validate()
        period = e1.period_s
        if normalized_phase_offset == 0.0:
            # Preserve the historical offset-zero floating-point path exactly.
            phase = 2.0 * math.pi * np.mod(time, period) / period
        else:
            phase = 2.0 * math.pi * np.mod(
                time / period + normalized_phase_offset, 1.0
            )
        c = math.cos(e1.beta_rad) * np.cos(phase)
        d_perp = e1.orbit_radius_m * np.sqrt(np.maximum(0.0, 1.0 - c * c))
        eclipse = (c < 0.0) & (d_perp <= e1.earth_radius_m)
        illumination = ~eclipse
        hot = illumination.copy()
        direct = (
            e1.radiator_solar_absorptivity
            * e1.solar_irradiance_W_m2
            * e1.radiator_solar_incidence_factor
            * illumination.astype(np.float64)
        )
        albedo_geometry = illumination.astype(np.float64) * np.maximum(0.0, c)
        albedo = (
            e1.radiator_solar_absorptivity
            * e1.solar_irradiance_W_m2
            * e1.earth_bond_albedo
            * e1.radiator_earth_view_factor
            * albedo_geometry
        )
        earth_ir = np.full_like(
            time,
            e1.radiator_IR_absorptivity
            * e1.earth_IR_flux_W_m2
            * e1.radiator_earth_view_factor,
        )
        flux = direct + albedo + earth_ir
        solar = (
            illumination.astype(np.float64)
            * e1.solar_array_incidence_factor
            * e1.solar_bus_power_W
        )
        metadata = {
            "model": "representative_analytic_leo_v1",
            "scope": "fixed-wall-clock representative environment challenge",
            "not_flight_environment_model": True,
            "not_tuned_to_E0": True,
            "beta_rad": e1.beta_rad,
            "eclipse_fraction": e1.eclipse_fraction,
            "eclipse_duration_s": e1.eclipse_duration_s,
            "sunlit_fraction": e1.sunlit_fraction,
            "environment_phase_offset_fraction": normalized_phase_offset,
            "environment_phase_offset_deg": normalized_phase_offset * 360.0,
            "albedo_treatment": "bounded analytic approximation",
            "radiator_and_solar_array_orientation_are_distinct": True,
        }

    arrays = [illumination, hot, direct, albedo, earth_ir, flux, solar]
    if any(not np.all(np.isfinite(np.asarray(a, dtype=np.float64))) for a in arrays):
        raise RuntimeError("non-finite E0/E1 environment value")
    if np.any(flux < 0.0) or np.any(solar < 0.0):
        raise RuntimeError("negative environment or solar-generation value")
    return EnvironmentTrace(
        environment_id=environment_id,
        time_s=_readonly(time),
        illumination=_readonly(illumination.astype(bool)),
        hot_mask=_readonly(hot.astype(bool)),
        direct_solar_W_m2=_readonly(np.asarray(direct, dtype=np.float64)),
        albedo_W_m2=_readonly(np.asarray(albedo, dtype=np.float64)),
        earth_IR_W_m2=_readonly(np.asarray(earth_ir, dtype=np.float64)),
        absorbed_flux_W_m2=_readonly(np.asarray(flux, dtype=np.float64)),
        solar_generation_W=_readonly(np.asarray(solar, dtype=np.float64)),
        period_s=period,
        physical_realization_sha256=_hash_trace(environment_id, period, flux),
        metadata=metadata,
    )


__all__ = [
    "DEFAULT_E1", "E0_CANONICAL", "E1_REPRESENTATIVE_ANALYTIC_LEO",
    "ENVIRONMENT_IDS", "E1Parameters", "EnvironmentTrace", "generate_environment",
]
