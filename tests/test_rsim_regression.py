from __future__ import annotations

import json
from pathlib import Path

from rsim_001_campaign import e0_mode_a_regression
from src.octm.adapters.v044 import CANONICAL_SOURCE_SHA256, canonical_source_hashes


def test_canonical_source_hashes_unchanged() -> None:
    assert canonical_source_hashes() == CANONICAL_SOURCE_SHA256


def test_e0_mode_a_matches_authoritative_wrb_seed_zero() -> None:
    result = e0_mode_a_regression([0])
    assert result["status"] == "PASS"
    assert result["max_peak_node_temperature_error_K"] <= 1e-10
    assert result["max_peak_radiator_temperature_error_K"] <= 1e-10


def test_parameter_registry_has_required_provenance_fields() -> None:
    registry = json.loads(Path("evidence/rsim001_parameters.json").read_text(encoding="utf-8"))
    required = {"id", "value", "unit", "status", "source", "rationale", "formula",
                "dependencies", "sweep_or_uncertainty", "used_by"}
    allowed = set(registry["allowed_statuses"])
    for parameter in registry["parameters"]:
        assert set(parameter) == required
        assert parameter["status"] in allowed
