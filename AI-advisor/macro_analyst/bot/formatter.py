"""Format data into Telegram-friendly messages (≤4096 chars each)."""

from db.models import Sentiment, Brief, Idea

TELEGRAM_MAX = 4096

SENTIMENT_EMOJI = {
    "bullish": "🟢",
    "bearish": "🔴",
    "neutral": "🟡",
}

DIRECTION_EMOJI = {
    "LONG": "📈",
    "SHORT": "📉",
}

ASSET_EMOJI = {
    "EURUSD": "💱",
    "XAUUSD": "🥇",
    "BRENT": "🛢️",
    "SPX": "📊",
    "BTC": "₿",
}

ASSET_NAMES = {
    "EURUSD": "EUR/USD",
    "XAUUSD": "Gold XAU/USD",
    "BRENT": "Brent Crude",
    "SPX": "S&P 500",
    "BTC": "Bitcoin BTC",
}


def _truncate(text: str, max_len: int = TELEGRAM_MAX) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ---- Welcome message --------------------------------------------------

def format_welcome() -> str:
    return (
        "👋 *Welcome to Macro Market Analyst Bot!*\n\n"
        "I provide daily AI-powered macro analysis covering:\n"
        "💱 EUR/USD • 🥇 Gold • 🛢️ Brent • 📊 S\\&P 500 • ₿ BTC\n\n"
        "*Commands:*\n"
        "/brief — Today's macro brief\n"
        "/sentiment — Live sentiment for all 5 assets\n"
        "/ideas — Today's 3 trading ideas\n"
        "/help — Show this help message\n\n"
        "📅 Updates delivered daily at 07:35 UTC"
    )


# ---- Help message -----------------------------------------------------

def format_help() -> str:
    return (
        "📖 *Available Commands*\n\n"
        "/start — Welcome message & subscription info\n"
        "/brief — Today's daily macro brief \\(400\\-500 words\\)\n"
        "/sentiment — Sentiment cards for all 5 assets\n"
        "/ideas — Today's 3 trading ideas with entry/SL/TP\n"
        "/help — This help message\n\n"
        "⏰ *Schedule \\(UTC\\)*\n"
        "• Every 30 min: Price \\& sentiment update\n"
        "• 07:00 — Daily macro brief generated\n"
        "• 07:30 — Trading ideas generated\n"
        "• 07:35 — Brief \\& ideas delivered to subscribers"
    )


# ---- Sentiment cards --------------------------------------------------

def format_sentiment_card(s: Sentiment) -> str:
    emoji = SENTIMENT_EMOJI.get(s.sentiment, "⚪")
    asset_emoji = ASSET_EMOJI.get(s.asset, "📌")
    asset_name = ASSET_NAMES.get(s.asset, s.asset)
    bar = _score_bar(s.score)
    return (
        f"{asset_emoji} *{asset_name}*\n"
        f"{emoji} *{s.sentiment.upper()}* — Score: {s.score}/100\n"
        f"{bar}\n"
        f"_{s.reasoning}_"
    )


def format_all_sentiments(sentiments: list[Sentiment]) -> list[str]:
    """Return list of messages (split if needed to stay under 4096 chars)."""
    if not sentiments:
        return ["⚠️ No sentiment data available yet\\. Try again in a few minutes\\."]

    header = "📡 *Live Market Sentiments*\n\n"
    cards = [format_sentiment_card(s) for s in sentiments]
    body = "\n\n".join(cards)
    full = header + body
    return _split_message(full)


def _score_bar(score: int, width: int = 10) -> str:
    filled = round(score / 100 * width)
    return "▓" * filled + "░" * (width - filled) + f" {score}%"


# ---- Brief ------------------------------------------------------------

def format_brief(brief: Brief) -> list[str]:
    """Split the brief into Telegram-sized chunks if needed."""
    header = "📰 *Daily Macro Brief*\n\n"
    full = header + brief.content
    return _split_message(full)


# ---- Trading ideas ----------------------------------------------------

def format_idea(idea: Idea) -> str:
    direction_emoji = DIRECTION_EMOJI.get(idea.direction, "➡️")
    asset_emoji = ASSET_EMOJI.get(idea.asset, "📌")
    asset_name = ASSET_NAMES.get(idea.asset, idea.asset)

    return (
        f"{asset_emoji} *{asset_name}* — {direction_emoji} *{idea.direction}*\n"
        f"⏱ Timeframe: `{idea.timeframe}`\n"
        f"🎯 Entry: `{idea.entry}`\n"
        f"🛑 Stop Loss: `{idea.stop_loss}`\n"
        f"✅ Take Profit: `{idea.take_profit}`\n"
        f"⚖️ R:R Ratio: `{idea.rr_ratio}`\n"
        f"💡 _{idea.reasoning}_"
    )


def format_all_ideas(ideas: list[Idea]) -> list[str]:
    if not ideas:
        return ["⚠️ No trading ideas available yet\\. Check back after 07:30 UTC\\."]

    header = "💡 *Today's Trading Ideas*\n\n"
    cards = [f"*Idea {i + 1}*\n{format_idea(idea)}" for i, idea in enumerate(ideas)]
    body = "\n\n" + "─" * 20 + "\n\n".join([""] + cards)
    full = header + body
    return _split_message(full)


# ---- Broadcast message ------------------------------------------------

def format_broadcast(brief: Brief, ideas: list[Idea]) -> list[str]:
    """Combine brief and ideas into one broadcast payload (multiple messages)."""
    messages = []
    messages.extend(format_brief(brief))
    messages.extend(format_all_ideas(ideas))
    return messages


# ---- Utility ----------------------------------------------------------

def _split_message(text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    """Split a long message into chunks ≤ max_len characters."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while len(text) > max_len:
        # Try to split at a paragraph boundary
        split_at = text.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks
