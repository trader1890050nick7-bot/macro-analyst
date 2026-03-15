"""APScheduler jobs.

Schedule (all times UTC):
  - 06:30, 12:00, 20:00 : fetch prices + news → run sentiment → save to DB
  - 18:45 daily         : generate macro brief → save to DB
  - 19:00 daily         : generate trading ideas → save to DB
  - 19:05 daily         : send brief + ideas to all subscribed Telegram users
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


# ---- job functions ----------------------------------------------------

async def job_sentiment_update() -> None:
    """Every 30 min: fetch prices + news → analyse sentiment → persist."""
    logger.info("[scheduler] Starting sentiment update job")
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
    """07:00 UTC: generate and save the daily macro brief."""
    logger.info("[scheduler] Starting daily brief generation")
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
    """07:30 UTC: generate and save trading ideas."""
    logger.info("[scheduler] Starting trading ideas generation")
    try:
        from ai.ideas import run_trading_ideas

        ideas = await run_trading_ideas()
        logger.info("[scheduler] %d trading ideas generated", len(ideas))
    except Exception as exc:
        logger.error("[scheduler] Trading ideas failed: %s", exc)


async def job_broadcast(application) -> None:
    """07:35 UTC: broadcast brief + ideas to all subscribers."""
    logger.info("[scheduler] Starting broadcast job")
    try:
        from bot.telegram_bot import broadcast_daily

        await broadcast_daily(application)
        logger.info("[scheduler] Broadcast completed")
    except Exception as exc:
        logger.error("[scheduler] Broadcast failed: %s", exc)


# ---- scheduler setup --------------------------------------------------

def create_scheduler(application) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # 06:30 UTC — morning sentiment update
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="sentiment_morning",
        name="Sentiment Update (Morning)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 12:00 UTC — midday sentiment update
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=12, minute=0, timezone="UTC"),
        id="sentiment_midday",
        name="Sentiment Update (Midday)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 20:00 UTC — evening sentiment update
    scheduler.add_job(
        job_sentiment_update,
        trigger=CronTrigger(hour=20, minute=0, timezone="UTC"),
        id="sentiment_evening",
        name="Sentiment Update (Evening)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 18:45 UTC daily (19:45 Belgrade/Berlin UTC+1) — macro brief
    scheduler.add_job(
        job_daily_brief,
        trigger=CronTrigger(hour=18, minute=45, timezone="UTC"),
        id="daily_brief",
        name="Daily Brief",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 19:00 UTC daily (20:00 Belgrade/Berlin UTC+1) — trading ideas
    scheduler.add_job(
        job_trading_ideas,
        trigger=CronTrigger(hour=19, minute=0, timezone="UTC"),
        id="trading_ideas",
        name="Trading Ideas",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 19:05 UTC daily (20:05 Belgrade/Berlin UTC+1) — Telegram broadcast
    scheduler.add_job(
        job_broadcast,
        args=[application],
        trigger=CronTrigger(hour=19, minute=5, timezone="UTC"),
        id="broadcast",
        name="Telegram Broadcast",
        replace_existing=True,
        misfire_grace_time=300,
    )

    return scheduler
