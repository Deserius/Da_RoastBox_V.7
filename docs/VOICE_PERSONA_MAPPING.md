# 40-Persona Voice Mapping (`docs/VOICE_PERSONA_MAPPING.md`)

All 40 existing characters in `backend/data/personas.json` (`persona_1`–`persona_25` free, `persona_p1`–`persona_p15` premium) receive dedicated voice profiles stored in `backend/data/voice_profiles.json` and `backend/services/tts/voice_profiles.py`.

## Native Identities vs. Customized Profiles
- **Kokoro-82M v1.0 provides 27 distinct native speakers** (`af_*`, `am_*`, `bf_*`, `bm_*`).
- **25 characters** receive unique 1-to-1 primary Kokoro speaker identities (`native_voice_identity: true`).
- **15 characters** share a base Kokoro speaker paired with distinct Piper fallback voices, bounded pitch (`0.89x–1.07x`), speaking rate (`0.88x–1.18x`), and delivery style tuning (`native_voice_identity: false`, `is_customized_profile: true`).
- Every persona retains its original **ElevenLabs `voice_id`** and **OpenAI `tts_voice_hd`** untouched for premium/BYOK playback.

## How to Add or Change a Voice
1. **In UI:** Open **🎙️ Voice Studio** (`/voice-studio`), pick a persona, choose a provider/voice/speed/pitch/delivery style, test with **Listen**, and click **Save Voice Assignment**.
2. **Via API:** `PUT /api/tts/profiles/{persona_id}` (and `POST /api/tts/profiles/{persona_id}/reset` to restore defaults).
3. **In Code:** Register additional base voices in `backend/services/tts/kokoro_provider.py` or `piper_provider.py`, then map them in `backend/services/tts/voice_profiles.py` and regenerate `backend/data/voice_profiles.json`.
