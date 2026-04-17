"""
Overpass API client: pharmacies, buildings, residential landuse, activity POIs.
Responses are cached under data_cache/overpass/. Uses multiple public mirrors and
throttling to reduce 429 Too Many Requests from any single endpoint.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Point, box

from cache_util import cache_key, json_cache_path, read_json_cached, write_json_cached
from cities import City
from config import OVERPASS_ENDPOINTS, OVERPASS_MIN_INTERVAL_SEC

logger = logging.getLogger(__name__)

_overpass_lock = threading.Lock()
_last_overpass_mono: float = 0.0
_rr_lock = threading.Lock()
_rr_counter = 0


def _throttle_overpass() -> None:
    """Space out live requests so we do not hammer one Overpass instance."""
    global _last_overpass_mono
    with _overpass_lock:
        now = time.monotonic()
        gap = now - _last_overpass_mono
        wait = OVERPASS_MIN_INTERVAL_SEC - gap
        if wait > 0:
            time.sleep(wait)
        _last_overpass_mono = time.monotonic()


def _bbox_tuple(city: City) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = city.bbox
    return (min_lat, min_lon, max_lat, max_lon)  # Overpass uses S,W,N,E


def _run_overpass(query: str, cache_path, max_rounds: int = 8) -> dict[str, Any]:
    global _rr_counter
    cached = read_json_cached(cache_path)
    if cached is not None:
        return cached

    last_err: Exception | None = None
    headers = {
        "User-Agent": "PharmaSpotMorocco/1.1 (educational; contact local admin)",
        "Accept": "application/json",
    }

    order = list(OVERPASS_ENDPOINTS)
    if not order:
        order = ["https://overpass.kumi.systems/api/interpreter"]
    n_m = len(order)
    with _rr_lock:
        shift = _rr_counter % n_m
        _rr_counter += 1

    for round_i in range(max_rounds):
        off = (shift + round_i) % n_m
        endpoints = order[off:] + order[:off]
        for url in endpoints:
            try:
                _throttle_overpass()
                # (connect, read) — large building extracts need a long read timeout
                r = requests.post(
                    url,
                    data={"data": query},
                    timeout=(30, 720),
                    headers=headers,
                )
                sc = r.status_code

                # Never use raise_for_status() here — it turns 429 into HTTPError and hides Retry-After.
                if sc == 429:
                    ra = r.headers.get("Retry-After", "")
                    try:
                        wait_extra = min(120, max(25, int(ra.strip())))
                    except ValueError:
                        wait_extra = 45
                    logger.warning(
                        "Overpass 429 from %s — cooling down %ss then next mirror", url, wait_extra
                    )
                    last_err = RuntimeError(f"429 Too Many Requests from {url}")
                    time.sleep(wait_extra)
                    continue

                if sc in (502, 503, 504):
                    logger.warning("Overpass %s from %s", sc, url)
                    last_err = RuntimeError(f"{sc} from {url}")
                    time.sleep(15)
                    continue

                if sc != 200:
                    logger.warning("Overpass HTTP %s from %s", sc, url)
                    last_err = RuntimeError(f"HTTP {sc} from {url}: {r.text[:300]!r}")
                    time.sleep(8)
                    continue

                try:
                    data = r.json()
                except Exception as je:
                    last_err = je
                    logger.warning("Overpass invalid JSON from %s: %s", url, je)
                    time.sleep(5)
                    continue

                write_json_cached(cache_path, data)
                return data
            except requests.RequestException as e:
                last_err = e
                logger.warning("Overpass request failed (%s): %s", url, e)
                time.sleep(10)
        # All mirrors failed this round — back off before retrying the set
        pause = 35 + round_i * 40
        logger.info("Overpass round %s exhausted; sleeping %ss", round_i + 1, pause)
        time.sleep(pause)

    raise RuntimeError(f"Overpass failed after retries: {last_err}")


def _elements_to_gdf(elements: list[dict], city: City) -> gpd.GeoDataFrame:
    """Convert Overpass JSON elements with lat/lon or geometry to GeoDataFrame in WGS84."""
    rows = []
    for el in elements:
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            rows.append({"id": el.get("id"), "geometry": Point(el["lon"], el["lat"])})
        elif el.get("type") == "way" and "center" in el:
            c = el["center"]
            rows.append({"id": el.get("id"), "geometry": Point(c["lon"], c["lat"])})
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    min_lon, min_lat, max_lon, max_lat = city.bbox
    b = box(min_lon, min_lat, max_lon, max_lat)
    gdf = gdf[gdf.intersects(b)]
    return gdf


def _pharmacy_elements_to_gdf(elements: list[Any], city: City) -> gpd.GeoDataFrame:
    """Pharmacy nodes/ways/relations with optional OSM name (or brand/operator fallback)."""
    rows = []
    for el in elements:
        tags = el.get("tags") or {}
        label = tags.get("name")
        if not label:
            label = tags.get("brand") or tags.get("operator")
        if label is not None:
            label = str(label).strip() or None
        pt = None
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            pt = Point(el["lon"], el["lat"])
        elif el.get("type") in ("way", "relation") and "center" in el:
            c = el["center"]
            pt = Point(c["lon"], c["lat"])
        if pt is None:
            continue
        rows.append({"id": el.get("id"), "name": label, "geometry": pt})
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    min_lon, min_lat, max_lon, max_lat = city.bbox
    b = box(min_lon, min_lat, max_lon, max_lat)
    gdf = gdf[gdf.intersects(b)]
    return gdf


def fetch_pharmacies(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    s, w, n, e = _bbox_tuple(city)
    key = cache_key("pharmacy", city.slug, f"{s},{w},{n},{e}")
    path = json_cache_path("overpass", key)
    if not use_cache and path.exists():
        path.unlink()

    query = f"""
    [out:json][timeout:180];
    (
      node["amenity"="pharmacy"]({s},{w},{n},{e});
      way["amenity"="pharmacy"]({s},{w},{n},{e});
      relation["amenity"="pharmacy"]({s},{w},{n},{e});
    );
    out center;
    """
    data = _run_overpass(query, path)
    gdf = _pharmacy_elements_to_gdf(data.get("elements", []), city)
    gdf["kind"] = "pharmacy"
    return gdf


def _city_bbox_area_deg2(city: City) -> float:
    min_lon, min_lat, max_lon, max_lat = city.bbox
    return (max_lon - min_lon) * (max_lat - min_lat)


def _bbox_grid_tiles(city: City, n_div: int) -> list[tuple[float, float, float, float]]:
    """Return (min_lon, min_lat, max_lon, max_lat) tiles in an n_div × n_div grid."""
    min_lon, min_lat, max_lon, max_lat = city.bbox
    tiles = []
    for ii in range(n_div):
        for jj in range(n_div):
            lo = min_lon + ii * (max_lon - min_lon) / n_div
            hi = lo + (max_lon - min_lon) / n_div
            la = min_lat + jj * (max_lat - min_lat) / n_div
            ha = la + (max_lat - min_lat) / n_div
            tiles.append((lo, la, hi, ha))
    return tiles


def _unlink_pattern_tiles(prefix: str, city_slug: str, n_div: int) -> None:
    for ti in range(n_div * n_div):
        tp = json_cache_path("overpass", cache_key(prefix, city_slug, str(n_div), str(ti)))
        if tp.exists():
            tp.unlink()


def fetch_buildings(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    """Building way centroids — tiled (3×3 if bbox is large) to avoid gateway timeouts."""
    min_lon, min_lat, max_lon, max_lat = city.bbox
    legacy_key = cache_key("buildings", city.slug, f"{min_lat},{min_lon},{max_lat},{max_lon}")
    legacy_path = json_cache_path("overpass", legacy_key)

    n_div = 3 if _city_bbox_area_deg2(city) > 0.016 else 2
    tiles = _bbox_grid_tiles(city, n_div)

    if not use_cache:
        if legacy_path.exists():
            legacy_path.unlink()
        _unlink_pattern_tiles("bld_tile", city.slug, 2)
        _unlink_pattern_tiles("bld_tile", city.slug, 3)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for ti, (lo, la, hi, ha) in enumerate(tiles):
        s, w, n, e = la, lo, ha, hi  # Overpass S,W,N,E
        path = json_cache_path("overpass", cache_key("bld_tile", city.slug, str(n_div), str(ti)))
        query = f"""
        [out:json][timeout:120];
        (
          way["building"]({s},{w},{n},{e});
        );
        out center;
        """
        data = _run_overpass(query, path)
        for el in data.get("elements", []):
            uid = (el.get("type"), el.get("id"))
            if uid in seen:
                continue
            seen.add(uid)
            merged.append(el)

    gdf = _elements_to_gdf(merged, city)
    gdf["kind"] = "building"
    return gdf


def fetch_residential_landuse(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    """Residential / mixed landuse ways — 2×2 tiles (ways are heavy in cities)."""
    s0, w0, n0, e0 = _bbox_tuple(city)
    legacy = json_cache_path("overpass", cache_key("residential", city.slug, f"{s0},{w0},{n0},{e0}"))
    n_div = 2
    if not use_cache:
        if legacy.exists():
            legacy.unlink()
        _unlink_pattern_tiles("res_tile", city.slug, n_div)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for ti, (lo, la, hi, ha) in enumerate(_bbox_grid_tiles(city, n_div)):
        s, w, n, e = la, lo, ha, hi
        path = json_cache_path("overpass", cache_key("res_tile", city.slug, str(n_div), str(ti)))
        query = f"""
        [out:json][timeout:90];
        (
          way["landuse"="residential"]({s},{w},{n},{e});
          way["landuse"="mixed"]({s},{w},{n},{e});
        );
        out center;
        """
        data = _run_overpass(query, path)
        for el in data.get("elements", []):
            uid = (el.get("type"), el.get("id"))
            if uid in seen:
                continue
            seen.add(uid)
            merged.append(el)

    gdf = _elements_to_gdf(merged, city)
    gdf["kind"] = "residential_proxy"
    return gdf


def fetch_activity_pois(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    """
    Schools, markets/shops, mosques/places of worship, public transport stops.
    Tiled 2×2 — dense bus_stop coverage can timeout a single bbox query.
    """
    s0, w0, n0, e0 = _bbox_tuple(city)
    legacy = json_cache_path("overpass", cache_key("activity", city.slug, f"{s0},{w0},{n0},{e0}"))
    n_div = 2
    if not use_cache:
        if legacy.exists():
            legacy.unlink()
        _unlink_pattern_tiles("act_tile", city.slug, n_div)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for ti, (lo, la, hi, ha) in enumerate(_bbox_grid_tiles(city, n_div)):
        s, w, n, e = la, lo, ha, hi
        path = json_cache_path("overpass", cache_key("act_tile", city.slug, str(n_div), str(ti)))
        query = f"""
        [out:json][timeout:120];
        (
          node["amenity"="school"]({s},{w},{n},{e});
          node["amenity"="marketplace"]({s},{w},{n},{e});
          node["shop"="supermarket"]({s},{w},{n},{e});
          node["amenity"="place_of_worship"]({s},{w},{n},{e});
          node["public_transport"="stop_position"]({s},{w},{n},{e});
          node["highway"="bus_stop"]({s},{w},{n},{e});
        );
        out;
        """
        data = _run_overpass(query, path)
        for el in data.get("elements", []):
            uid = (el.get("type"), el.get("id"))
            if uid in seen:
                continue
            seen.add(uid)
            merged.append(el)

    gdf = _elements_to_gdf(merged, city)
    gdf["kind"] = "activity_poi"
    return gdf


def fetch_highway_corridors(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    """
    Motorway / trunk / primary way centroids — 2×2 tiles to limit server work per request.
    """
    s0, w0, n0, e0 = _bbox_tuple(city)
    legacy = json_cache_path("overpass", cache_key("highways", city.slug, f"{s0},{w0},{n0},{e0}"))
    n_div = 2
    if not use_cache:
        if legacy.exists():
            legacy.unlink()
        _unlink_pattern_tiles("hw_tile", city.slug, n_div)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for ti, (lo, la, hi, ha) in enumerate(_bbox_grid_tiles(city, n_div)):
        s, w, n, e = la, lo, ha, hi
        path = json_cache_path("overpass", cache_key("hw_tile", city.slug, str(n_div), str(ti)))
        query = f"""
        [out:json][timeout:90];
        (
          way["highway"="motorway"]({s},{w},{n},{e});
          way["highway"="trunk"]({s},{w},{n},{e});
          way["highway"="primary"]({s},{w},{n},{e});
        );
        out center;
        """
        data = _run_overpass(query, path)
        for el in data.get("elements", []):
            uid = (el.get("type"), el.get("id"))
            if uid in seen:
                continue
            seen.add(uid)
            merged.append(el)

    gdf = _elements_to_gdf(merged, city)
    gdf["kind"] = "highway"
    return gdf


def fetch_neighborhood_labels(city: City, use_cache: bool = True) -> gpd.GeoDataFrame:
    """Named place areas for labeling recommendations (nodes + way centroids)."""
    s, w, n, e = _bbox_tuple(city)
    key = cache_key("places_v2", city.slug, f"{s},{w},{n},{e}")
    path = json_cache_path("overpass", key)
    if not use_cache and path.exists():
        path.unlink()

    query = f"""
    [out:json][timeout:120];
    (
      node["place"="suburb"]({s},{w},{n},{e});
      node["place"="quarter"]({s},{w},{n},{e});
      node["place"="neighbourhood"]({s},{w},{n},{e});
      node["place"="district"]({s},{w},{n},{e});
      node["place"="city_district"]({s},{w},{n},{e});
      node["place"="borough"]({s},{w},{n},{e});
      way["place"="suburb"]({s},{w},{n},{e});
      way["place"="quarter"]({s},{w},{n},{e});
      way["place"="neighbourhood"]({s},{w},{n},{e});
      way["place"="district"]({s},{w},{n},{e});
      way["place"="city_district"]({s},{w},{n},{e});
    );
    out center;
    """
    data = _run_overpass(query, path)
    rows = []
    for el in data.get("elements", []):
        name = el.get("tags", {}).get("name")
        if not name:
            continue
        typ = el.get("type")
        if typ == "node" and "lat" in el:
            rows.append({"name": name, "geometry": Point(el["lon"], el["lat"])})
        elif typ == "way" and "center" in el:
            c = el["center"]
            rows.append({"name": name, "geometry": Point(c["lon"], c["lat"])})
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")
