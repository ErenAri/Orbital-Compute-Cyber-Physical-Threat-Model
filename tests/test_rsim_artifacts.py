from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import re


RESULTS = Path("results/RSIM-001-smoke")


def _rows() -> list[dict]:
    return [json.loads(line) for line in (RESULTS / "runs.jsonl").read_text(encoding="utf-8").splitlines()]


def test_smoke_artifact_count_scope_and_pairing() -> None:
    rows = _rows()
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    assert len(rows) == summary["run_count"] == 360
    assert summary["authoritative_scientific_result"] is False
    assert summary["automatic_classification"] is None
    assert summary["valid_run_count"] + summary["invalid_run_count"] == 360
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["seed"], row["workload_id"])].append(row)
        assert row["workload_id"] != "attack"
        assert "validated attack" not in row["workload_label"].lower()
    assert len(grouped) == 60
    for members in grouped.values():
        assert len(members) == 6
        assert all(set(row) == set(members[0]) for row in members)
        assert len({row["requested_workload_trace_sha256"] for row in members}) == 1
        assert len({row["requested_compute_energy_J"] for row in members}) == 1


def test_all_required_invariants_pass_and_invalid_runs_are_explicit() -> None:
    report = json.loads((RESULTS / "invariants.json").read_text(encoding="utf-8"))
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    assert report["all_required_invariants_pass"] is True
    for name, result in report["results"].items():
        if name != "initialization_domination_flag":
            assert result["status"] == "PASS"
            assert result["pass_count"] == result["evaluated_run_count"] == 360
    assert all(item["reason"] == "SYSTEM_POWER_DEFICIT" for item in summary["invalid_runs"])


def test_e0_thermal_only_artifact_matches_existing_wrb() -> None:
    existing = {
        (row["seed"], row["workload_id"]): row
        for row in (
            json.loads(line) for line in Path("results/WRB-001/runs.jsonl").read_text(encoding="utf-8").splitlines()
        )
        if row["seed"] < 10
    }
    for row in _rows():
        if row["environment_id"] == "E0_CANONICAL" and row["mode"] == "THERMAL_ONLY":
            expected = existing[(row["seed"], row["workload_id"])]
            assert row["peak_node_temperature_K"] == expected["peak_node_temperature_K"]
            assert row["peak_radiator_temperature_K"] == expected["peak_radiator_temperature_K"]
            assert row["delta_peak_temperature_vs_reference_K"] == expected["delta_peak_temperature_vs_reference_K"]


def test_normative_artifacts_are_finite_and_have_no_machine_local_paths() -> None:
    pattern = re.compile(r"(?i)(C:/Users/|C:\\\\Users\\\\|/home/[^/]+/|Desktop/)")
    for path in [
        *RESULTS.glob("*.json"), RESULTS / "runs.jsonl", RESULTS / "runs.csv",
        Path("evidence/rsim001_parameters.json"),
        Path("experiments/RSIM-001/config.json"),
        Path("experiments/RSIM-001/architecture_A0.json"),
    ]:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), path
        if path.suffix == ".json":
            value = json.loads(text)

            def walk(item: object) -> None:
                if isinstance(item, float):
                    assert math.isfinite(item)
                elif isinstance(item, dict):
                    for nested in item.values():
                        walk(nested)
                elif isinstance(item, list):
                    for nested in item:
                        walk(nested)

            walk(value)


def test_run_schema_exactly_covers_every_serialized_field() -> None:
    schema = json.loads(Path("schemas/rsim_001.schema.json").read_text(encoding="utf-8"))
    rows = _rows()
    expected = set(schema["required"])
    assert expected == set(schema["properties"])
    assert all(set(row) == expected for row in rows)
