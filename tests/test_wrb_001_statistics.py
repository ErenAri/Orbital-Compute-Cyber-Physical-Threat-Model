from __future__ import annotations

import math

import pytest

from wrb_001_statistics import (
    ClassificationConfig,
    benign_ratio,
    classify_robustness,
    descriptive_statistics,
    json_safe,
    summarize_paired_delta,
)


def test_descriptive_statistics_are_sample_based_and_complete() -> None:
    result = descriptive_statistics([1.0, 2.0, 3.0])
    assert result["n"] == 3
    assert result["mean"] == 2.0
    assert result["median"] == 2.0
    assert result["std"] == 1.0
    assert set(result) == {"n", "mean", "median", "std", "min", "max", "p05", "p25", "p75", "p95"}


def test_bootstrap_is_deterministic() -> None:
    first = summarize_paired_delta(range(20), bootstrap_seed=1701, bootstrap_resamples=500)
    second = summarize_paired_delta(range(20), bootstrap_seed=1701, bootstrap_resamples=500)
    assert first == second


def test_ratio_handles_near_zero_denominator() -> None:
    result = benign_ratio(2.0, 1e-10, denominator_tolerance_K=1e-6)
    assert result == {"value": None, "status": "NEAR_ZERO_DENOMINATOR"}
    assert benign_ratio(2.0, 4.0, denominator_tolerance_K=1e-6)["value"] == 0.5


def test_classifier_requires_multiple_benign_families_for_robust() -> None:
    def summary(median: float) -> dict:
        return {
            "n": 100,
            "median": median,
            "bootstrap_95_ci": {"low": median - 0.2, "high": median + 0.2},
        }

    summaries = {
        "phase_shaped_candidate": summary(4.0),
        "bursty_benign": summary(2.0),
        "queue_driven_benign": summary(1.5),
    }
    result = classify_robustness(summaries, ClassificationConfig())
    assert result["label"] == "ROBUST"
    assert result["attack_validation"] is False


def test_nonfinite_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        descriptive_statistics([1.0, math.nan])
    with pytest.raises(ValueError):
        json_safe({"bad": math.inf})
