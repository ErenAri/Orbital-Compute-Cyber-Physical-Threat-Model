"""Run the frozen 960-case RSIM-001-EPOCH1 epoch challenge twice."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rsim_001_epoch1_campaign import (
    OUTPUT_DIR,
    hard_gates,
    mark_deterministic_rerun_pass,
    reproducibility_payload,
    run_epoch1,
    write_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--gates-only", action="store_true")
    parser.add_argument("--single-pass", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    gates = hard_gates()
    if args.gates_only:
        print(json.dumps(gates, indent=2, sort_keys=True))
        return 0
    first = run_epoch1(workers=args.workers)
    if not first[3]["all_required_invariants_pass"]:
        raise SystemExit("EPOCH1 required invariant failed; outputs not written")
    if args.single_pass:
        raise SystemExit("authoritative EPOCH1 output requires deterministic double execution")
    second = run_epoch1(workers=args.workers, commit=first[1]["git_commit"])
    if not second[3]["all_required_invariants_pass"]:
        raise SystemExit("EPOCH1 deterministic rerun invariant failed; outputs not written")
    first_payload = reproducibility_payload(*first)
    second_payload = reproducibility_payload(*second)
    if first_payload != second_payload:
        raise SystemExit("EPOCH1 deterministic rerun mismatch; outputs not written")
    mark_deterministic_rerun_pass(first[3])
    hashes = write_outputs(*first, output_dir=args.output_dir)
    print(json.dumps({
        "gates": gates,
        "summary": {
            key: first[1][key] for key in (
                "run_count", "valid_run_count", "invalid_run_count",
                "system_power_deficit_run_count", "warmup_power_deficit_run_count",
            )
        },
        "deterministic_payload_sha256": hashlib.sha256(first_payload).hexdigest(),
        "artifact_sha256": hashes,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
