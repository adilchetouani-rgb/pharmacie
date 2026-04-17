"""
End-to-end geo analysis: Overpass extracts, adaptive grid, raster sampling, scoring.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any

import geopandas as gpd
import numpy as np

from cities import City, get_city
from config import PROJECTED_CRS
from grid import build_adaptive_grid
from overpass_client import (
    fetch_activity_pois,
    fetch_buildings,
    fetch_highway_corridors,
    fetch_neighborhood_labels,
    fetch_pharmacies,
    fetch_residential_landuse,
)
from population import ensure_population_raster, raster_window_gdf, sample_raster_at_points
from scoring import (
    attach_activity_counts,
    attach_building_counts,
    attach_residential_flag,
    compute_scores,
    distance_to_nearest_m,
    finalize_eligibility,
)

logger = logging.getLogger(__name__)

# One full analysis per city is expensive (many Overpass calls). Cache in RAM so
# parallel /api/analyze + /api/recommendations do not double traffic.
_analysis_cache: dict[str, tuple[float, "AnalysisResult"]] = {}
_cache_lock = RLock()
CACHE_TTL_SEC = 45 * 60


def _cell_centroids_lonlat(grid_wgs: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    c = grid_wgs.geometry.centroid
    return np.array(c.x.values), np.array(c.y.values)


def _highway_mask(grid_wgs: gpd.GeoDataFrame, highways_wgs: gpd.GeoDataFrame) -> np.ndarray:
    """True = cell should be excluded (on/near major highway corridor)."""
    n = len(grid_wgs)
    if highways_wgs.empty:
        return np.zeros(n, dtype=bool)
    g = grid_wgs.reset_index(drop=True).to_crs(PROJECTED_CRS)
    g["_cell_ix"] = np.arange(n, dtype=np.int64)
    h = highways_wgs.to_crs(PROJECTED_CRS)
    h_buf = h.buffer(35)
    hg = gpd.GeoDataFrame(geometry=h_buf, crs=PROJECTED_CRS)
    # sjoin is one-to-many — collapse via _cell_ix; reindex to n so shapes always match grid.
    joined = gpd.sjoin(g[["geometry", "_cell_ix"]], hg[["geometry"]], how="left", predicate="intersects")
    hit = (
        joined["index_right"]
        .notna()
        .groupby(joined["_cell_ix"], sort=False)
        .any()
        .reindex(np.arange(n, dtype=np.int64), fill_value=False)
    )
    return hit.astype(bool).to_numpy()


def _nearest_place_name(grid_wgs: gpd.GeoDataFrame, places: gpd.GeoDataFrame) -> list[str | None]:
    if places.empty:
        return [None] * len(grid_wgs)
    pl = places.reset_index(drop=True)
    g = grid_wgs.to_crs(PROJECTED_CRS)
    p = pl.to_crs(PROJECTED_CRS)
    pnames = pl["name"].tolist()
    names: list[str | None] = []
    for geom in g.geometry.centroid:
        dists = p.geometry.distance(geom)
        j = int(dists.argmin())
        names.append(str(pnames[j]) if j < len(pnames) else None)
    return names


def _nearest_pharmacy_name(
    grid_wgs: gpd.GeoDataFrame, pharmacies: gpd.GeoDataFrame
) -> list[str | None]:
    """Label of the closest mapped pharmacy to each cell centroid (same metric as dist_pharmacy_m)."""
    if pharmacies.empty:
        return [None] * len(grid_wgs)
    ph = pharmacies.reset_index(drop=True)
    g = grid_wgs.to_crs(PROJECTED_CRS)
    p = ph.to_crs(PROJECTED_CRS)
    has_name = "name" in ph.columns
    names: list[str | None] = []
    for geom in g.geometry.centroid:
        dists = p.geometry.distance(geom)
        j = int(dists.argmin())
        if not has_name or j >= len(ph):
            names.append(None)
            continue
        raw = ph["name"].iloc[j]
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            names.append(None)
        else:
            s = str(raw).strip()
            names.append(s if s else None)
    return names


def _category(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def _color(score: float) -> str:
    if score >= 70:
        return "blue"
    if score >= 40:
        return "green"
    return "red"


def _explanation(
    score: float,
    pop: float,
    buildings: int,
    activity: int,
    dist_m: float,
    residential: bool,
) -> str:
    parts = []
    if dist_m >= 500:
        parts.append("pharmacy gap")
    elif dist_m >= 300:
        parts.append("legal distance from nearest pharmacy")
    if pop > 3000 and buildings >= 2:
        parts.append("high population footprint (model)")
    elif buildings >= 3:
        parts.append("dense building fabric")
    elif pop > 500:
        parts.append("moderate modeled population")
    if activity >= 3:
        parts.append("strong amenity activity")
    elif activity == 0:
        parts.append("low POI activity")
    if residential:
        parts.append("near residential landuse")
    if score >= 70:
        return "High opportunity: " + ", ".join(parts[:4]) if parts else "Strong composite signal."
    if score >= 40:
        return "Moderate opportunity: " + ", ".join(parts[:3]) if parts else "Balanced trade-offs."
    return "Weaker opportunity: " + ", ".join(parts[:3]) if parts else "Lower composite rank."


@dataclass
class AnalysisResult:
    city: City
    pharmacies_geojson: dict
    opportunities_geojson: dict
    heatmap_points: list[dict]
    meta: dict[str, Any]


def _run_analysis_impl(city_slug: str, refresh_cache: bool = False) -> AnalysisResult:
    city = get_city(city_slug)
    logger.info("Loading OSM data for %s", city.name)

    pharmacies = fetch_pharmacies(city, use_cache=not refresh_cache)
    buildings = fetch_buildings(city, use_cache=not refresh_cache)
    residential = fetch_residential_landuse(city, use_cache=not refresh_cache)
    activity = fetch_activity_pois(city, use_cache=not refresh_cache)
    places = fetch_neighborhood_labels(city, use_cache=not refresh_cache)
    highways = fetch_highway_corridors(city, use_cache=not refresh_cache)

    raster_path = ensure_population_raster(force_download=False)
    raster_loaded = raster_path is not None and raster_path.is_file()

    grid = build_adaptive_grid(city)
    if grid.empty:
        raise RuntimeError("Empty grid — check city bbox.")

    lons, lats = _cell_centroids_lonlat(grid)
    if raster_loaded:
        pop = sample_raster_at_points(raster_path, lons, lats, city)
    else:
        pop = np.zeros(len(grid))
        logger.warning("Population raster unavailable — using building-only human gate.")

    bcnt = attach_building_counts(grid, buildings)
    res_hit = attach_residential_flag(grid, residential)
    act_cnt = attach_activity_counts(grid, activity)

    g_proj = grid.to_crs(PROJECTED_CRS)
    cx = g_proj.geometry.centroid.x.values
    cy = g_proj.geometry.centroid.y.values
    cell_xy = np.column_stack([cx, cy])

    if pharmacies.empty:
        pharm_xy = np.zeros((0, 2))
    else:
        p_proj = pharmacies.to_crs(PROJECTED_CRS)
        pharm_xy = np.column_stack([p_proj.geometry.x.values, p_proj.geometry.y.values])

    dist_m = distance_to_nearest_m(cell_xy, pharm_xy)

    pop_01, act_01, dist_01, score_100, legal = compute_scores(
        pop, bcnt, res_hit, act_cnt, dist_m
    )
    eligible = finalize_eligibility(legal, pop, bcnt, raster_loaded)
    hw_excl = _highway_mask(grid, highways)
    eligible = eligible & (~hw_excl)

    place_names = _nearest_place_name(grid, places)
    nearest_pharmacy_labels = _nearest_pharmacy_name(grid, pharmacies)

    grid = grid.reset_index(drop=True)
    grid["pop_density_per_km2"] = pop
    # Rough people-in-cell estimate: density (people/km²) × cell footprint (km²)
    cell_km2 = (grid["cell_m"].astype(np.float64) ** 2) / 1_000_000.0
    grid["estimated_pop_nearby"] = np.clip(pop * cell_km2, 0, None)
    grid["buildings"] = bcnt
    grid["activity_pois"] = act_cnt
    grid["dist_pharmacy_m"] = dist_m
    grid["nearest_pharmacy_name"] = nearest_pharmacy_labels
    grid["score"] = score_100
    grid["pop_score"] = pop_01 * 100
    grid["activity_score"] = act_01 * 100
    grid["distance_score"] = dist_01 * 100
    grid["eligible"] = eligible
    grid["neighborhood"] = place_names
    grid["category"] = [_category(float(s)) for s in score_100]
    grid["color_tier"] = [_color(float(s)) for s in score_100]
    grid["reason"] = [
        _explanation(
            float(score_100[i]),
            float(pop[i]),
            int(bcnt[i]),
            int(act_cnt[i]),
            float(dist_m[i]),
            bool(res_hit[i]),
        )
        for i in range(len(grid))
    ]

    opp = grid[grid["eligible"]].copy()
    # Keep many zones: sort by score, do not truncate here (frontend can simplify if needed)
    opp = opp.sort_values("score", ascending=False)

    pharm_features = pharmacies.to_crs("EPSG:4326")
    opportunities = opp.to_crs("EPSG:4326")

    heatmap_points: list[dict] = []
    if raster_loaded:
        try:
            heatmap_points = raster_window_gdf(city, raster_path, sample_step=10)
        except Exception as e:
            logger.warning("Heatmap sampling failed: %s", e)

    meta = {
        "city": city.name,
        "slug": city.slug,
        "raster_loaded": raster_loaded,
        "pharmacy_count": len(pharmacies),
        "grid_cells": len(grid),
        "opportunity_cells": len(opp),
        "min_pharmacy_separation_m": 300,
    }

    pharm_fc = (
        json.loads(pharm_features.to_json())
        if not pharm_features.empty
        else {"type": "FeatureCollection", "features": []}
    )
    opp_fc = (
        json.loads(opportunities.to_json())
        if not opportunities.empty
        else {"type": "FeatureCollection", "features": []}
    )

    return AnalysisResult(
        city=city,
        pharmacies_geojson=pharm_fc,
        opportunities_geojson=opp_fc,
        heatmap_points=heatmap_points,
        meta=meta,
    )


def run_analysis(city_slug: str, refresh_cache: bool = False) -> AnalysisResult:
    key = city_slug.lower().strip()
    if not refresh_cache:
        with _cache_lock:
            hit = _analysis_cache.get(key)
            if hit is not None:
                ts, res = hit
                if time.time() - ts < CACHE_TTL_SEC:
                    logger.info("Serving cached analysis for %s", key)
                    return res
    result = _run_analysis_impl(key, refresh_cache=refresh_cache)
    with _cache_lock:
        _analysis_cache[key] = (time.time(), result)
    return result
