"""
Population density from WorldPop (Morocco) GeoTIFF.

Primary signal: people per km² (WorldPop 1 km UN-adjusted density product for Morocco).
We window-read only the city bounding box to keep memory low.

If the raster is unavailable (network, URL change), callers should reject cells
that also lack building evidence — see pipeline scoring rules.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import box, mapping

from cities import City
from config import DATA_CACHE, WORLDPOP_MAR_PD_2020

logger = logging.getLogger(__name__)

RASTER_DIR = DATA_CACHE / "rasters"
# Alternate filenames if WorldPop updates paths
WORLDPOP_URL_CANDIDATES = [
    WORLDPOP_MAR_PD_2020,
    "https://data.worldpop.org/GIS/Population_Density/Global_2000_2020_1km/2020/MAR/mar_pd_2020_1km.tif",
]


def local_raster_path() -> Path:
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    return RASTER_DIR / "mar_population_density_2020.tif"


def ensure_population_raster(force_download: bool = False) -> Path | None:
    """
    Download Morocco population density raster if missing. Returns path or None on failure.
    """
    path = local_raster_path()
    if path.is_file() and not force_download:
        return path

    import requests

    for url in WORLDPOP_URL_CANDIDATES:
        try:
            logger.info("Downloading population raster from %s", url)
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                tmp = path.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                tmp.replace(path)
            return path
        except Exception as e:
            logger.warning("Population download failed for %s: %s", url, e)
    return None if not path.is_file() else path


def sample_raster_at_points(
    raster_path: Path,
    lons: np.ndarray,
    lats: np.ndarray,
    city: City,
) -> np.ndarray:
    """
    Sample raster values at (lon, lat). WorldPop 1 km PD uses people per square kilometre.
    """
    vals = np.zeros(len(lons), dtype=np.float64)
    coords = list(zip(lons.tolist(), lats.tolist()))
    with rasterio.open(raster_path) as src:
        for i, v in enumerate(src.sample(coords)):
            x = float(v[0])
            if np.isnan(x) or x < 0:
                vals[i] = 0.0
            else:
                vals[i] = x
    return vals


def raster_window_gdf(city: City, raster_path: Path, sample_step: int = 8):
    """
    Build a coarse set of points with population values for Leaflet heatmap (optional).
    sample_step: read every Nth pixel in window to reduce payload size.
    """
    min_lon, min_lat, max_lon, max_lat = city.bbox
    geom = mapping(box(min_lon, min_lat, max_lon, max_lat))
    with rasterio.open(raster_path) as src:
        try:
            out_image, out_transform = mask(src, [geom], crop=True, filled=False)
        except ValueError:
            return []
        arr = out_image[0]
        rows, cols = arr.shape
        features = []
        for r in range(0, rows, sample_step):
            for c in range(0, cols, sample_step):
                val = arr[r, c]
                if np.ma.is_masked(val) or val <= 0:
                    continue
                x, y = rasterio.transform.xy(out_transform, r, c, offset="center")
                features.append({"lon": float(x), "lat": float(y), "weight": float(val)})
        return features


def raster_available() -> bool:
    return local_raster_path().is_file()
