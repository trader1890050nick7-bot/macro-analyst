"""Per-asset sentiment analysis via Claude API.

Runs every 30 minutes. Input: last 10 headlines + current price + 24h change %.
Output JSON: { asset, sentiment, score, reasoning }
"""

import json
import logging
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, ASSETS
from db.models import Sentiment, PriceRecord, NewsItem

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SENTIMENT_SYSTEM = """You are a professional macro market analyst with expertise in FX, commodities, equities, and crypto markets. Analyze market sentiment based on recent news and price action."""

SENTIMENT_PROMPT_TEMPLATE = """Analyze the market sentiment for {asset_name} based on the following data:

**Current Price:** {price}
**24h Change:** {change_24h:+.3f}%

**Recent Headlines (last 10):**
{headlines}

Return ONLY a valid JSON object with this exact structure:
{{
  "asset": "{asset_key}",
  "sentiment": "<bullish|bearish|neutral>",
  "score": <integer 0-100, where 0=extremely bearish, 50=neutral, 100=extremely bullish>,
  "reasoning": "<two sentences max explaining the sentiment>"
}}

No additional text, only the JSON object."""


async def analyze_sentiment(
    asset: str,
    price_record: Optional[PriceRecord],
    news_items: list[NewsItem],
) -> Optional[Sentiment]:
    """Call Claude to analyze sentiment for a single asset."""
    asset_cfg = ASSETS.get(asset)
    if not asset_cfg:
        logger.error("Unknown asset: %s", asset)
        return None

    price_str = f"{price_record.price}" if price_record else "N/A"
    change_str = price_record.change_24h if price_record else 0.0

    headlines = "\n".join(
        f"{i + 1}. {item.title}" for i, item in enumerate(news_items[:10])
    ) or "No recent headlines available."

    prompt = SENTIMENT_PROMPT_TEMPLATE.format(
        asset_name=asset_cfg["name"],
        asset_key=asset,
        price=price_str,
        change_24h=change_str,
        headlines=headlines,
    )

    try:
        with _get_client().messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=SENTIMENT_SYSTEM,
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
        return Sentiment(
            asset=data["asset"],
            sentiment=data["sentiment"].lower(),
            score=int(data["score"]),
            reasoning=data["reasoning"],
        )

    except json.JSONDecodeError as exc:
        logger.error("JSON parse error for %s sentiment: %s", asset, exc)
        return None
    except anthropic.BadRequestError as exc:
        logger.error("Bad request to Claude for %s: %s", asset, exc)
        return None
    except anthropic.RateLimitError:
        logger.warning("Claude rate limited during sentiment analysis for %s", asset)
        return None
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error for %s: %s %s", asset, exc.status_code, exc.message)
        return None


async def analyze_all_sentiments(
    prices: dict,
    news: dict,
) -> list[Sentiment]:
    """Analyze sentiment for all assets and save results to DB."""
    import asyncio
    from db import supabase as db

    async def _analyze_and_save(asset: str) -> Optional[Sentiment]:
        price_record = prices.get(asset)
        news_items = news.get(asset, [])
        result = await analyze_sentiment(asset, price_record, news_items)
        if result:
            db.save_sentiment(result)
        return result

    tasks = [asyncio.create_task(_analyze_and_save(asset)) for asset in ASSETS]
    results = await asyncio.gather(*tasks)
    return [s for s in results if s is not None]
