"""Metaculus — requires a free API token (Settings → API token) as METACULUS_TOKEN. Search + question metadata work with a basic token.
Aggregate community predictions (aggregations.recency_weighted) come back null for accounts without data-access approval —
request it at https://www.metaculus.com/api . Until then this tool returns *metadata cards* (question, forecaster count, link)
with value=None and confidence 0.3, so the reconciler treats Metaculus as 'question exists, value unknown' rather than inventing a number."""
import os, json
from .http import get_json
from .schema import Card, SourceResult

def metaculus_search(query: str, limit: int = 5) -> SourceResult:
    tok = os.environ.get("METACULUS_TOKEN")
    if not tok:
        return SourceResult(source="Metaculus", ok=False, error="METACULUS_TOKEN not set — create a free account at metaculus.com, Settings → API token, add to .env", unknowns=[query])
    d, err = get_json("https://www.metaculus.com/api/posts/", {"search": query, "limit": limit, "statuses": "open", "forecast_type": "binary", "with_cp": "true", "order_by": "-forecasters_count"},
                      headers={"Authorization": f"Token {tok}"})
    if err: return SourceResult(source="Metaculus", ok=False, error=err, unknowns=[query])
    cards = []
    for post in d.get("results", []):
        q = post.get("question") or {}
        agg = ((q.get("aggregations") or {}).get("recency_weighted") or {})
        latest = agg.get("latest") or {}
        centers = latest.get("centers") or []
        if not centers:
            cards.append(Card(id=f"metaculus:{post.get('id')}", family="forecasts",
                              claim=f"Metaculus question exists: “{post.get('title')}” ({post.get('nr_forecasters', '?')} forecasters) — community value not available to this API account",
                              value=None, unit="probability", source="Metaculus", url=f"https://www.metaculus.com/questions/{post.get('id')}/",
                              spread=f"{post.get('nr_forecasters', '?')} forecasters", confidence=0.3,
                              notes="aggregations null: request API data access at metaculus.com/api, or read the value on the question page"))
            continue
        p = float(centers[0])
        hist = agg.get("history") or []
        trend = (p - float(hist[-30]["centers"][0])) if len(hist) > 30 and hist[-30].get("centers") else None
        cards.append(Card(id=f"metaculus:{post.get('id')}", family="forecasts",
                          claim=f"Metaculus community forecast is {p:.0%} for “{post.get('title')}”",
                          value=p, unit="probability", source="Metaculus", url=f"https://www.metaculus.com/questions/{post.get('id')}/",
                          as_of=(latest.get("end_time") or latest.get("start_time") or "")[:10] if isinstance(latest.get("start_time"), str) else None,
                          spread=f"{latest.get('forecaster_count', '?')} forecasters", trend_30d=trend, confidence=0.8))
    has_values = any(c.value is not None for c in cards)
    return SourceResult(source="Metaculus", ok=True, cards=cards, unknowns=[] if has_values else [f"{query} (Metaculus values restricted for this account)"])
