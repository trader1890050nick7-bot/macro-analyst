"""FastAPI entry point for the AI Macro Market Analyst.

Startup:
  1. Build the Telegram Application
  2. Start APScheduler jobs
  3. Start Telegram polling in a background thread

REST endpoints (for health checks & manual triggers):
  GET  /health                  — liveness check
  POST /trigger/sentiment       — manually trigger sentiment update
  POST /trigger/brief           — manually trigger brief generation
  POST /trigger/ideas           — manually trigger ideas generation
  POST /trigger/broadcast       — manually trigger Telegram broadcast
  GET  /data/sentiments         — latest sentiments for all assets
  GET  /data/brief              — latest brief
  GET  /data/ideas              — latest trading ideas
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from config import TELEGRAM_BOT_TOKEN  # validates env on import
from bot.telegram_bot import build_application
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---- global state -----------------------------------------------------

_scheduler = None
_tg_application = None


# ---- lifespan ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler, _tg_application

    logger.info("Starting Macro Analyst API...")

    # Build Telegram app
    _tg_application = build_application()
    await _tg_application.initialize()

    # Start scheduler
    _scheduler = create_scheduler(_tg_application)
    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))

    # Start Telegram polling in a background thread so it doesn't block FastAPI
    _tg_thread = threading.Thread(
        target=_run_telegram_polling, daemon=True, name="telegram-polling"
    )
    _tg_thread.start()
    logger.info("Telegram polling started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    _scheduler.shutdown(wait=False)
    await _tg_application.stop()
    await _tg_application.shutdown()


def _run_telegram_polling() -> None:
    """Run the Telegram bot in its own event loop (separate thread)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_tg_application.run_polling(close_loop=False))
    finally:
        loop.close()


# ---- app --------------------------------------------------------------

app = FastAPI(
    title="AI Macro Market Analyst",
    description="Automated macro analysis for EUR/USD, Gold, Brent, S&P 500, and BTC",
    version="1.0.0",
    lifespan=lifespan,
)


# ---- health -----------------------------------------------------------

@app.get("/health")
async def health():
    jobs = [
        {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
        for j in (_scheduler.get_jobs() if _scheduler else [])
    ]
    return {"status": "ok", "scheduled_jobs": jobs}


# ---- manual triggers --------------------------------------------------

@app.post("/trigger/sentiment")
async def trigger_sentiment():
    from data.prices import fetch_all_prices
    from data.news import fetch_all_news
    from ai.sentiment import analyze_all_sentiments

    prices = await fetch_all_prices(force=True)
    news = await fetch_all_news(force=True)
    sentiments = await analyze_all_sentiments(prices, news)
    return {"triggered": "sentiment", "count": len(sentiments)}


@app.post("/trigger/brief")
async def trigger_brief():
    from ai.brief import run_daily_brief

    brief = await run_daily_brief()
    if not brief:
        raise HTTPException(status_code=500, detail="Brief generation failed")
    return {"triggered": "brief", "length": len(brief.content)}


@app.post("/trigger/ideas")
async def trigger_ideas():
    from ai.ideas import run_trading_ideas

    ideas = await run_trading_ideas()
    return {"triggered": "ideas", "count": len(ideas)}


@app.post("/trigger/broadcast")
async def trigger_broadcast():
    from bot.telegram_bot import broadcast_daily
    from db import supabase as db

    subscribers = db.get_subscribed_users()
    await broadcast_daily(_tg_application)
    return {"triggered": "broadcast", "subscribers": len(subscribers)}


# ---- data endpoints ---------------------------------------------------

@app.get("/data/sentiments")
async def get_sentiments():
    from db import supabase as db

    sentiments = db.get_latest_sentiments()
    return {"sentiments": [s.model_dump() for s in sentiments]}


@app.get("/data/brief")
async def get_brief():
    from db import supabase as db

    brief = db.get_latest_brief()
    if not brief:
        raise HTTPException(status_code=404, detail="No brief available")
    return brief.model_dump()


@app.get("/data/ideas")
async def get_ideas():
    from db import supabase as db

    ideas = db.get_latest_ideas()
    return {"ideas": [i.model_dump() for i in ideas]}


# ---- entry point ------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
