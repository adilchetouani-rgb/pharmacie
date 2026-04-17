#!/usr/bin/env bash
# Run on a fresh Ubuntu 22.04/24.04 ARM (Ampere) VM on Oracle Cloud.
# Usage (after SSH): curl -fsSL ... | bash   OR  bash oracle-vm-bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/adilchetouani-rgb/pharmacie.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pharmaspot}"
BRANCH="${BRANCH:-main}"
IMAGE_NAME="${IMAGE_NAME:-pharmaspot-backend}"
CONTAINER_NAME="${CONTAINER_NAME:-pharmaspot-backend}"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "==> Installing Docker (Ubuntu package docker.io — works on ARM Oracle images)..."
$SUDO apt-get update -y
$SUDO apt-get install -y ca-certificates curl git docker.io

$SUDO systemctl enable --now docker

echo "==> Cloning / updating repo..."
$SUDO mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  $SUDO git -C "$INSTALL_DIR" fetch origin
  $SUDO git -C "$INSTALL_DIR" checkout "$BRANCH"
  $SUDO git -C "$INSTALL_DIR" pull origin "$BRANCH"
else
  $SUDO git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

echo "==> Building image (ARM64; first build may take several minutes)..."
cd "$INSTALL_DIR"
$SUDO docker build -f backend/Dockerfile -t "$IMAGE_NAME:latest" .

echo "==> Stopping old container if any..."
$SUDO docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "==> Starting API on port 8000..."
$SUDO docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p 0.0.0.0:8000:8000 \
  -v pharmaspot_data_cache:/app/data_cache \
  "$IMAGE_NAME:latest"

echo ""
echo "Done. Test from your laptop:"
echo "  curl http://YOUR_PUBLIC_IP:8000/api/health"
echo ""
echo "Vercel env: VITE_API_BASE_URL=http://YOUR_PUBLIC_IP:8000"
echo "(Browsers block HTTP API from HTTPS sites — use docs/DEPLOY_ORACLE.md \"HTTPS\" section.)"
echo ""
