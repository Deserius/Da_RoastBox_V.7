# TTS Installation Guide (`docs/TTS_INSTALLATION.md`)

## Quick Install (Windows 10 / macOS / Linux)
1. Activate the project virtualenv (`.venv`).
2. Install pinned TTS packages and download Kokoro-82M CPU weights (~337 MB):
   ```bash
   python scripts/install_tts.py --engine kokoro
   ```
3. Optional: also install a lightweight Piper fallback voice (`en_US-lessac-medium`, MIT):
   ```bash
   python scripts/install_tts.py --engine both --piper-voice en_US-lessac-medium
   ```
4. Or install directly inside the running web app from **🎙️ Voice Studio → Install Kokoro-82M**.

## Hardware Target
- **CPU:** Intel i5/i7 or equivalent x86_64/ARM64 CPU (no CUDA GPU required).
- **RAM:** 8 GB RAM supported (models load lazily on first synthesis and can be unloaded cleanly).
- **Disk:** ~400 MB for Kokoro-82M (`backend/models/tts/kokoro/`); ~65 MB per Piper voice (`backend/models/tts/piper/`).

## Preserving Existing Keys & `.env`
`scripts/install_tts.py` never modifies `.env` or deletes existing `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` credentials.
