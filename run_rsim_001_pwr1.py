"""Run the frozen 240-case RSIM-001-PWR1 comparative smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsim_001_pwr1_campaign import OUTPUT_DIR, hard_gates, run_pwr1, write_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--gates-only", action="store_true")
    args = parser.parse_args()
    gates = hard_gates()
    if args.gates_only:
        print(json.dumps(gates, indent=2, sort_keys=True))
        return 0
    rows, summary, comparison, invariants = run_pwr1()
    if not invariants["all_required_invariants_pass"]:
        raise SystemExit("RSIM-001-PWR1 invariant hard gate failed")
    hashes = write_outputs(
        rows, summary, comparison, invariants, output_dir=args.output_dir
    )
    print(json.dumps({
        "gates": gates,
        "summary": summary,
        "comparison_totals": {
            "A0M_system_power_deficit_run_count": comparison["A0M_system_power_deficit_run_count"],
            "A0R_system_power_deficit_run_count": comparison["A0R_system_power_deficit_run_count"],
        },
        "artifact_sha256": hashes,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
