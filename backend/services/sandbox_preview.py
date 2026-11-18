"""Offline preview fallback for network-sandboxed environments (e.g. Arena.ai workspace preview).

Only active when PREVIEW_SANDBOX_FALLBACK=true (never in production deployments)
and ONLY triggered when outbound AI/TTS API connections are blocked by the network
sandbox (APIConnectionError / ConnectError / TimeoutError / OSError).

Includes a genuine local PIL/NumPy visual photo analyzer and a randomized,
non-repeating comedy generator so preview roasts inspect every uploaded photo,
honor persona personalities/topics/lingo, and never loop the same 5 templates.
"""
from __future__ import annotations

import hashlib
import io
import logging
import random
import re
import subprocess
from collections import deque
from typing import Dict, List, Optional, Tuple

import imageio_ffmpeg
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_RNG = random.SystemRandom()
# Track recently used template IDs across consecutive preview shows so repeating
# "Generate Roast" does not replay the same jokes back-to-back.
_RECENT_TEMPLATE_IDS: deque[str] = deque(maxlen=48)

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
            (r"\bshit\w*\b", "nonsense"),
            (r"\bbitch\w*\b", "clown"),
            (r"\basshole\b", "joker"),
            (r"\bdamn\b", "darn"),
            (r"\bhell\b", "heck"),
            (r"\bbullshit\b", "baloney"),
            (r"\bcrap\b", "junk"),
            (r"\bpiss\w*\b", "tick"),
        ):
            out = re.sub(bad, repl, out, flags=re.IGNORECASE)
    terms = [t.strip() for t in re.split(r"[,;\n]+", off_limits or "") if len(t.strip()) >= 3]
    for term in terms:
        phrase = re.escape(term).replace(r"\ ", r"\s+")
        out = re.sub(r"(?<!\w)" + phrase + r"(?!\w)", "that", out, flags=re.IGNORECASE)
    return out


def _extract_context_angles(user_context: Optional[str], off_limits: Optional[str], adult: bool) -> List[str]:
    """Break user_context into multiple usable story fragments instead of one truncated line."""
    cleaned = _clean_text(user_context or "", off_limits, adult)
    if not cleaned:
        return []
    raw_parts = [p.strip(" .,-;:") for p in re.split(r"[.!?\n;]+|\band\b|\bbut\b", cleaned) if p.strip()]
    angles: List[str] = []
    seen = set()
    for part in raw_parts:
        if len(part.split()) < 2:
            continue
        if len(part) > 78:
            part = part[:75].rsplit(" ", 1)[0] + "..."
        key = part.casefold()
        if key not in seen:
            seen.add(key)
            angles.append(part)
    if not angles and cleaned:
        angles.append(cleaned[:78])
    return angles[:6]


