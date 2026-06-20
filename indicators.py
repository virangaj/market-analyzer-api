"""
Technical indicators with TradingView-matching math.

Key fidelity notes:
- RSI / ATR use Wilder's smoothing (RMA), i.e. an EMA with alpha = 1/length.
- EMA uses alpha = 2/(length+1).
- Bollinger Bands use population stdev (ddof=0), matching Pine's ta.stdev.
All functions take/return pandas Series aligned to the input index, so they
compose cleanly and stay causal (each value uses only data up to that bar).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    # adjust=False replicates the recursive EMA TradingView uses
    return series.ewm(span=length, adjust=False).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average (RMA): EMA with alpha = 1/length."""
    return series.ewm(alpha=1 / length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(close: pd.Series, length: int = 20, mult: float = 2.0):
    basis = sma(close, length)
    # population stdev (ddof=0) to match Pine's ta.stdev
    dev = close.rolling(length).std(ddof=0)
    upper = basis + mult * dev
    lower = basis - mult * dev
    return pd.DataFrame({"basis": basis, "upper": upper, "lower": lower})


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    return rma(true_range(high, low, close), length)


def supertrend(high, low, close, length: int = 10, mult: float = 3.0):
    """Returns DataFrame with 'supertrend' line and 'dir' (1 up, -1 down)."""
    hl2 = (high + low) / 2
    atr_ = atr(high, low, close, length)
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_

    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(index=close.index, dtype=float)
    st = pd.Series(index=close.index, dtype=float)

    for i in range(len(close)):
        if i == 0 or np.isnan(atr_.iloc[i]):
            direction.iloc[i] = 1
            st.iloc[i] = lower.iloc[i]
            continue
        # carry the band forward (tighten only)
        final_upper.iloc[i] = (
            upper.iloc[i]
            if (upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1])
            else final_upper.iloc[i - 1]
        )
        final_lower.iloc[i] = (
            lower.iloc[i]
            if (lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1])
            else final_lower.iloc[i - 1]
        )
        prev_dir = direction.iloc[i - 1]
        if prev_dir == 1:
            direction.iloc[i] = -1 if close.iloc[i] < final_lower.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if close.iloc[i] > final_upper.iloc[i] else -1
        st.iloc[i] = final_lower.iloc[i] if direction.iloc[i] == 1 else final_upper.iloc[i]

    return pd.DataFrame({"supertrend": st, "dir": direction})


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (not direction). Wilder smoothing."""
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    atr_ = rma(true_range(high, low, close), length)
    plus_di = 100 * rma(plus_dm, length) / atr_
    minus_di = 100 * rma(minus_dm, length) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx, length)


def rvol(volume: pd.Series, length: int = 20) -> pd.Series:
    """Relative volume: current bar volume vs its rolling average."""
    return volume / volume.rolling(length).mean()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the full indicator set to an OHLCV DataFrame (cols: open/high/low/close/volume)."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], 21)
    out["ema_slow"] = ema(out["close"], 55)
    out["rsi"] = rsi(out["close"], 14)
    m = macd(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = m["macd"], m["signal"], m["hist"]
    bb = bollinger(out["close"])
    out["bb_basis"], out["bb_upper"], out["bb_lower"] = bb["basis"], bb["upper"], bb["lower"]
    out["atr"] = atr(out["high"], out["low"], out["close"], 14)
    sup = supertrend(out["high"], out["low"], out["close"])
    out["supertrend"], out["st_dir"] = sup["supertrend"], sup["dir"]
    out["adx"] = adx(out["high"], out["low"], out["close"], 14)
    out["rvol"] = rvol(out["volume"], 20)
    return out
