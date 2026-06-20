"""
Binance public market-data client. No API key needed for market data.

Only read-only public endpoints are used here. Order placement is
intentionally NOT implemented — this build is analysis & alerts only.
When you later add live trading, keep it behind a separate, explicitly
keyed module so research code can never accidentally send orders.
"""
from __future__ import annotations

import requests
import pandas as pd

BASE = "https://api.binance.com"

# Binance kline columns
_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "qav", "trades", "tb_base", "tb_quote", "ignore",
]


def get_klines(symbol: str = "PAXGUSDT", interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Fetch OHLCV candles. interval e.g. 1m,5m,15m,1h,4h,1d."""
    r = requests.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=_COLS)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df.set_index("time")[["open", "high", "low", "close", "volume"]]


def get_price(symbol: str = "PAXGUSDT") -> float:
    r = requests.get(f"{BASE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


def get_24h(symbol: str = "PAXGUSDT") -> dict:
    r = requests.get(f"{BASE}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    d = r.json()
    return {
        "last": float(d["lastPrice"]),
        "change_pct": float(d["priceChangePercent"]),
        "high": float(d["highPrice"]),
        "low": float(d["lowPrice"]),
        "volume": float(d["volume"]),
    }
