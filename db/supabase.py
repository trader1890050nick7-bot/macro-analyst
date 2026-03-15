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
    response = (
        get_client()
        .table("users")
        .select("telegram_id, language")
        .eq("subscribed", True)
        .execute()
    )
    return [
        (row["telegram_id"], row.get("language") or "en")
        for row in (response.data or [])
    ]


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
    """Return aggregated performance stats across all ideas."""
    from collections import defaultdict

    response = get_client().table("ideas").select("*").execute()
    ideas = response.data or []

    total = len(ideas)
    tp_hit = sum(1 for i in ideas if i.get("result") == "TP_HIT")
    sl_hit = sum(1 for i in ideas if i.get("result") == "SL_HIT")
    open_count = sum(1 for i in ideas if i.get("result", "OPEN") == "OPEN")
    closed = tp_hit + sl_hit
    win_rate = round(tp_hit / closed * 100, 1) if closed > 0 else 0.0

    by_asset: dict = defaultdict(lambda: {"total": 0, "tp": 0, "sl": 0, "open": 0})
    for idea in ideas:
        asset = idea.get("asset", "UNKNOWN")
        by_asset[asset]["total"] += 1
        res = idea.get("result", "OPEN")
        if res == "TP_HIT":
            by_asset[asset]["tp"] += 1
        elif res == "SL_HIT":
            by_asset[asset]["sl"] += 1
        else:
            by_asset[asset]["open"] += 1

    return {
        "total": total,
        "tp_hit": tp_hit,
        "sl_hit": sl_hit,
        "open": open_count,
        "win_rate": win_rate,
        "by_asset": dict(by_asset),
    }


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
