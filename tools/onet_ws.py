"""O*NET Web Services v2 (key: ONET_API_KEY, header X-API-Key). Live occupation detail — bright-outlook tag, description,
technology skills. Note: O*NET's own keyword search is weak (630 hits for 'product owner'); tools/resolve.py stays the primary resolver."""
import os
from .http import get_json
from .schema import Card, SourceResult
BASE = "https://api-v2.onetcenter.org/online"

def _h(): return {"X-API-Key": os.environ.get("ONET_API_KEY", "")}

def onet_occupation(onet_soc: str) -> SourceResult:
    """onet_soc like '11-2021.00'. Cards: description + bright outlook (+ technology skills if present). Cached 30 days by code + O*NET version."""
    from . import cache
    if not os.environ.get("ONET_API_KEY"): return SourceResult(source="O*NET Web Services", ok=False, error="ONET_API_KEY not set")
    key = cache.key_for("onet_ws", onet_soc=onet_soc)
    if not cache.disabled() and (hit := cache.get("onet_ws", key)) is not None: return cache.load_result(hit)
    r = _onet_occupation_live(onet_soc)
    if r.ok and not cache.disabled(): cache.put("onet_ws", key, cache.dump_result(r))
    return r

def _onet_occupation_live(onet_soc: str) -> SourceResult:
    d, err = get_json(f"{BASE}/occupations/{onet_soc}", headers=_h())
    if err: return SourceResult(source="O*NET Web Services", ok=False, error=err)
    url = f"https://www.onetonline.org/link/summary/{onet_soc}"; cards = [
        Card(id=f"onetws:desc:{onet_soc}", family="exposure", claim=f"{d.get('title')}: {d.get('description')}", source="O*NET", url=url, as_of="2026-08-01", confidence=0.95, unit="text"),
        Card(id=f"onetws:outlook:{onet_soc}", family="statistics", claim=f"{d.get('title')} is {'' if (d.get('tags') or {}).get('bright_outlook') else 'not '}tagged Bright Outlook by O*NET (rapid growth, many openings, or new/emerging)",
             value=1.0 if (d.get('tags') or {}).get('bright_outlook') else 0.0, unit="flag", source="O*NET", url=url, as_of="2026-08-01", confidence=0.9)]
    t, err2 = get_json(f"{BASE}/occupations/{onet_soc}/summary/technology_skills", headers=_h())
    if not err2 and t:
        names = [c.get("title", {}).get("name") if isinstance(c.get("title"), dict) else c.get("title") for c in (t.get("category") or [])][:8]
        names = [n for n in names if n]
        if names: cards.append(Card(id=f"onetws:tech:{onet_soc}", family="exposure", claim=f"Technology skills for {d.get('title')}: {', '.join(names)}", source="O*NET", url=url, as_of="2026-08-01", confidence=0.85, unit="text"))
    return SourceResult(source="O*NET Web Services", ok=True, cards=cards)

def onet_keyword_search(keyword: str, limit: int = 5) -> list[dict]:
    d, err = get_json(f"{BASE}/search", params={"keyword": keyword, "end": limit}, headers=_h())
    if err or not d: return []
    return [{"onet_soc": o.get("code"), "title": o.get("title"), "relevance": o.get("relevance_score")} for o in d.get("occupation", [])[:limit]]
