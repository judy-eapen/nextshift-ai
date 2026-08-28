"""Occupation search: how people name their jobs → official SOC code. Uses O*NET reported titles + occupation titles."""
from pathlib import Path
import pandas as pd, re
from functools import lru_cache
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

@lru_cache(maxsize=1)
def _index() -> pd.DataFrame:
    occ = pd.read_csv(RAW / "onet_occupation_data.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title"})
    rep = pd.read_csv(RAW / "onet_reported_titles.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Reported Job Title": "alias"})
    jt = pd.read_csv(RAW / "onet_job_titles.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Job Title": "alias"})  # 54K lay titles
    a = pd.concat([occ.assign(alias=occ.title)[["onet_soc", "title", "alias"]], rep[["onet_soc", "title", "alias"]], jt[["onet_soc", "title", "alias"]]])
    a["soc"] = a.onet_soc.str[:7]; a["alias_l"] = a.alias.str.lower()
    return a.drop_duplicates(["soc", "alias_l"])

def search_occupations(query: str, limit: int = 5) -> list[dict]:
    """Returns [{soc, onet_soc, title, matched_alias, exact}] — exact alias matches first, then substring."""
    q = query.strip().lower(); idx = _index()
    exact = idx[idx.alias_l == q]; sub = idx[idx.alias_l.str.contains(re.escape(q)) & (idx.alias_l != q)]
    out, seen = [], set()
    for df, ex in ((exact, True), (sub, False)):
        for _, r in df.iterrows():
            if r.soc in seen: continue
            seen.add(r.soc); out.append({"soc": r.soc, "onet_soc": r.onet_soc, "title": r.title, "matched_alias": r.alias, "exact": ex})
            if len(out) >= limit: return out
    return out
