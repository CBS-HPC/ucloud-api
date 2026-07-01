from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from .client import UCloudClient

SSH_COMMAND_RE = re.compile(r"ssh\s+\S+@\S+\s+-p\s+\d+")
TERMINAL_STATES = {"FAILURE", "EXPIRED", "SUCCESS", "ABORTED", "CANCELLED"}


@dataclass(frozen=True, slots=True)
class JobLaunchResult:
    job_id: str
    ssh_command: str
    job_url: str
    product_id: str | None = None


def _normalize_ucloud_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/") or normalized == "/":
        raise ValueError(
            f"UCloud mount paths must be absolute UCloud paths like '/123/shared'; got {path!r}"
        )
    return normalized


def build_file_resource(path: str, *, read_only: bool = False) -> dict[str, Any]:
    """Build a UCloud file/directory resource mount entry."""
    return {"path": _normalize_ucloud_path(path), "readOnly": read_only, "type": "file"}


def _copy_resource_list(resources: Any) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    if not isinstance(resources, list):
        return copied
    for resource in resources:
        if isinstance(resource, Mapping):
            copied.append(dict(resource))
    return copied


def _merge_file_mounts(
    existing_resources: Any,
    *,
    mounts: list[str],
    read_only_mounts: list[str],
) -> list[dict[str, Any]]:
    merged = _copy_resource_list(existing_resources)
    seen_paths = {
        resource.get("path")
        for resource in merged
        if resource.get("type") == "file" and isinstance(resource.get("path"), str)
    }

    for mount_path in mounts:
        resource = build_file_resource(mount_path, read_only=False)
        if resource["path"] not in seen_paths:
            merged.append(resource)
            seen_paths.add(resource["path"])

    for mount_path in read_only_mounts:
        resource = build_file_resource(mount_path, read_only=True)
        if resource["path"] not in seen_paths:
            merged.append(resource)
            seen_paths.add(resource["path"])

    return merged


def clean_specification(specification: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(dict(specification))
    cleaned.pop("resolvedProduct", None)
    cleaned.pop("resolvedApplication", None)
    cleaned.pop("resolvedSupport", None)

    parameters = cleaned.get("parameters")
    if isinstance(parameters, list):
        for parameter in parameters:
            if isinstance(parameter, MutableMapping):
                parameter.pop("readOnly", None)
    return cleaned


def latest_job_specification(client: UCloudClient) -> dict[str, Any]:
    jobs = client.browse_jobs(items_per_page=1, sort_by="CREATED_AT", include_parameters=True)
    items = jobs.get("items", [])
    if not items:
        raise RuntimeError(
            "No previous UCloud job found. Create one in the UI first so it can be reused as a template."
        )
    specification = items[0].get("specification")
    if not isinstance(specification, Mapping):
        raise RuntimeError("Latest job does not contain a reusable specification.")
    return clean_specification(specification)


def template_job_specification(
    client: UCloudClient,
    *,
    template_job_id: str | None = None,
) -> dict[str, Any]:
    if template_job_id:
        job = client.retrieve_job(template_job_id, include_updates=False)
        specification = job.get("specification")
        if not isinstance(specification, Mapping):
            raise RuntimeError(
                f"Template job {template_job_id!r} does not contain a reusable specification."
            )
        return clean_specification(specification)
    return latest_job_specification(client)


def build_job_specification(
    template: Mapping[str, Any],
    *,
    size: str,
    hours: int,
    name: str | None = None,
    ssh_enabled: bool = True,
    mounts: list[str] | None = None,
    read_only_mounts: list[str] | None = None,
) -> dict[str, Any]:
    specification = clean_specification(template)
    specification["product"] = {
        "id": build_cpu_product_id(size),
        "category": "cpu-amd-zen5",
        "provider": "ucloud",
    }
    specification["timeAllocation"] = {"hours": hours, "minutes": 0, "seconds": 0}
    specification["sshEnabled"] = ssh_enabled
    if mounts or read_only_mounts:
        specification["resources"] = _merge_file_mounts(
            specification.get("resources"),
            mounts=mounts or [],
            read_only_mounts=read_only_mounts or [],
        )
    if name:
        specification["name"] = name
    return specification


def build_cpu_product_id(size: str) -> str:
    clean_size = size.strip()
    if not clean_size:
        raise ValueError("size must not be empty")
    return f"cpu-amd-zen5-{clean_size}"


def extract_job_id(submission_response: Mapping[str, Any]) -> str:
    responses = submission_response.get("responses")
    if isinstance(responses, list) and responses:
        first = responses[0]
        if isinstance(first, Mapping) and first.get("id"):
            return str(first["id"])
    if submission_response.get("id"):
        return str(submission_response["id"])
    raise RuntimeError(f"Could not determine job id from response: {submission_response}")


def submit_job_from_latest_template(
    client: UCloudClient,
    *,
    size: str,
    hours: int,
    name: str | None = None,
    ssh_enabled: bool = True,
    mounts: list[str] | None = None,
    read_only_mounts: list[str] | None = None,
    template_job_id: str | None = None,
) -> JobLaunchResult:
    template = template_job_specification(client, template_job_id=template_job_id)
    specification = build_job_specification(
        template,
        size=size,
        hours=hours,
        name=name,
        ssh_enabled=ssh_enabled,
        mounts=mounts,
        read_only_mounts=read_only_mounts,
    )
    submission = client.submit_job(specification)
    job_id = extract_job_id(submission)
    return JobLaunchResult(
        job_id=job_id,
        ssh_command="",
        job_url=f"{client.settings.server.rstrip('/')}/app/jobs/properties/{job_id}",
        product_id=build_cpu_product_id(size),
    )


def latest_update_state(job: Mapping[str, Any]) -> str:
    updates = job.get("updates")
    if not isinstance(updates, list) or not updates:
        return ""
    latest = updates[-1]
    if not isinstance(latest, Mapping):
        return ""
    state = latest.get("state")
    return str(state) if state else ""


def extract_ssh_command(job: Mapping[str, Any]) -> str:
    updates = job.get("updates")
    if not isinstance(updates, list):
        return ""

    for update in reversed(updates):
        if not isinstance(update, Mapping):
            continue
        for field in ("status", "message", "description", "text"):
            value = update.get(field)
            if not isinstance(value, str):
                continue
            match = SSH_COMMAND_RE.search(value)
            if match:
                return match.group(0)
    return ""


def extract_job_product_id(job: Mapping[str, Any]) -> str | None:
    specification = job.get("specification")
    if not isinstance(specification, Mapping):
        return None
    product = specification.get("product")
    if not isinstance(product, Mapping):
        return None
    product_id = product.get("id")
    if not isinstance(product_id, str):
        return None
    value = product_id.strip()
    return value or None


def wait_for_running_job(
    client: UCloudClient,
    job_id: str,
    *,
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 5,
) -> tuple[dict[str, Any], str]:
    start = time.monotonic()
    ssh_command = ""
    job: dict[str, Any] = {}
    saw_running_state = False

    while True:
        job = client.retrieve_job(job_id, include_updates=True)
        state = latest_update_state(job)
        if state:
            print(f"[{time.strftime('%H:%M:%S')}] State: {state}")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] State: (pending)")

        if state == "RUNNING":
            saw_running_state = True
            ssh_command = extract_ssh_command(job)
            if ssh_command:
                return job, ssh_command
            print(f"[{time.strftime('%H:%M:%S')}] Waiting for SSH command")

        if state in TERMINAL_STATES:
            raise RuntimeError(f"Job ended unexpectedly in state {state!r}")

        if time.monotonic() - start > timeout_seconds:
            if saw_running_state and not ssh_command:
                raise TimeoutError(
                    f"Timed out after {timeout_seconds} seconds waiting for UCloud to expose an SSH command for job {job_id!r}. "
                    "The job reached RUNNING, but no SSH connection was published. "
                    "Use a known SSH-capable template job via UCLOUD_TEMPLATE_JOB_ID."
                )
            raise TimeoutError(f"Timed out after {timeout_seconds} seconds waiting for RUNNING")

        time.sleep(poll_interval_seconds)


