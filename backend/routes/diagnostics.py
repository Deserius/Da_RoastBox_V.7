"""Health + diagnostics endpoints. Deep checks make live calls to each provider."""
import asyncio
import logging
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from auth_deps import get_optional_user
from models import User

from config import (APP_VERSION, EMERGENT_LLM_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, STRIPE_API_KEY,
                    ELEVENLABS_API_KEY, STRIPE_TEST_ONLY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
                    ROAST_WRITER_PROVIDER, ROAST_WRITER_PROFILE, ROAST_WRITER_MODEL,
                    ALLOW_DEV_LOGIN, ALLOW_SOURCE_DOWNLOAD, ENABLE_PREVIEW_LOGIN,
                    ALLOW_PREVIEW_HOSTED_AI, PREVIEW_HOSTED_DAILY_SHOW_LIMIT, PREVIEW_HOSTED_DAILY_VOICE_LIMIT,
                    PREVIEW_UNLIMITED_CREDITS, PREVIEW_SANDBOX_FALLBACK, ALLOW_PREVIEW_TEST_PAYMENTS,
                    STORAGE_BACKEND, STRIPE_WEBHOOK_SECRET, AUDIO_DIR, DATA_DIR)
from db import db
from routes.personas import all_personas

log = logging.getLogger(__name__)
router = APIRouter(tags=["diagnostics"])

DEEP_CACHE_SECONDS = 600
_deep_cache: dict = {"at": 0.0, "checks": None}


async def _timed(coro):
    start = time.perf_counter()
    try:
        detail = await coro
        return {"ok": True, "ms": round((time.perf_counter() - start) * 1000), "detail": detail}
    except Exception as e:
        return {"ok": False, "ms": round((time.perf_counter() - start) * 1000), "error": str(e)[:300]}


async def _check_mongo():
    await db.command("ping")
    return "ping ok"


async def _check_llm():
    from services.openai_service import get_client
    client = get_client(timeout=30)
    resp = await asyncio.to_thread(
        client.chat.completions.create, model="gpt-4o", max_tokens=5,
        messages=[{"role": "user", "content": "Reply with: ok"}],
    )
    return (resp.choices[0].message.content or "").strip()


async def _check_tts():
    from services.openai_service import synthesize_tts_openai
    audio = await synthesize_tts_openai("Test.", voice="ash", instructions="Cocky comedian.")
    return f"{len(audio)} bytes mp3"


async def _check_stripe():
    from routes.payments import StripeCheckout
    if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("Both STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET are required for checkout")
    StripeCheckout(api_key=STRIPE_API_KEY, webhook_secret=STRIPE_WEBHOOK_SECRET, webhook_url=None)
    # Initialising a client does not validate credentials; query the account instead.
    import stripe
    await asyncio.to_thread(stripe.Account.retrieve)
    return "Stripe account reachable"


async def _check_storage():
    from services.storage import init_storage
    if not await init_storage():
        raise RuntimeError("Configured storage is not available")
    return f"{STORAGE_BACKEND} storage ready"


async def _check_elevenlabs():
    from services.elevenlabs_service import check_elevenlabs_key
    await check_elevenlabs_key(ELEVENLABS_API_KEY)
    return "key valid"


def _persona_integrity():
    personas = all_personas()
    public_dir = DATA_DIR.parent.parent / "frontend" / "public"
    missing_img = [p["id"] for p in personas if not (public_dir / p["image"]).exists()] if public_dir.exists() else []
    missing_voice = [p["id"] for p in personas if not p.get("tts_voice") or not p.get("elevenlabs")]
    return {
        "total": len(personas),
        "free": sum(p.get("tier") != "premium" for p in personas),
        "premium": sum(p.get("tier") == "premium" for p in personas),
        "missing_images": missing_img,
        "missing_voice_config": missing_voice,
    }


async def _deep_checks() -> dict:
    """Live provider calls, cached so repeated requests can't burn LLM budget."""
    if _deep_cache["checks"] and time.time() - _deep_cache["at"] < DEEP_CACHE_SECONDS:
        return {**_deep_cache["checks"], "cached": {"ok": True, "age_s": round(time.time() - _deep_cache["at"])}}
    tasks = {"llm": _check_llm(), "tts": _check_tts(), "stripe": _check_stripe(), "storage": _check_storage()}
    if ELEVENLABS_API_KEY:
        tasks["elevenlabs"] = _check_elevenlabs()
    results = dict(zip(tasks.keys(), await asyncio.gather(*[_timed(c) for c in tasks.values()])))
    _deep_cache.update(at=time.time(), checks=results)
    return results


