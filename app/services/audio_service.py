"""
Text-to-Speech service — Microsoft Edge neural TTS (via the free, keyless
``edge-tts`` package). Gives every supported language its own real neural
voice, and maps the four voice "tones" the frontend offers onto genuine
rate/pitch prosody so they produce audibly different audio.
"""

import logging

import edge_tts

logger = logging.getLogger(__name__)

# One curated neural voice per language the frontend offers (create-agent's
# LANGS list and the dashboard's agentConstants LANGUAGES list, unioned).
LANGUAGE_VOICES: dict[str, str] = {
    "English": "en-US-AndrewNeural",
    "Español": "es-ES-AlvaroNeural",
    "हिन्दी": "hi-IN-MadhurNeural",
    "Français": "fr-FR-HenriNeural",
    "Deutsch": "de-DE-ConradNeural",
    "Português": "pt-BR-AntonioNeural",
    "العربية": "ar-SA-HamedNeural",
    "中文": "zh-CN-YunyangNeural",
    "日本語": "ja-JP-KeitaNeural",
}
DEFAULT_LANGUAGE = "English"

# Rate/pitch prosody deltas per tone — mirrors the relative rate/pitch
# multipliers the frontend's browser-side voice preview already uses
# (Analytical 1.0/1.0, Conversational 1.05/1.06, Energetic 1.18/1.22, Calm
# 0.9/0.95) so the real generated audio matches what "Preview voice" implies.
TONE_PROSODY: dict[str, tuple[str, str]] = {
    "Analytical": ("+0%", "+0Hz"),
    "Conversational": ("+5%", "+6Hz"),
    "Energetic": ("+18%", "+20Hz"),
    "Calm": ("-10%", "-8Hz"),
}
DEFAULT_TONE = "Analytical"


def voice_for(language: str) -> str:
    return LANGUAGE_VOICES.get(language, LANGUAGE_VOICES[DEFAULT_LANGUAGE])


def prosody_for(tone: str) -> tuple[str, str]:
    return TONE_PROSODY.get(tone, TONE_PROSODY[DEFAULT_TONE])


async def _stream_edge_tts(text: str, voice: str, rate: str, pitch: str, chunk_size: int):
    """Async generator yielding raw MP3 bytes from Edge TTS as they arrive."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] != "audio":
            continue
        buffer.extend(chunk["data"])
        while len(buffer) >= chunk_size:
            yield bytes(buffer[:chunk_size])
            del buffer[:chunk_size]
    if buffer:
        yield bytes(buffer)


def generate_audio_stream(
    script: str,
    language: str = DEFAULT_LANGUAGE,
    tone: str = DEFAULT_TONE,
    chunk_size: int = 4096,
):
    """
    Convert text to an MP3 audio stream using Edge TTS.

    Args:
        script: The text to synthesize (should already be written in `language`).
        language: Human language label, e.g. "English" / "हिन्दी" / "中文".
        tone: Voice tone — "Analytical" | "Conversational" | "Energetic" | "Calm".
        chunk_size: Bytes per yielded chunk.

    Returns:
        An async generator yielding bytes chunks of MP3 audio data.

    Raises:
        ValueError: If the script is empty or whitespace-only. Raised
            immediately (not lazily) so callers can catch it before streaming
            a response.
    """
    if not script or not script.strip():
        raise ValueError("Script text is empty — cannot generate audio.")

    voice = voice_for(language)
    rate, pitch = prosody_for(tone)
    logger.info(
        "Generating TTS audio via Edge TTS (%d chars, language=%s -> voice=%s, tone=%s -> rate=%s pitch=%s)",
        len(script), language, voice, tone, rate, pitch,
    )

    return _stream_edge_tts(script, voice, rate, pitch, chunk_size)
