from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
import json
import math

import pytest

import wrb_001_campaign
from compare_wrb_001_migration import compare

from wrb_001_campaign import (
    DEFAULT_CONFIG_PATH,
    RUN_FIELDS,
    build_summary,
    frozen_v044_regression,
    load_config,
    run_campaign,
    write_outputs,
)
from wrb_001_workloads import WORKLOAD_IDS


def test_campaign_imports_canonical_adapter_not_reconstruction() -> None:
    assert wrb_001_campaign.simulate_thermal.__module__ == "src.octm.adapters.v044"
    assert "legacy" not in wrb_001_campaign.simulate_thermal.__module__


@pytest.fixture(scope="module")
def two_seed_campaign() -> tuple[list[dict], dict]:
    return run_campaign(seeds=[0, 1])


def test_pairing_schema_energy_and_allowed_inputs(two_seed_campaign: tuple[list[dict], dict]) -> None:
    runs, summary = two_seed_campaign
    assert len(runs) == 12
    assert summary["n_paired_seeds"] == 2
    assert summary["valid_run_count"] == 12

    by_seed: dict[int, list[dict]] = defaultdict(list)
    for row in runs:
        by_seed[row["seed"]].append(row)
        assert set(row) == set(RUN_FIELDS)
        assert row["valid_run"] is True
        assert row["invalid_reason"] is None
        assert abs(row["relative_energy_error"]) <= 0.001
        assert math.isfinite(row["peak_node_temperature_K"])
    for rows in by_seed.values():
        assert [row["workload_id"] for row in rows] == list(WORKLOAD_IDS)
        assert len({row["physical_realization_sha256"] for row in rows}) == 1

    w4_rows = [row for row in runs if row["workload_id"] == "power_aware_benign"]
    assert all("hot_mask" not in row["allowed_inputs"] for row in w4_rows)
    assert all("power_availability" in row["allowed_inputs"] for row in w4_rows)


def test_campaign_is_deterministic(two_seed_campaign: tuple[list[dict], dict]) -> None:
    first_runs, first_summary = two_seed_campaign
    second_runs, second_summary = run_campaign(seeds=[0, 1])
    assert first_runs == second_runs
    assert first_summary == second_summary


def test_authoritative_serialization_is_byte_deterministic(
    tmp_path: Path, two_seed_campaign: tuple[list[dict], dict]
) -> None:
    runs, summary = two_seed_campaign
    config = load_config(DEFAULT_CONFIG_PATH)
    first = write_outputs(runs, summary, config=config, output_dir=tmp_path / "first")
    second = write_outputs(runs, summary, config=config, output_dir=tmp_path / "second")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()

    jsonl_rows = [json.loads(line) for line in first["runs_jsonl"].read_text(encoding="utf-8").splitlines()]
    assert jsonl_rows == runs
    with first["runs_csv"].open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == RUN_FIELDS
        assert len(list(reader)) == len(runs)


def test_json_schema_required_fields_cover_actual_artifacts(
    two_seed_campaign: tuple[list[dict], dict]
) -> None:
    runs, summary = two_seed_campaign
    schema = json.loads(Path("schemas/wrb_001.schema.json").read_text(encoding="utf-8"))
    run_definition = schema["$defs"]["runRecord"]
    summary_definition = schema["$defs"]["summary"]
    assert set(run_definition["required"]) == set(RUN_FIELDS)
    assert set(run_definition["properties"]) == set(RUN_FIELDS)
    assert set(summary_definition["required"]) <= set(summary)
    assert all(set(row) == set(run_definition["required"]) for row in runs)


def test_no_nonfinite_number_enters_summary(two_seed_campaign: tuple[list[dict], dict]) -> None:
    _, summary = two_seed_campaign

    def walk(value: object) -> None:
        if isinstance(value, float):
            assert math.isfinite(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(summary)
    assert frozen_v044_regression()["status"] == "PASS"
    assert summary["baseline_regression"]["deterministic_fixed_forcing"]["status"] == "PASS"


def test_statistics_exclude_invalid_runs_but_retain_counts(
    two_seed_campaign: tuple[list[dict], dict]
) -> None:
    runs, _ = two_seed_campaign
    mutated = [dict(row) for row in runs]
    target = next(
        row
        for row in mutated
        if row["seed"] == 1 and row["workload_id"] == "diversified_stochastic"
    )
    target["valid_run"] = False
    target["invalid_reason"] = "INVALID_ENERGY_MATCH"
    target["peak_node_temperature_K"] = 1.0e12
    config = load_config(DEFAULT_CONFIG_PATH)
    summary = build_summary(mutated, config=config, selected_seeds=[0, 1])
    workload = summary["workload_summaries"]["diversified_stochastic"]
    assert workload["n_total"] == 2
    assert workload["n_valid"] == 1
    assert workload["invalid_reasons"] == {"INVALID_ENERGY_MATCH": 1}
    assert workload["metrics"]["peak_node_temperature_K"]["n"] == 1
    assert workload["metrics"]["peak_node_temperature_K"]["max"] < 1.0e12


def test_migration_comparison_artifact_generation(
    tmp_path: Path, two_seed_campaign: tuple[list[dict], dict]
) -> None:
    runs, summary = two_seed_campaign
    config = load_config(DEFAULT_CONFIG_PATH)
    canonical_dir = tmp_path / "canonical"
    write_outputs(runs, summary, config=config, output_dir=canonical_dir)
    result = compare(Path("results/WRB-001-reconstructed"), canonical_dir)
    assert result["artifact_type"] == "wrb_001_migration_comparison"
    assert result["reconstructed_results"] == "results/WRB-001-reconstructed"
    assert result["canonical_results"] == "canonical"
    assert not Path(result["reconstructed_results"]).is_absolute()
    assert not Path(result["canonical_results"]).is_absolute()
    assert set(result["workloads"]) == set(WORKLOAD_IDS)
    assert result["classification"]["reconstructed"] in {
        "ROBUST", "CONDITIONAL", "NOT_ROBUST", "NOT ROBUST"
    }


def test_full_campaign_rerun_artifacts_are_byte_identical() -> None:
    result = json.loads(
        Path("results/WRB-001/reproducibility.json").read_text(encoding="utf-8")
    )
    primary = json.loads(Path("results/WRB-001/summary.json").read_text(encoding="utf-8"))
    reproduction = json.loads(
        Path("results/WRB-001/repro-check/summary.json").read_text(encoding="utf-8")
    )
    assert primary["n_paired_seeds"] == 100
    assert primary == reproduction
    assert result["all_authoritative_files_byte_identical"] is True
    assert all(item["byte_identical"] for item in result["files"].values())
