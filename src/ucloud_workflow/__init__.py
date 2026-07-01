"""UCloud workflow toolkit."""

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import tomllib


def _source_version() -> str | None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError:
        return None
    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


_source_version_value = _source_version()
if _source_version_value is not None:
    __version__ = _source_version_value
else:
    try:
        __version__ = package_version("ucloud-workflow")
    except PackageNotFoundError:
        __version__ = "0.1.1"

from .client import UCloudAPIError, UCloudClient
from .settings import Settings, SettingsError

__all__ = [
    "__version__",
    "Settings",
    "SettingsError",
    "UCloudAPIError",
    "UCloudClient",
]
