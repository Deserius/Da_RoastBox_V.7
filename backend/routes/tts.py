"""Unified TTS & Voice Studio API endpoints."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_deps import get_current_user, get_optional_user
import config
from db import db
from models import User
from routes.personas import get_personas_by_ids
from services import roast_engine as eng
from services.tts import (
    DELIVERY_PROFILES,
    get_install_status,
    get_provider_health,
    list_all_voices,
    list_effective_profiles,
    get_effective_profile,
    reset_profile_to_default,
    save_profile_override,
    start_model_install,
    synthesize_and_cache,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["tts"])
_TTS_CLIPS = db["tts_preview_clips"]


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    persona_id: Optional[str] = Field(default=None, max_length=64)
    provider: Optional[str] = Field(default=None, max_length=32)
    voice_id: Optional[str] = Field(default=None, max_length=80)
    speed: Optional[float] = Field(default=None, ge=0.70, le=1.40)
    pitch: Optional[float] = Field(default=None, ge=0.85, le=1.15)
    delivery_style: Optional[str] = Field(default=None, max_length=40)
    room_ambience: Optional[bool] = None
    output_format: str = Field(default="mp3", pattern="^(mp3|wav)$")


class ProfileUpdateRequest(BaseModel):
    voice_provider: Optional[str] = Field(default=None, max_length=32)
    engine_model: Optional[str] = Field(default=None, max_length=64)
    voice_id: Optional[str] = Field(default=None, max_length=80)
    voice_display_name: Optional[str] = Field(default=None, max_length=120)
    piper_voice_id: Optional[str] = Field(default=None, max_length=80)
    edge_voice_id: Optional[str] = Field(default=None, max_length=80)
    pitch_adjustment: Optional[float] = Field(default=None, ge=0.85, le=1.15)
    speaking_rate: Optional[float] = Field(default=None, ge=0.80, le=1.30)
    speaking_style: Optional[str] = Field(default=None, max_length=40)
    delivery_personality: Optional[str] = Field(default=None, max_length=200)
    default_emotion: Optional[str] = Field(default=None, max_length=40)
    audio_processing: Optional[Dict[str, Any]] = None
    sample_preview_text: Optional[str] = Field(default=None, max_length=500)


class CompareCandidate(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    provider: Optional[str] = Field(default=None, max_length=32)
    voice_id: Optional[str] = Field(default=None, max_length=80)
    speed: Optional[float] = Field(default=1.0, ge=0.70, le=1.40)
    pitch: Optional[float] = Field(default=1.0, ge=0.85, le=1.15)
    delivery_style: Optional[str] = Field(default="casual", max_length=40)


class CompareRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    persona_id: Optional[str] = Field(default=None, max_length=64)
    candidates: List[CompareCandidate] = Field(..., min_length=2, max_length=4)


class ModelInstallRequest(BaseModel):
    target: str = Field(default="kokoro", pattern="^(kokoro|piper)$")
    piper_voice: str = Field(default="en_US-lessac-medium", max_length=80)


async def _record_clip_owner(user_id: str, audio_url: str) -> None:
    fname = Path(audio_url).name
    if fname:
        await _TTS_CLIPS.update_one(
            {"filename": fname, "user_id": user_id},
            {"$set": {"filename": fname, "user_id": user_id}},
            upsert=True,
        )


@router.get("/providers")
@router.get("/health")
async def tts_health(current_user: Optional[User] = Depends(get_optional_user)):
    byok_openai, byok_eleven = eng.user_byok(current_user) if current_user else (None, None)
    return get_provider_health(user_elevenlabs_key=byok_eleven, user_openai_key=byok_openai)


@router.get("/delivery-profiles")
async def list_delivery_profiles():
    return {"delivery_profiles": list(DELIVERY_PROFILES.values())}


@router.get("/voices")
async def list_voices(
    provider: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    accent: Optional[str] = Query(default=None),
    vocal_age: Optional[str] = Query(default=None),
    vocal_depth: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    free_only: Optional[bool] = Query(default=None),
):
    voices = list_all_voices()
    if provider:
        voices = [v for v in voices if v["provider"] == provider]
    if gender:
        voices = [v for v in voices if v["gender"].lower() == gender.lower()]
    if accent:
        voices = [v for v in voices if v["accent"].lower() == accent.lower()]
    if vocal_age:
        voices = [v for v in voices if v["vocal_age"].lower() == vocal_age.lower()]
    if vocal_depth:
        voices = [v for v in voices if v["vocal_depth"].lower() == vocal_depth.lower()]
    if tag:
        q = tag.lower()
        voices = [v for v in voices if any(q in t.lower() for t in v.get("tags", []))]
    if free_only is True:
        voices = [v for v in voices if v.get("is_free", True)]
    return {"voices": voices, "total": len(voices)}


@router.get("/profiles")
async def list_profiles():
    profiles = await list_effective_profiles()
    return {"profiles": profiles, "total": len(profiles)}


@router.get("/profiles/{persona_id}")
async def get_profile(persona_id: str):
    prof = await get_effective_profile(persona_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Unknown persona")
    return {"profile": prof}


@router.put("/profiles/{persona_id}")
async def update_profile(persona_id: str, body: ProfileUpdateRequest, current_user: User = Depends(get_current_user)):
    try:
        updated = await save_profile_override(persona_id, body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown persona")
    return {"profile": updated}


@router.post("/profiles/{persona_id}/reset")
async def reset_profile(persona_id: str, current_user: User = Depends(get_current_user)):
    try:
        restored = await reset_profile_to_default(persona_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown persona")
    return {"profile": restored}


@router.post("/speak")
@router.post("/preview")
async def speak_text(body: SpeakRequest, current_user: User = Depends(get_current_user)):
    byok_openai, byok_eleven = eng.user_byok(current_user)
    meta = None
    if body.persona_id:
        matches = get_personas_by_ids([body.persona_id])
        if not matches:
            raise HTTPException(status_code=404, detail="Unknown persona")
        meta = matches[0]
    allow_premium = bool(
        eng.has_premium_voices(current_user)
        and (not current_user.is_preview or bool(byok_eleven) or bool(config.PREVIEW_SANDBOX_FALLBACK))
    )
    if (body.provider or "").lower() == "elevenlabs" and not (byok_eleven or (allow_premium and config.ELEVENLABS_API_KEY)):
        raise HTTPException(
            status_code=402,
            detail="ElevenLabs requires your ElevenLabs API key in Settings or an unlocked Premium Voice pass. Free Local Kokoro/Piper voices are available with no key.",
        )
    try:
        url, result = await synthesize_and_cache(
            text=body.text,
            persona_id=body.persona_id,
            provider_preference=body.provider,
            voice_id=body.voice_id,
            speed=body.speed,
            pitch=body.pitch,
            delivery_style=body.delivery_style,
            room_ambience=body.room_ambience,
            output_format=body.output_format,
            user_elevenlabs_key=byok_eleven,
            user_openai_key=byok_openai,
            allow_premium_elevenlabs=allow_premium and (body.provider == "elevenlabs"),
            allow_hosted_openai=not current_user.is_preview,
            persona_meta=meta,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Speech synthesis unavailable: {exc}") from exc
    await _record_clip_owner(current_user.id, url)
    return {
        "audio_url": url,
        "provider": result.provider,
        "engine": result.engine,
        "voice_id": result.voice_id,
        "native_voice": result.native_voice,
        "processing_applied": result.processing_applied,
        "sandbox_preview": result.provider == "sandbox_preview",
        "text": body.text,
    }


@router.post("/compare")
async def compare_voices(body: CompareRequest, current_user: User = Depends(get_current_user)):
    byok_openai, byok_eleven = eng.user_byok(current_user)
    meta = get_personas_by_ids([body.persona_id])[0] if body.persona_id and get_personas_by_ids([body.persona_id]) else None
    allow_premium = bool(
        eng.has_premium_voices(current_user)
        and (not current_user.is_preview or bool(byok_eleven) or bool(config.PREVIEW_SANDBOX_FALLBACK))
    )
    comparisons = []
    for cand in body.candidates:
        try:
            url, result = await synthesize_and_cache(
                text=body.text,
                persona_id=body.persona_id,
                provider_preference=cand.provider,
                voice_id=cand.voice_id,
                speed=cand.speed,
                pitch=cand.pitch,
                delivery_style=cand.delivery_style,
                user_elevenlabs_key=byok_eleven,
                user_openai_key=byok_openai,
                allow_premium_elevenlabs=allow_premium and (cand.provider == "elevenlabs"),
                allow_hosted_openai=not current_user.is_preview,
                persona_meta=meta,
            )
            await _record_clip_owner(current_user.id, url)
            comparisons.append({
                "label": cand.label,
                "audio_url": url,
                "provider": result.provider,
                "engine": result.engine,
                "voice_id": result.voice_id,
                "sandbox_preview": result.provider == "sandbox_preview",
                "ok": True,
            })
        except Exception as exc:
            comparisons.append({
                "label": cand.label,
                "ok": False,
                "error": str(exc),
            })
    return {"text": body.text, "comparisons": comparisons}


@router.get("/models/status")
async def model_install_status():
    return get_install_status()


@router.post("/models/install")
async def model_install(body: ModelInstallRequest, current_user: User = Depends(get_current_user)):
    return await start_model_install(target=body.target, piper_voice=body.piper_voice)
