# TTS Troubleshooting (`docs/TTS_TROUBLESHOOTING.md`)

| Symptom | Cause | Fix |
|---|---|---|
| Health shows `missing_model_files` for Kokoro | First-run ONNX/voice weights (~337 MB) haven't been downloaded yet | Click **Install Kokoro-82M** in Voice Studio or run `python scripts/install_tts.py --engine kokoro` |
| Model download fails in a restricted/sandboxed container | Outbound S3/HuggingFace asset hosts blocked by container firewall | Run `install_tts.py` on your local machine/server with internet, or use Browser Web Speech fallback in preview |
| ElevenLabs returns `402` or key error | Missing or invalid `ELEVENLABS_API_KEY` | Enter and verify your key in **Settings → Verify & Activate Keys**, or switch provider to **Free Local AI** |
| Voices sound quiet or clipped | Source engine output variance | Ensure FFmpeg (`imageio_ffmpeg`) is installed so `naturalness.py` normalizes to `-16 dBFS` with 10 ms fade-in |
| Preview browser plays no sound until click | Browser autoplay policy after async API fetch | Click **Tap to play sound** or any Play button in the transcript |
