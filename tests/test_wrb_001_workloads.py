from __future__ import annotations

import inspect

import numpy as np
import pytest

from src.octm.baselines.v044 import thermal_model as canonical_v044

from wrb_001_workloads import (
    CANONICAL_DT_S,
    INVALID_ENERGY_MATCH,
    POWER_MAX_W,
    WORKLOAD_IDS,
    W0_CONSTANT_REFERENCE,
    W1_DIVERSIFIED_STOCHASTIC,
    W3_QUEUE_DRIVEN_BENIGN,
    W4_POWER_AWARE_BENIGN,
    W5_PHASE_SHAPED_CANDIDATE,
    WorkloadConfig,
    derive_workload_seed,
    generate_diversified_stochastic,
    generate_power_aware_benign,
    generate_workloads,
    make_workload_rng,
    match_sampled_energy,
    sampled_energy_J,
    trace_sha256,
)


@pytest.fixture
def campaign_inputs() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = 1_200
    time_s = np.arange(n, dtype=np.float64)
    measurement_mask = np.zeros(n, dtype=bool)
    measurement_mask[200:1_100] = True
    hot_mask = np.asarray(canonical_v044.in_hot_phase(time_s, canonical_v044.P), dtype=bool)
    # This is an abstract electrical signal, not the thermal hot indicator.
    power_availability = 0.15 + 0.85 * (0.5 + 0.5 * np.sin(time_s / 73.0))
    return time_s, measurement_mask, hot_mask, power_availability


