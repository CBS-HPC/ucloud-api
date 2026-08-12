from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import mimetypes


ARTIFACT_MANIFEST_SCHEMA = "ucloud.artifact-manifest.v1"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """A portable record of one delivered file."""

    path: str
    role: str
    size_bytes: int
    sha256: str
    content_type: str | None


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it into memory."""
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def describe_artifact(path: Path, *, archive_path: str, role: str) -> ArtifactRecord:
    """Create a manifest record for one source file."""
    return ArtifactRecord(
        path=archive_path,
        role=role,
        size_bytes=path.stat().st_size,
        sha256=file_sha256(path),
        content_type=mimetypes.guess_type(path.name)[0],
    )


def build_artifact_manifest(
    records: Sequence[ArtifactRecord],
    *,
    package_name: str,
    variables: Sequence[Mapping[str, Any]] = (),
    provenance: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the shared manifest used by delivery bundles and downstream tooling."""
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schema": ARTIFACT_MANIFEST_SCHEMA,
        "package_name": package_name,
        "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
        "artifacts": [asdict(record) for record in records],
        "variables": [dict(variable) for variable in variables],
        "provenance": dict(provenance or {}),
    }
