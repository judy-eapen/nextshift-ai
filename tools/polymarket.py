"""Polymarket Gamma API — public, no key. Market price ~ probability."""
import json
from .http import get_json
from .schema import Card, SourceResult

def polymarket_search(query: str, limit: int = 5, include_closed: bool = False) -> SourceResult:
    d, err = get_json("https://gamma-api.polymarket.com/public-search", {"q": query, "limit_per_type": limit})
    if err: return SourceResult(source="Polymarket", ok=False, error=err)
    cards = []
    for ev in d.get("events", []):
        for m in ev.get("markets") or []:
            if m.get("closed") and not include_closed: continue
            try:
                outcomes = json.loads(m.get("outcomes") or "[]"); prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
            except Exception: continue
            if not outcomes or not prices: continue
            yes_idx = outcomes.index("Yes") if "Yes" in outcomes else 0
            p = prices[yes_idx]
            cards.append(Card(id=f"polymarket:{m.get('id')}", family="forecasts",
                              claim=f"Market price implies {p:.0%} probability: “{m.get('question')}”",
                              value=p, unit="probability", source="Polymarket",
                              url=f"https://polymarket.com/event/{ev.get('slug')}", as_of=(m.get("updatedAt") or "")[:10],
                              spread=f"volume ${float(m.get('volume') or 0):,.0f}", confidence=0.7,
                              notes=f"ends {str(m.get('endDate'))[:10]}"))
    if not cards: return SourceResult(source="Polymarket", ok=True, cards=[], unknowns=[query], error=None)
    return SourceResult(source="Polymarket", ok=True, cards=cards[:limit])
