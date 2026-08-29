"""Assemble the supervisor graph (redesign).
START → load_memory → understand → ⏸ understanding_gate ⇉ Send×(forecasts, research, outlook×occ, exposure×occ) → reconcile → write_outlook → write_plan → skeptic ⟲ → render → ⏸ plan_gate → record → END"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from .state import State
from . import nodes as n, diag

CKPT = Path(__file__).resolve().parents[1] / "data" / "processed" / "checkpoints.sqlite"
GATHERERS = ["gather_forecasts", "gather_research", "gather_outlook", "gather_exposure"]

def build_graph(checkpointer=None):
    g = StateGraph(State)
    for name, fn in [("load_memory", n.load_memory), ("understand", n.understand), ("understanding_gate", n.understanding_gate),
                     ("gather_forecasts", n.gather_forecasts), ("gather_research", n.gather_research), ("gather_outlook", n.gather_outlook), ("gather_exposure", n.gather_exposure),
                     ("reconcile", n.reconcile), ("write_outlook", n.write_outlook), ("write_plan", n.write_plan), ("skeptic", n.skeptic),
                     ("render", n.render), ("plan_gate", n.plan_gate), ("record", n.record)]:
        g.add_node(name, diag.timed(name, fn))
    g.add_edge(START, "load_memory"); g.add_edge("load_memory", "understand"); g.add_edge("understand", "understanding_gate")
    g.add_conditional_edges("understanding_gate", lambda s: n.fan_out(s) if n.after_understanding(s) == "gather" else END, GATHERERS + [END])
    for x in GATHERERS: g.add_edge(x, "reconcile")
    g.add_edge("reconcile", "write_outlook"); g.add_edge("write_outlook", "write_plan"); g.add_edge("write_plan", "skeptic")
    g.add_conditional_edges("skeptic", n.after_skeptic, {"render": "render", "rewrite": "write_plan"})
    g.add_edge("render", "plan_gate")
    g.add_conditional_edges("plan_gate", n.after_plan, {"record": "record", "end": END})
    g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer or sqlite_checkpointer())

def _serde(): return JsonPlusSerializer(allowed_msgpack_modules=[("tools.schema", "Card")])

def sqlite_checkpointer():
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(CKPT, check_same_thread=False), serde=_serde())   # Streamlit runs nodes off the main thread

def memory_checkpointer(): return MemorySaver(serde=_serde())
