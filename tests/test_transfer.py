from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ucloud_workflow.settings import Settings
import ucloud_workflow.transfer as transfer
from ucloud_workflow.transfer import remote_job_directory, remote_work_root


def make_example_tree(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "worker.py").write_text("print('worker placeholder')\n", encoding="utf-8")
    (tmp_path / "dummy_input.txt").write_text("dummy input payload\n", encoding="utf-8")
    return tmp_path


def make_package_tree(tmp_path: Path) -> Path:
    package_dir = tmp_path / "mypkg"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    return package_dir


def test_remote_work_root_uses_work_folder_without_trailing_slash() -> None:
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        work_folder="/work/moody_agent/",
    )

    assert remote_work_root(settings) == "/work/moody_agent"


def test_remote_job_directory_uses_unique_subdirectory() -> None:
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        work_folder="/work/moody_agent",
    )

    assert remote_job_directory(settings, "20260603-120000", "job-abc123") == "/work/moody_agent/20260603-120000-job-abc123"


def test_build_helpers_format_remote_commands() -> None:
    assert transfer.build_python_run_command("main.py", ["--foo", "bar baz"]) == "python3 main.py --foo 'bar baz'"
    assert transfer.build_pip_install_command("mypkg", editable=True) == "python3 -m pip install --user -e ./mypkg"


