"""Scheduled jobs on PTB's JobQueue (APScheduler under the hood).
Schedules are persisted in SQLite and re-registered on startup, so they survive restarts."""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from telegram.ext import Application, ContextTypes

from utils import parse_hhmm

log = logging.getLogger(__name__)


async def _schedule_job(context: ContextTypes.DEFAULT_TYPE):
    await context.bot_data["svc"].run_schedule(context.job.data)


async def _digest_job(context: ContextTypes.DEFAULT_TYPE):
    await context.bot_data["svc"].daily_digest()


async def _cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    await context.bot_data["svc"].cleanup()


def queue_schedule(job_queue, sc) -> None:
    when = sc.run_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if when < now:  # missed while offline: post shortly after startup
        when = now + timedelta(seconds=5)
    job_queue.run_once(_schedule_job, when=when, data=sc.id, name=f"schedule:{sc.id}")


def setup_jobs(app: Application) -> None:
    cfg, db = app.bot_data["cfg"], app.bot_data["db"]
    jq = app.job_queue
    hh, mm = parse_hhmm(cfg.daily_digest_time)
    jq.run_daily(_digest_job, time=time(hh, mm, tzinfo=cfg.tz), name="daily_digest")
    ch, cm = parse_hhmm(cfg.cleanup_time)
    jq.run_daily(_cleanup_job, time=time(ch, cm, tzinfo=cfg.tz), name="daily_cleanup")
    pending = db.pending_schedules()
    for sc in pending:
        queue_schedule(jq, sc)
    log.info("Jobs ready: digest %s, cleanup %s %s, %d pending schedules restored",
             cfg.daily_digest_time, cfg.cleanup_time, cfg.timezone, len(pending))
