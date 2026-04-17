"""
Application configuration: cache paths and external service URLs.
"""
import os
from pathlib import Path

# Project root (parent of backend/)
ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE = ROOT / "data_cache"

# Public Overpass mirrors. **overpass-api.de is blocked by default** (strict 429/504 limits).
# To allow it: set PHARMASPOT_ALLOW_OVERPASS_DE=1 (not recommended).
# Custom list: PHARMASPOT_OVERPASS_URLS=https://mirror1/...,https://mirror2/...
_DEFAULT_OVERPASS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)


def _overpass_endpoints() -> tuple[str, ...]:
    raw = os.environ.get("PHARMASPOT_OVERPASS_URLS", "").strip()
    if raw:
        urls = tuple(u.strip() for u in raw.split(",") if u.strip())
    else:
        urls = _DEFAULT_OVERPASS
    allow_de = os.environ.get("PHARMASPOT_ALLOW_OVERPASS_DE", "").lower() in ("1", "true", "yes")
    if not allow_de:
        urls = tuple(u for u in urls if "overpass-api.de" not in u)
    return urls if urls else _DEFAULT_OVERPASS


OVERPASS_ENDPOINTS = _overpass_endpoints()

# Space between live Overpass calls — low values trigger 429 on public mirrors.
OVERPASS_MIN_INTERVAL_SEC = 8.0

# WorldPop Morocco population density 2020, 1 km, UN-adjusted (people per km², WGS84).
# Source: https://www.worldpop.org — CC BY 4.0; verify license for commercial use.
WORLDPOP_MAR_PD_2020 = (
    "https://data.worldpop.org/GIS/Population_Density/Global_2000_2020_1km_UNadj/2020/MAR/mar_pd_2020_1km_UNadj.tif"
)

# Minimum straight-line distance (meters) from any existing pharmacy (Moroccan regulation).
PHARMACY_MIN_SEPARATION_M = 300.0

# CRS: analysis in metric space for Morocco
PROJECTED_CRS = "EPSG:32628"  # UTM zone 28N — covers northern Morocco well
GEOGRAPHIC_CRS = "EPSG:4326"
