#!/usr/bin/env python3
"""Draft job: transfer the static example files to UCloud, then sync the dummy output back."""

from __future__ import annotations

import sys

from ucloud_workflow.settings import Settings, SettingsError
from ucloud_workflow.transfer import run_ssh_transfer_demo


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"Missing settings: {exc}", file=sys.stderr)
        return 2

    result = run_ssh_transfer_demo(settings)
    print("=== Local output ===")
    print(result.local_output_path)
    print("=== Remote job directory ===")
    print(result.remote_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
