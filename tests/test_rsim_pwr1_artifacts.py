from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "RSIM-001-PWR1"


def _load_json(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_pwr1_artifact_set_and_run_contract() -> None:
    assert {path.name for path in RESULTS.iterdir() if path.is_file()} == {
        "runs.csv", "runs.jsonl", "summary.json",
        "comparison_A0M_A0R.json", "invariants.json",
    }
    rows = [
        json.loads(line)
        for line in (RESULTS / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 240
    assert all(row["valid_run"] for row in rows)
    assert all(row["invalid_reason"] is None for row in rows)
    assert not any(row["warmup_power_deficit_flag"] for row in rows)
    assert all(row["invariants"]["compute_denial_attribution_closes"] for row in rows)
    assert all(row["invariants"]["soc_within_bounds"] for row in rows)
    assert all(row["invariants"]["electrical_balance_closes"] for row in rows)


def test_pwr1_summary_comparison_and_frozen_a0m_provenance() -> None:
    summary = _load_json("summary.json")
    comparison = _load_json("comparison_A0M_A0R.json")
    invariants = _load_json("invariants.json")
    assert summary["run_count"] == summary["valid_run_count"] == 240
    assert summary["system_power_deficit_run_count"] == 0
    assert comparison["A0M_system_power_deficit_run_count"] == 140
    assert comparison["A0R_system_power_deficit_run_count"] == 0
    frozen = ROOT / comparison["frozen_A0M_runs_path"]
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == comparison["frozen_A0M_runs_sha256"]
    assert invariants["all_required_invariants_pass"]
