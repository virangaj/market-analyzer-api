"""
MEXC Futures (contract) market-data client. Read-only, no API key needed.

Mirrors market_data.py's interface (get_klines/get_price/get_24h/get_symbols)
so api.py can treat spot and futures uniformly. But the contract API differs
from spot in several ways, all handled here:

  - base host:     contract.mexc.com  (override with FUTURES_BASE_URL)
  - kline path:    /api/v1/contract/kline/{SYMBOL}
  - symbol format: underscore, e.g. XAU_USDT  (we normalize XAUUSDT -> XAU_USDT)
  - intervals:     Min1/Min5/Min15/Min30/Min60/Hour4/Hour8/Day1/Week1/Month1
  - response:      column-oriented {data:{time:[...],open:[...],...}}, time in SECONDS
  - catalog:       /api/v1/contract/detail ; ticker: /api/v1/contract/ticker

An unlisted contract comes back as empty data -> we raise ValueError, which
api.py maps to a clean 404 (same as spot's HTTP 400).

NOTE: MEXC's docs mention the futures base may also be served from
api.mexc.com. If contract.mexc.com ever stops resolving, set
FUTURES_BASE_URL=https://api.mexc.com and keep the same paths.
Order placement is intentionally NOT implemented — analysis & alerts only.
"""
from __future__ import annotations

import os
import time

import requests
import pandas as pd

FUTURES_BASE = os.environ.get("FUTURES_BASE_URL", "https://contract.mexc.com").rstrip("/")

_OHLCV = ["open", "high", "low", "close", "volume"]

# app interval -> contract interval
_INTERVAL = {
    "1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30",
    "1h": "Min60", "60m": "Min60", "4h": "Hour4", "8h": "Hour8",
    "1d": "Day1", "1w": "Week1", "1M": "Month1",
}
# seconds per interval (to bound the start/end window for `limit` candles)
_INTERVAL_SEC = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "60m": 3600,
    "4h": 14400, "8h": 28800, "1d": 86400, "1w": 604800, "1M": 2592000,
}


def _contract_symbol(symbol: str) -> str:
    """XAUUSDT -> XAU_USDT (pass through if already underscored)."""
    s = symbol.upper().strip()
    if "_" in s:
        return s
    for q in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}_{q}"
    return s


def _host(base: str | None) -> str:
    return (base or FUTURES_BASE).rstrip("/")


def get_klines(symbol: str = "XAU_USDT", interval: str = "1h", limit: int = 500, base: str | None = None) -> pd.DataFrame:
    sym = _contract_symbol(symbol)
    iv = _INTERVAL.get(interval, "Min60")
    sec = _INTERVAL_SEC.get(interval, 3600)
    end = int(time.time())
    start = end - sec * (limit + 2)
    r = requests.get(
        f"{_host(base)}/api/v1/contract/kline/{sym}",
        params={"interval": iv, "start": start, "end": end},
        timeout=12,
    )
    r.raise_for_status()
    d = (r.json() or {}).get("data") or {}
    times = d.get("time") or []
    if not times:
        raise ValueError(f"no contract klines for {sym}")
    df = pd.DataFrame(
        {
            "open": d["open"],
            "high": d["high"],
            "low": d["low"],
            "close": d["close"],
            "volume": d.get("vol", d.get("volume", [0] * len(times))),
        }
    ).astype(float)
    df["time"] = pd.to_datetime(pd.Series(times, dtype="int64") * 1000, unit="ms")
    return df.set_index("time")[_OHLCV]


def _ticker(symbol: str, base: str | None) -> dict:
    r = requests.get(f"{_host(base)}/api/v1/contract/ticker", params={"symbol": _contract_symbol(symbol)}, timeout=10)
    r.raise_for_status()
    d = (r.json() or {}).get("data") or {}
    if isinstance(d, list):  # ticker without a symbol returns a list
        d = d[0] if d else {}
    return d


def get_price(symbol: str = "XAU_USDT", base: str | None = None) -> float:
    p = _ticker(symbol, base).get("lastPrice")
    if p is None:
        raise ValueError("no contract price")
    return float(p)


def get_24h(symbol: str = "XAU_USDT", base: str | None = None) -> dict:
    d = _ticker(symbol, base)
    return {
        "last": float(d.get("lastPrice", 0) or 0),
        "change_pct": float(d.get("riseFallRate", 0) or 0) * 100,  # contract returns a fraction
        "high": float(d.get("high24Price", 0) or 0),
        "low": float(d.get("lower24Price", 0) or 0),
        "volume": float(d.get("volume24", 0) or 0),
    }


def get_symbols(base: str | None = None) -> list[dict]:
    """All perpetual contracts from /contract/detail: [{symbol, base, quote}, ...]."""
    r = requests.get(f"{_host(base)}/api/v1/contract/detail", timeout=20)
    r.raise_for_status()
    out = []
    for s in (r.json() or {}).get("data", []):
        sym = s.get("symbol")
        if not sym:
            continue
        out.append({"symbol": sym, "base": s.get("baseCoin"), "quote": s.get("quoteCoin")})
    return out
