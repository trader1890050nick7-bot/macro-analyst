"""APScheduler jobs.

Schedule (all times UTC):
  - 07:00, 13:00, 18:00 : fetch prices + news → run sentiment → save to DB
  - 18:02 daily         : generate macro brief → save to DB
  - 18:04 daily         : generate trading ideas → save to DB
  - 18:05 daily         : send brief + ideas to all subscribed Telegram users
"""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


# ---- job functions ----------------------------------------------------

async def job_sentiment_update() -> None:
    """Every 30 min: fetch prices + news → analyse sentiment → persist."""
    logger.info("[scheduler] FIRED sentiment_update at %s UTC", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    try:
        from data.prices import fetch_all_prices
        from data.news import fetch_all_news
        from ai.sentiment import analyze_all_sentiments

        prices = await fetch_all_prices()
        news = await fetch_all_news()
        sentiments = await analyze_all_sentiments(prices, news)
        logger.info("[scheduler] Sentiment update done — %d sentiments saved", len(sentiments))
    except Exception as exc:
        logger.error("[scheduler] Sentiment update failed: %s", exc)


async def job_daily_brief() -> None:
    """18:30 UTC: generate and save the daily macro brief."""
    logger.info("[scheduler] FIRED daily_brief at %s UTC", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    try:
        from ai.brief import run_daily_brief

        brief = await run_daily_brief()
        if brief:
            logger.info("[scheduler] Daily brief generated (%d chars)", len(brief.content))
        else:
            logger.warning("[scheduler] Daily brief generation returned None")
    except Exception as exc:
        logger.error("[scheduler] Daily brief failed: %s", exc)


async def job_trading_ideas() -> None:
    """18:35 UTC: generate and save trading ideas."""
    logger.info("[scheduler] FIRED trading_ideas at %s UTC", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    try:
        from ai.ideas import run_trading_ideas

        ideas = await run_trading_ideas()
        logger.info("[scheduler] %d trading ideas generated", len(ideas))
    except Exception as exc:
        logger.error("[scheduler] Trading ideas failed: %s", exc)


async def job_performance_check() -> None:
    """Hourly: check open trading ideas against current prices."""
    logger.info("[scheduler] FIRED performance_check at %s UTC", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    try:
        from data.performance import run_performance_checks

        await run_performance_checks()
        logger.info("[scheduler] Performance check done")
    except Exception as exc:
        logger.error("[scheduler] Performance check failed: %s", exc)


async def job_broadcast(application) -> None:
    """18:40 UTC: broadcast brief + ideas to all subscribers."""
    logger.info("[scheduler] FIRED broadcast at %s UTC", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    try:
        from bot.telegram_bot import broadcast_daily

        await broadcast_daily(application)
        logger.info("[scheduler] Broadcast completed")
    except Exception as exc:
        logger.error("[scheduler] Broadcast failed: %s", exc)


# ---- scheduler setup --------------------------------------------------

def create_scheduler(application) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # 07:00 UTC Mon–Fri — morning sentiment update
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=7, minute=0, day_of_week="mon-fri", timezone="UTC"),
        id="sentiment_morning",
        name="Sentiment Update (Morning)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 13:00 UTC Mon–Fri — midday sentiment update
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=13, minute=0, day_of_week="mon-fri", timezone="UTC"),
        id="sentiment_midday",
        name="Sentiment Update (Midday)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 18:00 UTC Mon–Fri — pre-brief sentiment update (fresh prices for today's session)
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone="UTC"),
        id="sentiment_evening",
        name="Sentiment Update (Evening)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 18:02 UTC Mon–Fri — macro brief (uses 18:00 sentiment = today's prices)
    scheduler.add_job(
        job_daily_brief,
        trigger=CronTrigger(hour=18, minute=2, day_of_week="mon-fri", timezone="UTC"),
        id="daily_brief",
        name="Daily Brief",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 18:04 UTC Mon–Fri — trading ideas
    scheduler.add_job(
        job_trading_ideas,
        trigger=CronTrigger(hour=18, minute=4, day_of_week="mon-fri", timezone="UTC"),
        id="trading_ideas",
        name="Trading Ideas",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 18:05 UTC Mon–Fri — Telegram broadcast
    scheduler.add_job(
        job_broadcast,
        args=[application],
        trigger=CronTrigger(hour=18, minute=5, day_of_week="mon-fri", timezone="UTC"),
        id="broadcast",
        name="Telegram Broadcast",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Every hour at :00 — performance check for open ideas
    scheduler.add_job(
        job_performance_check,
        trigger=CronTrigger(minute=0, timezone="UTC"),
        id="performance_check",
        name="Performance Check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    return scheduler
