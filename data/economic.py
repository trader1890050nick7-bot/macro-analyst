"""Fetch macro economic calendar events from ForexFactory RSS feed."""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
import feedparser

logger = logging.getLogger(__name__)

FOREXFACTORY_RSS = "https://www.forexfactory.com/ff_calendar_thisweek.xml"
INVESTING_RSS = "https://www.investing.com/rss/news_285.rss"  # economic calendar fallback


async def fetch_economic_events(limit: int = 10) -> list[dict]:
    """
    Fetch upcoming economic calendar events.

    Returns a list of dicts with keys: title, date, impact, currency.
    Falls back to investing.com RSS if ForexFactory is unavailable.
    """
    events = await _fetch_forexfactory(limit)
    if not events:
        events = await _fetch_investing_rss(limit)
    return events


async def _fetch_forexfactory(limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; MacroAnalystBot/1.0)"
                )
            }
            r = await client.get(FOREXFACTORY_RSS, headers=headers)
            r.raise_for_status()
            content = r.text
    except Exception as exc:
        logger.warning("ForexFactory RSS unavailable: %s", exc)
        return []

    feed = feedparser.parse(content)
    events = []
    for entry in feed.entries[:limit]:
        events.append(
            {
                "title": entry.get("title", "Unknown event"),
                "date": entry.get("published", ""),
                "impact": _extract_impact(entry),
                "currency": _extract_currency(entry),
            }
        )
    return events


async def _fetch_investing_rss(limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(INVESTING_RSS)
            r.raise_for_status()
            content = r.text
    except Exception as exc:
        logger.warning("Investing.com RSS unavailable: %s", exc)
        return []

    feed = feedparser.parse(content)
    events = []
    for entry in feed.entries[:limit]:
        events.append(
            {
                "title": entry.get("title", "Unknown event"),
                "date": entry.get("published", ""),
                "impact": "medium",
                "currency": "USD",
            }
        )
    return events


def _extract_impact(entry) -> str:
    summary = entry.get("summary", "").lower()
    if "high" in summary or "⚠" in summary:
        return "high"
    if "medium" in summary or "med" in summary:
        return "medium"
    return "low"


def _extract_currency(entry) -> str:
    title = entry.get("title", "")
    # Simple heuristic — look for common currency codes in the title
    for ccy in ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY"]:
        if ccy in title.upper():
            return ccy
    return "USD"


def format_events_for_prompt(events: list[dict]) -> str:
    if not events:
        return "No major economic events found."
    lines = []
    for e in events:
        impact_label = {"high": "🔴 HIGH", "medium": "🟡 MED", "low": "⚪ LOW"}.get(
            e["impact"], "⚪ LOW"
        )
        lines.append(f"- {impact_label} | {e['currency']} | {e['title']} | {e['date']}")
    return "\n".join(lines)
