#!/usr/bin/env python3
"""Build a valid, beat-synced schema_version 2 starting plan from analysis.json.

Usage:
    baseline_plan.py WORK_DIR [--duration S] [--hook TEXT] [--subtitle TEXT] [--seed N]
                     [--prefs FILE] [--out FILE] [--script FILE] [--before ID --after ID] [--turn S]

Reads WORK_DIR/analysis.json and writes WORK_DIR/plan.json (or --out). The
plan follows the edit grammar (spec p.18-19) mechanically; the Director then
improves story order, looks and key words. It is never the final creative plan.

* Hook text (--hook, else the first caption line) on screen from frame 0; the
  reel opens on the strongest image (vision/sharpness scores when present, else
  folder order), never on the logo, with movement from frame 1.
* One beat-snapped cut per caption line where possible; 2-beat cuts in the
  first tense section (up to --turn, else the first ~15-30%), 4-beat holds
  otherwise, no shot over 4 beats.
* When the voice stops before the end, the music-only outro gets a fast recap
  montage of the best shots (up to 8), 2 beats each.
* Exactly one signature moment: a before/after wipe when --before/--after name
  a pair of photo/clip ids (P3, C0, ...), else a white-flash reveal on the
  biggest caption line.
* Whips at most every third cut, varied transitions, zooms alternating in and
  out, a pan across wide photos, before/warm looks split at --turn.
* End card on the last beats, held 3.5-5 s, over the bundled ripple image.
* Captions: one sentence per line (2 rows max), 1-2 gold key words per line.
  Music-only material with --script FILE (one sentence per line) gets the
  script as timed on-screen lines at about 2.3 words a second, on the beats.
* No photos or clips: the bundled brand photos are used.
* `formats` defaults: an 8-12 s reach cut around the signature moment, 3-5
  story stills, 5-8 carousel slides and a cover, when there is text for them.

Duration = min(--duration, audio, 60 s). Deterministic: same inputs, same plan.
"""
from __future__ import annotations

import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import validate_plan  # noqa: E402

MAX_LEN_S = 60.0
DEFAULT_NO_AUDIO_S = 30.0
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STOP = set("""a an and are as at be but by for from had has have he her his i in is it its me my no not of on or our
so than that the their them then there they this to too up us was we were what when which who will with you your
just like into over very can all out about been more most only own same some such these those also it's i'm we're
don't""".split())


@dataclass
class Media:
    id: str
    kind: str  # image | video
    src: str
    size: tuple[int, int] | None
    score: float
    duration: float = 0.0
    window: float | None = None
    faces: list = field(default_factory=list)
    focus: list | None = None
    logo: bool = False


def _cfg(dotted: str, default: Any) -> Any:
    try:
        return nc.config_value(dotted, default)
    except nc.UserError:
        return default


def r3(x: float) -> float:
    return round(float(x) + 0.0, 3)


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------
def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001 - unreadable file: no size, no pan
        return None


def collect_media(A: dict) -> list[Media]:
    items: list[Media] = []
    sharp = [p.get("sharpness") for p in A.get("photos", []) + A.get("clips", []) if p.get("sharpness") is not None]
    top = max(sharp) if sharp else 0.0
    logos = set()
    for key in ("wordmark", "secondary_mark"):
        try:
            logos.add(str(nc.brand_asset(key).resolve()))
        except nc.UserError:
            pass

    def is_logo(path: str) -> bool:
        return str(Path(path).resolve()) in logos or "logo" in Path(path).stem.lower()

    for p in A.get("photos", []):
        src = p.get("prepared_path") or p["path"]
        s = (p.get("sharpness") or 0.0) / top if top else 0.0
        s += 0.15 * min(1.0, len(p.get("faces") or []))
        items.append(Media(p["id"], "image", src, tuple(p["size"]) if p.get("size") else None, s,
                           faces=list(p.get("faces") or []), focus=p.get("focus"), logo=is_logo(src)))
    for c in A.get("clips", []):
        src = c.get("prepared_path") or c["path"]
        s = (c.get("sharpness") or 0.0) / top if top else 0.0
        win = None
        if c.get("windows"):
            win = float(c["windows"][0][0])
            s += 0.5 * float(c["windows"][0][2])
        s += 0.25  # a clip moves from frame 1
        items.append(Media(c["id"], "video", src, tuple(c["size"]) if c.get("size") else None, s,
                           duration=float(c.get("duration") or 0.0), window=win,
                           faces=list(c.get("faces") or []), focus=c.get("focus"), logo=is_logo(src)))
    if not any(p.get("sharpness") is not None or p.get("windows") or p.get("faces")
               for p in A.get("photos", []) + A.get("clips", [])):
        for m in items:  # no analysis scores: folder order decides
            m.score = 0.0
    items = [m for m in items if m.kind == "image" or m.duration > 0.1]
    if items:
        return items
    # R96: no visuals in the folder -> the bundled brand photos
    try:
        folder = nc.brand_asset("brand_photos_dir")
    except nc.UserError:
        folder = nc.BRAND_PHOTOS_DIR
    files = sorted(f for f in Path(folder).iterdir() if f.suffix.lower() in IMAGE_EXT) if Path(folder).is_dir() else []
    if not files:
        raise nc.UserError(f"no photos or clips in analysis.json and no brand photos in {folder}")
    nc.warn(f"no photos or clips in the folder: using the {len(files)} bundled brand photos")
    return [Media(f"B{i}", "image", str(f.resolve()), _image_size(f), 0.0, logo=is_logo(str(f)))
            for i, f in enumerate(files)]


