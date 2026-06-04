#!/usr/bin/env python3
"""Draft script: start a CPU job on UCloud, run a simple remote Python command, then terminate the job."""

from __future__ import annotations

from datetime import datetime, timezone
import subprocess
import sys

from ucloud_workflow.client import UCloudClient
from ucloud_workflow.jobs import (
    submit_job_from_latest_template,
    update_ssh_config,
    wait_for_running_job,
)
from ucloud_workflow.settings import Settings, SettingsError

REMOTE_SCRIPT = (
    "from datetime import datetime, timezone; "
    "from pathlib import Path; "
    "print('Hello from UCloud CPU job'); "
    "print('working_dir=', Path.cwd()); "
    "print('utc=', datetime.now(timezone.utc).isoformat())"
)


def run_remote_python(ssh_alias: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", ssh_alias, "python3", "-c", REMOTE_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"Missing settings: {exc}", file=sys.stderr)
        return 2

    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=settings.default_size,
            hours=settings.default_hours,
            name=f"python-cpu-draft-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            mounts=settings.mount_paths,
            template_job_id=settings.template_job_id,
        )
        try:
            _, ssh_command = wait_for_running_job(client, launched.job_id)
            update_ssh_config(
                ssh_command,
                alias=settings.ssh_alias,
                config_path=settings.ssh_config_path,
            )
            result = run_remote_python(settings.ssh_alias)
        finally:
            try:
                client.terminate_job(launched.job_id)
                print(f"Terminated UCloud job {launched.job_id}")
            except Exception as exc:
                print(
                    f"Warning: could not terminate UCloud job {launched.job_id}: {exc}",
                    file=sys.stderr,
                )

    print("=== Remote stdout ===")
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print("=== Remote stderr ===", file=sys.stderr)
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
