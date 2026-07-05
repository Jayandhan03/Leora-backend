"""
LLM service — Grok (xAI) powered agent and news summarization.
"""

import re
import logging

from langchain_xai import ChatXAI
from langgraph.prebuilt import create_react_agent
from langchain_tavily import TavilySearch
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.services.news_service import fetch_news

logger = logging.getLogger(__name__)

# ── LLM Initialization ──────────────────────────────────────────

_llm_model: ChatXAI | None = None

if not settings.XAI_API_KEY:
    logger.warning("XAI_API_KEY not set — LLM endpoints will be unavailable.")
else:
    _llm_model = ChatXAI(
        api_key=settings.XAI_API_KEY,
        model="grok-4-fast-reasoning",
        temperature=0,
        max_retries=3,
        timeout=120,
    )


def _require_llm() -> ChatXAI:
    """Return the LLM instance or raise if unavailable."""
    if _llm_model is None:
        raise ValueError("XAI_API_KEY is not configured — cannot use LLM features.")
    return _llm_model


def get_llm() -> ChatXAI:
    """Public accessor for the shared Grok LLM instance."""
    return _require_llm()


# ── Helpers ──────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Fix broken spacing (e.g. '8 0 M i l l i o n' → '80 Million')."""
    text = re.sub(r'(?<=\b\w)\s(?=\w\b)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Public API ───────────────────────────────────────────────────

def run_agent(topic: str) -> str:
    """
    Run the LangChain ReAct agent to search the web and summarize
    the latest news for the given topic.
    """
    llm = _require_llm()

    # 1. Fetch fresh news context from RapidAPI
    news_context = ""
    try:
        news_data = fetch_news(query=topic, limit=3)
        if news_data and "data" in news_data:
            for article in news_data["data"]:
                news_context += f"- {article.get('title')}: {article.get('link')}\n"
    except Exception as exc:
        logger.warning("Could not pre-fetch news for agent context: %s", exc)

    # 2. Build and invoke the agent
    search = TavilySearch(max_results=2)
    agent_executor = create_react_agent(model=llm, tools=[search])

    task_input = (
        f"Find the latest news about {topic}. "
        f"Here is some initial news context to consider:\n{news_context}\n"
        "Summarize the most important findings in clear bullet points."
    )

    response = agent_executor.invoke({"messages": [("user", task_input)]})

    # 3. Extract the final AI message
    final_text = _extract_ai_text(response)
    return clean_text(final_text) if final_text else "No summary generated."


def summarize_news(topic: str, articles: list[dict], language: str = "English") -> str:
    """
    Build a broadcast-style news summary from raw article dicts
    using the Grok LLM, written entirely in `language`.
    """
    llm = _require_llm()

    if not articles:
        return "No articles found for this topic."

    article_lines = []
    for i, art in enumerate(articles, 1):
        title = art.get("title", "(no title)")
        snippet = art.get("snippet", art.get("description", ""))
        published = art.get("published_datetime", art.get("date", ""))
        link = art.get("link", art.get("url", ""))
        article_lines.append(
            f"[{i}] TITLE: {title}\n"
            f"    DATE: {published}\n"
            f"    SNIPPET: {snippet}\n"
            f"    URL: {link}"
        )
    raw_context = "\n\n".join(article_lines)

    system_prompt = (
        "You are IndustryEar, a professional AI news anchor. "
        "Your job is to transform raw news headlines into a polished, "
        "engaging audio-ready news brief that is easy and pleasant to hear. "
        "Rules:\n"
        "  1. Open with a warm, one-sentence welcome that names the topic.\n"
        "  2. Present stories in order of importance (most significant first). "
        "     For each story you cover:\n"
        "       a. State the headline clearly.\n"
        "       b. Explain what happened in 1-2 concise sentences.\n"
        "       c. Add one short clause on why it matters to the listener.\n"
        "  3. Separate stories with a brief transition phrase (e.g., 'Moving on...', 'Next up...').\n"
        "  4. Close with a brief, upbeat sign-off (one sentence).\n"
        f"  5. Write the ENTIRE brief in {language} — every sentence, including the welcome "
        f"and sign-off. Do not mix in any other language, even for proper nouns' surrounding "
        f"text. Use plain, conversational {language} — no bullet points, no markdown.\n"
        "  6. Do NOT invent facts; only use what is in the provided articles.\n"
        "  7. LENGTH — this is spoken aloud, not read, and must never run past 3 minutes: "
        "target 300-380 words total, and never exceed 420 words under any circumstance. "
        "If the word budget isn't enough to cover every provided story, cover only the "
        "most significant ones fully rather than skimming all of them thinly — a shorter, "
        "well-told brief beats a rushed, complete one."
    )

    human_prompt = (
        f"Topic: {topic}\n\n"
        f"Here are today's articles:\n\n{raw_context}\n\n"
        f"Please produce the news summary now, entirely in {language}, following your anchor guidelines."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt),
    ]

    response = llm.invoke(messages)
    return response.content.strip()


# ── Internal helpers ─────────────────────────────────────────────

def _extract_ai_text(response: dict) -> str | None:
    """Walk response messages in reverse to find the final AI text."""
    for msg in reversed(response.get("messages", [])):
        if msg.type == "ai" and msg.content:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if block.get("type") == "text":
                        return block.get("text")
            elif isinstance(msg.content, str):
                return msg.content
    return None
