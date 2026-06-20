"""
Market-data client. Exchange-agnostic, read-only, no API key required.

Defaults to MEXC (lists thousands of pairs; public endpoints are key-free and
IP-rate-limited at 300 weight / 10s, klines = weight 1). MEXC's spot REST
mirrors Binance's schema, so the same code works on either. Switch the primary
source with:

    set MARKET_BASE_URL=https://api.binance.com     (Windows)
    export MARKET_BASE_URL=https://api.binance.us   (mac/linux)

Each function also takes an optional `base=` to query a specific exchange
regardless of the default (used by the Binance cross-check / sanity endpoint).

Schema difference handled: MEXC klines return 8 columns, Binance 12 — we keep
only the first 6 (open_time, OHLCV), so both parse.
Order placement is intentionally NOT implemented — analysis & alerts only.
"""
from __future__ import annotations

import os

import requests
import pandas as pd

MEXC = "https://api.mexc.com"
BINANCE = "https://api.binance.com"
BASE = os.environ.get("MARKET_BASE_URL", MEXC).rstrip("/")

_OHLCV = ["open", "high", "low", "close", "volume"]


def _base(base: str | None) -> str:
    return (base or BASE).rstrip("/")


def _to_df(rows: list) -> pd.DataFrame:
    """Parse a klines array (Binance or MEXC) into an OHLCV DataFrame."""
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time", *_OHLCV])
    for c in _OHLCV:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms")
    return df.set_index("time")[_OHLCV]


def get_klines(symbol: str = "PAXGUSDT", interval: str = "1h", limit: int = 500, base: str | None = None) -> pd.DataFrame:
    r = requests.get(
        f"{_base(base)}/api/v3/klines",
        params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return _to_df(r.json())


def get_price(symbol: str = "PAXGUSDT", base: str | None = None) -> float:
    r = requests.get(f"{_base(base)}/api/v3/ticker/price", params={"symbol": symbol.upper()}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


def get_24h(symbol: str = "PAXGUSDT", base: str | None = None) -> dict:
    r = requests.get(f"{_base(base)}/api/v3/ticker/24hr", params={"symbol": symbol.upper()}, timeout=10)
    r.raise_for_status()
    d = r.json()
    return {
        "last": float(d.get("lastPrice", 0) or 0),
        "change_pct": float(d.get("priceChangePercent", 0) or 0),
        "high": float(d.get("highPrice", 0) or 0),
        "low": float(d.get("lowPrice", 0) or 0),
        "volume": float(d.get("volume", 0) or 0),
    }


def get_symbols(base: str | None = None) -> list[dict]:
    """Full tradable catalog from exchangeInfo: [{symbol, base, quote}, ...]."""
    r = requests.get(f"{_base(base)}/api/v3/exchangeInfo", timeout=20)
    r.raise_for_status()
    out = []
    for s in r.json().get("symbols", []):
        sym = s.get("symbol")
        if not sym:
            continue
        # keep enabled/trading pairs; status naming differs across exchanges so be lenient
        status = s.get("status")
        if status in ("BREAK", "HALT", "0", 0, False):
            continue
        out.append({"symbol": sym, "base": s.get("baseAsset"), "quote": s.get("quoteAsset")})
    return out
