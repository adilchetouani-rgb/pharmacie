"""
PharmaSpot Morocco — FastAPI backend for pharmacy opportunity analysis.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `uvicorn main:app` from /backend with sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

import cities as cities_mod
from pipeline import run_analysis
from recommendations import get_recommendations, recommendations_from_opportunities_geojson

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PharmaSpot Morocco",
    description="Opportunity finder for pharmacy locations (300 m legal rule, human-presence gates).",
    version="0.1.0",
    default_response_class=ORJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pharmaspot-morocco"}


@app.get("/api/cities")
def api_cities():
    return {"cities": cities_mod.list_cities()}


@app.get("/api/dashboard/{city_slug}")
def api_dashboard(
    city_slug: str,
    refresh: int = Query(0, description="1 to bypass disk cache + in-memory cache"),
    top_n: int = Query(30, ge=5, le=200),
):
    """
    Single request: map layers + recommendations. Runs analysis once (avoids double Overpass load).
    """
    try:
        result = run_analysis(city_slug, refresh_cache=bool(refresh))
        recs = recommendations_from_opportunities_geojson(result.opportunities_geojson, top_n=top_n)
    except KeyError:
        raise HTTPException(404, f"Unknown city: {city_slug}")
    except Exception as e:
        logger.exception("Dashboard failed")
        raise HTTPException(500, str(e)) from e

    return {
        "meta": result.meta,
        "pharmacies": result.pharmacies_geojson,
        "opportunities": result.opportunities_geojson,
        "heatmap": result.heatmap_points,
        "recommendations": recs,
    }


@app.get("/api/analyze/{city_slug}")
def api_analyze(city_slug: str, refresh: int = Query(0, description="1 to bypass Overpass JSON cache")):
    try:
        result = run_analysis(city_slug, refresh_cache=bool(refresh))
    except KeyError:
        raise HTTPException(404, f"Unknown city: {city_slug}")
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(500, str(e)) from e

    return {
        "meta": result.meta,
        "pharmacies": result.pharmacies_geojson,
        "opportunities": result.opportunities_geojson,
        "heatmap": result.heatmap_points,
    }


@app.get("/api/recommendations/{city_slug}")
def api_recommendations(
    city_slug: str,
    top_n: int = Query(30, ge=5, le=200),
    refresh: int = Query(0),
):
    try:
        recs = get_recommendations(city_slug, top_n=top_n, refresh_cache=bool(refresh))
    except KeyError:
        raise HTTPException(404, f"Unknown city: {city_slug}")
    except Exception as e:
        logger.exception("Recommendations failed")
        raise HTTPException(500, str(e)) from e
    return {"city": city_slug, "count": len(recs), "recommendations": recs}