def test_all_workloads_are_finite_bounded_valid_and_canonically_ordered(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    workloads = generate_workloads(7, *campaign_inputs[:2], 1.0, *campaign_inputs[2:])

    assert tuple(workloads) == WORKLOAD_IDS
    for workload_id, realization in workloads.items():
        assert realization.workload_id == workload_id
        assert realization.valid_run is True
        assert realization.invalid_reason is None
        assert realization.dt_s == CANONICAL_DT_S
        assert realization.power_W.shape == campaign_inputs[0].shape
        assert np.all(np.isfinite(realization.power_W))
        assert np.all(realization.power_W >= 0.0)
        assert np.all(realization.power_W <= POWER_MAX_W)
        assert realization.power_W.flags.writeable is False
        assert realization.trace_sha256 == trace_sha256(realization.power_W)
        assert len(realization.trace_sha256) == 64


def test_every_family_matches_this_seeds_w1_sampled_energy(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    _, measurement_mask, _, _ = campaign_inputs
    workloads = generate_workloads(37, *campaign_inputs[:2], 1.0, *campaign_inputs[2:])
    reference = workloads[W1_DIVERSIFIED_STOCHASTIC]

    for realization in workloads.values():
        recomputed = sampled_energy_J(realization.power_W, measurement_mask, dt_s=1.0)
        assert recomputed == realization.sampled_energy_J
        assert realization.target_energy_J == reference.sampled_energy_J
        assert realization.relative_energy_error <= 1.0e-3
        assert recomputed == pytest.approx(reference.sampled_energy_J, rel=1.0e-12)

    expected_constant = reference.sampled_energy_J / np.count_nonzero(measurement_mask)
    np.testing.assert_array_equal(
        workloads[W0_CONSTANT_REFERENCE].power_W,
        np.full(campaign_inputs[0].size, expected_constant),
    )


def test_same_seed_is_byte_deterministic_and_global_rng_independent(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    first = generate_workloads(19, *campaign_inputs[:2], 1.0, *campaign_inputs[2:])
    np.random.seed(12345)
    _ = np.random.random(10_000)
    second = generate_workloads(19, *campaign_inputs[:2], 1.0, *campaign_inputs[2:])

    assert [w.trace_sha256 for w in first.values()] == [
        w.trace_sha256 for w in second.values()
    ]
    for workload_id in WORKLOAD_IDS:
        np.testing.assert_array_equal(
            first[workload_id].power_W, second[workload_id].power_W
        )


def test_workload_subseeds_are_stable_unique_and_order_independent() -> None:
    forward = {workload_id: derive_workload_seed(12, workload_id) for workload_id in WORKLOAD_IDS}
    reverse = {
        workload_id: derive_workload_seed(12, workload_id)
        for workload_id in reversed(WORKLOAD_IDS)
    }
    assert forward == reverse
    assert len(set(forward.values())) == len(WORKLOAD_IDS)
    assert forward != {
        workload_id: derive_workload_seed(13, workload_id) for workload_id in WORKLOAD_IDS
    }

    rng, lineage = make_workload_rng(12, W1_DIVERSIFIED_STOCHASTIC)
    assert isinstance(rng, np.random.Generator)
    assert lineage.rng_seed == forward[W1_DIVERSIFIED_STOCHASTIC]
    assert lineage.rng_algorithm == "numpy.PCG64 (default_rng)"
    assert lineage.derivation_path.endswith("diversified_stochastic/generation")


def test_family_rng_is_mandatory_and_must_be_generator() -> None:
    time_s = np.arange(5, dtype=np.float64)
    with pytest.raises(TypeError, match="explicit numpy.random.Generator"):
        generate_diversified_stochastic(
            time_s=time_s, rng=None, config=WorkloadConfig()  # type: ignore[arg-type]
        )


def test_matching_uses_half_open_mask_and_never_changes_warmup() -> None:
    raw = np.array([1_000.0, 2_000.0, 3_000.0, 4_000.0, 5_000.0])
    measurement = np.array([False, True, True, True, False])
    target_J = 18_000.0
    result = match_sampled_energy(raw, measurement, target_J, dt_s=1.0)

    assert result.valid
    assert result.sampled_energy_J == target_J
    np.testing.assert_array_equal(result.power_W[~measurement], raw[~measurement])
    assert result.diagnostics["outside_measurement_samples_modified"] == 0
    assert result.diagnostics["measurement_interval_semantics"].startswith("half-open")


def test_infeasible_energy_target_is_explicit_and_not_clipped() -> None:
    raw = np.array([1_000.0, 2_000.0, 3_000.0])
    measurement = np.array([False, True, True])
    impossible_target_J = 2.0 * POWER_MAX_W + 1.0
    result = match_sampled_energy(raw, measurement, impossible_target_J, dt_s=1.0)

    assert result.valid is False
    assert result.invalid_reason == INVALID_ENERGY_MATCH
    np.testing.assert_array_equal(result.power_W, raw)
    assert result.diagnostics["applied_adjustment_J"] == 0.0
    assert result.diagnostics["silent_clipping_used"] is False
    assert "outside the bounded interval" in result.diagnostics["failure_detail"]


def test_power_aware_generator_cannot_receive_hot_or_thermal_state(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    parameters = inspect.signature(generate_power_aware_benign).parameters
    assert "hot_mask" not in parameters
    assert not any("thermal" in parameter for parameter in parameters)

    _, _, _, availability = campaign_inputs
    rng, _ = make_workload_rng(3, W4_POWER_AWARE_BENIGN)
    power, diagnostics = generate_power_aware_benign(
        time_s=campaign_inputs[0],
        power_availability=availability,
        rng=rng,
        config=WorkloadConfig(),
    )
    assert power.shape == campaign_inputs[0].shape
    assert diagnostics["thermal_or_hot_state_observed"] is False


def test_noncanonical_hot_mask_is_rejected(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    time_s, measurement, hot, availability = campaign_inputs
    shifted_hot = hot.copy()
    shifted_hot[0] = ~shifted_hot[0]
    with pytest.raises(ValueError, match="canonical v0.4.4"):
        generate_workloads(8, time_s, measurement, 1.0, shifted_hot, availability)


def test_changing_availability_changes_w4_but_not_w5(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    time_s, measurement, hot, availability = campaign_inputs
    first = generate_workloads(9, time_s, measurement, 1.0, hot, availability)
    inverse_availability = 1.0 - availability
    second = generate_workloads(
        9, time_s, measurement, 1.0, hot, inverse_availability
    )
    assert first[W4_POWER_AWARE_BENIGN].trace_sha256 != second[W4_POWER_AWARE_BENIGN].trace_sha256
    assert first[W5_PHASE_SHAPED_CANDIDATE].trace_sha256 == second[W5_PHASE_SHAPED_CANDIDATE].trace_sha256


def test_queue_driven_diagnostics_record_real_queue_metrics(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    result = generate_workloads(
        22, *campaign_inputs[:2], 1.0, *campaign_inputs[2:]
    )[W3_QUEUE_DRIVEN_BENIGN]
    expected_metrics = {
        "jobs_arrived",
        "jobs_completed",
        "unfinished_jobs",
        "max_queue_jobs",
        "mean_queue_jobs",
        "max_backlog_J",
        "mean_backlog_J",
        "mean_job_response_time_s",
        "max_job_response_time_s",
        "raw_dispatch_utilization",
    }
    assert expected_metrics <= result.diagnostics.keys()
    assert result.diagnostics["jobs_arrived"] > 0
    assert result.diagnostics["jobs_completed"] > 0
    assert result.diagnostics["thermal_or_hot_state_observed"] is False


@pytest.mark.parametrize(
    ("time_s", "measurement", "dt_s", "message"),
    [
        (np.arange(10, dtype=float) * 2.0, np.ones(10, dtype=bool), 1.0, "canonical grid"),
        (np.arange(10, dtype=float), np.ones(10, dtype=bool), 0.5, "dt_s = 1.0"),
        (
            np.arange(10, dtype=float),
            np.array([False, True, True, False, True, True, False, False, False, False]),
            1.0,
            "contiguous half-open",
        ),
    ],
)
def test_noncanonical_grid_or_measurement_window_is_rejected(
    time_s: np.ndarray,
    measurement: np.ndarray,
    dt_s: float,
    message: str,
) -> None:
    hot = np.zeros(10, dtype=bool)
    availability = np.ones(10, dtype=float) * 0.5
    with pytest.raises(ValueError, match=message):
        generate_workloads(0, time_s, measurement, dt_s, hot, availability)


def test_w1_and_w5_disclose_canonical_source_and_candidate_status(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    workloads = generate_workloads(5, *campaign_inputs[:2], 1.0, *campaign_inputs[2:])
    assert workloads[W1_DIVERSIFIED_STOCHASTIC].diagnostics["historical_status"] == (
        "canonical_manifested_source"
    )
    w5 = workloads[W5_PHASE_SHAPED_CANDIDATE]
    assert w5.diagnostics["historical_status"] == "canonical_manifested_source"
    assert w5.diagnostics["classification"] == "adversarial candidate; not a validated attack"
    assert "adversarial candidate" in w5.label


def test_w1_wrapper_is_exact_canonical_historical_generator(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    time_s = campaign_inputs[0]
    wrapper_rng = np.random.default_rng(1234)
    direct_rng = np.random.default_rng(1234)
    wrapped, diagnostics = generate_diversified_stochastic(
        time_s=time_s, rng=wrapper_rng, config=WorkloadConfig()
    )
    direct = canonical_v044.load_nominal(time_s, canonical_v044.P, direct_rng)
    np.testing.assert_array_equal(wrapped, direct)
    assert diagnostics["generator"] == "canonical_v0.4.4.load_nominal"


def test_w5_wrapper_is_exact_canonical_historical_generator_before_energy_match(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    from wrb_001_workloads import generate_phase_shaped_candidate

    time_s, measurement, hot, _ = campaign_inputs
    wrapper_rng = np.random.default_rng(5678)
    direct_rng = np.random.default_rng(5678)
    wrapped, diagnostics = generate_phase_shaped_candidate(
        time_s=time_s,
        measurement_mask=measurement,
        hot_mask=hot,
        target_energy_J=1.0,
        rng=wrapper_rng,
        config=WorkloadConfig(),
    )
    direct = canonical_v044.load_phase_locked(time_s, canonical_v044.P, direct_rng)
    np.testing.assert_array_equal(wrapped, direct)
    assert diagnostics["generator"] == "canonical_v0.4.4.load_phase_locked"


def test_availability_contract_rejects_implicit_units(
    campaign_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    time_s, measurement, hot, _ = campaign_inputs
    availability_in_watts = np.full(time_s.size, 30_000.0)
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        generate_workloads(0, time_s, measurement, 1.0, hot, availability_in_watts)


def test_queue_dispatch_never_exceeds_capacity_across_many_seeds() -> None:
    from wrb_001_workloads import WorkloadConfig, generate_queue_driven_benign

    time_s = np.arange(600, dtype=np.float64)
    config = WorkloadConfig()
    for seed in range(25):
        power_W, _ = generate_queue_driven_benign(
            time_s=time_s,
            rng=np.random.default_rng(seed),
            config=config,
        )
        assert np.min(power_W) >= config.power_min_W
        assert np.max(power_W) <= config.power_max_W
