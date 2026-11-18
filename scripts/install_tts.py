#!/usr/bin/env python3
"""First-run TTS dependency & local neural model installer for Da RoastBox."""
import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def check_environment() -> None:
    print(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required for Da RoastBox TTS engines.")


def ensure_packages() -> None:
    req = ROOT / "backend" / "requirements-tts.txt"
    print(f"Installing/verifying TTS Python packages from {req}...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Da RoastBox Free Local TTS models")
    parser.add_argument("--engine", choices=("kokoro", "piper", "both"), default="kokoro")
    parser.add_argument("--piper-voice", default="en_US-lessac-medium")
    parser.add_argument("--skip-pip", action="store_true")
    args = parser.parse_args()

    check_environment()
    if not args.skip_pip:
        ensure_packages()

    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "roastbox")
    os.environ.setdefault("JWT_SECRET", "installer-temp-secret")

    from services.tts import kokoro_provider, piper_provider
    from services.tts.naturalness import process_voice_audio

    if args.engine in ("kokoro", "both"):
        health = kokoro_provider.install_models_sync(lambda msg, pct: print(f"[{pct:3d}%] {msg}"))
        print("Kokoro health:", health)
        wav = kokoro_provider.synthesize_sync("Da RoastBox local neural voice test passed.", voice_id="am_adam", speed=1.0)
        mp3, steps = process_voice_audio(wav, input_format="wav", output_format="mp3")
        print(f"Kokoro test synthesis: {len(wav)} WAV bytes -> {len(mp3)} MP3 bytes ({steps})")

    if args.engine in ("piper", "both"):
        p_health = piper_provider.install_voice_sync(args.piper_voice)
        print("Piper health:", p_health)
        wav = piper_provider.synthesize_sync("Piper local fallback voice test passed.", voice_id=args.piper_voice)
        mp3, steps = process_voice_audio(wav, input_format="wav", output_format="mp3")
        print(f"Piper test synthesis: {len(wav)} WAV bytes -> {len(mp3)} MP3 bytes ({steps})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