def analyze_images_locally(images: Optional[List[bytes]], off_limits: Optional[str] = None) -> List[Dict]:
    """Inspect uploaded image bytes with PIL + NumPy to extract concrete visual traits."""
    if not images:
        return []
    profiles: List[Dict] = []
    terms = [t.strip().casefold() for t in re.split(r"[,;\n]+", off_limits or "") if len(t.strip()) >= 3]
    for idx, raw in enumerate(images):
        trait = {
            "image_index": idx,
            "aspect": "square_crop",
            "lighting": "balanced_daylight",
            "palette": "earthy_neutral",
            "saturation": "natural_color",
            "clutter": "clean_backdrop",
            "framing": "center_subject",
            "brightness": 0.5,
            "details": [],
        }
        try:
            with Image.open(io.BytesIO(raw)) as im:
                w, h = im.size
                rgb = im.convert("RGB")
                small = rgb.resize((64, 64))
                arr = np.asarray(small, dtype=np.float32) / 255.0
                hsv_img = small.convert("HSV")
                hsv = np.asarray(hsv_img, dtype=np.float32) / 255.0

                mean_rgb = arr.mean(axis=(0, 1))
                luma = float(0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2])
                luma_map = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
                contrast = float(luma_map.std())
                sat = float(hsv[:, :, 1].mean())

                # Aspect ratio / crop classification
                ratio = h / max(1, w)
                if ratio >= 1.65:
                    aspect = "tall_screenshot"
                elif ratio >= 1.15:
                    aspect = "vertical_selfie"
                elif ratio <= 0.80:
                    aspect = "wide_landscape"
                else:
                    aspect = "square_crop"

                # Lighting & exposure
                bright_pct = float((luma_map > 0.86).mean())
                dark_pct = float((luma_map < 0.16).mean())
                if luma < 0.27 or dark_pct > 0.55:
                    lighting = "dim_moody"
                elif luma > 0.74 or bright_pct > 0.35:
                    lighting = "blown_out_flash"
                elif contrast > 0.28:
                    lighting = "high_contrast"
                elif contrast < 0.12:
                    lighting = "flat_fluorescent"
                else:
                    lighting = "balanced_daylight"

                # Dominant color palette
                r, g, b = float(mean_rgb[0]), float(mean_rgb[1]), float(mean_rgb[2])
                if sat < 0.14 and luma < 0.32:
                    palette = "all_black_monochrome"
                elif sat < 0.15:
                    palette = "washed_gray"
                elif sat > 0.48:
                    palette = "loud_neon"
                elif r > g + 0.08 and r > b + 0.10:
                    palette = "warm_amber_red"
                elif b > r + 0.07 and b >= g:
                    palette = "cool_blue_cyan"
                else:
                    palette = "earthy_neutral"

                # Saturation / filter vibe
                if sat > 0.44:
                    saturation = "oversaturated_filter"
                elif sat < 0.18:
                    saturation = "desaturated_vintage"
                else:
                    saturation = "natural_color"

                # Border clutter vs center focus via gradient energy
                gy, gx = np.gradient(luma_map)
                grad = np.hypot(gx, gy)
                center_grad = float(grad[16:48, 16:48].mean())
                border_mask = np.ones_like(grad, dtype=bool)
                border_mask[14:50, 14:50] = False
                border_grad = float(grad[border_mask].mean())
                if border_grad > 0.012 and border_grad >= center_grad * 0.85:
                    clutter = "cluttered_background"
                else:
                    clutter = "clean_backdrop"

                center_var = float(luma_map[16:48, 16:48].std())
                if center_var > border_grad * 1.4 and aspect in ("vertical_selfie", "square_crop"):
                    framing = "tight_closeup"
                elif aspect == "wide_landscape":
                    framing = "wide_scene"
                else:
                    framing = "mid_shot"

                details = [
                    f"{lighting.replace('_', ' ')} lighting",
                    f"{palette.replace('_', ' ')} color palette",
                    f"{aspect.replace('_', ' ')} framing",
                    f"{clutter.replace('_', ' ')}",
                ]
                details = [d for d in details if not any(term in d.casefold() for term in terms)]
                trait.update({
                    "aspect": aspect,
                    "lighting": lighting,
                    "palette": palette,
                    "saturation": saturation,
                    "clutter": clutter,
                    "framing": framing,
                    "brightness": round(luma, 3),
                    "details": details,
                })
        except Exception:
            pass
        profiles.append(trait)
    return profiles


