"""YAML config loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}, got {type(data).__name__}")
    return data


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load runtime settings.yaml."""
    return load_yaml(path or CONFIG_DIR / "settings.yaml")


def load_gestures(path: Path | None = None) -> dict[str, Any]:
    """Load gesture mapping config."""
    return load_yaml(path or CONFIG_DIR / "gestures.yaml")


def resolve_project_path(relative: str) -> Path:
    """Resolve a path relative to the project root."""
    candidate = Path(relative)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate
