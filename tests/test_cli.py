from __future__ import annotations

import io

import httpx
import rich.console
from typer.testing import CliRunner

from ucloud_workflow import __version__
from ucloud_workflow import cli
from ucloud_workflow.cli import app
from ucloud_workflow.settings import Settings


def test_version_command_prints_package_version() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"ucloud-workflow {__version__}"


def test_token_status_displays_metadata_without_a_token_secret(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, _settings) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def browse_api_tokens(self):
            return {
                "items": [
                    {
                        "id": "token-123",
                        "specification": {
                            "title": "Workflow token",
                            "expiresAt": 2_000_000_000_000,
                        },
                    }
                ]
            }

    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda **_: Settings(server="https://cloud.sdu.dk", token="very-secret", project="Moody's Datahub"),
    )
    monkeypatch.setattr(cli, "UCloudClient", DummyClient)
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", rich.console.Console(file=output, width=200))

    result = CliRunner().invoke(app, ["tokens", "status"])

    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "Workflow token" in rendered
    assert "token-123" in rendered
    assert "very-secret" not in rendered


def test_token_create_only_previews_without_yes(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", rich.console.Console(file=output, width=200))

    result = CliRunner().invoke(
        app,
        [
            "tokens",
            "create",
            "--title",
            "Replacement token",
            "--expires-at",
            "2030-01-01T00:00:00Z",
            "--permission",
            "jobs:READ",
        ],
    )

    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "Token creation request" in rendered
    assert "Preview only" in rendered


def test_token_create_accepts_valid_for_months(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", rich.console.Console(file=output, width=200))

    result = CliRunner().invoke(
        app,
        [
            "tokens",
            "create",
            "--title",
            "Replacement token",
            "--valid-for",
            "6",
        ],
    )

    assert result.exit_code == 0
    assert "Preview only" in output.getvalue()


def test_token_create_requires_yes_and_returns_one_time_secret(monkeypatch) -> None:
    captured_specification: dict[str, object] = {}

    class DummyClient:
        def __init__(self, _settings) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def create_api_token(self, specification):
            captured_specification.update(specification)
            return {"id": "replacement-123", "status": {"token": "new-one-time-secret"}}

    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda **_: Settings(server="https://cloud.sdu.dk", token="old-secret", project="Moody's Datahub"),
    )
    monkeypatch.setattr(cli, "UCloudClient", DummyClient)
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", rich.console.Console(file=output, width=200))

    result = CliRunner().invoke(
        app,
        [
            "tokens",
            "create",
            "--title",
            "Replacement token",
            "--expires-at",
            "2030-01-01T00:00:00Z",
            "--permission",
            "jobs:READ",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert captured_specification["requestedPermissions"] == [{"name": "jobs", "action": "READ"}]
    rendered = output.getvalue()
    assert "replacement-123" in rendered
    assert "new-one-time-secret" in rendered
    assert "old-secret" not in rendered


def test_token_create_does_not_retry_an_unknown_network_result(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, _settings) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def create_api_token(self, _specification):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda **_: Settings(server="https://cloud.sdu.dk", token="old-secret", project="Moody's Datahub"),
    )
    monkeypatch.setattr(cli, "UCloudClient", DummyClient)
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", rich.console.Console(file=output, width=200))

    result = CliRunner().invoke(
        app,
        [
            "tokens",
            "create",
            "--title",
            "Replacement token",
            "--expires-at",
            "2030-01-01T00:00:00Z",
            "--permission",
            "jobs:READ",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "Do not retry automatically" in rendered
    assert "old-secret" not in rendered
