from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rsim_001_epoch1_campaign import PHASE_OFFSETS


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "RSIM-001-EPOCH1"


def _load(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_epoch1_artifact_set_and_run_contract() -> None:
    assert {path.name for path in RESULTS.iterdir() if path.is_file()} == {
        "runs.csv", "runs.jsonl", "summary.json", "epoch_response.json",
        "invariants.json",
    }
    rows = [
        json.loads(line)
        for line in (RESULTS / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 960
    assert all(row["valid_run"] for row in rows)
    assert all(row["invalid_reason"] is None for row in rows)
    assert not any(row["warmup_power_deficit_flag"] for row in rows)
    assert {row["environment_phase_offset_fraction"] for row in rows} == set(PHASE_OFFSETS)
    assert all(row["invariants"]["electrical_balance_closes"] for row in rows)
    assert all(row["invariants"]["soc_within_bounds"] for row in rows)

    pairs: dict[tuple[int, str], set[str]] = {}
    for row in rows:
        key = (row["seed"], row["workload_id"])
        pairs.setdefault(key, set()).add(row["requested_workload_trace_sha256"])
    assert len(pairs) == 60
    assert all(len(hashes) == 1 for hashes in pairs.values())


def test_epoch1_summary_response_and_invariants() -> None:
    summary = _load("summary.json")
    response = _load("epoch_response.json")
    invariants = _load("invariants.json")
    assert summary["run_count"] == summary["valid_run_count"] == 960
    assert summary["invalid_run_count"] == summary["system_power_deficit_run_count"] == 0
    assert summary["automatic_classification"] is None
    assert len(response["distributions"]) == 12
    assert len(response["per_epoch"]) == 96
    assert all(item["paired_seed_epoch_count"] == 80 for item in response["distributions"])
    assert invariants["all_required_invariants_pass"]
    assert invariants["results"]["deterministic_rerun_identical"]["status"] == "PASS"
    assert invariants["offset_zero_reproduction"]["matched_run_count"] == 120
    assert invariants["offset_zero_reproduction"]["mismatch_count"] == 0
    frozen = ROOT / invariants["offset_zero_reproduction"]["frozen_PWR1_runs_path"]
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == invariants[
        "offset_zero_reproduction"
    ]["frozen_PWR1_runs_sha256"]
