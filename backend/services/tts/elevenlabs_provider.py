"""ElevenLabs Premium TTS adapter — preserves all existing voice IDs, keys, and models."""
from __future__ import annotations

from typing import Dict, List, Optional

import config
from services.elevenlabs_service import MODEL_CHAIN, synthesize_tts_elevenlabs
from .base import TTSVoice


def check_health(user_key: Optional[str] = None) -> Dict[str, object]:
    has_key = bool((user_key or "").strip() or config.ELEVENLABS_API_KEY)
    return {
        "provider": "elevenlabs",
        "display_name": "ElevenLabs (Premium Expressive Voices)",
        "is_free": False,
        "installed": True,
        "models_ready": has_key,
        "operational": has_key,
        "status": "operational" if has_key else "missing_api_key",
        "detail": "ElevenLabs API key active." if has_key else "Optional premium provider; add ELEVENLABS_API_KEY in Settings to enable.",
        "models": list(MODEL_CHAIN) + ["eleven_turbo_v2_5"],
    }


async def synthesize(
    text: str,
    api_key: str,
    voice_cfg: Optional[dict] = None,
) -> bytes:
    return await synthesize_tts_elevenlabs(api_key, text, voice_cfg)
