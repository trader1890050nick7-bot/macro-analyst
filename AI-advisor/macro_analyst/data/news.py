"""Fetch recent news headlines for each asset via NewsAPI.org."""

import logging
from typing import Optional

import httpx

from config import NEWS_API_KEY, ASSETS
from db.models import NewsItem
from db import supabase as db

logger = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2/everything"


async def _fetch_headlines(query: str, page_size: int = 10) -> list[dict]:
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "language": "en",
        "apiKey": NEWS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(NEWSAPI_BASE, params=params)
        r.raise_for_status()
        data = r.json()
    return data.get("articles", [])


async def fetch_news_for_asset(
    asset: str, force: bool = False
) -> list[NewsItem]:
    """Return up to 10 recent headlines for the asset, cached in Supabase."""
    if not force and db.is_news_fresh(asset):
        return db.get_recent_news(asset)

    asset_cfg = ASSETS.get(asset)
    if not asset_cfg:
        logger.error("Unknown asset: %s", asset)
        return []

    try:
        articles = await _fetch_headlines(asset_cfg["news_query"])
    except Exception as exc:
        logger.error("Error fetching news for %s: %s", asset, exc)
        return db.get_recent_news(asset)  # fall back to cached

    items = [
        NewsItem(
            asset=asset,
            title=a.get("title", "").strip(),
            url=a.get("url"),
            published_at=a.get("publishedAt"),
        )
        for a in articles
        if a.get("title") and a.get("title") != "[Removed]"
    ]

    if items:
        db.save_news(items)

    return items


async def fetch_all_news(force: bool = False) -> dict[str, list[NewsItem]]:
    """Fetch news for all 5 assets concurrently."""
    import asyncio

    tasks = {
        asset: asyncio.create_task(fetch_news_for_asset(asset, force))
        for asset in ASSETS
    }
    results = {}
    for asset, task in tasks.items():
        results[asset] = await task
    return results


def get_top_macro_news(hours: int = 12, limit: int = 15) -> list[str]:
    """Aggregate the most recent headlines across all assets from the DB."""
    from datetime import datetime, timedelta, timezone
    from db import supabase as _db

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Query DB directly for recent news across all assets
    client = _db.get_client()
    response = (
        client.table("news")
        .select("title, asset, published_at")
        .gte("created_at", cutoff.isoformat())
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        f"[{row['asset']}] {row['title']}"
        for row in (response.data or [])
    ]
