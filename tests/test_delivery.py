from pathlib import Path
import json
import zipfile

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

