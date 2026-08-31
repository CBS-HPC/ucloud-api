from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from .catalog import resolve_template_job_id


SSH_IDENTITY_FILE_NAMES = (
    "id_rsa",
    "id_ecdsa",
    "id_ecdsa_sk",
    "id_ed25519",
    "id_ed25519_sk",
    "id_xmss",
    "id_dsa",
)


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


def _env_optional_path(name: str) -> Path | None:
    raw = _env_optional(name)
    return Path(raw) if raw is not None else None


def discover_ssh_identity_files(config_path: Path) -> tuple[Path, ...]:
    """Return standard private keys located beside the selected SSH config file."""
    return tuple(
        candidate
        for name in SSH_IDENTITY_FILE_NAMES
        if (candidate := config_path.parent / name).is_file()
    )


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
    ssh_alias: str = "ucloud"
    work_folder: str = "/work"
    default_size: str = "128-vcpu"
    default_hours: int = 2
    output_dir: Path = Path("dist")
    delivery_root: Path = Path("deliveries")
    ssh_config_path: Path = Path.home() / ".ssh" / "config"
    ssh_identity_file: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        server: str | None = None,
        token: str | None = None,
        project: str | None = None,
        template_job_id: str | None = None,
        ssh_alias: str | None = None,
        work_folder: str | None = None,
        default_size: str | None = None,
        default_hours: int | None = None,
        output_dir: Path | None = None,
        delivery_root: Path | None = None,
        ssh_config_path: Path | None = None,
        ssh_identity_file: Path | None = None,
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
            ssh_alias=ssh_alias or os.getenv("UCLOUD_SSH_ALIAS", "ucloud"),
            work_folder=work_folder or os.getenv("UCLOUD_WORK_FOLDER", "/work/moody_agent"),
            default_size=default_size or os.getenv("UCLOUD_DEFAULT_SIZE", "128-vcpu"),
            default_hours=default_hours if default_hours is not None else _env_int("UCLOUD_DEFAULT_HOURS", 2),
            output_dir=output_dir or _env_path("UCLOUD_OUTPUT_DIR", "dist"),
            delivery_root=delivery_root or _env_path("UCLOUD_DELIVERY_ROOT", "deliveries"),
            ssh_config_path=ssh_config_path or _env_path(
                "UCLOUD_SSH_CONFIG_PATH", Path.home() / ".ssh" / "config"
            ),
            ssh_identity_file=ssh_identity_file or _env_optional_path(
                "UCLOUD_SSH_IDENTITY_FILE"
            ),
        )

    def template_job_id_for(self, profile_name: str | None = None) -> str | None:
        return resolve_template_job_id(profile_name, self.template_job_id)

    def resolved_ssh_identity_files(self) -> tuple[Path, ...]:
        """Return the configured key or standard keys beside ``ssh_config_path``."""
        if self.ssh_identity_file is not None:
            return (self.ssh_identity_file,)
        return discover_ssh_identity_files(self.ssh_config_path)
