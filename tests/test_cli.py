from __future__ import annotations

import io
from types import SimpleNamespace

import httpx
import pytest
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


@pytest.mark.parametrize("command", [
    ["jobs", "submit"],
    ["workflow", "run"],
    ["workflow", "ssh-transfer"],
    ["workflow", "python-job"],
])
@pytest.mark.parametrize("selection", ["cpu-default", "explicit-product", "template-product"])
def test_job_commands_forward_machine_selection(monkeypatch, tmp_path, command, selection) -> None:
    captured = {}
    settings = Settings(server="https://cloud.sdu.dk", token="test", project="test", default_size="128-vcpu")
    launched = SimpleNamespace(
        job_id="test-job",
        job_url="test",
        local_output_path=tmp_path / "out.txt",
        local_output_dir=tmp_path,
        downloaded_paths=(),
        job_report_path=None,
        remote_dir="/work/test",
    )
    product = {
        "id": "gpu-nvidia-b200-1-mig.1g",
        "category": "gpu-nvidia-b200",
        "provider": "ucloud",
    }

    class DummyClient:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    def capture_call(*_args, **kwargs):
        captured.update(kwargs)
        return launched

    monkeypatch.setattr(cli, "_load_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(cli, "UCloudClient", DummyClient)
    monkeypatch.setattr(cli, "submit_job_from_latest_template", capture_call)
    monkeypatch.setattr(cli, "run_remote_python_job", capture_call)
    monkeypatch.setattr(cli, "run_ssh_transfer_demo", capture_call)
    monkeypatch.setattr(cli, "wait_for_running_job", lambda *_args: ({}, "ssh test@host -p 22"))
    monkeypatch.setattr(cli, "update_ssh_config", lambda *_args, **_kwargs: {})
    options = []
    if selection == "template-product":
        options = ["--use-template-product"]
    elif selection == "explicit-product":
        options = [
            "--product-id", product["id"],
            "--product-category", product["category"],
            "--product-provider", product["provider"],
        ]
    if command[-1] == "python-job":
        script = tmp_path / "test.py"
        script.write_text("print('test')", encoding="utf-8")
        options.extend(["--script", str(script)])

    result = CliRunner().invoke(app, [*command, *options])

    assert result.exit_code == 0, result.output
    assert captured["product"] == (product if selection == "explicit-product" else None)
    if command[-1] in {"submit", "run"}:
        assert captured["size"] == (settings.default_size if selection == "cpu-default" else None)
    else:
        assert captured["use_template_product"] is (selection == "template-product")


@pytest.mark.parametrize("options", [
    ["--product-id", "gpu-test"],
    ["--product-category", "gpu-test", "--product-provider", "ucloud"],
    ["--use-template-product", "--size", "8-vcpu"],
    ["--size", "8-vcpu", "--product-id", "gpu-test", "--product-category", "gpu-test", "--product-provider", "ucloud"],
    ["--use-template-product", "--product-id", "gpu-test", "--product-category", "gpu-test", "--product-provider", "ucloud"],
])
def test_job_submit_rejects_conflicting_or_partial_product_options(options) -> None:
    result = CliRunner().invoke(app, ["jobs", "submit", *options])

    assert result.exit_code == 2


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
