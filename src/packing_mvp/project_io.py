from __future__ import annotations

import json
from pathlib import Path

from packing_mvp.catalog import PackProject

PROJECT_SUFFIX = ".packproj"


def save_project(project: PackProject, path: Path) -> Path:
    path = _normalize_project_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(project.to_dict(), handle, ensure_ascii=False, indent=2)
    return path


def load_project(path: Path) -> PackProject:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid project payload in {path}")
    return PackProject.from_dict(payload)


def _normalize_project_path(path: Path) -> Path:
    normalized = Path(path)
    if normalized.suffix.lower() != PROJECT_SUFFIX:
        normalized = normalized.with_suffix(PROJECT_SUFFIX)
    return normalized
