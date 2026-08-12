from pathlib import Path
import json
import zipfile

from ucloud_workflow.artifacts import ARTIFACT_MANIFEST_SCHEMA, file_sha256
from ucloud_workflow.delivery import DeliveryBundleSpec, create_delivery_bundle


def test_create_delivery_bundle_writes_manifest_and_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    scripts_dir = tmp_path / "scripts"
    data_dir.mkdir()
    docs_dir.mkdir()
    scripts_dir.mkdir()
    (data_dir / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (docs_dir / "README.md").write_text("docs", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    output = tmp_path / "delivery.zip"
    bundle = DeliveryBundleSpec(
        data_dir=data_dir,
        docs_dir=docs_dir,
        scripts_dir=scripts_dir,
        output_path=output,
        job_id="job-123",
        run_id="run-456",
        template_job_id="template-789",
        machine_product="cpu-amd-zen5-16-vcpu",
        variables=({"name": "company_id", "type": "string"},),
        workflow_notes=("Extracted from the approved source.",),
        metadata={"source_version": "2026-08"},
    )

    result = create_delivery_bundle(bundle)

    assert result == output
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "data/result.csv" in names
        assert "docs/README.md" in names
        assert "scripts/run.py" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["job_id"] == "job-123"
    assert "data/result.csv" in manifest["files"]
    assert manifest["schema"] == ARTIFACT_MANIFEST_SCHEMA
    assert manifest["provenance"]["ucloud"]["job_id"] == "job-123"
    assert manifest["provenance"]["ucloud"]["run_id"] == "run-456"
    assert manifest["provenance"]["ucloud"]["template_job_id"] == "template-789"
    assert manifest["provenance"]["ucloud"]["machine_product"] == "cpu-amd-zen5-16-vcpu"
    assert manifest["variables"] == [{"name": "company_id", "type": "string"}]
    assert manifest["provenance"]["workflow_notes"] == ["Extracted from the approved source."]
    assert manifest["provenance"]["metadata"] == {"source_version": "2026-08"}
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    data_record = artifacts["data/result.csv"]
    assert data_record["role"] == "data"
    assert data_record["size_bytes"] == (data_dir / "result.csv").stat().st_size
    assert data_record["sha256"] == file_sha256(data_dir / "result.csv")
    assert data_record["content_type"] is not None
