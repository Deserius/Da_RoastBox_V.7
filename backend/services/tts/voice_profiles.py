"""40-persona voice profile definitions, persistence, and default restoration.

Preserves all 40 characters in backend/data/personas.json untouched while
giving each character a dedicated, consistent Kokoro/Piper/Edge/ElevenLabs
voice profile. Clearly distinguishes native voice identity from profile-level
rate/pitch/delivery customization.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from db import db

log = logging.getLogger(__name__)
PROFILES_JSON = DATA_DIR / "voice_profiles.json"
COLLECTION = db["persona_voice_profiles"]

# Intentional 1-to-1 primary mapping across all 27 distinct Kokoro-82M voices,
# plus curated customized profiles (distinct rate/pitch/delivery/Piper voice)
# for the remaining 13 personas so every one of the 40 characters sounds distinct.
_SPEC_BY_ID: Dict[str, Dict[str, Any]] = {
    "persona_1":   {"kokoro": "am_adam",    "piper": "en_US-joe-medium",     "edge": "en-US-GuyNeural",   "age": "adult",       "accent": "American", "depth": "deep",      "pitch": 1.00, "rate": 1.05, "style": "high_energy_comedy", "personality": "Arena MC host with explosive crowd work",       "emotion": "hype",       "native": True},
    "persona_2":   {"kokoro": "af_aoede",   "piper": "en_US-kristin-medium", "edge": "en-US-JennyNeural", "age": "older",       "accent": "American", "depth": "warm",      "pitch": 1.07, "rate": 0.90, "style": "sarcastic",          "personality": "Sharp-tongued grandma with zero filter",        "emotion": "smug",       "native": True},
    "persona_3":   {"kokoro": "am_puck",    "piper": "en_US-bryce-medium",   "edge": "en-US-GuyNeural",   "age": "young_adult", "accent": "American", "depth": "higher",    "pitch": 1.02, "rate": 1.16, "style": "fast_energetic",     "personality": "Hyperactive internet troll & meme machine",     "emotion": "excited",    "native": True},
    "persona_4":   {"kokoro": "am_michael", "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "adult",       "accent": "American", "depth": "deep",      "pitch": 0.94, "rate": 0.98, "style": "deadpan",            "personality": "Condescending finance-bro executive",           "emotion": "smug",       "native": True},
    "persona_5":   {"kokoro": "am_echo",    "piper": "en_US-joe-medium",     "edge": "en-US-GuyNeural",   "age": "young_adult", "accent": "American", "depth": "medium",    "pitch": 1.01, "rate": 1.03, "style": "aggressive_roast",   "personality": "Rhythmic street-poet punchline sniper",         "emotion": "cocky",      "native": True},
    "persona_6":   {"kokoro": "am_liam",    "piper": "en_US-bryce-medium",   "edge": "en-US-GuyNeural",   "age": "young_adult", "accent": "American", "depth": "medium",    "pitch": 1.03, "rate": 1.15, "style": "fast_energetic",     "personality": "Trash-talking competitive gamer",               "emotion": "hype",       "native": True},
    "persona_7":   {"kokoro": "am_eric",    "piper": "en_US-joe-medium",     "edge": "en-US-DavisNeural", "age": "adult",       "accent": "American", "depth": "medium",    "pitch": 0.97, "rate": 0.91, "style": "calm",               "personality": "Ultra-chill roast assassin with slow burns",    "emotion": "deadpan",    "native": True},
    "persona_8":   {"kokoro": "af_sky",     "piper": "en_US-amy-medium",     "edge": "en-US-AriaNeural",  "age": "young_adult", "accent": "American", "depth": "bright",    "pitch": 1.05, "rate": 1.12, "style": "high_energy_comedy", "personality": "Loud theater-kid diva stealing the spotlight",  "emotion": "excited",    "native": True},
    "persona_9":   {"kokoro": "af_nicole",  "piper": "en_US-lessac-medium",  "edge": "en-US-JennyNeural", "age": "adult",       "accent": "American", "depth": "soft",      "pitch": 1.02, "rate": 0.98, "style": "whispering",         "personality": "Late-night gossip barista spilling hot tea",    "emotion": "whisper",    "native": True},
    "persona_10":  {"kokoro": "am_fenrir",  "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "mature",      "accent": "American", "depth": "very_deep", "pitch": 0.92, "rate": 0.98, "style": "shouting",           "personality": "Booming radio-legend mic annihilator",          "emotion": "outraged",   "native": True},
    "persona_11":  {"kokoro": "am_onyx",    "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "adult",       "accent": "American", "depth": "deep",      "pitch": 0.96, "rate": 1.08, "style": "sarcastic",          "personality": "Clinical diagnostician roasting your flaws",    "emotion": "incredulous","native": True},
    "persona_12":  {"kokoro": "bm_daniel",  "piper": "en_GB-alan-medium",    "edge": "en-GB-RyanNeural",  "age": "adult",       "accent": "British",  "depth": "medium",    "pitch": 0.99, "rate": 0.96, "style": "dramatic",           "personality": "Smooth PR spin doctor reframing disasters",     "emotion": "smug",       "native": True},
    "persona_13":  {"kokoro": "af_nova",    "piper": "en_US-amy-medium",     "edge": "en-US-AriaNeural",  "age": "adult",       "accent": "American", "depth": "medium",    "pitch": 1.02, "rate": 1.10, "style": "shouting",           "personality": "No-excuses athletic coach barking truth",       "emotion": "outraged",   "native": True},
    "persona_14":  {"kokoro": "bf_emma",    "piper": "en_GB-alba-medium",    "edge": "en-GB-SoniaNeural", "age": "adult",       "accent": "British",  "depth": "medium",    "pitch": 1.03, "rate": 0.92, "style": "slow_deliberate",    "personality": "Aristocratic British snob looking down on all",  "emotion": "disgusted",  "native": True},
    "persona_15":  {"kokoro": "af_heart",   "piper": "en_US-lessac-medium",  "edge": "en-US-JennyNeural", "age": "adult",       "accent": "American", "depth": "warm",      "pitch": 1.01, "rate": 0.94, "style": "emotional",          "personality": "Faux-sympathetic therapist diagnosing cringe",  "emotion": "mock_sympathy","native": True},
    "persona_16":  {"kokoro": "bm_lewis",   "piper": "en_GB-alan-medium",    "edge": "en-GB-RyanNeural",  "age": "adult",       "accent": "British",  "depth": "medium",    "pitch": 1.02, "rate": 1.13, "style": "excited",            "personality": "Over-the-top hype announcer",                   "emotion": "hype",       "native": True},
    "persona_17":  {"kokoro": "bm_fable",   "piper": "en_GB-alan-medium",    "edge": "en-GB-RyanNeural",  "age": "mature",      "accent": "British",  "depth": "deep",      "pitch": 0.96, "rate": 0.95, "style": "sarcastic",          "personality": "Cynical film/fashion critic panning your life", "emotion": "disgusted",  "native": True},
    "persona_18":  {"kokoro": "bm_george",  "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "older",       "accent": "British",  "depth": "deep",      "pitch": 0.95, "rate": 1.06, "style": "aggressive_roast",   "personality": "Heavyweight gym-bro roaring at skipped leg day","emotion": "cocky",      "native": True},
    "persona_19":  {"kokoro": "af_river",   "piper": "en_US-lessac-medium",  "edge": "en-US-JennyNeural", "age": "young_adult", "accent": "American", "depth": "medium",    "pitch": 1.03, "rate": 1.00, "style": "casual",             "personality": "Cosmic astrologer blaming your bad aura",       "emotion": "smug",       "native": True},
    "persona_20":  {"kokoro": "af_kore",    "piper": "en_US-lessac-medium",  "edge": "en-US-AriaNeural",  "age": "adult",       "accent": "American", "depth": "medium",    "pitch": 0.98, "rate": 0.90, "style": "deadpan",            "personality": "Minimalist deadpan sniper",                     "emotion": "deadpan",    "native": True},
    "persona_21":  {"kokoro": "af_alloy",   "piper": "en_US-kristin-medium", "edge": "en-US-JennyNeural", "age": "mature",      "accent": "American", "depth": "medium",    "pitch": 1.01, "rate": 0.98, "style": "sarcastic",          "personality": "Receipt-pulling family auntie who misses nothing","emotion": "incredulous","native": True},
    "persona_22":  {"kokoro": "bf_lily",    "piper": "en_US-joe-medium",     "edge": "en-US-DavisNeural", "age": "older",       "accent": "American", "depth": "deep",      "pitch": 0.92, "rate": 0.93, "style": "casual",             "personality": "Cross-country highway realist (custom male tune)","emotion": "deadpan",    "native": False},
    "persona_23":  {"kokoro": "af_bella",   "piper": "en_US-amy-medium",     "edge": "en-US-AriaNeural",  "age": "young_adult", "accent": "American", "depth": "bright",    "pitch": 1.04, "rate": 1.11, "style": "fast_energetic",     "personality": "Viral clout-chaser critiquing your aesthetics", "emotion": "sarcastic",  "native": True},
    "persona_24":  {"kokoro": "bf_alice",   "piper": "en_US-joe-medium",     "edge": "en-US-GuyNeural",   "age": "mature",      "accent": "British",  "depth": "bright",    "pitch": 1.01, "rate": 1.02, "style": "casual",             "personality": "Backyard cookout uncle with lethal dad jokes",  "emotion": "cocky",      "native": False},
    "persona_25":  {"kokoro": "af_sarah",   "piper": "en_US-lessac-medium",  "edge": "en-US-AriaNeural",  "age": "young_adult", "accent": "American", "depth": "bright",    "pitch": 1.00, "rate": 1.02, "style": "sarcastic",          "personality": "Sharp academic grading your life choices F-",   "emotion": "smug",       "native": True},
    "persona_p1":  {"kokoro": "am_fenrir",  "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "older",       "accent": "American", "depth": "very_deep", "pitch": 0.90, "rate": 0.94, "style": "dramatic",           "personality": "Mob-boss heavyweight delivering slow threats",  "emotion": "smug",       "native": False},
    "persona_p2":  {"kokoro": "am_puck",    "piper": "en_US-bryce-medium",   "edge": "en-US-GuyNeural",   "age": "young_adult", "accent": "American", "depth": "higher",    "pitch": 0.97, "rate": 1.18, "style": "fast_energetic",     "personality": "Turbocharged esports trash-talk king",          "emotion": "excited",    "native": False},
    "persona_p3":  {"kokoro": "af_jessica", "piper": "en_US-amy-medium",     "edge": "en-US-AriaNeural",  "age": "adult",       "accent": "American", "depth": "bright",    "pitch": 1.05, "rate": 1.07, "style": "high_energy_comedy", "personality": "Fiery kitchen boss with spicy clapbacks",       "emotion": "outraged",   "native": True},
    "persona_p4":  {"kokoro": "am_michael", "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "older",       "accent": "American", "depth": "very_deep", "pitch": 0.89, "rate": 0.88, "style": "dramatic",           "personality": "Fire-and-brimstone preacher roasting sins",     "emotion": "outraged",   "native": False},
    "persona_p5":  {"kokoro": "am_adam",    "piper": "en_US-joe-medium",     "edge": "en-US-GuyNeural",   "age": "adult",       "accent": "American", "depth": "deep",      "pitch": 1.04, "rate": 1.10, "style": "high_energy_comedy", "personality": "VIP champagne-popping flex king",               "emotion": "cocky",      "native": False},
    "persona_p6":  {"kokoro": "bf_isabella","piper": "en_GB-alba-medium",    "edge": "en-GB-SoniaNeural", "age": "mature",      "accent": "British",  "depth": "deep",      "pitch": 1.01, "rate": 0.95, "style": "sarcastic",          "personality": "Ice-cold British royalty slicing egos",         "emotion": "disgusted",  "native": True},
    "persona_p7":  {"kokoro": "am_echo",    "piper": "en_US-ryan-high",      "edge": "en-US-DavisNeural", "age": "mature",      "accent": "American", "depth": "deep",      "pitch": 0.93, "rate": 1.09, "style": "aggressive_roast",   "personality": "Drill sergeant barking inspection roasts",      "emotion": "outraged",   "native": False},
    "persona_p8":  {"kokoro": "am_liam",    "piper": "en_US-bryce-medium",   "edge": "en-US-GuyNeural",   "age": "young_adult", "accent": "American", "depth": "higher",    "pitch": 1.06, "rate": 1.14, "style": "excited",            "personality": "Chaotic rapid-fire hype brat",                  "emotion": "hype",       "native": False},
    "persona_p9":  {"kokoro": "af_aoede",   "piper": "en_US-kristin-medium", "edge": "en-US-JennyNeural", "age": "mature",      "accent": "American", "depth": "deep",      "pitch": 0.96, "rate": 0.91, "style": "whispering",         "personality": "Mystic fortune-teller predicting your L's",      "emotion": "whisper",    "native": False},
    "persona_p10": {"kokoro": "am_eric",    "piper": "en_US-joe-medium",     "edge": "en-US-DavisNeural", "age": "older",       "accent": "American", "depth": "deep",      "pitch": 0.94, "rate": 0.96, "style": "aggressive_roast",   "personality": "Old-school locker-room coach",                  "emotion": "incredulous","native": False},
    "persona_p11": {"kokoro": "am_onyx",    "piper": "en_US-joe-medium",     "edge": "en-US-GuyNeural",   "age": "mature",      "accent": "American", "depth": "deep",      "pitch": 0.95, "rate": 1.00, "style": "casual",             "personality": "Slick Vegas pit-boss counting your bad bets",   "emotion": "smug",       "native": False},
    "persona_p12": {"kokoro": "af_nicole",  "piper": "en_US-lessac-medium",  "edge": "en-US-JennyNeural", "age": "adult",       "accent": "American", "depth": "medium",    "pitch": 1.03, "rate": 1.01, "style": "sarcastic",          "personality": "Beverly Hills surgeon grading symmetry",        "emotion": "mock_sympathy","native": False},
    "persona_p13": {"kokoro": "bm_george",  "piper": "en_GB-alan-medium",    "edge": "en-GB-RyanNeural",  "age": "older",       "accent": "British",  "depth": "deep",      "pitch": 0.91, "rate": 0.92, "style": "slow_deliberate",    "personality": "Haunting disappointed grandpa from beyond",     "emotion": "deadpan",    "native": False},
    "persona_p14": {"kokoro": "bm_daniel",  "piper": "en_US-ryan-high",      "edge": "en-GB-RyanNeural",  "age": "adult",       "accent": "British",  "depth": "medium",    "pitch": 0.96, "rate": 1.04, "style": "deadpan",            "personality": "Classified intelligence agent reading your file","emotion": "deadpan",    "native": False},
    "persona_p15": {"kokoro": "af_nova",    "piper": "en_US-amy-medium",     "edge": "en-US-AriaNeural",  "age": "adult",       "accent": "American", "depth": "bright",    "pitch": 1.04, "rate": 1.09, "style": "aggressive_roast",   "personality": "Undefeated battle-queen closing the show",      "emotion": "cocky",      "native": False},
}

# Persona 22 & 24 are male characters; ensure they map to male Kokoro voices too!
_SPEC_BY_ID["persona_22"]["kokoro"] = "am_michael"
_SPEC_BY_ID["persona_22"]["accent"] = "American"
_SPEC_BY_ID["persona_22"]["pitch"] = 0.91
_SPEC_BY_ID["persona_24"]["kokoro"] = "am_adam"
_SPEC_BY_ID["persona_24"]["accent"] = "American"
_SPEC_BY_ID["persona_24"]["pitch"] = 0.95


def _personas_raw() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "personas.json").read_text(encoding="utf-8"))


def build_default_profiles() -> List[Dict[str, Any]]:
    from .kokoro_provider import get_voice as get_kokoro_voice

    profiles: List[Dict[str, Any]] = []
    for p in _personas_raw():
        pid = p["id"]
        spec = _SPEC_BY_ID.get(pid, {
            "kokoro": "am_adam" if p.get("gender") == "male" else "af_heart",
            "piper": "en_US-joe-medium" if p.get("gender") == "male" else "en_US-lessac-medium",
            "edge": "en-US-GuyNeural" if p.get("gender") == "male" else "en-US-JennyNeural",
            "age": "adult",
            "accent": "American",
            "depth": "medium",
            "pitch": 1.0,
            "rate": 1.0,
            "style": "casual",
            "personality": p.get("archetype") or "Roast comedian",
            "emotion": "cocky",
            "native": False,
        })
        k_voice = get_kokoro_voice(spec["kokoro"])
        samples = p.get("punchlines") or [p.get("tagline") or "Welcome to Da RoastBox."]
        profiles.append({
            "persona_id": pid,
            "persona_name": p.get("displayName") or p.get("name") or pid,
            "tier": p.get("tier", "free"),
            "voice_provider": "free_local",
            "engine_model": "kokoro-82m-onnx",
            "voice_id": spec["kokoro"],
            "voice_display_name": k_voice.display_name if k_voice else spec["kokoro"],
            "piper_voice_id": spec["piper"],
            "edge_voice_id": spec["edge"],
            "elevenlabs_voice_id": (p.get("elevenlabs") or {}).get("voice_id"),
            "elevenlabs_stability": (p.get("elevenlabs") or {}).get("stability", 0.55),
            "openai_voice": p.get("tts_voice_hd") or p.get("tts_voice") or "ash",
            "native_voice_identity": bool(spec["native"]),
            "is_customized_profile": not bool(spec["native"]),
            "gender_presentation": p.get("gender") or (k_voice.gender if k_voice else "other"),
            "vocal_age": spec["age"],
            "accent": spec["accent"],
            "vocal_depth": spec["depth"],
            "pitch_adjustment": float(spec["pitch"]),
            "speaking_rate": float(spec["rate"]),
            "speaking_style": spec["style"],
            "delivery_personality": spec["personality"],
            "default_emotion": spec["emotion"],
            "audio_processing": {
                "trim_silence": True,
                "normalize": True,
                "room_ambience": spec["style"] in ("high_energy_comedy", "aggressive_roast", "dramatic", "shouting"),
            },
            "sample_preview_text": samples[0],
            "assignment_status": "assigned_default",
        })
    return profiles


def ensure_profiles_json() -> List[Dict[str, Any]]:
    profiles = build_default_profiles()
    PROFILES_JSON.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")
    return profiles


_DEFAULT_LIST = build_default_profiles()
_DEFAULT_BY_ID: Dict[str, Dict[str, Any]] = {item["persona_id"]: item for item in _DEFAULT_LIST}


def list_default_profiles() -> List[Dict[str, Any]]:
    return [dict(v) for v in _DEFAULT_LIST]


def get_default_profile(persona_id: str) -> Optional[Dict[str, Any]]:
    prof = _DEFAULT_BY_ID.get(persona_id)
    return dict(prof) if prof else None


async def list_effective_profiles() -> List[Dict[str, Any]]:
    overrides = {}
    docs = await COLLECTION.find({}, {"_id": 0}).to_list(length=100)
    for doc in docs:
        pid = doc.get("persona_id")
        if pid:
            overrides[pid] = doc
    out = []
    for base in _DEFAULT_LIST:
        pid = base["persona_id"]
        if pid in overrides:
            merged = {**base, **overrides[pid]}
            out.append(merged)
        else:
            out.append(dict(base))
    return out


async def get_effective_profile(persona_id: str) -> Optional[Dict[str, Any]]:
    base = get_default_profile(persona_id)
    if not base:
        return None
    doc = await COLLECTION.find_one({"persona_id": persona_id}, {"_id": 0})
    if doc:
        return {**base, **doc}
    return base


async def save_profile_override(persona_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    base = get_default_profile(persona_id)
    if not base:
        raise KeyError(f"Unknown persona: {persona_id}")
    allowed = {
        "voice_provider", "engine_model", "voice_id", "voice_display_name",
        "piper_voice_id", "edge_voice_id", "pitch_adjustment", "speaking_rate",
        "speaking_style", "delivery_personality", "default_emotion", "audio_processing",
        "sample_preview_text",
    }
    clean: Dict[str, Any] = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if "pitch_adjustment" in clean:
        clean["pitch_adjustment"] = max(0.85, min(1.15, float(clean["pitch_adjustment"])))
    if "speaking_rate" in clean:
        clean["speaking_rate"] = max(0.80, min(1.30, float(clean["speaking_rate"])))
    clean["is_customized_profile"] = True
    clean["assignment_status"] = "customized"
    clean["updated_at"] = datetime.now(timezone.utc).isoformat()
    await COLLECTION.update_one(
        {"persona_id": persona_id},
        {"$set": {"persona_id": persona_id, **clean}},
        upsert=True,
    )
    return await get_effective_profile(persona_id)


async def reset_profile_to_default(persona_id: str) -> Dict[str, Any]:
    base = get_default_profile(persona_id)
    if not base:
        raise KeyError(f"Unknown persona: {persona_id}")
    await COLLECTION.delete_one({"persona_id": persona_id})
    return base
