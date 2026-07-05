"""
Telegram Bot service — sends audio files to users via the Bot API.
Account linking (chat_id capture) is handled by the bot deep-link + webhook
flow in the Next.js app; this service only handles outbound audio delivery.
"""

import io
import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_audio_to_user(
    chat_id: str | int,
    audio_bytes: bytes,
    filename: str = "news_audio.mp3",
    caption: str | None = None,
) -> dict:
    """
    Send an MP3 audio file to a Telegram user by chat_id.

    Args:
        chat_id: Telegram user/chat ID (captured when the user links the bot).
        audio_bytes: Raw MP3 bytes.
        filename: Filename for the attachment.
        caption: Optional caption sent with the audio.

    Returns:
        dict with success status and message_id.

    Raises:
        ValueError: If bot token is missing or Telegram rejects the request.
    """
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")

    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename

    data: dict = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption
    files = {"audio": (filename, audio_file, "audio/mpeg")}

    logger.info("Sending audio to chat_id=%s (%d bytes)", chat_id, len(audio_bytes))
    resp = requests.post(url, data=data, files=files, timeout=30)

    if not resp.ok:
        logger.error("Telegram sendAudio failed: %s %s", resp.status_code, resp.text[:200])
        raise ValueError(f"Telegram API error ({resp.status_code}): {resp.text}")

    result = resp.json()
    logger.info("Audio sent successfully to chat_id=%s", chat_id)
    return {"success": True, "message_id": result.get("result", {}).get("message_id")}