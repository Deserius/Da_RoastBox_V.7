"""Shared types and delivery profiles for the unified Da RoastBox TTS engine."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


DELIVERY_PROFILES: Dict[str, Dict[str, Any]] = {
    "casual": {
        "id": "casual",
        "label": "Casual Conversation",
        "rate_multiplier": 1.0,
        "pitch_multiplier": 1.0,
        "pause_scale": 1.0,
        "room_ambience": False,
        "description": "Natural conversational pacing with clean breath pauses.",
    },
    "high_energy_comedy": {
        "id": "high_energy_comedy",
        "label": "High-Energy Comedy",
        "rate_multiplier": 1.07,
        "pitch_multiplier": 1.03,
        "pause_scale": 0.90,
        "room_ambience": True,
        "description": "Punchy stand-up tempo with snappy setup-to-punchline cadence.",
    },
    "aggressive_roast": {
        "id": "aggressive_roast",
        "label": "Aggressive Roast",
        "rate_multiplier": 1.05,
        "pitch_multiplier": 0.98,
        "pause_scale": 0.88,
        "room_ambience": True,
        "description": "Sharp, assertive roast delivery with firm dynamic presence.",
    },
    "sarcastic": {
        "id": "sarcastic",
        "label": "Sarcastic Delivery",
        "rate_multiplier": 0.96,
        "pitch_multiplier": 1.01,
        "pause_scale": 1.12,
        "room_ambience": False,
        "description": "Slightly drawn-out inflection with dry comedic beats.",
    },
    "deadpan": {
        "id": "deadpan",
        "label": "Deadpan Humor",
        "rate_multiplier": 0.93,
        "pitch_multiplier": 0.97,
        "pause_scale": 1.18,
        "room_ambience": False,
        "description": "Flat, unhurried dry delivery that lets the punchline hang.",
    },
    "dramatic": {
        "id": "dramatic",
        "label": "Dramatic Narration",
        "rate_multiplier": 0.94,
        "pitch_multiplier": 0.96,
        "pause_scale": 1.22,
        "room_ambience": True,
        "description": "Theatrical pacing with deliberate dramatic pauses.",
    },
    "excited": {
        "id": "excited",
        "label": "Excited Delivery",
        "rate_multiplier": 1.10,
        "pitch_multiplier": 1.05,
        "pause_scale": 0.85,
        "room_ambience": True,
        "description": "Upbeat, energized pace with bright inflection.",
    },
    "calm": {
        "id": "calm",
        "label": "Calm Delivery",
        "rate_multiplier": 0.94,
        "pitch_multiplier": 0.99,
        "pause_scale": 1.12,
        "room_ambience": False,
        "description": "Relaxed, steady cadence with smooth breathing.",
    },
    "whispering": {
        "id": "whispering",
        "label": "Whispering (Conspiratorial)",
        "rate_multiplier": 0.92,
        "pitch_multiplier": 0.98,
        "pause_scale": 1.15,
        "room_ambience": False,
        "description": "Lower-volume intimate delivery (full breathy whisper supported natively on ElevenLabs v3).",
    },
    "shouting": {
        "id": "shouting",
        "label": "Shouting / Arena Hype",
        "rate_multiplier": 1.06,
        "pitch_multiplier": 1.04,
        "pause_scale": 0.92,
        "room_ambience": True,
        "description": "High-presence stage projection (native shouting tags supported on ElevenLabs v3).",
    },
    "slow_deliberate": {
        "id": "slow_deliberate",
        "label": "Slow & Deliberate",
        "rate_multiplier": 0.88,
        "pitch_multiplier": 0.97,
        "pause_scale": 1.25,
        "room_ambience": False,
        "description": "Measured tempo giving every syllable extra weight.",
    },
    "fast_energetic": {
        "id": "fast_energetic",
        "label": "Fast & Energetic",
        "rate_multiplier": 1.14,
        "pitch_multiplier": 1.02,
        "pause_scale": 0.80,
        "room_ambience": False,
        "description": "Rapid-fire comedic momentum with tight transitions.",
    },
    "emotional": {
        "id": "emotional",
        "label": "Emotional Delivery",
        "rate_multiplier": 0.95,
        "pitch_multiplier": 1.01,
        "pause_scale": 1.15,
        "room_ambience": True,
        "description": "Expressive phrasing with heightened cadence contrast.",
    },
}


@dataclass
class TTSVoice:
    voice_id: str
    display_name: str
    provider: str
    engine: str
    gender: str
    vocal_age: str
    accent: str
    vocal_depth: str
    is_free: bool = True
    is_native: bool = True
    tags: List[str] = field(default_factory=list)
    license: str = "Apache-2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "display_name": self.display_name,
            "provider": self.provider,
            "engine": self.engine,
            "gender": self.gender,
            "vocal_age": self.vocal_age,
            "accent": self.accent,
            "vocal_depth": self.vocal_depth,
            "is_free": self.is_free,
            "is_native": self.is_native,
            "tags": list(self.tags),
            "license": self.license,
        }


@dataclass
class TTSResult:
    audio_bytes: bytes
    media_type: str
    provider: str
    engine: str
    voice_id: str
    native_voice: bool
    processing_applied: List[str] = field(default_factory=list)
