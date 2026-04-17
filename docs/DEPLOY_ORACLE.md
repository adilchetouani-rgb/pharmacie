# Deploy backend on Oracle Cloud (Always Free ARM)

Your **FastAPI + Geo** backend should run on an **Ampere A1** VM (ARM), not on the tiny x86 “micro” instance (too little RAM).

I cannot create your Oracle account or VM for you. Follow Part A once, then Part B is one command.

## Part A — Create the VM (Oracle Console)

1. Sign in to [Oracle Cloud Console](https://cloud.oracle.com/).
2. **Create a VCN** (if you have none): Networking → Virtual Cloud Networks → **Create VCN** (use the default wizard “Create VCN with Internet Connectivity” or equivalent).
3. **Create a compute instance**:
   - **Image:** Canonical **Ubuntu 22.04** or **24.04** (aarch64 / ARM64).
   - **Shape:** **VM.Standard.A1.Flex** (Ampere).  
     - Pick **2 OCPU** and **12 GB memory** (or more if your quota allows; stay within Always Free limits).
   - **Networking:** public subnet, **assign public IPv4**.
   - **SSH keys:** paste your **public** key (generate with PuTTY or `ssh-keygen` on Windows).

4. **Open port 8000** in the **Subnet security list** (Ingress rules):
   - Source: `0.0.0.0/0` (demo) or your home IP only (safer).
   - IP protocol: **TCP**, destination port: **8000**.

5. Wait until instance state is **Running**. Note the **Public IP**.

6. **SSH** from your PC (PowerShell):

```powershell
ssh ubuntu@YOUR_PUBLIC_IP
```

(Username may be `ubuntu` or `opc` depending on image; Oracle’s connect dialog shows the right user.)

## Part B — Install the app (one script)

**Option 1 — after the script exists on GitHub `main`** (push your repo first):

On the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/adilchetouani-rgb/pharmacie/main/scripts/oracle-vm-bootstrap.sh | bash
```

Another repo URL:

```bash
export REPO_URL=https://github.com/YOUR_USER/YOUR_REPO.git
curl -fsSL https://raw.githubusercontent.com/adilchetouani-rgb/pharmacie/main/scripts/oracle-vm-bootstrap.sh | bash
```

**Option 2 — clone first** (works even before the raw file is on GitHub):

```bash
sudo mkdir -p /opt/pharmaspot
sudo git clone https://github.com/adilchetouani-rgb/pharmacie.git /opt/pharmaspot
sudo bash /opt/pharmaspot/scripts/oracle-vm-bootstrap.sh
```

## Verify

From your laptop:

```text
http://YOUR_PUBLIC_IP:8000/api/health
```

You should see JSON like `{"status":"ok",...}`.

## Frontend (Vercel) and HTTPS

- **Problem:** Vercel serves **HTTPS**. Browsers usually **block** calling an **HTTP** API (mixed content).
- **Fix (pick one):**
  1. **Cloudflare Tunnel** (no domain): install `cloudflared` on the VM and expose `localhost:8000` — you get an `https://....trycloudflare.com` URL. Set `VITE_API_BASE_URL` to that URL on Vercel.
  2. **Your own domain + reverse proxy + Let’s Encrypt** (Caddy or nginx) on the VM pointing to port 8000.

## Data cache

The bootstrap script mounts a Docker volume `pharmaspot_data_cache` at `/app/data_cache` so Overpass/raster files survive container restarts.

## Updates

SSH to the VM and run:

```bash
cd /opt/pharmaspot && sudo git pull && sudo docker build -f backend/Dockerfile -t pharmaspot-backend:latest . && sudo docker rm -f pharmaspot-backend && sudo docker run -d --name pharmaspot-backend --restart unless-stopped -p 0.0.0.0:8000:8000 -v pharmaspot_data_cache:/app/data_cache pharmaspot-backend:latest
```

## Troubleshooting

- **Out of memory:** increase A1 memory or reduce concurrent analysis; free tier elsewhere used 512MB — A1 with 12GB is usually fine.
- **First run slow:** Overpass + raster download; normal.
- **Cannot reach :8000:** check VCN security list, local firewall (`sudo ufw status`), and that the container is running (`sudo docker ps`).
