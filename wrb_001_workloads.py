"""Deterministic workload generators for the WRB-001 paired campaign.

The public v0.4.4 artefacts describe a 30 kW diversified stochastic load,
a 40 kW compute design limit, and a two-level phase-shaped comparator.  They
do not contain the released Python sources.  Consequently W1 and W5 below
are faithful *reconstructions of those documented semantics*, not claims of
source-code identity.  This limitation is recorded in each realization.

Every power sample is a left-endpoint, zero-order-hold value for the half-open
interval ``[time_s[i], time_s[i] + 1 s)``.  The measurement mask must identify
one non-empty, contiguous half-open interval.  Energy matching changes only
samples in that interval and uses bounded additive water filling; infeasible
targets are returned explicitly as ``INVALID_ENERGY_MATCH``.

No module/global random state is used.  Family functions require an explicit
``numpy.random.Generator``.  :func:`generate_workloads` creates one stable,
SHA-256-derived PCG64DXSM stream per workload so results do not depend on the
order in which workload families are evaluated.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np


CAMPAIGN_ID = "WRB-001"
MODEL_WORKLOAD_VERSION = "WRB-001-workloads-v1"
CANONICAL_DT_S = 1.0
POWER_MIN_W = 0.0
POWER_MAX_W = 40_000.0
INVALID_ENERGY_MATCH = "INVALID_ENERGY_MATCH"

W0_CONSTANT_REFERENCE = "constant_reference"
W1_DIVERSIFIED_STOCHASTIC = "diversified_stochastic"
W2_BURSTY_BENIGN = "bursty_benign"
W3_QUEUE_DRIVEN_BENIGN = "queue_driven_benign"
W4_POWER_AWARE_BENIGN = "power_aware_benign"
W5_PHASE_SHAPED_CANDIDATE = "phase_shaped_candidate"

WORKLOAD_IDS = (
    W0_CONSTANT_REFERENCE,
    W1_DIVERSIFIED_STOCHASTIC,
    W2_BURSTY_BENIGN,
    W3_QUEUE_DRIVEN_BENIGN,
    W4_POWER_AWARE_BENIGN,
    W5_PHASE_SHAPED_CANDIDATE,
)

WORKLOAD_LABELS = {
    W0_CONSTANT_REFERENCE: "W0 — constant reference",
    W1_DIVERSIFIED_STOCHASTIC: "W1 — diversified stochastic",
    W2_BURSTY_BENIGN: "W2 — bursty benign",
    W3_QUEUE_DRIVEN_BENIGN: "W3 — queue-driven benign",
    W4_POWER_AWARE_BENIGN: "W4 — power-aware benign",
    W5_PHASE_SHAPED_CANDIDATE: "W5 — phase-shaped adversarial candidate",
}


@dataclass(frozen=True)
class WorkloadConfig:
    """Versioned workload-policy parameters; these are not thermal inputs."""

    campaign_id: str = CAMPAIGN_ID
    generator_version: str = MODEL_WORKLOAD_VERSION
    power_min_W: float = POWER_MIN_W
    power_max_W: float = POWER_MAX_W
    energy_tolerance_fraction: float = 1.0e-3

    # W1: reconstructed v0.4.4 diversified stochastic semantics.
    diversified_mean_power_W: float = 30_000.0
    diversified_cycle_amplitude_W: float = 4_000.0
    diversified_cycle_period_s: float = 1_800.0
    diversified_sigma_W: float = 700.0

    # W2: stochastic shot-noise bursts.
    bursty_idle_power_W: float = 8_000.0
    bursty_arrival_rate_per_s: float = 0.045
    bursty_mean_duration_s: float = 80.0
    bursty_job_power_min_W: float = 4_000.0
    bursty_job_power_max_W: float = 10_000.0

    # W3: FIFO jobs and a work-conserving dispatch queue.
    queue_arrival_rate_per_s: float = 0.12
    queue_mean_job_energy_J: float = 250_000.0
    queue_job_energy_shape: float = 2.0

    # W4: only the caller-supplied electrical availability signal is observed.
    power_aware_low_W: float = 12_000.0
    power_aware_high_W: float = 38_000.0
    power_aware_jitter_sigma_W: float = 350.0

    def __post_init__(self) -> None:
        values = asdict(self)
        for name, value in values.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.power_min_W != POWER_MIN_W or self.power_max_W != POWER_MAX_W:
            raise ValueError("WRB-001 compute-power bounds are frozen at 0..40000 W")
        if not (0.0 < self.energy_tolerance_fraction <= 1.0e-3):
            raise ValueError("energy_tolerance_fraction must be in (0, 0.001]")
        if not (self.power_min_W <= self.diversified_mean_power_W <= self.power_max_W):
            raise ValueError("diversified_mean_power_W is outside compute-power bounds")
        if self.diversified_cycle_amplitude_W < 0.0:
            raise ValueError("diversified_cycle_amplitude_W must be non-negative")
        if self.diversified_cycle_period_s <= 0.0:
            raise ValueError("diversified_cycle_period_s must be positive")
        if self.diversified_sigma_W < 0.0:
            raise ValueError("diversified_sigma_W must be non-negative")
        if (
            self.diversified_mean_power_W - self.diversified_cycle_amplitude_W
            < self.power_min_W
            or self.diversified_mean_power_W + self.diversified_cycle_amplitude_W
            > self.power_max_W
        ):
            raise ValueError("diversified deterministic cycle is outside power bounds")
        if self.bursty_idle_power_W < self.power_min_W:
            raise ValueError("bursty_idle_power_W is below the compute-power bound")
        if self.bursty_arrival_rate_per_s <= 0.0 or self.bursty_mean_duration_s <= 0.0:
            raise ValueError("bursty arrival rate and mean duration must be positive")
        if not (0.0 <= self.bursty_job_power_min_W <= self.bursty_job_power_max_W):
            raise ValueError("invalid burst-job power range")
        if self.queue_arrival_rate_per_s <= 0.0:
            raise ValueError("queue_arrival_rate_per_s must be positive")
        if self.queue_mean_job_energy_J <= 0.0 or self.queue_job_energy_shape <= 0.0:
            raise ValueError("queue job-energy parameters must be positive")
        if not (
            self.power_min_W <= self.power_aware_low_W
            <= self.power_aware_high_W <= self.power_max_W
        ):
            raise ValueError("invalid power-aware output range")
        if self.power_aware_jitter_sigma_W < 0.0:
            raise ValueError("power_aware_jitter_sigma_W must be non-negative")


@dataclass(frozen=True)
class RNGStreamLineage:
    campaign_id: str
    campaign_seed: int
    workload_id: str
    stream_name: str
    rng_algorithm: str
    derivation: str
    derivation_path: str
    rng_seed: int


@dataclass(frozen=True)
class EnergyMatchResult:
    power_W: np.ndarray
    valid: bool
    invalid_reason: str | None
    sampled_energy_J: float
    target_energy_J: float
    relative_error: float
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True)
class WorkloadRealization:
    workload_id: str
    label: str
    power_W: np.ndarray
    valid_run: bool
    invalid_reason: str | None
    seed: int
    rng_seed: int
    rng_stream: str
    seed_lineage: RNGStreamLineage
    trace_sha256: str
    configuration_sha256: str
    input_sha256: str
    target_energy_J: float
    sampled_energy_J: float
    relative_energy_error: float
    dt_s: float
    measurement_start_index: int
    measurement_stop_index: int
    measurement_interval_s: tuple[float, float]
    allowed_inputs: tuple[str, ...]
    diagnostics: Mapping[str, Any]


def _require_generator(rng: np.random.Generator) -> None:
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be an explicit numpy.random.Generator")


def _require_seed(seed: int) -> int:
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)):
        raise TypeError("seed must be an integer")
    seed_i = int(seed)
    if seed_i < 0:
        raise ValueError("seed must be non-negative")
    return seed_i


def derive_workload_seed(
    seed: int,
    workload_id: str,
    *,
    campaign_id: str = CAMPAIGN_ID,
    stream_name: str = "generation",
) -> int:
    """Derive a stable 128-bit sub-seed without consuming another RNG."""

    seed_i = _require_seed(seed)
    if workload_id not in WORKLOAD_IDS:
        raise ValueError(f"unknown workload_id: {workload_id!r}")
    payload = {
        "campaign_id": campaign_id,
        "campaign_seed": seed_i,
        "namespace": "octm.wrb_001.workload_rng.v1",
        "stream_name": stream_name,
        "workload_id": workload_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:16], "big", signed=False)


def make_workload_rng(
    seed: int,
    workload_id: str,
    *,
    campaign_id: str = CAMPAIGN_ID,
    stream_name: str = "generation",
) -> tuple[np.random.Generator, RNGStreamLineage]:
    """Return an explicit, order-independent RNG and auditable lineage."""

    seed_i = _require_seed(seed)
    rng_seed = derive_workload_seed(
        seed_i, workload_id, campaign_id=campaign_id, stream_name=stream_name
    )
    path = f"{campaign_id}/seed={seed_i}/{workload_id}/{stream_name}"
    lineage = RNGStreamLineage(
        campaign_id=campaign_id,
        campaign_seed=seed_i,
        workload_id=workload_id,
        stream_name=stream_name,
        rng_algorithm="numpy.PCG64DXSM",
        derivation="SHA-256 first 128 bits over canonical JSON (v1)",
        derivation_path=path,
        rng_seed=rng_seed,
    )
    return np.random.Generator(np.random.PCG64DXSM(rng_seed)), lineage


def _validate_grid_and_mask(
    time_s: Sequence[float] | np.ndarray,
    measurement_mask: Sequence[bool] | np.ndarray,
    dt_s: float,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    if not math.isfinite(float(dt_s)) or float(dt_s) != CANONICAL_DT_S:
        raise ValueError("WRB-001 requires the canonical dt_s = 1.0")
    time = np.asarray(time_s, dtype=np.float64)
    if time.ndim != 1 or time.size == 0 or not np.all(np.isfinite(time)):
        raise ValueError("time_s must be a non-empty finite one-dimensional array")
    expected = np.arange(time.size, dtype=np.float64) * CANONICAL_DT_S
    if not np.array_equal(time, expected):
        raise ValueError("time_s must be the canonical grid arange(N) * 1.0 s")
    mask = np.asarray(measurement_mask)
    if mask.ndim != 1 or mask.shape != time.shape or mask.dtype.kind != "b":
        raise ValueError("measurement_mask must be a boolean array matching time_s")
    true_indices = np.flatnonzero(mask)
    if true_indices.size == 0:
        raise ValueError("measurement_mask must select a non-empty interval")
    start = int(true_indices[0])
    stop = int(true_indices[-1]) + 1
    expected_mask = np.zeros(time.size, dtype=bool)
    expected_mask[start:stop] = True
    if not np.array_equal(mask, expected_mask):
        raise ValueError("measurement_mask must select one contiguous half-open interval")
    return time, mask.astype(bool, copy=False), start, stop


def _validate_signal(
    signal: Sequence[Any] | np.ndarray,
    *,
    name: str,
    shape: tuple[int, ...],
    boolean: bool = False,
) -> np.ndarray:
    array = np.asarray(signal)
    if array.ndim != 1 or array.shape != shape:
        raise ValueError(f"{name} must be one-dimensional and match time_s")
    if boolean:
        if array.dtype.kind != "b":
            raise ValueError(f"{name} must be boolean")
        return array.astype(bool, copy=False)
    array = np.asarray(array, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def sampled_energy_J(
    power_W: Sequence[float] | np.ndarray,
    measurement_mask: Sequence[bool] | np.ndarray,
    *,
    dt_s: float = CANONICAL_DT_S,
) -> float:
    """Compute sampled left-endpoint energy on the selected half-open window."""

    if not math.isfinite(float(dt_s)) or float(dt_s) <= 0.0:
        raise ValueError("dt_s must be finite and positive")
    power = np.asarray(power_W, dtype=np.float64)
    mask = np.asarray(measurement_mask)
    if power.ndim != 1 or mask.ndim != 1 or power.shape != mask.shape:
        raise ValueError("power_W and measurement_mask must be matching 1-D arrays")
    if mask.dtype.kind != "b":
        raise ValueError("measurement_mask must be boolean")
    if not np.all(np.isfinite(power)):
        raise ValueError("power_W must be finite")
    return float(math.fsum(float(value) for value in power[mask]) * float(dt_s))


def _relative_energy_error(actual_J: float, target_J: float) -> float:
    if target_J == 0.0:
        return 0.0 if actual_J == 0.0 else math.inf
    return abs(actual_J - target_J) / abs(target_J)


def _readonly_power(power_W: np.ndarray) -> np.ndarray:
    frozen = np.ascontiguousarray(power_W, dtype=np.float64).copy()
    frozen.setflags(write=False)
    return frozen


def match_sampled_energy(
    power_W: Sequence[float] | np.ndarray,
    measurement_mask: Sequence[bool] | np.ndarray,
    target_energy_J: float,
    *,
    dt_s: float = CANONICAL_DT_S,
    power_min_W: float = POWER_MIN_W,
    power_max_W: float = POWER_MAX_W,
    tolerance_fraction: float = 1.0e-3,
) -> EnergyMatchResult:
    """Match energy by exact bounded additive water filling.

    Samples outside ``measurement_mask`` are never modified.  An infeasible
    target returns the original trace with ``valid=False``; it is never clipped
    or projected to a different budget.
    """

    if not math.isfinite(float(dt_s)) or float(dt_s) <= 0.0:
        raise ValueError("dt_s must be finite and positive")
    if not math.isfinite(float(target_energy_J)) or float(target_energy_J) < 0.0:
        raise ValueError("target_energy_J must be finite and non-negative")
    if not (math.isfinite(power_min_W) and math.isfinite(power_max_W)):
        raise ValueError("power bounds must be finite")
    if power_min_W > power_max_W:
        raise ValueError("power_min_W must not exceed power_max_W")
    if not (0.0 < tolerance_fraction <= 1.0e-3):
        raise ValueError("tolerance_fraction must be in (0, 0.001]")

    original = np.asarray(power_W, dtype=np.float64)
    mask = np.asarray(measurement_mask)
    if original.ndim != 1 or mask.ndim != 1 or original.shape != mask.shape:
        raise ValueError("power_W and measurement_mask must be matching 1-D arrays")
    if mask.dtype.kind != "b" or not np.any(mask):
        raise ValueError("measurement_mask must be boolean and non-empty")
    if not np.all(np.isfinite(original)):
        raise ValueError("power_W must contain only finite values")
    if np.any(original < power_min_W) or np.any(original > power_max_W):
        raise ValueError("power_W is outside the declared bounds before matching")

    matched = original.copy()
    indices = np.flatnonzero(mask)
    n_samples = int(indices.size)
    target = float(target_energy_J)
    feasible_min_J = float(n_samples * power_min_W * dt_s)
    feasible_max_J = float(n_samples * power_max_W * dt_s)
    raw_energy_J = sampled_energy_J(original, mask, dt_s=dt_s)
    base_diagnostics: dict[str, Any] = {
        "method": "bounded_additive_water_fill_v1",
        "measurement_sample_count": n_samples,
        "measurement_interval_semantics": "half-open; selected left-endpoint samples only",
        "raw_sampled_energy_J": raw_energy_J,
        "feasible_min_energy_J": feasible_min_J,
        "feasible_max_energy_J": feasible_max_J,
        "outside_measurement_samples_modified": 0,
        "silent_clipping_used": False,
    }

    # The tiny allowance is solely for representational roundoff at a bound.
    feasibility_eps_J = max(1.0e-9, 8.0 * np.finfo(np.float64).eps * max(1.0, feasible_max_J))
    if target < feasible_min_J - feasibility_eps_J or target > feasible_max_J + feasibility_eps_J:
        actual = raw_energy_J
        base_diagnostics.update(
            {
                "failure_detail": "target energy is outside the bounded interval",
                "requested_adjustment_J": target - raw_energy_J,
                "applied_adjustment_J": 0.0,
            }
        )
        return EnergyMatchResult(
            power_W=_readonly_power(original),
            valid=False,
            invalid_reason=INVALID_ENERGY_MATCH,
            sampled_energy_J=actual,
            target_energy_J=target,
            relative_error=_relative_energy_error(actual, target),
            diagnostics=base_diagnostics,
        )

    # Work in sum-of-watts space; this avoids repeatedly multiplying by dt.
    requested_delta_sum_W = (target - raw_energy_J) / float(dt_s)
    residual_sum_W = requested_delta_sum_W
    window = matched[indices].copy()
    water_fill_iterations = 0
    bound_hits = 0
    numerical_eps_W = 16.0 * np.finfo(np.float64).eps * max(1.0, power_max_W)

    while abs(residual_sum_W) > numerical_eps_W:
        water_fill_iterations += 1
        if water_fill_iterations > n_samples + 2:
            break
        if residual_sum_W > 0.0:
            capacity = power_max_W - window
        else:
            capacity = window - power_min_W
        active = capacity > numerical_eps_W
        if not np.any(active):
            break
        share = abs(residual_sum_W) / int(np.count_nonzero(active))
        applied_abs = np.minimum(capacity[active], share)
        if residual_sum_W > 0.0:
            window[active] += applied_abs
            residual_sum_W -= float(math.fsum(float(v) for v in applied_abs))
        else:
            window[active] -= applied_abs
            residual_sum_W += float(math.fsum(float(v) for v in applied_abs))
        bound_hits += int(np.count_nonzero(capacity[active] <= share + numerical_eps_W))

    # One representable correction removes accumulated summation roundoff.
    matched[indices] = window
    actual_before_correction_J = sampled_energy_J(matched, mask, dt_s=dt_s)
    correction_W = (target - actual_before_correction_J) / float(dt_s)
    correction_applied_W = 0.0
    if correction_W != 0.0:
        capacities = (
            power_max_W - matched[indices]
            if correction_W > 0.0
            else matched[indices] - power_min_W
        )
        candidates = np.flatnonzero(capacities >= abs(correction_W))
        if candidates.size:
            selected = int(indices[int(candidates[0])])
            matched[selected] += correction_W
            correction_applied_W = correction_W

    actual_J = sampled_energy_J(matched, mask, dt_s=dt_s)
    relative_error = _relative_energy_error(actual_J, target)
    bounds_ok = bool(
        np.all(matched >= power_min_W - numerical_eps_W)
        and np.all(matched <= power_max_W + numerical_eps_W)
    )
    valid = bool(bounds_ok and relative_error <= tolerance_fraction)
    base_diagnostics.update(
        {
            "requested_adjustment_J": target - raw_energy_J,
            "applied_adjustment_J": actual_J - raw_energy_J,
            "uniform_water_fill_iterations": water_fill_iterations,
            "water_fill_bound_hits": bound_hits,
            "final_single_sample_correction_W": correction_applied_W,
            "samples_at_lower_bound": int(np.count_nonzero(matched[mask] == power_min_W)),
            "samples_at_upper_bound": int(np.count_nonzero(matched[mask] == power_max_W)),
        }
    )
    if not valid:
        base_diagnostics["failure_detail"] = (
            "bounded water fill could not meet the requested tolerance"
        )
    return EnergyMatchResult(
        power_W=_readonly_power(matched),
        valid=valid,
        invalid_reason=None if valid else INVALID_ENERGY_MATCH,
        sampled_energy_J=actual_J,
        target_energy_J=target,
        relative_error=relative_error,
        diagnostics=base_diagnostics,
    )


def _bounded_normal(
    rng: np.random.Generator,
    *,
    mean: np.ndarray | float,
    sigma: float,
    size: int,
    lower: float,
    upper: float,
) -> tuple[np.ndarray, int]:
    """Sample a normal distribution with rejection, never post-hoc clipping."""

    _require_generator(rng)
    mean_array = np.broadcast_to(np.asarray(mean, dtype=np.float64), (size,))
    if sigma == 0.0:
        if np.any(mean_array < lower) or np.any(mean_array > upper):
            raise ValueError("zero-sigma normal mean is outside bounds")
        return mean_array.copy(), 0
    values = rng.normal(mean_array, sigma)
    rejected_total = 0
    rejected = (values < lower) | (values > upper)
    while np.any(rejected):
        count = int(np.count_nonzero(rejected))
        rejected_total += count
        values[rejected] = rng.normal(mean_array[rejected], sigma)
        rejected = (values < lower) | (values > upper)
    return values.astype(np.float64, copy=False), rejected_total


def generate_diversified_stochastic(
    *,
    time_s: np.ndarray,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W1: reconstructed slow diversified cycle plus stochastic demand.

    The embedded v0.4.4 Figure 1 is direct release evidence for an approximately
    30 kW trace with a regular 30-minute, roughly +/-4 kW component and smaller
    sample-scale variation.  Those visible semantics are encoded explicitly;
    the absent historical source still prevents a byte-identity claim.
    """

    _require_generator(rng)
    conditional_mean = (
        config.diversified_mean_power_W
        - config.diversified_cycle_amplitude_W
        * np.sin(2.0 * np.pi * time_s / config.diversified_cycle_period_s)
    )
    power, rejected = _bounded_normal(
        rng,
        mean=conditional_mean,
        sigma=config.diversified_sigma_W,
        size=int(time_s.size),
        lower=config.power_min_W,
        upper=config.power_max_W,
    )
    return power, {
        "generator": "reconstructed_diversified_cycle_plus_noise_v1",
        "historical_status": (
            "reconstructed_from_v0.4.4_published_artifacts; release source code absent"
        ),
        "documented_mean_power_W": config.diversified_mean_power_W,
        "figure_reconstructed_cycle_amplitude_W": (
            config.diversified_cycle_amplitude_W
        ),
        "figure_reconstructed_cycle_period_s": config.diversified_cycle_period_s,
        "reconstruction_sigma_W": config.diversified_sigma_W,
        "bound_enforcement": "rejection sampling (no clipping)",
        "rejected_draw_count": rejected,
    }