def test_example_worker_creates_dummy_output(tmp_path) -> None:
    examples_dir = transfer.default_examples_dir()
    worker_script = examples_dir / "worker.py"
    dummy_input = examples_dir / "dummy_input.txt"
    output_path = tmp_path / "dummy_output.txt"

    subprocess.run(
        [
            sys.executable,
            str(worker_script),
            "--input",
            str(dummy_input),
            "--output",
            str(output_path),
            "--delay",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output_path.exists()
    output_text = output_path.read_text(encoding="utf-8")
    assert "dummy output" in output_text
    assert dummy_input.name in output_text
    assert "dummy input payload" in output_text


def test_run_remote_python_job_uploads_script_package_and_downloads_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "main.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")
    package_dir = make_package_tree(tmp_path)
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        work_folder="/work/moody_agent",
    )

    terminated_job_ids: list[str] = []
    submitted_kwargs: dict[str, object] = {}
    uploaded_paths: list[tuple[str, str]] = []
    remote_commands: list[str] = []
    downloaded_paths: list[Path] = []

    class DummyClient:
        def __init__(self, _settings: Settings) -> None:
            self.settings = _settings

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def terminate_job(self, job_id: str) -> None:
            terminated_job_ids.append(job_id)

    monkeypatch.setattr(transfer, "UCloudClient", lambda _settings: DummyClient(_settings))
    monkeypatch.setattr(
        transfer,
        "submit_job_from_latest_template",
        lambda client, **kwargs: submitted_kwargs.update(kwargs) or SimpleNamespace(job_id="job-abc123"),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda client, job_id: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_path_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(transfer, "remote_dir_list", lambda *args, **kwargs: "main.py\nmypkg")
    monkeypatch.setattr(
        transfer,
        "scp_upload",
        lambda alias, local_path, remote_path: uploaded_paths.append((Path(local_path).name, remote_path)),
    )
    monkeypatch.setattr(
        transfer,
        "run_remote_shell_command",
        lambda alias, remote_dir, command: remote_commands.append(command),
    )
    monkeypatch.setattr(
        transfer,
        "scp_download",
        lambda alias, remote_path, local_path: (
            local_path.parent.mkdir(parents=True, exist_ok=True),
            downloaded_paths.append(local_path),
            local_path.write_text("downloaded", encoding="utf-8"),
        ),
    )

    spec = transfer.RemotePythonJobSpec(
        script_path=script_path,
        upload_paths=(package_dir,),
        setup_commands=(transfer.build_pip_install_command(package_dir.name, editable=True),),
        script_args=("--flag", "value with spaces"),
        output_paths=("output/result.txt", "run.log"),
        local_output_root=tmp_path / "artifacts",
    )

    result = transfer.run_remote_python_job(settings, spec, name="demo-job")

    assert submitted_kwargs["mounts"] == []
    assert submitted_kwargs["template_job_id"] is None
    assert uploaded_paths == [
        ("main.py", f"{result.remote_dir}/main.py"),
        ("mypkg", f"{result.remote_dir}/mypkg"),
    ]
    assert remote_commands == [
        "python3 -m pip install --user -e ./mypkg",
        "python3 main.py --flag 'value with spaces'",
    ]
    assert downloaded_paths == [
        result.local_output_dir / "output/result.txt",
        result.local_output_dir / "run.log",
    ]
    assert result.downloaded_paths == tuple(downloaded_paths)
    assert result.local_output_dir == tmp_path / "artifacts" / result.run_id
    assert terminated_job_ids == ["job-abc123"]


def test_run_ssh_transfer_demo_uploads_static_files_and_downloads_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    examples_dir = make_example_tree(tmp_path / "examples")
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        work_folder="/work/moody_agent",
    )

    terminated_job_ids: list[str] = []
    submitted_kwargs: dict[str, object] = {}
    uploaded_paths: list[tuple[str, str]] = []

    class DummyClient:
        def __init__(self, _settings: Settings) -> None:
            self.settings = _settings

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def terminate_job(self, job_id: str) -> None:
            terminated_job_ids.append(job_id)

    monkeypatch.setattr(transfer, "UCloudClient", lambda _settings: DummyClient(_settings))
    monkeypatch.setattr(
        transfer,
        "submit_job_from_latest_template",
        lambda client, **kwargs: submitted_kwargs.update(kwargs) or SimpleNamespace(job_id="job-abc123"),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda client, job_id: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_path_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(transfer, "remote_dir_list", lambda *args, **kwargs: "worker.py\ndummy_input.txt")
    monkeypatch.setattr(
        transfer,
        "scp_upload",
        lambda alias, local_path, remote_path: uploaded_paths.append((Path(local_path).name, remote_path)),
    )
    monkeypatch.setattr(transfer, "start_remote_worker", lambda *args, **kwargs: "999")
    monkeypatch.setattr(
        transfer,
        "sync_outputs_while_running",
        lambda alias, remote_dir, local_output_path, *, poll_seconds: local_output_path.write_text(
            "dummy output",
            encoding="utf-8",
        ),
    )

    result = transfer.run_ssh_transfer_demo(settings, examples_dir=examples_dir)

    assert submitted_kwargs["mounts"] == []
    assert submitted_kwargs["template_job_id"] is None
    assert uploaded_paths == [
        ("worker.py", f"{result.remote_dir}/worker.py"),
        ("dummy_input.txt", f"{result.remote_dir}/dummy_input.txt"),
    ]
    assert result.local_output_path == examples_dir / "dummy_output.txt"
    assert result.local_output_path.read_text(encoding="utf-8") == "dummy output"
    assert terminated_job_ids == ["job-abc123"]


def test_run_ssh_transfer_demo_terminates_job_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    examples_dir = make_example_tree(tmp_path / "examples")
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        work_folder="/work/moody_agent",
    )

    terminated_job_ids: list[str] = []

    class DummyClient:
        def __init__(self, _settings: Settings) -> None:
            self.settings = _settings

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def terminate_job(self, job_id: str) -> None:
            terminated_job_ids.append(job_id)

    monkeypatch.setattr(transfer, "UCloudClient", lambda _settings: DummyClient(_settings))
    monkeypatch.setattr(
        transfer,
        "submit_job_from_latest_template",
        lambda client, **kwargs: SimpleNamespace(job_id="job-abc123"),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda client, job_id: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_path_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(transfer, "remote_dir_list", lambda *args, **kwargs: "worker.py\ndummy_input.txt")
    monkeypatch.setattr(transfer, "scp_upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "start_remote_worker", lambda *args, **kwargs: "999")
    monkeypatch.setattr(transfer, "sync_outputs_while_running", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        transfer.run_ssh_transfer_demo(settings, examples_dir=examples_dir)

    assert terminated_job_ids == ["job-abc123"]
