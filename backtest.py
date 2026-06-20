"""
Walk-forward backtester — now models the REAL trade logic.

Previously this used a crude ±20 threshold with next-bar returns and never
touched the ATR bracket — so it validated a different strategy than the live
endpoint. Rewritten to share strategy.StrategyConfig with the live path and to
simulate the actual bracket:

  - entries via the hysteresis / asymmetric / regime-aware decide()
  - on entry: stop = atr_mult(rvol) × ATR, target = target_R × risk
  - each subsequent bar: exit if the bar's range hits the stop or the target
    (stop checked first — conservative), else exit on a signal flip
  - no look-ahead: the score at bar i uses data ≤ i; the entry fills at that
    bar's close; stop/target are only checked on later bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import indicators
import signal_engine
import strategy


def run(df: pd.DataFrame, cfg: "strategy.StrategyConfig | None" = None, fee_bps: float = 7.5, warmup: int = 60) -> dict:
    cfg = cfg or strategy.StrategyConfig()
    enriched = indicators.enrich(df)
    n = len(enriched)
    fee = fee_bps / 10000.0

    equity = 1.0
    eq_curve: list[float] = []
    eq_time: list[str] = []
    trade_rets: list[float] = []

    pos = 0
    entry_px = stop_px = tgt_px = 0.0

    def close_trade(exit_px: float):
        nonlocal equity, pos
        ret = pos * (exit_px / entry_px - 1) - 2 * fee  # round-trip cost
        equity *= 1 + ret
        trade_rets.append(ret)
        pos = 0

    for i in range(n):
        bar = enriched.iloc[i]
        atr = bar["atr"]
        if i < warmup or np.isnan(atr):
            eq_curve.append(equity)
            eq_time.append(enriched.index[i].isoformat())
            continue

        # 1) manage an open position against THIS bar's range (stop first)
        if pos != 0:
            if pos == 1:
                if bar["low"] <= stop_px:
                    close_trade(stop_px)
                elif bar["high"] >= tgt_px:
                    close_trade(tgt_px)
            else:
                if bar["high"] >= stop_px:
                    close_trade(stop_px)
                elif bar["low"] <= tgt_px:
                    close_trade(tgt_px)

        # 2) signal decision on data up to and including this bar (causal)
        score = signal_engine.analyze(enriched.iloc[: i + 1])["score"]
        regime = strategy.regime_of(None if np.isnan(bar["adx"]) else bar["adx"], cfg)
        new_pos = strategy.decide(score, pos, cfg, regime)

        if new_pos != pos:
            if pos != 0:  # signal-flip exit at close
                close_trade(bar["close"])
            if new_pos != 0:  # open a fresh bracket
                rvol = None if np.isnan(bar["rvol"]) else bar["rvol"]
                dist = strategy.atr_mult_for(rvol, cfg) * atr
                entry_px = bar["close"]
                sign = 1 if new_pos == 1 else -1
                stop_px = entry_px - sign * dist
                tgt_px = entry_px + sign * cfg.target_R * dist
            pos = new_pos

        eq_curve.append(equity)
        eq_time.append(enriched.index[i].isoformat())

    # close any position still open at the final price
    if pos != 0:
        close_trade(enriched["close"].iloc[-1])
        eq_curve[-1] = equity

    eq = pd.Series(eq_curve)
    rets = eq.pct_change().dropna()
    wins = sum(1 for t in trade_rets if t > 0)
    n_tr = len(trade_rets)
    peak = eq.cummax()
    max_dd = float((eq / peak - 1).min()) if len(eq) else 0.0
    sharpe = float(rets.mean() / (rets.std() + 1e-9) * np.sqrt(365 * 24)) if len(rets) else 0.0
    bh = float(enriched["close"].iloc[-1] / enriched["close"].iloc[warmup] - 1) if n > warmup else 0.0

    return {
        "total_return_pct": round(float(equity - 1) * 100, 2),
        "buy_hold_pct": round(bh * 100, 2),
        "win_rate_pct": round(wins / n_tr * 100, 1) if n_tr else 0.0,
        "trades": int(n_tr),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "equity_curve": [round(float(x), 4) for x in eq_curve],
        "timestamps": eq_time,
    }
