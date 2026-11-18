"""Persistent workspace-level key overrides for preview/local settings.

When PREVIEW_SANDBOX_FALLBACK is enabled, keys saved in Settings are encrypted
into backend/.workspace_keys.json (using Fernet derived from JWT_SECRET) and
synced to os.environ + backend/.env + live config attributes so they remain
active immediately across requests, preview re-logins, and server restarts.
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT_DIR / ".workspace_keys.json"

ALL_KEY_MAP = {
    "openai_key": "OPENAI_API_KEY",
    "openrouter_key": "OPENROUTER_API_KEY",
    "elevenlabs_key": "ELEVENLABS_API_KEY",
    "emergent_llm_key": "EMERGENT_LLM_KEY",
    "stripe_api_key": "STRIPE_API_KEY",
    "stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
}
BYOK_FIELDS = ("openai_key", "openrouter_key", "elevenlabs_key")


def _fernet() -> Fernet:
    secret = os.environ.get("JWT_SECRET") or "da-roastbox-workspace-fallback"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""


def _mask(value: str) -> str:
    s = value.strip()
    if len(s) <= 8:
        return "••••"
    return f"{s[:4]}••••{s[-4:]}"


def _read_raw() -> Dict[str, str]:
    if not STORE_PATH.is_file():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        out: Dict[str, str] = {}
        for k, enc in (data or {}).items():
            if isinstance(k, str) and isinstance(enc, str) and enc:
                dec = _decrypt(enc)
                if dec:
                    out[k] = dec
        return out
    except Exception:
        return {}


def _write_raw(plain: Dict[str, str]) -> None:
    if not plain:
        STORE_PATH.unlink(missing_ok=True)
        return
    encrypted = {k: _encrypt(v) for k, v in plain.items() if v and v.strip()}
    STORE_PATH.write_text(json.dumps(encrypted, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(STORE_PATH, 0o600)
    except OSError:
        pass


def _update_env_file(env_updates: Dict[str, str]) -> None:
    env_path = ROOT_DIR / ".env"
    if not env_path.is_file() or not env_updates:
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    remaining = dict(env_updates)
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


def apply_startup_workspace_keys() -> None:
    """Called from config.py during startup when PREVIEW_SANDBOX_FALLBACK=true."""
    if os.environ.get("PREVIEW_SANDBOX_FALLBACK", "false").strip().lower() not in ("1", "true", "yes"):
        return
    saved = _read_raw()
    for field, value in saved.items():
        env_name = ALL_KEY_MAP.get(field)
        if env_name and value:
            os.environ[env_name] = value


def get_saved_workspace_keys() -> Dict[str, str]:
    return _read_raw()


def get_saved_key(field: str) -> Optional[str]:
    return _read_raw().get(field)


def get_saved_key_masks() -> Dict[str, str]:
    saved = _read_raw()
    masks: Dict[str, str] = {}
    for field, env_name in ALL_KEY_MAP.items():
        val = saved.get(field) or os.environ.get(env_name, "").strip()
        if val:
            masks[field] = _mask(val)
    return masks


def save_workspace_keys(updates: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Persist provided keys to .workspace_keys.json, os.environ, config, and .env."""
    import sys
    import config

    current = _read_raw()
    env_updates: Dict[str, str] = {}
    for field, val in updates.items():
        if field not in ALL_KEY_MAP or val is None:
            continue
        cleaned = val.strip()
        env_name = ALL_KEY_MAP[field]
        if cleaned:
            current[field] = cleaned
            os.environ[env_name] = cleaned
            env_updates[env_name] = cleaned
            if hasattr(config, env_name):
                setattr(config, env_name, cleaned)
            for mod_name in ("routes.payments", "routes.auth", "services.voice_orchestrator", "services.roast_writer"):
                mod = sys.modules.get(mod_name)
                if mod is not None and hasattr(mod, env_name):
                    setattr(mod, env_name, cleaned)
        else:
            current.pop(field, None)
    _write_raw(current)
    if env_updates:
        _update_env_file(env_updates)
    return current


def clear_workspace_byok_keys() -> None:
    """Remove user-entered BYOK keys (openai/openrouter/elevenlabs) from workspace store."""
    current = _read_raw()
    for f in BYOK_FIELDS:
        current.pop(f, None)
    _write_raw(current)
