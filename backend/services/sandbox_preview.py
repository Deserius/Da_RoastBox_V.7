"""Offline preview fallback for network-sandboxed environments (e.g. Arena.ai workspace preview).

Only active when PREVIEW_SANDBOX_FALLBACK=true (never in production deployments)
and ONLY triggered when outbound AI/TTS API connections are blocked by the network
sandbox (APIConnectionError / ConnectError / TimeoutError / OSError).
"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from typing import Dict, List, Optional

import imageio_ffmpeg
import numpy as np

log = logging.getLogger(__name__)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_CONNECTION_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "TimeoutError",
    "SSLError",
    "ConnectionError",
    "gaierror",
}


class SandboxNetworkUnavailable(RuntimeError):
    """Raised internally when outbound AI network access is blocked in sandbox preview mode."""


def is_network_connection_error(exc: BaseException) -> bool:
    """Return True when exc (or its cause chain) is a network/TLS connection failure."""
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        if name in _CONNECTION_ERROR_NAMES or isinstance(cur, (OSError, TimeoutError, SandboxNetworkUnavailable)):
            return True
        msg = str(cur).lower()
        if any(marker in msg for marker in (
            "connection error",
            "connection refused",
            "network is unreachable",
            "name or service not known",
            "nodename nor servname",
            "timed out",
            "eof occurred in violation of protocol",
            "ssl",
            "tls",
            "failed to establish a new connection",
        )):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _clean_text(text: str, off_limits: Optional[str], adult: bool) -> str:
    out = re.sub(r"\s+", " ", (text or "").strip())
    if not adult:
        for bad, repl in (
            (r"\bfuck\w*\b", "freaking"),
            (r"\bshit\w*\b", "stuff"),
            (r"\bbitch\w*\b", "clown"),
            (r"\basshole\b", "joker"),
            (r"\bdamn\b", "darn"),
            (r"\bhell\b", "heck"),
        ):
            out = re.sub(bad, repl, out, flags=re.IGNORECASE)
    terms = [t.strip() for t in re.split(r"[,;\n]+", off_limits or "") if len(t.strip()) >= 3]
    for term in terms:
        out = re.sub(re.escape(term), "that", out, flags=re.IGNORECASE)
    return out


def _context_hook(user_context: Optional[str], off_limits: Optional[str], adult: bool) -> str:
    cleaned = _clean_text(user_context or "", off_limits, adult)
    if not cleaned:
        return ""
    snippet = cleaned.split(".")[0].strip()
    if len(snippet) > 90:
        snippet = snippet[:87].rsplit(" ", 1)[0] + "..."
    return snippet


def build_sandbox_preview_beats(
    personas: List[Dict],
    *,
    subject_name: Optional[str] = None,
    user_context: Optional[str] = None,
    expected_beats: Optional[int] = None,
    n_images: int = 1,
    adult: bool = True,
    off_limits: Optional[str] = None,
    is_battle: bool = False,
    is_rap: bool = False,
    comedy_styles: Optional[List[str]] = None,
    heat: str = "medium",
    roast_tier: str = "standard",
    premium_voice: bool = False,
) -> List[Dict]:
    """Build a complete, persona-voiced script for sandbox preview mode."""
    if not personas:
        return []
    guest = _clean_text(subject_name or "", off_limits, adult) or "tonight's guest"
    hook = _context_hook(user_context, off_limits, adult)
    n_imgs = max(1, int(n_images or 1))
    count = max(6, int(expected_beats or (8 if is_battle else 10)))

    if is_battle and len(personas) >= 2:
        a, b = personas[0], personas[1]
        a_name = a.get("displayName") or a.get("name") or a["id"]
        b_name = b.get("displayName") or b.get("name") or b["id"]
        beats: List[Dict] = []
        rap_bars_a = [
            f"{b_name} stepped in the booth looking like a clearance-rack sequel, talkin' big game with a mic check that's barely legal.",
            f"You call that a look? Even {guest} wouldn't borrow your fit on laundry day — step back before the crowd votes me the MVP.",
            f"Look at {b_name} sweating under the stage lights, dropping recycled one-liners from two thousand and hype-less nights.",
            f"Round over, pack your bag and your weak punchlines — I'm taking the belt while {b_name} takes the exit sign.",
        ]
        rap_bars_b = [
            f"Cute rhyme, {a_name}, did you write it on a napkin? Because your whole delivery sounds like a GPS buffering.",
            f"At least {guest} showed up with real energy tonight — you're out here swinging wild and missing every single highlight.",
            f"Talk all you want, {a_name}, your best bar was the door behind you — the scoreboard already knows who ran right through you.",
            f"Drop the mic and bow out before the buzzer rings, {a_name} — the crowd didn't come for cover bands, they came for the ring.",
        ]
        roast_lines_a = [
            f"Honestly {b_name}, seeing you across the stage makes {guest}'s photo look like a Vogue cover by comparison.",
            f"{b_name}'s whole comedy style is just yelling louder whenever the room goes quiet — and look how quiet it gets.",
            f"Don't worry {b_name}, if this roast career stalls out, there's always narrating warning labels.",
            f"Even {guest} is nodding right now because we both know {b_name} brought butter-knife energy to a flamethrower fight.",
        ]
        roast_lines_b = [
            f"Bold words from {a_name}, whose hairline is retreating faster than the crowd's patience tonight.",
            f"I love how confident {a_name} is — truly inspiring what zero self-awareness can achieve on a microphone.",
            f"{a_name} came ready to roast {guest}, then forgot the punchlines and started improvising apologies.",
            f"Wrap it up, {a_name} — the only thing getting cooked in your set is your own clock.",
        ]
        bank_a = rap_bars_a if is_rap else roast_lines_a
        bank_b = rap_bars_b if is_rap else roast_lines_b
        emotions = ["cocky", "sarcastic", "hype", "smug", "outraged", "incredulous"]
        reactions = ["laugh", "ooh", "cheer"]
        laughs = ["medium", "big", "explosive"]
        for i in range(count):
            fighter = a if i % 2 == 0 else b
            line_bank = bank_a if i % 2 == 0 else bank_b
            txt = line_bank[(i // 2) % len(line_bank)]
            if i == 1 and hook:
                txt = f"{txt} And about {hook} — we haven't forgotten that either."
            beats.append({
                "persona_id": fighter["id"],
                "type": "intro" if i == 0 else ("closer" if i == count - 1 else "punchline"),
                "text": _clean_text(txt, off_limits, adult),
                "emotion": emotions[i % len(emotions)],
                "delivery": "rapid battle bar on beat" if is_rap else "sharp ring comeback",
                "laugh_after": laughs[i % len(laughs)],
                "reaction": reactions[i % len(reactions)],
                "pause_before_ms": 180,
                "pause_after_ms": 260,
                "image_index": i % n_imgs,
                "rap_delivery": bool(is_rap),
                "_standalone": True,
                "_sandbox_preview": True,
            })
        return beats

    emotions = ["cocky", "sarcastic", "deadpan", "smug", "incredulous", "outraged", "hype"]
    laughs = ["small", "medium", "big", "explosive"]
    reactions = ["laugh", "ooh", "cheer"]
    style_hint = f" ({', '.join(comedy_styles[:2])})" if comedy_styles else ""
    is_premium = roast_tier == "premium"

    beats = []
    for i in range(count):
        p = personas[i % len(personas)]
        pname = p.get("displayName") or p.get("name") or p["id"]
        punchlines = [ln for ln in (p.get("punchlines") or []) if isinstance(ln, str) and ln.strip()]
        topics = [t for t in (p.get("topics") or []) if isinstance(t, str) and t.strip()]
        topic = topics[i % len(topics)] if topics else "the whole vibe"
        lingo = [w for w in (p.get("lingo") or []) if isinstance(w, str) and w.strip()]
        slang = lingo[i % len(lingo)] if lingo else "listen"
        img_idx = i % n_imgs

        if i == 0:
            raw = (
                f"Hold the applause — {guest} just walked onto the big screen with full VIP audacity and zero backup plan, looking like somebody clicked 'surprise me' on a character creator."
                if is_premium else
                f"Look at {guest} up on the big screen — I've seen better lighting in a DMV waiting room, and the expression says 'I definitely didn't read the terms of service.'"
            )
        elif i == 1 and hook:
            raw = (
                f"Wait a second, {guest}: '{hook}'? {slang} — you handed {pname} that entire storyline on a silver platter and expected a gentle toast? That's not a backstory, that's Exhibit A."
                if is_premium else
                f"Hold up, {guest}: {hook}? You really handed us that backstory and expected mercy from {pname}? That's like bringing gasoline to a barbecue."
            )
        elif i == 2 and punchlines:
            raw = (
                f"Real talk, {guest} — {punchlines[0]} Even in photo {img_idx + 1}, that pose screams 'I rehearsed this in the bathroom mirror and still lost the argument.'"
                if is_premium else
                f"For real though, {guest} — {punchlines[0]} And looking at photo {img_idx + 1}, you posed like somebody just yelled 'act natural' for the first time in your life."
            )
        elif i % 4 == 3:
            raw = (
                f"Zoom all the way in on frame {img_idx + 1}: {guest} has the exact posture of someone who says 'no worries!' in an email while plotting revenge{style_hint}."
                if is_premium else
                f"Can we zoom in on {guest}'s posture in shot {img_idx + 1}? That's pure 'I spent forty minutes picking an outfit just to pretend I threw it on'{style_hint}."
            )
        elif len(punchlines) > 1 and i % 3 == 1:
            raw = (
                f"{guest}, {punchlines[1]} Every time {topic} comes up around you, the group chat mutes itself for twenty minutes out of pure self-defense."
                if is_premium else
                f"{guest}, {punchlines[1]} Every time you bring up {topic}, the whole room checks their watch to see if it's a TED Talk or a cry for help."
            )
        elif i == count - 1:
            raw = (
                f"Give it up for {guest} — took {heat} heat from {pname} and the whole panel without blinking, even if that camera roll just filed for witness protection!"
                if is_premium else
                f"Alright {guest}, all love at the end of the night — you took the heat like a champ, even if that camera roll is never recovering from tonight!"
            )
        else:
            raw = (
                f"Honestly {guest}, in shot {img_idx + 1} with that smirk — {slang}, you look like the reigning undefeated champion of ignoring good advice about {topic}."
                if is_premium else
                f"Honestly {guest}, looking at frame {img_idx + 1} with that confident smirk — you look like the final boss of ignoring good advice about {topic}."
            )

        beats.append({
            "persona_id": p["id"],
            "type": "joke" if i < count - 1 else "closer",
            "text": _clean_text(raw, off_limits, adult),
            "emotion": emotions[i % len(emotions)],
            "delivery": f"{heat} {'premium showcase' if is_premium else 'roast'} delivery, land the punchline cleanly",
            "laugh_after": "explosive" if i == count - 1 else (laughs[(i + 1) % len(laughs)] if is_premium else laughs[i % len(laughs)]),
            "reaction": "cheer" if i == count - 1 else reactions[i % len(reactions)],
            "pause_before_ms": 200 if is_premium else 220,
            "pause_after_ms": 260 if is_premium else 280,
            "image_index": img_idx,
            "premium_voice": bool(premium_voice),
            "roast_tier": roast_tier,
            "_standalone": True,
            "_sandbox_preview": True,
        })
    return beats


def synthesize_sandbox_audio(text: str, persona_id: str, persona_meta: Optional[dict] = None) -> bytes:
    """Synthesize a clean, non-silent spoken-cadence MP3 locally using numpy + bundled FFmpeg."""
    words = max(3, len((text or "").split()))
    duration_s = max(1.3, min(3.8, words * 0.21))
    sr = 22050
    n_samples = int(sr * duration_s)
    t = np.linspace(0.0, duration_s, n_samples, endpoint=False, dtype=np.float32)

    digest = hashlib.sha256((persona_id or "host").encode("utf-8")).digest()
    gender = ((persona_meta or {}).get("gender") or "").lower()
    base_f = 195.0 if gender == "female" else 128.0
    base_f += (digest[0] % 48) - 16.0

    # Natural speech-like cadence: syllable envelope + mild intonation contour.
    syllable_hz = 3.6 + (digest[1] % 5) * 0.35
    cadence = 0.5 + 0.5 * np.sin(2.0 * np.pi * syllable_hz * t + (digest[2] % 7))
    envelope = np.clip(cadence, 0.12, 1.0)
    # Soft fade-in / fade-out so beat transitions never click.
    fade = min(int(sr * 0.06), n_samples // 6)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        envelope[:fade] *= ramp
        envelope[-fade:] *= ramp[::-1]

    pitch = base_f * (1.0 + 0.06 * np.sin(2.0 * np.pi * 1.1 * t) - 0.04 * (t / duration_s))
    phase = np.cumsum(2.0 * np.pi * pitch / sr, dtype=np.float64).astype(np.float32)
    signal = (
        0.55 * np.sin(phase)
        + 0.25 * np.sin(2.0 * phase)
        + 0.12 * np.sin(3.0 * phase)
    ) * envelope * 0.03

    pcm = np.clip(signal, -0.95, 0.95).astype("<f4").tobytes()
    proc = subprocess.run(
        [
            FFMPEG, "-v", "error",
            "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
            "-c:a", "libmp3lame", "-b:a", "96k", "-ar", "44100", "-ac", "1", "-f", "mp3", "pipe:1",
        ],
        input=pcm,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"Sandbox preview FFmpeg synth failed: {proc.stderr.decode(errors='ignore')[:200]}")
    return proc.stdout
