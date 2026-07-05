"""
IndustryEar — FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.api.routes import router as api_router

# ── Logging ──────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)


# ── Scheduler lifespan ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-process delivery scheduler on boot, stop it on shutdown."""
    scheduler = None
    if settings.SCHEDULER_ENABLED and settings.MONGODB_URI:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.services.scheduler_service import run_due_agent_deliveries, run_due_deliveries

            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                run_due_deliveries,
                trigger="interval",
                seconds=settings.SCHEDULER_TICK_SECONDS,
                id="deliver_due_briefings",
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                run_due_agent_deliveries,
                trigger="interval",
                seconds=settings.SCHEDULER_TICK_SECONDS,
                id="deliver_due_agent_briefings",
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
            logger.info(
                "Delivery scheduler started (tick=%ds).", settings.SCHEDULER_TICK_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to start scheduler: %s", exc)
            scheduler = None
    else:
        logger.info("Delivery scheduler disabled (SCHEDULER_ENABLED/MONGODB_URI not set).")

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("Delivery scheduler stopped.")


# ── App ──────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ── Root health probe ────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": settings.APP_TITLE, "version": settings.APP_VERSION}
