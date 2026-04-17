import { useCallback, useEffect, useMemo, useState } from "react";

/** Shown immediately so the city dropdown works even before /api/cities responds. */
const FALLBACK_CITIES = [
  { slug: "tangier", name: "Tangier", center: { lat: 35.7673, lon: -5.7998 } },
  { slug: "tetouan", name: "Tetouan", center: { lat: 35.5889, lon: -5.3626 } },
  { slug: "rabat", name: "Rabat", center: { lat: 33.9716, lon: -6.8498 } },
  { slug: "casablanca", name: "Casablanca", center: { lat: 33.5731, lon: -7.5898 } },
  { slug: "meknes", name: "Meknes", center: { lat: 33.895, lon: -5.5547 } },
  { slug: "asilah", name: "Asilah", center: { lat: 35.1714, lon: -6.0046 } },
  { slug: "chefchaouen", name: "Chefchaouen", center: { lat: 35.1688, lon: -5.2636 } },
  { slug: "martil", name: "Martil", center: { lat: 35.6167, lon: -5.275 } },
];
import {
  CircleMarker,
  GeoJSON,
  LayerGroup,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
const apiUrl = (path) => `${API_BASE_URL}${path}`;

// Fix default marker icons (bundlers break asset paths)
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function tryLoadHeatPlugin() {
  return import("leaflet.heat")
    .then(() => typeof L.heatLayer === "function")
    .catch(() => false);
}

function HeatmapLayer({ points }) {
  const map = useMap();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    tryLoadHeatPlugin().then(setReady);
  }, []);

  useEffect(() => {
    if (!points?.length) return;
    if (!ready) return;
    const mx = Math.max(1, ...points.map((x) => x.weight));
    const latlngs = points.map((p) => [
      p.lat,
      p.lon,
      Math.min(1, p.weight / mx),
    ]);
    const layer = L.heatLayer(latlngs, {
      radius: 28,
      blur: 22,
      maxZoom: 16,
      max: 1,
      gradient: { 0.2: "#1e3a5f", 0.5: "#2d6a4f", 0.7: "#f4a261", 1: "#e76f51" },
    });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points, ready]);

  if (!points?.length) return null;
  if (ready && points.length) return null;

  /* Fallback: circle markers if leaflet.heat fails to load */
  return (
    <LayerGroup>
      {points.slice(0, 2000).map((p, i) => (
        <CircleMarker
          key={i}
          center={[p.lat, p.lon]}
          radius={4}
          pathOptions={{
            color: "#e76f51",
            fillColor: "#f4a261",
            fillOpacity: 0.35,
            weight: 0,
          }}
        />
      ))}
    </LayerGroup>
  );
}

function FlyToCity({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center?.length === 2) {
      map.flyTo(center, 13, { duration: 0.6 });
    }
  }, [center[0], center[1], map]);
  return null;
}

function opportunityStyle(feature) {
  const tier = feature?.properties?.color_tier || "red";
  const colors = {
    blue: { fill: "#2563eb", stroke: "#1d4ed8" },
    green: { fill: "#16a34a", stroke: "#15803d" },
    red: { fill: "#dc2626", stroke: "#b91c1c" },
  };
  const c = colors[tier] || colors.red;
  return {
    color: c.stroke,
    weight: 1,
    fillColor: c.fill,
    fillOpacity: 0.45,
  };
}

function onEachOpportunity(feature, layer) {
  const p = feature.properties || {};
  const score = Number(p.score ?? 0).toFixed(1);
  const pop = Number(p.pop_density_per_km2 ?? 0).toFixed(0);
  const dist = Number(p.dist_pharmacy_m ?? 0).toFixed(0);
  const estPop = Number(p.estimated_pop_nearby ?? 0).toFixed(0);
  const reason = p.reason || "—";
  const tier = p.color_tier || "red";
  const tierLabel =
    tier === "blue" ? "High (≥70)" : tier === "green" ? "Moderate (40–69)" : "Low (<40)";
  const pharmName = p.nearest_pharmacy_name;
  const pharmNameStr =
    pharmName != null && String(pharmName).trim() !== ""
      ? escapeHtml(String(pharmName).trim())
      : null;
  const nearestPharmLine = pharmNameStr
    ? `<strong>Nearest pharmacy:</strong> ${pharmNameStr} · ${dist} m away<br/>`
    : `<strong>Nearest pharmacy:</strong> ${dist} m <span style="opacity:.75">(name not mapped in OSM)</span><br/>`;
  layer.bindTooltip(
    `<div style="min-width:220px;font-size:13px;line-height:1.35">
      <strong>Score:</strong> ${score} / 100 <span style="opacity:.8">(${tierLabel})</span><br/>
      <strong>Pop. density (WorldPop 1 km):</strong> ${pop} people/km²<br/>
      <strong>Est. people (model × cell area):</strong> ~${estPop}<br/>
      ${nearestPharmLine}
      <strong>Buildings in cell:</strong> ${p.buildings ?? 0}<br/>
      <strong>Activity POIs:</strong> ${p.activity_pois ?? 0}<br/>
      <em style="display:block;margin-top:6px;">${reason}</em>
    </div>`,
    { sticky: true, direction: "top", opacity: 0.95, className: "ps-tooltip" }
  );
}

