from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json


@dataclass(frozen=True, slots=True)
class ExtractionScriptSpec:
    title: str
    objective: str
    output_folder: str = "output"
    imports: Sequence[str] = field(default_factory=lambda: ("json", "os", "pathlib"))
    variables: Sequence[Mapping[str, str]] = field(default_factory=tuple)
    notes: Sequence[str] = field(default_factory=tuple)
    body: str = "    # TODO: implement the extraction logic here\n    pass\n"


def render_extraction_script(spec: ExtractionScriptSpec) -> str:
    metadata = {
        "title": spec.title,
        "objective": spec.objective,
        "output_folder": spec.output_folder,
        "variables": list(spec.variables),
        "notes": list(spec.notes),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    imports = "\n".join(f"import {module}" for module in spec.imports)
    body = spec.body.rstrip() + "\n"

    return f'''#!/usr/bin/env python3
from __future__ import annotations

{imports}
from pathlib import Path

SCRIPT_METADATA = {json.dumps(metadata, indent=2, ensure_ascii=False)}


def main() -> None:
    output_dir = Path(SCRIPT_METADATA["output_folder"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "script_metadata.json").write_text(
        json.dumps(SCRIPT_METADATA, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
{body}


if __name__ == "__main__":
    main()
'''


def write_extraction_script(path: Path, spec: ExtractionScriptSpec) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_extraction_script(spec), encoding="utf-8")
    return path

