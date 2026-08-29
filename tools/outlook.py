"""Employment outlook cards from the offline landscape (BLS Employment Projections 2025–35 + OES 2025), one occupation at a time.
Composites have no SOC row: we return the closest official categories' projections, clearly labelled as proxies, plus an explicit unknown."""
from __future__ import annotations
from functools import lru_cache
import pandas as pd
from pathlib import Path
from .schema import Card, SourceResult

LAND = Path(__file__).resolve().parents[1] / "data" / "processed" / "landscape.parquet"
URL = "https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm"
NATIONAL_GROWTH = 3.5   # Table 1.1, all occupations 2025–35

@lru_cache(maxsize=1)
def _land() -> pd.DataFrame: return pd.read_parquet(LAND).set_index("soc")

def _cards(soc: str, title: str, occ_tag: str, proxy: bool = False) -> list[Card]:
    if soc not in _land().index: return []
    r = _land().loc[soc]; pre = f"Closest official category {title} ({soc}): " if proxy else f"{title}: "
    conf = 0.6 if proxy else 0.95; cards = []
    def add(id_, claim, value, unit, **kw): cards.append(Card(id=f"bls:proj:{soc}:{id_}", family="statistics", occ=occ_tag, claim=pre + claim, value=value, unit=unit, source="BLS", url=URL, as_of="2025-12-01", confidence=conf, **kw))
    if pd.notna(r.get("growth_pct_10y")):
        g = float(r.growth_pct_10y); add("growth", f"BLS projects employment to change {g:+.1f}% from 2025 to 2035 (all occupations: {NATIONAL_GROWTH:+.1f}%)", g, "percent", spread=f"vs national {NATIONAL_GROWTH:+.1f}%")
    if pd.notna(r.get("emp_change_k_10y")): add("change", f"BLS projects {float(r.emp_change_k_10y):+,.1f} thousand jobs added or lost, 2025–35", float(r.emp_change_k_10y) * 1000, "jobs")
    if pd.notna(r.get("openings_annual_k")): add("openings", f"BLS projects about {float(r.openings_annual_k):,.1f} thousand openings per year on average, 2025–35 (growth plus replacement)", float(r.openings_annual_k) * 1000, "jobs")
    if pd.notna(r.get("emp_2025_k")): add("emp2025", f"{float(r.emp_2025_k):,.1f} thousand people employed in 2025 (BLS projections base year)", float(r.emp_2025_k) * 1000, "jobs")
    if isinstance(r.get("education_entry"), str): add("education", f"Typical education needed for entry: {r.education_entry}" + (f"; work experience: {r.experience_entry}" if isinstance(r.get("experience_entry"), str) and r.experience_entry != "None" else "") + (f"; on-the-job training: {r.training_entry}" if isinstance(r.get("training_entry"), str) and r.training_entry != "None" else ""), None, "text")
    if pd.notna(r.get("median_wage")): add("wage", f"Median annual wage ${float(r.median_wage):,.0f} (OES {r.get('oes_year', '2025')})", float(r.median_wage), "usd")
    return cards

def outlook_cards(persona: dict) -> SourceResult:
    if not persona.get("composite"):
        cards = _cards(persona["soc"], persona["title"], persona["soc"])
        return SourceResult(source="BLS", ok=True, cards=cards, unknowns=[] if cards else [f"BLS: no employment projection row for {persona['title']} ({persona['soc']})"])
    # composite: proxies from the occupations that contributed the most tasks
    counts = pd.Series([t["onet_soc"][:7] for t in persona.get("tasks", [])]).value_counts().head(3)
    land = _land(); titles = {s: (land.loc[s, "title"] if s in land.index else next(t["title"] for t in persona["tasks"] if t["onet_soc"][:7] == s)) for s in counts.index}   # BLS 6-digit category names, not detailed O*NET titles
    cards = [c for soc in counts.index for c in _cards(soc, titles.get(soc, soc), persona["soc"], proxy=True)]
    return SourceResult(source="BLS", ok=True, cards=cards, unknowns=[f"BLS: no employment projection exists for “{persona['title']}” — the SOC taxonomy has no such occupation; the closest official categories ({', '.join(titles.get(s, s) for s in counts.index)}) are shown as proxies and labelled"])
