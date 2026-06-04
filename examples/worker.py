#!/usr/bin/env python3
"""Dummy worker used to verify SSH file transfer to UCloud."""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input file to read")
    parser.add_argument("--output", required=True, help="Output file to write")
    parser.add_argument("--delay", type=float, default=0.0, help="Optional delay before writing output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if args.delay > 0:
        time.sleep(args.delay)

    input_text = input_path.read_text(encoding="utf-8").strip()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "dummy output\n"
        f"input_file={input_path.name}\n"
        f"input_text={input_text}\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
