"""The shared notebook every node reads and writes. Reducers (Annotated) let parallel gatherers append concurrently.
Redesign (Sat 2026-08-28): the person (Profile) and 1–3 occupation targets are first-class; the output is a Plan, not a scenario tree."""
from __future__ import annotations
import operator
from typing import Annotated, Literal, Optional, TypedDict
from tools.schema import Card

def merge_dicts(a: dict | None, b: dict | None) -> dict: return {**(a or {}), **(b or {})}

class Persona(TypedDict, total=False):
    soc: str; onet_soc: str; title: str; matched_via: str
    composite: bool; tasks: list[dict]; source_occupations: list[str]; note: str   # composite occupations only

class Profile(TypedDict, total=False):
    """The person — everything the understanding gate shows and the plan personalizes on."""
    door: Literal["student", "professional"]
    interests: list[str]; strengths: list[str]; constraints: dict          # student: education_max, cost, location, remote, lifestyle
    role_title: str; week_description: str; industry: str                  # professional
    concerns: list[Literal["demand", "change", "learn", "pivot"]]
    horizon: str                                                           # "1-2y" | "2030" | "2035"
    question: str
    summary: str                                                           # paragraph shown at the understanding gate (editable)

class OccupationTarget(TypedDict):
    persona: Persona; role: Literal["current", "candidate"]

class Outlook(TypedDict, total=False):
    """Per occupation. Facts (official projections) are kept apart from AI-related interpretation."""
    soc: str; title: str
    demand_reading: Literal["growing", "stable", "declining", "unknown"]    # from BLS 2025–35 projection only
    ai_change_reading: Literal["substantial", "moderate", "limited", "unknown"]  # from observed task penetration — an interpretation
    facts: list[str]                                                       # templated, cited lines
    interpretation: list[str]                                              # model-written, cited, tagged [interpretation]
    education_entry: Optional[str]; proxy_note: Optional[str]              # composites: which official categories the facts come from

class WorkChange(TypedDict, total=False):
    """Replaces task_diff. No multipliers, no 'disappears', no 'grows'."""
    soc: str
    ai_assists: list[dict]        # observed penetration ≥ 0.60 — fact: AI is already used heavily for this task today
    more_important: list[dict]    # low observed use AND a stated reason it resists delegation — interpretation, cited
    uncertain: list[dict]         # 0.25–0.60, or not observed and no reason given
    method_note: str

class Plan(TypedDict, total=False):
    direct_answer: str; outlook_takeaway: str; for_you: str
    d30: list[str]; m6: list[str]; y1: list[str]
    adjacent: list[dict]          # {title, why_fit, transferable, prep, outlook, tradeoff} — may be empty
    adjacent_note: str            # why empty, when empty
    comparison: list[dict]        # student: one row per candidate occupation
    our_read: str                 # student: which direction(s) and why
    confidence: dict              # {strong: [...], interpretation: [...], unknown: [...], disagree: [...]}

class State(TypedDict, total=False):
    # input
    profile: Profile; targets: list[OccupationTarget]; thread_id: str
    # memory
    prior_snapshot: Optional[dict]
    # gather (reducers — gatherers write concurrently)
    evidence: Annotated[list[Card], operator.add]
    unknowns: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    source_status: Annotated[dict, merge_dicts]
    tool_calls: Annotated[int, operator.add]
    cost_usd: Annotated[float, operator.add]
    # reconcile
    refs: dict; disagreements: list[dict]; deltas: list[dict]
    forecast_context: list[str]   # cited conditional sentences about pace, from forecast cards
    # analysis
    outlooks: dict                # soc → Outlook
    changes: dict                 # soc → WorkChange
    plan: Plan
    plan_md: str                  # the whole plan as markdown (what the skeptic checks and what gets exported)
    # review
    skeptic: dict
    # output
    views: dict; approvals: dict; exported_path: Optional[str]
