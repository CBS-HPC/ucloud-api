from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import httpx

from .client import UCloudAPIError, UCloudClient
from .resources import ManagementError, browse_all, management_call


DEFAULT_STORAGE_FOLDER = "ucloud-workflow"


def _object(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManagementError("Malformed setup metadata; no configuration changes made")
    return value


def _can_write(item: dict) -> bool:
    permissions = _object(item.get("permissions")).get("myself")
    if permissions is None:
        return False
    if not isinstance(permissions, list) or any(not isinstance(permission, str) for permission in permissions):
        raise ManagementError("Malformed setup permissions; write access could not be verified")
    return bool(set(permissions) & {"EDIT", "ADMIN"})


def validate_server(server: str) -> str:
    parsed = urlsplit(server)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Setup requires an HTTPS UCloud server origin without credentials or query parameters")
    return server.rstrip("/")


def list_projects(client: UCloudClient) -> list[dict]:
    return [project for project in browse_all(client.browse_projects)
            if project.get("id") and _object(project.get("specification"))
            and not _object(project.get("status")).get("archived")
            and project["specification"].get("canConsumeResources") is not False]


def list_writable_drives(client: UCloudClient) -> list[dict]:
    drives = []
    for drive in browse_all(client.browse_drives):
        support = _object(_object(_object(drive.get("status")).get("resolvedSupport")).get("support"))
        if (drive.get("id") and _can_write(drive)
                and _object(support.get("files")).get("isReadOnly") is False):
            drives.append(drive)
    return drives


def storage_directory_path(drive_id: str, path: str | None = None) -> str:
    target = path.rstrip("/") if path is not None else f"/{drive_id}/{DEFAULT_STORAGE_FOLDER}"
    components = target.split("/")
    if (len(components) < 3 or components[0] != "" or components[1] != drive_id
            or any(component in {"", ".", ".."} for component in components[1:])
            or "\\" in target or any(ord(character) < 32 or ord(character) == 127 for character in target)):
        raise ValueError("Storage path must be an absolute folder path inside the selected drive, without traversal")
    return target


def _directory(client: UCloudClient, path: str) -> dict | None:
    try:
        item = client.retrieve_file(path)
    except UCloudAPIError as error:
        if error.status_code == 404:
            return None
        if error.status_code == 400 and path.count("/") >= 2:
            parent = path.rsplit("/", 1)[0]
            matches = [entry for entry in browse_all(lambda **kwargs: client.browse_files(parent, **kwargs))
                       if entry.get("id") == path]
            if not matches:
                return None
            if len(matches) != 1:
                raise ManagementError("Ambiguous directory metadata; no entries will be replaced") from None
            item = matches[0]
        else:
            raise ManagementError(f"Cannot inspect storage directory (HTTP {error.status_code}); check provider availability, token permissions, and drive access") from None
    except (httpx.HTTPError, ValueError):
        raise ManagementError("Cannot inspect storage directory; check connectivity and response format") from None
    if (not isinstance(item, dict) or item.get("id") != path
            or _object(item.get("status")).get("type") != "DIRECTORY"):
        raise ManagementError("The storage path is not a verified directory; no files will be replaced")
    if not _can_write(item):
        raise ManagementError("The storage directory does not grant write access")
    return item


def prepare_storage_directory(client: UCloudClient, path: str, *, create: bool = False) -> tuple[str, ...]:
    """Preview missing directories, or create them without replacing existing entries."""
    drive_id = path.split("/")[1] if path.startswith("/") else ""
    path = storage_directory_path(drive_id, path)
    components = path.split("/")[1:]
    if _directory(client, f"/{drive_id}") is None:
        raise ManagementError("Selected drive root could not be verified")
    missing = []
    for index in range(2, len(components) + 1):
        directory = "/" + "/".join(components[:index])
        if missing and not create:
            missing.append(directory)
            continue
        if _directory(client, directory) is not None:
            continue
        missing.append(directory)
        if not create:
            continue
        try:
            client.create_folder(directory)
        except UCloudAPIError as error:
            if error.status_code == 409:
                if _directory(client, directory) is not None:
                    continue
            elif error.status_code is not None and error.status_code < 500:
                raise ManagementError("Folder creation was rejected; check storage permissions and allocation") from None
            raise ManagementError("Folder creation outcome is unknown; rerun setup to inspect it before another write") from None
        except (httpx.HTTPError, ValueError):
            raise ManagementError("Folder creation outcome is unknown; rerun setup to inspect it before another write") from None
        if _directory(client, directory) is None:
            raise ManagementError("Created folder could not be verified; rerun setup to reconcile it")
    return tuple(missing)


def template_candidates(client: UCloudClient) -> list[dict]:
    jobs = browse_all(lambda **kwargs: client.browse_jobs(items_per_page=100, **kwargs))
    return [job for job in jobs if job.get("id") and isinstance(job.get("specification"), dict)
            and isinstance(job["specification"].get("application"), dict)
            and _object(job.get("owner")).get("project") == client.settings.project]


def validate_template(client: UCloudClient, template_job_id: str) -> None:
    job = management_call(client.retrieve_job, template_job_id, include_updates=False)
    if (not isinstance(job, dict) or job.get("id") != template_job_id
            or _object(job.get("owner")).get("project") != client.settings.project
            or not isinstance(job.get("specification"), dict)
            or not isinstance(job["specification"].get("application"), dict)):
        raise ManagementError("Template is not a reusable job in the selected project")


def write_setup_env(path: Path, values: dict[str, str], *, original: str | None) -> None:
    """Atomically update managed values, preserving unrelated settings and comments."""
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlinked environment file")
    current = path.read_text(encoding="utf-8-sig") if path.exists() else None
    if current != original:
        raise ValueError("Environment file changed during setup; rerun before saving")
    for value in values.values():
        if not isinstance(value, str) or any(ord(character) < 32 for character in value):
            raise ValueError("Environment settings must be single-line strings")
    lines = []
    remaining = dict(values)
    for line in (original or "").splitlines():
        key = line.strip().split("=", 1)[0].removeprefix("export ").strip()
        if key in values:
            if key in remaining:
                lines.append(f"{key}={json.dumps(remaining.pop(key), ensure_ascii=False)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in remaining.items())
    descriptor, temporary = tempfile.mkstemp(prefix=".ucloud-setup-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or (path.read_text(encoding="utf-8-sig") if path.exists() else None) != original:
            raise ValueError("Environment file changed during setup; rerun before saving")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
