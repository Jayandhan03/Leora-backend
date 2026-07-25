"""
Centralized configuration — loads all environment variables once
and exposes them as typed attributes on a single `settings` object.
"""

import os
from dotenv import load_dotenv

load_dotenv()

 
class Settings:
    """Application settings loaded from environment variables."""

    # --- News ---
    RAPID_API_KEY: str = os.getenv("RAPID_API_KEY", "")

    # --- LLM ---
    XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

    # --- TTS ---
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

    # --- Search ---
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    SERP_API_KEY: str = os.getenv("SERP_API_KEY", "")

    # ---Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # --- WhatsApp (via Kapso) ---
    KAPSO_API_KEY: str = os.getenv("KAPSO_API_KEY", "")
    KAPSO_PHONE_NUMBER_ID: str = os.getenv("KAPSO_PHONE_NUMBER_ID", "")
    # Approved template used to ask permission before delivering a briefing
    # outside the 24h session window (see whatsapp_service.send_template_message).
    WHATSAPP_BRIEFING_TEMPLATE_NAME: str = os.getenv("WHATSAPP_BRIEFING_TEMPLATE_NAME", "briefing_ready")
    WHATSAPP_BRIEFING_TEMPLATE_LANG: str = os.getenv("WHATSAPP_BRIEFING_TEMPLATE_LANG", "en_US")
    # How long a queued briefing waits for the user to tap "Send it" before
    # it's swept and marked expired.
    WHATSAPP_PENDING_TTL_HOURS: int = int(os.getenv("WHATSAPP_PENDING_TTL_HOURS", "24"))

    # --- Push notifications (Firebase Cloud Messaging) ---
    # The whole service-account JSON as one env var, not a file path — keeps
    # the secret out of any deployable artifact on the EC2 box.
    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")

    # --- Database (shared with the YourNews Next.js app) ---
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "yournews")

    # --- Scheduler ---
    # In-process APScheduler that delivers scheduled audio briefings.
    SCHEDULER_ENABLED: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
    # How often (seconds) the scheduler wakes up to look for due deliveries.
    SCHEDULER_TICK_SECONDS: int = int(os.getenv("SCHEDULER_TICK_SECONDS", "60"))

    # --- CORS ---
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000"
    ).split(",")

    # --- App ---
    APP_TITLE: str = "IndustryEar API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