def _lighting_lines(lighting: str, guest: str, img_num: int, heat: str) -> List[Tuple[str, str]]:
    bank: Dict[str, List[Tuple[str, str]]] = {
        "dim_moody": [
            ("light_dim_1", f"Why is photo {img_num} lit like {guest} is hiding from a process server in a basement?"),
            ("light_dim_2", f"Did {guest} shoot photo {img_num} inside a glove compartment, or is the electric bill part of the roast?"),
            ("light_dim_3", f"In frame {img_num}, {guest} turned the brightness down so low even my screen asked for a flashlight."),
            ("light_dim_4", f"Photo {img_num} has pure witness-protection lighting — {guest} is three shadows away from becoming a true-crime silhouette."),
        ],
        "blown_out_flash": [
            ("light_flash_1", f"Photo {img_num} has so much flash glare I thought {guest} was opening the Ark of the Covenant."),
            ("light_flash_2", f"Who aimed a police helicopter spotlight at {guest} in photo {img_num}? My retinas just filed for workers' comp."),
            ("light_flash_3", f"{guest} cranked the exposure on shot {img_num} until half the background went straight to heaven."),
            ("light_flash_4", f"Frame {img_num} looks like {guest} took a selfie directly inside a microwave ring light."),
        ],
        "high_contrast": [
            ("light_hc_1", f"Look at the dramatic shadows in photo {img_num} — {guest} thinks this is an Oscar-campaign poster instead of a Tuesday."),
            ("light_hc_2", f"Shot {img_num} has movie-villain contrast, like {guest} rehearsed a monologue before checking the mirror."),
            ("light_hc_3", f"With that moody lighting in photo {img_num}, {guest} is auditioning to narrate cologne commercials nobody buys."),
        ],
        "flat_fluorescent": [
            ("light_flat_1", f"Photo {img_num} has the exact fluorescent glow of a 24-hour laundromat at 2 a.m., and {guest} still posed like a VIP."),
            ("light_flat_2", f"The lighting in frame {img_num} looks like a break-room ceiling panel — somehow {guest} still brought main-character posture."),
            ("light_flat_3", f"Shot {img_num} was clearly captured under office-cubicle lighting while {guest} pretended it was golden hour."),
        ],
        "balanced_daylight": [
            ("light_day_1", f"{guest} chose full daylight in photo {img_num} — bold decision when there are zero shadows left to blame."),
            ("light_day_2", f"Full-clarity lighting in frame {img_num}, and {guest} still hit upload with complete confidence. Respect the bravery, question the judgment."),
            ("light_day_3", f"Shot {img_num} is crystal clear from edge to edge, which means {guest} had plenty of light to rethink that pose and chose not to."),
        ],
    }
    lines = list(bank.get(lighting, bank["balanced_daylight"]))
    if heat in ("fire", "inferno"):
        lines.append((f"light_extra_{lighting}", f"Honestly, in frame {img_num}, {guest} looked directly at that {lighting.replace('_', ' ')} setup and still thought 'yeah, the internet needs this.'"))
    return lines


def _palette_lines(palette: str, saturation: str, guest: str, img_num: int) -> List[Tuple[str, str]]:
    bank: Dict[str, List[Tuple[str, str]]] = {
        "all_black_monochrome": [
            ("pal_blk_1", f"All-dark everything in shot {img_num} — {guest} dressed like a bouncer for an imaginary nightclub."),
            ("pal_blk_2", f"{guest} went full monochrome in photo {img_num}, like wearing black hides bad decisions."),
            ("pal_blk_3", f"Between the dark tones and serious face in frame {img_num}, {guest} looks like a backup dancer for a funeral."),
        ],
        "loud_neon": [
            ("pal_neon_1", f"The colors in photo {img_num} are screaming so loud my speakers clipped — did {guest} get dressed inside a highlighter factory?"),
            ("pal_neon_2", f"Look at the color saturation in shot {img_num}: {guest} is visible from commercial airspace."),
            ("pal_neon_3", f"{guest} turned the color slider in photo {img_num} up past eleven until even traffic cones looked subtle."),
        ],
        "warm_amber_red": [
            ("pal_warm_1", f"Photo {img_num} is soaked in so much warm orange tint {guest} looks like they're posing inside a toaster oven."),
            ("pal_warm_2", f"That heavy warm tone in frame {img_num} makes {guest} look like a sunset filter that lost a fistfight."),
            ("pal_warm_3", f"{guest} bathed shot {img_num} in amber light like a dramatic sitcom flashback."),
        ],
        "cool_blue_cyan": [
            ("pal_cool_1", f"Why is photo {img_num} tinted blue like {guest} took it through a fish tank?"),
            ("pal_cool_2", f"That icy blue glow in shot {img_num} makes {guest} look like a hologram waiting for a software patch."),
            ("pal_cool_3", f"Frame {img_num} has pure 3 a.m. monitor-glare energy — {guest} didn't even leave the desk lamp on."),
        ],
        "washed_gray": [
            ("pal_gray_1", f"Photo {img_num} has less color than a tax audit — {guest} drained the joy straight out of the pixels."),
            ("pal_gray_2", f"Look at the faded gray vibe in frame {img_num}: {guest} looks like an album cover for songs about expired coupons."),
            ("pal_gray_3", f"{guest} uploaded shot {img_num} in beige-and-gray like color costs extra per megabyte."),
        ],
        "earthy_neutral": [
            ("pal_earth_1", f"All those neutral tones in photo {img_num} — {guest} blended right into a furniture catalog and called it drip."),
            ("pal_earth_2", f"Frame {img_num} looks like an oat-milk commercial starring {guest}'s unbothered expression."),
            ("pal_earth_3", f"{guest} picked an earth-tone palette in shot {img_num} so safe even beige walls feel edgy next to it."),
        ],
    }
    lines = list(bank.get(palette, bank["earthy_neutral"]))
    if saturation == "oversaturated_filter":
        lines.append((f"sat_hi_{img_num}", f"By the way, whichever filter {guest} slapped on photo {img_num} is working harder than a defense attorney."))
    elif saturation == "desaturated_vintage":
        lines.append((f"sat_lo_{img_num}", f"And that faded vintage wash on frame {img_num}? {guest} wasn't trying to be artistic — that's just low morale in JPEG form."))
    return lines


