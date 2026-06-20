"""
Entry suggestion logic — derives a risk-defined bracket from the signal.

Now driven by the shared StrategyConfig (strategy.py), so it uses the same
asymmetric thresholds, regime gate, and dynamic stop as the backtester.

Hardened per review:
  - No ATR -> NO TRADE at all (not just "no stop"). A direction without an
    invalidation price is forbidden.
  - Regime-aware: in a ranging market the entry bar is raised (harder to buy
    a local top in chop).
  - Dynamic stop: widens to atr_mult_highvol when relative volume spikes; the
    position auto-shrinks so the dollar risk stays identical.
"""
from __future__ import annotations

import numpy as np

import strategy


def _val(row, key):
    v = row.get(key, np.nan)
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def suggest(
    df,
    score: float,
    confidence: float,
    cfg: "strategy.StrategyConfig | None" = None,
    account: float | None = None,
    risk_pct: float = 1.0,
) -> dict:
    cfg = cfg or strategy.StrategyConfig()
    row = df.iloc[-1]
    entry = float(row["close"])
    atr = _val(row, "atr")
    adx = _val(row, "adx")
    rvol = _val(row, "rvol")
    regime = strategy.regime_of(adx, cfg)

    base = {"entry": round(entry, 6), "atr": atr, "regime": regime,
            "adx": None if adx is None else round(adx, 1)}

    # HARD guardrail: no volatility basis -> no trade (review fix #3)
    if atr is None or atr <= 0:
        return {**base, "side": "none", "stop": None, "risk_per_unit": None,
                "targets": [], "sizing": None,
                "note": "ATR unavailable — trade forbidden (no risk basis)."}

    # regime-scaled, asymmetric entry thresholds
    el, es = strategy.effective_thresholds(cfg, regime)
    side = "long" if score >= el else "short" if (cfg.allow_short and score <= es) else "none"

    if side == "none":
        return {**base, "side": "none", "stop": None, "risk_per_unit": None,
                "targets": [], "sizing": None,
                "note": f"No edge in {regime} regime (need ≥ {el:.0f} / ≤ {es:.0f}) — HOLD."}

    mult = strategy.atr_mult_for(rvol, cfg)
    dist = mult * atr
    sign = 1 if side == "long" else -1
    stop = entry - sign * dist
    targets = [{"label": f"{m}R", "price": round(entry + sign * m * dist, 6), "rr": float(m)} for m in (1, 2, 3)]

    sizing = None
    if account and account > 0 and risk_pct and risk_pct > 0:
        risk_amount = account * risk_pct / 100.0
        qty = risk_amount / dist
        notional = qty * entry
        sizing = {
            "account": round(account, 2), "risk_pct": round(risk_pct, 3),
            "risk_amount": round(risk_amount, 2), "qty": round(qty, 8),
            "notional": round(notional, 2), "leverage": round(notional / account, 2),
        }

    return {
        **base,
        "side": side,
        "stop": round(stop, 6),
        "atr_mult": mult,
        "rvol": None if rvol is None else round(rvol, 2),
        "risk_per_unit": round(dist, 6),
        "targets": targets,
        "sizing": sizing,
        "confidence": confidence,
    }
