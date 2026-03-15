"""Check open trading ideas against current prices and update results."""

import logging
import re
from typing import Optional

from db import supabase as db
from db.models import Idea

logger = logging.getLogger(__name__)


def _parse_price(s: str) -> Optional[float]:
    """Parse price strings like '1.0850', '2,500', '$95.50' → float."""
    cleaned = re.sub(r"[^\d.]", "", s.replace(",", ""))
    try:
        v = float(cleaned)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


async def _check_idea(idea: Idea) -> None:
    """Compare current price to SL/TP and update result if triggered."""
    from data.prices import fetch_price

    if idea.id is None:
        return

    entry = _parse_price(idea.entry)
    sl = _parse_price(idea.stop_loss)
    tp = _parse_price(idea.take_profit)

    if not all([entry, sl, tp]):
        logger.warning(
            "Could not parse prices for idea %s: entry=%s sl=%s tp=%s",
            idea.id, idea.entry, idea.stop_loss, idea.take_profit,
        )
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
    """Fetch all open ideas and update results where SL/TP has been hit."""
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
