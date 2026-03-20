"""Telegram bot handlers.

Commands:
  /start    — Welcome + subscription
  /brief    — Today's macro brief
  /sentiment — Sentiment cards for all 5 assets
  /ideas    — Today's 3 trading ideas
  /help     — Command list
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID
from bot.formatter import (
    format_welcome,
    format_help,
    format_all_sentiments,
    format_brief,
    format_all_ideas,
    format_admin_stats,
)
from db import supabase as db

LANGUAGES = {
    "en": "🇬🇧 English",
    "es": "🇪🇸 Español",
    "de": "🇩🇪 Deutsch",
    "ru": "🇷🇺 Русский",
    "uz": "🇺🇿 O'zbek",
    "uk": "🇺🇦 Українська",
    "fr": "🇫🇷 Français",
    "zh": "🇨🇳 中文",
}

logger = logging.getLogger(__name__)


# ---- helpers ----------------------------------------------------------

async def _send_chunks(
    update: Update,
    messages: list[str],
    parse_mode: str = ParseMode.HTML,
) -> None:
    for chunk in messages:
        await update.message.reply_text(chunk, parse_mode=parse_mode)


async def _send_translated(update: Update, messages: list[str]) -> None:
    """Translate messages to the user's language, then send."""
    from ai.translate import translate_text
    user_id = update.effective_user.id
    lang = db.get_user_language(user_id)
    if lang != "en":
        translated = [await translate_text(msg, lang) for msg in messages]
    else:
        translated = messages
    await _send_chunks(update, translated)


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
            "⚠️ No brief available yet. Briefs are generated weekdays at 18:45 UTC.",
        )
        return

    await _send_translated(update, format_brief(brief))


async def cmd_sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📡 Fetching latest sentiments...")

    sentiments = db.get_latest_sentiments()
    await _send_translated(update, format_all_sentiments(sentiments))


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("💡 Fetching today's trading ideas...")

    ideas = db.get_latest_ideas()
    await _send_translated(update, format_all_ideas(ideas))


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = list(LANGUAGES.items())
    keyboard = [
        [
            InlineKeyboardButton(items[i][1], callback_data=f"lang_{items[i][0]}"),
            InlineKeyboardButton(items[i + 1][1], callback_data=f"lang_{items[i + 1][0]}"),
        ]
        for i in range(0, len(items), 2)
    ]
    await update.message.reply_text(
        "🌐 <b>Choose your language:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang_code = query.data.replace("lang_", "")
    if lang_code not in LANGUAGES:
        return
    db.update_user_language(query.from_user.id, lang_code)
    lang_name = LANGUAGES[lang_code]
    await query.edit_message_text(f"✅ Language set to {lang_name}")


# ---- admin commands ---------------------------------------------------

async def cmd_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info("[admin_stats] Called by user_id=%s, ADMIN_TELEGRAM_ID=%s", user_id, ADMIN_TELEGRAM_ID)

    if not ADMIN_TELEGRAM_ID:
        await update.message.reply_text("⚠️ ADMIN_TELEGRAM_ID env var is not set on the server.")
        return
    if user_id != ADMIN_TELEGRAM_ID:
        return  # Silent ignore for non-admins

    await update.message.reply_text("⏳ Generating stats...")
    stats = db.get_performance_stats()
    await update.message.reply_text(format_admin_stats(stats), parse_mode=ParseMode.HTML)

    # Send equity charts
    try:
        from bot.charts import generate_equity_chart, generate_per_asset_chart
        equity_trades = stats.get("equity_trades", [])
        by_asset = stats.get("by_asset", {})

        overall_img = generate_equity_chart(equity_trades)
        if overall_img:
            await update.message.reply_photo(
                photo=overall_img,
                caption="📊 Overall Equity Curve (all assets combined)",
            )

        per_asset_img = generate_per_asset_chart(by_asset, equity_trades)
        if per_asset_img:
            await update.message.reply_photo(
                photo=per_asset_img,
                caption="📊 Per-Asset Equity Curves",
            )
    except Exception as exc:
        logger.error("Failed to generate admin charts: %s", exc)


# ---- broadcast (called by scheduler) ----------------------------------

async def broadcast_daily(application: Application, force: bool = False) -> None:
    """Send brief + ideas to all subscribed users in their preferred language.

    Args:
        force: If True, bypasses the deduplication lock (for manual triggers).
    """
    from bot.formatter import format_broadcast
    from ai.translate import translate_text
    from collections import defaultdict

    logger.info("[broadcast] Starting broadcast (force=%s)", force)

    brief = db.get_latest_brief()
    ideas = db.get_latest_ideas()
    logger.info("[broadcast] DB check — brief: %s, ideas count: %d",
                f"id={brief.id}" if brief else "None", len(ideas))

    if not brief and not ideas:
        logger.warning("[broadcast] Nothing to broadcast — brief and ideas both missing")
        return

    # Deduplication: only one Railway instance should send the broadcast.
    # Skipped when force=True (manual trigger via API).
    if not force and brief and brief.id is not None:
        if not db.claim_brief_for_broadcast(brief.id):
            logger.info("[broadcast] Already claimed by another instance — skipping")
            return
    elif force:
        logger.info("[broadcast] force=True — skipping deduplication lock")

    subscribers = db.get_subscribed_users_with_language()
    logger.info("[broadcast] Subscribers from DB: %d — %s",
                len(subscribers), [(uid, lang) for uid, lang in subscribers])
    if not subscribers:
        logger.warning("[broadcast] No subscribers found with subscribed=True")
        return

    # Build English content once
    messages_en = format_broadcast(brief, ideas) if brief else format_all_ideas(ideas)
    logger.info("[broadcast] Prepared %d message chunk(s) in EN, total chars: %s",
                len(messages_en), [len(m) for m in messages_en])

    # Group users by language
    by_lang: dict[str, list[int]] = defaultdict(list)
    for user_id, lang in subscribers:
        by_lang[lang].append(user_id)

    # Translate once per language group, then send
    for lang, user_ids in by_lang.items():
        if lang == "en":
            messages = messages_en
        else:
            try:
                messages = [await translate_text(msg, lang) for msg in messages_en]
            except Exception as exc:
                logger.error("[broadcast] Translation failed for lang=%s: %s — falling back to EN", lang, exc)
                messages = messages_en

        logger.info("[broadcast] Sending %d msg(s) in [%s] to %d user(s): %s",
                    len(messages), lang, len(user_ids), user_ids)
        for user_id in user_ids:
            logger.info("[broadcast] → Sending to user_id=%s", user_id)
            try:
                for i, msg in enumerate(messages):
                    logger.info("[broadcast]   chunk %d/%d (%d chars): %s",
                                i + 1, len(messages), len(msg), msg[:80].replace("\n", " "))
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=msg,
                        parse_mode=ParseMode.HTML,
                    )
                    logger.info("[broadcast]   chunk %d sent OK to user_id=%s", i + 1, user_id)
            except Exception as exc:
                logger.error("[broadcast] FAILED to send to user_id=%s: %s", user_id, exc)

    logger.info("[broadcast] Broadcast complete")


# ---- app factory ------------------------------------------------------

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("sentiment", cmd_sentiment))
    app.add_handler(CommandHandler("ideas", cmd_ideas))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("admin_stats", cmd_admin_stats))
    app.add_handler(CallbackQueryHandler(callback_language, pattern="^lang_"))
    return app
