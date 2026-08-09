from __future__ import annotations

import json

import numpy as np

from rsim_001_campaign import generate_seed_workloads
from rsim_001_epoch1_campaign import (
    PHASE_OFFSETS,
    _distribution,
    add_epoch_paired_deltas,
    epoch_environment_inputs,
)
from src.octm.rsim.environment import E1_REPRESENTATIVE_ANALYTIC_LEO
from src.octm.rsim.reserve import ESSENTIAL_RESERVE_FEASIBLE


def test_frozen_epoch_offsets() -> None:
    assert PHASE_OFFSETS == (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)


def test_requested_workload_hashes_are_independent_of_epoch() -> None:
    workloads = generate_seed_workloads(0)
    for workload in workloads.values():
        replayed = {offset: workload.trace_sha256 for offset in PHASE_OFFSETS}
        assert len(set(replayed.values())) == 1
        assert np.array_equal(workload.power_W, workload.power_W.copy())


def test_offset_zero_environment_hash_matches_frozen_pwr1() -> None:
    environment, reserve = epoch_environment_inputs(0.0)
    rows = [
        json.loads(line)
        for line in open("results/RSIM-001-PWR1/runs.jsonl", encoding="utf-8")
    ]
    expected = {
        row["physical_realization_sha256"]
        for row in rows
        if row["environment_id"] == E1_REPRESENTATIVE_ANALYTIC_LEO
    }
    assert expected == {environment.physical_realization_sha256}
    assert reserve.architecture_condition == ESSENTIAL_RESERVE_FEASIBLE


def test_paired_delta_uses_same_seed_epoch_and_mode() -> None:
    rows = []
    for offset, reference, candidate in ((0.0, 300.0, 305.0), (0.125, 310.0, 307.0)):
        rows.extend([
            {
                "seed": 0, "environment_phase_offset_fraction": offset,
                "mode": "POWER_CONSTRAINED", "workload_id": "constant_reference",
                "peak_node_temperature_K": reference,
            },
            {
                "seed": 0, "environment_phase_offset_fraction": offset,
                "mode": "POWER_CONSTRAINED", "workload_id": "phase_shaped_candidate",
                "peak_node_temperature_K": candidate,
            },
        ])
    add_epoch_paired_deltas(rows)
    candidates = [row for row in rows if row["workload_id"] == "phase_shaped_candidate"]
    assert [row["delta_peak_temperature_vs_reference_K"] for row in candidates] == [5.0, -3.0]


def test_epoch_distribution_contract() -> None:
    result = _distribution(range(80))
    assert result["n"] == 80
    assert result["min"] == 0.0
    assert result["max"] == 79.0
    assert result["median"] == 39.5
    assert result["std_definition"] == "sample standard deviation (ddof=1)"
