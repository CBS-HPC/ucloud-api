#!/usr/bin/env python3
"""Draft job: transfer the static example files to UCloud, then sync the dummy output back."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ucloud_workflow.settings import Settings, SettingsError
from ucloud_workflow.transfer import run_ssh_transfer_demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Local destination for dummy_output.txt (defaults to examples/dummy_output.txt)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"Missing settings: {exc}", file=sys.stderr)
        return 2

    result = run_ssh_transfer_demo(settings, local_output_path=args.output)
    print("=== Local output ===")
    print(result.local_output_path)
    if result.job_report_path is not None:
        print("=== Job report ===")
        print(result.job_report_path)
    print("=== Remote job directory ===")
    print(result.remote_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
