# Da RoastBox Voice Studio Guide (`docs/VOICE_STUDIO.md`)

Open **🎙️ Voice Studio** (`/voice-studio`) from the top navigation bar or mobile backstage menu.

## Capabilities
- **Provider Health & One-Click Model Install:** View live status (`operational`, `available`, `missing_model_files`, `missing_api_key`) for Kokoro-82M, Piper, ElevenLabs, Edge-TTS, and Browser Speech. Install Kokoro-82M or Piper models once with progress tracking and retry support.
- **Browse & Filter All 40 Characters:** Search by name or personality and filter by Tier (`Free` / `Premium`), Gender (`Male` / `Female` / `Other`), Accent (`American` / `British`), Age (`Younger` / `Adult` / `Mature` / `Older`), Depth (`Very Deep` / `Deep` / `Medium` / `Bright`), Speed (`Fast` / `Balanced` / `Slow`), and Style (`Comedic` / `Dramatic`).
- **Voice Tuning & Delivery Profiles:** Adjust Speed (`0.80x–1.30x`), Pitch (`0.85x–1.15x`), any of 13 Delivery Styles (`casual`, `high_energy_comedy`, `aggressive_roast`, `sarcastic`, `deadpan`, `dramatic`, `excited`, `calm`, `whispering`, `shouting`, `slow_deliberate`, `fast_energetic`, `emotional`), and optional Comedy Club Room Ambience.
- **Compare Two Voices:** Audition Candidate A vs. Candidate B using identical sample text before saving.
- **Persistent Voice Assignments:** Saving updates the character's MongoDB `persona_voice_profiles` override, which persists across roasts, battles, voice previews, and reloads. Click **Restore Default** anytime to reset.
