"""Unified Da RoastBox TTS subsystem (Kokoro-82M, Piper, Edge-TTS, ElevenLabs, OpenAI)."""
from .base import DELIVERY_PROFILES, TTSResult, TTSVoice
from .manager import (
    cache_key_for,
    get_install_status,
    get_provider_health,
    list_all_voices,
    start_model_install,
    synthesize_and_cache,
    synthesize_speech,
)
from .voice_profiles import (
    ensure_profiles_json,
    get_default_profile,
    get_effective_profile,
    list_default_profiles,
    list_effective_profiles,
    reset_profile_to_default,
    save_profile_override,
)

__all__ = [
    "DELIVERY_PROFILES",
    "TTSResult",
    "TTSVoice",
    "cache_key_for",
    "ensure_profiles_json",
    "get_default_profile",
    "get_effective_profile",
    "get_install_status",
    "get_provider_health",
    "list_all_voices",
    "list_default_profiles",
    "list_effective_profiles",
    "reset_profile_to_default",
    "save_profile_override",
    "start_model_install",
    "synthesize_and_cache",
    "synthesize_speech",
]
