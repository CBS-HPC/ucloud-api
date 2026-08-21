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
    analysis_calls: list[tuple[Path, str | None]] = []

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
        lambda client, **kwargs: (
            submitted_kwargs.update(kwargs)
            or SimpleNamespace(job_id="job-abc123", product_id="cpu-amd-zen5-128-vcpu")
        ),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda client, job_id: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_path_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(transfer, "remote_dir_list", lambda *args, **kwargs: "main.py\nmypkg")
    monkeypatch.setattr(
        transfer,
        "analyze_job_report",
        lambda report_path, *, current_machine_product=None: (
            analysis_calls.append((report_path, current_machine_product)) or SimpleNamespace()
        ),
    )
    monkeypatch.setattr(transfer, "render_utilization_analysis", lambda analysis: "utilization analysis")
    monkeypatch.setattr(
        transfer,
        "scp_upload",
        lambda alias, local_path, remote_path, **_kwargs: uploaded_paths.append((Path(local_path).name, remote_path)),
    )
    monkeypatch.setattr(
        transfer,
        "run_remote_shell_command",
        lambda alias, remote_dir, command, **_kwargs: remote_commands.append(command),
    )
    monkeypatch.setattr(
        transfer,
        "scp_download",
        lambda alias, remote_path, local_path, **_kwargs: (
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
        result.local_output_dir / "job-report.csv",
    ]
    assert result.downloaded_paths == (
        result.local_output_dir / "output/result.txt",
        result.local_output_dir / "run.log",
    )
    assert result.local_output_dir == tmp_path / "artifacts" / result.run_id
    assert result.job_report_path == result.local_output_dir / "job-report.csv"
    assert analysis_calls == [
        (result.local_output_dir / "job-report.csv", "cpu-amd-zen5-128-vcpu"),
    ]
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
    downloaded_paths: list[Path] = []
    analysis_calls: list[tuple[Path, str | None]] = []

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
        lambda client, **kwargs: (
            submitted_kwargs.update(kwargs)
            or SimpleNamespace(job_id="job-abc123", product_id="cpu-amd-zen5-128-vcpu")
        ),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda client, job_id: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer, "remote_path_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(transfer, "remote_dir_list", lambda *args, **kwargs: "worker.py\ndummy_input.txt")
    monkeypatch.setattr(
        transfer,
        "analyze_job_report",
        lambda report_path, *, current_machine_product=None: (
            analysis_calls.append((report_path, current_machine_product)) or SimpleNamespace()
        ),
    )
    monkeypatch.setattr(transfer, "render_utilization_analysis", lambda analysis: "utilization analysis")
    monkeypatch.setattr(
        transfer,
        "scp_upload",
        lambda alias, local_path, remote_path, **_kwargs: uploaded_paths.append((Path(local_path).name, remote_path)),
    )
    monkeypatch.setattr(
        transfer,
        "scp_download",
        lambda alias, remote_path, local_path, **_kwargs: (
            local_path.parent.mkdir(parents=True, exist_ok=True),
            downloaded_paths.append(local_path),
            local_path.write_text("downloaded", encoding="utf-8"),
        ),
    )
    monkeypatch.setattr(transfer, "start_remote_worker", lambda *args, **kwargs: "999")
    monkeypatch.setattr(
        transfer,
        "sync_outputs_while_running",
        lambda alias, remote_dir, local_output_path, *, poll_seconds, **_kwargs: local_output_path.write_text(
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
    assert downloaded_paths == [examples_dir / "job-report.csv"]
    assert result.local_output_path == examples_dir / "dummy_output.txt"
    assert result.local_output_path.read_text(encoding="utf-8") == "dummy output"
    assert result.job_report_path == examples_dir / "job-report.csv"
    assert analysis_calls == [
        (examples_dir / "job-report.csv", "cpu-amd-zen5-128-vcpu"),
    ]
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


def test_run_command_times_out_and_cleans_up_the_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_pids: list[int] = []
    popen_calls: list[dict[str, object]] = []

    class HungProcess:
        pid = 1234
        returncode: int | None = None

        def __init__(self) -> None:
            self.communicate_calls: list[float | None] = []

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.communicate_calls.append(timeout)
            if len(self.communicate_calls) == 1:
                raise subprocess.TimeoutExpired("ssh", timeout)
            self.returncode = -9
            return "", ""

    process = HungProcess()

    def fake_popen(_args: list[str], **kwargs: object) -> HungProcess:
        popen_calls.append(kwargs)
        return process

    monkeypatch.setattr(transfer.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        transfer,
        "terminate_process_tree",
        lambda timed_out_process: cleanup_pids.append(timed_out_process.pid),
    )

    with pytest.raises(transfer.RemoteCommandTimeoutError, match="SSH readiness probe timed out after 1"):
        transfer.run_command(
            ["ssh", "ucloud", "true"],
            timeout_seconds=1,
            command_name="SSH readiness probe",
        )

    assert cleanup_pids == [1234]
    assert process.communicate_calls == [1, None]
    if sys.platform == "win32":
        assert popen_calls[0]["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert popen_calls[0]["start_new_session"] is True


def test_terminate_process_tree_uses_taskkill_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    class Process:
        pid = 1234

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

    monkeypatch.setattr(transfer.os, "name", "nt")
    monkeypatch.setattr(
        transfer.subprocess,
        "run",
        lambda args, **_kwargs: commands.append(args) or SimpleNamespace(returncode=0),
    )

    transfer.terminate_process_tree(Process())

    assert commands == [["taskkill", "/PID", "1234", "/T", "/F"]]


def test_wait_for_ssh_ready_retries_noninteractive_probe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probes: list[tuple[list[str], float]] = []
    responses = [255, 255, 0]

    def fake_run_command(
        args: list[str],
        *,
        check: bool,
        timeout_seconds: float,
        command_name: str,
    ) -> subprocess.CompletedProcess[str]:
        probes.append((args, timeout_seconds))
        return subprocess.CompletedProcess(args, responses.pop(0), "", "not ready")

    monkeypatch.setattr(transfer, "run_command", fake_run_command)

    transfer.wait_for_ssh_ready("ucloud", attempts=3, retry_seconds=0, probe_timeout_seconds=25)

    assert len(probes) == 3
    assert probes[0] == (
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
            "-o",
            "NumberOfPasswordPrompts=0",
            "ucloud",
            "true",
        ],
        25,
    )
    assert "Starting SSH readiness probe 1/3" in capsys.readouterr().out


def test_scp_commands_are_noninteractive_and_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[tuple[list[str], float]] = []
    local_file = tmp_path / "input.txt"
    local_file.write_text("input", encoding="utf-8")

    def fake_run_command(
        args: list[str],
        *,
        check: bool = True,
        timeout_seconds: float,
        command_name: str,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((args, timeout_seconds))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(transfer, "run_command", fake_run_command)

    transfer.scp_upload("ucloud", local_file, "/work/input.txt", timeout_seconds=17)
    transfer.scp_download("ucloud", "/work/output.txt", tmp_path / "output.txt", timeout_seconds=19)

    assert commands == [
        (
            [
                "scp",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "-o",
                "NumberOfPasswordPrompts=0",
                str(local_file),
                "ucloud:/work/input.txt",
            ],
            17,
        ),
        (
            [
                "scp",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "-o",
                "NumberOfPasswordPrompts=0",
                "ucloud:/work/output.txt",
                str(tmp_path / "output.txt"),
            ],
            19,
        ),
    ]


def test_remote_python_job_terminates_when_workspace_preparation_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "main.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")
    settings = Settings(server="https://cloud.sdu.dk", token="token", project="Moody's Datahub")
    terminated_job_ids: list[str] = []

    class DummyClient:
        def __init__(self, _settings: Settings) -> None:
            pass

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
        lambda _client, **_kwargs: SimpleNamespace(job_id="job-abc123"),
    )
    monkeypatch.setattr(transfer, "wait_for_running_job", lambda *_args: ({}, "ssh ucloud@host -p 22"))
    monkeypatch.setattr(transfer, "update_ssh_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        transfer,
        "remote_mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            transfer.SSHReadinessError("ucloud", attempts=6)
        ),
    )

    with pytest.raises(transfer.SSHReadinessError, match="not ready"):
        transfer.run_remote_python_job(
            settings,
            transfer.RemotePythonJobSpec(script_path=script_path, local_output_root=tmp_path / "artifacts"),
        )

    assert terminated_job_ids == ["job-abc123"]