# ---------------------------------------------------------------------------
# Beats
# ---------------------------------------------------------------------------
def beat_grid(A: dict, D: float) -> tuple[list[float], float]:
    beats = sorted(float(b) for b in A.get("beats") or [] if 0 <= float(b) < D)
    diffs = [b - a for a, b in zip(beats, beats[1:]) if b - a > 1e-3]
    if diffs:
        period = statistics.median(diffs)
    elif A.get("bpm"):
        period = 60.0 / float(A["bpm"])
    else:
        period = 0.5
    if len(beats) < 2:
        beats = [r3(i * period) for i in range(1, int(D / period) + 1)]
    else:
        t = beats[-1] + period
        while t < D - 0.05:  # beat tracking can stop early: continue the grid
            beats.append(r3(t))
            t += period
    if period < 0.3:  # very fast music: cut on every other beat
        beats, period = beats[::2], period * 2
    return [r3(b) for b in beats if 0 < b < D], period


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------
class RowMeter:
    """Counts caption rows the way the engine wraps them (92 px font, 960 px box)."""

    def __init__(self) -> None:
        from PIL import ImageFont
        px = int(_cfg("render.captions.font_px", 92))
        self.fr = ImageFont.truetype(str(nc.brand_font("regular")), px)
        self.fi = ImageFont.truetype(str(nc.brand_font("italic")), px)

    def rows(self, words: list[str], gold: bool = True) -> int:
        rows, rw = 1, 0.0
        for w in words:
            ww = max(self.fr.getlength(w), self.fi.getlength(w) if gold else 0) + 26
            if rw + ww > 960 and rw > 0:
                rows, rw = rows + 1, 0.0
            rw += ww
        return rows


def _clean(w: str) -> str:
    return re.sub(r"[^\w']+", "", w.lower()).strip("'")


def pick_gold(words: list[str]) -> set[int]:
    """1-2 key words: the longest content words (later wins ties); 2 for lines of 6+ words."""
    cand = [(len(_clean(w)), i) for i, w in enumerate(words) if _clean(w) not in STOP and len(_clean(w)) >= 4]
    if not cand:
        cand = [(len(_clean(w)), i) for i, w in enumerate(words) if _clean(w)]
    if not cand:
        return set()
    cand.sort(key=lambda x: (-x[0], -x[1]))
    n = 2 if len(words) >= 6 and len(cand) >= 2 else 1
    return {i for _, i in cand[:n]}


