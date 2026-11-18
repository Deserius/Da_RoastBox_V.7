# Da RoastBox Dual-Provider TTS Architecture (`docs/TTS_SYSTEM.md`)

## Architecture Overview
Da RoastBox uses a unified `TTSManager` (`backend/services/tts/manager.py`) that supports both **Free Local Neural TTS** (default) and **ElevenLabs Premium TTS** (preserved intact), plus online and browser fallbacks:

1. **Kokoro-82M (`kokoro-onnx` + `onnxruntime` CPU)** — Primary free local neural engine (~337 MB weights stored in `backend/models/tts/kokoro/`). No API key, no GPU, runs on Windows 10 i5/i7 CPU with 8 GB RAM via lazy singleton loading.
2. **Piper TTS (`piper-tts`)** — Lightweight optional local CPU fallback (`backend/models/tts/piper/`).
3. **ElevenLabs (`elevenlabs_service.py`)** — Fully preserved premium voice system (`eleven_v3`, `eleven_multilingual_v2`, `eleven_turbo_v2_5`). Uses existing voice IDs and `ELEVENLABS_API_KEY` (hosted or per-user BYOK). Only called when selected or unlocked with valid credentials.
4. **OpenAI Expressive TTS (`openai_service.py`)** — Preserved fallback when OpenAI credentials are configured.
5. **Edge-TTS (`edge-tts`)** — Optional free online neural fallback (requires outbound internet).
6. **Browser Web Speech API (`frontend/src/lib/sandboxSpeech.js`)** — Client-side fallback when offline/network-sandboxed without downloaded ONNX weights.

### Qwen3-TTS Hardware Evaluation
Qwen3-TTS requires ~3–6+ GB VRAM / large PyTorch checkpoints to deliver acceptable latency and is **not** viable as a mandatory engine on 8 GB RAM CPU-only Windows 10 laptops. It is intentionally omitted from the required runtime so Da RoastBox stays fast and lightweight on consumer CPUs.

## Naturalness Pipeline (`backend/services/tts/naturalness.py`)
Every generated clip goes through a bounded FFmpeg (`imageio_ffmpeg`) optimization chain:
- Punctuation-aware segmentation (`optimize_text_for_tts`) without altering dialogue words.
- Gentle silence trimming (`silenceremove`) avoiding clipped word edges.
- Pitch shaping strictly clamped to `[0.85, 1.15]` with duration compensation (`asetrate` + `atempo`).
- RMS loudness normalization (`-16.0 dBFS`), soft compression, peak limiting (`alimiter`), 10 ms anti-click fade-in, and optional subtle comedy-room ambience.

## Licensing & Commercial Deployment
- **Kokoro-82M & `kokoro-onnx`:** Apache-2.0 — commercial use permitted with attribution.
- **Piper TTS (`piper-tts`) & official Rhasspy EN voices:** MIT / Apache-2.0 (verify individual community voice cards before bundling third-party weights).
- **FFmpeg (`imageio_ffmpeg`):** LGPL/GPL depending on build; invoked as an external subprocess.
- **ElevenLabs / OpenAI / Edge-TTS:** Governed by each provider's commercial API / Terms of Service.
