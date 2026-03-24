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
    # Gold Futures (GC=F) from Yahoo Finance — free, real-time, no API key needed.
    # Alpha Vantage free tier returns stale XAU/USD data, so Yahoo is more reliable.
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(url, params={"interval": "1d", "range": "2d"})
        r.raise_for_status()
        data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    meta = result[0].get("meta", {})
    price = float(meta.get("regularMarketPrice", 0))
    prev_close = float(meta.get("chartPreviousClose", 0))
    if not price:
        return None
    change_24h = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
    return PriceRecord(asset="XAUUSD", price=round(price, 2), change_24h=round(change_24h, 3))


async def _fetch_brent() -> Optional[PriceRecord]:
    # Brent Crude Futures (BZ=F) from Yahoo Finance — real-time, no API key needed.
    url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(url, params={"interval": "1d", "range": "2d"})
        r.raise_for_status()
        data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    meta = result[0].get("meta", {})
    price = float(meta.get("regularMarketPrice", 0))
    prev_close = float(meta.get("chartPreviousClose", 0))
    if not price:
        return None
    change_24h = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
    return PriceRecord(asset="BRENT", price=round(price, 2), change_24h=round(change_24h, 3))


async def _fetch_spx() -> Optional[PriceRecord]:
    # Fetch E-Mini S&P 500 Futures (ES=F) from Yahoo Finance — no API key needed
    url = "https://query1.finance.yahoo.com/v8/finance/chart/ES%3DF"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(url, params={"interval": "1d", "range": "2d"})
        r.raise_for_status()
        data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    meta = result[0].get("meta", {})
    price = float(meta.get("regularMarketPrice", 0))
    prev_close = float(meta.get("chartPreviousClose", 0))
    if not price:
        return None
    change_24h = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
    return PriceRecord(asset="SPX", price=round(price, 2), change_24h=round(change_24h, 3))


async def _fetch_btc() -> Optional[PriceRecord]:
    # BTC-USD from Yahoo Finance — uses chartPreviousClose (previous session close)
    # so change_24h reflects day-over-day move, consistent with other assets.
    url = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(url, params={"interval": "1d", "range": "2d"})
        r.raise_for_status()
        data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    meta = result[0].get("meta", {})
    price = float(meta.get("regularMarketPrice", 0))
    prev_close = float(meta.get("chartPreviousClose", 0))
    if not price:
        return None
    change_24h = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
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
