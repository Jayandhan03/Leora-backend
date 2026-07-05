"""
Database service — shared MongoDB access for the scheduler and preferences.

The Next.js app (YourNews) owns user identity, Telegram links and writes the
news preferences. This service reads those same collections so the backend
scheduler can autonomously deliver briefings. Collection names match the
Mongoose model pluralization used by the frontend:
    UserPreference -> "userpreferences"
    TelegramLink   -> "telegramlinks"
"""

import logging

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Return a lazily-initialised, process-wide Mongo client."""
    global _client
    if _client is None:
        if not settings.MONGODB_URI:
            raise ValueError("MONGODB_URI is not configured — database features unavailable.")
        _client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tz_aware=True,
        )
        logger.info("MongoDB client initialised (db=%s).", settings.MONGODB_DB)
    return _client


def get_db() -> Database:
    return get_client()[settings.MONGODB_DB]


def preferences_collection() -> Collection:
    return get_db()["userpreferences"]


def telegram_links_collection() -> Collection:
    return get_db()["telegramlinks"]


def agents_collection() -> Collection:
    return get_db()["agents"]


def get_chat_id_for_email(email: str) -> str | None:
    """Look up the Telegram chat_id linked to a user's email, if any."""
    doc = telegram_links_collection().find_one({"email": email.lower()})
    return doc.get("chatId") if doc else None


def is_available() -> bool:
    """True when a connection string is configured (used to gate the scheduler)."""
    return bool(settings.MONGODB_URI)
