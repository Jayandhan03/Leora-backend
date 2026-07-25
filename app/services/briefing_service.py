"""
Briefing history service — permanent storage for generated audio briefings.

Unlike the WhatsApp GridFS buffer (whatsappAudio, short-lived, deleted once a
pending delivery is fulfilled or expires), everything written here is meant
to stick around indefinitely so the Next.js dashboard can list and replay
past briefings per agent. Mirrored on the frontend by models/Briefing.ts —
this module writes the same "briefings" collection Mongoose reads.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.services.db_service import briefings_collection, get_briefing_gridfs

logger = logging.getLogger(__name__)


def persist_briefing(
    *,
    agent: dict,
    email: str,
    script: str,
    audio_bytes: bytes,
    filename: str,
    label: str,
    language: str,
    tone: str,
    article_count: int,
) -> ObjectId:
    """Store the audio in GridFS and record the briefing doc. Returns the new
    briefing's _id. Raises on failure — a briefing that can't be persisted
    shouldn't be silently treated as delivered."""
    audio_file_id = get_briefing_gridfs().put(audio_bytes, filename=filename, content_type="audio/mpeg")

    doc: dict[str, Any] = {
        "email": email.lower(),
        "agentId": agent.get("_id"),
        "agentName": agent.get("name") or "Agent",
        "agentIcon": agent.get("icon"),
        "audioFileId": audio_file_id,
        "filename": filename,
        "mimeType": "audio/mpeg",
        "sizeBytes": len(audio_bytes),
        "articleCount": article_count,
        "label": label,
        "script": script,
        "language": language,
        "tone": tone,
        "channels": {},
        "createdAt": datetime.now(timezone.utc),
    }
    briefing_id = briefings_collection().insert_one(doc).inserted_id
    logger.info("Persisted briefing %s for %s (agent %s).", briefing_id, email, agent.get("_id"))
    return briefing_id


def set_briefing_channels(briefing_id: ObjectId, channels: dict) -> None:
    """Record which channels the briefing actually went out on, once
    _send_to_linked_channels has finished fanning out. "app" is always True —
    reaching this point means the audio is already durably stored."""
    briefings_collection().update_one(
        {"_id": briefing_id},
        {"$set": {"channels": {"app": True, **channels}}},
    )
