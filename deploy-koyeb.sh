#!/usr/bin/env bash
# One-shot Koyeb deploy from GitHub (needs: koyeb CLI logged in, secrets created; see README).
set -euo pipefail
koyeb app init kdrama-heaven \
  --git github.com/nika-kirann/kdrama-heaven-bot --git-branch main \
  --git-builder docker --git-docker-dockerfile Dockerfile \
  --type worker --instance-type eco-nano --regions sin --min-scale 1 --max-scale 1 \
  --env BOT_TOKEN=@BOT_TOKEN --env CHANNEL_ID=@CHANNEL_ID --env STORAGE_CHANNEL_ID=@STORAGE_CHANNEL_ID \
  --env ADMIN_IDS=@ADMIN_IDS --env TIMEZONE=Asia/Kolkata --env STORAGE_BACKEND=telegram \
  --env DAILY_DIGEST_TIME=10:00 --env CLEANUP_DAYS=2 --env CLEANUP_TIME=03:30 \
  --env DATABASE_URL=sqlite:////tmp/kdrama.db
