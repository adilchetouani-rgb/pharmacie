# Deploy backend on Google Cloud Run

This guide runs your **Docker** API on **Cloud Run** (HTTPS URL, good match for Vercel).

**Billing:** Google Cloud usually asks for a **payment method** even when you stay inside the **free tier**. You can set **budget alerts** in the console so you get notified if usage grows.

**Where you work:** mostly **Google Cloud Console** (browser) + **your PC terminal** with `gcloud` installed.

---

## 1) Create a project (browser)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Top bar → **Select a project** → **New project** → name it (e.g. `pharmaspot`) → **Create**.
3. Note the **Project ID** (not only the display name).

---

## 2) Enable APIs (browser)

Menu → **APIs & Services** → **Enable APIs and services**, and enable:

- **Cloud Run API**
- **Cloud Build API**
- **Artifact Registry API** (optional if you use GCR; Cloud Build may prompt you)

Or in **Cloud Shell** (see below), run:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com artifactregistry.googleapis.com
```

(`containerregistry.googleapis.com` is needed to push to `gcr.io/...` from Cloud Build.)

---

## 3) Install `gcloud` on your PC (your computer)

- Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) for Windows.
- Open **PowerShell** and run:

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Replace `YOUR_PROJECT_ID` with the ID from step 1.

---

## 4) Build the image (your PC, in the project folder)

In PowerShell, go to your repo root (folder that contains `backend/` and `cloudbuild.yaml`):

```powershell
cd path\to\pharmaspot-morocco
gcloud builds submit --config cloudbuild.yaml .
```

First run can take **10–20 minutes** (Geo stack). When it finishes, the image is at:

`gcr.io/YOUR_PROJECT_ID/pharmaspot-backend:latest`

---

## 5) Deploy to Cloud Run (your PC)

Pick a **region** close to you, e.g. `europe-west1` (Belgium).

```powershell
gcloud run deploy pharmaspot-backend `
  --image gcr.io/YOUR_PROJECT_ID/pharmaspot-backend:latest `
  --region europe-west1 `
  --platform managed `
  --allow-unauthenticated `
  --memory 4Gi `
  --cpu 2 `
  --timeout 3600 `
  --max-instances 2 `
  --port 8080
```

Notes:

- **`--memory 4Gi`**: heavy analysis may need this; if deploy fails or you see OOM in logs, try **`8Gi`**.
- **`--timeout 3600`**: long Overpass + grid work (max allowed for Cloud Run requests).
- **`--port 8080`**: Cloud Run’s default; the app reads **`PORT`** (our Dockerfile supports it).

When it finishes, the command prints a **HTTPS URL** like:

`https://pharmaspot-backend-xxxxx-ew.a.run.app`

---

## 6) Test (browser)

Open:

`https://YOUR_SERVICE_URL/api/health`

You should see JSON with `"status":"ok"`.

---

## 7) Connect Vercel (browser)

1. Vercel → your project → **Settings** → **Environment variables**.
2. Set:

   - `VITE_API_BASE_URL` = `https://YOUR_SERVICE_URL`  
     (no trailing slash)

3. **Redeploy** the frontend so the variable is baked into the build.

---

## Cache / disk on Cloud Run

Cloud Run **does not** give you a persistent disk for `data_cache`. After scale-to-zero or new instances, **Overpass/raster may download again** (slower, more rate limits). For a stable cache you’d add **Cloud Storage** or another store later; for a demo this is usually acceptable.

---

## Troubleshooting

| Problem | What to try |
|--------|-------------|
| Build fails | In Cloud Console → **Cloud Build** → **History** → open failed build → read error log. |
| 503 / timeout | Raise **`--timeout`**, increase **memory**, try a smaller city first. |
| 429 from Overpass | Wait and retry; cache is less effective without persistent disk. |

---

## Alternative: Cloud Shell (no local `gcloud` install)

1. Open [Cloud Shell](https://shell.cloud.google.com/) from the console.
2. Upload or clone your repo, then run the same `gcloud builds submit` and `gcloud run deploy` commands (use Linux path syntax).
