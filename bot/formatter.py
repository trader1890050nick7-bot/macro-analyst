"""Format data into Telegram-friendly HTML messages (≤4096 chars each)."""

from db.models import Sentiment, Brief, Idea

TELEGRAM_MAX = 3500

SENTIMENT_EMOJI = {
    "bullish": "🟢",
    "bearish": "🔴",
    "neutral": "🟡",
}

DIRECTION_EMOJI = {
    "LONG": "📈",
    "SHORT": "📉",
}

TIMEFRAME_LABELS = {
    "scalp": "scalp (1-60 мин)",
    "intraday": "intraday (1 день)",
    "swing": "swing (2-7 дней)",
    "position": "position (1-4 недели)",
}


ASSET_EMOJI = {
    "EURUSD": "💱",
    "XAUUSD": "🥇",
    "BRENT": "🛢️",
    "SPX": "📊",  # E-Mini S&P 500 Futures
    "BTC": "₿",
}

ASSET_NAMES = {
    "EURUSD": "EUR/USD · EURUSD",
    "XAUUSD": "Gold · XAUUSD",
    "BRENT": "Brent Crude · CL",
    "SPX": "E-Mini S&amp;P 500 Futures · ES",
    "BTC": "Bitcoin · BTCUSD",
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
        "📅 Broadcast Mon–Fri at 19:20 UTC (GMT)"
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
        "• 19:15 — Daily macro brief generated\n"
        "• 19:16 — Trading ideas generated\n"
        "• 19:20 — Brief &amp; ideas delivered to subscribers\n\n"
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
    content = brief.content.replace("**", "")
    return _split_message(header + _h(content))


# ---- Trading ideas ----------------------------------------------------

def format_idea(idea: Idea) -> str:
    direction_emoji = DIRECTION_EMOJI.get(idea.direction, "➡️")
    asset_emoji = ASSET_EMOJI.get(idea.asset, "📌")
    asset_name = ASSET_NAMES.get(idea.asset, idea.asset)

    return (
        f"{asset_emoji} <b>{asset_name}</b> — {direction_emoji} <b>{idea.direction}</b>\n"
        f"⏱ Timeframe: <code>{_h(TIMEFRAME_LABELS.get(idea.timeframe.lower(), idea.timeframe))}</code>\n"
        f"🎯 Entry: <code>{_h(idea.entry)}</code>\n"
        f"🛑 Stop Loss: <code>{_h(idea.stop_loss)}</code>\n"
        f"✅ Take Profit: <code>{_h(idea.take_profit)}</code>\n"
        f"⚖️ Risk/Reward Ratio: <code>{_h(idea.rr_ratio)}</code>\n"
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
    expired = stats.get("expired", 0)
    open_count = stats.get("open", 0)
    win_rate = stats.get("win_rate", 0.0)
    total_pnl = stats.get("total_pnl", 0.0)
    by_asset = stats.get("by_asset", {})
    stats_start = stats.get("stats_start", "2026-03-19")
    closed = tp_hit + sl_hit

    starting = 50_000.0
    equity = starting + total_pnl
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"

    lines = [
        "🔐 <b>Admin — Trading Ideas Performance</b>",
        f"📅 Since: <b>{stats_start}</b>\n",
        f"📊 Total ideas: <b>{total}</b>",
        f"✅ TP Hit: <b>{tp_hit}</b>   🛑 SL Hit: <b>{sl_hit}</b>   ⏰ Expired: <b>{expired}</b>   🔄 Open: <b>{open_count}</b>",
        f"🏆 Win rate: <b>{win_rate}%</b>  ({tp_hit}/{closed} closed)\n",
        f"💰 <b>P&amp;L (MetaTrader lots, $50k start)</b>",
        f"{pnl_emoji} Total P&amp;L: <b>{pnl_sign}${total_pnl:,.2f}</b>",
        f"📊 Equity: <b>${equity:,.2f}</b>\n",
        "<b>By asset:</b>",
    ]

    for asset in sorted(by_asset):
        s = by_asset[asset]
        emoji = ASSET_EMOJI.get(asset, "📌")
        name = ASSET_NAMES.get(asset, asset)
        asset_closed = s.get("tp", 0) + s.get("sl", 0)
        wr = f"{round(s['tp'] / asset_closed * 100)}%" if asset_closed > 0 else "—"
        asset_pnl = s.get("pnl", 0.0)
        pnl_s = "+" if asset_pnl >= 0 else ""
        lines.append(
            f"{emoji} {name}: ✅{s.get('tp',0)} 🛑{s.get('sl',0)} "
            f"⏰{s.get('expired',0)} 🔄{s.get('open',0)}  "
            f"WR {wr}  P&amp;L: <b>{pnl_s}${asset_pnl:,.2f}</b>"
        )

    lines.append("\n📊 <i>Charts attached below</i>")
    return "\n".join(lines)


# ---- Utility ----------------------------------------------------------

def _safe_split_point(text: str, pos: int) -> int:
    """Back pos up to before any unclosed HTML tag at the split boundary."""
    tag_start = text.rfind("<", 0, pos)
    if tag_start != -1 and ">" not in text[tag_start:pos]:
        return tag_start
    return pos


def _split_message(text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while len(text) > max_len:
        # Prefer splitting at a paragraph break, then a line break
        split_at = text.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        # Ensure we never cut inside an HTML tag
        split_at = _safe_split_point(text, split_at)
        if split_at == 0:
            # Fallback: no safe split found, hard-cut at max_len outside any tag
            split_at = _safe_split_point(text, max_len)
            if split_at == 0:
                split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks
