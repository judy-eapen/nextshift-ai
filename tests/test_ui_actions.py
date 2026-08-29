"""Interview actions: immediate status, duplicate-submit guard, answer preserved on failure (tests 4 and 5)."""
import types, pytest
import streamlit as st
from ui import student_ui as U

class FakeStatus:
    def __init__(self, *a, **k): self.updates = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def update(self, **k): self.updates.append(k)
    def write(self, *a, **k): pass

@pytest.fixture
def ui(monkeypatch):
    statuses = []
    def fake_status(label, **k): s = FakeStatus(); s.label = label; statuses.append(s); return s
    monkeypatch.setattr(st, "status", fake_status); monkeypatch.setattr(st, "write", lambda *a, **k: None); monkeypatch.setattr(U, "route", lambda S, p: S.__setitem__("routed", p))
    return statuses

class Sess(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v

def test_duplicate_submission_runs_graph_once(ui, monkeypatch):
    calls = []
    monkeypatch.setattr(U, "run", lambda S, inp, box=None: (calls.append(inp), {"kind": "interview", "turn": 4})[1])
    S = Sess(); U.act(S, {"action": "answer", "text": "hi"}, "Understanding your answer…", "Next question ready", guard="answer:3")
    U.act(S, {"action": "answer", "text": "hi"}, "Understanding your answer…", "Next question ready", guard="answer:3")   # double click / rerun
    assert len(calls) == 1 and S["routed"]["turn"] == 4 and ui[0].label == "Understanding your answer…" and ui[0].updates[-1]["state"] == "complete"

def test_failed_resume_preserves_answer_and_allows_retry(ui, monkeypatch):
    attempts = []
    def flaky(S, inp, box=None):
        attempts.append(1)
        if len(attempts) == 1: raise RuntimeError("endpoint down")
        return {"kind": "interview", "turn": 4}
    monkeypatch.setattr(U, "run", flaky)
    S = Sess(); S.pending_answer = "my long answer"
    U.act(S, {"action": "answer", "text": "my long answer"}, "Understanding your answer…", guard="answer:3")
    assert S.pending_answer == "my long answer" and S.last_error == "RuntimeError" and "routed" not in S and ui[0].updates[-1]["state"] == "error" and S.submitted is None
    U.act(S, {"action": "answer", "text": "my long answer"}, "Understanding your answer…", guard="answer:3")   # retry with the same token is allowed after a failure
    assert len(attempts) == 2 and S["routed"]["turn"] == 4 and S.pending_answer is None

def test_status_shows_phase_copy_lines(monkeypatch):
    lines = []
    class Box:
        def write(self, s): lines.append(s)
    class G:
        def stream(self, inp, cfg, stream_mode): 
            yield ("custom", {"phase": "profile", "t": 0}); yield ("custom", {"phase": "completeness", "t": 0}); yield ("custom", {"say": "Learned: interests", "t": 0}); yield ("custom", {"phase": "question", "t": 0})
            yield ("updates", {"__interrupt__": [types.SimpleNamespace(value={"kind": "interview"})]})
    monkeypatch.setattr(U, "sgraph", lambda: G())
    S = Sess(); S.thread_id = "t"; S.log = []
    out = U.run(S, None, Box()); assert out == {"kind": "interview"}
    assert lines == ["· Adding what you shared to your profile…", "· Checking what remains unclear…", "· Learned: interests", "· Choosing the next useful question…"] and S.phase is None
