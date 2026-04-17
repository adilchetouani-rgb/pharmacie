"""
Adaptive city grid in projected coordinates (meters).

Dense core (within `dense_radius_m` of city center): 75 m cells.
Outer area: 150 m cells.

This approximates the spec without an expensive multi-resolution global solver.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box, Point

from cities import City
from config import GEOGRAPHIC_CRS, PROJECTED_CRS

DENSE_RADIUS_M = 4500.0
CELL_DENSE_M = 75.0
CELL_SUBURBAN_M = 150.0


def _bbox_polygon_wgs84(city: City):
    min_lon, min_lat, max_lon, max_lat = city.bbox
    return box(min_lon, min_lat, max_lon, max_lat)


def build_adaptive_grid(city: City) -> gpd.GeoDataFrame:
    """
    Returns GeoDataFrame of grid cell polygons in WGS84 with projected centroids
    stored for distance math (centroid_x_m, centroid_y_m in EPSG:32628).
    """
    bbox_gdf = gpd.GeoDataFrame(geometry=[_bbox_polygon_wgs84(city)], crs=GEOGRAPHIC_CRS)
    proj = bbox_gdf.to_crs(PROJECTED_CRS)
    minx, miny, maxx, maxy = proj.total_bounds

    center_pt = gpd.GeoDataFrame(
        geometry=[Point(city.center[1], city.center[0])], crs=GEOGRAPHIC_CRS
    ).to_crs(PROJECTED_CRS)
    cx, cy = center_pt.geometry.iloc[0].x, center_pt.geometry.iloc[0].y

    polys = []
    meta_cell_m = []

    # First pass: suburban 150m grid
    x0 = np.floor(minx / CELL_SUBURBAN_M) * CELL_SUBURBAN_M
    y0 = np.floor(miny / CELL_SUBURBAN_M) * CELL_SUBURBAN_M
    xs = np.arange(x0, maxx + CELL_SUBURBAN_M, CELL_SUBURBAN_M)
    ys = np.arange(y0, maxy + CELL_SUBURBAN_M, CELL_SUBURBAN_M)

    for x in xs:
        for y in ys:
            cell = box(x, y, x + CELL_SUBURBAN_M, y + CELL_SUBURBAN_M)
            if not cell.intersects(proj.geometry.iloc[0]):
                continue
            clipped = cell.intersection(proj.geometry.iloc[0])
            if clipped.is_empty:
                continue
            c = clipped.centroid
            dist = np.hypot(c.x - cx, c.y - cy)
            if dist <= DENSE_RADIUS_M:
                # Replace with 2x2 fine grid of 75m inside this 150m slot (approximate)
                for dx in (0, CELL_DENSE_M):
                    for dy in (0, CELL_DENSE_M):
                        small = box(x + dx, y + dy, x + dx + CELL_DENSE_M, y + dy + CELL_DENSE_M)
                        if not small.intersects(proj.geometry.iloc[0]):
                            continue
                        cl = small.intersection(proj.geometry.iloc[0])
                        if cl.is_empty or cl.area < 1e-6:
                            continue
                        polys.append(cl)
                        meta_cell_m.append(CELL_DENSE_M)
            else:
                polys.append(clipped)
                meta_cell_m.append(CELL_SUBURBAN_M)

    if not polys:
        return gpd.GeoDataFrame(
            columns=["cell_m", "centroid_x_m", "centroid_y_m"], geometry=[], crs=GEOGRAPHIC_CRS
        )

    gdf_p = gpd.GeoDataFrame({"cell_m": meta_cell_m, "geometry": polys}, crs=PROJECTED_CRS)
    gdf_p["centroid_x_m"] = gdf_p.geometry.centroid.x
    gdf_p["centroid_y_m"] = gdf_p.geometry.centroid.y

    gdf_wgs = gdf_p.to_crs(GEOGRAPHIC_CRS)
    gdf_wgs["cell_id"] = range(len(gdf_wgs))
    return gdf_wgs
