"""WRB-001 paired-seed campaign orchestration and canonical serialization."""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import sys

import numpy as np

from src.octm.adapters.v044 import (
    CANONICAL_SOURCE_SHA256,
    DEFAULT_PARAMETERS,
    canonical_source_hashes,
    measurement_step_mask,
    orbital_environment,
    simulate_thermal,
)
from wrb_001_statistics import (
    ClassificationConfig,
    benign_ratio,
    classify_robustness,
    descriptive_statistics,
    json_safe,
    summarize_paired_delta,
)
from wrb_001_workloads import (
    WORKLOAD_IDS as WORKLOAD_ORDER,
    WORKLOAD_LABELS,
    WorkloadConfig,
    generate_workloads,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "experiments" / "WRB-001" / "config.json"
EXPECTED_V044_HASHES = {
    "Orbital_Compute_Threat_Model_v0_4_4.docx": "1e55e20c9c291d25f89ff9176e5155babeb3985fded1a0b1d6ec05e22992fe29",
    "QA_REPORT_v0.4.4.md": "34c3312386afc8098efe79d5fb472fbf5515f50478f2418795d9b1be2c5da866",
    "RELEASE_NOTES_v0.4.4.md": "71121909da87eaaaa3e8fee6cf0b7098ac45c9665b93b6d0d3f83ebf71951e9a",
    "results_v044.json": "51ee15fc35b2494123b9bb10141ce2eeacbc54d2f1a0c4170920abaa66430686",
}

RUN_FIELDS = (
    "record_type",
    "schema_version",
    "campaign_id",
    "model_version",
    "git_commit",
    "seed",
    "run_seed",
    "workload_id",
    "workload_label",
    "workload_category",
    "dt_s",
    "evaluation_start_s",
    "evaluation_end_s_exclusive",
    "evaluation_sample_count",
    "mean_compute_power_W",
    "cumulative_compute_energy_J",
    "reference_compute_energy_J",
    "relative_energy_error",
    "peak_compute_power_W",
    "power_variance_W2",
    "peak_node_temperature_K",
    "peak_radiator_temperature_K",
    "delta_peak_temperature_vs_reference_K",
    "delta_peak_temperature_vs_diversified_K",
    "time_above_throttle_threshold_s",
    "time_above_model_hazard_threshold_s",
    "peak_node_radiator_gradient_K",
    "hot_phase_energy_fraction",
    "phase_correlation",
    "phase_correlation_status",
    "r_benign",
    "r_benign_status",
    "r_benign_vs_diversified",
    "r_benign_vs_diversified_status",
    "workload_rng_seed",
    "workload_rng_stream",
    "workload_trace_sha256",
    "physical_realization_sha256",
    "physical_randomness_applied",
    "allowed_inputs",
    "diagnostics",
    "valid_run",
    "invalid_reason",
)

MAJOR_METRICS = (
    "mean_compute_power_W",
    "cumulative_compute_energy_J",
    "peak_compute_power_W",
    "power_variance_W2",
    "peak_node_temperature_K",
    "peak_radiator_temperature_K",
    "delta_peak_temperature_vs_reference_K",
    "delta_peak_temperature_vs_diversified_K",
    "time_above_throttle_threshold_s",
    "time_above_model_hazard_threshold_s",
    "peak_node_radiator_gradient_K",
    "hot_phase_energy_fraction",
    "phase_correlation",
)

WORKLOAD_CATEGORIES = {
    "constant_reference": "reference",
    "diversified_stochastic": "benign",
    "bursty_benign": "benign",
    "queue_driven_benign": "benign",
    "power_aware_benign": "benign",
    "phase_shaped_candidate": "adversarial_candidate",
}


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "campaign_id",
        "model_version",
        "dt_s",
        "warmup_orbits",
        "measurement_orbits",
        "seeds_file",
        "energy_relative_tolerance",
        "bootstrap",
        "ratio",
        "classification",
        "outputs",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"campaign config missing fields: {missing}")
    if float(config["dt_s"]) != 1.0:
        raise ValueError("WRB-001 release protocol fixes dt_s at 1.0")
    return config


