from __future__ import annotations

from typer.testing import CliRunner

from ucloud_workflow import __version__
from ucloud_workflow.cli import app


def test_version_command_prints_package_version() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"ucloud-workflow {__version__}"
