"""Explorer → interview bridge (deterministic). When a student arrives at the interview from the Career Explorer, the careers they saved and how they
reacted become *profile evidence* — quoted as what they did while browsing, never as a decision — and a few targeted comparison questions are
templated from the catalog's trait/education profiles of those careers. No model is involved here; the interview's model only interprets answers."""
from __future__ import annotations
from tools import catalog as C

REACTION_LABEL = {"interesting": "interesting", "maybe": "maybe", "no": "not for me", "understand": "I want to understand this better"}
POSITIVE = ("interesting", "maybe", "understand")

def seed_evidence(seed: dict | None) -> dict[str, list[dict]]:
    """Profile additions keyed by field. Saved/positive → existing_career_ideas; 'not for me' → dislikes. source_turn 0 = 'from the Career Explorer'."""
    if not seed or not seed.get("saved"): return {}
    ideas, dislikes = [], []
    for s in seed["saved"]:
        rx = s.get("reaction") or "saved"; lab = REACTION_LABEL.get(rx, "saved")
        if rx == "no": dislikes.append({"value": f"{s['title']} (ruled out while browsing)", "quote": f"Marked “{lab}” in the Career Explorer", "source_turn": 0, "kind": "stated"})
        else: ideas.append({"value": s["title"], "quote": f"Saved in the Career Explorer, reaction “{lab}”. Saving is not choosing.", "source_turn": 0, "kind": "stated"})   # short value: it is quoted back by clarifying questions
    out = {}
    if ideas: out["existing_career_ideas"] = ideas
    if dislikes: out["dislikes"] = dislikes
    return out

_PAIR_QUESTIONS = [   # (trait present only in A, trait present only in B) → question. Checked in both orders.
    (("creativity", "analysis"), "You saved {A} and {B}. Are you more drawn to visual or creative creation, or to solving analytical, functional problems?"),
    (("helping", "technology"), "You saved {A} and {B}. Is working directly with people the draw for you, or working with technology and systems?"),
    (("outdoors", "technology"), "You saved {A} and {B}. Does being outdoors and on the move matter to you, or would you be just as happy at a desk?"),
    (("building", "communication"), "You saved {A} and {B}. Would you rather make or fix things with your hands, or explain and persuade with words?"),
    (("helping", "analysis"), "You saved {A} and {B}. When you picture a good day, is it helping a particular person, or working out a hard problem?"),
    (("creativity", "helping"), "You saved {A} and {B}. Is it making something new that pulls you, or being there for people?"),
    (("outdoors", "helping"), "You saved {A} and {B}. Would you trade an indoor, people-centred day for an outdoor one — or the other way round?"),
]

def seed_questions(seed: dict | None, limit: int = 3) -> list[str]:
    """Targeted comparison questions from the saved careers' catalog profiles. Deterministic; returns [] when nothing useful can be asked."""
    if not seed or not seed.get("saved"): return []
    recs = [(s, C.get(s["id"])) for s in seed["saved"] if (s.get("reaction") or "saved") != "no"]
    recs = [(s, r) for s, r in recs if r]
    pairs: list[str] = []
    for i in range(len(recs)):   # pairwise trait forks (careers whose profiles differ on a trait)
        for j in range(i + 1, len(recs)):
            (sa, a), (sb, b) = recs[i], recs[j]; ta, tb = set(a.traits), set(b.traits)
            for (x, y), q in _PAIR_QUESTIONS:
                if x in ta - tb and y in tb - ta: pairs.append(q.format(A=a.title, B=b.title)); break
                if y in ta - tb and x in tb - ta: pairs.append(q.format(A=b.title, B=a.title)); break
    edu = next((f"You saved {r.title}, which typically needs {(r.education_entry or 'many years of preparation').lower()}. How important is it to you to start working soon rather than spend years in school first?"
                for s, r in recs if s.get("reaction") in ("maybe", "understand") and ((r.job_zone or 0) >= 5 or (r.education_entry or "").startswith(("Doctoral", "Master")))), None)
    understand = next((f"You marked {r.title} as something you want to understand better. What would you want to know before deciding whether it could be for you?" for s, r in recs if s.get("reaction") == "understand"), None)
    shared_q = None; helping = [r.title for _, r in recs if "helping" in r.traits]
    if len(helping) >= 2: shared_q = f"Several careers you saved involve helping people directly ({helping[0]} and {helping[1]}). Does that feel energizing to you, or draining after a while?"
    else:
        for tid in ("creativity", "technology", "analysis", "building", "outdoors", "communication"):
            shared = [r.title for _, r in recs if tid in r.traits]
            if len(shared) >= 2: shared_q = f"Several careers you saved involve {C.TRAITS[tid]['label'].lower()} ({shared[0]} and {shared[1]}). Is that the part that draws you, or something else about them?"; break
    ordered = [pairs[0] if pairs else None, edu, understand, shared_q] + pairs[1:]     # priority: one fork · preparation · 'understand better' · shared theme · more forks
    return list(dict.fromkeys(q for q in ordered if q))[:limit]

def seed_summary(seed: dict | None) -> list[str]:
    """Plain lines for the UI: what the interview knows from the explorer."""
    if not seed or not seed.get("saved"): return []
    return [f"{s['title']} — {REACTION_LABEL.get(s.get('reaction') or 'saved', 'saved')}" for s in seed["saved"]]
