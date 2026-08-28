"""BLS — OES employment + median wage per SOC via the public API (v2, key)."""
import os
from .http import post_json
from .schema import Card, SourceResult

def _oes_id(soc: str, datatype: str) -> str:
    return f"OEUN0000000000000{soc.replace('-', '')}{datatype}"   # OEU + N + area(7 zeros) + industry(6 zeros) + SOC(6) + datatype: 01 employment, 13 annual median wage

def bls_occupation(soc: str) -> SourceResult:
    """soc like '11-2021'. Returns employment + median wage cards."""
    key = os.environ.get("BLS_API_KEY")
    if not key: return SourceResult(source="BLS", ok=False, error="BLS_API_KEY not set")
    soc6 = soc[:7]
    ids = [_oes_id(soc6, "01"), _oes_id(soc6, "13")]
    d, err = post_json("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                       {"seriesid": ids, "startyear": "2023", "endyear": "2026", "registrationkey": key})
    if err: return SourceResult(source="BLS", ok=False, error=err)
    if d.get("status") != "REQUEST_SUCCEEDED": return SourceResult(source="BLS", ok=False, error=str(d.get("message")))
    cards, unknowns = [], []
    for s in d["Results"]["series"]:
        data = s.get("data") or []
        if not data: unknowns.append(s["seriesID"]); continue
        latest = data[0]; year = latest["year"]; val = float(latest["value"].replace(",", ""))
        if s["seriesID"].endswith("01"):
            cards.append(Card(id=f"bls:oes:{soc6}:emp:{year}", family="statistics", claim=f"{val:,.0f} people employed in SOC {soc6} (OES {year})",
                              value=val, unit="jobs", source="BLS", url=f"https://www.bls.gov/oes/current/oes{soc6.replace('-','')}.htm", as_of=f"{year}-05-01", confidence=0.95))
        else:
            cards.append(Card(id=f"bls:oes:{soc6}:wage:{year}", family="statistics", claim=f"Median annual wage for SOC {soc6} was ${val:,.0f} (OES {year})",
                              value=val, unit="usd", source="BLS", url=f"https://www.bls.gov/oes/current/oes{soc6.replace('-','')}.htm", as_of=f"{year}-05-01", confidence=0.95))
    return SourceResult(source="BLS", ok=bool(cards), cards=cards, unknowns=unknowns, error=None if cards else "no OES data for this SOC")

def bls_batch(series_ids: list[str]) -> tuple[dict, str | None]:
    """Up to 50 series per call. Returns {series_id: (year, value)}."""
    key = os.environ.get("BLS_API_KEY")
    d, err = post_json("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                       {"seriesid": series_ids[:50], "startyear": "2024", "endyear": "2026", "registrationkey": key}, timeout=60)
    if err: return {}, err
    out = {}
    for s in d.get("Results", {}).get("series", []):
        data = s.get("data") or []
        if not data: continue
        v = data[0]["value"].replace(",", "")
        if v in ("-", "*", "**", "#", ""): continue          # BLS suppression markers
        try: out[s["seriesID"]] = (data[0]["year"], float(v))
        except ValueError: continue
    return out, None
