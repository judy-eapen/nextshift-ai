"""Small, realistic payloads shaped exactly like the graph's interrupt values (see graph/student_explore.py render_results, graph/nodes.py render)."""
import copy

PROFILE_REFS = {"p:interests:0": "interests: film — “editing videos for friends”", "p:energizing_activities:0": "energizing_activities: organizing — “organizing the school's charity drive”",
                "p:education_constraints:0": "education_constraints: up to a 4-year degree — “I'd stay within a four-year degree”", "p:dislikes:0": "dislikes: data entry — “I hate repetitive data entry”"}

def candidate(key="k1", label="Video Producer", group="strong", resolution="official (tier 1)", removed=None, demand="growing"):
    return {"key": key, "label": label, "group": group, "resolution": resolution, "resolver_note": "", "persona": {"soc": "27-2012", "onet_soc": "27-2012.00", "title": "Producers and Directors"},
            "rationale": {"matches_interests": ["You enjoy editing video for friends [p:interests:0]"], "uses_strengths": ["You organized the charity drive [p:energizing_activities:0]"], "fits_preferences": [],
                          "constraints_ok": ["A bachelor's is typical, within your limit [p:education_constraints:0]"], "constraints_conflict": [], "why_included": "You said this is where you lose track of time [p:interests:0]", "poor_fit_if": "Long irregular hours bother you."},
            "card": {"why_fit": "You enjoy visual storytelling and organizing people [p:interests:0] [p:energizing_activities:0].", "what_work_is_like": "Producers coordinate crews and schedules [c01].",
                     "how_ai_may_reshape": "AI is already used for rough cuts and captioning [c02] [interpretation].", "human_capabilities": "Directing people on set stays with humans [c03] [interpretation].",
                     "tradeoff": "Irregular hours and freelance income are common [c01] [interpretation].", "constraint_flags": [], "evidence_confidence": "moderate — one BLS card and eight task cards",
                     "demand_reading": demand, "ai_change_reading": "moderate", "facts": ["Projected change 2025–35: +7% [c01]", "Typical education: Bachelor's degree [c01]", "Annual openings: 15,400 [c01]"],
                     "education_entry": "Bachelor's degree", "proxy_note": None, "ai_assists": [{"task": "Edit footage", "penetration": 0.71, "ref": "c02", "card_id": "x2"}], "more_important": [{"task": "Direct cast and crew", "ref": "c03", "why": "requires live judgment [c03] [interpretation]", "card_id": "x3"}]},
            "review": {"removed": removed or []}}

def views(review_status="verified", sources=None, removed=None):
    sources = sources or {"BLS": "ok", "O*NET": "ok", "Anthropic Economic Index": "ok", "Polymarket": "ok", "Manifold": "ok", "Epoch AI": "ok", "FRED": "ok"}
    removed = removed if removed is not None else [{"path": "candidates[0].card.why_fit#1", "sentence": "This career is a perfect fit for you and is safe from AI [c01].", "reason": "certainty about the future (lint)"}]
    unavailable = [k for k, v in sources.items() if v == "unavailable"]
    badges = ([f"Partial evidence — unavailable: {', '.join(unavailable)}"] if unavailable else []) + [f"Checked — {len(removed)} line(s) removed for lacking support"]
    if review_status == "unverified": badges.insert(0, "⚠ UNVERIFIED — our independent review step failed, so these cards were checked for citations only, not for accuracy. Treat them as a draft.")
    c1 = candidate(removed=removed); c2 = candidate("k2", "Community Program Coordinator", "explore", "composite"); c2["card"]["proxy_note"] = "closest official categories: Social and Community Service Managers; Meeting, Convention, and Event Planners"; c2["card"]["demand_reading"] = "unknown"
    return {"badges": badges, "review_status": review_status, "groups": {"strong": [c1], "explore": [c2], "unexpected": [], "reconsider": []},
            "group_label": {"strong": "Strong matches", "explore": "Worth exploring", "unexpected": "Unexpected possibilities", "reconsider": "Your ideas, reconsidered"},
            "disagreements": [], "forecast_context": ["If AI progress is fast, adoption in media may accelerate [c07] [interpretation]"], "unknowns": ["No official projection exists for composite roles [u01]"], "source_status": sources,
            "skeptic": {"stripped": removed, "kept": 40, "total": 41, "ratio": 0.02, "status": review_status, "model": "Qwen/Qwen3-Next-80B-A3B-Thinking", "attempt": 1, "escalated": False, "rationale_lines_removed": 1},
            "cards_by_family": {"statistics": [{"id": "bls-27-2012", "claim": "Projected change +7%", "source": "BLS", "as_of": "2025", "url": "https://bls.gov"}], "exposure": [], "forecasts": [], "research": []},
            "budget": {"tool_calls": 22, "cost_usd": 0.0712}, "profile_refs": PROFILE_REFS}

def results_payload(**kw): return {"kind": "results", "views": views(**kw)}

def interview_payload():
    return {"kind": "interview", "turn": 3, "max_turns": 14, "goal": "strengths_example", "question": "What's something people come to you for help with?", "learned": ["interests: film"], "coverage": {}, "can_recommend": True,
            "previous": [{"i": 1, "question": "What do you lose track of time doing?", "answer": "editing videos for friends"}, {"i": 2, "question": "Which subjects pull you in?", "answer": "film and psychology"}],
            "profile": {"interests": [{"value": "film", "quote": "editing videos for friends", "source_turn": 1, "kind": "stated"}], "energizing_activities": [{"value": "organizing", "quote": "organizing the school's charity drive", "source_turn": 1, "kind": "stated"}],
                        "demonstrated_strengths": [], "claimed_strengths": [], "growth_areas": [{"value": "calculus", "quote": "calculus is hard but I want to get better", "source_turn": 2, "kind": "stated"}], "not_yet_learned": [], "dislikes": [], "work_preferences": [],
                        "pidth": {"people": 0.6, "technology": 0.3}, "values": [], "desired_impact": [], "lifestyle_preferences": [], "education_constraints": [], "financial_constraints": [], "location_constraints": [], "time_constraints": [],
                        "existing_career_ideas": [], "uncertainties": [], "contradictions": [], "unresolved_questions": []}}
