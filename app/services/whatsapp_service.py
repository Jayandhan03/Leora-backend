"""
WhatsApp service (via Kapso) — sends audio files to users through the
official WhatsApp Cloud API. Account linking (wa_id capture) is handled by
the wa.me deep-link + webhook flow in the Next.js app; this service only
handles outbound audio delivery.
"""

import io
import logging
from datetime import datetime, timedelta, timezone

import requests

from app.core.config import settings
from app.services.db_service import get_gridfs, pending_whatsapp_deliveries_collection

logger = logging.getLogger(__name__)

KAPSO_BASE = "https://api.kapso.ai/meta/whatsapp/v24.0"


def _upload_media(audio_bytes: bytes, filename: str, mime_type: str = "audio/mpeg") -> str:
    """Upload audio bytes to Kapso/Meta and return the media id for use in a send call."""
    phone_number_id = settings.KAPSO_PHONE_NUMBER_ID
    url = f"{KAPSO_BASE}/{phone_number_id}/media"
    files = {"file": (filename, io.BytesIO(audio_bytes), mime_type)}
    data = {"messaging_product": "whatsapp"}
    headers = {"X-API-Key": settings.KAPSO_API_KEY}

    resp = requests.post(url, headers=headers, data=data, files=files, timeout=30)
    if not resp.ok:
        raise ValueError(f"Kapso media upload failed ({resp.status_code}): {resp.text}")

    media_id = resp.json().get("id")
    if not media_id:
        raise ValueError(f"Kapso media upload returned no id: {resp.text}")
    return media_id


def _send_text(wa_id: str, body: str) -> None:
    url = f"{KAPSO_BASE}/{settings.KAPSO_PHONE_NUMBER_ID}/messages"
    headers = {"Content-Type": "application/json", "X-API-Key": settings.KAPSO_API_KEY}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {"body": body},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        logger.error("Kapso sendText failed: %s %s", resp.status_code, resp.text[:200])


def send_audio_to_user(
    wa_id: str,
    audio_bytes: bytes,
    filename: str = "news_audio.mp3",
    caption: str | None = None,
) -> dict:
    """
    Send an MP3 audio file to a WhatsApp user by wa_id (phone number, digits only).

    WhatsApp's audio message type has no caption field (unlike Telegram), so
    if a caption is given it's sent as a preceding text message.

    Raises:
        ValueError: If Kapso config is missing or the API rejects the request.
    """
    phone_number_id = settings.KAPSO_PHONE_NUMBER_ID
    if not phone_number_id or not settings.KAPSO_API_KEY:
        raise ValueError("KAPSO_API_KEY / KAPSO_PHONE_NUMBER_ID is not configured.")

    if caption:
        _send_text(wa_id, caption)

    logger.info("Uploading audio to Kapso for wa_id=%s (%d bytes)", wa_id, len(audio_bytes))
    media_id = _upload_media(audio_bytes, filename)

    url = f"{KAPSO_BASE}/{phone_number_id}/messages"
    headers = {"Content-Type": "application/json", "X-API-Key": settings.KAPSO_API_KEY}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "audio",
        "audio": {"id": media_id},
    }

    logger.info("Sending audio to wa_id=%s (%d bytes)", wa_id, len(audio_bytes))
    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if not resp.ok:
        logger.error("Kapso sendAudio failed: %s %s", resp.status_code, resp.text[:200])
        raise ValueError(f"Kapso API error ({resp.status_code}): {resp.text}")

    result = resp.json()
    messages = result.get("messages") or []
    message_id = messages[0].get("id") if messages else None
    logger.info("Audio sent successfully to wa_id=%s", wa_id)
    return {"success": True, "message_id": message_id}


def send_template_message(
    wa_id: str,
    template_name: str,
    language_code: str,
    body_params: list[str],
    button_payload: str,
    button_index: int = 0,
) -> dict:
    """
    Send an approved template message with a single Quick Reply button.

    Unlike send_audio_to_user, this can be sent outside the 24h session
    window — it's the only thing WhatsApp allows for messages a business
    initiates rather than replies to. `button_payload` is echoed back on the
    inbound webhook event when the user taps the button, so it should encode
    which pending delivery this ping is for.
    """
    if not settings.KAPSO_PHONE_NUMBER_ID or not settings.KAPSO_API_KEY:
        raise ValueError("KAPSO_API_KEY / KAPSO_PHONE_NUMBER_ID is not configured.")

    url = f"{KAPSO_BASE}/{settings.KAPSO_PHONE_NUMBER_ID}/messages"
    headers = {"Content-Type": "application/json", "X-API-Key": settings.KAPSO_API_KEY}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in body_params],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(button_index),
                    "parameters": [{"type": "payload", "payload": button_payload}],
                },
            ],
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        logger.error("Kapso sendTemplate failed: %s %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Kapso API error ({resp.status_code}): {resp.text}")

    result = resp.json()
    messages = result.get("messages") or []
    message_id = messages[0].get("id") if messages else None
    logger.info("Template ping sent to wa_id=%s (template=%s)", wa_id, template_name)
    return {"success": True, "message_id": message_id}


def queue_whatsapp_delivery(
    *,
    email: str,
    wa_id: str,
    first_name: str,
    label: str,
    audio_bytes: bytes,
    filename: str,
    caption: str,
    agent_id: str | None = None,
) -> bool:
    """
    Hold a generated briefing until the user confirms they want it, since it
    can't be sent directly outside the 24h session window: stores the audio
    in GridFS, records a pending-delivery doc, and sends the approved
    "briefing ready" template with a Quick Reply button. The webhook resolves
    the tap back to this pending doc and triggers the real audio send.

    Returns True if the ping was sent.
    """
    file_id = get_gridfs().put(audio_bytes, filename=filename, content_type="audio/mpeg")

    now = datetime.now(timezone.utc)
    doc = {
        "email": email.lower(),
        "waId": wa_id,
        "agentId": agent_id,
        "audioFileId": file_id,
        "filename": filename,
        "caption": caption,
        "status": "pending",
        "createdAt": now,
        "expiresAt": now + timedelta(hours=settings.WHATSAPP_PENDING_TTL_HOURS),
    }
    inserted_id = pending_whatsapp_deliveries_collection().insert_one(doc).inserted_id

    try:
        send_template_message(
            wa_id=wa_id,
            template_name=settings.WHATSAPP_BRIEFING_TEMPLATE_NAME,
            language_code=settings.WHATSAPP_BRIEFING_TEMPLATE_LANG,
            body_params=[first_name, label],
            button_payload=str(inserted_id),
        )
        return True
    except Exception:
        pending_whatsapp_deliveries_collection().update_one(
            {"_id": inserted_id}, {"$set": {"status": "failed"}}
        )
        get_gridfs().delete(file_id)
        raise
