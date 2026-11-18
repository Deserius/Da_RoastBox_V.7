"""Voice naturalness & audio-quality optimization pipeline.

Clearly separates text segmentation / pacing hints from FFmpeg post-processing
effects (silence trimming, bounded pitch adjustment, RMS loudness leveling,
headroom limiting, smooth fades, and optional subtle room ambience).
"""
from __future__ import annotations

import logging
import math
import re
import subprocess
from typing import List, Tuple

import imageio_ffmpeg
import numpy as np

from .base import DELIVERY_PROFILES

log = logging.getLogger(__name__)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
TARGET_RMS_DBFS = -16.0
SAMPLE_RATE = 44100


def optimize_text_for_tts(text: str, delivery_style: str = "casual") -> str:
    """Improve punctuation and clause phrasing without changing dialogue meaning."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    # Normalize spaced dashes into clean pauses so neural engines breathe naturally.
    cleaned = re.sub(r"\s+--\s+|\s+—\s+", " — ", cleaned)
    profile = DELIVERY_PROFILES.get(delivery_style, DELIVERY_PROFILES["casual"])
    if profile["pause_scale"] >= 1.15:
        cleaned = re.sub(r";\s+", "... ", cleaned)
    if cleaned[-1] not in ".!?\"'":
        cleaned += "."
    return cleaned


def _measure_speech_rms(raw_pcm_bytes: bytes) -> float | None:
    samples = np.frombuffer(raw_pcm_bytes, dtype="<f4")
    if not samples.size or not np.isfinite(samples).all():
        return None
    frame_size = 1600
    count = len(samples) // frame_size
    if count:
        frames = samples[:count * frame_size].reshape(count, frame_size).astype(np.float64)
        levels = np.sqrt(np.mean(frames * frames, axis=1))
    else:
        levels = np.array([np.sqrt(np.mean(samples.astype(np.float64) ** 2))])
    active = levels[levels >= 10 ** (-48 / 20)]
    if not active.size:
        return None
    return float(np.percentile(active, 60))


def _probe_pcm(audio_bytes: bytes, input_format: str) -> bytes:
    cmd = [FFMPEG, "-v", "error"]
    if input_format:
        cmd.extend(["-f", input_format])
    cmd.extend(["-i", "pipe:0", "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"])
    res = subprocess.run(cmd, input=audio_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if res.returncode != 0:
        return b""
    return res.stdout


def process_voice_audio(
    audio_bytes: bytes,
    *,
    input_format: str = "wav",
    output_format: str = "mp3",
    pitch_factor: float = 1.0,
    rate_factor: float = 1.0,
    delivery_style: str = "casual",
    trim_silence: bool = True,
    room_ambience: bool = False,
    normalize: bool = True,
) -> Tuple[bytes, List[str]]:
    """Run bounded FFmpeg naturalness processing; returns (bytes, applied_steps)."""
    if not audio_bytes:
        return audio_bytes, []

    profile = DELIVERY_PROFILES.get(delivery_style, DELIVERY_PROFILES["casual"])
    # Bound pitch strictly to [0.85, 1.15] so voices stay human and natural.
    safe_pitch = max(0.85, min(1.15, float(pitch_factor or 1.0)))
    safe_rate = max(0.80, min(1.30, float(rate_factor or 1.0)))
    filters: List[str] = []
    applied: List[str] = []

    if trim_silence:
        filters.append("silenceremove=start_periods=1:start_duration=0.02:start_threshold=-46dB:stop_periods=-1:stop_duration=0.18:stop_threshold=-46dB")
        applied.append("silence_trim")

    # Apply bounded pitch shift without altering playback duration.
    if abs(safe_pitch - 1.0) >= 0.015:
        target_sr = int(round(SAMPLE_RATE * safe_pitch))
        inv_tempo = max(0.75, min(1.35, 1.0 / safe_pitch))
        filters.append(f"aresample={SAMPLE_RATE},asetrate={target_sr},aresample={SAMPLE_RATE},atempo={inv_tempo:.4f}")
        applied.append(f"pitch_{safe_pitch:.2f}x")

    # Optional additional tempo adjustment when engine couldn't apply rate directly.
    if abs(safe_rate - 1.0) >= 0.02:
        filters.append(f"atempo={safe_rate:.4f}")
        applied.append(f"tempo_{safe_rate:.2f}x")

    if normalize:
        pcm = _probe_pcm(audio_bytes, input_format)
        level = _measure_speech_rms(pcm) if pcm else None
        if level and math.isfinite(level) and level > 0:
            gain_db = max(-16.0, min(16.0, TARGET_RMS_DBFS - 20 * math.log10(level)))
            filters.append(f"volume={gain_db:.3f}dB")
            applied.append("rms_normalize")

    filters.append("acompressor=threshold=0.28:ratio=2.0:attack=10:release=110")
    filters.append("alimiter=limit=0.92:level=0:latency=1")
    applied.append("dynamics_level")

    if room_ambience or profile.get("room_ambience"):
        filters.append("aecho=0.8:0.86:16:0.09")
        applied.append("subtle_room_ambience")

    # Whisper/shout presence shaping (clearly labeled as audio-processing).
    if delivery_style == "whispering":
        filters.append("highpass=f=180,lowpass=f=5200,volume=-4dB")
        applied.append("whisper_presence_eq")
    elif delivery_style == "shouting":
        filters.append("equalizer=f=2400:t=q:w=1.2:g=2.5")
        applied.append("stage_presence_eq")

    # Smooth 10ms fade-in to eliminate clicks/clipped starts, plus short tail pad.
    filters.append("afade=t=in:st=0:d=0.010,apad=pad_dur=0.06")
    applied.append("anti_clip_fade")

    cmd = [FFMPEG, "-v", "error"]
    if input_format:
        cmd.extend(["-f", input_format])
    cmd.extend(["-i", "pipe:0", "-map_metadata", "-1", "-vn", "-af", ",".join(filters), "-ar", str(SAMPLE_RATE), "-ac", "1"])

    out_fmt = "wav" if output_format.lower() == "wav" else "mp3"
    if out_fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le", "-f", "wav", "pipe:1"])
    else:
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"])

    try:
        res = subprocess.run(cmd, input=audio_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        if res.returncode == 0 and res.stdout:
            return res.stdout, applied
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("FFmpeg naturalness pipeline failed (%s); returning unprocessed audio.", exc)
    return audio_bytes, []
