"""Deterministic statistics for the WRB-001 robustness campaign.

The campaign is an exploratory characterization using the canonical v0.4.4
TSM-01 model. These helpers deliberately reject non-finite values instead of letting
NaN or infinity leak into authoritative output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
import math

import numpy as np


DESCRIPTIVE_KEYS = (
    "n",
    "mean",
    "median",
    "std",
    "min",
    "max",
    "p05",
    "p25",
    "p75",
    "p95",
)


def _finite_array(values: Iterable[float], *, name: str = "values") -> np.ndarray:
    array = np.asarray(list(values), dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains NaN or infinity")
    return array


def descriptive_statistics(values: Iterable[float]) -> dict[str, int | float | None]:
    """Return the preregistered descriptive statistics for finite values."""

    array = _finite_array(values)
    if array.size == 0:
        return {key: 0 if key == "n" else None for key in DESCRIPTIVE_KEYS}

    quantiles = np.quantile(array, [0.05, 0.25, 0.75, 0.95], method="linear")
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "std": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "p05": float(quantiles[0]),
        "p25": float(quantiles[1]),
        "p75": float(quantiles[2]),
        "p95": float(quantiles[3]),
    }


def bootstrap_median_ci(
    values: Iterable[float],
    *,
    seed: int,
    resamples: int,
    confidence: float = 0.95,
) -> dict[str, int | float | str | None]:
    """Percentile bootstrap interval for the median of paired-seed deltas.

    Each input value is already a within-seed paired difference.  Resampling
    these values therefore resamples paired seed indices, not individual runs.
    """

    array = _finite_array(values)
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between zero and one")
    if array.size == 0:
        return {
            "low": None,
            "high": None,
            "confidence": float(confidence),
            "method": "paired_seed_percentile_median",
            "resamples": int(resamples),
            "bootstrap_seed": int(seed),
        }

    rng = np.random.default_rng(seed)
    sample_indices = rng.integers(0, array.size, size=(resamples, array.size))
    medians = np.median(array[sample_indices], axis=1)
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(medians, [alpha, 1.0 - alpha], method="linear")
    return {
        "low": float(low),
        "high": float(high),
        "confidence": float(confidence),
        "method": "paired_seed_percentile_median",
        "resamples": int(resamples),
        "bootstrap_seed": int(seed),
    }


def summarize_paired_delta(
    values: Iterable[float], *, bootstrap_seed: int, bootstrap_resamples: int
) -> dict[str, Any]:
    array = _finite_array(values)
    summary = descriptive_statistics(array)
    summary["bootstrap_95_ci"] = bootstrap_median_ci(
        array,
        seed=bootstrap_seed,
        resamples=bootstrap_resamples,
        confidence=0.95,
    )
    return summary


def benign_ratio(
    numerator_delta_K: float,
    denominator_delta_K: float,
    *,
    denominator_tolerance_K: float,
) -> dict[str, float | str | None]:
    """Return W4/W5 for one seed with an explicit denominator status."""

    numerator = float(numerator_delta_K)
    denominator = float(denominator_delta_K)
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return {"value": None, "status": "NONFINITE_INPUT"}
    if denominator_tolerance_K <= 0.0:
        raise ValueError("denominator_tolerance_K must be positive")
    if abs(denominator) <= denominator_tolerance_K:
        return {"value": None, "status": "NEAR_ZERO_DENOMINATOR"}
    ratio = numerator / denominator
    if not math.isfinite(ratio):
        return {"value": None, "status": "NONFINITE_RESULT"}
    return {"value": float(ratio), "status": "VALID"}


@dataclass(frozen=True)
class ClassificationConfig:
    """Exploratory, campaign-specific decision rule (not a safety threshold)."""

    material_delta_K: float = 1.0
    robust_min_benign_families: int = 2
    benign_workload_ids: tuple[str, ...] = (
        "diversified_stochastic",
        "bursty_benign",
        "queue_driven_benign",
        "power_aware_benign",
    )
    shaped_workload_id: str = "phase_shaped_candidate"


def classify_robustness(
    workload_summaries: Mapping[str, Mapping[str, Any]],
    config: ClassificationConfig,
) -> dict[str, Any]:
    """Classify timing sensitivity without making an attack-validity claim.

    A family is material when its median paired delta reaches the configured
    magnitude and its 95% bootstrap interval excludes zero in the same
    direction.  ROBUST requires the shaped candidate plus multiple benign
    families.  CONDITIONAL covers a shaped effect with fewer benign families.
    """

    if config.material_delta_K <= 0.0:
        raise ValueError("material_delta_K must be positive")
    if config.robust_min_benign_families < 2:
        raise ValueError("ROBUST must require multiple benign families")

    def material(summary: Mapping[str, Any] | None) -> bool:
        if not summary or not summary.get("n"):
            return False
        median = summary.get("median")
        ci = summary.get("bootstrap_95_ci") or {}
        low, high = ci.get("low"), ci.get("high")
        if None in (median, low, high):
            return False
        if median >= config.material_delta_K:
            return low > 0.0
        if median <= -config.material_delta_K:
            return high < 0.0
        return False

    benign_material = [
        workload_id
        for workload_id in config.benign_workload_ids
        if material(workload_summaries.get(workload_id))
    ]
    shaped_material = material(workload_summaries.get(config.shaped_workload_id))

    if shaped_material and len(benign_material) >= config.robust_min_benign_families:
        label = "ROBUST"
    elif shaped_material or benign_material:
        label = "CONDITIONAL"
    else:
        label = "NOT_ROBUST"

    return {
        "label": label,
        "scope": "workload-timing sensitivity using the canonical v0.4.4 TSM-01 baseline",
        "attack_validation": False,
        "material_delta_K": float(config.material_delta_K),
        "robust_min_benign_families": int(config.robust_min_benign_families),
        "material_benign_workloads": benign_material,
        "phase_shaped_candidate_material": bool(shaped_material),
        "rule": (
            "material median absolute paired delta with a same-direction "
            "paired-seed percentile-bootstrap 95% interval excluding zero"
        ),
    }


def json_safe(value: Any) -> Any:
    """Convert NumPy/scalar containers and reject non-finite numerics."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("authoritative output contains NaN or infinity")
        return converted
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (Sequence, np.ndarray)) and not isinstance(value, (str, bytes)):
        return [json_safe(item) for item in value]
    raise TypeError(f"unsupported authoritative-output type: {type(value)!r}")
