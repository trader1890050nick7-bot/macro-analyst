"""Supabase client and all CRUD helpers used across the project."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY, CACHE_TTL_MINUTES
from db.models import User, PriceRecord, NewsItem, Sentiment, Brief, Idea

# ---- singleton client -------------------------------------------------

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ---- users ------------------------------------------------------------

def upsert_user(telegram_id: int, subscribed: bool = True) -> None:
    get_client().table("users").upsert(
        {"telegram_id": telegram_id, "subscribed": subscribed}
    ).execute()


def get_subscribed_users() -> list[int]:
    response = (
        get_client()
        .table("users")
        .select("telegram_id")
        .eq("subscribed", True)
        .execute()
    )
    return [row["telegram_id"] for row in (response.data or [])]


def get_subscribed_users_with_language() -> list[tuple[int, str]]:
    """Return (telegram_id, language) for users with an active paid subscription."""
    now_iso = datetime.now(timezone.utc).isoformat()
    response = (
        get_client()
        .table("users")
        .select("telegram_id, language")
        .gt("subscription_expires_at", now_iso)
        .execute()
    )
    return [
        (row["telegram_id"], row.get("language") or "en")
        for row in (response.data or [])
    ]


# ---- subscriptions ----------------------------------------------------

def is_premium(telegram_id: int) -> bool:
    """Return True if user has an active paid subscription."""
    response = (
        get_client()
        .table("users")
        .select("subscription_expires_at")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return False
    raw = response.data[0].get("subscription_expires_at")
    if not raw:
        return False
    expires = datetime.fromisoformat(raw)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def get_subscription_expiry(telegram_id: int) -> Optional[datetime]:
    """Return subscription expiry datetime, or None if not subscribed."""
    response = (
        get_client()
        .table("users")
        .select("subscription_expires_at")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    raw = response.data[0].get("subscription_expires_at")
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def activate_subscription(telegram_id: int, days: int = 30) -> datetime:
    """Extend or activate subscription by `days`. Returns new expiry datetime."""
    now = datetime.now(timezone.utc)
    current = get_subscription_expiry(telegram_id)
    base = current if (current and current > now) else now
    new_expiry = base + timedelta(days=days)
    get_client().table("users").update(
        {"subscription_expires_at": new_expiry.isoformat()}
    ).eq("telegram_id", telegram_id).execute()
    return new_expiry


# ---- payments ---------------------------------------------------------

def save_payment(
    telegram_id: int,
    nowpayments_id: str,
    payment_address: str,
    pay_amount: float,
    price_amount: float = 19.0,
) -> None:
    get_client().table("payments").insert({
        "telegram_id": telegram_id,
        "nowpayments_id": nowpayments_id,
        "payment_address": payment_address,
        "pay_amount": pay_amount,
        "price_amount": price_amount,
        "status": "waiting",
    }).execute()


def get_payment_by_nowpayments_id(nowpayments_id: str) -> Optional[dict]:
    response = (
        get_client()
        .table("payments")
        .select("*")
        .eq("nowpayments_id", nowpayments_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def update_payment_status(nowpayments_id: str, status: str) -> None:
    get_client().table("payments").update({"status": status}).eq(
        "nowpayments_id", nowpayments_id
    ).execute()


def get_user_language(telegram_id: int) -> str:
    response = (
        get_client()
        .table("users")
        .select("language")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0].get("language") or "en"
    return "en"


def update_user_language(telegram_id: int, language: str) -> None:
    get_client().table("users").update({"language": language}).eq("telegram_id", telegram_id).execute()


def check_and_increment_lang_change(telegram_id: int, limit: int = 3) -> bool:
    """Return True if language change is allowed, and increment counter. False if limit reached."""
    now = datetime.now(timezone.utc)
    response = (
        get_client()
        .table("users")
        .select("lang_changes_today, lang_changes_reset")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return True  # new user, allow

    row = response.data[0]
    count = row.get("lang_changes_today") or 0
    reset_raw = row.get("lang_changes_reset")
    reset_at = datetime.fromisoformat(reset_raw) if reset_raw else now

    # Reset counter if 24 hours have passed
    if (now - reset_at) >= timedelta(hours=24):
        count = 0
        reset_at = now

    if count >= limit:
        return False

    get_client().table("users").update({
        "lang_changes_today": count + 1,
        "lang_changes_reset": reset_at.isoformat(),
    }).eq("telegram_id", telegram_id).execute()
    return True


# ---- prices -----------------------------------------------------------

def save_price(record: PriceRecord) -> None:
    get_client().table("prices").insert(record.model_dump(exclude={"created_at"})).execute()


def get_latest_price(asset: str) -> Optional[PriceRecord]:
    response = (
        get_client()
        .table("prices")
        .select("*")
        .eq("asset", asset)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    row = response.data[0]
    return PriceRecord(**row)


def get_day_open_prices() -> dict:
    """Return the first price record saved today (UTC) for each asset.

    The 00:01 UTC job saves these; they serve as the day-open reference for
    calculating % change in the evening brief.
    """
    from config import ASSETS

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    results: dict = {}
    for asset_key in ASSETS:
        response = (
            get_client()
            .table("prices")
            .select("*")
            .eq("asset", asset_key)
            .gte("created_at", start_of_day.isoformat())
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        results[asset_key] = PriceRecord(**response.data[0]) if response.data else None
    return results


def is_price_fresh(asset: str) -> bool:
    """Return True if a price record exists that is younger than CACHE_TTL_MINUTES."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
    response = (
        get_client()
        .table("prices")
        .select("id")
        .eq("asset", asset)
        .gte("created_at", cutoff.isoformat())
        .limit(1)
        .execute()
    )
    return bool(response.data)


