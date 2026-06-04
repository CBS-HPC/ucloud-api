from __future__ import annotations

from collections.abc import Sequence
import shlex
import subprocess
import time
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .client import UCloudClient
from .jobs import submit_job_from_latest_template, update_ssh_config, wait_for_running_job
from .settings import Settings


DEFAULT_REMOTE_WORK_DIR = "/work/moody_agent"
DEFAULT_POLL_SECONDS = 2
DEFAULT_DUMMY_INPUT_NAME = "dummy_input.txt"
DEFAULT_DUMMY_OUTPUT_NAME = "dummy_output.txt"


@dataclass(frozen=True, slots=True)
class SSHTransferDemoResult:
    job_id: str
    run_id: str
    local_output_path: Path
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


def run_command(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def remote_mkdir(alias: str, remote_dir: str) -> None:
    run_command(["ssh", alias, f"mkdir -p {remote_quote(remote_dir)}"])


def scp_upload(alias: str, local_path: Path, remote_path: str) -> None:
    command = ["scp"]
    if local_path.is_dir():
        command.append("-r")
    command.extend([str(local_path), f"{alias}:{remote_path}"])
    run_command(command)


def scp_download(alias: str, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(["scp", f"{alias}:{remote_path}", str(local_path)])


def remote_path_exists(alias: str, remote_path: str) -> bool:
    completed = run_command(["ssh", alias, f"test -e {remote_quote(remote_path)}"], check=False)
    return completed.returncode == 0


def remote_file_exists(alias: str, remote_path: str) -> bool:
    return remote_path_exists(alias, remote_path)


def remote_dir_list(alias: str, remote_dir: str) -> str:
    completed = run_command(["ssh", alias, f"ls -la {remote_quote(remote_dir)}"])
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


def run_remote_shell_command(alias: str, remote_dir: str, command: str) -> None:
    run_command(["ssh", alias, f"cd {remote_quote(remote_dir)} && {command}"])


def upload_paths_to_remote(alias: str, remote_dir: str, upload_paths: Sequence[Path]) -> None:
    for local_path in upload_paths:
        if not local_path.exists():
            raise FileNotFoundError(f"Missing upload source: {local_path}")
        scp_upload(alias, local_path, f"{remote_dir}/{local_path.name}")


def verify_remote_uploads(alias: str, remote_dir: str, filenames: Sequence[str]) -> None:
    missing = [filename for filename in filenames if not remote_path_exists(alias, f"{remote_dir}/{filename}")]
    if missing:
        listing = remote_dir_list(alias, remote_dir)
        raise FileNotFoundError(
            f"Uploaded files not found in {remote_dir}: {', '.join(missing)}\nRemote listing:\n{listing}"
        )


def run_remote_python_job(
    settings: Settings,
    spec: RemotePythonJobSpec,
    *,
    name: str | None = None,
) -> RemotePythonJobResult:
    if not spec.script_path.is_file():
        raise FileNotFoundError(f"Missing Python script: {spec.script_path}")

    run_id = timestamp_slug()
    local_output_dir = spec.local_output_root / f"{run_id}"
    local_output_dir.mkdir(parents=True, exist_ok=True)
    remote_dir = ""

    upload_paths = [spec.script_path, *spec.upload_paths]

    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=settings.default_size,
            hours=settings.default_hours,
            name=name or f"{spec.job_name_prefix}-{run_id}",
            ssh_enabled=True,
            mounts=settings.mount_paths,
            template_job_id=settings.template_job_id,
        )

        downloaded_paths: list[Path] = []

        try:
            _, ssh_command = wait_for_running_job(client, launched.job_id)
            update_ssh_config(
                ssh_command,
                alias=settings.ssh_alias,
                config_path=settings.ssh_config_path,
            )

            remote_dir = remote_job_directory(settings, run_id, launched.job_id)
            remote_mkdir(settings.ssh_alias, remote_dir)

            upload_paths_to_remote(settings.ssh_alias, remote_dir, upload_paths)
            verify_remote_uploads(
                settings.ssh_alias,
                remote_dir,
                [path.name for path in upload_paths],
            )

            for index, command in enumerate(spec.setup_commands, start=1):
                print(f"Running setup command {index}/{len(spec.setup_commands)}", flush=True)
                run_remote_shell_command(settings.ssh_alias, remote_dir, command)

            run_command_text = build_python_run_command(spec.script_path.name, spec.script_args)
            print(f"Running Python script: {run_command_text}", flush=True)
            run_remote_shell_command(settings.ssh_alias, remote_dir, run_command_text)

            for relative_output_path in spec.output_paths:
                remote_output_path = f"{remote_dir}/{relative_output_path}"
                local_output_path = local_output_dir / relative_output_path
                scp_download(settings.ssh_alias, remote_output_path, local_output_path)
                downloaded_paths.append(local_output_path)
                print(f"Downloaded {relative_output_path} -> {local_output_path}", flush=True)
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
    )


def start_remote_worker(
    alias: str,
    remote_dir: str,
    *,
    delay_seconds: int,
) -> str:
    start_command = (
        f"cd {remote_quote(remote_dir)} && "
        f"nohup python3 worker.py --input {DEFAULT_DUMMY_INPUT_NAME} --output {DEFAULT_DUMMY_OUTPUT_NAME} "
        f"--delay {delay_seconds} > run.log 2>&1 </dev/null & echo $!"
    )
    completed = run_command(["ssh", alias, start_command])
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
) -> None:
    remote_output = f"{remote_dir}/{DEFAULT_DUMMY_OUTPUT_NAME}"
    print(f"Waiting for {DEFAULT_DUMMY_OUTPUT_NAME}", flush=True)
    wait_for_remote_file(
        alias,
        remote_output,
        timeout_seconds=900,
        poll_seconds=poll_seconds,
    )
    scp_download(alias, remote_output, local_output_path)
    print(f"Downloaded {DEFAULT_DUMMY_OUTPUT_NAME} -> {local_output_path}", flush=True)

def run_ssh_transfer_demo(
    settings: Settings,
    *,
    examples_dir: Path | None = None,
    local_output_path: Path | None = None,
    delay_seconds: int = 0,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
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

    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=settings.default_size,
            hours=settings.default_hours,
            name=f"ssh-transfer-demo-{run_id}",
            ssh_enabled=True,
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

            remote_dir = remote_job_directory(settings, run_id, launched.job_id)
            remote_mkdir(settings.ssh_alias, remote_dir)
            print(f"Uploading static files to {remote_dir}", flush=True)
            scp_upload(settings.ssh_alias, worker_script_path, f"{remote_dir}/worker.py")
            scp_upload(settings.ssh_alias, dummy_input_path, f"{remote_dir}/{DEFAULT_DUMMY_INPUT_NAME}")
            verify_remote_uploads(
                settings.ssh_alias,
                remote_dir,
                ["worker.py", DEFAULT_DUMMY_INPUT_NAME],
            )
            print(f"Verified uploads in {remote_dir}", flush=True)

            pid = start_remote_worker(
                settings.ssh_alias,
                remote_dir,
                delay_seconds=delay_seconds,
            )
            print(f"Remote worker started with PID {pid}")
            sync_outputs_while_running(
                settings.ssh_alias,
                remote_dir,
                local_output_path,
                poll_seconds=poll_seconds,
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
        remote_dir=remote_dir,
    )
