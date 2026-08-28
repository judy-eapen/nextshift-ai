"""Epoch AI notable models — local CSV, refreshed by re-downloading epoch.ai/data/notable_ai_models.csv."""
from pathlib import Path
import pandas as pd
from functools import lru_cache
from .schema import Card, SourceResult
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

@lru_cache(maxsize=1)
def _df():
    d = pd.read_csv(RAW / "epoch_notable_models.csv", low_memory=False)
    d["date"] = pd.to_datetime(d["Publication date"], errors="coerce"); d["flop"] = pd.to_numeric(d["Training compute (FLOP)"], errors="coerce")
    return d

def epoch_recent(days: int = 180, min_flop: float = 1e25) -> SourceResult:
    d = _df(); cutoff = d.date.max() - pd.Timedelta(days=days)
    big = d[(d.date >= cutoff) & (d.flop >= min_flop)].sort_values("date", ascending=False)
    cards = [Card(id=f"epoch:{r.Model}", family="research", claim=f"{r.Model} ({r.Organization}) trained with ~{r.flop:.1e} FLOP, published {r.date.date()}",
                  value=float(r.flop), unit="flop", source="Epoch AI", url="https://epoch.ai/data/ai-models", as_of=str(r.date.date()), confidence=0.85)
             for _, r in big.head(8).iterrows()]
    summary = Card(id=f"epoch:count:{days}d", family="research", claim=f"{len(big)} notable models at ≥{min_flop:.0e} FLOP were published in the last {days} days (through {d.date.max().date()})",
                   value=float(len(big)), unit="count", source="Epoch AI", url="https://epoch.ai/data/ai-models", as_of=str(d.date.max().date()), confidence=0.85)
    return SourceResult(source="Epoch AI", ok=True, cards=[summary] + cards)
