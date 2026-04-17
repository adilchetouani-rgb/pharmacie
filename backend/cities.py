"""
City registry: bounding boxes in WGS84 (min_lon, min_lat, max_lon, max_lat).
Architecture: append new entries to CITIES to add municipalities dynamically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class City:
    slug: str
    name: str
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat
    # Rough center for map default
    center: tuple[float, float]  # lat, lon


# BBoxes are conservative envelopes around urban fabric (not full provinces).
CITIES: dict[str, City] = {
    "tangier": City(
        "tangier",
        "Tangier",
        (-5.95, 35.65, -5.65, 35.88),
        (35.7673, -5.7998),
    ),
    "tetouan": City(
        "tetouan",
        "Tetouan",
        (-5.45, 35.55, -5.25, 35.62),
        (35.5889, -5.3626),
    ),
    "rabat": City(
        "rabat",
        "Rabat",
        (-6.95, 33.95, -6.75, 34.05),
        (33.9716, -6.8498),
    ),
    "casablanca": City(
        "casablanca",
        "Casablanca",
        (-7.75, 33.50, -7.50, 33.65),
        (33.5731, -7.5898),
    ),
    "meknes": City(
        "meknes",
        "Meknes",
        (-5.65, 33.85, -5.45, 33.95),
        (33.8950, -5.5547),
    ),
    "asilah": City(
        "asilah",
        "Asilah",
        (-6.05, 35.15, -5.85, 35.20),
        (35.1714, -6.0046),
    ),
    "chefchaouen": City(
        "chefchaouen",
        "Chefchaouen",
        (-5.35, 35.15, -5.15, 35.20),
        (35.1688, -5.2636),
    ),
    "martil": City(
        "martil",
        "Martil",
        (-5.35, 35.60, -5.25, 35.65),
        (35.6167, -5.2750),
    ),
}


def list_cities() -> list[dict[str, Any]]:
    return [
        {"slug": c.slug, "name": c.name, "center": {"lat": c.center[0], "lon": c.center[1]}}
        for c in CITIES.values()
    ]


def get_city(slug: str) -> City:
    key = slug.lower().strip()
    if key not in CITIES:
        raise KeyError(f"Unknown city: {slug}")
    return CITIES[key]
