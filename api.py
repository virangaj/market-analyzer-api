"""
FastAPI surface for the React dashboard.

Endpoints (all GET, read-only):
  /candles   -> OHLCV + indicators for charting
  /analyze   -> current composite signal (+ optional macro/news context)
  /backtest  -> walk-forward backtest metrics + equity curve
  /health

Run:  uvicorn gold_analyzer.api:app --reload --port 8000
"""
from __future__ import annotations

import math

import requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import market_data as bc
import futures_data as fut
import indicators, signal_engine, backtest, context_providers, entries, strategy

app = FastAPI(title="Gold (PAXG) Analyzer", version="0.1.0")


def _source(market: str):
    """Pick the data client: 'futures' -> MEXC contract, else MEXC spot."""
    return fut if market == "futures" else bc

# allow the React dev server to call us during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_safe(records: list[dict]) -> list[dict]:
    """Replace NaN/inf (e.g. indicator warmup) with None so Starlette's
    allow_nan=False JSON encoder doesn't choke. None survives here because
    we operate on plain dicts, not float64 columns (where None -> NaN)."""
    return [
        {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in row.items()}
        for row in records
    ]


def _klines(symbol: str, interval: str, limit: int, market: str):
    """Fetch klines from the chosen market, converting an unlisted symbol or
    upstream hiccup into a clean HTTP error instead of an unhandled 500."""
    try:
        return _source(market).get_klines(symbol, interval, limit)
    except ValueError:
        raise HTTPException(404, f"'{symbol.upper()}' is not a tradable {market} pair on this exchange.")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 502
        if code == 400:
            raise HTTPException(404, f"'{symbol.upper()}' is not a tradable {market} pair on this exchange.")
        if code == 429:
            raise HTTPException(429, "Rate limited by the exchange — slow down and retry.")
        raise HTTPException(502, f"Exchange returned {code} for '{symbol.upper()}'.")
    except requests.RequestException as e:
        raise HTTPException(502, f"Could not reach the exchange: {e}")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/candles")
def candles(symbol: str = "PAXGUSDT", interval: str = "1h", limit: int = Query(300, le=1000), market: str = "spot"):
    df = indicators.enrich(_klines(symbol, interval, limit, market))
    df = df.reset_index()
    df["time"] = df["time"].astype(str)
    try:
        ticker = _source(market).get_24h(symbol)
    except Exception:  # noqa: BLE001 — ticker is non-essential, don't fail the chart
        ticker = None
    return {
        "symbol": symbol,
        "interval": interval,
        "market": market,
        "ticker": ticker,
        "candles": _json_safe(df.to_dict(orient="records")),
    }


@app.get("/symbols")
def symbols(market: str = "spot"):
    """Full tradable catalog (spot or futures) for the frontend autocomplete."""
    try:
        syms = _source(market).get_symbols()
        return {"market": market, "count": len(syms), "symbols": syms}
    except Exception as e:  # noqa: BLE001
        return {"market": market, "count": 0, "symbols": [], "error": str(e)}


@app.get("/sanity")
def sanity(symbol: str = "PAXGUSDT", market: str = "spot"):
    """Cross-check a pair's price: chosen MEXC market vs Binance spot."""
    sym = symbol.upper()
    spot_sym = sym.replace("_", "")  # Binance spot form, e.g. XAU_USDT -> XAUUSDT
    mexc_price = binance_price = None
    try:
        mexc_price = _source(market).get_price(sym)
    except Exception:  # noqa: BLE001
        pass
    try:
        binance_price = bc.get_price(spot_sym, base=bc.BINANCE)
    except Exception:  # noqa: BLE001
        pass

    divergence = None
    if mexc_price and binance_price:
        divergence = round(abs(mexc_price - binance_price) / binance_price * 100, 3)
        status = "diverge" if divergence > 0.5 else "ok"
        note = f"MEXC {market} and Binance spot differ by {divergence}%" if divergence > 0.5 else f"Prices agree within {divergence}%"
    elif binance_price is None and mexc_price is not None:
        status, note = "binance_unavailable", "Binance spot doesn't list this pair (or is geo-blocked) — can't cross-check"
    elif mexc_price is None:
        status, note = "mexc_unavailable", f"No MEXC {market} price for this pair"
    else:
        status, note = "mexc_unavailable", "no price available"

    return {
        "symbol": sym,
        "market": market,
        "mexc_price": mexc_price,
        "binance_price": binance_price,
        "divergence_pct": divergence,
        "status": status,
        "note": note,
    }


@app.get("/analyze")
def analyze(symbol: str = "PAXGUSDT", interval: str = "1h", use_news: bool = False, market: str = "spot"):
    df = indicators.enrich(_klines(symbol, interval, 300, market))
    price = float(df["close"].iloc[-1])

    ctx = context_providers.macro_context(price)
    if use_news:
        # supply your own headline source here; empty -> neutral
        ctx = context_providers.combine(ctx, context_providers.news_context([]))

    result = signal_engine.analyze(df, context=ctx)
    result["symbol"] = symbol
    result["interval"] = interval
    result["market"] = market
    return result


@app.get("/entry")
def entry(
    symbol: str = "PAXGUSDT",
    interval: str = "1h",
    market: str = "spot",
    account: float | None = None,
    risk_pct: float = 1.0,
    enter_long: float | None = None,
    enter_short: float | None = None,
):
    """Risk-defined entry/stop/target bracket derived from the live signal."""
    df = indicators.enrich(_klines(symbol, interval, 300, market))
    price = float(df["close"].iloc[-1])
    res = signal_engine.analyze(df, context=context_providers.macro_context(price))
    cfg = strategy.StrategyConfig()
    if enter_long is not None:
        cfg.enter_long = enter_long
    if enter_short is not None:
        cfg.enter_short = enter_short
    bracket = entries.suggest(df, res["score"], res["confidence"], cfg=cfg, account=account, risk_pct=risk_pct)
    bracket["symbol"] = symbol
    bracket["market"] = market
    bracket["score"] = res["score"]
    bracket["label"] = res["label"]
    return bracket


@app.get("/backtest")
def run_backtest(
    symbol: str = "PAXGUSDT",
    interval: str = "1h",
    limit: int = Query(1000, le=1000),
    market: str = "spot",
    fee_bps: float = 7.5,
    enter_long: float | None = None,
    enter_short: float | None = None,
    allow_short: bool | None = None,
    target_r: float | None = None,
):
    df = _klines(symbol, interval, limit, market)
    cfg = strategy.StrategyConfig()
    if enter_long is not None:
        cfg.enter_long = enter_long
    if enter_short is not None:
        cfg.enter_short = enter_short
    if allow_short is not None:
        cfg.allow_short = allow_short
    if target_r is not None:
        cfg.target_R = target_r
    return backtest.run(df, cfg=cfg, fee_bps=fee_bps)
