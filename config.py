import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
ALPHA_VANTAGE_API_KEY: str = _require("ALPHA_VANTAGE_API_KEY")
NEWS_API_KEY: str = _require("NEWS_API_KEY")
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
SUPABASE_URL: str = _require("SUPABASE_URL")
SUPABASE_KEY: str = _require("SUPABASE_KEY")

# Admin Telegram ID for /admin_stats (optional — bot still works without it)
_admin_raw = os.getenv("ADMIN_TELEGRAM_ID", "").strip().strip('"').strip("'")
try:
    ADMIN_TELEGRAM_ID: Optional[int] = int(_admin_raw) if _admin_raw else None
except ValueError:
    ADMIN_TELEGRAM_ID = None

print(f"[config] ADMIN_TELEGRAM_ID raw={os.getenv('ADMIN_TELEGRAM_ID')!r} parsed={ADMIN_TELEGRAM_ID}", flush=True)

# Claude model
CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"

# Cache TTL in minutes
CACHE_TTL_MINUTES: int = 30

# Assets configuration
ASSETS: dict = {
    "EURUSD": {
        "name": "EUR/USD (EURUSD)",
        "type": "fx",
        "news_query": "euro dollar ECB Fed",
    },
    "XAUUSD": {
        "name": "Gold (XAUUSD)",
        "type": "commodity",
        "news_query": "gold XAU fed dollar inflation",
    },
    "BRENT": {
        "name": "Brent Crude (CL)",
        "type": "commodity",
        "news_query": "brent crude oil OPEC",
    },
    "SPX": {
        "name": "E-Mini S&P 500 Futures (ES)",
        "type": "index",
        "news_query": "S&P 500 ES futures fed earnings market",
    },
    "BTC": {
        "name": "Bitcoin (BTCUSD)",
        "type": "crypto",
        "news_query": "bitcoin crypto ETF",
    },
}