# ---- news -------------------------------------------------------------

def save_news(items: list[NewsItem]) -> None:
    if not items:
        return
    rows = [item.model_dump(exclude={"created_at"}) for item in items]
    get_client().table("news").insert(rows).execute()


def get_recent_news(asset: str, limit: int = 10) -> list[NewsItem]:
    response = (
        get_client()
        .table("news")
        .select("*")
        .eq("asset", asset)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [NewsItem(**row) for row in (response.data or [])]


def is_news_fresh(asset: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
    response = (
        get_client()
        .table("news")
        .select("id")
        .eq("asset", asset)
        .gte("created_at", cutoff.isoformat())
        .limit(1)
        .execute()
    )
    return bool(response.data)


# ---- sentiments -------------------------------------------------------

def save_sentiment(s: Sentiment) -> None:
    get_client().table("sentiments").insert(s.model_dump(exclude={"created_at"})).execute()


def get_latest_sentiments() -> list[Sentiment]:
    """Return the most recent sentiment for each asset."""
    from config import ASSETS

    results: list[Sentiment] = []
    for asset_key in ASSETS:
        response = (
            get_client()
            .table("sentiments")
            .select("*")
            .eq("asset", asset_key)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            results.append(Sentiment(**response.data[0]))
    return results


def get_all_sentiments_today() -> list[Sentiment]:
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    response = (
        get_client()
        .table("sentiments")
        .select("*")
        .gte("created_at", start_of_day.isoformat())
        .order("created_at", desc=True)
        .execute()
    )
    return [Sentiment(**row) for row in (response.data or [])]


# ---- briefs -----------------------------------------------------------

def save_brief(brief: Brief) -> None:
    get_client().table("briefs").insert({"content": brief.content}).execute()


def claim_brief_for_broadcast(brief_id: int) -> bool:
    """Atomically mark brief as broadcast_sent=True. Returns True only for the first caller."""
    result = (
        get_client()
        .table("briefs")
        .update({"broadcast_sent": True})
        .eq("id", brief_id)
        .eq("broadcast_sent", False)
        .execute()
    )
    return bool(result.data)


def get_latest_brief() -> Optional[Brief]:
    response = (
        get_client()
        .table("briefs")
        .select("*")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    return Brief(**response.data[0])


# ---- ideas ------------------------------------------------------------

def save_ideas(ideas: list[Idea]) -> None:
    rows = [idea.model_dump(exclude={"created_at", "id", "result_price", "checked_at"}) for idea in ideas]
    get_client().table("ideas").insert(rows).execute()


def get_open_ideas() -> list[Idea]:
    """Return all ideas with result='OPEN'."""
    response = (
        get_client()
        .table("ideas")
        .select("*")
        .eq("result", "OPEN")
        .order("created_at", desc=False)
        .execute()
    )
    return [Idea(**row) for row in (response.data or [])]


def update_idea_result(idea_id: int, result: str, result_price: float) -> None:
    get_client().table("ideas").update({
        "result": result,
        "result_price": result_price,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", idea_id).execute()


def get_performance_stats() -> dict:
    """Return aggregated performance stats for ideas since STATS_START_DATE, with P&L."""
    import re
    from collections import defaultdict
    from datetime import date

    # Track stats starting from this date
    STATS_START_DATE = "2026-03-19"

    # Position sizes in base units per asset (MetaTrader lot × contract size)
    LOT_SIZES: dict[str, float] = {
        "XAUUSD": 1.0,      # 100 oz/lot × 0.01 lot
        "SPX":    0.5,      # 50 contracts/lot × 0.01 lot
        "EURUSD": 3000.0,   # 100,000 EUR/lot × 0.03 lot
        "BTC":    0.06,     # 1 BTC/lot × 0.06 lot
        "BRENT":  50.0,     # 1,000 bbl/lot × 0.05 lot
    }

    def _parse_price(s: str) -> float | None:
        cleaned = re.sub(r"[^\d.]", "", str(s).replace(",", ""))
        try:
            v = float(cleaned)
            return v if v > 0 else None
        except (ValueError, TypeError):
            return None

    def _best_entry(entry_str: str, direction: str) -> float | None:
        parts = re.split(r"(?<=\d)-(?=\d)", str(entry_str).strip())
        prices = [_parse_price(p) for p in parts]
        prices = [p for p in prices if p is not None]
        if len(prices) == 2:
            low, high = min(prices), max(prices)
            return low if direction == "LONG" else high
        elif len(prices) == 1:
            return prices[0]
        return None

    response = (
        get_client()
        .table("ideas")
        .select("*")
        .gte("created_at", STATS_START_DATE)
        .order("created_at", desc=False)
        .execute()
    )
    ideas = response.data or []

    total = len(ideas)
    tp_hit = sum(1 for i in ideas if i.get("result") == "TP_HIT")
    sl_hit = sum(1 for i in ideas if i.get("result") == "SL_HIT")
    expired = sum(1 for i in ideas if i.get("result") == "EXPIRED")
    open_count = sum(1 for i in ideas if i.get("result") in ("OPEN", None))
    closed = tp_hit + sl_hit
    win_rate = round(tp_hit / closed * 100, 1) if closed > 0 else 0.0

    by_asset: dict = defaultdict(lambda: {
        "total": 0, "tp": 0, "sl": 0, "open": 0, "expired": 0, "pnl": 0.0,
        "trades": [],
    })

    equity_trades: list[dict] = []  # for overall equity curve

    for idea in ideas:
        asset = idea.get("asset", "UNKNOWN")
        result = idea.get("result", "OPEN")
        by_asset[asset]["total"] += 1

        if result == "TP_HIT":
            by_asset[asset]["tp"] += 1
        elif result == "SL_HIT":
            by_asset[asset]["sl"] += 1
        elif result == "EXPIRED":
            by_asset[asset]["expired"] += 1
        else:
            by_asset[asset]["open"] += 1

        # P&L for closed trades
        if result in ("TP_HIT", "SL_HIT"):
            result_price = idea.get("result_price")
            entry_str = idea.get("entry", "")
            direction = idea.get("direction", "LONG")
            lot_size = LOT_SIZES.get(asset, 1.0)

            entry_price = _best_entry(entry_str, direction)
            r_price = _parse_price(str(result_price)) if result_price is not None else None

            if entry_price and r_price:
                if direction == "LONG":
                    pnl = lot_size * (r_price - entry_price)
                else:
                    pnl = lot_size * (entry_price - r_price)

                by_asset[asset]["pnl"] += pnl
                by_asset[asset]["trades"].append({
                    "created_at": idea.get("created_at"),
                    "result": result,
                    "pnl": pnl,
                })
                equity_trades.append({
                    "asset": asset,
                    "created_at": idea.get("created_at"),
                    "result": result,
                    "pnl": pnl,
                })

    # Sort equity trades by time
    equity_trades.sort(key=lambda x: x.get("created_at") or "")

    total_pnl = sum(t["pnl"] for t in equity_trades)

    return {
        "total": total,
        "tp_hit": tp_hit,
        "sl_hit": sl_hit,
        "expired": expired,
        "open": open_count,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "by_asset": {k: dict(v) for k, v in by_asset.items()},
        "equity_trades": equity_trades,
        "stats_start": STATS_START_DATE,
    }


# ---- translation cache ------------------------------------------------

TRANSLATION_CACHE_TTL_HOURS = 3


def get_cached_translation(cache_key: str) -> Optional[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TRANSLATION_CACHE_TTL_HOURS)
    response = (
        get_client()
        .table("translation_cache")
        .select("translated")
        .eq("cache_key", cache_key)
        .gte("created_at", cutoff.isoformat())
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["translated"]
    return None


def save_cached_translation(cache_key: str, translated: str) -> None:
    get_client().table("translation_cache").upsert({
        "cache_key": cache_key,
        "translated": translated,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def get_latest_ideas() -> list[Idea]:
    """Return today's trading ideas (up to 3)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    response = (
        get_client()
        .table("ideas")
        .select("*")
        .gte("created_at", start_of_day.isoformat())
        .order("created_at", desc=True)
        .limit(3)
        .execute()
    )
    return [Idea(**row) for row in (response.data or [])]