export default function App() {
  const [cities, setCities] = useState(FALLBACK_CITIES);
  const [citySlug, setCitySlug] = useState("tangier");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [recErr, setRecErr] = useState(null);
  const [data, setData] = useState(null);
  const [recs, setRecs] = useState([]);

  const center = useMemo(() => {
    const c = cities.find((x) => x.slug === citySlug);
    if (c?.center) return [c.center.lat, c.center.lon];
    return [35.7673, -5.7998];
  }, [cities, citySlug]);

  const loadCities = useCallback(async () => {
    try {
      const r = await fetch(apiUrl("/api/cities"));
      if (!r.ok) return;
      const j = await r.json();
      if (Array.isArray(j.cities) && j.cities.length > 0) {
        setCities(j.cities);
      }
    } catch {
      /* keep FALLBACK_CITIES */
    }
  }, []);

  const runAnalyze = useCallback(async (refresh = false) => {
    setLoading(true);
    setErr(null);
    setRecErr(null);
    const slug = encodeURIComponent(citySlug);
    const parseError = async (r, text) => {
      let msg = text || r.statusText;
      try {
        const j = JSON.parse(text);
        if (j.detail != null) {
          msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        }
      } catch {
        /* keep msg */
      }
      return msg;
    };
    try {
      /*
        Use /api/analyze then /api/recommendations (not /api/dashboard) so any backend
        build works. Second call hits server RAM cache — no second Overpass run.
        Refresh only on analyze; recommendations omits refresh so it reuses that result.
      */
      const aQ = refresh ? "?refresh=1" : "";
      const r1 = await fetch(apiUrl(`/api/analyze/${slug}${aQ}`));
      const t1 = await r1.text();
      if (!r1.ok) throw new Error(await parseError(r1, t1));

      const aj = JSON.parse(t1);
      setData({
        meta: aj.meta,
        pharmacies: aj.pharmacies,
        opportunities: aj.opportunities,
        heatmap: aj.heatmap,
      });

      const r2 = await fetch(apiUrl(`/api/recommendations/${slug}?top_n=30`));
      const t2 = await r2.text();
      if (!r2.ok) {
        setRecs([]);
        setRecErr(await parseError(r2, t2));
      } else {
        const bj = JSON.parse(t2);
        setRecs(bj.recommendations || []);
      }
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [citySlug]);

  useEffect(() => {
    loadCities();
  }, [loadCities]);

  useEffect(() => {
    runAnalyze();
  }, [runAnalyze]);

  const pharmFeatures = data?.pharmacies?.features || [];
  const oppFeatures = data?.opportunities?.features || [];
  const heatPoints = data?.heatmap || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <header
        style={{
          padding: "10px 16px",
          background: "linear-gradient(90deg,#0c1829,#1a2744)",
          borderBottom: "1px solid #2d3f5a",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700 }}>
          PharmaSpot Morocco
        </h1>
        <span style={{ opacity: 0.85, fontSize: "0.9rem" }}>
          Opportunity Finder · 300 m pharmacy rule · human-presence filters
          {loading && (
            <span style={{ display: "block", marginTop: 4, color: "#7dd3fc" }}>
              Loading OSM + scores (first run per city often 3–10 min; mirrors rotate on rate limits)…
            </span>
          )}
        </span>
        <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span>City</span>
          <select
            value={citySlug}
            onChange={(e) => setCitySlug(e.target.value)}
            style={{
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid #3d5270",
              background: "#111a28",
              color: "#e6edf3",
            }}
          >
            {cities.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => runAnalyze(true)}
          disabled={loading}
          style={{
            padding: "8px 14px",
            borderRadius: 6,
            border: "none",
            background: loading ? "#3d5270" : "#2d6a4f",
            color: "#fff",
            cursor: loading ? "wait" : "pointer",
            fontWeight: 600,
          }}
        >
          {loading ? "Analyzing…" : "Refresh analysis"}
        </button>
      </header>

      {err && (
        <div
          style={{
            padding: "8px 16px",
            background: "#3f1f24",
            color: "#fecaca",
            fontSize: "0.9rem",
          }}
        >
          <div>{err}</div>
          {/429|Too Many Requests/i.test(err) && (
            <div style={{ marginTop: 8, opacity: 0.9 }}>
              Public Overpass limits how fast apps can download map data. <strong>Wait 10–20 minutes</strong>{" "}
              before trying again. Do <strong>not</strong> spam &quot;Refresh analysis&quot; — that clears cache
              and makes throttling worse. After one successful run,{" "}
              <code style={{ fontSize: "0.85em" }}>data_cache/overpass</code> reuses data so later loads are
              light.
            </div>
          )}
        </div>
      )}

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }}>
            <FlyToCity center={center} />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <HeatmapLayer points={heatPoints} />
            <GeoJSON
              key={`opp-${citySlug}-${oppFeatures.length}`}
              data={{ type: "FeatureCollection", features: oppFeatures }}
              style={opportunityStyle}
              onEachFeature={onEachOpportunity}
            />
            <LayerGroup>
              {pharmFeatures.map((f, i) => {
                const g = f.geometry;
                if (g?.type !== "Point") return null;
                const [lon, lat] = g.coordinates;
                const pnm = f.properties?.name;
                const label =
                  pnm != null && String(pnm).trim() !== ""
                    ? String(pnm).trim()
                    : "Pharmacy (OSM)";
                return (
                  <CircleMarker
                    key={i}
                    center={[lat, lon]}
                    radius={6}
                    pathOptions={{
                      color: "#c1121f",
                      fillColor: "#ffccd5",
                      fillOpacity: 0.9,
                      weight: 2,
                    }}
                  >
                    <Tooltip direction="top" offset={[0, -4]} opacity={0.9}>
                      {label}
                    </Tooltip>
                  </CircleMarker>
                );
              })}
            </LayerGroup>
          </MapContainer>
          <div
            style={{
              position: "absolute",
              bottom: 12,
              left: 12,
              zIndex: 1000,
              background: "rgba(15,20,25,.88)",
              padding: "10px 12px",
              borderRadius: 8,
              fontSize: "12px",
              border: "1px solid #2d3f5a",
              maxWidth: 280,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 6 }}>Legend</div>
            <div>
              <span style={{ color: "#2563eb" }}>■</span> High opportunity (≥70)
            </div>
            <div>
              <span style={{ color: "#16a34a" }}>■</span> Moderate (40–69)
            </div>
            <div>
              <span style={{ color: "#dc2626" }}>■</span> Low (&lt;40)
            </div>
            <div style={{ marginTop: 6, opacity: 0.85 }}>
              Dots: existing pharmacies · Warm layer: population model
            </div>
            {data?.meta && (
              <div style={{ marginTop: 8, opacity: 0.75, lineHeight: 1.4 }}>
                Cells: {data.meta.grid_cells} · Opportunities:{" "}
                {data.meta.opportunity_cells} · Pharmacies: {data.meta.pharmacy_count}
                {!data.meta.raster_loaded && " · Raster: offline (buildings-only gate)"}
              </div>
            )}
          </div>
        </div>

        <aside
          style={{
            width: 340,
            borderLeft: "1px solid #2d3f5a",
            overflow: "auto",
            background: "#111820",
            padding: 12,
          }}
        >
          <h2 style={{ margin: "0 0 10px", fontSize: "1rem" }}>Top recommendations</h2>
          <p style={{ margin: "0 0 12px", fontSize: "0.82rem", opacity: 0.8 }}>
            Ranked mix of high, moderate, and lower opportunities. All respect ≥300 m from
            nearest mapped pharmacy and require population + buildings when raster is
            available.
          </p>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {recs.map((r, i) => (
              <li
                key={i}
                style={{
                  marginBottom: 10,
                  padding: 10,
                  background: "#1a2332",
                  borderRadius: 8,
                  borderLeft: `4px solid ${
                    r.score >= 70 ? "#2563eb" : r.score >= 40 ? "#16a34a" : "#dc2626"
                  }`,
                }}
              >
                <div style={{ fontWeight: 600 }}>
                  {r.neighborhood || "Area"}{" "}
                  <span style={{ opacity: 0.75, fontWeight: 400 }}>
                    · {r.score.toFixed(1)} pts
                  </span>
                </div>
                <div style={{ fontSize: "0.78rem", opacity: 0.85, marginTop: 4 }}>
                  {r.opportunity_category.replace(/_/g, " ")} · nearest pharmacy{" "}
                  {r.nearest_pharmacy_name ? `“${r.nearest_pharmacy_name}” · ` : ""}
                  {r.distance_nearest_pharmacy_m} m
                </div>
                <div style={{ fontSize: "0.78rem", marginTop: 6, lineHeight: 1.35 }}>
                  {r.explanation}
                </div>
              </li>
            ))}
          </ul>
          {recErr && (
            <p style={{ opacity: 0.85, color: "#fbbf24", fontSize: "0.82rem" }}>
              Recommendations request failed (map data still loaded): {recErr}
            </p>
          )}
          {!recs.length && !loading && !recErr && (
            <p style={{ opacity: 0.7 }}>No eligible cells — try refresh or another city.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
