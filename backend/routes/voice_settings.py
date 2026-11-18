"""API key management & pre-activation verification for BYOK and workspace config."""
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth_deps import get_current_user
import config
from config import PREVIEW_SANDBOX_FALLBACK, ROOT_DIR, STRIPE_TEST_ONLY
from crypto_utils import encrypt
from db import users_collection
from models import User
from services.sandbox_preview import is_network_connection_error
from services.workspace_keys import clear_workspace_byok_keys, get_saved_key_masks, save_workspace_keys

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice-settings", tags=["voice-settings"])


class KeysBody(BaseModel):
    openai_key: Optional[str] = None
    elevenlabs_key: Optional[str] = None
    openrouter_key: Optional[str] = None


class VerifyAndSaveBody(KeysBody):
    emergent_llm_key: Optional[str] = None
    stripe_api_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    activate: bool = True


def _clean_val(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = val.strip()
    return s if s else None


def _check_format(field: str, value: str) -> Optional[str]:
    if any(ch.isspace() for ch in value):
        return "Key must not contain spaces or newlines"
    if field == "openai_key":
        if not value.startswith("sk-") or len(value) < 20:
            return "OpenAI keys start with 'sk-' and are at least 20 characters"
    elif field == "openrouter_key":
        if not value.startswith("sk-or-") or len(value) < 20:
            return "OpenRouter keys start with 'sk-or-' and are at least 20 characters"
    elif field == "elevenlabs_key":
        if len(value) < 16:
            return "ElevenLabs key looks too short (expected 16+ characters)"
    elif field == "emergent_llm_key":
        if len(value) < 16:
            return "Emergent LLM key looks too short"
    elif field == "stripe_api_key":
        if STRIPE_TEST_ONLY and not value.startswith(("sk_test_", "rk_test_")):
            return "Test-only mode requires a Stripe test key starting with 'sk_test_' or 'rk_test_'"
        if not value.startswith(("sk_test_", "rk_test_", "sk_live_", "rk_live_")) or len(value) < 20:
            return "Stripe secret key must start with 'sk_test_' / 'sk_live_' / 'rk_test_'"
    elif field == "stripe_webhook_secret":
        if not value.startswith("whsec_") or len(value) < 18:
            return "Stripe webhook secret must start with 'whsec_'"
    elif field == "google_client_id":
        if not value.endswith(".apps.googleusercontent.com") or len(value) < 30:
            return "Google Client ID must end with '.apps.googleusercontent.com'"
    elif field == "google_client_secret":
        if len(value) < 12:
            return "Google Client Secret looks too short"
    return None


async def _probe_live(field: str, value: str) -> Dict[str, object]:
    err = _check_format(field, value)
    if err:
        return {"ok": False, "status": "invalid_format", "message": err}

    probes = {
        "openai_key": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {value}"}),
        "openrouter_key": ("https://openrouter.ai/api/v1/auth/key", {"Authorization": f"Bearer {value}"}),
        "elevenlabs_key": ("https://api.elevenlabs.io/v1/user", {"xi-api-key": value}),
        "stripe_api_key": ("https://api.stripe.com/v1/balance", {"Authorization": f"Bearer {value}"}),
    }
    if field not in probes:
        return {"ok": True, "status": "format_ok", "message": "Format verified"}

    url, headers = probes[field]
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return {"ok": True, "status": "verified", "message": "Verified live with provider"}
        if resp.status_code in (401, 403):
            return {"ok": False, "status": "rejected", "message": f"Provider rejected key (HTTP {resp.status_code})"}
        if resp.status_code == 429:
            return {"ok": True, "status": "verified_rate_limited", "message": "Key recognized (provider rate limited)"}
        return {"ok": False, "status": "error", "message": f"Unexpected provider status HTTP {resp.status_code}"}
    except Exception as exc:
        if PREVIEW_SANDBOX_FALLBACK and is_network_connection_error(exc):
            return {
                "ok": True,
                "status": "format_ok_sandbox",
                "message": "Format valid (live provider check blocked by Arena sandbox network)",
            }
        return {"ok": False, "status": "unreachable", "message": f"Could not reach provider ({type(exc).__name__})"}


def _update_local_env(updates: Dict[str, str]) -> None:
    """Persist workspace env overrides when running in local/sandbox preview mode."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    new_lines = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in remaining:
            k = m.group(1)
            val = remaining.pop(k)
            quoted = f"'{val}'" if any(c in val for c in (" ", "#")) else val
            new_lines.append(f"{k}={quoted}")
        else:
            new_lines.append(line)
    for k, val in remaining.items():
        quoted = f"'{val}'" if any(c in val for c in (" ", "#")) else val
        new_lines.append(f"{k}={quoted}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for k, val in updates.items():
        os.environ[k] = val


@router.post("/keys")
async def update_keys(body: KeysBody, current_user: User = Depends(get_current_user)):
    update = {}
    if body.openai_key is not None:
        if body.openai_key.strip():
            update["openai_key_encrypted"] = encrypt(body.openai_key.strip())
            update["has_byok_openai"] = True
        else:
            update["openai_key_encrypted"] = None
            update["has_byok_openai"] = False
    if body.elevenlabs_key is not None:
        if body.elevenlabs_key.strip():
            update["elevenlabs_key_encrypted"] = encrypt(body.elevenlabs_key.strip())
            update["has_byok_elevenlabs"] = True
        else:
            update["elevenlabs_key_encrypted"] = None
            update["has_byok_elevenlabs"] = False
    if body.openrouter_key is not None:
        if body.openrouter_key.strip():
            update["openrouter_key_encrypted"] = encrypt(body.openrouter_key.strip())
            update["has_byok_openrouter"] = True
        else:
            update["openrouter_key_encrypted"] = None
            update["has_byok_openrouter"] = False
    if not update:
        raise HTTPException(status_code=400, detail="No keys provided")

    await users_collection.update_one({"id": current_user.id}, {"$set": update})
    if config.PREVIEW_SANDBOX_FALLBACK:
        save_workspace_keys({
            "openai_key": body.openai_key,
            "elevenlabs_key": body.elevenlabs_key,
            "openrouter_key": body.openrouter_key,
        })
    return {"status": "ok",
            "has_byok_openai": update.get("has_byok_openai", current_user.has_byok_openai),
            "has_byok_elevenlabs": update.get("has_byok_elevenlabs", current_user.has_byok_elevenlabs),
            "has_byok_openrouter": update.get("has_byok_openrouter", getattr(current_user, "has_byok_openrouter", False)),
            "saved_key_masks": get_saved_key_masks() if config.PREVIEW_SANDBOX_FALLBACK else {}}


@router.post("/verify")
@router.post("/verify-and-save")
async def verify_and_save_keys(body: VerifyAndSaveBody, current_user: User = Depends(get_current_user)):
    fields = {
        "openai_key": _clean_val(body.openai_key),
        "openrouter_key": _clean_val(body.openrouter_key),
        "elevenlabs_key": _clean_val(body.elevenlabs_key),
        "emergent_llm_key": _clean_val(body.emergent_llm_key),
        "stripe_api_key": _clean_val(body.stripe_api_key),
        "stripe_webhook_secret": _clean_val(body.stripe_webhook_secret),
        "google_client_id": _clean_val(body.google_client_id),
        "google_client_secret": _clean_val(body.google_client_secret),
    }
    provided = {k: v for k, v in fields.items() if v is not None}
    if not provided:
        raise HTTPException(status_code=400, detail="Enter at least one API key to verify")

    results = {}
    for k, val in provided.items():
        results[k] = await _probe_live(k, val)

    all_valid = all(item["ok"] for item in results.values())
    if not all_valid:
        return JSONResponse(
            status_code=422,
            content={
                "status": "failed",
                "all_valid": False,
                "activated": False,
                "detail": "One or more keys failed verification and were NOT activated.",
                "results": results,
            },
        )

    if not body.activate:
        return {"status": "verified", "all_valid": True, "activated": False, "results": results}

    user_update = {}
    if "openai_key" in provided:
        user_update["openai_key_encrypted"] = encrypt(provided["openai_key"])
        user_update["has_byok_openai"] = True
    if "elevenlabs_key" in provided:
        user_update["elevenlabs_key_encrypted"] = encrypt(provided["elevenlabs_key"])
        user_update["has_byok_elevenlabs"] = True
    if "openrouter_key" in provided:
        user_update["openrouter_key_encrypted"] = encrypt(provided["openrouter_key"])
        user_update["has_byok_openrouter"] = True
    if user_update:
        await users_collection.update_one({"id": current_user.id}, {"$set": user_update})

    server_env_updated = False
    if config.PREVIEW_SANDBOX_FALLBACK:
        save_workspace_keys(provided)
        server_env_updated = True

    return {
        "status": "activated",
        "all_valid": True,
        "activated": True,
        "server_env_updated": server_env_updated,
        "results": results,
        "saved_key_masks": get_saved_key_masks() if config.PREVIEW_SANDBOX_FALLBACK else {},
        "has_byok_openai": user_update.get("has_byok_openai", current_user.has_byok_openai),
        "has_byok_elevenlabs": user_update.get("has_byok_elevenlabs", current_user.has_byok_elevenlabs),
        "has_byok_openrouter": user_update.get("has_byok_openrouter", getattr(current_user, "has_byok_openrouter", False)),
    }


@router.delete("/keys")
async def clear_keys(current_user: User = Depends(get_current_user)):
    await users_collection.update_one(
        {"id": current_user.id},
        {"$set": {
            "openai_key_encrypted": None, "has_byok_openai": False,
            "elevenlabs_key_encrypted": None, "has_byok_elevenlabs": False,
            "openrouter_key_encrypted": None, "has_byok_openrouter": False,
        }},
    )
    if config.PREVIEW_SANDBOX_FALLBACK:
        clear_workspace_byok_keys()
    return {"status": "ok"}
