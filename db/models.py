from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class User(BaseModel):
    telegram_id: int
    subscribed: bool = True
    language: str = "en"
    created_at: Optional[datetime] = None


class PriceRecord(BaseModel):
    asset: str          # e.g. "EURUSD"
    price: float
    change_24h: float   # percentage
    created_at: Optional[datetime] = None


class NewsItem(BaseModel):
    asset: str
    title: str
    url: Optional[str] = None
    published_at: Optional[str] = None


class Sentiment(BaseModel):
    asset: str
    sentiment: str      # "bullish" | "bearish" | "neutral"
    score: int          # 0–100
    reasoning: str
    created_at: Optional[datetime] = None


class Brief(BaseModel):
    id: Optional[int] = None
    content: str
    broadcast_sent: bool = False
    created_at: Optional[datetime] = None


class Idea(BaseModel):
    id: Optional[int] = None
    asset: str
    direction: str      # "LONG" | "SHORT"
    entry: str
    stop_loss: str
    take_profit: str
    rr_ratio: str
    timeframe: str
    reasoning: str
    result: str = "OPEN"        # "OPEN" | "TP_HIT" | "SL_HIT"
    result_price: Optional[float] = None
    checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# -----------------------------------------------------------------------
# Supabase SQL to create tables (run once in Supabase SQL editor):
#
# CREATE TABLE IF NOT EXISTS users (
#     telegram_id BIGINT PRIMARY KEY,
#     subscribed  BOOLEAN DEFAULT TRUE,
#     language    TEXT DEFAULT 'en',
#     created_at  TIMESTAMPTZ DEFAULT NOW()
# );
#
# If table already exists:
#   ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en';
#
# CREATE TABLE IF NOT EXISTS prices (
#     id          BIGSERIAL PRIMARY KEY,
#     asset       TEXT NOT NULL,
#     price       NUMERIC NOT NULL,
#     change_24h  NUMERIC NOT NULL,
#     created_at  TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE IF NOT EXISTS news (
#     id           BIGSERIAL PRIMARY KEY,
#     asset        TEXT NOT NULL,
#     title        TEXT NOT NULL,
#     url          TEXT,
#     published_at TEXT,
#     created_at   TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE IF NOT EXISTS sentiments (
#     id         BIGSERIAL PRIMARY KEY,
#     asset      TEXT NOT NULL,
#     sentiment  TEXT NOT NULL,
#     score      INTEGER NOT NULL,
#     reasoning  TEXT NOT NULL,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE IF NOT EXISTS briefs (
#     id             BIGSERIAL PRIMARY KEY,
#     content        TEXT NOT NULL,
#     broadcast_sent BOOLEAN DEFAULT FALSE,
#     created_at     TIMESTAMPTZ DEFAULT NOW()
# );
#
# If table already exists:
#   ALTER TABLE briefs ADD COLUMN IF NOT EXISTS broadcast_sent BOOLEAN DEFAULT FALSE;
#
# CREATE TABLE IF NOT EXISTS ideas (
#     id           BIGSERIAL PRIMARY KEY,
#     asset        TEXT NOT NULL,
#     direction    TEXT NOT NULL,
#     entry        TEXT NOT NULL,
#     stop_loss    TEXT NOT NULL,
#     take_profit  TEXT NOT NULL,
#     rr_ratio     TEXT NOT NULL,
#     timeframe    TEXT NOT NULL,
#     reasoning    TEXT NOT NULL,
#     result       TEXT DEFAULT 'OPEN',
#     result_price NUMERIC,
#     checked_at   TIMESTAMPTZ,
#     created_at   TIMESTAMPTZ DEFAULT NOW()
# );
#
# If table already exists, run these ALTER statements in Supabase SQL editor:
#   ALTER TABLE ideas ADD COLUMN IF NOT EXISTS result TEXT DEFAULT 'OPEN';
#   ALTER TABLE ideas ADD COLUMN IF NOT EXISTS result_price NUMERIC;
#   ALTER TABLE ideas ADD COLUMN IF NOT EXISTS checked_at TIMESTAMPTZ;
# -----------------------------------------------------------------------
