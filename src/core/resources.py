"""Resolve bundled data consistently in source and packaged builds."""
from __future__ import annotations

from pathlib import Path
import sys


def application_root() -> Path:
    """Return the source root or PyInstaller extraction directory."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[2]


def resource_path(relative_path: str | Path) -> Path:
    """Return an absolute path to a shipped read-only resource."""
    return application_root() / Path(relative_path)


DATA_DIR = resource_path("data")
ASSETS_DIR = resource_path("assets")
