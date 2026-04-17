# PharmaSpot Morocco — Opportunity Finder

MVP that ranks **legal** (≥ **300 m** from any mapped pharmacy) and **human-populated** grid cells in Moroccan cities using **WorldPop** density, **OpenStreetMap** buildings, residential landuse, amenities, and distance to pharmacies.

## Architecture (brief)

1. **Backend (FastAPI)** loads city bounding boxes, pulls OSM via **Overpass** (pharmacies, buildings, residential/mixed landuse, activity POIs, major highways, neighborhood labels), downloads **WorldPop Morocco 2020 1 km** population density (people/km²) once into `data_cache/rasters/`, builds an **adaptive grid** (75 m near the urban core, 150 m outward), scores every cell, and filters out highway corridors and cells without both raster population signal and buildings (or stricter building counts if the raster is missing).
2. **Frontend (React + Vite + Leaflet)** calls `/api/analyze/{city}` and draws pharmacies, a population heat layer, and scored opportunity polygons with tooltips; the sidebar lists diversified recommendations from `/api/recommendations/{city}`.
3. **Caching**: Overpass JSON and the GeoTIFF live under `data_cache/` so reruns are fast.

## Prerequisites

- **Python 3.11+** (3.12 recommended).
- **Node.js 20+** (for the frontend).
- **Internet** on first run (Overpass + WorldPop download).

**Windows note:** `rasterio` and `geopandas` ship wheels for many setups; if `pip install` fails on GDAL/rasterio, install Conda/Mamba and run:

```text
conda create -n pharmaspot python=3.12 -y
conda activate pharmaspot
conda install -c conda-forge geopandas rasterio fastapi uvicorn scikit-learn -y
pip install requests pydantic
```

Then install any remaining packages from `backend/requirements.txt` with `pip`.

## Step-by-step setup (minimal prior knowledge)

### 1. Open a terminal in the project folder

The folder should contain `backend`, `frontend`, `data_cache`, and `scripts`.

### 2. Create a Python virtual environment (recommended)

**Windows (PowerShell):**

```powershell
cd path\to\pharmaspot-morocco
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
cd path/to/pharmaspot-morocco
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install backend dependencies

```powershell
cd backend
pip install -r requirements.txt
cd ..
```

### 4. Start the API server

Stay in the project root with the virtual environment active:

```powershell
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Leave this window open. First analysis may download a ~2–3 MB WorldPop GeoTIFF and query Overpass (can take 1–5 minutes).

### 5. Install and run the frontend (new terminal)

```powershell
cd path\to\pharmaspot-morocco\frontend
npm install
npm run dev
```

Open the URL shown (usually `http://127.0.0.1:5173`). The dev server proxies `/api` to `http://127.0.0.1:8000`.

### 6. Example without the browser (Tangier)

With the virtual environment active:

```powershell
cd path\to\pharmaspot-morocco
python scripts\run_tangier.py
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness |
| GET | `/api/cities` | Supported cities |
| GET | `/api/analyze/{city_slug}?refresh=0` | GeoJSON pharmacies + opportunities + heatmap points |
| GET | `/api/recommendations/{city_slug}?top_n=30` | Ranked recommendation objects |

`refresh=1` bypasses Overpass JSON cache (not the raster file).

## Docker (optional)

Run the stack in containers so you can **stop everything with one command** when you are not using it, and **cap CPU/RAM** so analysis does not use unlimited resources.

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose v2) running.

From the project root (`pharmaspot-morocco`):

```powershell
docker compose up --build
```

Then open **http://localhost:8080** (nginx serves the built UI and proxies `/api` to the API).

- **Stop** (free memory/CPU): `docker compose stop` or `docker compose down`
- **Data cache** (Overpass + WorldPop) is stored on your machine in `./data_cache` via a volume mount, so it survives container restarts.
- **Resource limits** are set in `docker-compose.yml` (`cpus` / `mem_limit`); increase or remove those lines if analysis is too slow or gets OOM-killed.

**Honest note:** Docker does not make the **same** analysis use less CPU or RAM than running natively — it mainly helps you **turn the stack off** easily and **bound** peak usage. Heavy grid + Overpass work is still heavy inside the container.

## Deploy backend on Oracle Cloud (Always Free ARM)

Step-by-step: [docs/DEPLOY_ORACLE.md](docs/DEPLOY_ORACLE.md). Use an **Ampere A1** VM with enough RAM; bootstrap script: `scripts/oracle-vm-bootstrap.sh`.

## Deploy backend on Google Cloud Run

HTTPS URL, pairs well with Vercel: [docs/DEPLOY_GCP.md](docs/DEPLOY_GCP.md). Build uses `cloudbuild.yaml` at repo root; the API listens on **`PORT`** (Cloud Run) or **8000** (local Docker).

## Public deployment (shareable link)

This app is best deployed as:

- **Frontend on Vercel** (React/Vite static build).
- **Backend on a Python host** (Render/Railway/Fly.io), because this API uses heavy geospatial libs (`geopandas`, `rasterio`, `shapely`) and long-running Overpass/raster work that does not fit typical Vercel serverless limits.

### 1) Deploy backend first (example: Render)

Use `backend/Dockerfile` as the service runtime and mount a persistent disk for `/app/data_cache` so Overpass and raster files survive restarts.

When backend is live, copy its URL, for example:

`https://pharmaspot-backend.onrender.com`

Test:

- `https://pharmaspot-backend.onrender.com/api/health`
- `https://pharmaspot-backend.onrender.com/api/cities`

### 2) Deploy frontend to Vercel

Create a Vercel project rooted at `frontend/` with:

- **Framework preset:** Vite
- **Build command:** `npm run build`
- **Output directory:** `dist`

Set environment variable in Vercel:

- `VITE_API_BASE_URL=https://your-backend-url.example.com`

Then deploy. Vercel will give you a public URL like:

`https://your-app-name.vercel.app`

### 3) Update CORS if you want to lock it down

Current backend CORS allows all origins (`*`) for easier setup. For production hardening, restrict it to your Vercel domain.

## Cities

Defined in `backend/cities.py` (`slug` → bbox): Tangier, Tetouan, Rabat, Casablanca, Meknes, Asilah, Chefchaouen, Martil. Add another `City(...)` entry to extend the list.

## Important limitations (MVP)

- Pharmacy locations and buildings come from **OpenStreetMap**; coverage and tagging quality vary by city.
- The **300 m** rule uses **straight-line (planar) distance** in UTM meters between cell centroid and pharmacy points, not street-network walking distance.
- **WorldPop** is a **model** (1 km resolution); it must be combined with OSM buildings as implemented — not a substitute for field verification or licensed cadastral data.
- **Regulatory, commercial, and clinical** constraints are out of scope; this tool supports **exploratory** siting only.

## License note

Respect **OpenStreetMap ODbL**, **WorldPop** (CC BY 4.0 for the cited product), and Overpass usage policies.
