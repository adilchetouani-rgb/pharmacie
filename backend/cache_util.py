"""Local file cache helpers for downloads and GeoJSON snapshots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from config import DATA_CACHE


def ensure_cache_dir() -> Path:
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    return DATA_CACHE


def cache_key(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
    return h


def json_cache_path(namespace: str, key: str) -> Path:
    d = ensure_cache_dir() / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def read_json_cached(path: Path) -> Any | None:
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def write_json_cached(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
