"""
Example: run analysis for Tangier from the command line (no browser).

Usage (from project root, after activating your Python environment):

  cd pharmaspot-morocco
  python scripts/run_tangier.py

Or from backend folder with PYTHONPATH:

  cd backend
  set PYTHONPATH=.
  python ../scripts/run_tangier.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from pipeline import run_analysis  # noqa: E402
from recommendations import get_recommendations  # noqa: E402


def main():
    print("PharmaSpot Morocco — Tangier example")
    print("Downloading/caching OSM + WorldPop on first run may take several minutes.\n")

    result = run_analysis("tangier", refresh_cache=False)
    print("Meta:", json.dumps(result.meta, indent=2))
    print(f"\nOpportunity polygons: {len(result.opportunities_geojson.get('features', []))}")
    print(f"Heatmap sample points: {len(result.heatmap_points)}")

    recs = get_recommendations("tangier", top_n=12)
    print("\nSample recommendations:")
    for i, r in enumerate(recs, 1):
        nb = r.get("neighborhood") or "—"
        print(f"  {i}. {nb} | score={r['score']} | {r['explanation'][:80]}…")


if __name__ == "__main__":
    main()
