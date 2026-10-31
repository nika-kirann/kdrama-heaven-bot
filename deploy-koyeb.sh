#!/usr/bin/env bash
# Koyeb deploy from GitHub as a FREE web service (needs: koyeb CLI logged in, secrets created; see README).
set -euo pipefail
koyeb app init kdrama-heaven \
  --git github.com/nika-kirann/kdrama-heaven-bot --git-branch main \
  --git-builder docker --git-docker-dockerfile Dockerfile \
  --type web --instance-type free --regions fra --min-scale 1 --max-scale 1 \
  --ports 8000:http --routes /:8000 --checks 8000:http:/healthz \
  --env BOT_TOKEN=@BOT_TOKEN --env CHANNEL_ID=@CHANNEL_ID --env STORAGE_CHANNEL_ID=@STORAGE_CHANNEL_ID \
  --env ADMIN_IDS=@ADMIN_IDS --env PORT=8000 --env TIMEZONE=Asia/Kolkata --env STORAGE_BACKEND=telegram \
  --env DAILY_DIGEST_TIME=10:00 --env CLEANUP_DAYS=2 --env CLEANUP_TIME=03:30 \
  --env DATABASE_URL=sqlite:////tmp/kdrama.db
