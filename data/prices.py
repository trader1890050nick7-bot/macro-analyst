"""Fetch current prices for all 5 assets.

Sources:
- Alpha Vantage: EUR/USD (FX), Gold XAU/USD (FX), Brent Crude (commodity),
  S&P 500 / SPY (equity quote)
- CoinGecko (free, no key): Bitcoin BTC
"""

import logging
from typing import Optional

import httpx

from config import ALPHA_VANTAGE_API_KEY, ASSETS
from db.models import PriceRecord
from db import supabase as db

logger = logging.getLogger(__name__)

AV_BASE = "https://www.alphavantage.co/query"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


# ---- helpers ----------------------------------------------------------

async def _av_get(params: dict) -> dict:
    params["apikey"] = ALPHA_VANTAGE_API_KEY
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(AV_BASE, params=params)
        r.raise_for_status()
        return r.json()


async def _fetch_eurusd() -> Optional[PriceRecord]:
    data = await _av_get(
        {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": "EUR", "to_currency": "USD"}
    )
    info = data.get("Realtime Currency Exchange Rate", {})
    price = float(info.get("5. Exchange Rate", 0))
    if not price:
        return None
    # Alpha Vantage exchange rate endpoint doesn't give 24h change directly;
    # compute via daily series for a rough 24h change
    daily = await _av_get(
        {"function": "FX_DAILY", "from_symbol": "EUR", "to_symbol": "USD", "outputsize": "compact"}
    )
    series = daily.get("Time Series FX (Daily)", {})
    dates = sorted(series.keys(), reverse=True)
    if len(dates) >= 2:
        prev_close = float(series[dates[1]]["4. close"])
        change_24h = ((price - prev_close) / prev_close) * 100
    else:
        change_24h = 0.0
    return PriceRecord(asset="EURUSD", price=round(price, 5), change_24h=round(change_24h, 3))


async def _fetch_gold() -> Optional[PriceRecord]:
    # XAU/USD is treated as a currency pair by Alpha Vantage
    data = await _av_get(
        {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": "XAU", "to_currency": "USD"}
    )
    info = data.get("Realtime Currency Exchange Rate", {})
    price = float(info.get("5. Exchange Rate", 0))
    if not price:
        return None
    daily = await _av_get(
        {"function": "FX_DAILY", "from_symbol": "XAU", "to_symbol": "USD", "outputsize": "compact"}
    )
    series = daily.get("Time Series FX (Daily)", {})
    dates = sorted(series.keys(), reverse=True)
    if len(dates) >= 2:
        prev_close = float(series[dates[1]]["4. close"])
        change_24h = ((price - prev_close) / prev_close) * 100
    else:
        change_24h = 0.0
    return PriceRecord(asset="XAUUSD", price=round(price, 2), change_24h=round(change_24h, 3))


async def _fetch_brent() -> Optional[PriceRecord]:
    data = await _av_get({"function": "BRENT", "interval": "daily"})
    series = data.get("data", [])
    if len(series) < 2:
        return None
    price = float(series[0]["value"])
    prev_price = float(series[1]["value"])
    change_24h = ((price - prev_price) / prev_price) * 100
    return PriceRecord(asset="BRENT", price=round(price, 2), change_24h=round(change_24h, 3))


async def _fetch_spx() -> Optional[PriceRecord]:
    # SPY ETF ≈ S&P 500 / 10 — multiply by 10 to get the index / ES futures level
    data = await _av_get({"function": "GLOBAL_QUOTE", "symbol": "SPY"})
    quote = data.get("Global Quote", {})
    spy_price = float(quote.get("05. price", 0))
    change_pct = float(quote.get("10. change percent", "0%").replace("%", ""))
    if not spy_price:
        return None
    index_price = round(spy_price * 10, 0)
    return PriceRecord(asset="SPX", price=index_price, change_24h=round(change_pct, 3))


async def _fetch_btc() -> Optional[PriceRecord]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
        )
        r.raise_for_status()
        data = r.json()
    btc = data.get("bitcoin", {})
    price = btc.get("usd", 0)
    change_24h = btc.get("usd_24h_change", 0)
    if not price:
        return None
    return PriceRecord(asset="BTC", price=round(price, 2), change_24h=round(change_24h, 3))


# ---- public API -------------------------------------------------------

_FETCHERS = {
    "EURUSD": _fetch_eurusd,
    "XAUUSD": _fetch_gold,
    "BRENT": _fetch_brent,
    "SPX": _fetch_spx,
    "BTC": _fetch_btc,
}


async def fetch_price(asset: str, force: bool = False) -> Optional[PriceRecord]:
    """Fetch price for a single asset, using Supabase cache unless force=True."""
    if not force and db.is_price_fresh(asset):
        return db.get_latest_price(asset)

    fetcher = _FETCHERS.get(asset)
    if not fetcher:
        logger.error("No fetcher for asset: %s", asset)
        return None

    try:
        record = await fetcher()
    except Exception as exc:
        logger.error("Error fetching price for %s: %s", asset, exc)
        return db.get_latest_price(asset)  # fall back to cached value

    if record:
        db.save_price(record)
    return record


async def fetch_all_prices(force: bool = False) -> dict[str, Optional[PriceRecord]]:
    """Fetch prices for all 5 assets concurrently."""
    import asyncio

    tasks = {asset: asyncio.create_task(fetch_price(asset, force)) for asset in ASSETS}
    results = {}
    for asset, task in tasks.items():
        results[asset] = await task
    return results
