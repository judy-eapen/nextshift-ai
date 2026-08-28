"""Offline join → data/processed/landscape.parquet: one row per SOC with title, AIOE, AEI exposure, BLS employment + wage.
BLS projections (growth) column left null until bls_occupation_projections.xlsx is present (manual download)."""
import os, sys, time, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from tools.exposure import _aioe, _aei_jobs; from tools.bls import bls_batch, _oes_id
RAW = os.path.join(os.path.dirname(__file__), "raw"); OUT = os.path.join(os.path.dirname(__file__), "processed", "landscape.parquet")

occ = pd.read_csv(os.path.join(RAW, "onet_occupation_data.csv")).rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title"})
occ["soc"] = occ.onet_soc.str[:7]; base = occ[occ.onet_soc.str.endswith(".00")][["soc", "title"]].drop_duplicates("soc")
df = base.merge(_aioe()[["soc", "aioe", "aioe_lm", "aioe_pct", "aioe_lm_pct"]], on="soc", how="left").merge(_aei_jobs()[["soc", "observed_exposure"]], on="soc", how="left")
print(f"{len(df)} occupations; AIOE coverage {df.aioe.notna().mean():.0%}; AEI coverage {df.observed_exposure.notna().mean():.0%}")

cache = os.path.join(os.path.dirname(__file__), "processed", "bls_oes_cache.parquet")
if os.path.exists(cache): oes = pd.read_parquet(cache); print("using cached OES")
else:
    ids = [ _oes_id(s, dt) for s in df.soc for dt in ("01", "13") ]; got = {}
    for i in range(0, len(ids), 50):
        chunk, err = bls_batch(ids[i:i+50]); got.update(chunk)
        if err: print("BLS batch error:", err); break
        time.sleep(0.4); print(f"  BLS {i+50}/{len(ids)}", end="\r")
    rows = []
    for s in df.soc:
        e = got.get(_oes_id(s, "01")); w = got.get(_oes_id(s, "13"))
        rows.append({"soc": s, "employment": e[1] if e else None, "median_wage": w[1] if w else None, "oes_year": (e or w or (None, None))[0]})
    oes = pd.DataFrame(rows); oes.to_parquet(cache, index=False); print()
df = df.merge(oes, on="soc", how="left")
proj = os.path.join(RAW, "bls_occupation_projections.xlsx")
df["growth_pct_10y"] = None
if os.path.exists(proj):
    try:
        p = pd.read_excel(proj, header=1); code_col = next(c for c in p.columns if "code" in str(c).lower()); pct_col = next(c for c in p.columns if "percent" in str(c).lower())
        p = p[[code_col, pct_col]].rename(columns={code_col: "soc", pct_col: "growth_pct_10y"}); p["soc"] = p.soc.astype(str).str[:7]
        df = df.drop(columns=["growth_pct_10y"]).merge(p.drop_duplicates("soc"), on="soc", how="left"); print("projections merged")
    except Exception as e: print("projections file present but not parsed:", e)
df.to_parquet(OUT, index=False)
print(f"wrote {OUT}: {len(df)} rows; employment coverage {df.employment.notna().mean():.0%}; wage coverage {df.median_wage.notna().mean():.0%}")
print(df[df.soc == "11-2021"].T)
