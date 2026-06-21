"""
Multi-timeframe (MTF) confluence.

Runs the same signal engine across the timeframes traders actually watch and
combines them into one verdict. Higher timeframes carry more weight, because the
dominant trend should outrank intraday noise — this is what stops a 1h long that
is fighting the daily downtrend.

  15m  intraday entry timing
  1h   intraday trend
  4h   swing trend
  1d   dominant trend   (weighted heaviest)

Output: a per-timeframe breakdown, a weighted combined score, and an
"alignment" % (how much the timeframes agree — high alignment = high conviction).
"""
from __future__ import annotations

import numpy as np

import indicators
import signal_engine

# Most-watched timeframes and their confluence weights (higher TF = more weight).
DEFAULT_TFS = ["15m", "1h", "4h", "1d"]
WEIGHTS = {"1m": 0.05, "5m": 0.10, "15m": 0.15, "1h": 0.25, "4h": 0.30, "1d": 0.35, "1w": 0.35}


def _label(score: float) -> str:
    if score >= 40:
        return "Strong Bullish"
    if score >= 15:
        return "Bullish"
    if score > -15:
        return "Neutral"
    if score > -40:
        return "Bearish"
    return "Strong Bearish"


def analyze_mtf(get_klines, symbol: str, timeframes: list[str] | None = None) -> dict:
    """
    get_klines: a function (symbol, interval, limit) -> OHLCV DataFrame
                (pass the spot or futures client's get_klines).
    Resilient per timeframe: if one fails, the others still combine.
    """
    tfs = timeframes or DEFAULT_TFS
    rows = []
    wsum = 0.0
    weighted_score = 0.0
    align = 0.0

    for tf in tfs:
        w = WEIGHTS.get(tf, 0.20)
        try:
            df = indicators.enrich(get_klines(symbol, tf, 300))
            res = signal_engine.analyze(df)
            adx = df["adx"].iloc[-1]
            rows.append({
                "timeframe": tf,
                "score": res["score"],
                "label": res["label"],
                "confidence": res["confidence"],
                "adx": None if np.isnan(adx) else round(float(adx), 1),
                "weight": w,
            })
            wsum += w
            weighted_score += w * res["score"]
            align += w * (1 if res["score"] > 0 else -1 if res["score"] < 0 else 0)
        except Exception as e:  # noqa: BLE001 — one bad timeframe shouldn't sink the rest
            rows.append({"timeframe": tf, "score": None, "label": "n/a", "weight": w, "error": str(e)})

    combined = round(weighted_score / wsum, 1) if wsum else 0.0
    alignment = round(abs(align / wsum) * 100, 0) if wsum else 0.0

    return {
        "symbol": symbol,
        "combined_score": combined,
        "combined_label": _label(combined),
        "alignment_pct": alignment,   # 100 = every timeframe agrees
        "timeframes": rows,
    }
