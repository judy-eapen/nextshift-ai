"""Manifold Markets — public API, no key. Play-money markets, dense on AI questions. Good disagreement counterpart."""
from .http import get_json
from .schema import Card, SourceResult

def manifold_search(query: str, limit: int = 5) -> SourceResult:
    d, err = get_json("https://api.manifold.markets/v0/search-markets", {"term": query, "limit": limit, "filter": "open", "sort": "most-popular", "contractType": "BINARY"})
    if err: return SourceResult(source="Manifold", ok=False, error=err)
    cards = []
    for m in d or []:
        p = m.get("probability")
        if p is None or (m.get("uniqueBettorCount") or 0) < 30: continue   # skip thin/noisy markets
        cards.append(Card(id=f"manifold:{m.get('id')}", family="forecasts",
                          claim=f"Manifold traders put {p:.0%} on “{m.get('question')}”",
                          value=float(p), unit="probability", source="Manifold", url=m.get("url"),
                          as_of=None, spread=f"{m.get('uniqueBettorCount', 0)} traders · volume {m.get('volume', 0):,.0f} M$",
                          confidence=0.55, notes=f"closes {str(m.get('closeTime'))[:10]}; play-money market"))
    return SourceResult(source="Manifold", ok=True, cards=cards, unknowns=[] if cards else [query])
