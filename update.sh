#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Pulling latest changes..."
git pull

if [[ ! -d ".venv" ]]; then
    echo "==> Creating virtual environment in .venv..."
    python3 -m venv .venv
fi

echo "==> Updating package and dependencies in editable mode..."
.venv/bin/pip install -e .

SERVICE_NAME="index-org-webhook"
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    echo "==> Restarting ${SERVICE_NAME} systemd service..."
    sudo systemctl restart "${SERVICE_NAME}"
    echo "==> ${SERVICE_NAME} restarted."
elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" 2>/dev/null | grep -q "${SERVICE_NAME}.service"; then
    echo "==> Restarting ${SERVICE_NAME} systemd service..."
    sudo systemctl restart "${SERVICE_NAME}"
    echo "==> ${SERVICE_NAME} restarted."
else
    echo "==> Note: systemd service '${SERVICE_NAME}' not running or not found. Restart manually if running."
fi

echo "==> Update complete!"
