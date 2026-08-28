"""The shared notebook every node reads and writes. Reducers (Annotated) let the four gatherers append concurrently."""
from __future__ import annotations
import operator
from typing import Annotated, Literal, Optional, TypedDict
from tools.schema import Card

def merge_dicts(a: dict | None, b: dict | None) -> dict: return {**(a or {}), **(b or {})}

class Persona(TypedDict):
    soc: str; onet_soc: str; title: str; matched_via: str; horizon: int   # 2030 | 2035

class Worldview(TypedDict, total=False):
    """Interrupt-1 payload AND resume payload — same shape so the UI is a form, not a text box."""
    soc: str; title: str; horizon: int
    anchor_question: str            # the forecast question the AGI branch hangs on
    anchor_card_ids: list[str]
    scenario_names: list[str]
    claims: list[str]               # editable one-line assumptions written by the planner
    edited: bool

class State(TypedDict, total=False):
    # input
    question: str; door: Literal["professional", "student"]; persona: Persona; thread_id: str
    # memory
    prior_snapshot: Optional[dict]
    # decompose
    subquestions: list[dict]        # {id, text, family, why}
    # gather (reducers — four gatherers write concurrently)
    evidence: Annotated[list[Card], operator.add]
    unknowns: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    source_status: Annotated[dict, merge_dicts]   # {source: "ok" | "partial" | "unavailable"}
    tool_calls: Annotated[int, operator.add]
    cost_usd: Annotated[float, operator.add]
    # reconcile
    refs: dict                      # short citation ref (c01) → card id; what the models cite and the skeptic checks
    disagreements: list[dict]       # {topic, card_ids, low, high, spread}
    worldview: Worldview
    # build
    scenarios: list[dict]           # {name, color, prob_low, prob_high, prob_card_ids, prob_note, assumptions, for_you, evidence_refs}
    task_diff: dict                 # {scenario_name: {disappears:[{card_id, task, eff}], supervised:[...], grows:[...]}}
    brief_draft: str
    # skeptic
    skeptic: dict                   # {stripped:[{sentence, reason}], kept, total, ratio, attempt, escalated}
    # output
    brief_md: str
    views: dict
    deltas: list[dict]
    approvals: dict                 # {worldview: {...}, publish: {...}}
    exported_path: Optional[str]
