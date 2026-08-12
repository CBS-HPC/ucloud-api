from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import zipfile
from typing import Any

from .artifacts import ArtifactRecord, build_artifact_manifest, describe_artifact


@dataclass(frozen=True, slots=True)
class DeliveryBundleSpec:
    data_dir: Path
    docs_dir: Path | None = None
    scripts_dir: Path | None = None
    output_path: Path = Path("dist/delivery.zip")
    job_id: str | None = None
    run_id: str | None = None
    template_job_id: str | None = None
    machine_product: str | None = None
    package_name: str = "ucloud-delivery"
    variables: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    workflow_notes: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _sorted_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _add_directory(
    zf: zipfile.ZipFile,
    root: Path,
    prefix: str,
    *,
    role: str,
) -> list[ArtifactRecord]:
    added: list[ArtifactRecord] = []
    for file_path in _sorted_files(root):
        arcname = f"{prefix}/{file_path.relative_to(root).as_posix()}"
        zf.write(file_path, arcname)
        added.append(describe_artifact(file_path, archive_path=arcname, role=role))
    return added


def build_manifest(spec: DeliveryBundleSpec, *, artifacts: Sequence[ArtifactRecord]) -> dict[str, Any]:
    provenance = {
        "ucloud": {
            "job_id": spec.job_id,
            "run_id": spec.run_id,
            "template_job_id": spec.template_job_id,
            "machine_product": spec.machine_product,
        },
        "workflow_notes": list(spec.workflow_notes),
        "metadata": dict(spec.metadata),
    }
    manifest = build_artifact_manifest(
        artifacts,
        package_name=spec.package_name,
        variables=spec.variables,
        provenance=provenance,
        generated_at=datetime.now(timezone.utc),
    )
    manifest["job_id"] = spec.job_id
    manifest["files"] = [artifact.path for artifact in artifacts]
    return manifest


def create_delivery_bundle(spec: DeliveryBundleSpec) -> Path:
    if not spec.data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {spec.data_dir}")

    spec.output_path.parent.mkdir(parents=True, exist_ok=True)
    added_artifacts: list[ArtifactRecord] = []

    with zipfile.ZipFile(spec.output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        added_artifacts.extend(_add_directory(zf, spec.data_dir, "data", role="data"))
        if spec.docs_dir and spec.docs_dir.exists():
            added_artifacts.extend(_add_directory(zf, spec.docs_dir, "docs", role="documentation"))
        if spec.scripts_dir and spec.scripts_dir.exists():
            added_artifacts.extend(_add_directory(zf, spec.scripts_dir, "scripts", role="script"))

        manifest = build_manifest(spec, artifacts=added_artifacts)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    return spec.output_path
