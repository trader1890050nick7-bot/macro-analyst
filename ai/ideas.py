"""Trading Ideas generator — runs at 07:30 UTC.

Input: daily brief + all 5 sentiment scores + current prices
Output: JSON array of exactly 3 trading ideas.
  One idea must always be BTC or crypto.
"""

import json
import logging
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, ASSETS
from db.models import Idea, Brief, Sentiment, PriceRecord

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


IDEAS_SYSTEM = """You are a professional trading strategist specialising in macro and technical analysis across FX, commodities, indices, and crypto. You generate high-quality, actionable trade setups with precise risk management."""

IDEAS_PROMPT_TEMPLATE = """Based on today's macro brief and market data, generate exactly 3 trading ideas.

**Today's Macro Brief:**
{brief}

**Current Prices and Sentiments:**
{market_data}

**Direction Constraints (MUST be followed):**
{direction_constraints}

Generate exactly 3 trading ideas as a JSON array. Requirements:
- Exactly 3 ideas
- At least 1 idea MUST be for BTC (Bitcoin)
- Entry, stop loss, and take profit MUST be derived from the CURRENT PRICES above — never use levels from your training knowledge
- R:R ratio should be at least 1:1.5
- Never write "SPX" — always write "S&P 500" in reasoning text
- STRICTLY follow the Direction Constraints above — do not generate a direction that contradicts the sentiment
- IMPORTANT: The sentiment scores in "Current Prices and Sentiments" are the authoritative source. If the brief mentions different scores, ignore them and use only the scores from "Current Prices and Sentiments"

Return ONLY a valid JSON array with this exact structure:
[
  {{
    "asset": "<asset_key from: EURUSD, XAUUSD, BRENT, SPX, BTC>",
    "direction": "<LONG|SHORT>",
    "entry": "<price range e.g. 2185-2190>",
    "stop_loss": "<price level>",
    "take_profit": "<price level>",
    "rr_ratio": "<e.g. 1:2.2>",
    "timeframe": "<scalp|intraday|swing|position>",
    "reasoning": "<two sentences max>"
  }}
]

No additional text, only the JSON array."""


def _build_direction_constraints(sentiments: list[Sentiment]) -> str:
    """Return per-asset direction rules based on sentiment scores."""
    lines = []
    for s in sentiments:
        if s.score > 60:
            rule = f"- {s.asset}: LONG only (bullish sentiment, score {s.score}/100)"
        elif s.score < 40:
            rule = f"- {s.asset}: SHORT only (bearish sentiment, score {s.score}/100)"
        else:
            rule = f"- {s.asset}: LONG or SHORT allowed (neutral sentiment, score {s.score}/100)"
        lines.append(rule)
    return "\n".join(lines) if lines else "No constraints — use your discretion."


def _format_market_data(
    sentiments: list[Sentiment],
    prices: dict[str, Optional[PriceRecord]],
) -> str:
    lines = []
    for asset_key in ASSETS:
        asset_name = ASSETS[asset_key]["name"]
        price_rec = prices.get(asset_key)
        price_str = f"{price_rec.price}" if price_rec else "N/A"
        change_str = f"{price_rec.change_24h:+.3f}%" if price_rec else "N/A"

        sentiment = next((s for s in sentiments if s.asset == asset_key), None)
        if sentiment:
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
                sentiment.sentiment, "⚪"
            )
            sentiment_str = f"{emoji} {sentiment.sentiment.upper()} ({sentiment.score}/100)"
        else:
            sentiment_str = "⚪ N/A"

        lines.append(
            f"- {asset_name} ({asset_key}): Price={price_str}, 24h={change_str}, "
            f"Sentiment={sentiment_str}"
        )
    return "\n".join(lines)


async def generate_trading_ideas(
    brief: Brief,
    sentiments: list[Sentiment],
    prices: dict[str, Optional[PriceRecord]],
) -> list[Idea]:
    """Call Claude to generate 3 trading ideas."""
    market_data = _format_market_data(sentiments, prices)
    direction_constraints = _build_direction_constraints(sentiments)

    prompt = IDEAS_PROMPT_TEMPLATE.format(
        brief=brief.content,
        market_data=market_data,
        direction_constraints=direction_constraints,
    )

    try:
        with _get_client().messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=IDEAS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        if not isinstance(data, list):
            logger.error("Expected JSON array from ideas, got: %s", type(data))
            return []

        ideas = []
        for item in data[:3]:
            ideas.append(
                Idea(
                    asset=item["asset"],
                    direction=item["direction"].upper(),
                    entry=str(item["entry"]),
                    stop_loss=str(item["stop_loss"]),
                    take_profit=str(item["take_profit"]),
                    rr_ratio=str(item["rr_ratio"]),
                    timeframe=item["timeframe"],
                    reasoning=item["reasoning"],
                )
            )
        return ideas

    except json.JSONDecodeError as exc:
        logger.error("JSON parse error for trading ideas: %s", exc)
        return []
    except anthropic.RateLimitError:
        logger.warning("Claude rate limited during ideas generation")
        return []
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error during ideas generation: %s %s", exc.status_code, exc.message)
        return []
    except Exception as exc:
        logger.error("Unexpected error during ideas generation: %s", exc)
        return []


async def run_trading_ideas() -> list[Idea]:
    """Orchestrate ideas generation: pull data → generate → save."""
    from db import supabase as db
    from data.prices import fetch_all_prices

    brief = db.get_latest_brief()
    if not brief:
        logger.warning("No brief found — skipping ideas generation")
        return []

    sentiments = db.get_latest_sentiments()
    prices = await fetch_all_prices()

    ideas = await generate_trading_ideas(brief, sentiments, prices)

    if ideas:
        db.save_ideas(ideas)
        logger.info("Saved %d trading ideas", len(ideas))

    return ideas