def generate_constant_reference(
    *,
    time_s: np.ndarray,
    target_energy_J: float,
    measurement_sample_count: int,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W0: constant power preserving this seed's sampled W1 energy."""

    _require_generator(rng)
    mean_power_W = target_energy_J / (measurement_sample_count * CANONICAL_DT_S)
    power = np.full(time_s.size, mean_power_W, dtype=np.float64)
    return power, {
        "generator": "per_seed_constant_reference_v1",
        "reference_workload_id": W1_DIVERSIFIED_STOCHASTIC,
        "constant_power_W": float(mean_power_W),
        "rng_draw_count": 0,
    }


def generate_bursty_benign(
    *,
    time_s: np.ndarray,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W2: benign Poisson arrivals with stochastic burst powers/durations."""

    _require_generator(rng)
    n = int(time_s.size)
    arrivals = rng.poisson(config.bursty_arrival_rate_per_s, size=n)
    difference = np.zeros(n + 1, dtype=np.float64)
    job_count = int(np.sum(arrivals, dtype=np.int64))
    duration_sum = 0
    truncated_jobs = 0
    probability = 1.0 / config.bursty_mean_duration_s
    for start, count in enumerate(arrivals):
        count_i = int(count)
        if count_i == 0:
            continue
        durations = rng.geometric(probability, size=count_i).astype(np.int64)
        job_powers = rng.uniform(
            config.bursty_job_power_min_W,
            config.bursty_job_power_max_W,
            size=count_i,
        )
        for duration, job_power_W in zip(durations, job_powers, strict=True):
            stop = min(n, start + int(duration))
            duration_sum += int(stop - start)
            truncated_jobs += int(start + int(duration) > n)
            difference[start] += float(job_power_W)
            difference[stop] -= float(job_power_W)
    unconstrained = config.bursty_idle_power_W + np.cumsum(difference[:-1])
    saturation = unconstrained > config.power_max_W
    # Capacity saturation is part of the scheduler, recorded explicitly; it is
    # unrelated to (and occurs before) the energy-matching control operation.
    power = np.minimum(unconstrained, config.power_max_W)
    return power, {
        "generator": "poisson_shot_noise_bursts_v1",
        "jobs_arrived": job_count,
        "mean_realised_burst_duration_s": (
            float(duration_sum / job_count) if job_count else 0.0
        ),
        "jobs_truncated_at_trace_end": truncated_jobs,
        "capacity_saturated_samples": int(np.count_nonzero(saturation)),
        "capacity_saturation_is_scheduler_semantics": True,
        "thermal_or_hot_state_observed": False,
    }


def generate_queue_driven_benign(
    *,
    time_s: np.ndarray,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W3: FIFO stochastic jobs with work-conserving compute dispatch."""

    _require_generator(rng)
    n = int(time_s.size)
    arrivals = rng.poisson(config.queue_arrival_rate_per_s, size=n)
    queue: deque[list[float | int]] = deque()
    power = np.zeros(n, dtype=np.float64)
    queue_depth = np.zeros(n, dtype=np.int64)
    backlog_J = np.zeros(n, dtype=np.float64)
    waiting_times_s: list[float] = []
    jobs_arrived = 0
    jobs_completed = 0
    gamma_scale_J = config.queue_mean_job_energy_J / config.queue_job_energy_shape

    for index, count in enumerate(arrivals):
        count_i = int(count)
        if count_i:
            energies = rng.gamma(config.queue_job_energy_shape, gamma_scale_J, size=count_i)
            for energy_J in energies:
                # [remaining_energy_J, arrival_index]
                queue.append([float(energy_J), index])
            jobs_arrived += count_i

        dispatch_budget_J = config.power_max_W * CANONICAL_DT_S
        initial_dispatch_budget_J = dispatch_budget_J
        while queue and dispatch_budget_J > 0.0:
            remaining_J = float(queue[0][0])
            served_J = min(remaining_J, dispatch_budget_J)
            remaining_J -= served_J
            dispatch_budget_J -= served_J
            # When a job consumes the exact remaining capacity, snap the
            # arithmetic residual to zero. This prevents an accumulated
            # floating-point sum from exceeding the scheduler's 40 kW budget
            # by a few ulps; it is not post-hoc workload clipping.
            if dispatch_budget_J < 4.0 * np.finfo(np.float64).eps * initial_dispatch_budget_J:
                dispatch_budget_J = 0.0
            if remaining_J <= 4.0 * np.finfo(np.float64).eps * max(1.0, served_J):
                _, arrival_index = queue.popleft()
                jobs_completed += 1
                waiting_times_s.append(float((index + 1 - int(arrival_index)) * CANONICAL_DT_S))
            else:
                queue[0][0] = remaining_J

        dispatched_J = initial_dispatch_budget_J - dispatch_budget_J
        power[index] = dispatched_J / CANONICAL_DT_S
        queue_depth[index] = len(queue)
        backlog_J[index] = math.fsum(float(job[0]) for job in queue)

    return power, {
        "generator": "fifo_poisson_queue_work_conserving_v1",
        "queue_policy": "FIFO; arrivals before dispatch; 40 kW work-conserving capacity",
        "jobs_arrived": jobs_arrived,
        "jobs_completed": jobs_completed,
        "unfinished_jobs": int(len(queue)),
        "max_queue_jobs": int(np.max(queue_depth, initial=0)),
        "mean_queue_jobs": float(np.mean(queue_depth)),
        "max_backlog_J": float(np.max(backlog_J, initial=0.0)),
        "mean_backlog_J": float(np.mean(backlog_J)),
        "mean_job_response_time_s": (
            float(np.mean(waiting_times_s)) if waiting_times_s else 0.0
        ),
        "max_job_response_time_s": (
            float(max(waiting_times_s)) if waiting_times_s else 0.0
        ),
        "raw_dispatch_utilization": float(np.mean(power) / config.power_max_W),
        "thermal_or_hot_state_observed": False,
    }


def generate_power_aware_benign(
    *,
    time_s: np.ndarray,
    power_availability: np.ndarray,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W4: benign policy observing electrical availability only.

    Deliberately, this function has no ``hot_mask`` or thermal-state argument.
    ``power_availability`` is a caller-defined, dimensionless electrical signal
    constrained to [0, 1].
    """

    _require_generator(rng)
    availability = _validate_signal(
        power_availability,
        name="power_availability",
        shape=time_s.shape,
        boolean=False,
    )
    if np.any(availability < 0.0) or np.any(availability > 1.0):
        raise ValueError("power_availability must be dimensionless and within [0, 1]")
    span_W = config.power_aware_high_W - config.power_aware_low_W
    conditional_mean = config.power_aware_low_W + span_W * availability
    power, rejected = _bounded_normal(
        rng,
        mean=conditional_mean,
        sigma=config.power_aware_jitter_sigma_W,
        size=int(time_s.size),
        lower=config.power_min_W,
        upper=config.power_max_W,
    )
    return power, {
        "generator": "electrical_availability_only_policy_v1",
        "allowed_policy_observation": "dimensionless electrical power availability [0,1]",
        "thermal_or_hot_state_observed": False,
        "availability_min": float(np.min(availability)),
        "availability_max": float(np.max(availability)),
        "availability_mean": float(np.mean(availability)),
        "jitter_rejected_draw_count": rejected,
        "bound_enforcement": "rejection sampling (no clipping)",
    }


def generate_phase_shaped_candidate(
    *,
    time_s: np.ndarray,
    measurement_mask: np.ndarray,
    hot_mask: np.ndarray,
    target_energy_J: float,
    rng: np.random.Generator,
    config: WorkloadConfig,
) -> tuple[np.ndarray, Mapping[str, Any]]:
    """W5: documented hot-indicator two-level adversarial candidate."""

    _require_generator(rng)
    hot = _validate_signal(hot_mask, name="hot_mask", shape=time_s.shape, boolean=True)
    measured_hot = int(np.count_nonzero(hot & measurement_mask))
    measured_n = int(np.count_nonzero(measurement_mask))
    measured_cold = measured_n - measured_hot
    target_mean_W = target_energy_J / (measured_n * CANONICAL_DT_S)

    if measured_hot == 0 or measured_cold == 0:
        high_W = target_mean_W
        low_W = target_mean_W
        degeneracy = "measurement interval contains only one phase"
    else:
        hot_fraction = measured_hot / measured_n
        high_W = config.power_max_W
        low_W = (target_mean_W - hot_fraction * high_W) / (1.0 - hot_fraction)
        if low_W < config.power_min_W:
            low_W = config.power_min_W
            high_W = (
                target_mean_W - (1.0 - hot_fraction) * config.power_min_W
            ) / hot_fraction
        degeneracy = None

    power = np.where(hot, high_W, low_W).astype(np.float64, copy=False)
    return power, {
        "generator": "reconstructed_hot_indicator_two_level_v1",
        "classification": "adversarial candidate; not a validated attack",
        "historical_status": (
            "reconstructed_from_v0.4.4_published_artifacts; release source code absent"
        ),
        "hot_power_W": float(high_W),
        "cold_power_W": float(low_W),
        "measurement_hot_fraction": float(measured_hot / measured_n),
        "degeneracy": degeneracy,
        "rng_draw_count": 0,
    }


def _canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def trace_sha256(power_W: Sequence[float] | np.ndarray) -> str:
    """Hash canonical little-endian float64 trace bytes."""

    power = np.asarray(power_W, dtype="<f8")
    if power.ndim != 1 or not np.all(np.isfinite(power)):
        raise ValueError("power_W must be a finite one-dimensional array")
    return hashlib.sha256(np.ascontiguousarray(power).tobytes(order="C")).hexdigest()


def _input_hash(
    *,
    time_s: np.ndarray,
    measurement_mask: np.ndarray,
    workload_id: str,
    hot_mask: np.ndarray | None = None,
    power_availability: np.ndarray | None = None,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"octm.wrb_001.workload_inputs.v1\0")
    hasher.update(workload_id.encode("ascii"))
    hasher.update(np.asarray(time_s, dtype="<f8").tobytes(order="C"))
    hasher.update(np.asarray(measurement_mask, dtype=np.uint8).tobytes(order="C"))
    if hot_mask is not None:
        hasher.update(b"hot_mask\0")
        hasher.update(np.asarray(hot_mask, dtype=np.uint8).tobytes(order="C"))
    if power_availability is not None:
        hasher.update(b"power_availability\0")
        hasher.update(np.asarray(power_availability, dtype="<f8").tobytes(order="C"))
    return hasher.hexdigest()


def _realization(
    *,
    workload_id: str,
    raw_power_W: np.ndarray,
    seed: int,
    lineage: RNGStreamLineage,
    time_s: np.ndarray,
    measurement_mask: np.ndarray,
    start: int,
    stop: int,
    target_energy_J: float,
    allowed_inputs: tuple[str, ...],
    generation_diagnostics: Mapping[str, Any],
    config: WorkloadConfig,
    input_sha256: str,
    skip_adjustment: bool = False,
) -> WorkloadRealization:
    if skip_adjustment:
        actual = sampled_energy_J(raw_power_W, measurement_mask, dt_s=CANONICAL_DT_S)
        match = EnergyMatchResult(
            power_W=_readonly_power(raw_power_W),
            valid=True,
            invalid_reason=None,
            sampled_energy_J=actual,
            target_energy_J=target_energy_J,
            relative_error=_relative_energy_error(actual, target_energy_J),
            diagnostics={
                "method": "reference_trace_no_adjustment",
                "measurement_sample_count": int(np.count_nonzero(measurement_mask)),
                "measurement_interval_semantics": (
                    "half-open; selected left-endpoint samples only"
                ),
                "raw_sampled_energy_J": actual,
                "requested_adjustment_J": 0.0,
                "applied_adjustment_J": 0.0,
                "outside_measurement_samples_modified": 0,
                "silent_clipping_used": False,
            },
        )
    else:
        match = match_sampled_energy(
            raw_power_W,
            measurement_mask,
            target_energy_J,
            dt_s=CANONICAL_DT_S,
            power_min_W=config.power_min_W,
            power_max_W=config.power_max_W,
            tolerance_fraction=config.energy_tolerance_fraction,
        )
    diagnostics = dict(generation_diagnostics)
    diagnostics["energy_match"] = dict(match.diagnostics)
    diagnostics["post_match_min_power_W"] = float(np.min(match.power_W))
    diagnostics["post_match_max_power_W"] = float(np.max(match.power_W))
    return WorkloadRealization(
        workload_id=workload_id,
        label=WORKLOAD_LABELS[workload_id],
        power_W=match.power_W,
        valid_run=match.valid,
        invalid_reason=match.invalid_reason,
        seed=seed,
        rng_seed=lineage.rng_seed,
        rng_stream=lineage.derivation_path,
        seed_lineage=lineage,
        trace_sha256=trace_sha256(match.power_W),
        configuration_sha256=_canonical_json_sha256(asdict(config)),
        input_sha256=input_sha256,
        target_energy_J=match.target_energy_J,
        sampled_energy_J=match.sampled_energy_J,
        relative_energy_error=match.relative_error,
        dt_s=CANONICAL_DT_S,
        measurement_start_index=start,
        measurement_stop_index=stop,
        measurement_interval_s=(float(time_s[start]), float(time_s[stop - 1] + CANONICAL_DT_S)),
        allowed_inputs=allowed_inputs,
        diagnostics=diagnostics,
    )


def generate_workloads(
    seed: int,
    time_s: np.ndarray,
    measurement_mask: np.ndarray,
    dt_s: float,
    hot_mask: np.ndarray,
    power_availability: np.ndarray,
    config: WorkloadConfig = WorkloadConfig(),
) -> OrderedDict[str, WorkloadRealization]:
    """Generate the six paired, equal-energy WRB-001 workload traces.

    W1 is generated first internally and its exact sampled measurement energy
    becomes the per-seed target.  The returned mapping is nevertheless in the
    canonical W0..W5 order.  Each family has a separately derived RNG stream.
    """

    seed_i = _require_seed(seed)
    if not isinstance(config, WorkloadConfig):
        raise TypeError("config must be a WorkloadConfig")
    time, measure, start, stop = _validate_grid_and_mask(time_s, measurement_mask, dt_s)
    hot = _validate_signal(hot_mask, name="hot_mask", shape=time.shape, boolean=True)
    availability = _validate_signal(
        power_availability,
        name="power_availability",
        shape=time.shape,
        boolean=False,
    )
    if np.any(availability < 0.0) or np.any(availability > 1.0):
        raise ValueError("power_availability must be dimensionless and within [0, 1]")

    streams = {
        workload_id: make_workload_rng(
            seed_i, workload_id, campaign_id=config.campaign_id
        )
        for workload_id in WORKLOAD_IDS
    }

    w1_rng, w1_lineage = streams[W1_DIVERSIFIED_STOCHASTIC]
    w1_raw, w1_diagnostics = generate_diversified_stochastic(
        time_s=time, rng=w1_rng, config=config
    )
    target_energy_J = sampled_energy_J(w1_raw, measure, dt_s=CANONICAL_DT_S)
    w1 = _realization(
        workload_id=W1_DIVERSIFIED_STOCHASTIC,
        raw_power_W=w1_raw,
        seed=seed_i,
        lineage=w1_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "rng"),
        generation_diagnostics=w1_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time, measurement_mask=measure, workload_id=W1_DIVERSIFIED_STOCHASTIC
        ),
        skip_adjustment=True,
    )

    w0_rng, w0_lineage = streams[W0_CONSTANT_REFERENCE]
    w0_raw, w0_diagnostics = generate_constant_reference(
        time_s=time,
        target_energy_J=target_energy_J,
        measurement_sample_count=stop - start,
        rng=w0_rng,
        config=config,
    )
    w0 = _realization(
        workload_id=W0_CONSTANT_REFERENCE,
        raw_power_W=w0_raw,
        seed=seed_i,
        lineage=w0_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "rng"),
        generation_diagnostics=w0_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time, measurement_mask=measure, workload_id=W0_CONSTANT_REFERENCE
        ),
    )

    w2_rng, w2_lineage = streams[W2_BURSTY_BENIGN]
    w2_raw, w2_diagnostics = generate_bursty_benign(
        time_s=time, rng=w2_rng, config=config
    )
    w2 = _realization(
        workload_id=W2_BURSTY_BENIGN,
        raw_power_W=w2_raw,
        seed=seed_i,
        lineage=w2_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "rng"),
        generation_diagnostics=w2_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time, measurement_mask=measure, workload_id=W2_BURSTY_BENIGN
        ),
    )

    w3_rng, w3_lineage = streams[W3_QUEUE_DRIVEN_BENIGN]
    w3_raw, w3_diagnostics = generate_queue_driven_benign(
        time_s=time, rng=w3_rng, config=config
    )
    w3 = _realization(
        workload_id=W3_QUEUE_DRIVEN_BENIGN,
        raw_power_W=w3_raw,
        seed=seed_i,
        lineage=w3_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "rng"),
        generation_diagnostics=w3_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time, measurement_mask=measure, workload_id=W3_QUEUE_DRIVEN_BENIGN
        ),
    )

    w4_rng, w4_lineage = streams[W4_POWER_AWARE_BENIGN]
    w4_raw, w4_diagnostics = generate_power_aware_benign(
        time_s=time,
        power_availability=availability,
        rng=w4_rng,
        config=config,
    )
    w4 = _realization(
        workload_id=W4_POWER_AWARE_BENIGN,
        raw_power_W=w4_raw,
        seed=seed_i,
        lineage=w4_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "power_availability", "rng"),
        generation_diagnostics=w4_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time,
            measurement_mask=measure,
            workload_id=W4_POWER_AWARE_BENIGN,
            power_availability=availability,
        ),
    )

    w5_rng, w5_lineage = streams[W5_PHASE_SHAPED_CANDIDATE]
    w5_raw, w5_diagnostics = generate_phase_shaped_candidate(
        time_s=time,
        measurement_mask=measure,
        hot_mask=hot,
        target_energy_J=target_energy_J,
        rng=w5_rng,
        config=config,
    )
    w5 = _realization(
        workload_id=W5_PHASE_SHAPED_CANDIDATE,
        raw_power_W=w5_raw,
        seed=seed_i,
        lineage=w5_lineage,
        time_s=time,
        measurement_mask=measure,
        start=start,
        stop=stop,
        target_energy_J=target_energy_J,
        allowed_inputs=("time_s", "hot_mask", "rng"),
        generation_diagnostics=w5_diagnostics,
        config=config,
        input_sha256=_input_hash(
            time_s=time,
            measurement_mask=measure,
            workload_id=W5_PHASE_SHAPED_CANDIDATE,
            hot_mask=hot,
        ),
    )

    return OrderedDict(
        (
            (W0_CONSTANT_REFERENCE, w0),
            (W1_DIVERSIFIED_STOCHASTIC, w1),
            (W2_BURSTY_BENIGN, w2),
            (W3_QUEUE_DRIVEN_BENIGN, w3),
            (W4_POWER_AWARE_BENIGN, w4),
            (W5_PHASE_SHAPED_CANDIDATE, w5),
        )
    )


__all__ = [
    "CAMPAIGN_ID",
    "CANONICAL_DT_S",
    "INVALID_ENERGY_MATCH",
    "MODEL_WORKLOAD_VERSION",
    "POWER_MAX_W",
    "POWER_MIN_W",
    "WORKLOAD_IDS",
    "WORKLOAD_LABELS",
    "W0_CONSTANT_REFERENCE",
    "W1_DIVERSIFIED_STOCHASTIC",
    "W2_BURSTY_BENIGN",
    "W3_QUEUE_DRIVEN_BENIGN",
    "W4_POWER_AWARE_BENIGN",
    "W5_PHASE_SHAPED_CANDIDATE",
    "EnergyMatchResult",
    "RNGStreamLineage",
    "WorkloadConfig",
    "WorkloadRealization",
    "derive_workload_seed",
    "generate_bursty_benign",
    "generate_constant_reference",
    "generate_diversified_stochastic",
    "generate_phase_shaped_candidate",
    "generate_power_aware_benign",
    "generate_queue_driven_benign",
    "generate_workloads",
    "make_workload_rng",
    "match_sampled_energy",
    "sampled_energy_J",
    "trace_sha256",
]
