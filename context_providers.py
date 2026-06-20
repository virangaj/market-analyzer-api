"""
Context providers — the non-price inputs for the signal engine.

These are the parts you'll flesh out as you add real feeds. Each returns a
piece of signal_engine.Context. They're deliberately isolated so the price
engine keeps working even if a feed is down or unconfigured.

  macro_context()  -> DXY direction + PAXG-vs-spot-gold premium
  news_context()   -> LLM-scored headline sentiment for gold

Both degrade to neutral (0) on any failure.
"""
from __future__ import annotations

import os
import json

import requests

from signal_engine import Context


# --------------------------------------------------------------------------
# MACRO: dollar direction + the PAXG/spot-gold premium (gold's biggest tell)
# --------------------------------------------------------------------------
def macro_context(paxg_price: float | None = None) -> Context:
    """
    Gold is strongly INVERSELY correlated with the US dollar (DXY), and PAXG
    can trade at a premium/discount to physical gold. Both are edges most
    generic crypto bots ignore.

    Plug in:
      - DXY: any FX/markets data provider, or a futures feed.
      - spot XAU/USD: a metals API (e.g. metals-api, GoldAPI, your broker).
    Compute premium = (paxg_price - spot_xau) / spot_xau, then normalize.
    Returns neutral until you wire the feeds.
    """
    notes = []
    dxy_score = 0.0
    premium_score = 0.0

    # TODO: replace with a real DXY feed; +ve when dollar weakening (bullish gold)
    # TODO: fetch spot XAU/USD and compute premium vs paxg_price
    if paxg_price is not None:
        notes.append(f"PAXG last: {paxg_price:.2f} (spot-gold premium not wired)")

    return Context(dxy_score=dxy_score, premium_score=premium_score, notes=notes)


# --------------------------------------------------------------------------
# NEWS: LLM-scored sentiment, gold-specific (macro reasoning beats keywords)
# --------------------------------------------------------------------------
_PROMPT = (
    "You are a gold-market analyst. Given these headlines, rate the NET impact "
    "on the gold price over the next few days. Respond with ONLY a JSON object: "
    '{{"score": <float -1..1>, "rationale": "<one sentence>"}}. '
    "Positive = bullish for gold (e.g. dollar weakness, falling real yields, "
    "rate-cut odds, risk-off, geopolitical stress). Negative = bearish.\n\n"
    "Headlines:\n{headlines}"
)


def news_context(headlines: list[str]) -> Context:
    """
    Score a batch of headlines with Claude. Requires ANTHROPIC_API_KEY in env.
    You supply `headlines` from whatever news source you prefer (NewsAPI,
    an RSS pull, a macro calendar, etc.). Falls back to neutral on any error.
    """
    if not headlines:
        return Context(news_score=0.0, notes=["no headlines"])
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return Context(news_score=0.0, notes=["ANTHROPIC_API_KEY not set; news neutral"])

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "messages": [
                    {"role": "user", "content": _PROMPT.format(headlines="\n".join(f"- {h}" for h in headlines))}
                ],
            },
            timeout=30,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        score = max(-1.0, min(1.0, float(data["score"])))
        return Context(news_score=score, notes=[data.get("rationale", "")])
    except Exception as e:  # noqa: BLE001 — never let news break the pipeline
        return Context(news_score=0.0, notes=[f"news scoring failed: {e}"])


def combine(*contexts: Context) -> Context:
    """Merge several Context objects (macro + news) into one."""
    out = Context()
    for c in contexts:
        out.dxy_score += c.dxy_score
        out.premium_score += c.premium_score
        out.news_score += c.news_score
        out.notes.extend(c.notes)
    return out