def _framing_lines(aspect: str, clutter: str, guest: str, img_num: int) -> List[Tuple[str, str]]:
    lines: List[Tuple[str, str]] = []
    if aspect == "tall_screenshot":
        lines.extend([
            ("frm_tall_1", f"Photo {img_num} is cropped like a panicked phone screenshot — {guest} couldn't even find the original file in their own camera roll."),
            ("frm_tall_2", f"Did {guest} upload an uncropped phone screen for frame {img_num}? Next time crop out the bad decisions first."),
        ])
    elif aspect == "vertical_selfie":
        lines.extend([
            ("frm_vert_1", f"Look at that tight vertical angle in shot {img_num} — {guest} held the phone at exact flattering altitude like a trained sniper."),
            ("frm_vert_2", f"Frame {img_num} is classic arm's-length selfie geometry: {guest} worked thirty angles to pick the one that says 'I woke up like this.'"),
        ])
    elif aspect == "wide_landscape":
        lines.extend([
            ("frm_wide_1", f"Why is photo {img_num} in widescreen cinema aspect? {guest} really thought the surrounding room deserved an IMAX budget."),
            ("frm_wide_2", f"In shot {img_num}, there's so much wide empty margin around {guest} even the background is keeping a polite distance."),
        ])
    else:
        lines.extend([
            ("frm_sq_1", f"Neat little square crop on photo {img_num} — {guest} trimmed the edges right where the mess started."),
            ("frm_sq_2", f"Shot {img_num} is framed like {guest} spent twenty minutes cropping out whoever didn't pay for dinner."),
        ])

    if clutter == "cluttered_background":
        lines.extend([
            ("clut_1", f"And don't think nobody spotted the chaotic background in photo {img_num} — {guest} really hit 'post' without glancing behind them once."),
            ("clut_2", f"There is so much visual clutter behind {guest} in frame {img_num} it looks like an I-Spy book for procrastination."),
        ])
    else:
        lines.extend([
            ("clean_bg_1", f"Notice how clean the backdrop is in shot {img_num} — {guest} definitely kicked a pile of laundry out of frame two seconds before the timer went off."),
            ("clean_bg_2", f"Standing against a blank wall in photo {img_num} like a passport renewal doesn't make {guest} mysterious, it just looks like a hostage proof-of-life."),
        ])
    return lines


def _persona_angle_line(persona: Dict, guest: str, prev_persona: Optional[Dict], img_idx: int, heat: str, adult: bool) -> Tuple[str, str]:
    pname = persona.get("displayName") or persona.get("name") or persona["id"]
    topics = [t for t in (persona.get("topics") or []) if isinstance(t, str) and t.strip()]
    lingo = [w for w in (persona.get("lingo") or []) if isinstance(w, str) and w.strip()]
    role = (persona.get("role") or "roaster").strip()
    topic = _RNG.choice(topics) if topics else "bad life choices"
    slang = _RNG.choice(lingo) if lingo else "listen"
    prev_name = (prev_persona.get("displayName") or prev_persona.get("name") or "they") if prev_persona else None

    pool = [
        ("p_role_1", f"{slang}, as {role.lower()}, I've seen a lot of questionable {topic}, but {guest} turned it into an extreme sport."),
        ("p_role_2", f"Hold on — {guest} brings up {topic} like an expert, yet photo {img_idx + 1} screams 'expired free trial.'"),
        ("p_role_3", f"You don't even have to know {guest}'s browser history to tell that {topic} is currently undefeated against them."),
        ("p_role_4", f"The wild part is {guest} probably thinks {topic} is their strong suit — somebody hand them a mirror and a helmet."),
        ("p_role_5", f"With that look in frame {img_idx + 1}, {guest} is one pep talk away from giving terrible advice about {topic} on a podcast nobody subscribed to."),
    ]
    if prev_name and prev_persona and prev_persona["id"] != persona["id"]:
        pool.extend([
            ("p_reply_1", f"Wait, {prev_name} was going easy on you, {guest} — from over here, your whole aura looks like an unskippable tutorial."),
            ("p_reply_2", f"Forget what {prev_name} just said, {guest} — look at frame {img_idx + 1} again. That is the face of someone who claps when the airplane lands."),
            ("p_reply_3", f"Nah {prev_name}, don't let {guest} off that light — that smirk says 'I reply all to company emails just to say thanks.'"),
            ("p_reply_4", f"I'm backing {prev_name} up on this one: {guest} radiates pure 'reads the menu out loud before ordering chicken tenders' energy."),
        ])
    if heat in ("fire", "inferno") and adult:
        pool.extend([
            ("p_hot_1", f"Let's cut the polite bullshit, {guest} — even {pname} has limits, and your whole vibe in shot {img_idx + 1} is testing them."),
            ("p_hot_2", f"{slang}, {guest} walked in acting bulletproof while looking like a bad decision that learned how to text back."),
        ])
    return _RNG.choice(pool)