def parse_ssh_command(ssh_command: str) -> tuple[str, str, str]:
    match = re.match(r"ssh\s+(?P<user>\S+)@(?P<host>\S+)\s+-p\s+(?P<port>\d+)", ssh_command)
    if not match:
        raise ValueError(f"Unrecognised SSH command: {ssh_command!r}")
    return match.group("user"), match.group("host"), match.group("port")


def find_code_cli() -> str:
    candidates = [
        shutil.which("code"),
        "/usr/local/bin/code",
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        "C:/Program Files/Microsoft VS Code/bin/code.cmd",
        str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/bin/code.cmd"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def update_ssh_config(
    ssh_command: str,
    *,
    alias: str,
    config_path: Path,
) -> dict[str, str]:
    user, host, port = parse_ssh_command(ssh_command)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    begin_marker = f"# >>> ucloud-managed ({alias}) >>>"
    end_marker = f"# <<< ucloud-managed ({alias}) <<<"
    block = [
        begin_marker,
        f"Host {alias}",
        f"    HostName {host}",
        f"    User {user}",
        f"    Port {port}",
        "    StrictHostKeyChecking no",
        "    UserKnownHostsFile /dev/null",
        "    LogLevel ERROR",
        "    ServerAliveInterval 60",
        end_marker,
    ]

    existing = config_path.read_text(encoding="utf-8").splitlines() if config_path.exists() else []
    if begin_marker in existing and end_marker in existing:
        start_index = existing.index(begin_marker)
        end_index = existing.index(end_marker)
        existing = existing[:start_index] + existing[end_index + 1 :]

    while existing and not existing[-1].strip():
        existing.pop()

    text = "\n".join([*existing, "", *block]).strip() + "\n"
    config_path.write_text(text, encoding="utf-8")
    return {"alias": alias, "host": host, "port": port, "user": user}


def open_in_vscode(alias: str, folder: str) -> bool:
    code_cli = find_code_cli()
    if not code_cli:
        return False
    uri = f"vscode-remote://ssh-remote+{alias}{folder}"
    subprocess.Popen([code_cli, "--folder-uri", uri])
    return True
