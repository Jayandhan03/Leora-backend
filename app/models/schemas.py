"""
Pydantic request / response schemas for all API endpoints.
"""

from pydantic import BaseModel, Field


# ── Request Schemas ──────────────────────────────────────────────

class NewsRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Search topic")


class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(default="", description="Message text")


class PreferenceChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(
        default_factory=list,
        description="Running conversation so far (empty to start the chat).",
    )


class DeliverNowRequest(BaseModel):
    email: str = Field(..., min_length=3, description="User email whose briefing to send now")


class DeliverNowAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, description="Mongo _id of the agent to deliver now")


class DeliverPendingWhatsAppRequest(BaseModel):
    pending_id: str = Field(..., min_length=1, description="Mongo _id of the PendingWhatsAppDelivery to fulfill")


class WhatsAppTestPingRequest(BaseModel):
    email: str = Field(..., min_length=3, description="Signed-in user's email whose linked WhatsApp to ping")


class SummarizeRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Search topic")
    limit: int = Field(default=5, ge=1, le=20, description="Number of articles to fetch")
    time_published: str = Field(
        default="anytime",
        description="Time filter: anytime | past_hour | past_day | past_week",
    )
    language: str = Field(
        default="English",
        description="Human language label the summary should be written in, e.g. English/Español/हिन्दी/中文",
    )


class AudioRequest(SummarizeRequest):
    tone: str = Field(
        default="Analytical",
        description="Voice tone: Analytical | Conversational | Energetic | Calm",
    )


class VoiceSampleRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Short sample text to synthesize as-is (no LLM step)")
    language: str = Field(default="English", description="Human language label, e.g. English/Español/हिन्दी/中文")
    tone: str = Field(default="Analytical", description="Voice tone: Analytical | Conversational | Energetic | Calm")


# ── Response Schemas ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str


class NewsResponse(BaseModel):
    success: bool
    news: str | None = None
    error: str | None = None


class SummarizeResponse(BaseModel):
    success: bool
    topic: str | None = None
    article_count: int | None = None
    summary: str | None = None
    error: str | None = None


class PreferenceChatResponse(BaseModel):
    success: bool
    reply: str
    preferences: dict | None = None
    complete: bool = False
    error: str | None = None


# ── Agent onboarding (per-agent topic lock-in) ───────────────────

class AgentOnboardingChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(
        default_factory=list,
        description="Running conversation so far (empty to start the chat).",
    )


class AgentOnboardingLocked(BaseModel):
    """The finalized research directive derived from the conversation."""
    topic: str = Field(..., description="Short niche label, e.g. 'US stocks — rising trends'")
    summary: str = Field(..., description="1-2 sentence plain-English description shown to the user")
    core_prompt: str = Field(..., description="Detailed research directive stored as the agent's core role")
    keywords: list[str] = Field(default_factory=list)
    region: str = Field(default="Global")


class AgentOnboardingChatResponse(BaseModel):
    success: bool
    reply: str
    complete: bool = False
    locked: AgentOnboardingLocked | None = None
    error: str | None = None


# ── Scouts (dashboard) ───────────────────────────────────────────

class ScoutPersonality(BaseModel):
    """How a scout sounds when it briefs the user."""
    voice: str = Field(default="Professional", description="Voice tone, e.g. Professional / Casual / Energetic")
    voice_id: str = Field(default="JBFqnCBsd6RMkjVDRZzb", description="ElevenLabs voice ID")
    language: str = Field(default="English", description="Briefing language")
    tone_summary: str = Field(default="", description="Short human description of the scout's persona")


class ScoutPlatform(BaseModel):
    """A delivery channel wired to a scout."""
    platform: str = Field(..., description="telegram | whatsapp")
    connected: bool = Field(default=False, description="Whether the channel is linked")
    handle: str | None = Field(default=None, description="Username / phone / chat id shown to the user")


class ScoutSchedule(BaseModel):
    """When and how often a scout sends its voice-note briefings."""
    frequency: str = Field(default="daily", description="Human label, e.g. 'Twice daily'")
    interval_minutes: int = Field(default=1440, description="Canonical cadence the scheduler uses")
    times: list[str] = Field(default_factory=list, description="Preferred send times, e.g. ['08:00', '18:00']")
    timezone: str = Field(default="UTC", description="Timezone the times are expressed in")
    enabled: bool = Field(default=True, description="Whether automated delivery is on")
    next_run_at: str | None = Field(default=None, description="ISO timestamp of the next scheduled briefing")
    last_sent_at: str | None = Field(default=None, description="ISO timestamp of the last briefing sent")


class ScoutStats(BaseModel):
    """Lightweight activity counters shown on the dashboard."""
    briefings_sent: int = Field(default=0)
    sources_tracked: int = Field(default=0)
    last_briefing: str | None = Field(default=None, description="Human label, e.g. '2h ago'")


class Scout(BaseModel):
    """A single deployed scout and all of its configurable traits."""
    id: str
    name: str
    icon: str = Field(default="🛰️", description="Emoji shown on the card")
    accent: str = Field(default="#4d7fff", description="Accent color for the card")
    niche: str = Field(..., description="What this scout watches, e.g. 'Finance & Markets'")
    description: str = Field(default="", description="One-line summary of the scout's beat")
    status: str = Field(default="active", description="active | paused")
    keywords: list[str] = Field(default_factory=list)
    personality: ScoutPersonality = Field(default_factory=ScoutPersonality)
    platforms: list[ScoutPlatform] = Field(default_factory=list)
    schedule: ScoutSchedule = Field(default_factory=ScoutSchedule)
    stats: ScoutStats = Field(default_factory=ScoutStats)


class ScoutsResponse(BaseModel):
    success: bool
    scouts: list[Scout] = Field(default_factory=list)
    error: str | None = None


class ScoutResponse(BaseModel):
    success: bool
    scout: Scout | None = None
    error: str | None = None
