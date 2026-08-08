"""Compare two complete WRB-001 output directories byte-for-byte."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import os


AUTHORITATIVE_FILES = ("runs.csv", "runs.jsonl", "summary.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(primary: Path, reproduction: Path) -> dict:
    files = {}
    for name in AUTHORITATIVE_FILES:
        primary_hash = sha256(primary / name)
        reproduction_hash = sha256(reproduction / name)
        files[name] = {
            "primary_sha256": primary_hash,
            "reproduction_sha256": reproduction_hash,
            "byte_identical": primary_hash == reproduction_hash,
        }
    return {
        "artifact_type": "reproducibility_check",
        "campaign_id": "WRB-001",
        "scope": "two independent complete runs using seeds 0..99",
        "files": files,
        "all_authoritative_files_byte_identical": all(
            item["byte_identical"] for item in files.values()
        ),
    }


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("primary", type=Path)
    parser.add_argument("reproduction", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = compare(args.primary, args.reproduction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    os.replace(temporary, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["all_authoritative_files_byte_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
