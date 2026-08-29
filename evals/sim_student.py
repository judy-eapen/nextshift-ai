"""A simulated student for reproducible evals: a fixed persona spec answered by the EXTRACTOR model, one question at a time.
Personas can also script behaviours (answer 'I don't know' N times, ask for recommendations at turn K, edit an earlier answer)."""
from __future__ import annotations
from graph import llm

PERSONAS = {
    "no_ideas": {"name": "Maya", "spec": "17, junior in high school. Loses track of time editing videos for friends and organizing the school's charity drive. Good at noticing what people need; teachers say she's a natural coordinator. Finds calculus hard but wants to get better. Hates repetitive data entry. Prefers working with people, some technology. Values helping others and having variety. Wants to stay within a 4-year degree, cost matters (family income modest), open to moving. No career ideas at all; unsure whether 'creative' careers are realistic."},
    "three_ideas": {"name": "Devon", "spec": "18, senior. Considering graphic design, UX design and psychology. Loves figuring out why people behave as they do and making things look clear. Built a club website (demonstrated). Dislikes cold-calling and sales. Prefers ideas + people. Open to graduate school if it pays off; no location constraint; wants remote flexibility eventually."},
    "vague": {"name": "Sam", "spec": "16. Answers almost every question with some version of 'I don't know' or 'not sure' for the first five questions; after that, admits liking fixing bikes and gaming setups (hands-on + technology), dislikes writing essays, wants to earn early and avoid a long degree."},
    "cost_strict": {"name": "Priya", "spec": "18. Loves biology and caring for her grandmother; strong at memorizing and staying calm under pressure (demonstrated during a family emergency). Cannot afford more than a 2-year program right now; must stay in her city. People + hands-on. Wants stable income fast."},
    "likes_field_dislikes_work": {"name": "Leo", "spec": "17. Fascinated by medicine and the human body, but faints at blood and hates hospitals' pace and shift work; loves explaining things and drawing diagrams. Ideas + people. Open to 4-year degree."},
    "conflicting_strengths": {"name": "Ava", "spec": "17. Says she is 'really good at math' but every example she gives is about writing, debating and persuading people; when asked for a math example she can't think of one. Values winning arguments and being heard; dislikes routine."},
}

SIM_SYS = """You are role-playing a real student in a career-discovery interview. Stay in character; answer in 1-3 natural sentences a teenager would actually type — casual, sometimes uncertain, never a list of traits. Only reveal what the question asks about. Never mention that you are simulated."""

def answer(persona_key: str, question: str, history: list[dict], scripted: dict | None = None, turn: int | None = None) -> dict:
    """Returns a resume payload for interview_gate. scripted: {"unsure_until": 5, "recommend_at": 3, "more_at": 9, "edit": {"turn": 2, "text": "..."}}"""
    turn = turn or (len(history) + 1); sc = scripted or {}
    if sc.get("edit") and turn == sc["edit"].get("at") and not sc["edit"].get("done"):
        sc["edit"]["done"] = True; return {"action": "edit", "edit_turn": sc["edit"]["turn"], "text": sc["edit"]["text"]}   # one-shot: the interviewer's turn number doesn't advance on an edit
    if turn == sc.get("recommend_at"): return {"action": "recommend"}
    if turn == sc.get("more_at"): return {"action": "more"}
    if turn <= sc.get("unsure_until", 0): return {"action": "unsure"}
    p = PERSONAS[persona_key]; convo = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history[-4:])
    try: text, _ = llm.chat("extractor", SIM_SYS, f"You are {p['name']}: {p['spec']}\n\nConversation so far:\n{convo}\n\nInterviewer asks: {question}\nYour answer:", max_tokens=120, temperature=0.7)
    except Exception: text = "I'm not really sure."
    return {"action": "answer", "text": text.strip().strip('"')}
