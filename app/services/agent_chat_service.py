"""
Agent onboarding chat — a Grok-powered conversational assistant whose ONLY job is
to pin down what a single agent should research, then lock that in as the agent's
core role.

Unlike the general preference chat (see ``preferences_chat_service``), this flow
is intentionally short and bounded: greet -> user states what they want -> Leora
reflects a summary back with exactly three sharpening follow-ups -> user answers
-> Leora locks in a finalized research directive and ends the conversation. A
hard turn cap guarantees the chat can never loop indefinitely even if the model
misbehaves.
"""

import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)

# Hard safety cap — after this many user messages we force a lock-in regardless
# of what the model wants to do next, so the chat can never run away.
MAX_USER_TURNS = 4

SYSTEM_PROMPT = """You are Leora, an onboarding assistant with exactly ONE job: figure out \
precisely what a single research agent should watch/research for its owner, then lock that \
in. You are not a general chatbot — do not answer questions, do not research anything \
yourself, do not make small talk beyond what's needed.

Follow this exact flow:
1. First turn (no user messages yet): greet warmly as Leora in one short sentence and ask \
what updates they want to hear about from this agent. complete=false, locked=null.
2. As soon as the user describes what they want: reply with (a) a one-to-two sentence \
summary reflecting their intent back to them, and (b) exactly THREE short, concrete \
follow-up questions (numbered 1-3) that would sharpen the agent's research focus — pick \
whichever three matter most for what they said (e.g. specific sub-topics or names to track, \
angle/lens to prioritize, what to exclude, comparison set, time horizon, risk appetite). \
complete=false, locked=null.
3. After the user answers those follow-ups (even partially, even if they just say "that's \
fine" / "lock it in"): produce the final lock-in and STOP — do not ask anything else. Set \
complete=true and fully populate "locked".

Hard rule: you must never go past TWO user messages before finalizing. If you are about to \
ask a third round of questions, stop yourself and finalize instead using your best judgement \
from whatever context you have.

Output STRICT JSON only — no markdown, no code fences, no text outside the JSON. Shape exactly:
{
  "reply": "<message to show the user>",
  "complete": <true|false>,
  "locked": null OR {
    "topic": "<short 3-8 word niche label>",
    "summary": "<1-2 sentence plain-English description of exactly what this agent will research and deliver — written to show the user what they'll receive>",
    "core_prompt": "<a detailed, self-contained research directive written in second person to the research agent, e.g. 'Research and report on...'. Include the topic, the angle/focus, what to prioritize, what to exclude, and the kind of insight the user wants (e.g. best bets, rising trends).>",
    "keywords": ["<keyword>", ...],
    "region": "<Global|US|India|UK|Europe|...>"
  }
}
"""

FORCE_FINALIZE_NUDGE = (
    "(You have asked enough questions already. Finalize now using your best judgement from "
    "the conversation so far — do not ask anything else. Set complete=true and fully populate "
    "locked.)"
)


def chat_agent_onboarding(messages: list[dict]) -> dict:
    """
    Advance the agent-onboarding conversation by one assistant turn.

    Args:
        messages: prior conversation as [{"role": "user"|"assistant", "content": str}, ...].

    Returns:
        dict: {"reply": str, "complete": bool, "locked": dict | None}
    """
    llm = get_llm()
    history = messages or []
    user_turns = sum(1 for m in history if (m.get("role") or "user").lower() == "user")

    lc_messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for m in history:
        role = (m.get("role") or "user").lower()
        content = m.get("content", "") or ""
        lc_messages.append(AIMessage(content=content) if role == "assistant" else HumanMessage(content=content))

    if user_turns == 0:
        lc_messages.append(HumanMessage(content="(The user just opened the chat. Greet them and ask your first question.)"))
    elif user_turns >= MAX_USER_TURNS:
        lc_messages.append(HumanMessage(content=FORCE_FINALIZE_NUDGE))

    response = llm.invoke(lc_messages)
    raw = response.content if isinstance(response.content, str) else _flatten(response.content)
    result = _parse(raw)

    # Safety net: never let the conversation hang past the hard cap, and never
    # report complete=true without a usable locked payload.
    if user_turns >= MAX_USER_TURNS and (not result["complete"] or not result["locked"]):
        result = _force_lock(result, history)

    return result


# ── Internal helpers ─────────────────────────────────────────────

def _flatten(content) -> str:
    """Flatten a list-of-blocks message into plain text."""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _parse(raw: str) -> dict:
    """Tolerantly parse the model's JSON reply."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    data: dict = {}
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                logger.warning("Could not parse agent onboarding chat JSON; returning raw text.")

    if not isinstance(data, dict) or "reply" not in data:
        return {"reply": text or "Sorry, could you say that again?", "complete": False, "locked": None}

    locked = data.get("locked")
    if isinstance(locked, dict) and locked.get("topic") and locked.get("core_prompt"):
        locked = {
            "topic": str(locked.get("topic", "")).strip(),
            "summary": str(locked.get("summary", "")).strip(),
            "core_prompt": str(locked.get("core_prompt", "")).strip(),
            "keywords": [k for k in (locked.get("keywords") or []) if k],
            "region": locked.get("region") or "Global",
        }
    else:
        locked = None

    return {
        "reply": str(data.get("reply", "")).strip(),
        "complete": bool(data.get("complete", False)) and locked is not None,
        "locked": locked,
    }


def _force_lock(result: dict, history: list[dict]) -> dict:
    """Synthesize a usable lock-in from whatever the conversation contains so far."""
    user_texts = [str(m.get("content", "")).strip() for m in history if (m.get("role") or "user").lower() == "user"]
    combined = " ".join(t for t in user_texts if t) or "General updates"
    topic = combined[:60] + ("…" if len(combined) > 60 else "")
    locked = result.get("locked") or {
        "topic": topic,
        "summary": f"This agent will research and summarize the latest on: {combined}",
        "core_prompt": f"Research and report on: {combined}. Prioritize the most significant, recent developments and explain why each matters.",
        "keywords": [],
        "region": "Global",
    }
    reply = result.get("reply") or f"Got it — I've locked this agent in to cover: {locked['topic']}."
    return {"reply": reply, "complete": True, "locked": locked}
