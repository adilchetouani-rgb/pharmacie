"""
Opportunity scoring: legal distance, population presence, activity proxies.

Composite score (weighted sum, 0–100) as required:
  0.5 * population_score + 0.3 * activity_score + 0.2 * distance_score

Each sub-score is normalized to [0, 1] within the city before blending, then
the blend is scaled to [0, 100].

Legal rule: only cells with distance to nearest pharmacy >= PHARMACY_MIN_SEPARATION_M
are eligible as *recommendations*; we still score others low for map context if desired,
or exclude from GeoJSON — we exclude ineligible from opportunity layers but can show dimmed.
For MVP we only emit polygons for legal + human-presence cells.
"""
from __future__ import annotations

import numpy as np
import geopandas as gpd
from sklearn.neighbors import BallTree

from config import PHARMACY_MIN_SEPARATION_M, PROJECTED_CRS


def _minmax01(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x
    lo, hi = np.nanmin(x), np.nanmax(x)
    if hi <= lo:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def distance_to_nearest_m(
    cell_xy: np.ndarray,  # shape (N, 2) in projected meters
    pharm_xy: np.ndarray,  # shape (M, 2)
) -> np.ndarray:
    if pharm_xy.shape[0] == 0:
        # No pharmacies in extract: entire city is "far" — cap score conservatively
        return np.full(cell_xy.shape[0], 10_000.0)
    tree = BallTree(pharm_xy, metric="euclidean")
    dist, _ = tree.query(cell_xy, k=1)
    return dist.ravel()


def distance_subscore(dist_m: np.ndarray) -> np.ndarray:
    """
    Higher when farther from competition, but only meaningful past legal minimum.
    Maps [300, 300+d] to rising score where d scales with urban context.
    """
    d0 = PHARMACY_MIN_SEPARATION_M
    d1 = d0 + 1200.0  # ~1.2 km beyond minimum approaches plateau
    s = (dist_m - d0) / (d1 - d0)
    s = np.clip(s, 0.0, 1.0)
    # If under 300m, zero contribution (illegal for new pharmacy)
    s = np.where(dist_m >= d0, s, 0.0)
    return s


def attach_building_counts(
    grid_wgs: gpd.GeoDataFrame,
    buildings_wgs: gpd.GeoDataFrame,
) -> np.ndarray:
    n = len(grid_wgs)
    if buildings_wgs.empty:
        return np.zeros(n, dtype=np.int32)
    g = grid_wgs.reset_index(drop=True).to_crs(PROJECTED_CRS)
    g["_cell_ix"] = np.arange(n, dtype=np.int64)
    b = buildings_wgs.to_crs(PROJECTED_CRS)
    joined = gpd.sjoin(g[["geometry", "_cell_ix"]], b[["geometry"]], how="left", predicate="intersects")
    # sjoin can duplicate rows; index alignment is fragile — always collapse to RangeIndex(n).
    counts = (
        joined.groupby("_cell_ix", sort=False)
        .size()
        .reindex(np.arange(n, dtype=np.int64), fill_value=0)
        .to_numpy(dtype=np.int32)
    )
    return counts


def attach_residential_flag(
    grid_wgs: gpd.GeoDataFrame,
    residential_wgs: gpd.GeoDataFrame,
) -> np.ndarray:
    n = len(grid_wgs)
    if residential_wgs.empty:
        return np.zeros(n, dtype=np.int8)
    g = grid_wgs.reset_index(drop=True).to_crs(PROJECTED_CRS)
    g["_cell_ix"] = np.arange(n, dtype=np.int64)
    r = residential_wgs.to_crs(PROJECTED_CRS)
    buf = r.buffer(40)  # small buffer so centroid-near residential counts
    r_gdf = gpd.GeoDataFrame(geometry=buf, crs=PROJECTED_CRS)
    joined = gpd.sjoin(g[["geometry", "_cell_ix"]], r_gdf[["geometry"]], how="left", predicate="intersects")
    hit = (
        joined["index_right"]
        .notna()
        .groupby(joined["_cell_ix"], sort=False)
        .any()
        .reindex(np.arange(n, dtype=np.int64), fill_value=False)
    )
    return hit.astype(np.int8).to_numpy()


def attach_activity_counts(
    grid_wgs: gpd.GeoDataFrame,
    pois_wgs: gpd.GeoDataFrame,
) -> np.ndarray:
    n = len(grid_wgs)
    if pois_wgs.empty:
        return np.zeros(n, dtype=np.int32)
    g = grid_wgs.reset_index(drop=True).to_crs(PROJECTED_CRS)
    g["_cell_ix"] = np.arange(n, dtype=np.int64)
    p = pois_wgs.to_crs(PROJECTED_CRS)
    # Count POIs within buffered cell (activity bleeds across street blocks)
    g_buf = g[["geometry", "_cell_ix"]].copy()
    g_buf["geometry"] = g_buf.buffer(50)
    joined = gpd.sjoin(g_buf, p[["geometry"]], how="left", predicate="intersects")
    counts = (
        joined.groupby("_cell_ix", sort=False)
        .size()
        .reindex(np.arange(n, dtype=np.int64), fill_value=0)
        .to_numpy(dtype=np.int32)
    )
    return counts


def compute_scores(
    pop_density: np.ndarray,  # people / km² at centroid (WorldPop) or 0
    building_counts: np.ndarray,
    residential_hit: np.ndarray,
    activity_counts: np.ndarray,
    dist_pharmacy_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
      population_score_01, activity_score_01, distance_score_01,
      final_0_100, legal (distance >= min separation)
    """
    # Population composite: log1p(pop) + building signal + residential boost
    pop_raw = np.log1p(np.maximum(pop_density, 0.0))
    bld_raw = np.log1p(building_counts.astype(np.float64))
    res_boost = residential_hit.astype(np.float64) * 0.35
    pop_composite = pop_raw + 0.6 * bld_raw + res_boost

    act_raw = np.log1p(activity_counts.astype(np.float64))

    pop_01 = _minmax01(pop_composite)
    act_01 = _minmax01(act_raw)
    dist_01 = distance_subscore(dist_pharmacy_m)

    # Weighted sum → 0–100
    blend = 0.5 * pop_01 + 0.3 * act_01 + 0.2 * dist_01
    score_100 = 100.0 * blend

    legal = dist_pharmacy_m >= PHARMACY_MIN_SEPARATION_M

    return pop_01, act_01, dist_01, score_100, legal


def finalize_eligibility(
    legal: np.ndarray,
    pop_density: np.ndarray,
    building_counts: np.ndarray,
    raster_loaded: bool,
) -> np.ndarray:
    """
    Human-presence gate (reject if population or buildings missing):
    - With raster: require pop raster signal AND at least one building in cell.
    - Without raster: require several buildings (avoids empty land / forest).
    """
    has_buildings = building_counts >= 1
    if raster_loaded:
        # WorldPop 1 km density is people/km²; ~50+ excludes near-empty raster cells
        has_pop = pop_density > 50
        human = has_pop & has_buildings
    else:
        human = building_counts >= 3

    return legal & human
