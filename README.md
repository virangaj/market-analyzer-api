# Gold (PAXG) Market Analyzer

Analysis & alerts engine for trading **PAX Gold (PAXG)** on Binance. PAXG is
tokenized physical gold — so it behaves like a gold tracker (driven by the US
dollar / DXY, real yields, rate expectations, geopolitics) *and* a crypto asset
(its own order-book liquidity, BTC correlation, and a premium/discount vs. spot
gold that is itself a signal).

This repo is the **research-now / live-later** backend. It is **analysis-only** —
no order placement anywhere in the codebase.

## Architecture

```
                 ┌────────────────────────────────────────────┐
   Binance REST  │  binance_client.py   (OHLCV + ticker)        │
   (public)      └───────────────┬──────────────────────────────┘
                                 ▼
                    indicators.py   EMA/SMA · RSI · MACD · Bollinger
                                    ATR · Supertrend  (TradingView math)
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                                ▼
          patterns.py                     context_providers.py
       candlestick context              macro (DXY, PAXG-vs-spot premium)
                 │                       news  (Claude-scored headlines)
                 └───────────────┬───────────────┘
                                 ▼
                         signal_engine.py
                 weighted blend → score [-100..100] + confidence
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                                ▼
            backtest.py                        api.py  (FastAPI)
       walk-forward, no look-ahead     /candles /analyze /backtest
                                                 │
                                                 ▼
                                       React dashboard (separate file)
```

## Run

```bash
pip install -r requirements.txt
uvicorn gold_analyzer.api:app --reload --port 8000
# open http://localhost:8000/docs  to try the endpoints
```

Then point the dashboard's API base at `http://localhost:8000`.

> Note: Binance market-data endpoints are geo-restricted in some regions. If
> `/candles` errors, route the host through a permitted region or swap the base
> URL in `binance_client.py` to `api.binance.us` / a mirror.

## The signal

Each component emits a sub-score in `[-1, 1]`; the weighted blend scales to
`[-100, 100]`. Defaults (`signal_engine.Weights`):

| component   | weight | source |
|-------------|:------:|--------|
| trend       | 0.30 | EMA21 vs EMA55, price vs slow EMA |
| momentum    | 0.25 | RSI(14) centered, MACD histogram |
| volatility  | 0.10 | position within Bollinger band |
| supertrend  | 0.10 | ATR Supertrend direction |
| candles     | 0.10 | engulfing / hammer / star patterns |
| macro       | 0.10 | DXY direction + PAXG-vs-spot premium |
| news        | 0.05 | Claude-scored headline sentiment |

Tune the weights to taste — they're a constructor argument, not hardcoded.

## Where to extend (the seams are already cut)

- **Live mode** — add a Binance WebSocket kline stream and call
  `signal_engine.analyze` on each closed bar; push to the dashboard over SSE/WS.
- **News** — `context_providers.news_context(headlines)` already scores
  headlines with Claude (`claude-sonnet-4-6`). Set `ANTHROPIC_API_KEY` and feed
  it your own headline source (NewsAPI, RSS, a macro calendar).
- **Macro** — fill in `context_providers.macro_context`: a DXY feed (gold is
  inversely correlated) and a spot XAU/USD feed to compute the PAXG premium.
- **Alerts** — when `analyze().score` crosses a threshold, fire Telegram/email.
  (You've built a Telegram signals bot before — same pattern.)
- **Trade execution** — deliberately absent. If you ever add it, put it behind a
  separate, explicitly-keyed module so research code can never send an order.

## Honest limits

Every layer is a *probabilistic edge at best*. TA and candlestick patterns
describe tendencies, not certainties; news sentiment is noisy and often already
priced in. Backtest results overstate live performance (no slippage model,
single asset, in-sample tuning risk). This is a tool to structure your own
decisions — not financial advice, and not a recommendation engine. Risk and
position sizing matter more than signal quality.
