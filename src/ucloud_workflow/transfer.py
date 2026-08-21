from __future__ import annotations

from collections.abc import Callable, Sequence
import math
import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import TypeVar

from .client import UCloudClient
from .jobs import submit_job_from_latest_template, update_ssh_config, wait_for_running_job
from .settings import Settings
from .utilization import analyze_job_report, render_utilization_analysis


DEFAULT_REMOTE_WORK_DIR = "/work/moody_agent"
DEFAULT_REMOTE_JOB_REPORT_PATH = "/work/job-report.csv"
DEFAULT_POLL_SECONDS = 2
DEFAULT_DUMMY_INPUT_NAME = "dummy_input.txt"
DEFAULT_DUMMY_OUTPUT_NAME = "dummy_output.txt"
DEFAULT_JOB_REPORT_NAME = "job-report.csv"
SSH_CONNECT_TIMEOUT_SECONDS = 20
DEFAULT_SSH_TRANSPORT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_SSH_READINESS_ATTEMPTS = 6
DEFAULT_SSH_READINESS_PROBE_TIMEOUT_SECONDS = SSH_CONNECT_TIMEOUT_SECONDS + 5
DEFAULT_SSH_READINESS_RETRY_SECONDS = 5
DEFAULT_REMOTE_WORKSPACE_TIMEOUT_SECONDS = 3 * 60
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 15 * 60
DEFAULT_UPLOAD_VERIFY_TIMEOUT_SECONDS = 2 * 60
DEFAULT_REMOTE_SETUP_TIMEOUT_SECONDS = 30 * 60
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 15 * 60
SSH_TRANSPORT_OPTIONS = (
    "-o",
    "BatchMode=yes",
    "-o",
    f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=2",
    "-o",
    "NumberOfPasswordPrompts=0",
)

T = TypeVar("T")


class RemoteCommandTimeoutError(TimeoutError):
    """Raised after a bounded SSH or SCP transport process is terminated."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"{operation} timed out after {timeout_seconds:g} seconds; "
            "the local transport process was terminated."
        )


class SSHReadinessError(RuntimeError):
    """Raised when UCloud exposes an SSH command before its endpoint is usable."""

    def __init__(self, alias: str, *, attempts: int) -> None:
        self.alias = alias
        self.attempts = attempts
        super().__init__(
            f"SSH endpoint for alias {alias!r} was not ready after {attempts} bounded probe attempts."
        )


@dataclass(frozen=True, slots=True)
class SSHTransferDemoResult:
    job_id: str
    run_id: str
    local_output_path: Path
    job_report_path: Path | None
    remote_dir: str


@dataclass(frozen=True, slots=True)
class RemotePythonJobSpec:
    script_path: Path
    upload_paths: tuple[Path, ...] = ()
    setup_commands: tuple[str, ...] = ()
    script_args: tuple[str, ...] = ()
    output_paths: tuple[str, ...] = ()
    local_output_root: Path = Path("artifacts") / "python-job"
    job_name_prefix: str = "python-job"


@dataclass(frozen=True, slots=True)
class RemotePythonJobResult:
    job_id: str
    run_id: str
    remote_dir: str
    local_output_dir: Path
    downloaded_paths: tuple[Path, ...]
    job_report_path: Path | None


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def default_examples_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "examples"


def remote_work_root(settings: Settings) -> str:
    return settings.work_folder.rstrip("/") or DEFAULT_REMOTE_WORK_DIR


def remote_job_directory(settings: Settings, run_id: str, job_id: str) -> str:
    return f"{remote_work_root(settings)}/{run_id}-{job_id}"


def remote_quote(path: str) -> str:
    return shlex.quote(path)


def _transport_popen_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a timed-out transport process and every child it started."""
    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    try:
        process.kill()
    except OSError:
        pass


