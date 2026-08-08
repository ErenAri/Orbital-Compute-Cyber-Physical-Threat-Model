"""Run RSIM-001 hard gates and the approved 360-run smoke campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsim_001_campaign import (
    OUTPUT_DIR, e0_mode_a_regression, run_smoke, verify_baseline_gate, write_outputs,
)
from src.octm.rsim.thermal_bridge import benchmark_bridge


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    baseline = verify_baseline_gate()
    e0_regression = e0_mode_a_regression()
    benchmark = benchmark_bridge(intervals=10_000, repeats=5)
    gates = {
        "artifact_type": "rsim_001_hard_gates",
        "baseline": baseline,
        "e0_mode_a_wrb_regression": e0_regression,
        "thermal_bridge": benchmark,
        "status": "PASS" if benchmark["status"] == "PASS" else "FAIL",
    }
    if gates["status"] != "PASS":
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "hard_gates.json").write_text(
            json.dumps(gates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise SystemExit("RSIM-001 hard gate failed; smoke campaign not started")
    if args.gates_only:
        print(json.dumps(gates, indent=2, sort_keys=True))
        return 0
    rows, summary, invariants = run_smoke()
    if not invariants["all_required_invariants_pass"]:
        raise SystemExit("RSIM-001 invariant hard gate failed")
    hashes = write_outputs(rows, summary, invariants, benchmark, gates, output_dir=args.output_dir)
    print(json.dumps({"gates": gates, "summary": summary, "artifact_sha256": hashes}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
