"""Comprehensive functional tests for Da RoastBox TTS Engine, 40 Voice Profiles,
Naturalness Pipeline, Provider Health, Caching, ElevenLabs Preservation, and
Persistent Workspace Keys in Preview Mode.
"""
import asyncio
import io
import os
import sys
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "roastbox_test_tts")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tts-tests-only")


def _sine_wav_bytes(freq: float = 220.0, dur_s: float = 0.35, sr: int = 24000) -> bytes:
    t = np.linspace(0, dur_s, int(sr * dur_s), endpoint=False)
    samples = (0.3 * np.sin(2.0 * np.pi * freq * t) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def test_all_40_persona_voice_profiles_intact():
    from services.tts.voice_profiles import list_default_profiles
    profiles = list_default_profiles()
    assert len(profiles) == 40
    ids = {p["persona_id"] for p in profiles}
    assert len(ids) == 40
    for p in profiles:
        assert p["voice_id"]
        assert p["piper_voice_id"]
        assert p["elevenlabs_voice_id"]
        assert 0.85 <= p["pitch_adjustment"] <= 1.15
        assert 0.80 <= p["speaking_rate"] <= 1.30
        assert p["sample_preview_text"]
    native_voices = {p["voice_id"] for p in profiles if p["native_voice_identity"]}
    assert len(native_voices) >= 25


def test_kokoro_and_piper_honest_health_when_models_missing(tmp_path, monkeypatch):
    from services.tts import kokoro_provider, piper_provider
    monkeypatch.setattr(kokoro_provider, "MODELS_DIR", tmp_path / "kokoro")
    monkeypatch.setattr(piper_provider, "MODELS_DIR", tmp_path / "piper")
    kh = kokoro_provider.check_health()
    ph = piper_provider.check_health()
    assert kh["installed"] is True
    assert kh["models_ready"] is False
    assert kh["operational"] is False
    assert kh["status"] == "missing_model_files"
    assert ph["installed"] is True
    assert ph["operational"] is False
    assert ph["status"] == "missing_model_files"


def test_naturalness_pipeline_pitch_speed_delivery_and_export():
    from services.tts.base import DELIVERY_PROFILES
    from services.tts.naturalness import optimize_text_for_tts, process_voice_audio

    assert len(DELIVERY_PROFILES) >= 13
    shaped = optimize_text_for_tts("Look at that haircut; zero mercy", "deadpan")
    assert shaped.endswith(".")
    wav = _sine_wav_bytes(220.0, 0.4)
    mp3_out, steps_mp3 = process_voice_audio(
        wav, input_format="wav", output_format="mp3",
        pitch_factor=1.08, rate_factor=1.05, delivery_style="high_energy_comedy", room_ambience=True,
    )
    assert len(mp3_out) > 200
    assert "rms_normalize" in steps_mp3
    assert "subtle_room_ambience" in steps_mp3

    wav_out, steps_wav = process_voice_audio(
        wav, input_format="wav", output_format="wav",
        pitch_factor=0.92, delivery_style="whispering",
    )
    assert wav_out[:4] == b"RIFF"
    assert "whisper_presence_eq" in steps_wav


def test_kokoro_piper_edge_elevenlabs_synthesis_and_cache(tmp_path, monkeypatch):
    import config
    from services import storage
    from services.tts import kokoro_provider, piper_provider, manager, voice_profiles

    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(storage, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(manager, "AUDIO_DIR", tmp_path)
    manager._CACHE.clear()

    fake_wav = _sine_wav_bytes(300.0, 0.3)

    async def _run():
        with patch.object(manager, "get_effective_profile", new=AsyncMock(side_effect=lambda pid: voice_profiles.get_default_profile(pid))):
            # 1. Free Kokoro local synthesis without any API key (mocked ONNX model weights)
            with patch.object(kokoro_provider, "is_package_installed", return_value=True), \
                 patch.object(kokoro_provider, "models_present", return_value=True), \
                 patch.object(kokoro_provider, "synthesize", new=AsyncMock(return_value=fake_wav)) as mock_k:
                url1, res1 = await manager.synthesize_and_cache(
                    text="Free local male voice check.", persona_id="persona_1",
                    voice_id="am_adam", speed=1.1, pitch=0.96, delivery_style="aggressive_roast",
                )
                assert res1.provider == "kokoro"
                assert url1.startswith("/api/audio/")
                assert mock_k.call_count == 1

                # Cache hit on identical settings
                url2, res2 = await manager.synthesize_and_cache(
                    text="Free local male voice check.", persona_id="persona_1",
                    voice_id="am_adam", speed=1.1, pitch=0.96, delivery_style="aggressive_roast",
                )
                assert url2 == url1
                assert res2.provider == "cache"
                assert mock_k.call_count == 1

                # Cache invalidates when voice/pitch changes
                url3, res3 = await manager.synthesize_and_cache(
                    text="Free local female voice check.", persona_id="persona_2",
                    voice_id="af_aoede", speed=0.9, pitch=1.06, delivery_style="sarcastic",
                )
                assert url3 != url1
                assert res3.provider == "kokoro"
                assert mock_k.call_count == 2

            # 2. Piper fallback when Kokoro is unavailable
            with patch.object(kokoro_provider, "models_present", return_value=False), \
                 patch.object(piper_provider, "is_package_installed", return_value=True), \
                 patch.object(piper_provider, "installed_voice_ids", return_value=["en_US-lessac-medium"]), \
                 patch.object(piper_provider, "synthesize", new=AsyncMock(return_value=fake_wav)):
                res_p = await manager.synthesize_speech(
                    text="Piper local fallback check.", persona_id="persona_1",
                )
                assert res_p.provider == "piper"

            # 3. ElevenLabs preservation when explicitly selected with API key
            with patch("services.tts.elevenlabs_provider.synthesize", new=AsyncMock(return_value=b"ID3fake-mp3-data" * 50)) as mock_el:
                el_dummy = "el-offline-not-a-real-key-012345"
                res_el = await manager.synthesize_speech(
                    text="Premium ElevenLabs voice preserved.", persona_id="persona_p1",
                    provider_preference="elevenlabs", user_elevenlabs_key=el_dummy,
                    allow_premium_elevenlabs=True,
                )
                assert res_el.provider == "elevenlabs"
                assert mock_el.call_count == 1

    asyncio.run(_run())


def test_profile_persistence_and_restore():
    from services.tts import voice_profiles
    store = {}

    class _FakeCol:
        async def find_one(self, q, _proj=None):
            return dict(store[q["persona_id"]]) if q["persona_id"] in store else None

        def find(self, *_a, **_kw):
            class _Cursor:
                async def to_list(self, length=100):
                    return [dict(v) for v in store.values()]
            return _Cursor()

        async def update_one(self, q, upd, upsert=False):
            store[q["persona_id"]] = dict(upd["$set"])

        async def delete_one(self, q):
            store.pop(q["persona_id"], None)

    with patch.object(voice_profiles, "COLLECTION", _FakeCol()):
        saved = asyncio.run(voice_profiles.save_profile_override("persona_1", {
            "voice_id": "bm_george",
            "speaking_rate": 0.92,
            "pitch_adjustment": 0.95,
            "speaking_style": "dramatic",
        }))
        assert saved["voice_id"] == "bm_george"
        assert saved["assignment_status"] == "customized"

        loaded = asyncio.run(voice_profiles.get_effective_profile("persona_1"))
        assert loaded["voice_id"] == "bm_george"

        restored = asyncio.run(voice_profiles.reset_profile_to_default("persona_1"))
        assert restored["voice_id"] == "am_adam"
        assert restored["assignment_status"] == "assigned_default"


def test_workspace_keys_persist_across_preview_sessions(tmp_path, monkeypatch):
    from services import workspace_keys
    monkeypatch.setattr(workspace_keys, "STORE_PATH", tmp_path / ".workspace_keys.json")
    monkeypatch.setenv("PREVIEW_SANDBOX_FALLBACK", "true")

    dummy_or = "sk-or-v1-" + "offline-not-a-real-key-12345"
    dummy_el = "el-" + "offline-not-a-real-key-12345"
    workspace_keys.save_workspace_keys({
        "openrouter_key": dummy_or,
        "elevenlabs_key": dummy_el,
    })
    assert workspace_keys.get_saved_key("openrouter_key") == dummy_or
    assert workspace_keys.get_saved_key("elevenlabs_key") == dummy_el
    masks = workspace_keys.get_saved_key_masks()
    assert "openrouter_key" in masks and "••••" in masks["openrouter_key"]

    workspace_keys.clear_workspace_byok_keys()
    assert workspace_keys.get_saved_key("openrouter_key") is None
