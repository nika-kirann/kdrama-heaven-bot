#!/usr/bin/env bash
# Sets up a venv on first run, then starts the bot.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { echo "No .env found: cp .env.example .env and fill it in."; exit 1; }
exec .venv/bin/python main.py
