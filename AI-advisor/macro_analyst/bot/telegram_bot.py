"""Telegram bot handlers.

Commands:
  /start    — Welcome + subscription
  /brief    — Today's macro brief
  /sentiment — Sentiment cards for all 5 assets
  /ideas    — Today's 3 trading ideas
  /help     — Command list
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN
from bot.formatter import (
    format_welcome,
    format_help,
    format_all_sentiments,
    format_brief,
    format_all_ideas,
)
from db import supabase as db

logger = logging.getLogger(__name__)


# ---- helpers ----------------------------------------------------------

async def _send_chunks(
    update: Update,
    messages: list[str],
    parse_mode: str = ParseMode.HTML,
) -> None:
    for chunk in messages:
        await update.message.reply_text(chunk, parse_mode=parse_mode)


# ---- command handlers -------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    try:
        db.upsert_user(user_id, subscribed=True)
        logger.info("User %s subscribed", user_id)
    except Exception as exc:
        logger.error("Failed to upsert user %s: %s", user_id, exc)

    await update.message.reply_text(
        format_welcome(),
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        format_help(),
        parse_mode=ParseMode.HTML,
    )


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Fetching today's brief...")

    brief = db.get_latest_brief()
    if not brief:
        await update.message.reply_text(
            "⚠️ No brief available yet. Briefs are generated at 07:00 UTC.",
        )
        return

    await _send_chunks(update, format_brief(brief))


async def cmd_sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📡 Fetching latest sentiments...")

    sentiments = db.get_latest_sentiments()
    await _send_chunks(update, format_all_sentiments(sentiments))


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("💡 Fetching today's trading ideas...")

    ideas = db.get_latest_ideas()
    await _send_chunks(update, format_all_ideas(ideas))


# ---- broadcast (called by scheduler) ----------------------------------

async def broadcast_daily(application: Application) -> None:
    """Send brief + ideas to all subscribed users."""
    from bot.formatter import format_broadcast

    brief = db.get_latest_brief()
    ideas = db.get_latest_ideas()

    if not brief and not ideas:
        logger.warning("Nothing to broadcast — brief and ideas both missing")
        return

    subscribers = db.get_subscribed_users()
    if not subscribers:
        logger.info("No subscribers to broadcast to")
        return

    messages = format_broadcast(brief, ideas) if brief else format_all_ideas(ideas)
    logger.info("Broadcasting %d messages to %d subscribers", len(messages), len(subscribers))

    for user_id in subscribers:
        try:
            for msg in messages:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                )
        except Exception as exc:
            logger.error("Failed to send broadcast to %s: %s", user_id, exc)


# ---- app factory ------------------------------------------------------

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("sentiment", cmd_sentiment))
    app.add_handler(CommandHandler("ideas", cmd_ideas))
    return app
