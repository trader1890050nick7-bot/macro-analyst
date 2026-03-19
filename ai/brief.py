"""Daily Macro Brief generator — runs at 18:30 UTC.

Input: sentiment of all 5 assets + top macro news since morning (06:00 UTC)
Output: structured text up to 400 words covering:
  - Today's key macro events (morning through market session)
  - Each asset: key levels + bias
  - Overall risk sentiment: Risk-On / Risk-Off / Neutral
"""

import logging
from datetime import date
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from db.models import Brief, Sentiment

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


BRIEF_SYSTEM = """You are a senior macro market strategist writing an end-of-day market brief for professional traders. Your writing is concise, insightful, and actionable. Use precise financial language."""

BRIEF_PROMPT_TEMPLATE = """Today's date is {today_date}. Write the Daily Macro Brief for {today_date} based on the following data.

**Asset Sentiments:**
{sentiment_block}

**Today's Macro News (since morning, {news_hours}h window):**
{news_block}

Write a structured brief covering:
1. **Today's Key Macro Events** — summarise the most important developments that occurred today during the trading session (from morning through now, not overnight)
2. **Asset Analysis** — for each of the 5 assets, state key price levels and directional bias
3. **Overall Risk Sentiment** — conclude with Risk-On / Risk-Off / Neutral and why

Use professional financial language. Be direct and specific. Do NOT use bullet points for the main narrative — use short paragraphs.
IMPORTANT: Keep the total brief under 400 words. Do not exceed 400 words under any circumstances.
IMPORTANT: Do NOT use markdown bold formatting (**text**). Do not wrap asset names or any other text in asterisks.
IMPORTANT: Use the exact asset names and tickers as given in the sentiment data (e.g. "Brent Crude (CL)", "E-Mini S&P 500 Futures (ES)", "Gold (XAUUSD)"). Be consistent — do not switch to alternative names like "crude oil", "WTI", "SPX", "S&P 500", or "XAU" within the same section."""


def _format_sentiments(sentiments: list[Sentiment]) -> str:
    lines = []
    for s in sentiments:
        emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(s.sentiment, "⚪")
        lines.append(
            f"- {s.asset}: {emoji} {s.sentiment.upper()} (score {s.score}/100) — {s.reasoning}"
        )
    return "\n".join(lines) if lines else "No sentiment data available."


async def generate_daily_brief(
    sentiments: list[Sentiment],
    macro_news: list[str],
    news_hours: int = 13,
) -> Optional[Brief]:
    """Call Claude to generate the daily macro brief."""
    sentiment_block = _format_sentiments(sentiments)
    news_block = (
        "\n".join(f"• {headline}" for headline in macro_news[:15])
        or "No recent macro news available."
    )

    today = date.today().strftime("%B %d, %Y")
    prompt = BRIEF_PROMPT_TEMPLATE.format(
        today_date=today,
        sentiment_block=sentiment_block,
        news_block=news_block,
        news_hours=news_hours,
    )

    try:
        with _get_client().messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        content = response.content[0].text.strip()
        # Strip markdown bold markers Claude occasionally inserts
        content = content.replace("**", "")
        return Brief(content=content)

    except anthropic.RateLimitError:
        logger.warning("Claude rate limited during brief generation")
        return None
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error during brief generation: %s %s", exc.status_code, exc.message)
        return None
    except Exception as exc:
        logger.error("Unexpected error during brief generation: %s", exc)
        return None


async def run_daily_brief() -> Optional[Brief]:
    """Orchestrate brief generation: pull data → generate → save."""
    from db import supabase as db
    from data.news import get_top_macro_news

    sentiments = db.get_latest_sentiments()
    if not sentiments:
        logger.warning("No sentiments found — skipping brief generation")
        return None

    # Cover news from 06:00 UTC (morning) to now (~18:30 UTC) = ~13 hours
    from datetime import datetime, timezone as tz
    _now = datetime.now(tz.utc)
    news_hours = max(12, _now.hour - 5)  # at least 12h, covering since ~06:00 UTC
    macro_news = get_top_macro_news(hours=news_hours)
    brief = await generate_daily_brief(sentiments, macro_news, news_hours=news_hours)

    if brief:
        db.save_brief(brief)
        logger.info("Daily brief saved (%d chars)", len(brief.content))

    return brief
