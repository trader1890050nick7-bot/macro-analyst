"""Format data into Telegram-friendly HTML messages (≤4096 chars each)."""

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
    "SPX": "S&amp;P 500",
    "BTC": "Bitcoin BTC",
}


def _h(text: str) -> str:
    """Escape HTML special chars."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---- Welcome ----------------------------------------------------------

def format_welcome() -> str:
    return (
        "👋 <b>Welcome to Macro Market Analyst Bot!</b>\n\n"
        "I provide daily AI-powered macro analysis covering:\n"
        "💱 EUR/USD • 🥇 Gold • 🛢️ Brent • 📊 S&amp;P 500 • ₿ BTC\n\n"
        "<b>Commands:</b>\n"
        "/brief — Today's macro brief\n"
        "/sentiment — Live sentiment for all 5 assets\n"
        "/ideas — Today's 3 trading ideas\n"
        "/language — Choose your language 🌐\n"
        "/help — Show this help message\n\n"
        "📅 Broadcast Mon–Fri at 20:05 Belgrade/Berlin time"
    )


# ---- Help -------------------------------------------------------------

def format_help() -> str:
    return (
        "📖 <b>Available Commands</b>\n\n"
        "/start — Welcome message &amp; subscription info\n"
        "/brief — Today's daily macro brief (400-500 words)\n"
        "/sentiment — Sentiment cards for all 5 assets\n"
        "/ideas — Today's 3 trading ideas with entry/SL/TP\n"
        "/language — Choose your language 🌐\n"
        "/help — This help message\n\n"
        "⏰ <b>Schedule (Mon–Fri, UTC)</b>\n"
        "• 06:30 / 12:00 / 20:00 — Sentiment update\n"
        "• 18:45 — Daily macro brief generated\n"
        "• 19:00 — Trading ideas generated\n"
        "• 19:05 — Brief &amp; ideas delivered to subscribers\n\n"
        "🌐 <b>Languages:</b> EN • ES • DE • RU • UZ • UK • FR • ZH"
    )


# ---- Sentiment cards --------------------------------------------------

def format_sentiment_card(s: Sentiment) -> str:
    emoji = SENTIMENT_EMOJI.get(s.sentiment, "⚪")
    asset_emoji = ASSET_EMOJI.get(s.asset, "📌")
    asset_name = ASSET_NAMES.get(s.asset, s.asset)
    bar = _score_bar(s.score)
    return (
        f"{asset_emoji} <b>{asset_name}</b>\n"
        f"{emoji} <b>{s.sentiment.upper()}</b> — Score: {s.score}/100\n"
        f"{bar}\n"
        f"<i>{_h(s.reasoning)}</i>"
    )


def format_all_sentiments(sentiments: list[Sentiment]) -> list[str]:
    if not sentiments:
        return ["⚠️ No sentiment data available yet. Try again in a few minutes."]

    header = "📡 <b>Live Market Sentiments</b>\n\n"
    cards = [format_sentiment_card(s) for s in sentiments]
    body = "\n\n".join(cards)
    return _split_message(header + body)


def _score_bar(score: int, width: int = 10) -> str:
    filled = round(score / 100 * width)
    return "▓" * filled + "░" * (width - filled) + f" {score}%"


# ---- Brief ------------------------------------------------------------

def format_brief(brief: Brief) -> list[str]:
    header = "📰 <b>Daily Macro Brief</b>\n\n"
    return _split_message(header + _h(brief.content))


# ---- Trading ideas ----------------------------------------------------

def format_idea(idea: Idea) -> str:
    direction_emoji = DIRECTION_EMOJI.get(idea.direction, "➡️")
    asset_emoji = ASSET_EMOJI.get(idea.asset, "📌")
    asset_name = ASSET_NAMES.get(idea.asset, idea.asset)

    return (
        f"{asset_emoji} <b>{asset_name}</b> — {direction_emoji} <b>{idea.direction}</b>\n"
        f"⏱ Timeframe: <code>{_h(idea.timeframe)}</code>\n"
        f"🎯 Entry: <code>{_h(idea.entry)}</code>\n"
        f"🛑 Stop Loss: <code>{_h(idea.stop_loss)}</code>\n"
        f"✅ Take Profit: <code>{_h(idea.take_profit)}</code>\n"
        f"⚖️ R:R Ratio: <code>{_h(idea.rr_ratio)}</code>\n"
        f"💡 <i>{_h(idea.reasoning)}</i>"
    )


def format_all_ideas(ideas: list[Idea]) -> list[str]:
    if not ideas:
        return ["⚠️ No trading ideas available yet. Check back after 07:30 UTC."]

    header = "💡 <b>Today's Trading Ideas</b>\n\n"
    cards = [f"<b>Idea {i + 1}</b>\n{format_idea(idea)}" for i, idea in enumerate(ideas)]
    body = ("\n\n" + "─" * 20 + "\n\n").join(cards)
    return _split_message(header + body)


# ---- Broadcast --------------------------------------------------------

def format_broadcast(brief: Brief, ideas: list[Idea]) -> list[str]:
    messages = []
    messages.extend(format_brief(brief))
    messages.extend(format_all_ideas(ideas))
    return messages


# ---- Admin stats ------------------------------------------------------

def format_admin_stats(stats: dict) -> str:
    total = stats.get("total", 0)
    tp_hit = stats.get("tp_hit", 0)
    sl_hit = stats.get("sl_hit", 0)
    open_count = stats.get("open", 0)
    win_rate = stats.get("win_rate", 0.0)
    by_asset = stats.get("by_asset", {})
    closed = tp_hit + sl_hit

    lines = [
        "🔐 <b>Admin — Trading Ideas Performance</b>\n",
        f"📊 Total ideas: <b>{total}</b>",
        f"✅ TP Hit: <b>{tp_hit}</b>   🛑 SL Hit: <b>{sl_hit}</b>   🔄 Open: <b>{open_count}</b>",
        f"🏆 Win rate: <b>{win_rate}%</b>  ({tp_hit}/{closed} closed)\n",
        "<b>By asset:</b>",
    ]

    for asset in sorted(by_asset):
        s = by_asset[asset]
        emoji = ASSET_EMOJI.get(asset, "📌")
        name = ASSET_NAMES.get(asset, asset)
        asset_closed = s["tp"] + s["sl"]
        wr = f"{round(s['tp'] / asset_closed * 100)}%" if asset_closed > 0 else "—"
        lines.append(f"{emoji} {name}: ✅{s['tp']} 🛑{s['sl']} 🔄{s['open']}  WR {wr}")

    return "\n".join(lines)


# ---- Utility ----------------------------------------------------------

def _split_message(text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while len(text) > max_len:
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
