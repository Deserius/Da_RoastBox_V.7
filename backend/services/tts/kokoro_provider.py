"""Kokoro-82M local neural TTS provider (CPU-friendly via kokoro-onnx + onnxruntime).

License: Kokoro-82M weights & kokoro-onnx are Apache-2.0 (commercial use permitted).
Model files live outside frontend/public under backend/models/tts/kokoro/.
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

import soundfile as sf

from .base import TTSVoice

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "tts" / "kokoro"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices-v1.0.bin"
MIN_MODEL_BYTES = 50_000_000
MIN_VOICES_BYTES = 5_000_000

_LOAD_LOCK = threading.Lock()
_KOKORO_INSTANCE = None

# 27 genuine distinct Kokoro-82M v1.0 voice identities (American + British).
KOKORO_VOICES: List[TTSVoice] = [
    TTSVoice("af_heart", "Heart (Warm Expressive)", "kokoro", "kokoro-82m-onnx", "female", "adult", "American", "medium", True, True, ["warm", "expressive", "comedic"], "Apache-2.0"),
    TTSVoice("af_bella", "Bella (Sharp & Confident)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "American", "medium", True, True, ["sharp", "confident", "fast"], "Apache-2.0"),
    TTSVoice("af_nicole", "Nicole (Smooth Whisper-Capable)", "kokoro", "kokoro-82m-onnx", "female", "adult", "American", "soft", True, True, ["smooth", "intimate", "sarcastic"], "Apache-2.0"),
    TTSVoice("af_sarah", "Sarah (Clear & Crisp)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "American", "bright", True, True, ["crisp", "casual", "comedic"], "Apache-2.0"),
    TTSVoice("af_sky", "Sky (Bright & Playful)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "American", "higher", True, True, ["playful", "energetic", "fast"], "Apache-2.0"),
    TTSVoice("af_nova", "Nova (Bold & Punchy)", "kokoro", "kokoro-82m-onnx", "female", "adult", "American", "medium", True, True, ["bold", "comedic", "roast"], "Apache-2.0"),
    TTSVoice("af_alloy", "Alloy (Neutral Studio)", "kokoro", "kokoro-82m-onnx", "female", "adult", "American", "medium", True, True, ["balanced", "deadpan", "clear"], "Apache-2.0"),
    TTSVoice("af_aoede", "Aoede (Dramatic & Rich)", "kokoro", "kokoro-82m-onnx", "female", "mature", "American", "deep", True, True, ["dramatic", "theatrical", "rich"], "Apache-2.0"),
    TTSVoice("af_jessica", "Jessica (Quick Wit)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "American", "bright", True, True, ["snappy", "sarcastic", "fast"], "Apache-2.0"),
    TTSVoice("af_kore", "Kore (Measured & Cool)", "kokoro", "kokoro-82m-onnx", "female", "adult", "American", "medium", True, True, ["cool", "deadpan", "slow"], "Apache-2.0"),
    TTSVoice("af_river", "River (Chill & Dry)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "American", "medium", True, True, ["chill", "dry", "deadpan"], "Apache-2.0"),
    TTSVoice("am_adam", "Adam (Classic Arena Host)", "kokoro", "kokoro-82m-onnx", "male", "adult", "American", "deep", True, True, ["host", "energetic", "comedic"], "Apache-2.0"),
    TTSVoice("am_michael", "Michael (Rich Baritone)", "kokoro", "kokoro-82m-onnx", "male", "mature", "American", "deep", True, True, ["baritone", "dramatic", "authoritative"], "Apache-2.0"),
    TTSVoice("am_fenrir", "Fenrir (Heavy Gravel)", "kokoro", "kokoro-82m-onnx", "male", "mature", "American", "very_deep", True, True, ["gravel", "aggressive", "roast"], "Apache-2.0"),
    TTSVoice("am_liam", "Liam (Fast Millennial)", "kokoro", "kokoro-82m-onnx", "male", "young_adult", "American", "medium", True, True, ["fast", "sarcastic", "energetic"], "Apache-2.0"),
    TTSVoice("am_onyx", "Onyx (Low & Smooth)", "kokoro", "kokoro-82m-onnx", "male", "adult", "American", "deep", True, True, ["smooth", "cool", "dramatic"], "Apache-2.0"),
    TTSVoice("am_puck", "Puck (Mischievous Comic)", "kokoro", "kokoro-82m-onnx", "male", "young_adult", "American", "higher", True, True, ["mischievous", "comedic", "fast"], "Apache-2.0"),
    TTSVoice("am_echo", "Echo (Crisp Tenor)", "kokoro", "kokoro-82m-onnx", "male", "young_adult", "American", "medium", True, True, ["crisp", "energetic", "narrator"], "Apache-2.0"),
    TTSVoice("am_eric", "Eric (Dry Conversational)", "kokoro", "kokoro-82m-onnx", "male", "adult", "American", "medium", True, True, ["deadpan", "casual", "dry"], "Apache-2.0"),
    TTSVoice("bf_emma", "Emma (Refined British)", "kokoro", "kokoro-82m-onnx", "female", "adult", "British", "medium", True, True, ["british", "sarcastic", "posh"], "Apache-2.0"),
    TTSVoice("bf_isabella", "Isabella (Velvet British)", "kokoro", "kokoro-82m-onnx", "female", "mature", "British", "deep", True, True, ["british", "dramatic", "icy"], "Apache-2.0"),
    TTSVoice("bf_alice", "Alice (Sharp London)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "British", "bright", True, True, ["british", "snappy", "comedic"], "Apache-2.0"),
    TTSVoice("bf_lily", "Lily (Warm British)", "kokoro", "kokoro-82m-onnx", "female", "young_adult", "British", "medium", True, True, ["british", "casual", "warm"], "Apache-2.0"),
    TTSVoice("bm_george", "George (Commanding British)", "kokoro", "kokoro-82m-onnx", "male", "older", "British", "deep", True, True, ["british", "older", "authoritative"], "Apache-2.0"),
    TTSVoice("bm_lewis", "Lewis (Dry British Wit)", "kokoro", "kokoro-82m-onnx", "male", "adult", "British", "medium", True, True, ["british", "deadpan", "sarcastic"], "Apache-2.0"),
    TTSVoice("bm_daniel", "Daniel (Polished British)", "kokoro", "kokoro-82m-onnx", "male", "adult", "British", "medium", True, True, ["british", "narrator", "dramatic"], "Apache-2.0"),
    TTSVoice("bm_fable", "Fable (Storyteller British)", "kokoro", "kokoro-82m-onnx", "male", "mature", "British", "deep", True, True, ["british", "storyteller", "theatrical"], "Apache-2.0"),
]

_VOICE_MAP = {v.voice_id: v for v in KOKORO_VOICES}


def model_paths() -> tuple[Path, Path]:
    return MODELS_DIR / MODEL_FILENAME, MODELS_DIR / VOICES_FILENAME


def is_package_installed() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def models_present() -> bool:
    m, v = model_paths()
    return m.is_file() and v.is_file() and m.stat().st_size >= MIN_MODEL_BYTES and v.stat().st_size >= MIN_VOICES_BYTES


def check_health() -> Dict[str, object]:
    pkg_ok = is_package_installed()
    files_ok = models_present()
    if not pkg_ok:
        status = "missing_dependencies"
        detail = "Install kokoro-onnx and onnxruntime to enable Kokoro-82M."
    elif not files_ok:
        status = "missing_model_files"
        detail = "Kokoro-82M weights (~337 MB) not yet downloaded. Run model install in Voice Studio."
    else:
        status = "operational" if _KOKORO_INSTANCE is not None else "available"
        detail = "Kokoro-82M CPU neural TTS ready."
    return {
        "provider": "kokoro",
        "display_name": "Kokoro-82M (Free Local AI)",
        "is_free": True,
        "installed": pkg_ok,
        "models_ready": files_ok,
        "loaded": _KOKORO_INSTANCE is not None,
        "operational": pkg_ok and files_ok,
        "status": status,
        "detail": detail,
        "license": "Apache-2.0",
        "native_voices_count": len(KOKORO_VOICES),
    }


def list_voices() -> List[Dict]:
    return [v.to_dict() for v in KOKORO_VOICES]


def get_voice(voice_id: str) -> Optional[TTSVoice]:
    return _VOICE_MAP.get(voice_id)


def unload_model() -> None:
    global _KOKORO_INSTANCE
    with _LOAD_LOCK:
        _KOKORO_INSTANCE = None


def _get_model():
    global _KOKORO_INSTANCE
    if _KOKORO_INSTANCE is not None:
        return _KOKORO_INSTANCE
    if not is_package_installed():
        raise RuntimeError("kokoro-onnx package is not installed")
    if not models_present():
        raise FileNotFoundError("Kokoro-82M model files are missing. Install models from Voice Studio first.")
    with _LOAD_LOCK:
        if _KOKORO_INSTANCE is None:
            from kokoro_onnx import Kokoro
            m, v = model_paths()
            _KOKORO_INSTANCE = Kokoro(str(m), str(v))
    return _KOKORO_INSTANCE


def _download_file(url: str, dest: Path, min_bytes: int, progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "DaRoastBox-TTS-Installer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(262_144)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    if tmp.stat().st_size < min_bytes:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded file {dest.name} is unexpectedly small ({dest.stat().st_size if dest.exists() else 0} bytes)")
    tmp.replace(dest)


def install_models_sync(progress_cb: Optional[Callable[[str, int], None]] = None) -> Dict[str, object]:
    m, v = model_paths()
    if progress_cb:
        progress_cb("Downloading Kokoro voices pack (voices-v1.0.bin)...", 5)
    if not (v.is_file() and v.stat().st_size >= MIN_VOICES_BYTES):
        _download_file(VOICES_URL, v, MIN_VOICES_BYTES,
                       lambda d, t: progress_cb("Downloading voices-v1.0.bin...", 5 + int(15 * (d / max(t, 1)))) if progress_cb else None)
    if progress_cb:
        progress_cb("Downloading Kokoro-82M ONNX weights (kokoro-v1.0.onnx)...", 22)
    if not (m.is_file() and m.stat().st_size >= MIN_MODEL_BYTES):
        _download_file(MODEL_URL, m, MIN_MODEL_BYTES,
                       lambda d, t: progress_cb("Downloading kokoro-v1.0.onnx...", 22 + int(73 * (d / max(t, 1)))) if progress_cb else None)
    if progress_cb:
        progress_cb("Validating Kokoro-82M CPU inference...", 96)
    _get_model()
    if progress_cb:
        progress_cb("Kokoro-82M installed and verified!", 100)
    return check_health()


def synthesize_sync(text: str, voice_id: str = "af_heart", speed: float = 1.0) -> bytes:
    """Synthesize speech locally on CPU and return WAV bytes."""
    model = _get_model()
    voice = voice_id if voice_id in _VOICE_MAP else "af_heart"
    lang = "en-gb" if voice.startswith(("bf_", "bm_")) else "en-us"
    safe_speed = max(0.65, min(1.50, float(speed or 1.0)))
    samples, sample_rate = model.create(text, voice=voice, speed=safe_speed, lang=lang)
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


async def synthesize(text: str, voice_id: str = "af_heart", speed: float = 1.0) -> bytes:
    return await asyncio.to_thread(synthesize_sync, text, voice_id, speed)
