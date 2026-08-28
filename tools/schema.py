"""Shared contracts every gatherer returns. This is the message contract between agents (Lesson 32)."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Family = Literal["forecasts", "exposure", "statistics", "research"]

class Card(BaseModel):
    """One piece of evidence. Every claim the agent makes must trace to one of these."""
    id: str
    family: Family
    subq_id: Optional[str] = None
    claim: str                      # plain-English statement of what this card supports
    value: Optional[float] = None   # the number (probability 0-1, %, count, $, score)
    unit: str = ""                  # "probability" | "percent" | "jobs" | "usd" | "score" | "count"
    source: str                     # "Metaculus" | "Polymarket" | "Manifold" | "AIOE" | "Anthropic Economic Index" | "O*NET" | "BLS" | "FRED" | "Epoch AI"
    url: Optional[str] = None
    as_of: Optional[str] = None     # ISO date of the observation
    spread: Optional[str] = None    # e.g. "25–31%" or "n=1,842 forecasters"
    trend_30d: Optional[float] = None
    confidence: float = Field(0.5, ge=0, le=1)  # how much the gatherer trusts this card
    notes: str = ""

class SourceResult(BaseModel):
    """What a tool returns. Never raises — errors are data the agent can reason about."""
    source: str
    ok: bool
    cards: list[Card] = []
    error: Optional[str] = None
    unknowns: list[str] = []        # sub-questions this source could not answer
