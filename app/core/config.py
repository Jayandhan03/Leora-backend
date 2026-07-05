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
