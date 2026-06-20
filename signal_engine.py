"""
Composite signal engine.

Turns enriched OHLCV + optional macro/news context into a single
directional bias in [-100, +100] with a confidence read. Each component
emits a sub-score in [-1, 1]; the weighted blend is scaled to [-100, 100].

Weights are configurable. Macro (DXY / spot-gold premium) and news default
to neutral when not supplied, so the engine runs on price alone until you
wire those feeds in (see context= argument).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import patterns


@dataclass
class Weights:
    trend: float = 0.30
    momentum: float = 0.25
    volatility: float = 0.10
    supertrend: float = 0.10
    candles: float = 0.10
    macro: float = 0.10   # DXY direction + PAXG-vs-spot premium
    news: float = 0.05    # LLM-scored headline sentiment


@dataclass
class Context:
    """External, non-price inputs. All optional; default neutral (0)."""
    dxy_score: float = 0.0      # +1 dollar weakening (bullish gold) .. -1 strengthening
    premium_score: float = 0.0  # PAXG rich/cheap vs spot gold, normalized -1..1
    news_score: float = 0.0     # aggregate headline sentiment for gold, -1..1
    notes: list = field(default_factory=list)


def _clip(x: float) -> float:
    return float(max(-1.0, min(1.0, x)))


def _trend_score(row) -> float:
    if np.isnan(row.ema_fast) or np.isnan(row.ema_slow):
        return 0.0
    sep = (row.ema_fast - row.ema_slow) / row.close          # EMA spread
    pos = (row.close - row.ema_slow) / row.close              # price vs slow EMA
    return _clip(60 * sep + 20 * pos)


def _momentum_score(row) -> float:
    s = 0.0
    if not np.isnan(row.rsi):
        s += (row.rsi - 50) / 50 * 0.6          # centered RSI
    if not np.isnan(row.macd_hist):
        s += _clip(row.macd_hist / row.close * 800) * 0.4
    return _clip(s)


def _volatility_score(row) -> float:
    # position within Bollinger band: near lower = bullish mean-revert, near upper = bearish
    if np.isnan(row.bb_upper) or row.bb_upper == row.bb_lower:
        return 0.0
    pos = (row.close - row.bb_basis) / (row.bb_upper - row.bb_basis)  # 0=basis,1=upper
    return _clip(-0.5 * pos)


def _supertrend_score(row) -> float:
    return 0.0 if np.isnan(row.st_dir) else float(row.st_dir)


def analyze(df: pd.DataFrame, weights: Weights | None = None, context: Context | None = None) -> dict:
    """df must already be passed through indicators.enrich(). Uses the last bar."""
    weights = weights or Weights()
    context = context or Context()
    row = df.iloc[-1]

    pat = patterns.detect(df)
    candle_score = _clip(sum(pat.values()))

    components = {
        "trend": _trend_score(row),
        "momentum": _momentum_score(row),
        "volatility": _volatility_score(row),
        "supertrend": _supertrend_score(row),
        "candles": candle_score,
        "macro": _clip(context.dxy_score + context.premium_score),
        "news": _clip(context.news_score),
    }

    w = weights.__dict__
    raw = sum(components[k] * w[k] for k in components)
    score = round(raw * 100, 1)

    if score >= 40:
        label = "Strong Bullish"
    elif score >= 15:
        label = "Bullish"
    elif score > -15:
        label = "Neutral"
    elif score > -40:
        label = "Bearish"
    else:
        label = "Strong Bearish"

    # confidence = component agreement (low dispersion + non-trivial magnitude)
    vals = np.array(list(components.values()))
    agreement = 1 - (vals.std() / (abs(vals).mean() + 1e-9))
    confidence = round(max(0.0, min(1.0, 0.5 * abs(raw) + 0.5 * max(0, agreement))) * 100, 0)

    return {
        "score": score,
        "label": label,
        "confidence": confidence,
        "components": {k: round(v, 3) for k, v in components.items()},
        "patterns": pat,
        "atr": None if np.isnan(row.atr) else round(float(row.atr), 4),
        "close": round(float(row.close), 4),
        "notes": context.notes,
    }