def _context_roast_lines(angle: str, persona: Dict, guest: str, img_idx: int, heat: str) -> List[Tuple[str, str]]:
    lingo = [w for w in (persona.get("lingo") or []) if isinstance(w, str) and w.strip()]
    slang = _RNG.choice(lingo) if lingo else "wait a second"
    pool = [
        (f"ctx_1_{hash(angle) % 999}", f"Wait — '{angle}'? {slang}, {guest} put that in writing like it was a flex instead of a warning label."),
        (f"ctx_2_{hash(angle) % 999}", f"So {guest} wants us to know '{angle}', meanwhile photo {img_idx + 1} looks like the exact moment that plan fell apart."),
        (f"ctx_3_{hash(angle) % 999}", f"Nobody asked for the backstory '{angle}', yet {guest} volunteered it anyway — bold move in a room full of comedians."),
        (f"ctx_4_{hash(angle) % 999}", f"'{angle}' is hilarious coming from somebody posing like frame {img_idx + 1} — pick a struggle, {guest}."),
    ]
    if heat in ("fire", "inferno"):
        pool.append((f"ctx_5_{hash(angle) % 999}", f"If '{angle}' is your highlight reel, {guest}, I'd hate to see the deleted scenes."))
    return pool


def _pick_fresh(candidates: List[Tuple[str, str]], used_in_show: set) -> Optional[str]:
    _RNG.shuffle(candidates)
    # Prefer templates not seen in recent shows OR in this show
    for tid, text in candidates:
        if tid not in used_in_show and tid not in _RECENT_TEMPLATE_IDS:
            used_in_show.add(tid)
            _RECENT_TEMPLATE_IDS.append(tid)
            return text
    for tid, text in candidates:
        if tid not in used_in_show:
            used_in_show.add(tid)
            _RECENT_TEMPLATE_IDS.append(tid)
            return text
    return None


def _style_flavor(styles: Optional[List[str]]) -> str:
    if not styles:
        return ""
    s = styles[0]
    notes = {
        "savage": "cutting verbal takedown",
        "dark": "dark comic twist",
        "street_battle": "competitive stage snap",
        "sarcastic": "bone-dry sarcasm",
        "intellectual": "sharp wordplay",
        "absurdist": "absurd surreal comparison",
        "southern_country": "country storytelling drawl",
        "old_school": "classic club timing",
        "celebrity_roast": "headline dais energy",
        "freestyle": "loose freestyle riff",
    }
    return notes.get(s, "")


