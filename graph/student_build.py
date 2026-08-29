"""Compile the student graph. Phase B: interview loop → understanding gate (confirm → END placeholder until Phase C adds candidates)."""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from .student import StudentState
from . import student as s
from .build import sqlite_checkpointer

def build_student_graph(checkpointer=None, phase_c=None):
    g = StateGraph(StudentState)
    for name, fn in [("init_interview", s.init_interview), ("select_question", s.select_question), ("interview_gate", s.interview_gate), ("update_profile", s.update_profile),
                     ("evaluate_completeness", s.evaluate_completeness), ("render_understanding", s.render_understanding), ("understanding_gate", s.understanding_gate)]:
        g.add_node(name, fn)
    g.add_edge(START, "init_interview"); g.add_edge("init_interview", "select_question"); g.add_edge("select_question", "interview_gate")
    g.add_edge("interview_gate", "update_profile"); g.add_edge("update_profile", "evaluate_completeness")
    g.add_conditional_edges("evaluate_completeness", s.after_completeness, {"ask": "select_question", "understanding": "render_understanding"})
    g.add_edge("render_understanding", "understanding_gate")
    targets = {"back": "select_question", "end": END, "candidates": END}
    if phase_c: phase_c(g); targets["candidates"] = "generate_candidates"
    g.add_conditional_edges("understanding_gate", s.after_understanding, targets)
    return g.compile(checkpointer=checkpointer or sqlite_checkpointer())
