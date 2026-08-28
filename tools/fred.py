"""FRED — macro series. Free key, 120 req/min."""
import os
from .http import get_json
from .schema import Card, SourceResult

SERIES = {
    "UNRATE":  ("US unemployment rate", "percent"),
    "CIVPART": ("US labor force participation rate", "percent"),
    "OPHNFB":  ("Nonfarm business labor productivity (index)", "index"),
    "CPIAUCSL":("CPI, all urban consumers (index)", "index"),
}

def fred_series(series_id: str, n: int = 24) -> SourceResult:
    key = os.environ.get("FRED_API_KEY")
    if not key: return SourceResult(source="FRED", ok=False, error="FRED_API_KEY not set")
    d, err = get_json("https://api.stlouisfed.org/fred/series/observations",
                      {"series_id": series_id, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": n})
    if err: return SourceResult(source="FRED", ok=False, error=err)
    obs = [o for o in d.get("observations", []) if o.get("value") not in (".", None)]
    if not obs: return SourceResult(source="FRED", ok=False, error=f"no observations for {series_id}")
    latest, label = obs[0], SERIES.get(series_id, (series_id, ""))
    prev = obs[1] if len(obs) > 1 else None
    trend = (float(latest["value"]) - float(prev["value"])) if prev else None
    card = Card(id=f"fred:{series_id}:{latest['date']}", family="statistics",
                claim=f"{label[0]} was {latest['value']}{'%' if label[1]=='percent' else ''} as of {latest['date']}",
                value=float(latest["value"]), unit=label[1], source="FRED",
                url=f"https://fred.stlouisfed.org/series/{series_id}", as_of=latest["date"],
                trend_30d=trend, confidence=0.95, notes=f"{len(obs)} obs returned")
    return SourceResult(source="FRED", ok=True, cards=[card])
