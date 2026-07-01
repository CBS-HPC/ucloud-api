#!/usr/bin/env python3
"""Analyze a UCloud utilization report and print a machine-size recommendation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ucloud_workflow.utilization import analyze_job_report, render_utilization_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report",
        nargs="?",
        default="job-report.csv",
        type=Path,
        help="Path to a job-report.csv file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the rendered Markdown analysis",
    )
    parser.add_argument(
        "--current-machine",
        help="Optional current UCloud product id for a next-machine suggestion",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    analysis = analyze_job_report(args.report, current_machine_product=args.current_machine)
    rendered = render_utilization_analysis(analysis)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote analysis to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
