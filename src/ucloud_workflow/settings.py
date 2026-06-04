from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


class SettingsError(RuntimeError):
    """Raised when required UCloud settings are missing."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer, got {raw!r}") from exc


def _env_optional(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _env_path(name: str, default: str | Path) -> Path:
    raw = os.getenv(name)
    return Path(raw) if raw else Path(default)


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


@dataclass(frozen=True, slots=True)
class Settings:
    server: str
    token: str
    project: str
    template_job_id: str | None = None
    mount_path: str | None = None
    ssh_alias: str = "ucloud"
    work_folder: str = "/work"
    default_size: str = "128-vcpu"
    default_hours: int = 2
    output_dir: Path = Path("dist")
    delivery_root: Path = Path("deliveries")
    ssh_config_path: Path = Path.home() / ".ssh" / "config"

    @classmethod
    def from_env(
        cls,
        *,
        server: str | None = None,
        token: str | None = None,
        project: str | None = None,
        template_job_id: str | None = None,
        mount_path: str | None = None,
        ssh_alias: str | None = None,
        work_folder: str | None = None,
        default_size: str | None = None,
        default_hours: int | None = None,
        output_dir: Path | None = None,
        delivery_root: Path | None = None,
        ssh_config_path: Path | None = None,
    ) -> "Settings":
        _load_dotenv()
        resolved_server = server or os.getenv("UCLOUD_SERVER", "https://cloud.sdu.dk")
        resolved_token = token or os.getenv("UCLOUD_TOKEN")
        resolved_project = project or os.getenv("UCLOUD_PROJECT")

        missing = [
            name
            for name, value in (
                ("UCLOUD_TOKEN", resolved_token),
                ("UCLOUD_PROJECT", resolved_project),
            )
            if not value
        ]
        if missing:
            raise SettingsError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(
            server=resolved_server,
            token=resolved_token,
            project=resolved_project,
            template_job_id=template_job_id if template_job_id is not None else _env_optional("UCLOUD_TEMPLATE_JOB_ID"),
            mount_path=mount_path if mount_path is not None else _env_optional("UCLOUD_MOUNT_PATH"),
            ssh_alias=ssh_alias or os.getenv("UCLOUD_SSH_ALIAS", "ucloud"),
            work_folder=work_folder or os.getenv("UCLOUD_WORK_FOLDER", "/work/moody_agent"),
            default_size=default_size or os.getenv("UCLOUD_DEFAULT_SIZE", "128-vcpu"),
            default_hours=default_hours if default_hours is not None else _env_int("UCLOUD_DEFAULT_HOURS", 2),
            output_dir=output_dir or _env_path("UCLOUD_OUTPUT_DIR", "dist"),
            delivery_root=delivery_root or _env_path("UCLOUD_DELIVERY_ROOT", "deliveries"),
            ssh_config_path=ssh_config_path or Path.home() / ".ssh" / "config",
        )

    @property
    def mount_paths(self) -> list[str]:
        return [self.mount_path] if self.mount_path else []
