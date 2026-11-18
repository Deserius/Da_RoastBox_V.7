"""Edge-TTS online neural fallback provider (free, requires internet)."""
from __future__ import annotations

import logging
from typing import Dict, List

from .base import TTSVoice

log = logging.getLogger(__name__)

EDGE_VOICES: List[TTSVoice] = [
    TTSVoice("en-US-GuyNeural", "Guy (American Male Energetic)", "edge_tts", "edge-neural", "male", "adult", "American", "medium", True, True, ["american", "energetic", "host"], "Microsoft Online Terms"),
    TTSVoice("en-US-JennyNeural", "Jenny (American Female Natural)", "edge_tts", "edge-neural", "female", "adult", "American", "medium", True, True, ["american", "natural", "casual"], "Microsoft Online Terms"),
    TTSVoice("en-US-AriaNeural", "Aria (American Female Expressive)", "edge_tts", "edge-neural", "female", "young_adult", "American", "bright", True, True, ["american", "expressive", "comedic"], "Microsoft Online Terms"),
    TTSVoice("en-US-DavisNeural", "Davis (American Male Deep)", "edge_tts", "edge-neural", "male", "adult", "American", "deep", True, True, ["american", "deep", "dramatic"], "Microsoft Online Terms"),
    TTSVoice("en-GB-RyanNeural", "Ryan UK (British Male Crisp)", "edge_tts", "edge-neural", "male", "adult", "British", "medium", True, True, ["british", "crisp", "sarcastic"], "Microsoft Online Terms"),
    TTSVoice("en-GB-SoniaNeural", "Sonia UK (British Female Posh)", "edge_tts", "edge-neural", "female", "adult", "British", "medium", True, True, ["british", "posh", "dramatic"], "Microsoft Online Terms"),
]


def is_package_installed() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def check_health() -> Dict[str, object]:
    pkg_ok = is_package_installed()
    return {
        "provider": "edge_tts",
        "display_name": "Edge-TTS (Free Online Neural Fallback)",
        "is_free": True,
        "requires_internet": True,
        "installed": pkg_ok,
        "models_ready": pkg_ok,
        "operational": pkg_ok,
        "status": "available" if pkg_ok else "missing_dependencies",
        "detail": "Uses Microsoft Edge online neural service when internet is reachable." if pkg_ok else "edge-tts not installed.",
        "native_voices_count": len(EDGE_VOICES),
    }


def list_voices() -> List[Dict]:
    return [v.to_dict() for v in EDGE_VOICES]


async def synthesize(text: str, voice_id: str = "en-US-GuyNeural", speed: float = 1.0) -> bytes:
    import edge_tts
    pct = int(round((max(0.7, min(1.4, float(speed or 1.0))) - 1.0) * 100))
    rate_str = f"{pct:+d}%"
    comm = edge_tts.Communicate(text=text, voice=voice_id, rate=rate_str)
    chunks = []
    async for item in comm.stream():
        if item.get("type") == "audio":
            chunks.append(item["data"])
    audio = b"".join(chunks)
    if not audio:
        raise RuntimeError("Edge-TTS returned empty audio stream")
    return audio
