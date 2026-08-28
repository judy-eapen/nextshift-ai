"""Assemble the supervisor graph. START → load_memory → decompose ⇉ 4 gatherers → reconcile → ⏸worldview → build → brief → skeptic ⟲ → render → ⏸publish → record → END"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from .state import State
from . import nodes as n

CKPT = Path(__file__).resolve().parents[1] / "data" / "processed" / "checkpoints.sqlite"

def build_graph(checkpointer=None):
    g = StateGraph(State)
    for name, fn in [("load_memory", n.load_memory), ("decompose", n.decompose), ("gather_forecasts", n.gather_forecasts), ("gather_exposure", n.gather_exposure),
                     ("gather_statistics", n.gather_stats), ("gather_research", n.gather_research), ("reconcile", n.reconcile), ("worldview_gate", n.worldview_gate),
                     ("build_scenarios", n.build_scenarios), ("write_brief", n.write_brief), ("skeptic", n.skeptic), ("render", n.render),
                     ("publish_gate", n.publish_gate), ("record", n.record)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_memory"); g.add_edge("load_memory", "decompose")
    g.add_conditional_edges("decompose", n.fan_out, ["gather_forecasts", "gather_exposure", "gather_statistics", "gather_research"])
    for fam in ("forecasts", "exposure", "statistics", "research"): g.add_edge(f"gather_{fam}", "reconcile")
    g.add_edge("reconcile", "worldview_gate")
    g.add_conditional_edges("worldview_gate", n.after_worldview, {"build": "build_scenarios", "end": END})
    g.add_edge("build_scenarios", "write_brief"); g.add_edge("write_brief", "skeptic")
    g.add_conditional_edges("skeptic", n.after_skeptic, {"render": "render", "rebuild": "build_scenarios"})
    g.add_edge("render", "publish_gate")
    g.add_conditional_edges("publish_gate", n.after_publish, {"record": "record", "end": END})
    g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer or sqlite_checkpointer())

def sqlite_checkpointer():
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(CKPT, check_same_thread=False), serde=_serde())   # Streamlit runs nodes off the main thread

def _serde(): return JsonPlusSerializer(allowed_msgpack_modules=[("tools.schema", "Card")])

def memory_checkpointer(): return MemorySaver(serde=_serde())
