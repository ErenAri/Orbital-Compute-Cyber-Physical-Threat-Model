"""Command-line entry point for WRB-001."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json

from wrb_001_campaign import DEFAULT_CONFIG_PATH, load_config, run_campaign, write_outputs


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run the WRB-001 paired-seed robustness campaign")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--seeds", type=int, nargs="+", help="override the authoritative seed registry")
    parser.add_argument("--output-dir", type=Path, help="write standard artifact names below this directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    runs, summary = run_campaign(config_path=args.config, seeds=args.seeds)
    paths = write_outputs(runs, summary, config=config, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "campaign_id": summary["campaign_id"],
                "classification": summary["classification"]["label"],
                "n_paired_seeds": summary["n_paired_seeds"],
                "valid_runs": summary["valid_run_count"],
                "invalid_runs": summary["invalid_run_count"],
                "outputs": {key: str(path) for key, path in paths.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
