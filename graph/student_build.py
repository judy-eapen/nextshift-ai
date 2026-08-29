"""Compile the student graph: interview loop → ⏸ understanding → candidates → LIGHT evidence (official outlook, local O*NET description; parallel) → light cards →
fast review → ⏸ results/reactions → DEEP evidence for the reacted-to careers only (task-level AI use; parallel) → detailed cards → thinking review → discriminators →
shortlist → ⏸ shortlist gate → deep dive → ⏸ explore → … → ⏸ save → record. One graph, one thread, several interrupts."""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from .student import StudentState
from . import student as s, student_explore as x, nodes as n, diag
from .build import sqlite_checkpointer

LIGHT_GATHERERS = ["gather_forecasts", "gather_research", "gather_outlook"]

def build_student_graph(checkpointer=None):
    g = StateGraph(StudentState)
    for name, fn in [("init_interview", s.init_interview), ("select_question", s.select_question), ("interview_gate", s.interview_gate), ("update_profile", s.update_profile),
                     ("evaluate_completeness", s.evaluate_completeness), ("render_understanding", s.render_understanding), ("understanding_gate", s.understanding_gate),
                     ("generate_candidates", x.generate_candidates), ("resolve_candidates", x.resolve_candidates),
                     ("gather_forecasts", n.gather_forecasts), ("gather_research", n.gather_research), ("gather_outlook", n.gather_outlook), ("gather_exposure", n.gather_exposure),
                     ("reconcile", n.reconcile), ("write_outlook", n.write_outlook), ("analyze_fit_light", x.analyze_fit_light), ("review_cards_light", x.review_cards), ("render_results", x.render_results),
                     ("reaction_gate", x.reaction_gate), ("update_from_reactions", x.update_from_reactions),
                     ("reconcile_deep", n.reconcile), ("write_outlook_deep", n.write_outlook), ("analyze_fit", x.analyze_fit), ("review_cards", x.review_cards), ("refresh_results", x.render_results), ("deepen_one", x.deepen_one),
                     ("discriminate", x.discriminate), ("discriminator_gate", x.discriminator_gate), ("apply_discriminators", x.apply_discriminators),
                     ("build_shortlist", x.build_shortlist), ("shortlist_gate", x.shortlist_gate), ("deep_dive", x.deep_dive), ("explore_gate", x.explore_gate), ("explore", x.explore),
                     ("save_gate", x.save_gate), ("record", x.record)]:
        g.add_node(name, diag.timed(name, fn))
    # interview loop
    g.add_edge(START, "init_interview"); g.add_edge("init_interview", "select_question"); g.add_edge("select_question", "interview_gate")
    g.add_edge("interview_gate", "update_profile"); g.add_edge("update_profile", "evaluate_completeness")
    g.add_conditional_edges("evaluate_completeness", s.after_completeness, {"ask": "select_question", "understanding": "render_understanding"})
    g.add_edge("render_understanding", "understanding_gate")
    g.add_conditional_edges("understanding_gate", s.after_understanding, {"back": "select_question", "end": END, "candidates": "generate_candidates"})
    # Level A: candidates → light evidence → light cards → fast review → results
    g.add_edge("generate_candidates", "resolve_candidates")
    g.add_conditional_edges("resolve_candidates", x.fan_out_light, LIGHT_GATHERERS)
    for gname in LIGHT_GATHERERS: g.add_edge(gname, "reconcile")
    g.add_edge("reconcile", "write_outlook"); g.add_edge("write_outlook", "analyze_fit_light"); g.add_edge("analyze_fit_light", "review_cards_light"); g.add_edge("review_cards_light", "render_results"); g.add_edge("render_results", "reaction_gate")
    g.add_conditional_edges("reaction_gate", x.after_reactions, {"update": "update_from_reactions", "end": END, "regen": "generate_candidates"})
    # Level B: deep evidence for the reacted-to set (or a picked career) → detailed cards → thinking review → refreshed results → continue
    g.add_conditional_edges("update_from_reactions", x.fan_out_deep, ["gather_exposure", "discriminate", "deep_dive"])
    g.add_conditional_edges("deepen_one", x.fan_out_deep, ["gather_exposure", "discriminate", "deep_dive"])
    g.add_edge("gather_exposure", "reconcile_deep"); g.add_edge("reconcile_deep", "write_outlook_deep"); g.add_edge("write_outlook_deep", "analyze_fit"); g.add_edge("analyze_fit", "review_cards"); g.add_edge("review_cards", "refresh_results")
    g.add_conditional_edges("refresh_results", x.after_refresh, {"discriminate": "discriminate", "deep_dive": "deep_dive"})
    g.add_conditional_edges("discriminate", x.after_discriminate, {"ask": "discriminator_gate", "shortlist": "build_shortlist"})
    g.add_edge("discriminator_gate", "apply_discriminators"); g.add_edge("apply_discriminators", "build_shortlist"); g.add_edge("build_shortlist", "shortlist_gate")
    g.add_conditional_edges("shortlist_gate", x.after_shortlist, {"deep_dive": "deep_dive", "deepen": "deepen_one", "explore": "explore", "results": "render_results", "save": "save_gate", "end": END})
    g.add_edge("deep_dive", "explore_gate")
    g.add_conditional_edges("explore_gate", x.after_explore, {"save": "save_gate", "end": END, "shortlist": "shortlist_gate", "deep_dive": "deep_dive", "deepen": "deepen_one", "results": "render_results", "explore": "explore"})
    g.add_edge("explore", "shortlist_gate")
    g.add_conditional_edges("save_gate", x.after_save, {"record": "record", "end": END}); g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer or sqlite_checkpointer())
