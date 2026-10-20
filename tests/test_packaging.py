from pathlib import Path
import tomllib


def test_distribution_declares_both_licenses_and_includes_full_texts():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "MIT AND CC-BY-4.0"
    assert project["license-files"] == ["LICENSE", "LICENSE-DOCS"]
    assert "Permission is hereby granted, free of charge" in (root / "LICENSE").read_text(encoding="utf-8")
    documentation_license = (root / "LICENSE-DOCS").read_text(encoding="utf-8")
    assert documentation_license.startswith("Attribution 4.0 International")
    assert "Section 8 -- Interpretation." in documentation_license
