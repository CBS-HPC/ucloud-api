from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import zipfile
from typing import Any


@dataclass(frozen=True, slots=True)
class DeliveryBundleSpec:
    data_dir: Path
    docs_dir: Path | None = None
    scripts_dir: Path | None = None
    output_path: Path = Path("dist/delivery.zip")
    job_id: str | None = None
    package_name: str = "ucloud-delivery"
    variables: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    workflow_notes: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _sorted_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _add_directory(zf: zipfile.ZipFile, root: Path, prefix: str) -> list[str]:
    added: list[str] = []
    for file_path in _sorted_files(root):
        arcname = f"{prefix}/{file_path.relative_to(root).as_posix()}"
        zf.write(file_path, arcname)
        added.append(arcname)
    return added


def build_manifest(spec: DeliveryBundleSpec, *, files: Sequence[str]) -> dict[str, Any]:
    return {
        "schema": "ucloud.delivery.v1",
        "package_name": spec.package_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": spec.job_id,
        "files": list(files),
        "variables": list(spec.variables),
        "workflow_notes": list(spec.workflow_notes),
        "metadata": dict(spec.metadata),
    }


def create_delivery_bundle(spec: DeliveryBundleSpec) -> Path:
    if not spec.data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {spec.data_dir}")

    spec.output_path.parent.mkdir(parents=True, exist_ok=True)
    added_files: list[str] = []

    with zipfile.ZipFile(spec.output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        added_files.extend(_add_directory(zf, spec.data_dir, "data"))
        if spec.docs_dir and spec.docs_dir.exists():
            added_files.extend(_add_directory(zf, spec.docs_dir, "docs"))
        if spec.scripts_dir and spec.scripts_dir.exists():
            added_files.extend(_add_directory(zf, spec.scripts_dir, "scripts"))

        manifest = build_manifest(spec, files=added_files)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    return spec.output_path

