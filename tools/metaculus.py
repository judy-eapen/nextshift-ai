"""Metaculus — requires a free API token since 2026 (Settings → API token). Token: METACULUS_TOKEN in .env.
Returns community recency-weighted forecast + history when available."""
import os, json
from .http import get_json
from .schema import Card, SourceResult

def metaculus_search(query: str, limit: int = 5) -> SourceResult:
    tok = os.environ.get("METACULUS_TOKEN")
    if not tok:
        return SourceResult(source="Metaculus", ok=False, error="METACULUS_TOKEN not set — create a free account at metaculus.com, Settings → API token, add to .env", unknowns=[query])
    d, err = get_json("https://www.metaculus.com/api/posts/", {"search": query, "limit": limit, "statuses": "open", "forecast_type": "binary"},
                      headers={"Authorization": f"Token {tok}"})
    if err: return SourceResult(source="Metaculus", ok=False, error=err, unknowns=[query])
    cards = []
    for post in d.get("results", []):
        q = post.get("question") or {}
        agg = ((q.get("aggregations") or {}).get("recency_weighted") or {})
        latest = agg.get("latest") or {}
        centers = latest.get("centers") or []
        if not centers: continue
        p = float(centers[0])
        hist = agg.get("history") or []
        trend = (p - float(hist[-30]["centers"][0])) if len(hist) > 30 and hist[-30].get("centers") else None
        cards.append(Card(id=f"metaculus:{post.get('id')}", family="forecasts",
                          claim=f"Metaculus community forecast is {p:.0%} for “{post.get('title')}”",
                          value=p, unit="probability", source="Metaculus", url=f"https://www.metaculus.com/questions/{post.get('id')}/",
                          as_of=(latest.get("end_time") or latest.get("start_time") or "")[:10] if isinstance(latest.get("start_time"), str) else None,
                          spread=f"{latest.get('forecaster_count', '?')} forecasters", trend_30d=trend, confidence=0.8))
    return SourceResult(source="Metaculus", ok=True, cards=cards, unknowns=[] if cards else [query])
