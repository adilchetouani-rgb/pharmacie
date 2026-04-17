"""
Ranked textual recommendations for pharmacy siting (API + library use).
"""
from __future__ import annotations

import math
from typing import Any

from pipeline import run_analysis


def _centroid_lonlat_from_geojson(geom: dict[str, Any]) -> tuple[float, float] | None:
    """
    Grid cells clipped to city bbox often serialize as MultiPolygon; recommender must
    not skip them (Polygon-only logic produced empty recommendation lists).
    """
    t = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    if t == "Point" and len(coords) >= 2:
        return float(coords[0]), float(coords[1])
    if t == "Polygon":
        ring = coords[0]
        if len(ring) < 3:
            return None
        xs = [float(c[0]) for c in ring]
        ys = [float(c[1]) for c in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if t == "MultiPolygon":
        xs: list[float] = []
        ys: list[float] = []
        for poly in coords:
            for ring in poly:
                for c in ring:
                    xs.append(float(c[0]))
                    ys.append(float(c[1]))
        if not xs:
            return None
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return None


def diversify_bucket(recs: list[dict], top_n: int) -> list[dict]:
    """Prefer a mix of high / moderate / low opportunities, then fill by score."""
    high = [r for r in recs if r["score"] >= 70]
    mid = [r for r in recs if 40 <= r["score"] < 70]
    low = [r for r in recs if r["score"] < 40]
    per = max(2, top_n // 3)
    out: list[dict] = []
    out.extend(high[:per])
    out.extend(mid[:per])
    out.extend(low[:per])
    rest = sorted([r for r in recs if r not in out], key=lambda x: x["score"], reverse=True)
    for r in rest:
        if len(out) >= top_n:
            break
        out.append(r)
    seen = set()
    uniq: list[dict] = []
    for r in out:
        k = (round(r["coordinates"]["lat"], 5), round(r["coordinates"]["lon"], 5))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
        if len(uniq) >= top_n:
            break
    return uniq


def recommendations_from_opportunities_geojson(
    opp_geojson: dict[str, Any], top_n: int = 30
) -> list[dict[str, Any]]:
    """Build recommendation rows from an opportunities FeatureCollection (no Overpass)."""
    fc = opp_geojson
    features = sorted(
        fc.get("features", []),
        key=lambda f: float(f.get("properties", {}).get("score", 0)),
        reverse=True,
    )
    if not features:
        return []

    rows = []
    for f in features[: max(top_n * 3, 80)]:
        p = f.get("properties", {})
        geom = f.get("geometry") or {}
        ll = _centroid_lonlat_from_geojson(geom)
        if ll is None:
            continue
        lon, lat = ll
        score = float(p.get("score", 0))
        tier = p.get("color_tier", "red")
        if tier == "blue":
            opp_cat = "high_opportunity"
        elif tier == "green":
            opp_cat = "moderate_opportunity"
        else:
            opp_cat = "low_opportunity"

        expl = p.get("reason", "")
        if score >= 70 and "High" not in expl:
            expl = "High population + pharmacy gap. " + expl
        elif score < 40 and "Weaker" not in expl:
            expl = "Low activity despite distance. " + expl

        nb = p.get("neighborhood")
        if isinstance(nb, float) and math.isnan(nb):
            nb = None
        pn = p.get("nearest_pharmacy_name")
        if isinstance(pn, float) and math.isnan(pn):
            pn = None
        elif pn is not None:
            pn = str(pn).strip() or None
        rows.append(
            {
                "neighborhood": nb,
                "nearest_pharmacy_name": pn,
                "coordinates": {"lat": lat, "lon": lon},
                "opportunity_category": opp_cat,
                "score": round(score, 2),
                "estimated_pop_density_per_km2": round(float(p.get("pop_density_per_km2", 0)), 2),
                "buildings_in_cell": int(p.get("buildings", 0)),
                "distance_nearest_pharmacy_m": round(float(p.get("dist_pharmacy_m", 0)), 1),
                "estimated_pop_nearby": round(float(p.get("estimated_pop_nearby", 0)), 1),
                "explanation": expl.strip(),
            }
        )

    rows.sort(key=lambda r: r["score"], reverse=True)
    return diversify_bucket(rows, top_n)


def get_recommendations(city_slug: str, top_n: int = 30, refresh_cache: bool = False) -> list[dict[str, Any]]:
    """
    Return top_n opportunity cells with neighborhood labels, scores, categories,
    and human-readable explanations. Includes a spread of high / moderate / low
    ranks when possible (sorted by score descending, capped at top_n).
    """
    result = run_analysis(city_slug, refresh_cache=refresh_cache)
    return recommendations_from_opportunities_geojson(result.opportunities_geojson, top_n=top_n)
