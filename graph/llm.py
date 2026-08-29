"""All LLM calls go through Nebius Token Factory (OpenAI-compatible). Three roles, three models (see .env):
PLANNER (decompose, assumptions, scenarios, brief) · SKEPTIC (a different model family — reflection must not share the planner's blind spots) ·
EXTRACTOR (cheap, high-volume: relevance filtering). Every call returns (text, cost_usd) so the graph can enforce the $ cap."""
from __future__ import annotations
import os, json, re, time
from langchain_openai import ChatOpenAI
from . import diag

# rough $/1M tokens (input, output) — estimates for the cost cap, not billing
PRICES = {"Qwen/Qwen3-235B-A22B-Instruct-2507": (0.20, 0.60), "Qwen/Qwen3-Next-80B-A3B-Thinking": (0.15, 0.45), "Qwen/Qwen3-30B-A3B-Instruct-2507": (0.10, 0.30)}
ROLE_ENV = {"planner": "PLANNER_MODEL", "skeptic": "SKEPTIC_MODEL", "extractor": "EXTRACTOR_MODEL"}
DEFAULTS = {"planner": "Qwen/Qwen3-235B-A22B-Instruct-2507", "skeptic": "Qwen/Qwen3-Next-80B-A3B-Thinking", "extractor": "Qwen/Qwen3-30B-A3B-Instruct-2507"}

def model_name(role: str) -> str: return os.environ.get(ROLE_ENV[role], DEFAULTS[role])

def _client(role: str, temperature: float, max_tokens: int) -> ChatOpenAI:
    return ChatOpenAI(model=model_name(role), api_key=os.environ["NEBIUS_API_KEY"],
                      base_url=os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/"),
                      temperature=temperature, max_tokens=max_tokens, timeout=120, max_retries=1)   # fail fast into node-level fallbacks rather than stall a run

def chat(role: str, system: str, user: str, temperature: float = 0.2, max_tokens: int = 2000, purpose: str = "") -> tuple[str, float]:
    t0 = time.perf_counter()
    try: msg = _client(role, temperature, max_tokens).invoke([("system", system), ("user", user)])
    except Exception as e:
        diag.emit("llm", role=role, model=model_name(role), purpose=purpose, ms=round((time.perf_counter() - t0) * 1000), ok=False, error=type(e).__name__, max_tokens=max_tokens); raise
    usage = msg.usage_metadata or {}; pin, pout = PRICES.get(model_name(role), (0.3, 0.9))
    cost = (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6
    diag.emit("llm", role=role, model=model_name(role), purpose=purpose, ms=round((time.perf_counter() - t0) * 1000), ok=True, tokens_in=usage.get("input_tokens", 0), tokens_out=usage.get("output_tokens", 0), cost_usd=round(cost, 6), max_tokens=max_tokens)
    text = msg.content if isinstance(msg.content, str) else "".join(getattr(p, "text", str(p)) for p in msg.content)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # thinking models may emit reasoning tags
    return text, cost

def chat_json(role: str, system: str, user: str, **kw) -> tuple[dict | list, float]:
    """Ask for JSON, tolerate fences/preamble. Raises ValueError if unparseable (caller decides how to degrade)."""
    text, cost = chat(role, system + "\nRespond with valid JSON only — no prose, no markdown fences.", user, **kw)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0: raise ValueError(f"no JSON in model output: {text[:200]}")
    try: obj, _ = json.JSONDecoder().raw_decode(text[start:])          # first complete object; ignores trailing chatter
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not m: raise
        obj = json.loads(m.group(1))
    return obj, cost