def run_command(
    args: list[str],
    *,
    check: bool = True,
    timeout_seconds: float = DEFAULT_SSH_TRANSPORT_TIMEOUT_SECONDS,
    command_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_transport_popen_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process)
        stdout, stderr = process.communicate()
        operation = command_name or Path(args[0]).name
        raise RemoteCommandTimeoutError(operation, timeout_seconds) from None

    completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def ssh_command(alias: str, remote_command: str) -> list[str]:
    return ["ssh", *SSH_TRANSPORT_OPTIONS, alias, remote_command]


def scp_command(*arguments: str) -> list[str]:
    return ["scp", *SSH_TRANSPORT_OPTIONS, *arguments]


def _remaining_timeout_seconds(deadline: float, operation: str) -> float:
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise RemoteCommandTimeoutError(operation, 0)
    return max(1, math.ceil(remaining_seconds))


def wait_for_ssh_ready(
    alias: str,
    *,
    attempts: int = DEFAULT_SSH_READINESS_ATTEMPTS,
    retry_seconds: float = DEFAULT_SSH_READINESS_RETRY_SECONDS,
    probe_timeout_seconds: float = DEFAULT_SSH_READINESS_PROBE_TIMEOUT_SECONDS,
    timeout_seconds: float | None = None,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    if retry_seconds < 0:
        raise ValueError("retry_seconds must not be negative")
    if probe_timeout_seconds <= 0:
        raise ValueError("probe_timeout_seconds must be greater than zero")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    completed_attempts = 0
    for attempt in range(1, attempts + 1):
        effective_probe_timeout_seconds = probe_timeout_seconds
        if deadline is not None:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            effective_probe_timeout_seconds = min(
                probe_timeout_seconds,
                max(1, math.ceil(remaining_seconds)),
            )
        completed_attempts = attempt
        print(
            f"Starting SSH readiness probe {attempt}/{attempts} (budget: {effective_probe_timeout_seconds:g}s)",
            flush=True,
        )
        try:
            completed = run_command(
                ssh_command(alias, "true"),
                check=False,
                timeout_seconds=effective_probe_timeout_seconds,
                command_name="SSH readiness probe",
            )
        except RemoteCommandTimeoutError:
            print(f"SSH readiness probe {attempt}/{attempts} timed out", flush=True)
        else:
            if completed.returncode == 0:
                print(f"SSH readiness probe {attempt}/{attempts} completed", flush=True)
                return
            print(
                f"SSH readiness probe {attempt}/{attempts} failed with exit code {completed.returncode}",
                flush=True,
            )

        if attempt < attempts:
            sleep_seconds = retry_seconds
            if deadline is not None:
                sleep_seconds = min(sleep_seconds, max(0, deadline - time.monotonic()))
            time.sleep(sleep_seconds)

    raise SSHReadinessError(alias, attempts=completed_attempts)


def remote_mkdir(
    alias: str,
    remote_dir: str,
    *,
    timeout_seconds: float = DEFAULT_REMOTE_WORKSPACE_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    wait_for_ssh_ready(alias, timeout_seconds=timeout_seconds)
    run_command(
        ssh_command(alias, f"mkdir -p {remote_quote(remote_dir)}"),
        timeout_seconds=_remaining_timeout_seconds(deadline, "prepare_remote_workspace"),
        command_name="prepare_remote_workspace",
    )


def scp_upload(
    alias: str,
    local_path: Path,
    remote_path: str,
    *,
    timeout_seconds: float = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
) -> None:
    command = scp_command()
    if local_path.is_dir():
        command.append("-r")
    command.extend([str(local_path), f"{alias}:{remote_path}"])
    run_command(command, timeout_seconds=timeout_seconds, command_name="upload files")


def scp_download(
    alias: str,
    remote_path: str,
    local_path: Path,
    *,
    timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        scp_command(f"{alias}:{remote_path}", str(local_path)),
        timeout_seconds=timeout_seconds,
        command_name="download files",
    )


def remote_path_exists(
    alias: str,
    remote_path: str,
    *,
    timeout_seconds: float = DEFAULT_SSH_READINESS_PROBE_TIMEOUT_SECONDS,
) -> bool:
    completed = run_command(
        ssh_command(alias, f"test -e {remote_quote(remote_path)}"),
        check=False,
        timeout_seconds=timeout_seconds,
        command_name="remote path check",
    )
    return completed.returncode == 0


def remote_file_exists(
    alias: str,
    remote_path: str,
    *,
    timeout_seconds: float = DEFAULT_SSH_READINESS_PROBE_TIMEOUT_SECONDS,
) -> bool:
    return remote_path_exists(alias, remote_path, timeout_seconds=timeout_seconds)


def download_optional_remote_file(
    alias: str,
    remote_path: str,
    local_path: Path,
    *,
    timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> Path | None:
    deadline = time.monotonic() + timeout_seconds
    if not remote_path_exists(
        alias,
        remote_path,
        timeout_seconds=_remaining_timeout_seconds(deadline, "download optional file"),
    ):
        return None
    scp_download(
        alias,
        remote_path,
        local_path,
        timeout_seconds=_remaining_timeout_seconds(deadline, "download optional file"),
    )
    return local_path


def download_optional_job_report(
    alias: str,
    local_output_dir: Path,
    *,
    timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> Path | None:
    local_report_path = local_output_dir / DEFAULT_JOB_REPORT_NAME
    return download_optional_remote_file(
        alias,
        DEFAULT_REMOTE_JOB_REPORT_PATH,
        local_report_path,
        timeout_seconds=timeout_seconds,
    )


def print_job_report_analysis(
    report_path: Path,
    *,
    current_machine_product: str | None = None,
) -> None:
    try:
        analysis = analyze_job_report(
            report_path,
            current_machine_product=current_machine_product,
        )
        print(render_utilization_analysis(analysis), flush=True)
    except Exception as exc:
        print(
            f"Warning: could not analyze utilization report {report_path}: {exc}",
            file=sys.stderr,
        )


def remote_dir_list(
    alias: str,
    remote_dir: str,
    *,
    timeout_seconds: float = DEFAULT_UPLOAD_VERIFY_TIMEOUT_SECONDS,
) -> str:
    completed = run_command(
        ssh_command(alias, f"ls -la {remote_quote(remote_dir)}"),
        timeout_seconds=timeout_seconds,
        command_name="list remote workspace",
    )
    return completed.stdout.strip()


def wait_for_remote_file(
    alias: str,
    remote_path: str,
    *,
    timeout_seconds: int = 600,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
) -> None:
    start = time.monotonic()
    while not remote_file_exists(alias, remote_path):
        if time.monotonic() - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for {remote_path}")
        time.sleep(poll_seconds)


def build_python_run_command(script_name: str, script_args: Sequence[str]) -> str:
    return shlex.join(["python3", script_name, *script_args])


def build_pip_install_command(package_name: str, *, editable: bool = False) -> str:
    package_target = f"./{package_name}"
    if editable:
        return shlex.join(["python3", "-m", "pip", "install", "--user", "-e", package_target])
    return shlex.join(["python3", "-m", "pip", "install", "--user", package_target])


def run_remote_shell_command(
    alias: str,
    remote_dir: str,
    command: str,
    *,
    timeout_seconds: float = DEFAULT_REMOTE_SETUP_TIMEOUT_SECONDS,
) -> None:
    run_command(
        ssh_command(alias, f"cd {remote_quote(remote_dir)} && {command}"),
        timeout_seconds=timeout_seconds,
        command_name="remote shell command",
    )


def upload_paths_to_remote(
    alias: str,
    remote_dir: str,
    upload_paths: Sequence[Path],
    *,
    timeout_seconds: float = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    for local_path in upload_paths:
        if not local_path.exists():
            raise FileNotFoundError(f"Missing upload source: {local_path}")
        scp_upload(
            alias,
            local_path,
            f"{remote_dir}/{local_path.name}",
            timeout_seconds=_remaining_timeout_seconds(deadline, "upload local files"),
        )


def verify_remote_uploads(
    alias: str,
    remote_dir: str,
    filenames: Sequence[str],
    *,
    timeout_seconds: float = DEFAULT_UPLOAD_VERIFY_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    missing = [
        filename
        for filename in filenames
        if not remote_path_exists(
            alias,
            f"{remote_dir}/{filename}",
            timeout_seconds=_remaining_timeout_seconds(deadline, "verify uploaded files"),
        )
    ]
    if missing:
        listing = remote_dir_list(
            alias,
            remote_dir,
            timeout_seconds=_remaining_timeout_seconds(deadline, "verify uploaded files"),
        )
        raise FileNotFoundError(
            f"Uploaded files not found in {remote_dir}: {', '.join(missing)}\nRemote listing:\n{listing}"
        )


def run_setup_stage(
    name: str,
    *,
    timeout_seconds: float,
    operation: Callable[[float], T],
) -> T:
    started = time.monotonic()
    print(f"Starting {name} (budget: {timeout_seconds:g}s)", flush=True)
    try:
        result = operation(timeout_seconds)
    except Exception:
        elapsed_seconds = time.monotonic() - started
        print(f"{name} failed after {elapsed_seconds:.1f}s", flush=True)
        raise
    elapsed_seconds = time.monotonic() - started
    print(f"Completed {name} in {elapsed_seconds:.1f}s", flush=True)
    return result


def remote_execution_timeout_seconds(settings: Settings) -> int:
    return max(1, settings.default_hours * 60 * 60 + 5 * 60)


def run_remote_python_job(
    settings: Settings,
    spec: RemotePythonJobSpec,
    *,
    name: str | None = None,
    template_job_id: str | None = None,
) -> RemotePythonJobResult:
    if not spec.script_path.is_file():
        raise FileNotFoundError(f"Missing Python script: {spec.script_path}")

    run_id = timestamp_slug()
    local_output_dir = spec.local_output_root / f"{run_id}"
    local_output_dir.mkdir(parents=True, exist_ok=True)
    remote_dir = ""
    job_report_path: Path | None = None

    upload_paths = [spec.script_path, *spec.upload_paths]
    selected_template_job_id = settings.template_job_id if template_job_id is None else template_job_id

    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=settings.default_size,
            hours=settings.default_hours,
            name=name or f"{spec.job_name_prefix}-{run_id}",
            ssh_enabled=True,
            mounts=[],
            template_job_id=selected_template_job_id,
        )

        downloaded_paths: list[Path] = []

        try:
            _, ssh_command = wait_for_running_job(client, launched.job_id)
            update_ssh_config(
                ssh_command,
                alias=settings.ssh_alias,
                config_path=settings.ssh_config_path,
            )
            current_machine_product = getattr(launched, "product_id", None)

            remote_dir = remote_job_directory(settings, run_id, launched.job_id)
            run_setup_stage(
                "prepare_remote_workspace",
                timeout_seconds=DEFAULT_REMOTE_WORKSPACE_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: remote_mkdir(
                    settings.ssh_alias,
                    remote_dir,
                    timeout_seconds=timeout_seconds,
                ),
            )

            run_setup_stage(
                "upload_local_files",
                timeout_seconds=DEFAULT_UPLOAD_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: upload_paths_to_remote(
                    settings.ssh_alias,
                    remote_dir,
                    upload_paths,
                    timeout_seconds=timeout_seconds,
                ),
            )
            run_setup_stage(
                "verify_uploaded_files",
                timeout_seconds=DEFAULT_UPLOAD_VERIFY_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: verify_remote_uploads(
                    settings.ssh_alias,
                    remote_dir,
                    [path.name for path in upload_paths],
                    timeout_seconds=timeout_seconds,
                ),
            )

            for index, command in enumerate(spec.setup_commands, start=1):
                run_setup_stage(
                    f"setup_command_{index}_of_{len(spec.setup_commands)}",
                    timeout_seconds=DEFAULT_REMOTE_SETUP_TIMEOUT_SECONDS,
                    operation=lambda timeout_seconds, command=command: run_remote_shell_command(
                        settings.ssh_alias,
                        remote_dir,
                        command,
                        timeout_seconds=timeout_seconds,
                    ),
                )

            run_command_text = build_python_run_command(spec.script_path.name, spec.script_args)
            run_setup_stage(
                "run_python_script",
                timeout_seconds=remote_execution_timeout_seconds(settings),
                operation=lambda timeout_seconds: run_remote_shell_command(
                    settings.ssh_alias,
                    remote_dir,
                    run_command_text,
                    timeout_seconds=timeout_seconds,
                ),
            )

            for relative_output_path in spec.output_paths:
                remote_output_path = f"{remote_dir}/{relative_output_path}"
                local_output_path = local_output_dir / relative_output_path
                run_setup_stage(
                    f"download_{relative_output_path}",
                    timeout_seconds=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
                    operation=lambda timeout_seconds, remote_output_path=remote_output_path, local_output_path=local_output_path: scp_download(
                        settings.ssh_alias,
                        remote_output_path,
                        local_output_path,
                        timeout_seconds=timeout_seconds,
                    ),
                )
                downloaded_paths.append(local_output_path)
                print(f"Downloaded {relative_output_path} -> {local_output_path}", flush=True)

            job_report_path = run_setup_stage(
                "download_job_report",
                timeout_seconds=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: download_optional_job_report(
                    settings.ssh_alias,
                    local_output_dir,
                    timeout_seconds=timeout_seconds,
                ),
            )
            if job_report_path is not None:
                print(f"Downloaded job report -> {job_report_path}", flush=True)
                print_job_report_analysis(
                    job_report_path,
                    current_machine_product=current_machine_product,
                )
        finally:
            try:
                client.terminate_job(launched.job_id)
                print(f"Terminated UCloud job {launched.job_id}")
            except Exception as exc:
                print(
                    f"Warning: could not terminate UCloud job {launched.job_id}: {exc}",
                    file=sys.stderr,
                )

    return RemotePythonJobResult(
        job_id=launched.job_id,
        run_id=run_id,
        remote_dir=remote_dir,
        local_output_dir=local_output_dir,
        downloaded_paths=tuple(downloaded_paths),
        job_report_path=job_report_path,
    )


def start_remote_worker(
    alias: str,
    remote_dir: str,
    *,
    delay_seconds: int,
    timeout_seconds: float = DEFAULT_REMOTE_SETUP_TIMEOUT_SECONDS,
) -> str:
    start_command = (
        f"cd {remote_quote(remote_dir)} && "
        f"nohup python3 worker.py --input {DEFAULT_DUMMY_INPUT_NAME} --output {DEFAULT_DUMMY_OUTPUT_NAME} "
        f"--delay {delay_seconds} > run.log 2>&1 </dev/null & echo $!"
    )
    completed = run_command(
        ssh_command(alias, start_command),
        timeout_seconds=timeout_seconds,
        command_name="start remote worker",
    )
    pid = completed.stdout.strip().splitlines()[-1].strip()
    if not pid:
        raise RuntimeError("Could not read remote worker PID")
    return pid


def sync_outputs_while_running(
    alias: str,
    remote_dir: str,
    local_output_path: Path,
    *,
    poll_seconds: int,
    timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> None:
    remote_output = f"{remote_dir}/{DEFAULT_DUMMY_OUTPUT_NAME}"
    deadline = time.monotonic() + timeout_seconds
    print(f"Waiting for {DEFAULT_DUMMY_OUTPUT_NAME}", flush=True)
    wait_for_remote_file(
        alias,
        remote_output,
        timeout_seconds=math.ceil(_remaining_timeout_seconds(deadline, "download dummy output")),
        poll_seconds=poll_seconds,
    )
    scp_download(
        alias,
        remote_output,
        local_output_path,
        timeout_seconds=_remaining_timeout_seconds(deadline, "download dummy output"),
    )
    print(f"Downloaded {DEFAULT_DUMMY_OUTPUT_NAME} -> {local_output_path}", flush=True)

def run_ssh_transfer_demo(
    settings: Settings,
    *,
    examples_dir: Path | None = None,
    local_output_path: Path | None = None,
    delay_seconds: int = 0,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    template_job_id: str | None = None,
) -> SSHTransferDemoResult:
    examples_dir = examples_dir or default_examples_dir()
    worker_script_path = examples_dir / "worker.py"
    dummy_input_path = examples_dir / DEFAULT_DUMMY_INPUT_NAME
    local_output_path = local_output_path or examples_dir / DEFAULT_DUMMY_OUTPUT_NAME

    if not worker_script_path.is_file():
        raise FileNotFoundError(f"Missing worker script: {worker_script_path}")
    if not dummy_input_path.is_file():
        raise FileNotFoundError(f"Missing dummy input file: {dummy_input_path}")

    run_id = timestamp_slug()
    local_output_path.parent.mkdir(parents=True, exist_ok=True)
    remote_dir = ""
    job_report_path: Path | None = None
    selected_template_job_id = settings.template_job_id if template_job_id is None else template_job_id

    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=settings.default_size,
            hours=settings.default_hours,
            name=f"ssh-transfer-demo-{run_id}",
            ssh_enabled=True,
            mounts=[],
            template_job_id=selected_template_job_id,
        )

        try:
            _, ssh_command = wait_for_running_job(client, launched.job_id)
            update_ssh_config(
                ssh_command,
                alias=settings.ssh_alias,
                config_path=settings.ssh_config_path,
            )
            current_machine_product = getattr(launched, "product_id", None)

            remote_dir = remote_job_directory(settings, run_id, launched.job_id)
            run_setup_stage(
                "prepare_remote_workspace",
                timeout_seconds=DEFAULT_REMOTE_WORKSPACE_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: remote_mkdir(
                    settings.ssh_alias,
                    remote_dir,
                    timeout_seconds=timeout_seconds,
                ),
            )
            print(f"Uploading static files to {remote_dir}", flush=True)
            run_setup_stage(
                "upload_static_files",
                timeout_seconds=DEFAULT_UPLOAD_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: upload_paths_to_remote(
                    settings.ssh_alias,
                    remote_dir,
                    [worker_script_path, dummy_input_path],
                    timeout_seconds=timeout_seconds,
                ),
            )
            run_setup_stage(
                "verify_uploaded_files",
                timeout_seconds=DEFAULT_UPLOAD_VERIFY_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: verify_remote_uploads(
                    settings.ssh_alias,
                    remote_dir,
                    ["worker.py", DEFAULT_DUMMY_INPUT_NAME],
                    timeout_seconds=timeout_seconds,
                ),
            )
            print(f"Verified uploads in {remote_dir}", flush=True)

            pid = run_setup_stage(
                "start_remote_worker",
                timeout_seconds=DEFAULT_REMOTE_SETUP_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: start_remote_worker(
                    settings.ssh_alias,
                    remote_dir,
                    delay_seconds=delay_seconds,
                    timeout_seconds=timeout_seconds,
                ),
            )
            print(f"Remote worker started with PID {pid}")
            run_setup_stage(
                "download_dummy_output",
                timeout_seconds=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: sync_outputs_while_running(
                    settings.ssh_alias,
                    remote_dir,
                    local_output_path,
                    poll_seconds=poll_seconds,
                    timeout_seconds=timeout_seconds,
                ),
            )
            job_report_path = run_setup_stage(
                "download_job_report",
                timeout_seconds=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
                operation=lambda timeout_seconds: download_optional_job_report(
                    settings.ssh_alias,
                    examples_dir,
                    timeout_seconds=timeout_seconds,
                ),
            )
            if job_report_path is not None:
                print(f"Downloaded job report -> {job_report_path}", flush=True)
                print_job_report_analysis(
                    job_report_path,
                    current_machine_product=current_machine_product,
                )
        finally:
            try:
                client.terminate_job(launched.job_id)
                print(f"Terminated UCloud job {launched.job_id}")
            except Exception as exc:
                print(
                    f"Warning: could not terminate UCloud job {launched.job_id}: {exc}",
                    file=sys.stderr,
                )

    return SSHTransferDemoResult(
        job_id=launched.job_id,
        run_id=run_id,
        local_output_path=local_output_path,
        job_report_path=job_report_path,
        remote_dir=remote_dir,
    )
