"""Unified TTS Manager: provider health, selection, caching, naturalness & installers."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from config import AUDIO_DIR, PREVIEW_SANDBOX_FALLBACK
from services.sandbox_preview import is_network_connection_error, synthesize_sandbox_audio
from services.storage import save_audio
from . import edge_provider, elevenlabs_provider, kokoro_provider, openai_provider, piper_provider
from .base import DELIVERY_PROFILES, TTSResult
from .naturalness import optimize_text_for_tts, process_voice_audio
from .voice_profiles import get_effective_profile

log = logging.getLogger(__name__)

_CACHE: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 600
_INSTALL_STATE: Dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "message": "Not started",
    "error": None,
}
_INSTALL_TASK: Optional[asyncio.Task] = None
_SYNTH_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_lock(key: str) -> asyncio.Lock:
    if len(_SYNTH_LOCKS) > 512:
        _SYNTH_LOCKS.clear()
    return _SYNTH_LOCKS.setdefault(key, asyncio.Lock())


def cache_key_for(
    *,
    text: str,
    provider: str,
    voice_id: str,
    rate: float,
    pitch: float,
    delivery_style: str,
    room_ambience: bool,
    output_format: str,
) -> str:
    payload = "\x1f".join([
        provider,
        voice_id,
        f"{rate:.3f}",
        f"{pitch:.3f}",
        delivery_style,
        "1" if room_ambience else "0",
        output_format,
        text.strip(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def list_all_voices() -> List[Dict[str, Any]]:
    voices: List[Dict[str, Any]] = []
    voices.extend(kokoro_provider.list_voices())
    voices.extend(piper_provider.list_voices())
    voices.extend(edge_provider.list_voices())
    return voices


def get_provider_health(
    *,
    user_elevenlabs_key: Optional[str] = None,
    user_openai_key: Optional[str] = None,
) -> Dict[str, Any]:
    kokoro = kokoro_provider.check_health()
    piper = piper_provider.check_health()
    edge = edge_provider.check_health()
    eleven = elevenlabs_provider.check_health(user_elevenlabs_key)
    openai_h = openai_provider.check_health(user_openai_key)
    browser = {
        "provider": "browser_speech",
        "display_name": "Browser Web Speech Fallback",
        "is_free": True,
        "installed": True,
        "models_ready": True,
        "operational": True,
        "status": "available",
        "detail": "Client-side fallback active when offline / preview models are absent.",
    }
    free_operational = bool(kokoro["operational"] or piper["operational"])
    return {
        "default_provider": "free_local",
        "free_local_ready": free_operational,
        "providers": {
            "kokoro": kokoro,
            "piper": piper,
            "edge_tts": edge,
            "elevenlabs": eleven,
            "openai": openai_h,
            "browser_speech": browser,
        },
        "install_job": dict(_INSTALL_STATE),
    }


def get_install_status() -> Dict[str, Any]:
    return {
        "job": dict(_INSTALL_STATE),
        "kokoro": kokoro_provider.check_health(),
        "piper": piper_provider.check_health(),
    }


async def start_model_install(target: str = "kokoro", piper_voice: str = "en_US-lessac-medium") -> Dict[str, Any]:
    global _INSTALL_TASK
    if _INSTALL_TASK and not _INSTALL_TASK.done():
        return get_install_status()

    _INSTALL_STATE.update(status="running", progress=1, message=f"Starting {target} download...", error=None)

    def _progress(msg: str, pct: int) -> None:
        _INSTALL_STATE.update(status="running", progress=pct, message=msg, error=None)

    async def _runner():
        try:
            if target == "piper":
                await asyncio.to_thread(piper_provider.install_voice_sync, piper_voice)
                _INSTALL_STATE.update(status="completed", progress=100, message=f"Piper voice {piper_voice} installed.", error=None)
            else:
                await asyncio.to_thread(kokoro_provider.install_models_sync, _progress)
                _INSTALL_STATE.update(status="completed", progress=100, message="Kokoro-82M installed and verified!", error=None)
        except Exception as exc:
            _INSTALL_STATE.update(status="failed", progress=0, message="Model installation failed.", error=str(exc))

    _INSTALL_TASK = asyncio.create_task(_runner())
    return get_install_status()


async def synthesize_speech(
    *,
    text: str,
    persona_id: Optional[str] = None,
    provider_preference: Optional[str] = None,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
    pitch: Optional[float] = None,
    delivery_style: Optional[str] = None,
    room_ambience: Optional[bool] = None,
    output_format: str = "mp3",
    user_elevenlabs_key: Optional[str] = None,
    user_openai_key: Optional[str] = None,
    allow_premium_elevenlabs: bool = False,
    allow_hosted_openai: bool = True,
    persona_meta: Optional[dict] = None,
    eleven_text: Optional[str] = None,
    openai_instructions: Optional[str] = None,
) -> TTSResult:
    profile = await get_effective_profile(persona_id) if persona_id else None
    pref = (provider_preference or (profile or {}).get("voice_provider") or "free_local").lower()
    style = delivery_style or (profile or {}).get("speaking_style") or "casual"
    deliv = DELIVERY_PROFILES.get(style, DELIVERY_PROFILES["casual"])

    rate = float(speed if speed is not None else (profile or {}).get("speaking_rate") or 1.0)
    eff_rate = max(0.80, min(1.30, rate * float(deliv["rate_multiplier"])))
    eff_pitch = float(pitch if pitch is not None else (profile or {}).get("pitch_adjustment") or 1.0)
    eff_pitch = max(0.85, min(1.15, eff_pitch * float(deliv["pitch_multiplier"])))
    use_ambience = bool(room_ambience if room_ambience is not None else ((profile or {}).get("audio_processing") or {}).get("room_ambience", False))
    fmt = "wav" if output_format.lower() == "wav" else "mp3"

    shaped_text = optimize_text_for_tts(text, style)
    chosen_kokoro = voice_id or (profile or {}).get("voice_id") or "af_heart"
    chosen_piper = voice_id if (voice_id and voice_id.startswith("en_")) else (profile or {}).get("piper_voice_id") or "en_US-lessac-medium"
    chosen_edge = voice_id if (voice_id and "Neural" in voice_id) else (profile or {}).get("edge_voice_id") or "en-US-GuyNeural"

    eleven_key = (user_elevenlabs_key or "").strip() or (config.ELEVENLABS_API_KEY if allow_premium_elevenlabs else "")
    raw_bytes: Optional[bytes] = None
    raw_fmt = "wav"
    used_provider = "none"
    used_engine = "none"
    used_voice = chosen_kokoro
    native_voice = bool((profile or {}).get("native_voice_identity", True))

    # 1. Explicit ElevenLabs premium path (only when selected or unlocked + key present)
    if (pref == "elevenlabs" or allow_premium_elevenlabs) and eleven_key:
        el_cfg = (persona_meta or {}).get("elevenlabs") or {
            "voice_id": (profile or {}).get("elevenlabs_voice_id") or "nPczCjzI2devNBz1zQrb",
            "stability": (profile or {}).get("elevenlabs_stability", 0.55),
        }
        try:
            raw_bytes = await elevenlabs_provider.synthesize(eleven_text or shaped_text, eleven_key, el_cfg)
            raw_fmt = "mp3"
            used_provider = "elevenlabs"
            used_engine = "eleven_v3"
            used_voice = str(el_cfg.get("voice_id") or "elevenlabs")
            native_voice = True
        except Exception as exc:
            log.warning("ElevenLabs synthesis failed (%s); falling back.", exc)
            if pref == "elevenlabs" and not (kokoro_provider.models_present() or piper_provider.installed_voice_ids()):
                raise

    # 2. Free Local Kokoro-82M (primary free engine)
    if raw_bytes is None and pref in ("free_local", "kokoro", "elevenlabs") and kokoro_provider.is_package_installed() and kokoro_provider.models_present():
        try:
            raw_bytes = await kokoro_provider.synthesize(shaped_text, voice_id=chosen_kokoro, speed=eff_rate)
            raw_fmt = "wav"
            used_provider = "kokoro"
            used_engine = "kokoro-82m-onnx"
            used_voice = chosen_kokoro
        except Exception as exc:
            log.warning("Kokoro synthesis failed (%s); trying Piper fallback.", exc)

    # 3. Free Local Piper TTS fallback
    if raw_bytes is None and pref in ("free_local", "kokoro", "piper", "elevenlabs") and piper_provider.is_package_installed() and piper_provider.installed_voice_ids():
        try:
            raw_bytes = await piper_provider.synthesize(shaped_text, voice_id=chosen_piper, speed=eff_rate)
            raw_fmt = "wav"
            used_provider = "piper"
            used_engine = "piper-onnx"
            used_voice = chosen_piper
        except Exception as exc:
            log.warning("Piper synthesis failed (%s); checking next fallback.", exc)

    # 4. Edge-TTS online free fallback (when selected or allowed)
    if raw_bytes is None and pref in ("edge_tts",) and edge_provider.is_package_installed():
        raw_bytes = await edge_provider.synthesize(shaped_text, voice_id=chosen_edge, speed=eff_rate)
        raw_fmt = "mp3"
        used_provider = "edge_tts"
        used_engine = "edge-neural"
        used_voice = chosen_edge

    # 5. OpenAI Expressive TTS fallback (when credentials permitted)
    if raw_bytes is None and (user_openai_key or (allow_hosted_openai and (config.OPENAI_API_KEY or config.EMERGENT_LLM_KEY))):
        try:
            oai_voice = (persona_meta or {}).get("tts_voice_hd") or (profile or {}).get("openai_voice") or "ash"
            raw_bytes = await openai_provider.synthesize(
                shaped_text,
                voice=oai_voice,
                speed=eff_rate,
                byok_key=user_openai_key,
                instructions=openai_instructions,
            )
            raw_fmt = "mp3"
            used_provider = "openai"
            used_engine = "gpt-4o-mini-tts"
            used_voice = oai_voice
        except Exception as exc:
            if PREVIEW_SANDBOX_FALLBACK and is_network_connection_error(exc):
                log.warning("OpenAI TTS unreachable (%s); using sandbox preview audio.", type(exc).__name__)
            else:
                raise

    # 6. Sandbox preview fallback when local models aren't downloaded & outbound APIs are blocked
    if raw_bytes is None and PREVIEW_SANDBOX_FALLBACK:
        raw_bytes = await asyncio.to_thread(synthesize_sandbox_audio, shaped_text, persona_id or "host", persona_meta)
        return TTSResult(
            audio_bytes=raw_bytes,
            media_type="audio/mpeg",
            provider="sandbox_preview",
            engine="browser_speech_fallback",
            voice_id=chosen_kokoro,
            native_voice=native_voice,
            processing_applied=["sandbox_preview"],
        )

    if raw_bytes is None:
        raise RuntimeError(
            "No operational TTS provider available. Download Kokoro-82M in Voice Studio or configure an API key in Settings."
        )

    # Apply naturalness pipeline on local/neural audio (skip unnecessary re-pitching for ElevenLabs unless requested)
    apply_pitch = eff_pitch if used_provider not in ("elevenlabs", "openai") else (pitch if pitch is not None else 1.0)
    processed_bytes, applied = await asyncio.to_thread(
        process_voice_audio,
        raw_bytes,
        input_format=raw_fmt,
        output_format=fmt,
        pitch_factor=apply_pitch,
        rate_factor=1.0,  # speed already applied cleanly by engine
        delivery_style=style,
        trim_silence=True,
        room_ambience=use_ambience,
        normalize=True,
    )
    return TTSResult(
        audio_bytes=processed_bytes,
        media_type="audio/wav" if fmt == "wav" else "audio/mpeg",
        provider=used_provider,
        engine=used_engine,
        voice_id=used_voice,
        native_voice=native_voice,
        processing_applied=applied,
    )


async def synthesize_and_cache(
    *,
    text: str,
    persona_id: Optional[str] = None,
    provider_preference: Optional[str] = None,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
    pitch: Optional[float] = None,
    delivery_style: Optional[str] = None,
    room_ambience: Optional[bool] = None,
    output_format: str = "mp3",
    user_elevenlabs_key: Optional[str] = None,
    user_openai_key: Optional[str] = None,
    allow_premium_elevenlabs: bool = False,
    allow_hosted_openai: bool = True,
    persona_meta: Optional[dict] = None,
    eleven_text: Optional[str] = None,
    openai_instructions: Optional[str] = None,
    filename: Optional[str] = None,
) -> Tuple[str, TTSResult]:
    profile = await get_effective_profile(persona_id) if persona_id else None
    pref = (provider_preference or (profile or {}).get("voice_provider") or "free_local").lower()
    style = delivery_style or (profile or {}).get("speaking_style") or "casual"
    rate = float(speed if speed is not None else (profile or {}).get("speaking_rate") or 1.0)
    eff_pitch = float(pitch if pitch is not None else (profile or {}).get("pitch_adjustment") or 1.0)
    use_amb = bool(room_ambience if room_ambience is not None else ((profile or {}).get("audio_processing") or {}).get("room_ambience", False))
    vid = voice_id or (profile or {}).get("voice_id") or "default"
    fmt = "wav" if output_format.lower() == "wav" else "mp3"

    ck = cache_key_for(
        text=text,
        provider=f"{pref}:{'el' if allow_premium_elevenlabs else 'std'}",
        voice_id=f"{persona_id or 'none'}:{vid}",
        rate=rate,
        pitch=eff_pitch,
        delivery_style=style,
        room_ambience=use_amb,
        output_format=fmt,
    )

    if filename is None and ck in _CACHE:
        cached_url = _CACHE[ck]
        fname = cached_url.rsplit("/", 1)[-1]
        if (AUDIO_DIR / fname).is_file():
            _CACHE.move_to_end(ck)
            return cached_url, TTSResult(
                audio_bytes=b"",
                media_type="audio/wav" if fmt == "wav" else "audio/mpeg",
                provider="cache",
                engine="cache",
                voice_id=vid,
                native_voice=bool((profile or {}).get("native_voice_identity", True)),
                processing_applied=["cache_hit"],
            )
        _CACHE.pop(ck, None)

    async with _get_lock(ck):
        res = await synthesize_speech(
            text=text,
            persona_id=persona_id,
            provider_preference=provider_preference,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            delivery_style=delivery_style,
            room_ambience=room_ambience,
            output_format=fmt,
            user_elevenlabs_key=user_elevenlabs_key,
            user_openai_key=user_openai_key,
            allow_premium_elevenlabs=allow_premium_elevenlabs,
            allow_hosted_openai=allow_hosted_openai,
            persona_meta=persona_meta,
            eleven_text=eleven_text,
            openai_instructions=openai_instructions,
        )
        ext = "wav" if res.media_type == "audio/wav" else "mp3"
        out_name = filename or f"tts_{persona_id or 'voice'}_{ck[:16]}.{ext}"
        await save_audio(out_name, res.audio_bytes)
        url = f"/api/audio/{out_name}"
        if filename is None and res.provider != "sandbox_preview":
            _CACHE[ck] = url
            _CACHE.move_to_end(ck)
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
        return url, res
