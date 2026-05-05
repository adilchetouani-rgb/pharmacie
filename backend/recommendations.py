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


def _aggregate_by_neighborhood(recs: list[dict], top_n: int) -> list[dict]:
    """
    Return one representative row per neighborhood with count of opportunities.
    Representative is the highest-score cell in that neighborhood.
    """
    groups: dict[str, list[dict]] = {}
    for r in recs:
        nb = str(r.get("neighborhood") or "").strip()
        if not nb:
            continue
        groups.setdefault(nb, []).append(r)

    out: list[dict] = []
    for nb, items in groups.items():
        # Populated/legal opportunities are already pre-filtered upstream, but keep a guard.
        eligible = [
            x
            for x in items
            if float(x.get("estimated_pop_density_per_km2", 0)) > 0
            and int(x.get("buildings_in_cell", 0)) > 0
        ]
        if not eligible:
            continue
        best = max(eligible, key=lambda x: float(x.get("score", 0)))
        avg_score = sum(float(x.get("score", 0)) for x in eligible) / len(eligible)
        avg_pop = (
            sum(float(x.get("estimated_pop_density_per_km2", 0)) for x in eligible) / len(eligible)
        )
        # Neighborhood-level grading is softer than cell-level thresholds so the list
        # has actionable spread (good / average / bad) across all neighborhoods.
        if avg_score >= 58 and avg_pop >= 1200:
            neighborhood_rating = "good"
            opp_cat = "high_opportunity"
        elif avg_score >= 52 and avg_pop >= 300:
            neighborhood_rating = "average"
            opp_cat = "moderate_opportunity"
        else:
            neighborhood_rating = "bad"
            opp_cat = "low_opportunity"

        rep = dict(best)
        rep["neighborhood"] = nb
        rep["opportunities_in_neighborhood"] = len(eligible)
        rep["average_neighborhood_score"] = round(avg_score, 2)
        rep["average_pop_density_per_km2"] = round(avg_pop, 2)
        rep["neighborhood_rating"] = neighborhood_rating
        rep["opportunity_category"] = opp_cat
        rep["legal_opportunities_count"] = len(eligible)
        rep["explanation"] = (
            f"{len(eligible)} opportunities found in {nb}. " + str(rep.get("explanation", "")).strip()
        ).strip()
        out.append(rep)

    out.sort(
        key=lambda x: (
            float(x.get("score", 0)),
            int(x.get("opportunities_in_neighborhood", 0)),
        ),
        reverse=True,
    )
    return out[:top_n]


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
        elif nb is not None:
            nb = str(nb).strip() or None
        pn = p.get("nearest_pharmacy_name")
        if isinstance(pn, float) and math.isnan(pn):
            pn = None
        elif pn is not None:
            pn = str(pn).strip() or None

        # Always provide a displayable area label for sidebar cards.
        if not nb:
            if pn:
                nb = f"Near {pn}"
            else:
                nb = f"Zone {lat:.3f}, {lon:.3f}"

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
    return _aggregate_by_neighborhood(rows, top_n)


def get_recommendations(city_slug: str, top_n: int = 30, refresh_cache: bool = False) -> list[dict[str, Any]]:
    """
    Return top_n opportunity cells with neighborhood labels, scores, categories,
    and human-readable explanations. Includes a spread of high / moderate / low
    ranks when possible (sorted by score descending, capped at top_n).
    """
    result = run_analysis(city_slug, refresh_cache=refresh_cache)
    return recommendations_from_opportunities_geojson(result.opportunities_geojson, top_n=top_n)
