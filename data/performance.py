"""Check open trading ideas against current prices and update results."""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import supabase as db
from db.models import Idea

logger = logging.getLogger(__name__)

# How long each timeframe order stays valid before expiring
TIMEFRAME_EXPIRY: dict[str, timedelta] = {
    "scalp": timedelta(hours=1),
    "intraday": timedelta(days=1),
    "swing": timedelta(days=7),
    "position": timedelta(days=28),
}


def _parse_price(s: str) -> Optional[float]:
    """Parse price strings like '1.0850', '2,500', '$95.50' → float."""
    cleaned = re.sub(r"[^\d.]", "", s.replace(",", ""))
    try:
        v = float(cleaned)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_entry_best(entry_str: str, direction: str) -> Optional[float]:
    """Parse entry range and return the most favourable price for the direction.

    For LONG: buy at the lower price (cheaper entry = better).
    For SHORT: sell at the higher price (more expensive = better).
    Single price: return as-is.
    """
    # Split on dash that is surrounded by digits (avoids splitting negative numbers)
    # e.g. "2185-2190" → ["2185", "2190"], "1.0850-1.0870" → ["1.0850", "1.0870"]
    parts = re.split(r"(?<=\d)-(?=\d)", entry_str.strip())
    prices = [_parse_price(p) for p in parts]
    prices = [p for p in prices if p is not None]

    if len(prices) == 2:
        low, high = min(prices), max(prices)
        return low if direction == "LONG" else high
    elif len(prices) == 1:
        return prices[0]
    return None


async def _check_idea(idea: Idea) -> None:
    """Compare current price to SL/TP; expire if past timeframe window."""
    from data.prices import fetch_price

    if idea.id is None:
        return

    sl = _parse_price(idea.stop_loss)
    tp = _parse_price(idea.take_profit)

    if not all([sl, tp]):
        logger.warning(
            "Could not parse prices for idea %s: sl=%s tp=%s",
            idea.id, idea.stop_loss, idea.take_profit,
        )
        return

    # --- Expiry check ---
    if idea.created_at:
        expiry_delta = TIMEFRAME_EXPIRY.get(idea.timeframe.lower())
        if expiry_delta:
            created = idea.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > created + expiry_delta:
                logger.info(
                    "Idea %s %s %s EXPIRED (timeframe=%s, created=%s)",
                    idea.id, idea.asset, idea.direction, idea.timeframe, created,
                )
                db.update_idea_result(idea.id, "EXPIRED", 0.0)
                return

    price_record = await fetch_price(idea.asset, force=True)
    if not price_record:
        logger.warning("Could not fetch price for %s (idea %s)", idea.asset, idea.id)
        return

    current = price_record.price
    result: Optional[str] = None

    if idea.direction == "LONG":
        if current >= tp:
            result = "TP_HIT"
        elif current <= sl:
            result = "SL_HIT"
    elif idea.direction == "SHORT":
        if current <= tp:
            result = "TP_HIT"
        elif current >= sl:
            result = "SL_HIT"

    if result:
        logger.info(
            "Idea %s %s %s → %s (price=%.5g)",
            idea.id, idea.asset, idea.direction, result, current,
        )
        db.update_idea_result(idea.id, result, current)
    else:
        logger.debug(
            "Idea %s %s %s still OPEN (price=%.5g)",
            idea.id, idea.asset, idea.direction, current,
        )


async def run_performance_checks() -> None:
    """Fetch all open ideas and update results where SL/TP has been hit or idea expired."""
    open_ideas = db.get_open_ideas()
    if not open_ideas:
        logger.info("[perf] No open ideas to check")
        return

    logger.info("[perf] Checking %d open idea(s)", len(open_ideas))
    for idea in open_ideas:
        try:
            await _check_idea(idea)
        except Exception as exc:
            logger.error("[perf] Error checking idea %s: %s", getattr(idea, "id", "?"), exc)