def split_sentences(words: list[dict], meter: RowMeter, max_chars: int = 70) -> list[list[dict]]:
    """Words -> lines: one sentence per line, split at pauses, then at commas/midpoints to stay within 2 rows."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for j, w in enumerate(words):
        cur.append(w)
        nxt = words[j + 1] if j + 1 < len(words) else None
        if nxt is None or w["w"].rstrip().endswith((".", "!", "?")) or float(nxt["appear"]) - float(w["end"]) > 0.7:
            groups.append(cur)
            cur = []
    out: list[list[dict]] = []

    def fits(g: list[dict]) -> bool:
        return meter.rows([x["w"] for x in g]) <= 2 and len(" ".join(x["w"] for x in g)) <= max_chars

    def split(g: list[dict]) -> None:
        if len(g) <= 1 or fits(g):
            out.append(g)
            return
        mid = len(g) // 2
        commas = [i + 1 for i, x in enumerate(g[:-1]) if x["w"].rstrip().endswith((",", ";", ":", "-"))]
        cut = min(commas, key=lambda i: abs(i - mid)) if commas else mid
        if not 0 < cut < len(g):
            cut = mid
        split(g[:cut])
        split(g[cut:])

    for g in groups:
        split(g)
    return out


def make_line(group: list[dict], end: float) -> dict:
    texts = [x["w"] for x in group]
    gold = pick_gold(texts)
    ws = []
    for i, x in enumerate(group):
        w: list = [x["w"], r3(x["appear"])]
        if i in gold:
            w.append(1)
        ws.append(w)
    return {"words": ws, "end": r3(end)}


def lines_from_words(words: list[dict], body_end: float, D: float, meter: RowMeter) -> list[dict]:
    words = [w for w in words if float(w["appear"]) < body_end - 0.3]
    groups = split_sentences(words, meter)
    lines = []
    for j, g in enumerate(groups):
        last = float(g[-1]["appear"])
        nxt = float(groups[j + 1][0]["appear"]) if j + 1 < len(groups) else min(body_end, D)
        end = min(float(g[-1]["end"]) + 0.6, nxt, body_end, D)
        lines.append(make_line(g, max(end, last)))
    return lines


def lines_from_script(script: str, grid: list[float], body_end: float, meter: RowMeter) -> list[dict]:
    """R92: script sentences as timed on-screen lines, starting on beats, ~2.3 words a second."""
    sentences: list[str] = []
    for raw in script.splitlines():
        raw = " ".join(raw.split())
        if raw:
            sentences += [s for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if not sentences:
        return []
    rate0 = float(_cfg("render.words_per_second", 2.3))
    groups_src = []
    for s in sentences:  # keep each line within 2 rows
        ws = [{"w": w, "appear": i * 0.1, "end": i * 0.1} for i, w in enumerate(s.split())]  # no pauses
        groups_src += [[x["w"] for x in g] for g in split_sentences(ws, meter)]

    def on_beat(t: float) -> float:
        later = [g for g in grid if g >= t - 1e-6]
        return later[0] if later else t

    def layout(rate: float, snap: bool) -> list[tuple[list[str], float, float]]:
        out = []
        t = on_beat(0.3) if snap else 0.3
        for g in groups_src:
            last = t + (len(g) - 1) / rate
            end = last + 0.8
            out.append((g, t, end))
            t = on_beat(end + 0.1) if snap else end + 0.1
        return out

    chosen = None
    for rate in (rate0, rate0 * 1.15, rate0 * 1.3, rate0 * 1.5, rate0 * 1.75):
        for snap in (True, False):
            lay = layout(rate, snap)
            if lay[-1][2] <= body_end - 0.2:
                chosen = (lay, rate)
                break
        if chosen:
            break
    if not chosen:
        lay = layout(rate0 * 1.75, False)
        kept = [x for x in lay if x[2] <= body_end - 0.2]
        nc.warn(f"the script is too long for {body_end:.1f} s: {len(lay) - len(kept)} line(s) left out")
        chosen = (kept, rate0 * 1.75)
    lay, rate = chosen
    lines = []
    for j, (g, t, end) in enumerate(lay):
        nxt = lay[j + 1][1] if j + 1 < len(lay) else body_end
        group = [{"w": w, "appear": t + i / rate} for i, w in enumerate(g)]
        lines.append(make_line(group, min(end, nxt)))
    return lines


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
def snap(t: float, points: list[float]) -> int:
    return min(range(len(points)), key=lambda i: (abs(points[i] - t), i))


def fill(points: list[float], anchors: list[int], tense_end: float) -> list[int]:
    """Cut indices into `points`: anchors kept, gaps filled with 2-beat (tense) or 4-beat pieces."""
    cuts = [anchors[0]]
    for a, b in zip(anchors, anchors[1:]):
        g = b - a
        step = 2 if points[a] < tense_end - 1e-6 else 4
        k = max(1, math.ceil(g / step))
        base, extra = divmod(g, k)
        idx = a
        for piece in range(k):
            idx += base + (1 if piece < extra else 0)
            cuts.append(idx)
    return cuts


def build_plan(work: Path, A: dict, *, duration: float | None = None, hook: str | None = None,
               subtitle: str | None = None, seed: int = 0, prefs: dict | None = None,
               script: str | None = None, before: str | None = None, after: str | None = None,
               turn: float | None = None) -> dict:
    prefs = prefs or {}
    audio_d = float(A.get("duration") or 0.0)
    if audio_d > 0:
        D = min(x for x in (duration, audio_d, MAX_LEN_S) if x)
    else:
        D = min(duration or DEFAULT_NO_AUDIO_S, MAX_LEN_S)
        nc.warn(f"analysis has no audio: building a {D:g} s plan without music")
    if isinstance(prefs.get("max_duration"), (int, float)):
        D = min(D, float(prefs["max_duration"]))
    D = r3(D)
    if D <= 1.0:
        raise nc.UserError(f"reel length {D:g} s is too short to build a plan")
    fps = int(_cfg("render.fps", 30))
    grid, period = beat_grid(A, D)
    media = collect_media(A)
    by_id = {m.id: m for m in media}
    meter = RowMeter()

    # end card on the last beats, held 3.5-5 s
    lo, hi = float(_cfg("render.endcard.min_hold_s", 3.5)), float(_cfg("render.endcard.max_hold_s", 5.0))
    end_t: float | None = None
    if D >= lo + 1.5:
        cands = [g for g in grid if lo - 1e-6 <= D - g <= hi + 1e-6]
        end_t = min(cands, key=lambda g: (abs(D - 4.0 - g), g)) if cands else r3(D - 4.0)
    body_end = end_t if end_t is not None else D

    # captions
    voice_words = [w for w in A.get("words") or [] if A.get("voice_present", True)]
    if voice_words:
        lines = lines_from_words(voice_words, body_end, D, meter)
    elif script:
        lines = lines_from_script(script, grid, body_end, meter)
    else:
        lines = []

    # outro montage (music after the last word)
    body_pts = [g for g in grid if 0.3 <= g <= body_end - 0.3]
    montage_start = None
    montage_pts: list[float] = []
    if voice_words and lines:
        last_word = max(float(w["end"]) for w in voice_words if float(w["appear"]) < body_end)
        tail = [g for g in body_pts if g >= last_word + 0.1]
        n = min(8, len(tail) // 2)
        if n >= 3:
            montage_pts = tail[len(tail) - 2 * n::2]
            montage_start = montage_pts[0]
    story_end = montage_start if montage_start is not None else body_end
    points = [0.0] + [g for g in body_pts if 0.3 <= g <= story_end - 0.3] + [story_end]

    # turn, tense section, signature
    turn_idx = snap(turn, points) if turn is not None and 0 < turn < story_end else None
    if turn_idx == 0:
        turn_idx = None
    if before or after:
        if not (before and after):
            raise nc.UsageError("--before and --after go together (the wipe needs both shots)")
        for i in (before, after):
            if i not in by_id:
                raise nc.UserError(f"--before/--after: no photo or clip with id {i} in analysis.json "
                                   f"(ids: {', '.join(sorted(by_id))})")
    line_anchor = []
    for ln in lines:
        t = float(ln["words"][0][1])
        if 1.2 <= t < story_end - 0.3:  # a cut right under the hook would cut the opener short
            line_anchor.append((snap(t, points), ln))
    big = None
    cands = [(i, ln) for i, ln in line_anchor if 0 < i < len(points) - 1]
    if cands:
        big = max(cands, key=lambda x: (len(" ".join(w[0] for w in x[1]["words"])), -x[0]))[0]
    mid = snap(story_end * 0.5, points) if len(points) > 2 else None
    if mid is not None and not (0 < mid < len(points) - 1):
        mid = None
    sig_idx = turn_idx if (before and turn_idx) else (big if big is not None else mid)
    if before and turn_idx is None and sig_idx is not None:
        turn_idx = sig_idx
    if turn_idx is not None:
        tense_end = points[turn_idx]
    else:
        first_end = float(lines[0]["end"]) if lines else 0.0
        tense_end = min(0.3 * story_end, max(0.15 * story_end, first_end))

    anchors = sorted({0, len(points) - 1, *(i for i, _ in line_anchor),
                      *([sig_idx] if sig_idx is not None else []), *([turn_idx] if turn_idx is not None else [])})
    cut_idx = fill(points, anchors, tense_end)
    times = [points[i] for i in cut_idx] + montage_pts[1:] + ([end_t] if end_t is not None else []) + [D]
    times = [r3(t) for t in times]
    dedup = [times[0]]
    for t in times[1:]:
        if t - dedup[-1] > 1e-6:
            dedup.append(t)
    times = dedup
    n_shots = len(times) - 1
    sig_t = r3(points[sig_idx]) if sig_idx is not None else None
    turn_t = r3(points[turn_idx]) if turn_idx is not None else None
    endcard_i = n_shots - 1 if end_t is not None else None
    montage_set = {i for i in range(n_shots) if montage_start is not None and times[i] >= montage_start - 1e-6
                   and i != endcard_i}

    # who goes where
    ranked = sorted(range(len(media)), key=lambda i: (-media[i].score, i))
    opener_i = next((i for i in ranked if not media[i].logo), ranked[0])
    rest = [m for i, m in enumerate(media) if i != opener_i] + [media[opener_i]]
    best = [media[i] for i in ranked if not media[i].logo] or media
    assign: list[Media] = []
    k = 0
    m_k = 0
    for i in range(n_shots):
        if i == endcard_i:
            assign.append(None)  # type: ignore[arg-type]
        elif i == 0:
            assign.append(media[opener_i])
        elif i in montage_set:
            assign.append(best[m_k % len(best)])
            m_k += 1
        else:
            m = rest[k % len(rest)]
            if assign and assign[-1] is m and len(rest) > 1:
                k += 1
                m = rest[k % len(rest)]
            assign.append(m)
            k += 1
    wipe_i = None
    if before and sig_t is not None:
        wipe_i = times.index(sig_t)
        if wipe_i >= 1:
            assign[wipe_i - 1] = by_id[before]
            assign[wipe_i] = by_id[after]
        else:
            wipe_i = None

    flash_i = None if wipe_i is not None else (times.index(sig_t) if sig_t in times and times.index(sig_t) > 0 else None)
    max_whips = prefs.get("max_whips")
    clip_cursor: dict[str, float] = {}
    shots = []
    last_whip = -99
    whips = 0
    zoom_dir = 0
    for i in range(n_shots):
        t0, t1 = times[i], times[i + 1]
        if i == endcard_i:
            shots.append({"src": str(nc.brand_asset("endcard_background")), "look": "none", "t0": t0, "t1": t1,
                          "z": [1.0, 1.08], "pan": [0, 0], "tr": "flash"})
            continue
        m = assign[i]
        if i == 0:
            tr = "cut"
        elif i == wipe_i:
            tr = "wipe"
        elif i == flash_i:
            tr = "flash"
        elif i - last_whip >= 3 and i % 3 == 0 and (max_whips is None or whips < max_whips) \
                and i + 1 != wipe_i and i + 1 != flash_i:
            tr = "whip"
        elif i in montage_set:
            tr = "punch" if i % 2 else "cut"
        else:
            short = (t1 - t0) < 1.0 or (times[i] - times[i - 1]) < 1.0
            tr = ["punch", "leakfade", "punch", "cut"][i % 4]
            if tr == "leakfade" and short:
                tr = "punch"
        if tr == "whip":
            last_whip, whips = i, whips + 1
        if turn_t is not None:
            look = "before" if t1 <= turn_t + 1e-6 else "warm"
        else:
            look = "warm"
        if i == 0:
            z = [1.0, 1.12]
        elif zoom_dir % 2 == 0:
            z = [1.02, 1.14] if i not in montage_set else [1.04, 1.16]
        else:
            z = [1.14, 1.02] if i not in montage_set else [1.16, 1.04]
        zoom_dir += 1
        pan = [0, 0]
        if m.size and m.size[0] > m.size[1] * 1.05:
            pan = [0.06 if i % 2 == 0 else -0.06, 0]
        shot: dict[str, Any] = {}
        if m.kind == "video":
            shot["kind"] = "video"
        shot["src"] = m.src
        if m.kind == "video":
            span = t1 - t0
            dur = m.duration
            start = clip_cursor.get(m.src, m.window if m.window is not None else max(0.0, dur / 2 - span / 2))
            speed = 1.0
            if dur <= span + 0.05:
                start = 0.0
                speed = max(0.05, math.floor(dur * 0.97 / span * 1000) / 1000)
            elif start + span > dur - 0.05:
                start = max(0.0, dur - span - 0.05)
            shot["start"] = r3(start)
            if speed != 1.0:
                shot["speed"] = speed
            nxt = start + span * speed
            clip_cursor[m.src] = nxt if nxt + 1.0 < dur else (m.window or 0.0)
        shot.update({"look": look, "t0": t0, "t1": t1, "z": z, "pan": pan, "tr": tr})
        if m.focus:
            shot["focus"] = list(m.focus)
        if m.faces:
            shot["faces"] = [list(b) for b in m.faces]
        shots.append(shot)

    plan: dict[str, Any] = {
        "schema_version": nc.PLAN_SCHEMA_VERSION,
        "duration": D,
        "out_dir": str(work),
        "fps": fps,
        "size": list(_cfg("render.size", [1080, 1920])),
        "quality": "final",
        "seed": int(seed),
        "accent_rgb": nc.accent_rgb(),
        "caption_y": float(_cfg("render.captions.default_y", 1420)),
        "font_regular": str(nc.brand_font("regular")),
        "font_italic": str(nc.brand_font("italic")),
    }
    hook_text = hook.strip() if hook and hook.strip() else (" ".join(w[0] for w in lines[0]["words"]) if lines else None)
    if hook_text:
        plan["hook"] = {"text": hook_text, "t1": r3(min(D, max(float(_cfg("render.hook.min_visible_s", 1.5)), 2.0)))}
    plan["shots"] = shots
    plan["lines"] = lines

    leaks = []
    if sig_t is not None:
        leaks.append([sig_t, r3(min(1.0, D - sig_t)), 0.35])
    if end_t is not None:
        leaks.append([r3(end_t), r3(min(1.4, D - end_t)), 0.4])
    if isinstance(prefs.get("max_leaks"), (int, float)):
        leaks = leaks[: int(prefs["max_leaks"])]
    plan["leaks"] = leaks
    if end_t is not None:
        plan["endcard"] = {
            "t": r3(end_t),
            "logo": str(nc.brand_asset("wordmark")),
            "tagline": nc.brand_value("endcard.tagline") or "",
            "subtitle": (subtitle or nc.brand_value("endcard.default_subtitle") or "").strip(),
        }
        for k in ("tagline", "subtitle"):
            if not plan["endcard"][k]:
                del plan["endcard"][k]
    if sig_t is not None and (wipe_i is not None or flash_i is not None):
        plan["signature"] = {"type": "wipe" if wipe_i is not None else "flash", "t": sig_t}

    audio = A.get("audio") or {}
    if audio.get("generated_pad") and audio.get("music"):
        plan["music"] = {"source": "pad", "path": audio["music"], "license": None,
                         "title": "Offline generated pad (last resort)"}
    elif audio.get("music"):
        plan["music"] = {"source": "folder", "path": audio["music"], "license": "Supplied by NUMA in the reel folder",
                         "title": None}
    elif audio.get("combined") and audio.get("master"):
        plan["music"] = {"source": "folder", "path": audio["master"], "license": "Supplied by NUMA in the reel folder",
                         "title": None}
    else:
        plan["music"] = {"source": "natural", "path": None, "license": None, "title": None}
    plan["ai"] = {"people": False, "scenes": False, "label_required": False}
    job_name = work.parent.name if work.name == "work" else work.name
    plan["meta"] = {"slug": nc.slugify(job_name)}
    formats = make_formats(plan, lines, sig_t, story_end, grid, hook_text)
    if formats:
        plan["formats"] = formats
    return plan


def make_formats(plan: dict, lines: list[dict], sig_t: float | None, story_end: float, grid: list[float],
                 hook_text: str | None) -> dict:
    D = plan["duration"]
    out: dict[str, Any] = {}
    texts = [" ".join(w[0] for w in ln["words"]) for ln in lines]
    longest = max(texts, key=len) if texts else None
    centre = sig_t if sig_t is not None else story_end / 2
    lo, hi = _cfg("render.length_s.reach_cut", [8, 12])
    reach_hook = hook_text or longest
    if story_end >= lo and reach_hook:
        pts = [0.0] + [g for g in grid if g <= story_end]
        t0 = max([p for p in pts if p <= max(0.0, centre - 3.0)] or [0.0])
        target = t0 + 10.0
        ends = [p for p in pts + [story_end] if lo <= p - t0 <= hi]
        if not ends:
            t0 = max(0.0, story_end - 10.0)
            ends = [p for p in pts + [story_end] if lo <= p - t0 <= hi] or [min(story_end, t0 + 10.0)]
        t1 = min(ends, key=lambda p: (abs(p - target), p))
        if lo - 1e-6 <= t1 - t0 <= hi + 1e-6:
            out["reach_cut"] = {"t0": r3(t0), "t1": r3(t1), "hook": reach_hook}
    if len(lines) >= 3:
        n = min(5, len(lines))
        pick = sorted({round(i * (len(lines) - 1) / (n - 1)) for i in range(n)})
        out["story"] = [{"t": r3((float(lines[i]["words"][0][1]) + float(lines[i]["end"])) / 2), "text": texts[i]}
                        for i in pick]
    if len(lines) >= 5:
        n = min(8, len(lines))
        pick = sorted({round(i * (len(lines) - 1) / (n - 1)) for i in range(n)})
        out["carousel"] = [{"t": r3((float(lines[i]["words"][-1][1]) + float(lines[i]["end"])) / 2), "text": texts[i]}
                           for i in pick]
    title = hook_text or longest
    if title:
        t = min(D, (sig_t + 0.5) if sig_t is not None else (plan["shots"][0]["t1"] / 2))
        out["cover"] = {"t": r3(t), "title": title}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="baseline_plan.py", description="Build a valid, beat-synced v2 plan.json from analysis.json.")
    ap.add_argument("work", metavar="WORK_DIR")
    ap.add_argument("--duration", type=float, metavar="S", help="target length (capped by the audio and 60 s)")
    ap.add_argument("--hook", metavar="TEXT", help="hook text on screen from frame 0 (default: the first caption line)")
    ap.add_argument("--subtitle", metavar="TEXT", help="gold end-card sign-off (default: brand.json)")
    ap.add_argument("--seed", type=int, default=0, metavar="N", help="plan seed (grain and leak motion)")
    ap.add_argument("--prefs", metavar="FILE", help="preference limits, e.g. {\"max_whips\": 1}")
    ap.add_argument("--out", metavar="FILE", help="output plan (default WORK_DIR/plan.json)")
    ap.add_argument("--script", metavar="FILE", help="voiceover script (one sentence per line) for music-only reels")
    ap.add_argument("--before", metavar="ID", help="before shot id (P3, C0, ...) for the before/after wipe")
    ap.add_argument("--after", metavar="ID", help="after shot id for the before/after wipe")
    ap.add_argument("--turn", type=float, metavar="S", help="turning point: 'before' look and 2-beat cuts up to here")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.duration is not None and args.duration <= 0:
        raise nc.UsageError("--duration must be positive")
    if args.seed < 0:
        raise nc.UsageError("--seed must be 0 or more")

    work = Path(args.work).expanduser().resolve()
    if not work.is_dir():
        raise nc.UserError(f"work folder not found: {work}")
    apath = work / "analysis.json"
    A = nc.read_json(apath, "analysis")
    nc.validate_against("analysis", A, what=str(apath))
    prefs = validate_plan.load_prefs(args.prefs) if args.prefs else {}
    script = None
    if args.script:
        sp = Path(args.script).expanduser().resolve()
        if not sp.is_file():
            raise nc.UserError(f"script file not found: {sp}")
        script = sp.read_text(encoding="utf-8", errors="replace")
        if A.get("words"):
            nc.info("script given but the analysis has a transcript: captions follow the voice")

    plan = build_plan(work, A, duration=args.duration, hook=args.hook, subtitle=args.subtitle, seed=args.seed,
                      prefs=prefs, script=script, before=args.before, after=args.after, turn=args.turn)
    errs = nc.schema_errors("plan", plan)
    if errs:
        raise nc.UserError("built plan does not match plan.schema.json: " + "; ".join(errs[:5]))
    out = Path(args.out).expanduser().resolve() if args.out else work / "plan.json"
    nc.write_json(out, plan)
    issues = validate_plan.validate(plan, A, prefs, out)
    for i in issues:
        nc.warn(f"plan check: {i.level} {i.line()}")
    n_err = sum(1 for i in issues if i.level == "ERROR")
    print(f"{out}: {len(plan['shots'])} shots, {len(plan['lines'])} caption lines, {plan['duration']:g} s"
          + (f", {n_err} validation error(s) to fix" if n_err else ""))
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