@router.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@router.get("/diagnostics")
async def diagnostics(deep: bool = False, user: Optional[User] = Depends(get_optional_user)):
    """Config summary; `?deep=true` (signed-in only) performs live provider calls."""
    import config as cfg
    from services.workspace_keys import get_saved_key_masks
    if deep and not user:
        raise HTTPException(status_code=401, detail="Sign in to run deep diagnostics")
    if deep and user and user.is_preview:
        raise HTTPException(status_code=403, detail="Live provider diagnostics are disabled for preview accounts.")
    report = {
        "version": APP_VERSION,
        "config": {
            "emergent_llm_key": bool(cfg.EMERGENT_LLM_KEY),
            "openai_hosted_key": bool(cfg.OPENAI_API_KEY),
            "openrouter_hosted_key": bool(cfg.OPENROUTER_API_KEY),
            "stripe_api_key": bool(cfg.STRIPE_API_KEY),
            "stripe_test_only": cfg.STRIPE_TEST_ONLY,
            "elevenlabs_hosted_key": bool(cfg.ELEVENLABS_API_KEY),
            "google_oauth_configured": bool(cfg.GOOGLE_CLIENT_ID and cfg.GOOGLE_CLIENT_SECRET),
            "roast_writer_provider": cfg.ROAST_WRITER_PROVIDER,
            "roast_writer_profile": cfg.ROAST_WRITER_PROFILE,
            "roast_writer_model": cfg.ROAST_WRITER_MODEL,
            "dev_login_enabled": cfg.ALLOW_DEV_LOGIN,
            "source_download_enabled": cfg.ALLOW_SOURCE_DOWNLOAD,
            "preview_login_enabled": cfg.ENABLE_PREVIEW_LOGIN,
            "preview_hosted_ai_enabled": cfg.ENABLE_PREVIEW_LOGIN and cfg.ALLOW_PREVIEW_HOSTED_AI and bool(cfg.EMERGENT_LLM_KEY or cfg.OPENAI_API_KEY or cfg.OPENROUTER_API_KEY),
            "preview_hosted_daily_show_limit": "unlimited" if cfg.PREVIEW_HOSTED_DAILY_SHOW_LIMIT < 0 else cfg.PREVIEW_HOSTED_DAILY_SHOW_LIMIT,
            "preview_hosted_daily_voice_limit": "unlimited" if cfg.PREVIEW_HOSTED_DAILY_VOICE_LIMIT < 0 else cfg.PREVIEW_HOSTED_DAILY_VOICE_LIMIT,
            "preview_unlimited_credits": cfg.PREVIEW_UNLIMITED_CREDITS,
            "preview_sandbox_fallback": cfg.PREVIEW_SANDBOX_FALLBACK,
            "test_payments_enabled": bool(
                cfg.ALLOW_PREVIEW_TEST_PAYMENTS
                and cfg.STRIPE_TEST_ONLY
                and cfg.STRIPE_API_KEY.startswith(("sk_test_", "rk_test_"))
            ),
            "saved_key_masks": get_saved_key_masks() if cfg.PREVIEW_SANDBOX_FALLBACK else {},
            "storage_backend": cfg.STORAGE_BACKEND,
            "stripe_webhook_secret": bool(cfg.STRIPE_WEBHOOK_SECRET),
            "audio_cache_writable": cfg.AUDIO_DIR.exists(),
        },
        "personas": _persona_integrity(),
        "checks": {"mongo": await _timed(_check_mongo())},
    }
    if deep:
        report["checks"].update(await _deep_checks())
    report["warnings"] = []
    if not (EMERGENT_LLM_KEY or OPENAI_API_KEY):
        report["warnings"].append("Hosted AI key missing; configure OpenAI/Emergent or use a personal key in Settings.")
    if not STRIPE_API_KEY:
        report["warnings"].append("Stripe API key missing; checkout is disabled.")
    if not STRIPE_WEBHOOK_SECRET:
        report["warnings"].append("Stripe webhook signing secret missing; checkout and webhooks are disabled.")
    report["status"] = "ok" if not report["warnings"] and all(c["ok"] for c in report["checks"].values()) else "degraded"
    return report
