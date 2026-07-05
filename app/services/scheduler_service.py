"""
Scheduler service — autonomous delivery of scheduled audio briefings.

A lightweight in-process loop (driven by APScheduler from main.py) periodically
asks: "which users are due for their next briefing?" For each, it rebuilds the
news query from their saved preferences, runs the existing fetch -> summarize ->
TTS pipeline, and sends the MP3 to their linked Telegram chat.

Preferences are written by the Next.js app; this module only reads them and
updates the scheduling bookkeeping fields (lastSentAt / nextRunAt / lastResult).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.audio_service import generate_audio_stream
from app.services.db_service import (
    agents_collection,
    get_chat_id_for_email,
    get_wa_id_for_email,
    preferences_collection,
)
from app.services.llm_service import summarize_news
from app.services.news_service import fetch_news
from app.services.telegram_service import send_audio_to_user as send_telegram_audio
from app.services.whatsapp_service import send_audio_to_user as send_whatsapp_audio

logger = logging.getLogger(__name__)

# Map the user-facing region to a RapidAPI country code.
REGION_TO_COUNTRY = {
    "global": "US",
    "us": "US",
    "usa": "US",
    "united states": "US",
    "india": "IN",
    "uk": "GB",
    "united kingdom": "GB",
    "gb": "GB",
    "europe": "GB",
    "canada": "CA",
    "australia": "AU",
}

DEFAULT_INTERVAL_MINUTES = 1440  # daily fallback


# ── Query building ───────────────────────────────────────────────

def _build_query(pref: dict) -> str:
    topics = pref.get("topics") or []
    keywords = pref.get("keywords") or []
    terms = [t for t in (list(topics) + list(keywords)) if t]
    if terms:
        return " ".join(terms)
    return (pref.get("summary") or "top news").strip()


def _topic_label(pref: dict) -> str:
    topics = pref.get("topics") or []
    if topics:
        return ", ".join(topics)
    return (pref.get("summary") or "Your News").strip()


def _country_for(pref: dict) -> str:
    return REGION_TO_COUNTRY.get(str(pref.get("region", "global")).lower(), "US")


# ── TTS helper ───────────────────────────────────────────────────

def _drain_audio_stream(async_stream) -> bytes:
    """
    Run an Edge-TTS async audio generator to completion and return the full
    MP3 bytes. Safe to call here because this module always runs off the main
    FastAPI event loop (APScheduler background thread / synchronous callers).
    """
    async def _collect() -> bytes:
        chunks = [chunk async for chunk in async_stream]
        return b"".join(chunks)

    return asyncio.run(_collect())


# ── Delivery ─────────────────────────────────────────────────────

def _send_to_linked_channels(
    email: str,
    chat_id: str | None,
    wa_id: str | None,
    audio_bytes: bytes,
    filename: str,
    caption: str,
) -> dict:
    """
    Send the generated audio to every channel the user has linked. A channel
    failing to send doesn't block the other — each is tried independently.
    """
    channels: dict = {}

    if chat_id:
        try:
            send_telegram_audio(chat_id=chat_id, audio_bytes=audio_bytes, filename=filename, caption=caption)
            channels["telegram"] = True
        except Exception as exc:  # noqa: BLE001 — record and keep going
            logger.error("Telegram delivery failed for %s: %s", email, exc)
            channels["telegram"] = False

    if wa_id:
        try:
            send_whatsapp_audio(wa_id=wa_id, audio_bytes=audio_bytes, filename=filename, caption=caption)
            channels["whatsapp"] = True
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp delivery failed for %s: %s", email, exc)
            channels["whatsapp"] = False

    return channels


def deliver_for_user(pref: dict) -> dict:
    """
    Run the full pipeline for a single user's preferences and send the audio
    to every chat platform they've linked. Raises on hard failures so the
    caller can record it.
    """
    email = pref.get("email")
    if not email:
        return {"email": None, "delivered": False, "reason": "missing_email"}

    chat_id = get_chat_id_for_email(email)
    wa_id = get_wa_id_for_email(email)
    if not chat_id and not wa_id:
        logger.info("Skipping %s — no delivery channel linked.", email)
        return {"email": email, "delivered": False, "reason": "no_channel_linked"}

    query = _build_query(pref)
    label = _topic_label(pref)
    limit = int(pref.get("articleLimit") or 5)

    news_data = fetch_news(
        query=query,
        limit=limit,
        time_published="1d",
        country=_country_for(pref),
    )
    articles = news_data.get("data", []) if news_data else []
    language = pref.get("language") or "English"
    script = summarize_news(topic=label, articles=articles, language=language)

    audio_bytes = _drain_audio_stream(generate_audio_stream(script, language=language))
    if not audio_bytes:
        raise ValueError("TTS produced no audio.")

    filename = (label.replace(" ", "_").replace(",", "")[:40] or "news") + "_briefing.mp3"
    caption = f"🎙 Your scheduled briefing: {label}"

    channels = _send_to_linked_channels(email, chat_id, wa_id, audio_bytes, filename, caption)
    delivered = any(channels.values())
    logger.info("Delivered scheduled briefing to %s (%d articles) — channels=%s", email, len(articles), channels)
    return {"email": email, "delivered": delivered, "articles": len(articles), "channels": channels}


def deliver_for_agent(agent: dict) -> dict:
    """
    Run the full pipeline for a single per-user Agent document and send the
    audio to every chat platform its owner has linked. Mirrors
    deliver_for_user, but reads the nested Agent shape
    (topics/keywords/region/articleLimit/personality) instead of the flat
    legacy UserPreference shape.
    """
    email = agent.get("email")
    if not email:
        return {"email": None, "delivered": False, "reason": "missing_email"}

    chat_id = get_chat_id_for_email(email)
    wa_id = get_wa_id_for_email(email)
    if not chat_id and not wa_id:
        logger.info("Skipping agent %s (%s) — no delivery channel linked.", agent.get("_id"), email)
        return {"email": email, "delivered": False, "reason": "no_channel_linked"}

    query = _build_query(agent)
    label = _topic_label(agent) or agent.get("name") or "Your News"
    limit = int(agent.get("articleLimit") or 5)
    personality = agent.get("personality", {}) or {}
    language = personality.get("language") or "English"
    tone = personality.get("voice") or "Analytical"

    news_data = fetch_news(
        query=query,
        limit=limit,
        time_published="1d",
        country=_country_for(agent),
    )
    articles = news_data.get("data", []) if news_data else []
    script = summarize_news(topic=label, articles=articles, language=language)

    audio_bytes = _drain_audio_stream(generate_audio_stream(script, language=language, tone=tone))
    if not audio_bytes:
        raise ValueError("TTS produced no audio.")

    filename = (label.replace(" ", "_").replace(",", "")[:40] or "news") + "_briefing.mp3"
    caption = f"🎙 {agent.get('name', 'Agent')}: {label}"

    channels = _send_to_linked_channels(email, chat_id, wa_id, audio_bytes, filename, caption)
    delivered = any(channels.values())
    logger.info("Delivered agent briefing to %s (%d articles) — channels=%s", email, len(articles), channels)
    return {"email": email, "delivered": delivered, "articles": len(articles), "channels": channels}


# ── Scheduling ───────────────────────────────────────────────────

def compute_next_run(interval_minutes: int, from_time: datetime | None = None) -> datetime:
    base = from_time or datetime.now(timezone.utc)
    minutes = max(1, int(interval_minutes or DEFAULT_INTERVAL_MINUTES))
    return base + timedelta(minutes=minutes)


# JS weekday convention used by the frontend: 0=Sun..6=Sat. Python's date.weekday() is Mon=0..Sun=6.
def _js_weekday(d) -> int:
    return (d.weekday() + 1) % 7


def compute_next_run_at(schedule: dict, now: datetime | None = None) -> datetime:
    """
    Timezone- and clock-time-aware version of compute_next_run, mirroring the
    frontend's lib/schedule.ts computeNextRunAt exactly (same algorithm, same
    weekday convention) so an agent's nextRunAt keeps landing on the time the
    user actually picked (e.g. "every day at 9am") instead of just drifting by
    a fixed interval from whenever the last delivery happened.
    """
    now = now or datetime.now(timezone.utc)
    frequency = schedule.get("frequency") or "Daily brief"

    if frequency in ("Real-time", "Hourly"):
        minutes = max(1, int(schedule.get("intervalMinutes") or 60))
        return now + timedelta(minutes=minutes)

    try:
        tz = ZoneInfo(schedule.get("timezone") or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    times = schedule.get("times") or ["09:00"]
    weekday = schedule.get("weekday")

    local_now = now.astimezone(tz)
    candidates: list[datetime] = []

    for day_offset in range(0, 8):
        cand_date = local_now.date() + timedelta(days=day_offset)
        if weekday is not None and _js_weekday(cand_date) != weekday:
            continue
        for t in times:
            try:
                hh, mm = map(int, str(t).split(":"))
            except Exception:
                hh, mm = 9, 0
            candidate = datetime(cand_date.year, cand_date.month, cand_date.day, hh, mm, tzinfo=tz)
            if candidate > local_now:
                candidates.append(candidate)

    if not candidates:
        return now + timedelta(days=1)
    return min(candidates).astimezone(timezone.utc)


def run_due_deliveries() -> dict:
    """
    Find every enabled preference whose next run is due (or never scheduled) and
    deliver it, then advance its nextRunAt. Designed to be called on a timer.
    """
    coll = preferences_collection()
    now = datetime.now(timezone.utc)

    due = list(
        coll.find(
            {
                "scheduleEnabled": True,
                "$or": [{"nextRunAt": {"$lte": now}}, {"nextRunAt": None}],
            }
        )
    )

    if due:
        logger.info("Scheduler tick: %d user(s) due.", len(due))

    results = []
    for pref in due:
        interval = pref.get("intervalMinutes") or DEFAULT_INTERVAL_MINUTES
        try:
            res = deliver_for_user(pref)
        except Exception as exc:  # noqa: BLE001 — record and keep going
            logger.error("Scheduled delivery failed for %s: %s", pref.get("email"), exc)
            res = {"email": pref.get("email"), "delivered": False, "reason": str(exc)}

        update = {
            "lastResult": res,
            "nextRunAt": compute_next_run(interval, now),
        }
        if res.get("delivered"):
            update["lastSentAt"] = now

        coll.update_one({"_id": pref["_id"]}, {"$set": update})
        results.append(res)

    return {"checked": len(due), "results": results}


def run_due_agent_deliveries() -> dict:
    """
    Same sweep as run_due_deliveries, but for the real per-user Agent
    collection (multiple independently-scheduled agents per user) instead of
    the legacy single UserPreference document per user.
    """
    coll = agents_collection()
    now = datetime.now(timezone.utc)

    due = list(
        coll.find(
            {
                "schedule.enabled": True,
                "$or": [{"schedule.nextRunAt": {"$lte": now}}, {"schedule.nextRunAt": None}],
            }
        )
    )

    if due:
        logger.info("Agent scheduler tick: %d agent(s) due.", len(due))

    results = []
    for agent in due:
        try:
            res = deliver_for_agent(agent)
        except Exception as exc:  # noqa: BLE001 — record and keep going
            logger.error("Scheduled delivery failed for agent %s: %s", agent.get("_id"), exc)
            res = {"email": agent.get("email"), "delivered": False, "reason": str(exc)}

        next_run = compute_next_run_at(agent.get("schedule", {}), now)
        update: dict = {"$set": {"lastResult": res, "schedule.nextRunAt": next_run}}
        if res.get("delivered"):
            update["$set"]["schedule.lastSentAt"] = now
            update["$set"]["stats.sourcesTracked"] = res.get("articles", 0)
            update["$inc"] = {"stats.briefingsSent": 1}

        coll.update_one({"_id": agent["_id"]}, update)
        results.append(res)

    return {"checked": len(due), "results": results}
