"""
Candlestick pattern detection.

Patterns are returned as signed weights on the LAST closed bar:
  positive  -> bullish bias, negative -> bearish bias, magnitude 0..1.
Patterns are deliberately treated as *context*, not standalone triggers:
the signal engine only counts them when they line up with trend/levels.
"""
from __future__ import annotations

import pandas as pd


def _body(o, c):
    return abs(c - o)


def _range(h, l):
    return (h - l) or 1e-9


def detect(df: pd.DataFrame) -> dict:
    """Inspect the last 1-3 closed candles. Returns {name: weight} for hits."""
    if len(df) < 3:
        return {}
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    i = len(df) - 1
    p = i - 1  # previous bar
    hits: dict[str, float] = {}

    body = _body(o[i], c[i])
    rng = _range(h[i], l[i])
    upper_wick = h[i] - max(o[i], c[i])
    lower_wick = min(o[i], c[i]) - l[i]
    bullish = c[i] > o[i]

    # Doji — indecision (neutral-ish, slight mean-reversion context)
    if body <= 0.1 * rng:
        hits["doji"] = 0.0

    # Hammer — long lower wick, small body near top (bullish reversal)
    if lower_wick >= 2 * body and upper_wick <= body and body > 0:
        hits["hammer"] = 0.6

    # Shooting star — long upper wick, small body near bottom (bearish reversal)
    if upper_wick >= 2 * body and lower_wick <= body and body > 0:
        hits["shooting_star"] = -0.6

    # Engulfing — current body fully engulfs previous body
    prev_body_low, prev_body_high = min(o[p], c[p]), max(o[p], c[p])
    cur_body_low, cur_body_high = min(o[i], c[i]), max(o[i], c[i])
    engulfs = cur_body_low <= prev_body_low and cur_body_high >= prev_body_high
    if engulfs and bullish and c[p] < o[p]:
        hits["bullish_engulfing"] = 0.7
    if engulfs and not bullish and c[p] > o[p]:
        hits["bearish_engulfing"] = -0.7

    # Morning / evening star — 3-bar reversal
    pp = i - 2
    mid_small = _body(o[p], c[p]) <= 0.5 * _body(o[pp], c[pp])
    if (
        c[pp] < o[pp]  # big down bar
        and mid_small  # small middle
        and c[i] > o[i]  # big up bar
        and c[i] > (o[pp] + c[pp]) / 2
    ):
        hits["morning_star"] = 0.8
    if (
        c[pp] > o[pp]  # big up bar
        and mid_small
        and c[i] < o[i]  # big down bar
        and c[i] < (o[pp] + c[pp]) / 2
    ):
        hits["evening_star"] = -0.8

    return hits
