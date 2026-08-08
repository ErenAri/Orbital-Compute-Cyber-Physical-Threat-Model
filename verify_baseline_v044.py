"""Reproduce and verify the canonical v0.4.4 authoritative numerical pipeline."""

from __future__ import annotations

from argparse import ArgumentParser
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

from src.octm.adapters.v044 import BASELINE_DIRECTORY, canonical_source_hashes


ROOT = Path(__file__).resolve().parent
AUTHORITATIVE_RESULT = ROOT / "results_v044.json"
DEFAULT_OUTPUT = ROOT / "results" / "baseline_v044_verification.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"


def manifest_coverage() -> dict[str, Any]:
    entries: dict[str, Any] = {}
    missing: list[str] = []
    for line in (BASELINE_DIRECTORY / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        candidates = (BASELINE_DIRECTORY / name, ROOT / name)
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            entries[name] = {"status": "MISSING", "expected_sha256": expected}
            missing.append(name)
        else:
            actual = sha256(path)
            entries[name] = {
                "status": "PASS" if actual == expected else "FAIL",
                "expected_sha256": expected,
                "actual_sha256": actual,
                "path": str(path.relative_to(ROOT).as_posix()),
            }
    available = [entry for entry in entries.values() if entry["status"] != "MISSING"]
    all_entries_present = len(available) == len(entries)
    all_entries_match = all_entries_present and all(
        entry["status"] == "PASS" for entry in entries.values()
    )
    return {
        "status": "PASS" if all_entries_match else "FAIL",
        "manifest_entry_count": len(entries),
        "available_entry_count": len(available),
        "missing_entry_count": len(missing),
        "all_entries_present": all_entries_present,
        "all_entries_match": all_entries_match,
        "available_entries_all_match": all(entry["status"] == "PASS" for entry in available),
        "missing_entries": missing,
        "entries": entries,
    }


def _numeric_comparison(left: Any, right: Any) -> dict[str, Any]:
    differences: list[float] = []
    mismatched_paths: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                mismatched_paths.append(path or "$")
                return
            for key in sorted(a):
                walk(a[key], b[key], f"{path}.{key}" if path else str(key))
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                mismatched_paths.append(path)
                return
            for index, (av, bv) in enumerate(zip(a, b, strict=True)):
                walk(av, bv, f"{path}[{index}]")
        elif isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(
            b, (int, float)
        ) and not isinstance(b, bool):
            differences.append(abs(float(a) - float(b)))
            if float(a) != float(b):
                mismatched_paths.append(path)
        elif a != b:
            mismatched_paths.append(path)

    walk(left, right, "")
    return {
        "numeric_value_count": len(differences),
        "matched_numeric_value_count": sum(difference == 0.0 for difference in differences),
        "max_absolute_numeric_difference": max(differences, default=0.0),
        "mismatch_count": len(mismatched_paths),
        "mismatched_paths": mismatched_paths[:100],
    }


def verify() -> dict[str, Any]:
    source_hashes = canonical_source_hashes()
    coverage = manifest_coverage()
    with tempfile.TemporaryDirectory(prefix="octm-v044-") as directory:
        work = Path(directory)
        for name in ("thermal_model.py", "run_all_v044.py"):
            shutil.copy2(BASELINE_DIRECTORY / name, work / name)
        completed = subprocess.run(
            [sys.executable, "run_all_v044.py"],
            cwd=work,
            text=True,
            capture_output=True,
            check=False,
        )
        generated_path = work / "results_v044.json"
        if completed.returncode != 0 or not generated_path.exists():
            return {
                "artifact_type": "baseline_v044_verification",
                "status": "FAIL",
                "source_sha256": source_hashes,
                "pipeline_returncode": completed.returncode,
                "pipeline_stdout": completed.stdout,
                "pipeline_stderr": completed.stderr,
                "git_commit": git_commit(),
            }
        generated_hash = sha256(generated_path)
        generated = json.loads(generated_path.read_text(encoding="utf-8"))

    authoritative = json.loads(AUTHORITATIVE_RESULT.read_text(encoding="utf-8"))
    generated_science = deepcopy(generated)
    authoritative_science = deepcopy(authoritative)
    generated_environment = generated_science.pop("environment", None)
    authoritative_environment = authoritative_science.pop("environment", None)
    comparison = _numeric_comparison(generated_science, authoritative_science)
    science_equal = generated_science == authoritative_science
    scientific_reproduction = {
        "status": "PASS" if science_equal else "FAIL",
        "comparison": {
            **comparison,
            "scientific_semantic_equal": science_equal,
            "declared_tolerance": 0.0,
        },
        "result_sha256": {
            "authoritative": sha256(AUTHORITATIVE_RESULT),
            "regenerated": generated_hash,
            "byte_identical_including_environment_metadata": (
                generated_hash == sha256(AUTHORITATIVE_RESULT)
            ),
            "difference_scope": (
                "none"
                if generated_hash == sha256(AUTHORITATIVE_RESULT)
                else "environment metadata only"
            ),
        },
    }
    release_artifact_verification = {
        "status": coverage["status"],
        "verification_basis": "src/octm/baselines/v044/MANIFEST.sha256",
        "manifest_sha256": sha256(BASELINE_DIRECTORY / "MANIFEST.sha256"),
        **coverage,
    }
    environment_differences = {
        "authoritative": authoritative_environment,
        "regenerated": generated_environment,
        "environments_differ": authoritative_environment != generated_environment,
        "excluded_from_scientific_equality": True,
        "reason": "release platform metadata is not a scientific result",
    }
    passed = science_equal and coverage["all_entries_match"]
    result = {
        "artifact_type": "baseline_v044_verification",
        "baseline_version": "0.4.4",
        "status": "PASS" if passed else "FAIL",
        "verification_rule": (
            "all scientific fields must be exactly equal and every MANIFEST.sha256 entry "
            "must be present and byte-identical; environment metadata is reported separately"
        ),
        "source_sha256": source_hashes,
        "scientific_numerical_reproduction": scientific_reproduction,
        "byte_level_release_artifact_verification": release_artifact_verification,
        "environment_differences": environment_differences,
        "pipeline": {
            "command": "python run_all_v044.py",
            "interpreter_executable_name": Path(sys.executable).name,
            "returncode": completed.returncode,
        },
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "git_commit": git_commit(),
    }
    return result


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    os.replace(temporary, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
