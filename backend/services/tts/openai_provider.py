"""OpenAI Expressive TTS adapter — preserves existing gpt-4o-mini-tts / tts-1 flow."""
from __future__ import annotations

from typing import Dict, Optional

import config
from services.openai_service import synthesize_tts_openai


def check_health(user_key: Optional[str] = None) -> Dict[str, object]:
    has_key = bool((user_key or "").strip() or config.OPENAI_API_KEY or config.EMERGENT_LLM_KEY)
    return {
        "provider": "openai",
        "display_name": "OpenAI Expressive TTS",
        "is_free": False,
        "installed": True,
        "models_ready": has_key,
        "operational": has_key,
        "status": "operational" if has_key else "missing_api_key",
        "detail": "OpenAI / Emergent TTS credentials active." if has_key else "No OpenAI key configured.",
    }


async def synthesize(
    text: str,
    *,
    voice: str = "ash",
    speed: float = 1.0,
    byok_key: Optional[str] = None,
    instructions: Optional[str] = None,
) -> bytes:
    return await synthesize_tts_openai(
        text=text,
        voice=voice,
        speed=speed,
        byok_key=byok_key,
        instructions=instructions,
    )
