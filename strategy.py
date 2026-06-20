"""
Strategy configuration and the position decision logic — the single source of
truth shared by BOTH the live entry endpoint and the backtester, so they can
never silently diverge again.

Encodes the upgrades:
  - asymmetric thresholds   (harder to short than to long, by default)
  - hysteresis              (enter at one level, exit at a closer one -> no border whiplash)
  - regime awareness        (ADX-based: require more confluence in a range)
  - dynamic ATR multiplier  (widen the stop when relative volume spikes)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class StrategyConfig:
    # entry thresholds (asymmetric: shorts need more confluence)
    enter_long: float = 15.0
    enter_short: float = -25.0
    # hysteresis exits — once in a trade, hold until the score decays past these
    exit_long: float = 5.0
    exit_short: float = -5.0
    allow_short: bool = True
    # stop sizing
    atr_mult: float = 1.5
    atr_mult_highvol: float = 2.5
    rvol_high: float = 2.0            # relative volume above this -> use the wide stop
    # regime
    regime_adx_min: float = 20.0     # ADX below this == ranging
    range_threshold_mult: float = 1.6  # in a range, require this much more score to enter
    # backtest exit target (in R multiples)
    target_R: float = 2.0


def regime_of(adx: float | None, cfg: StrategyConfig) -> str:
    """'trend' when ADX is healthy, else 'range'. Unknown ADX defaults to trend."""
    if adx is None or np.isnan(adx):
        return "trend"
    return "trend" if adx >= cfg.regime_adx_min else "range"


def effective_thresholds(cfg: StrategyConfig, regime: str) -> tuple[float, float]:
    """Entry thresholds after the regime adjustment (harder to enter in a range)."""
    m = cfg.range_threshold_mult if regime == "range" else 1.0
    return cfg.enter_long * m, cfg.enter_short * m


def atr_mult_for(rvol: float | None, cfg: StrategyConfig) -> float:
    """Wide stop when relative volume is abnormally high, else the base multiple."""
    if rvol is not None and not np.isnan(rvol) and rvol >= cfg.rvol_high:
        return cfg.atr_mult_highvol
    return cfg.atr_mult


def decide(score: float, prev_pos: int, cfg: StrategyConfig, regime: str = "trend") -> int:
    """
    Hysteresis state machine. Returns the new position (-1 short, 0 flat, 1 long)
    given the current score and the position we're already in.

      flat   -> long  when score >= enter_long (regime-scaled)
      long   -> flat  only when score falls below exit_long  (sticky, no whiplash)
      long   -> short directly if score collapses past enter_short
      (mirror for shorts)
    """
    el, es = effective_thresholds(cfg, regime)
    pos = prev_pos

    if prev_pos == 1:  # currently long
        if score <= cfg.exit_long:
            pos = 0
        if cfg.allow_short and score <= es:
            pos = -1
    elif prev_pos == -1:  # currently short
        if score >= cfg.exit_short:
            pos = 0
        if score >= el:
            pos = 1
    else:  # flat
        if score >= el:
            pos = 1
        elif cfg.allow_short and score <= es:
            pos = -1

    return pos
