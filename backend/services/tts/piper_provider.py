"""Piper TTS lightweight local CPU fallback provider.

Models are downloaded explicitly from official Rhasspy/Piper HuggingFace/GitHub
distributions outside frontend/public under backend/models/tts/piper/.
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import urllib.request
import wave
from pathlib import Path
from typing import Dict, List, Optional

from .base import TTSVoice

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "tts" / "piper"
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

PIPER_VOICES: List[TTSVoice] = [
    TTSVoice("en_US-ryan-high", "Ryan (American Male Deep)", "piper", "piper-onnx", "male", "adult", "American", "deep", True, True, ["american", "deep", "clear"], "MIT"),
    TTSVoice("en_US-lessac-medium", "Lessac (American Female Crisp)", "piper", "piper-onnx", "female", "adult", "American", "medium", True, True, ["american", "crisp", "narrator"], "MIT"),
    TTSVoice("en_US-amy-medium", "Amy (American Female Bright)", "piper", "piper-onnx", "female", "young_adult", "American", "bright", True, True, ["american", "bright", "casual"], "MIT"),
    TTSVoice("en_US-joe-medium", "Joe (American Male Casual)", "piper", "piper-onnx", "male", "adult", "American", "medium", True, True, ["american", "casual", "warm"], "MIT"),
    TTSVoice("en_US-bryce-medium", "Bryce (American Male Young)", "piper", "piper-onnx", "male", "young_adult", "American", "medium", True, True, ["american", "fast", "energetic"], "MIT"),
    TTSVoice("en_US-kristin-medium", "Kristin (American Female Mature)", "piper", "piper-onnx", "female", "mature", "American", "medium", True, True, ["american", "mature", "sarcastic"], "MIT"),
    TTSVoice("en_GB-alan-medium", "Alan (British Male Classic)", "piper", "piper-onnx", "male", "older", "British", "deep", True, True, ["british", "older", "dry"], "MIT"),
    TTSVoice("en_GB-alba-medium", "Alba (British Female Warm)", "piper", "piper-onnx", "female", "adult", "British", "medium", True, True, ["british", "warm", "comedic"], "MIT"),
]

_HF_REL_PATHS: Dict[str, str] = {
    "en_US-ryan-high": "en/en_US/ryan/high/en_US-ryan-high",
    "en_US-lessac-medium": "en/en_US/lessac/medium/en_US-lessac-medium",
    "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium",
    "en_US-joe-medium": "en/en_US/joe/medium/en_US-joe-medium",
    "en_US-bryce-medium": "en/en_US/bryce/medium/en_US-bryce-medium",
    "en_US-kristin-medium": "en/en_US/kristin/medium/en_US-kristin-medium",
    "en_GB-alan-medium": "en/en_GB/alan/medium/en_GB-alan-medium",
    "en_GB-alba-medium": "en/en_GB/alba/medium/en_GB-alba-medium",
}

_VOICE_MAP = {v.voice_id: v for v in PIPER_VOICES}
_CACHE_LOCK = threading.Lock()
_LOADED_VOICES: Dict[str, object] = {}


def is_package_installed() -> bool:
    try:
        from piper.voice import PiperVoice  # noqa: F401
        return True
    except ImportError:
        return False


def installed_voice_ids() -> List[str]:
    out = []
    for vid in _VOICE_MAP:
        onnx = MODELS_DIR / f"{vid}.onnx"
        cfg = MODELS_DIR / f"{vid}.onnx.json"
        if onnx.is_file() and cfg.is_file() and onnx.stat().st_size > 1_000_000:
            out.append(vid)
    return out


def check_health() -> Dict[str, object]:
    pkg_ok = is_package_installed()
    ready = installed_voice_ids()
    if not pkg_ok:
        status = "missing_dependencies"
        detail = "Install piper-tts to enable lightweight Piper fallback."
    elif not ready:
        status = "missing_model_files"
        detail = "No Piper .onnx voices downloaded yet (optional CPU fallback)."
    else:
        status = "operational"
        detail = f"Piper ready with {len(ready)} local voice(s)."
    return {
        "provider": "piper",
        "display_name": "Piper TTS (Lightweight Local Fallback)",
        "is_free": True,
        "installed": pkg_ok,
        "models_ready": bool(ready),
        "operational": pkg_ok and bool(ready),
        "status": status,
        "detail": detail,
        "installed_voices": ready,
        "license": "MIT",
        "native_voices_count": len(PIPER_VOICES),
    }


def list_voices() -> List[Dict]:
    return [v.to_dict() for v in PIPER_VOICES]


def install_voice_sync(voice_id: str = "en_US-lessac-medium") -> Dict[str, object]:
    if voice_id not in _HF_REL_PATHS:
        raise ValueError(f"Unknown Piper voice: {voice_id}")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    rel = _HF_REL_PATHS[voice_id]
    for ext in (".onnx", ".onnx.json"):
        dest = MODELS_DIR / f"{voice_id}{ext}"
        if dest.is_file() and dest.stat().st_size > 500:
            continue
        url = f"{HF_BASE}/{rel}{ext}"
        tmp = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "DaRoastBox-TTS-Installer/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp.write_bytes(resp.read())
        tmp.replace(dest)
    return check_health()


def _get_voice(voice_id: str):
    ready = installed_voice_ids()
    if not ready:
        raise FileNotFoundError("No Piper voice models installed")
    vid = voice_id if voice_id in ready else ready[0]
    with _CACHE_LOCK:
        if vid not in _LOADED_VOICES:
            from piper.voice import PiperVoice
            # Keep memory bounded on 8GB machines: cache at most 2 Piper models at once.
            if len(_LOADED_VOICES) >= 2:
                _LOADED_VOICES.clear()
            _LOADED_VOICES[vid] = PiperVoice.load(str(MODELS_DIR / f"{vid}.onnx"))
        return _LOADED_VOICES[vid]


def synthesize_sync(text: str, voice_id: str = "en_US-lessac-medium", speed: float = 1.0) -> bytes:
    voice = _get_voice(voice_id)
    from piper.voice import SynthesisConfig
    length_scale = max(0.65, min(1.5, 1.0 / max(0.65, float(speed or 1.0))))
    syn_cfg = SynthesisConfig(length_scale=length_scale)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn_cfg)
    return buf.getvalue()


async def synthesize(text: str, voice_id: str = "en_US-lessac-medium", speed: float = 1.0) -> bytes:
    return await asyncio.to_thread(synthesize_sync, text, voice_id, speed)