def load_seeds(config: Mapping[str, Any], *, root: Path = ROOT) -> list[int]:
    path = Path(str(config["seeds_file"]))
    if not path.is_absolute():
        path = root / path
    seeds = [int(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(seeds) != len(set(seeds)):
        raise ValueError("seed registry contains duplicates")
    return seeds


def electrical_power_availability(time_s: np.ndarray, orbit_period_s: float) -> np.ndarray:
    """Abstract [0,1] electrical availability; never consumes thermal state."""

    phase = 2.0 * np.pi * np.asarray(time_s, dtype=np.float64) / float(orbit_period_s)
    raw = 0.56 + 0.30 * np.sin(phase - 1.10) + 0.10 * np.sin(2.0 * phase + 0.40)
    return np.clip(raw, 0.0, 1.0)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_v044_regression(root: Path = ROOT) -> dict[str, Any]:
    actual: dict[str, str | None] = {}
    for filename in EXPECTED_V044_HASHES:
        path = root / filename
        actual[filename] = _sha256(path) if path.exists() else None
    matches = {name: actual[name] == expected for name, expected in EXPECTED_V044_HASHES.items()}
    return {
        "status": "PASS" if all(matches.values()) else "FAIL",
        "expected_sha256": dict(EXPECTED_V044_HASHES),
        "actual_sha256": actual,
        "matches": matches,
    }


def deterministic_fixed_forcing_regression() -> dict[str, Any]:
    """Reproduce the published v0.4.4 dt=1 fixed-forcing check."""

    params = DEFAULT_PARAMETERS
    dt_s = 1.0
    n_steps = int(round(8 * params.orbit_period_s / dt_s))
    step_time_s = np.arange(n_steps, dtype=np.float64) * dt_s
    flux, hot_mask = orbital_environment(step_time_s, params)
    measurement = measurement_step_mask(
        step_time_s, params=params, warmup_orbits=2, measurement_orbits=6
    )
    constant = np.full(n_steps, 30_000.0, dtype=np.float64)
    cold_power = (
        30_000.0 - params.hot_fraction * params.compute_design_power_W
    ) / (1.0 - params.hot_fraction)
    shaped = np.where(hot_mask, params.compute_design_power_W, cold_power)
    nominal = simulate_thermal(constant, flux, dt_s=dt_s, params=params)
    phase = simulate_thermal(shaped, flux, dt_s=dt_s, params=params)
    nominal_peak_C = float(np.max(nominal.node_temperature_K[1:][measurement]) - 273.15)
    phase_peak_C = float(np.max(phase.node_temperature_K[1:][measurement]) - 273.15)
    delta_K = phase_peak_C - nominal_peak_C
    published = {
        "nominal_peak_C": 50.986481,
        "phase_shaped_peak_C": 68.439837,
        "peak_delta_K": 17.453355,
    }
    observed = {
        "nominal_peak_C": nominal_peak_C,
        "phase_shaped_peak_C": phase_peak_C,
        "peak_delta_K": delta_K,
    }
    errors = {key: abs(observed[key] - published[key]) for key in published}
    return {
        "status": "PASS" if max(errors.values()) <= 1e-5 else "FAIL",
        "dt_s": dt_s,
        "published": published,
        "observed": observed,
        "absolute_error": errors,
        "tolerance": 1e-5,
    }


def _phase_correlation(power_W: np.ndarray, hot_mask: np.ndarray) -> tuple[float | None, str]:
    if (
        power_W.size < 2
        or float(np.ptp(power_W)) <= 1e-9
        or float(np.ptp(hot_mask.astype(float))) == 0.0
    ):
        return None, "ZERO_VARIANCE"
    value = float(np.corrcoef(power_W, hot_mask.astype(float))[0, 1])
    if not np.isfinite(value):
        return None, "NONFINITE"
    return value, "VALID"


def _base_row(
    *, config: Mapping[str, Any], seed: int, workload: Any, dt_s: float, measurement: np.ndarray
) -> dict[str, Any]:
    indices = np.flatnonzero(measurement)
    rng_seed = _get(workload, "rng_seed", _get(workload, "workload_rng_seed"))
    rng_stream = _get(workload, "rng_stream", _get(workload, "workload_rng_stream"))
    relative_error = _get(workload, "relative_energy_error")
    if relative_error is None:
        relative_error = _get(workload, "energy_relative_error")
    return {
        "record_type": "run",
        "schema_version": config["schema_version"],
        "campaign_id": config["campaign_id"],
        "model_version": config["model_version"],
        "git_commit": _git_commit(),
        "seed": int(seed),
        "run_seed": int(seed),
        "workload_id": str(_get(workload, "workload_id")),
        "workload_label": str(_get(workload, "label", WORKLOAD_LABELS[str(_get(workload, "workload_id"))])),
        "workload_category": WORKLOAD_CATEGORIES[str(_get(workload, "workload_id"))],
        "dt_s": float(dt_s),
        "evaluation_start_s": float(indices[0] * dt_s),
        "evaluation_end_s_exclusive": float((indices[-1] + 1) * dt_s),
        "evaluation_sample_count": int(indices.size),
        "mean_compute_power_W": None,
        "cumulative_compute_energy_J": _get(workload, "sampled_energy_J"),
        "reference_compute_energy_J": _get(workload, "target_energy_J"),
        "relative_energy_error": relative_error,
        "peak_compute_power_W": None,
        "power_variance_W2": None,
        "peak_node_temperature_K": None,
        "peak_radiator_temperature_K": None,
        "delta_peak_temperature_vs_reference_K": None,
        "delta_peak_temperature_vs_diversified_K": None,
        "time_above_throttle_threshold_s": None,
        "time_above_model_hazard_threshold_s": None,
        "peak_node_radiator_gradient_K": None,
        "hot_phase_energy_fraction": None,
        "phase_correlation": None,
        "phase_correlation_status": "NOT_EVALUATED",
        "r_benign": None,
        "r_benign_status": "NOT_APPLICABLE",
        "r_benign_vs_diversified": None,
        "r_benign_vs_diversified_status": "NOT_APPLICABLE",
        "workload_rng_seed": int(rng_seed) if rng_seed is not None else None,
        "workload_rng_stream": rng_stream,
        "workload_trace_sha256": _get(workload, "trace_sha256"),
        "physical_realization_sha256": None,
        "physical_randomness_applied": False,
        "allowed_inputs": list(_get(workload, "allowed_inputs", [])),
        "diagnostics": dict(_get(workload, "diagnostics", {})),
        "valid_run": bool(_get(workload, "valid_run", False)),
        "invalid_reason": _get(workload, "invalid_reason"),
    }


def _populate_valid_metrics(
    row: dict[str, Any],
    workload: Any,
    *,
    flux_W_m2: np.ndarray,
    hot_mask: np.ndarray,
    measurement: np.ndarray,
    dt_s: float,
) -> None:
    power_W = np.asarray(_get(workload, "power_W"), dtype=np.float64)
    simulation = simulate_thermal(power_W, flux_W_m2, dt_s=dt_s, params=DEFAULT_PARAMETERS)
    measured_power = power_W[measurement]
    node_K = simulation.node_temperature_K[1:][measurement]
    radiator_K = simulation.radiator_temperature_K[1:][measurement]
    measured_hot = hot_mask[measurement]
    correlation, correlation_status = _phase_correlation(measured_power, measured_hot)
    total_energy = float(np.sum(measured_power, dtype=np.float64) * dt_s)
    hot_energy = float(np.sum(measured_power[measured_hot], dtype=np.float64) * dt_s)
    row.update(
        {
            "mean_compute_power_W": float(np.mean(measured_power)),
            "cumulative_compute_energy_J": total_energy,
            "peak_compute_power_W": float(np.max(measured_power)),
            "power_variance_W2": float(np.var(measured_power, ddof=0)),
            "peak_node_temperature_K": float(np.max(node_K)),
            "peak_radiator_temperature_K": float(np.max(radiator_K)),
            "time_above_throttle_threshold_s": float(
                np.count_nonzero(node_K >= DEFAULT_PARAMETERS.throttle_threshold_K) * dt_s
            ),
            "time_above_model_hazard_threshold_s": float(
                np.count_nonzero(node_K >= DEFAULT_PARAMETERS.model_hazard_threshold_K) * dt_s
            ),
            "peak_node_radiator_gradient_K": float(np.max(node_K - radiator_K)),
            "hot_phase_energy_fraction": hot_energy / total_energy if total_energy > 0.0 else None,
            "phase_correlation": correlation,
            "phase_correlation_status": correlation_status,
            "physical_realization_sha256": simulation.physical_realization_sha256,
        }
    )


def _finalize_seed_pair(rows: list[dict[str, Any]], denominator_tolerance_K: float) -> None:
    by_id = {row["workload_id"]: row for row in rows}
    w0 = by_id.get("constant_reference")
    w1 = by_id.get("diversified_stochastic")
    if not w0 or not w0["valid_run"] or not w1 or not w1["valid_run"]:
        return
    reference_peak = float(w0["peak_node_temperature_K"])
    diversified_peak = float(w1["peak_node_temperature_K"])
    for row in rows:
        if row["valid_run"] and row["peak_node_temperature_K"] is not None:
            peak = float(row["peak_node_temperature_K"])
            row["delta_peak_temperature_vs_reference_K"] = peak - reference_peak
            row["delta_peak_temperature_vs_diversified_K"] = peak - diversified_peak

    w4 = by_id.get("power_aware_benign")
    w5 = by_id.get("phase_shaped_candidate")
    if not w4 or not w5 or not w4["valid_run"] or not w5["valid_run"]:
        return
    primary = benign_ratio(
        float(w4["delta_peak_temperature_vs_reference_K"]),
        float(w5["delta_peak_temperature_vs_reference_K"]),
        denominator_tolerance_K=denominator_tolerance_K,
    )
    historical = benign_ratio(
        float(w4["delta_peak_temperature_vs_diversified_K"]),
        float(w5["delta_peak_temperature_vs_diversified_K"]),
        denominator_tolerance_K=denominator_tolerance_K,
    )
    w4["r_benign"], w4["r_benign_status"] = primary["value"], primary["status"]
    w4["r_benign_vs_diversified"] = historical["value"]
    w4["r_benign_vs_diversified_status"] = historical["status"]


def run_campaign(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    seeds: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = load_config(config_path)
    selected_seeds = list(load_seeds(config) if seeds is None else seeds)
    if not selected_seeds or len(selected_seeds) != len(set(selected_seeds)):
        raise ValueError("campaign requires a non-empty unique seed list")

    dt_s = float(config["dt_s"])
    n_orbits = int(config["warmup_orbits"]) + int(config["measurement_orbits"])
    n_steps = int(round(n_orbits * DEFAULT_PARAMETERS.orbit_period_s / dt_s))
    step_time_s = np.arange(n_steps, dtype=np.float64) * dt_s
    flux_W_m2, hot_mask = orbital_environment(step_time_s, DEFAULT_PARAMETERS)
    measurement = measurement_step_mask(
        step_time_s,
        params=DEFAULT_PARAMETERS,
        warmup_orbits=int(config["warmup_orbits"]),
        measurement_orbits=int(config["measurement_orbits"]),
    )
    availability = electrical_power_availability(step_time_s, DEFAULT_PARAMETERS.orbit_period_s)
    workload_config = WorkloadConfig(
        energy_tolerance_fraction=float(config["energy_relative_tolerance"]),
    )

    runs: list[dict[str, Any]] = []
    for seed in selected_seeds:
        workloads = generate_workloads(
            seed=int(seed),
            time_s=step_time_s,
            measurement_mask=measurement,
            dt_s=dt_s,
            hot_mask=hot_mask,
            power_availability=availability,
            config=workload_config,
        )
        if list(workloads) != list(WORKLOAD_ORDER):
            raise RuntimeError("workload generator returned non-canonical ordering")
        seed_rows: list[dict[str, Any]] = []
        for workload in workloads.values():
            row = _base_row(config=config, seed=int(seed), workload=workload, dt_s=dt_s, measurement=measurement)
            if row["valid_run"]:
                _populate_valid_metrics(
                    row,
                    workload,
                    flux_W_m2=flux_W_m2,
                    hot_mask=hot_mask,
                    measurement=measurement,
                    dt_s=dt_s,
                )
            seed_rows.append(row)
        physical_hashes = {
            row["physical_realization_sha256"]
            for row in seed_rows
            if row["valid_run"] and row["physical_realization_sha256"] is not None
        }
        if len(physical_hashes) != 1:
            raise RuntimeError(f"seed {seed} does not share one physical realization")
        _finalize_seed_pair(
            seed_rows,
            denominator_tolerance_K=float(config["ratio"]["near_zero_denominator_K"]),
        )
        runs.extend(seed_rows)

    summary = build_summary(runs, config=config, selected_seeds=selected_seeds)
    return json_safe(runs), json_safe(summary)


def _valid_values(rows: Iterable[Mapping[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if row.get("valid_run") and value is not None:
            converted = float(value)
            if not np.isfinite(converted):
                raise ValueError(f"valid run contains non-finite {field}")
            values.append(converted)
    return values


def build_summary(
    runs: Sequence[Mapping[str, Any]], *, config: Mapping[str, Any], selected_seeds: Sequence[int]
) -> dict[str, Any]:
    bootstrap_base = int(config["bootstrap"]["seed"])
    bootstrap_resamples = int(config["bootstrap"]["resamples"])
    by_workload: dict[str, list[Mapping[str, Any]]] = {
        workload_id: [row for row in runs if row["workload_id"] == workload_id]
        for workload_id in WORKLOAD_ORDER
    }
    workload_summaries: dict[str, Any] = OrderedDict()
    delta_summaries: dict[str, Any] = {}
    for index, workload_id in enumerate(WORKLOAD_ORDER):
        rows = by_workload[workload_id]
        invalid_reasons = Counter(
            str(row["invalid_reason"])
            for row in rows
            if not row["valid_run"] and row.get("invalid_reason")
        )
        metrics = {field: descriptive_statistics(_valid_values(rows, field)) for field in MAJOR_METRICS}
        delta_values = _valid_values(rows, "delta_peak_temperature_vs_reference_K")
        delta_summary = summarize_paired_delta(
            delta_values,
            bootstrap_seed=bootstrap_base + index,
            bootstrap_resamples=bootstrap_resamples,
        )
        metrics["delta_peak_temperature_vs_reference_K"] = delta_summary
        delta_summaries[workload_id] = delta_summary
        workload_summaries[workload_id] = {
            "n_total": len(rows),
            "n_valid": sum(bool(row["valid_run"]) for row in rows),
            "n_invalid": sum(not bool(row["valid_run"]) for row in rows),
            "invalid_reasons": dict(sorted(invalid_reasons.items())),
            "metrics": metrics,
        }

    ratio_rows = by_workload["power_aware_benign"]
    ratio_values = [
        float(row["r_benign"])
        for row in ratio_rows
        if row.get("r_benign_status") == "VALID" and row.get("r_benign") is not None
    ]
    historical_values = [
        float(row["r_benign_vs_diversified"])
        for row in ratio_rows
        if row.get("r_benign_vs_diversified_status") == "VALID"
        and row.get("r_benign_vs_diversified") is not None
    ]
    ratio_statuses = Counter(str(row.get("r_benign_status")) for row in ratio_rows)
    historical_statuses = Counter(str(row.get("r_benign_vs_diversified_status")) for row in ratio_rows)

    classification_config = ClassificationConfig(
        material_delta_K=float(config["classification"]["material_delta_K"]),
        robust_min_benign_families=int(
            config["classification"]["robust_min_benign_families"]
        ),
    )
    source_files = [
        "src/octm/adapters/v044.py",
        "src/octm/baselines/v044/thermal_model.py",
        "src/octm/baselines/v044/run_all_v044.py",
        "wrb_001_workloads.py",
        "wrb_001_statistics.py",
        "wrb_001_campaign.py",
        "run_wrb_001.py",
        "experiments/WRB-001/config.json",
    ]
    source_hashes = {
        name: _sha256(ROOT / name) for name in source_files if (ROOT / name).exists()
    }
    return {
        "artifact_type": "summary",
        "schema_version": config["schema_version"],
        "campaign_id": config["campaign_id"],
        "model_version": config["model_version"],
        "scientific_scope": config["scientific_scope"],
        "attack_validation": False,
        "git_commit": _git_commit(),
        "seeds": [int(seed) for seed in selected_seeds],
        "n_paired_seeds": len(selected_seeds),
        "run_count": len(runs),
        "valid_run_count": sum(bool(row["valid_run"]) for row in runs),
        "invalid_run_count": sum(not bool(row["valid_run"]) for row in runs),
        "workload_order": list(WORKLOAD_ORDER),
        "workload_summaries": workload_summaries,
        "benign_shaped_ratio_vs_constant_reference": {
            "definition": "delta_peak(power_aware_benign vs W0) / delta_peak(phase_shaped_candidate vs W0)",
            "status_counts": dict(sorted(ratio_statuses.items())),
            "statistics": summarize_paired_delta(
                ratio_values,
                bootstrap_seed=bootstrap_base + 1000,
                bootstrap_resamples=bootstrap_resamples,
            ),
        },
        "benign_shaped_ratio_vs_diversified": {
            "definition": "delta_peak(power_aware_benign vs W1) / delta_peak(phase_shaped_candidate vs W1)",
            "historical_context": "v0.4.4 reported one reconstructed-comparator result near 0.84; this campaign reports a distribution",
            "status_counts": dict(sorted(historical_statuses.items())),
            "statistics": summarize_paired_delta(
                historical_values,
                bootstrap_seed=bootstrap_base + 1001,
                bootstrap_resamples=bootstrap_resamples,
            ),
        },
        "classification": classify_robustness(delta_summaries, classification_config),
        "protocol": {
            "dt_s": float(config["dt_s"]),
            "warmup_orbits": int(config["warmup_orbits"]),
            "measurement_orbits": int(config["measurement_orbits"]),
            "measurement_interval": "half-open, left-endpoint forcing samples",
            "energy_relative_tolerance": float(config["energy_relative_tolerance"]),
            "preferred_energy_relative_tolerance": float(
                config["preferred_energy_relative_tolerance"]
            ),
            "bootstrap": dict(config["bootstrap"]),
            "ratio": dict(config["ratio"]),
            "classification": dict(config["classification"]),
        },
        "baseline_regression": {
            "frozen_artifacts": frozen_v044_regression(),
            "deterministic_fixed_forcing": deterministic_fixed_forcing_regression(),
        },
        "provenance": {
            "implementation_status": "canonical_v0.4.4_source_via_compatibility_adapter",
            "historical_source_available": True,
            "canonical_baseline_module": "src.octm.baselines.v044.thermal_model",
            "adapter_module": "src.octm.adapters.v044",
            "canonical_source_sha256": canonical_source_hashes(),
            "expected_canonical_source_sha256": dict(CANONICAL_SOURCE_SHA256),
            "historical_stochastic_generator_identity": "canonical load_nominal/load_phase_locked",
            "physical_randomness_applied": False,
            "source_sha256": source_hashes,
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
    }


@lru_cache(maxsize=1)
def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def write_outputs(
    runs: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    configured = config["outputs"]
    if output_dir is None:
        paths = {key: ROOT / str(value) for key, value in configured.items()}
    else:
        base = Path(output_dir)
        paths = {key: base / Path(str(value)).name for key, value in configured.items()}

    safe_runs = [json_safe(dict(row)) for row in runs]
    safe_summary = json_safe(dict(summary))
    jsonl = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
        for row in safe_runs
    )
    _atomic_write_text(paths["runs_jsonl"], jsonl)
    _atomic_write_text(
        paths["summary_json"],
        json.dumps(safe_summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
    )

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=RUN_FIELDS, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in safe_runs:
        encoded: dict[str, Any] = {}
        for field in RUN_FIELDS:
            value = row.get(field)
            if isinstance(value, (dict, list)):
                encoded[field] = json.dumps(
                    value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
            elif value is None:
                encoded[field] = ""
            elif isinstance(value, bool):
                encoded[field] = "true" if value else "false"
            else:
                encoded[field] = value
        writer.writerow(encoded)
    _atomic_write_text(paths["runs_csv"], buffer.getvalue())
    return paths
