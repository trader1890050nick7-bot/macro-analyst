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
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from telegram.error import Conflict

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

    # Start Telegram polling directly in the FastAPI event loop
    # drop_pending_updates=True clears any queued updates so a previously
    # running instance (local or Railway) cannot cause a Conflict error.
    try:
        await _tg_application.updater.start_polling(drop_pending_updates=True)
        await _tg_application.start()
        logger.info("Telegram polling started")
    except Conflict as exc:
        logger.error(
            "Telegram Conflict: another bot instance is already polling — %s. "
            "Stop the other instance and redeploy.",
            exc,
        )
        raise RuntimeError("Telegram bot conflict: only one instance may poll at a time.") from exc

    yield

    # Shutdown
    logger.info("Shutting down...")
    _scheduler.shutdown(wait=False)
    await _tg_application.updater.stop()
    await _tg_application.stop()
    await _tg_application.shutdown()


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
async def trigger_broadcast(force: bool = False):
    from bot.telegram_bot import broadcast_daily
    from db import supabase as db

    subscribers = db.get_subscribed_users()
    await broadcast_daily(_tg_application, force=force)
    return {"triggered": "broadcast", "subscribers": len(subscribers), "force": force}


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


# ---- NOWPayments IPN webhook ------------------------------------------

PAYMENT_CONFIRMED_STATUSES = {"confirmed", "sending", "finished"}


@app.post("/webhook/nowpayments")
async def webhook_nowpayments(request: Request):
    from payments.nowpayments import verify_ipn_signature
    from db import supabase as db
    from config import SUBSCRIPTION_DAYS

    raw_body = await request.body()
    sig = request.headers.get("x-nowpayments-sig", "")

    if not verify_ipn_signature(raw_body, sig):
        logger.warning("[nowpayments] IPN signature mismatch — rejected")
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(raw_body)
    nowpayments_id = str(data.get("payment_id", ""))
    status = data.get("payment_status", "")
    order_id = str(data.get("order_id", ""))

    logger.info("[nowpayments] IPN: payment_id=%s status=%s order_id=%s", nowpayments_id, status, order_id)

    if nowpayments_id:
        db.update_payment_status(nowpayments_id, status)

    if status not in PAYMENT_CONFIRMED_STATUSES:
        return {"ok": True}

    # Idempotency: only activate once per payment
    payment_row = db.get_payment_by_nowpayments_id(nowpayments_id)
    if payment_row and payment_row.get("status") in PAYMENT_CONFIRMED_STATUSES:
        logger.info("[nowpayments] Payment %s already processed — skipping", nowpayments_id)
        return {"ok": True}

    # Get telegram_id from order_id (set to str(telegram_id) on payment creation)
    try:
        telegram_id = int(order_id)
    except (ValueError, TypeError):
        logger.error("[nowpayments] Cannot parse telegram_id from order_id=%s", order_id)
        return {"ok": True}

    new_expiry = db.activate_subscription(telegram_id, days=SUBSCRIPTION_DAYS)
    logger.info("[nowpayments] Subscription activated for user %s until %s", telegram_id, new_expiry)

    # Notify user via Telegram
    if _tg_application:
        try:
            await _tg_application.bot.send_message(
                chat_id=telegram_id,
                text=(
                    "🎉 <b>Payment confirmed!</b>\n\n"
                    f"Your subscription is active until <b>{new_expiry.strftime('%B %d, %Y')}</b>.\n\n"
                    "You now have access to /brief, /sentiment and /ideas. Enjoy! 📈"
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("[nowpayments] Failed to notify user %s: %s", telegram_id, exc)

    return {"ok": True}


# ---- entry point ------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