def build_sandbox_preview_lineup_roasts(
    personas: List[Dict],
    *,
    adult: bool = True,
    off_limits: Optional[str] = None,
) -> Dict[str, str]:
    """Generate fresh, non-repeating host walk-on jokes per persona for sandbox previews."""
    out: Dict[str, str] = {}
    used = set()
    for p in personas:
        name = (p.get("displayName") or p.get("name") or p["id"]).strip()
        role = (p.get("role") or "panel comic").strip().lower()
        topics = [t for t in (p.get("topics") or []) if isinstance(t, str) and t.strip()]
        topic = _RNG.choice(topics) if topics else "hot takes"
        candidates = [
            f"{name} calls themselves a {role}, which is fancy talk for starting arguments nobody invited.",
            f"Everybody watch your drinks — {name} brought thirty minutes of material about {topic} and zero self-restraint.",
            f"{name} showed up early just to practice looking unimpressed in the mirror.",
            f"Make some noise for {name}, the only comic here whose punchlines require a reading glasses prescription.",
            f"{name} talks big about {topic} like the group chat hasn't had them on mute since last spring.",
            f"Give it up for {name} — confident enough to headline, chaotic enough to get kicked out of the green room.",
        ]
        _RNG.shuffle(candidates)
        for cand in candidates:
            cleaned = _clean_text(cand, off_limits, adult)
            if cleaned.casefold() not in used:
                used.add(cleaned.casefold())
                out[p["id"]] = cleaned
                break
    return out


