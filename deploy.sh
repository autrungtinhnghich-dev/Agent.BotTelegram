#!/bin/bash
# deploy.sh — Kéo code mới nhất và restart Docker
# Dùng: ./deploy.sh
# Hoặc tự động qua GitHub Actions / webhook

set -e

echo "=== Deploy started: $(date) ==="

# Kéo code mới nhất
git pull origin main

# Rebuild và restart (không downtime nếu build thành công)
docker compose build --no-cache
docker compose up -d --force-recreate

# Dọn image cũ
docker image prune -f

echo "=== Deploy done: $(date) ==="
docker compose logs --tail=20
