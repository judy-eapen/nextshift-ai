"""Exposure gatherer's data: AIOE (Felten), Anthropic Economic Index, O*NET tasks. All local files in data/raw/."""
from pathlib import Path
import pandas as pd
from functools import lru_cache
from .schema import Card, SourceResult

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

@lru_cache(maxsize=1)
def _aioe() -> pd.DataFrame:
    a = pd.read_excel(RAW / "aioe_AIOE_DataAppendix.xlsx", sheet_name="Appendix A")
    a.columns = ["soc", "title", "aioe"]
    lm = pd.read_excel(RAW / "aioe_Language_Modeling_AIOE_and_AIIE.xlsx", sheet_name="LM AIOE")
    lm.columns = [c.lower().replace(" ", "_") for c in lm.columns]
    soc_col = next(c for c in lm.columns if "soc" in c); val_col = next(c for c in lm.columns if "aioe" in c and c != soc_col)
    lm = lm.rename(columns={soc_col: "soc", val_col: "aioe_lm"})[["soc", "aioe_lm"]]
    df = a.merge(lm, on="soc", how="left")
    df["soc"] = df["soc"].astype(str).str[:7]
    df["aioe_pct"] = df["aioe"].rank(pct=True); df["aioe_lm_pct"] = df["aioe_lm"].rank(pct=True)
    return df

@lru_cache(maxsize=1)
def _aei_jobs() -> pd.DataFrame:
    return pd.read_csv(RAW / "aei" / "job_exposure.csv").rename(columns={"occ_code": "soc"})

@lru_cache(maxsize=1)
def _aei_tasks() -> pd.DataFrame:
    return pd.read_csv(RAW / "aei" / "task_penetration.csv")

@lru_cache(maxsize=1)
def _onet_tasks() -> pd.DataFrame:
    t = pd.read_csv(RAW / "onet_task_statements.csv")
    t = t.rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Task": "task", "Task Type": "task_type"})
    t["soc"] = t["onet_soc"].str[:7]
    return t

def aioe_lookup(soc: str) -> SourceResult:
    df = _aioe(); row = df[df.soc == soc[:7]]
    if row.empty: return SourceResult(source="AIOE", ok=True, cards=[], unknowns=[f"AIOE score for {soc}"])
    r = row.iloc[0]; cards = [
        Card(id=f"aioe:{soc}", family="exposure", claim=f"{r.title} has an AI Occupational Exposure score of {r.aioe:.2f} (percentile {r.aioe_pct:.0%} of occupations)",
             value=float(r.aioe), unit="score", source="AIOE", url="https://github.com/AIOE-Data/AIOE", as_of="2023-01-01", spread=f"range −2.67 to 1.58", confidence=0.85,
             notes="Felten, Raj & Seamans; links AI capabilities to the 52 O*NET abilities an occupation uses")]
    if pd.notna(r.get("aioe_lm")):
        cards.append(Card(id=f"aioe_lm:{soc}", family="exposure", claim=f"Language-model-specific exposure for {r.title}: {r.aioe_lm:.2f} (percentile {r.aioe_lm_pct:.0%})",
             value=float(r.aioe_lm), unit="score", source="AIOE", url="https://github.com/AIOE-Data/AIOE", as_of="2023-01-01", confidence=0.85))
    return SourceResult(source="AIOE", ok=True, cards=cards)

def anthropic_index(soc: str) -> SourceResult:
    j = _aei_jobs(); row = j[j.soc == soc[:7]]
    if row.empty: return SourceResult(source="Anthropic Economic Index", ok=True, cards=[], unknowns=[f"observed AI exposure for {soc}"])
    r = row.iloc[0]
    pct = (j.observed_exposure < r.observed_exposure).mean()
    return SourceResult(source="Anthropic Economic Index", ok=True, cards=[
        Card(id=f"aei:job:{soc}", family="exposure", claim=f"{r.observed_exposure:.0%} of {r.title} tasks show observed AI usage (percentile {pct:.0%} of 756 occupations)",
             value=float(r.observed_exposure), unit="share", source="Anthropic Economic Index",
             url="https://huggingface.co/datasets/Anthropic/EconomicIndex", as_of="2025-03-27", confidence=0.8,
             notes="Observed usage on one vendor's platform, not a forecast; labor_market_impacts/job_exposure.csv")])

def onet_task_diff(soc: str) -> SourceResult:
    """Every task for the occupation, joined to AEI task penetration. Raw material for the task-diff board."""
    t = _onet_tasks(); rows = t[t.soc == soc[:7]]
    if rows.empty: return SourceResult(source="O*NET", ok=True, cards=[], unknowns=[f"task list for {soc}"])
    pen = _aei_tasks().drop_duplicates("task").set_index("task")["penetration"]
    cards = []
    for _, r in rows.iterrows():
        p = pen.get(r.task)
        cards.append(Card(id=f"onet:task:{r['Task ID']}", family="exposure",
                          claim=r.task, value=(None if p is None or pd.isna(p) else float(p)), unit="penetration",
                          source="O*NET + Anthropic Economic Index", url=f"https://www.onetonline.org/link/summary/{r.onet_soc}",
                          as_of="2025-03-27", confidence=0.75 if p is not None and not pd.isna(p) else 0.4,
                          notes=f"{r.task_type} task; penetration = share of observed AI conversations touching this task (None = not observed)"))
    return SourceResult(source="O*NET", ok=True, cards=cards)