def build_sandbox_preview_beats(
    personas: List[Dict],
    *,
    subject_name: Optional[str] = None,
    user_context: Optional[str] = None,
    expected_beats: Optional[int] = None,
    n_images: int = 1,
    images: Optional[List[bytes]] = None,
    adult: bool = True,
    off_limits: Optional[str] = None,
    is_battle: bool = False,
    is_rap: bool = False,
    comedy_styles: Optional[List[str]] = None,
    heat: str = "hot",
    roast_tier: str = "standard",
    premium_voice: bool = False,
) -> List[Dict]:
    """Build a fresh, photo-aware, persona-voiced script for sandbox preview mode."""
    if not personas:
        return []
    guest = _clean_text(subject_name or "", off_limits, adult) or "tonight's guest"
    ctx_angles = _extract_context_angles(user_context, off_limits, adult)
    img_profiles = analyze_images_locally(images, off_limits=off_limits)
    n_imgs = max(1, len(img_profiles) or int(n_images or 1))
    count = max(6, int(expected_beats or (8 if is_battle else 10)))
    used_in_show: set = set()
    style_note = _style_flavor(comedy_styles)
    is_premium = roast_tier == "premium"

    if is_battle and len(personas) >= 2:
        a, b = personas[0], personas[1]
        a_name = a.get("displayName") or a.get("name") or a["id"]
        b_name = b.get("displayName") or b.get("name") or b["id"]
        a_topic = (_RNG.choice(a.get("topics") or ["mic skills"]))
        b_topic = (_RNG.choice(b.get("topics") or ["crowd work"]))
        hook = ctx_angles[0] if ctx_angles else ""

        rap_pool_a = [
            ("rap_a1", f"{b_name} stepped in the booth looking like a clearance-rack sequel, talking heavy with a cadence barely legal."),
            ("rap_a2", f"You claim mastery over {b_topic}, {b_name}? Even {guest} wouldn't co-sign your highlight reel on laundry day."),
            ("rap_a3", f"Watch {b_name} sweating under stage lights, dropping recycled sixteen-bar clichés from two thousand and hype-less nights."),
            ("rap_a4", f"I came sharper than a blade on concrete, {b_name} — pack that weak rhyme scheme and take the backseat."),
            ("rap_a5", f"Every verse you spit sounds like buffering Wi-Fi, {b_name} — step aside while I electrify this entire side."),
        ]
        rap_pool_b = [
            ("rap_b1", f"Cute bar, {a_name}, did you draft it on a napkin? Your whole delivery sounds like GPS recalculating."),
            ("rap_b2", f"At least {guest} brought real presence to the show — {a_name} is swinging wild and missing every single blow."),
            ("rap_b3", f"Talk big about {a_topic}, {a_name}, your best line was the exit sign — scoreboard already says the belt is mine."),
            ("rap_b4", f"Drop the mic before the buzzer rings, {a_name} — crowd didn't pay for cover bands, they paid for kings."),
            ("rap_b5", f"You brought butter-knife bars to a lyrical riot, {a_name} — after this round even your corner goes quiet."),
        ]
        classic_pool_a = [
            ("cls_a1", f"Honestly {b_name}, standing across from you makes {guest}'s photo look like a museum centerpiece by comparison."),
            ("cls_a2", f"{b_name}'s whole strategy is just talking faster whenever the room stops laughing — and listen how loud the air conditioning just got."),
            ("cls_a3", f"Don't sweat it {b_name}, if stand-up stalls out, there's always reading terms and conditions in slow motion."),
            ("cls_a4", f"Even {guest} is nodding right now because we all know {b_name} brought safety scissors to a chainsaw duel."),
            ("cls_a5", f"{b_name} acts like an authority on {b_topic}, yet dresses like a lost-and-found bin got a budget."),
        ]
        classic_pool_b = [
            ("cls_b1", f"Bold talk from {a_name}, whose confidence is writing checks their punchlines keep bouncing."),
            ("cls_b2", f"I admire {a_name}'s stamina — truly inspiring what zero self-awareness can accomplish near a microphone."),
            ("cls_b3", f"{a_name} came ready to roast {guest}, ran out of ammo in ten seconds, and started improvising apologies."),
            ("cls_b4", f"Wrap it up {a_name} — the only thing getting cooked in your round is the shot clock."),
            ("cls_b5", f"You brag about {a_topic} like anybody asked, {a_name} — meanwhile your best punchline was introducing me."),
        ]

        beats: List[Dict] = []
        emotions = ["cocky", "sarcastic", "hype", "smug", "outraged", "incredulous"]
        reactions = ["laugh", "ooh", "cheer"]
        laughs = ["medium", "big", "explosive"]
        for i in range(count):
            fighter = a if i % 2 == 0 else b
            pool = list(rap_pool_a if is_rap else classic_pool_a) if i % 2 == 0 else list(rap_pool_b if is_rap else classic_pool_b)
            txt = _pick_fresh(pool, used_in_show) or pool[i % len(pool)][1]
            if i == 2 and img_profiles:
                p0 = img_profiles[0]
                txt = f"{txt} And look at {guest}'s photo 1 ({p0['lighting'].replace('_', ' ')}) — even the camera took a side."
            elif i == 1 and hook:
                txt = f"{txt} Plus '{hook}'? Neither of us forgot about that."
            beats.append({
                "persona_id": fighter["id"],
                "type": "intro" if i == 0 else ("closer" if i == count - 1 else "punchline"),
                "text": _clean_text(txt, off_limits, adult),
                "emotion": emotions[i % len(emotions)],
                "delivery": "rapid battle bar on beat" if is_rap else (style_note or "sharp ring comeback"),
                "laugh_after": laughs[i % len(laughs)],
                "reaction": reactions[i % len(reactions)],
                "pause_before_ms": 170,
                "pause_after_ms": 250,
                "image_index": i % n_imgs,
                "rap_delivery": bool(is_rap),
                "_standalone": True,
                "_sandbox_preview": True,
            })
        return beats

    # Roast show mode: assemble rich, non-repeating beats grounded in actual
    # photo attributes, user context clauses, persona quirks, and banter.
    emotions = ["cocky", "sarcastic", "deadpan", "smug", "incredulous", "outraged", "hype"]
    laughs = ["small", "medium", "big", "explosive"]
    reactions = ["laugh", "ooh", "cheer"]
    lineup_map = build_sandbox_preview_lineup_roasts(personas, adult=adult, off_limits=off_limits)

    beats = []
    # Shuffle persona order after index 0 (host) for fresh panel pacing
    panel_order = [personas[0]] + _RNG.sample(personas[1:], len(personas) - 1) if len(personas) > 1 else [personas[0]]

    for i in range(count):
        p = panel_order[i % len(panel_order)]
        prev_p = panel_order[(i - 1) % len(panel_order)] if i > 0 else None
        img_idx = i % n_imgs
        prof = img_profiles[img_idx] if img_idx < len(img_profiles) else {
            "lighting": "balanced_daylight",
            "palette": "earthy_neutral",
            "saturation": "natural_color",
            "aspect": "square_crop",
            "clutter": "clean_backdrop",
        }
        img_num = img_idx + 1

        chosen_line: Optional[str] = None
        beat_type = "joke"

        if i == 0:
            # Photo-grounded opening jab using real lighting/aspect observations
            openers = _lighting_lines(prof["lighting"], guest, img_num, heat) + [
                ("open_gen_1", f"{guest} walked onto the big screen in photo {img_num} looking way too proud for somebody who hasn't heard the panel yet."),
                ("open_gen_2", f"Look at {guest} in shot {img_num} — pure 'clicked surprise me on character creation and rolled with it' energy."),
            ]
            chosen_line = _pick_fresh(openers, used_in_show)
            beat_type = "intro"
        elif i == count - 1:
            # Callback & mic-drop closer referencing context or multi-photo contrast
            closers = [
                ("close_1", f"Give it up for {guest} — stayed in the hot seat through {heat} heat while photo {img_num} officially filed for witness protection!"),
                ("close_2", f"Alright {guest}, much love for stepping up tonight — you survived the panel, even if that camera roll needs a week in recovery!"),
                ("close_3", f"Say what you want about {guest}, they took every hit like a champ — and now somebody go turn a real lamp on for photo {img_num}!"),
            ]
            if ctx_angles:
                closers.append(("close_ctx", f"At the end of the night, {guest} survived the whole panel — '{ctx_angles[0]}' and all — so give them a hand before we call security on that outfit!"))
            chosen_line = _pick_fresh(closers, used_in_show)
            beat_type = "closer"
        elif ctx_angles and i in (1, 5, 9) and (i // 4) < len(ctx_angles):
            angle = ctx_angles[(i // 4) % len(ctx_angles)]
            chosen_line = _pick_fresh(_context_roast_lines(angle, p, guest, img_idx, heat), used_in_show)
            beat_type = "punchline"
        elif i % 4 == 2:
            chosen_line = _pick_fresh(
                _palette_lines(prof["palette"], prof["saturation"], guest, img_num),
                used_in_show,
            )
            beat_type = "punchline"
        elif i % 4 == 3:
            chosen_line = _pick_fresh(
                _framing_lines(prof["aspect"], prof["clutter"], guest, img_num),
                used_in_show,
            )
            beat_type = "tag" if len(personas) > 1 else "crowd_work"
        else:
            # Mix persona topic/banter + multi-photo comparison if available
            if len(img_profiles) >= 2 and i == 4:
                p0, p1 = img_profiles[0], img_profiles[1]
                multi = [
                    ("multi_1", f"Compare photo 1 ({p0['lighting'].replace('_', ' ')}) to photo 2 ({p1['lighting'].replace('_', ' ')}) — {guest} aged three whole moods between uploads."),
                    ("multi_2", f"Between frame 1's {p0['palette'].replace('_', ' ')} vibe and frame 2's {p1['palette'].replace('_', ' ')} look, {guest} still couldn't decide who they're catfishing."),
                ]
                chosen_line = _pick_fresh(multi, used_in_show)
            if not chosen_line:
                tid, p_line = _persona_angle_line(p, guest, prev_p, img_idx, heat, adult)
                if tid in used_in_show:
                    # Fallback to lighting/palette lines not yet used
                    fallback_pool = _lighting_lines(prof["lighting"], guest, img_num, heat) + _framing_lines(prof["aspect"], prof["clutter"], guest, img_num)
                    chosen_line = _pick_fresh(fallback_pool, used_in_show) or p_line
                else:
                    used_in_show.add(tid)
                    chosen_line = p_line
            beat_type = "callback" if i >= count - 3 else "joke"

        if not chosen_line:
            chosen_line = f"{guest}, even {p.get('displayName') or p['id']} is stunned by the sheer audacity in frame {img_num}."

        delivery_base = style_note or ("high-craft headline delivery" if is_premium else f"{heat} comedy-club delivery")
        beat_obj = {
            "persona_id": p["id"],
            "type": beat_type,
            "text": _clean_text(chosen_line, off_limits, adult),
            "emotion": _RNG.choice(emotions),
            "delivery": f"{delivery_base}, land the surprise at the end",
            "laugh_after": "explosive" if i == count - 1 else _RNG.choice(laughs[1:] if is_premium else laughs),
            "reaction": "cheer" if i == count - 1 else _RNG.choice(reactions),
            "pause_before_ms": 180 if beat_type == "tag" else 230,
            "pause_after_ms": 260 if is_premium else 300,
            "image_index": img_idx,
            "premium_voice": bool(premium_voice),
            "roast_tier": roast_tier,
            "_standalone": beat_type not in ("tag", "callback"),
            "_sandbox_preview": True,
        }
        if p["id"] in lineup_map:
            beat_obj["_lineup_roast"] = lineup_map.pop(p["id"])
        beats.append(beat_obj)
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
