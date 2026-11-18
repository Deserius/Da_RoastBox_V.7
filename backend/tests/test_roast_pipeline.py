"""Unit tests for the roast pipeline, multimodal routing, photo analyzer, and sandbox preview freshness."""
import asyncio
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_jpeg(rgb=(30, 30, 35), size=(300, 480), noisy_border=False) -> bytes:
    arr = np.full((size[1], size[0], 3), rgb, dtype=np.uint8)
    if noisy_border:
        rng = np.random.default_rng(42)
        b_h = max(1, size[1] // 5)
        b_w = max(1, size[0] // 5)
        arr[:b_h, :, :] = rng.integers(0, 95, size=(b_h, size[0], 3), dtype=np.uint8)
        arr[-b_h:, :, :] = rng.integers(0, 95, size=(b_h, size[0], 3), dtype=np.uint8)
        arr[:, :b_w, :] = rng.integers(0, 95, size=(size[1], b_w, 3), dtype=np.uint8)
        arr[:, -b_w:, :] = rng.integers(0, 95, size=(size[1], b_w, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_local_photo_analyzer_detects_real_visual_attributes():
    from services.sandbox_preview import analyze_images_locally

    dark_tall = _make_jpeg(rgb=(18, 18, 22), size=(300, 540), noisy_border=True)
    bright_wide = _make_jpeg(rgb=(242, 240, 235), size=(640, 360), noisy_border=False)

    traits = analyze_images_locally([dark_tall, bright_wide])
    assert len(traits) == 2
    assert traits[0]["lighting"] == "dim_moody"
    assert traits[0]["aspect"] == "tall_screenshot"
    assert traits[0]["clutter"] == "cluttered_background"
    assert traits[1]["lighting"] == "blown_out_flash"
    assert traits[1]["aspect"] == "wide_landscape"


def test_sandbox_preview_never_repeats_same_five_jokes_and_uses_photo_and_context():
    from services.sandbox_preview import build_sandbox_preview_beats

    personas = json.loads((BACKEND_DIR / "data/personas.json").read_text(encoding="utf-8"))[:3]
    dark_img = _make_jpeg(rgb=(18, 20, 25), size=(360, 620), noisy_border=True)
    neon_img = _make_jpeg(rgb=(250, 40, 210), size=(640, 400), noisy_border=False)

    show1 = build_sandbox_preview_beats(
        personas,
        subject_name="Alex",
        user_context="claims to run three startups and sleeps in sunglasses",
        expected_beats=10,
        images=[dark_img, neon_img],
        adult=True,
        heat="fire",
        comedy_styles=["sarcastic"],
    )
    show2 = build_sandbox_preview_beats(
        personas,
        subject_name="Alex",
        user_context="claims to run three startups and sleeps in sunglasses",
        expected_beats=10,
        images=[dark_img, neon_img],
        adult=True,
        heat="fire",
        comedy_styles=["sarcastic"],
    )
    texts1 = [b["text"] for b in show1]
    texts2 = [b["text"] for b in show2]
    assert len(texts1) == 10 and len(texts2) == 10
    assert len(set(texts1)) == 10
    assert len(set(texts2)) == 10
    # Two back-to-back generations on identical inputs should produce fresh jokes
    assert texts1 != texts2
    assert any("startups" in t or "sunglasses" in t for t in texts1)


def test_multimodal_openrouter_profile_sends_images_directly():
    from services import roast_writer

    personas = json.loads((BACKEND_DIR / "data/personas.json").read_text(encoding="utf-8"))[:2]
    img = _make_jpeg(rgb=(120, 140, 180), size=(320, 320))
    captured_models = []
    captured_contents = []

    class _FakeCompletions:
        def create(self, **kwargs):
            captured_models.append(kwargs["model"])
            captured_contents.append(kwargs["messages"][1]["content"])
            script = [
                {
                    "persona_id": personas[i % 2]["id"],
                    "type": "intro" if i == 0 else "joke",
                    "text": f"Original multimodal roast line number {i} inspecting the blue shirt.",
                    "emotion": "cocky",
                    "delivery": "punchy",
                    "laugh_after": "big",
                    "reaction": "laugh",
                    "pause_before_ms": 150,
                    "pause_after_ms": 250,
                    "image_index": 0,
                    "standalone": True,
                }
                for i in range(10)
            ]
            payload = json.dumps({
                "lineup_roasts": {p["id"]: f"{p['displayName']} wears confidence like a borrowed tuxedo." for p in personas},
                "script": script,
            })
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=payload))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    async def _run():
        with patch.object(roast_writer, "ROAST_WRITER_PROVIDER", "openrouter"), \
             patch.object(roast_writer, "ROAST_WRITER_PROFILE", "multimodal"), \
             patch.object(roast_writer, "ROAST_FREE_WRITER_ONLY", False), \
             patch.object(roast_writer, "ROAST_OPENROUTER_MODELS", ("anthropic/claude-sonnet-4.5", "openai/gpt-4.1")), \
             patch.object(roast_writer, "ROAST_STREAM_TTS", False), \
             patch.object(roast_writer, "_creative_client", return_value=fake_client):
            return await roast_writer.write_script(
                "MODE: ROAST SHOW", personas, [img], ["image/jpeg"],
                byok_openrouter="or-offline-test-key", expected_beats=10,
            )

    beats = asyncio.run(_run())
    assert len(beats) == 10
    assert captured_models == ["anthropic/claude-sonnet-4.5"]
    assert any(part.get("type") == "image_url" for part in captured_contents[0])


def test_analyze_images_falls_back_to_openrouter_vision_when_openai_unavailable():
    from services import roast_writer

    img = _make_jpeg(rgb=(200, 80, 70), size=(320, 320))
    calls = []

    class _FailOpenAI:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(("openai", kwargs["model"]))
                    raise RuntimeError("401 invalid OpenAI key")

    class _OkOpenRouter:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(("openrouter", kwargs["model"]))
                    return SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps({"photos": [{"image_index": 0, "details": ["bright red hoodie", "sideways smirk"]}]}))
                    )])

    async def _run():
        with patch.object(roast_writer, "ROAST_FREE_WRITER_ONLY", False):
            return await roast_writer._analyze_images(
                _FailOpenAI(), [img], ["image/jpeg"], None, openrouter_client=_OkOpenRouter()
            )

    obs = asyncio.run(_run())
    assert obs == [{"image_index": 0, "details": ["bright red hoodie", "sideways smirk"]}]
    assert ("openrouter", "openai/gpt-4o") in calls
