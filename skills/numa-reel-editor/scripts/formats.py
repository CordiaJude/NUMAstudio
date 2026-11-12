#!/usr/bin/env python3
"""One reel, many outputs: render the plan's extra formats from the same plan (spec p.30, p.46, p.48).

    formats.py PLAN_JSON REEL_MP4 [--out DIR] [--slug SLUG]
               [--only reach,story,carousel,cover,srt,hooks] [--draft] [--json]

Every picture comes from the render engine and the same plan (crops happen in
the engine, never with Higgsfield Reframe); every sound comes from the finished
reel's own audio (REEL_MP4, else WORK/master.wav), cut to the matching time
and brought back to -15 LUFS. Outputs in DIR (default: the reel's folder):

* ``<slug>_reach.mp4``  reach cut-down: plan time [t0, t1] (8-12 s) as a derived
  plan (shots clipped and re-tiled, captions shifted, the new hook text from
  frame 0, the end card when it falls inside the window, else a short end-card
  tail when the window leaves room), muxed with the matching audio slice
  (short fades, loudness to spec), checked with check_output --kind reach.
* ``<slug>_story_<N>.jpg`` 3-5 vertical stills (or ``.mp4`` 5 s clips when the
  entry has ``clip: true``), one line of text each, inside the safe areas.
* ``<slug>_carousel_<N>.jpg`` 5-8 slides rendered by the engine at 1080x1350
  (4:5, never cropped from the 9:16 frame), a short caption each; from a reel
  time ``t`` or a source photo ``src``.
* ``<slug>_cover.jpg`` 1080x1920 cover with the title inside the centre square
  (y 420-1500) so it reads in the profile grid.
* ``<slug>.srt`` one cue per caption line (start = first word's appear time,
  end = the line's end), UTF-8; music-only plans fall back to analysis.json words.
* ``<slug>_hook_<N>.mp4`` 2-3 alternate openings (about 4 s, a shot boundary in
  3-5 s when there is one), each with new hook text or a different first shot.

Missing ``formats`` entries get defaults derived from the plan (captions,
shots, peak shot, title, hook); a plan entry is used as given. Output sizes are
relative to the plan's size (1080 wide -> 1080x1920 and 1080x1350); ``--draft``
renders at the draft scale with the draft encoder. Each derived plan passes
the plan schema and validate_plan's rules (claims, safe area, tiling, files)
before it is rendered. Re-running replaces this script's earlier files of the
same kind. Writes the ``formats`` section of DIR/report.json (sections of other
kinds from earlier runs are kept) and each video's ``check_output`` result.
Exit 1 when an input is unusable or a video fails its output check.
"""
from __future__ import annotations

import copy
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import engine  # noqa: E402
import engine_media as em  # noqa: E402
import engine_text as et  # noqa: E402
import check_output  # noqa: E402
import finish  # noqa: E402
import validate_plan  # noqa: E402

KINDS = ("reach", "story", "carousel", "cover", "srt", "hooks")
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
EPS = 1e-6

STILL_MIN_T = 0.6                     # stills: a caption needs ~0.3 s to fade in; stay off frame 0
STILL_END_GUARD = engine.FADE_OUT_S + 0.1   # and off the reel's closing fade
TEXT_LEAD_S = 0.6                     # a still's text appears this long before its frame (fully faded in)
ENDCARD_TAIL_MIN_S = 2.0              # an appended end card needs ~2 s for the logo and subtitle to land
ENDCARD_TAIL_PREF_S = 3.0
HOOK_VARIANT_S = (3.0, 5.0, 4.0)      # opening length: min, max, preferred
STORY_CLIP_DEFAULT_S = 5.0
SHORT_CAPTION_CHARS = 48              # carousel captions are short
SRT_ROW_CHARS = 42                    # standard subtitle row width
AUDIO_FADE_IN_S = 0.08
AUDIO_JOIN_FADE_S = 0.12
LOUDNESS_PASSES = 6
LOUDNESS_SETTLE_LU = 0.3
FRAMING_KEYS = ("kind", "start", "speed", "look", "z", "pan", "crop", "blur", "focus", "faces",
                "people", "consent", "ai_generated")
# validate_plan rules that do not apply to a derived output: music record (the sound is the
# finished reel's), the main reel's length/size, end-card hold, beat/rhythm advice
DERIVED_IGNORED_ERRORS = {29}
STILL_IGNORED_ERRORS = {29, 40}       # a still has no "movement from frame 1"
DERIVED_SHOWN_WARNINGS = {12, 22, 25, 26, 27}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def r3(x: float) -> float:
    return round(float(x) + 0.0, 3)


def r6(x: float) -> float:
    return round(float(x) + 0.0, 6)


def even(x: float) -> int:
    return max(16, int(round(x / 2.0)) * 2)


def plain(text: str) -> str:
    """Display text without gold markup, single-spaced."""
    return " ".join(str(text).replace("*", "").split())


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", plain(text).lower()).strip()


def line_text(ln: dict) -> str:
    return " ".join(str(w[0]) for w in ln["words"])


def output_cfg(kind: str) -> dict:
    for o in nc.config_value("formats.outputs", []) or []:
        if isinstance(o, dict) and o.get("id") == kind:
            return o
    return {}


def plan_size(plan: dict) -> tuple[int, int]:
    w, h = plan.get("size") or nc.config_value("render.size", [1080, 1920])
    return int(w), int(h)


def carousel_size(plan: dict) -> tuple[int, int]:
    """1080x1350 for a 1080-wide plan; scales with the plan's width."""
    cw, ch = output_cfg("carousel").get("size") or [1080, 1350]
    pw, _ = plan_size(plan)
    return even(pw), even(pw * ch / cw)


def cover_box(plan: dict) -> tuple[float, float]:
    """Title band (top, bottom) in plan pixels: y 420-1500 of 1920, the centre 1080x1080 square."""
    box = output_cfg("cover").get("title_box") or [0, 420, 1080, 1500]
    _, ph = plan_size(plan)
    ref_h = (output_cfg("cover").get("size") or [1080, 1920])[1]
    return box[1] * ph / ref_h, box[3] * ph / ref_h


def sorted_shots(plan: dict) -> list[dict]:
    return sorted(plan["shots"], key=lambda s: float(s["t0"]))


def content_end(plan: dict) -> float:
    ec = plan.get("endcard")
    D = float(plan["duration"])
    if isinstance(ec, dict) and 0 < float(ec["t"]) < D:
        return float(ec["t"])
    return D


def shot_at(plan: dict, t: float) -> dict:
    shots = sorted_shots(plan)
    cur = shots[0]
    for s in shots:
        if float(s["t0"]) <= t + EPS:
            cur = s
    return cur


def still_time(plan: dict, t: float) -> float:
    D = float(plan["duration"])
    hi = max(0.0, D - STILL_END_GUARD)
    return r3(min(max(float(t), min(STILL_MIN_T, hi)), hi))


def shorten(text: str, limit: int = SHORT_CAPTION_CHARS) -> str:
    """A short caption: the first clause that fits, else whole words cut with an ellipsis."""
    t = plain(text)
    if len(t) <= limit:
        return t
    for part in re.split(r"(?<=[,;:.!?])\s+|\s+[-–—]\s+", t):
        p = part.strip().rstrip(",;:-–—").strip()
        if 3 <= len(p) <= limit:
            return p
    out = ""
    for w in t.split():
        if len(out) + len(w) + 2 > limit:
            break
        out = f"{out} {w}".strip()
    return (out.rstrip(",;:") + "…") if out else t[:limit]


def text_words(text: str, appear: float, step: float = 0.01) -> list[list]:
    """Plan caption words for display text ('*gold*' markup, else the last word gold)."""
    words = et.hook_words(text)
    if not words:
        raise nc.UserError(f"text {text!r} has no words")
    return [[w, r6(appear + k * step), 1] if g else [w, r6(appear + k * step)] for k, (w, g) in enumerate(words)]


def media_kind(path: str) -> str:
    return "video" if Path(path).suffix.lower() in VIDEO_EXT else "image"


def framing_of(plan: dict, src: str) -> dict | None:
    """Framing and safety fields of the first plan shot showing src (blur, consent ... carry over)."""
    for s in sorted_shots(plan):
        if s["src"] == src:
            return {k: copy.deepcopy(s[k]) for k in FRAMING_KEYS if k in s}
    return None


# ---------------------------------------------------------------------------
# Derived plans
# ---------------------------------------------------------------------------
def _base(plan: dict) -> dict:
    """The plan minus everything a derived output sets itself."""
    d = copy.deepcopy(plan)
    for k in ("formats", "nat", "signature", "hook", "endcard"):
        d.pop(k, None)
    d["lines"] = []
    return d


def _clip_shot(s: dict, lo: float, hi: float, a: float) -> dict:
    """Shot s cut to reel time [lo, hi] and moved to start at lo - a; zoom/pan keep their path."""
    d = copy.deepcopy(s)
    s0, s1 = float(s["t0"]), float(s["t1"])
    L = max(EPS, s1 - s0)
    pa, pb = (lo - s0) / L, (hi - s0) / L
    if pa > EPS or pb < 1 - EPS:
        z = s.get("z", [1.02, 1.14])
        ea, eb = em.motion_ease(pa), em.motion_ease(pb)
        d["z"] = [round(z[0] + (z[1] - z[0]) * ea, 4), round(z[0] + (z[1] - z[0]) * eb, 4)]
        if s.get("pan"):
            d["pan"] = [round(p * (eb - ea), 4) for p in s["pan"]]
        if s.get("kind") == "video":
            d["start"] = r6(float(s.get("start", 0.0)) + (lo - s0) * float(s.get("speed", 1.0)))
    d["t0"], d["t1"] = r6(lo - a), r6(hi - a)
    return d


def clip_plan(plan: dict, a: float, b: float, *, keep_endcard: bool = True, keep_lines: bool = True) -> dict:
    """The plan's time window [a, b] as a plan of its own (duration b - a)."""
    a, b = float(a), float(b)
    fps = float(plan.get("fps") or 30)
    out = _base(plan)
    shots = []
    for s in sorted_shots(plan):
        lo, hi = max(float(s["t0"]), a), min(float(s["t1"]), b)
        if hi - lo > EPS:
            shots.append(_clip_shot(s, lo, hi, a))
    if not shots:
        raise nc.UserError(f"no shots in the window {a:g}-{b:g} s")
    sliver = 1.5 / fps
    if len(shots) > 1 and shots[0]["t1"] - shots[0]["t0"] < sliver:   # a frame-long remnant: let the next shot start
        gone = shots.pop(0)
        dt = shots[0]["t0"] - gone["t0"]
        if shots[0].get("kind") == "video":
            shots[0]["start"] = r6(max(0.0, float(shots[0].get("start", 0.0)) - dt * float(shots[0].get("speed", 1.0))))
        shots[0]["t0"] = 0.0
    if len(shots) > 1 and shots[-1]["t1"] - shots[-1]["t0"] < sliver:
        gone = shots.pop()
        shots[-1]["t1"] = gone["t1"]
    shots[0]["t0"] = 0.0
    shots[0]["tr"] = "cut"
    shots[-1]["t1"] = r6(b - a)
    out["shots"] = shots
    out["duration"] = r6(b - a)
    if keep_lines:
        lines = []
        for ln in plan.get("lines") or []:
            words = [w for w in ln["words"] if a - EPS <= float(w[1]) < b - 0.05]
            if not words:
                continue
            nw = [[w[0], r6(max(0.0, float(w[1]) - a)), *w[2:]] for w in words]
            end = min(float(ln["end"]), b) - a
            end = max(end, nw[-1][1])
            lines.append({"words": nw, "end": r6(min(end, b - a))})
        out["lines"] = lines
    leaks = []
    for t, d, k in plan.get("leaks") or []:
        lo, hi = max(float(t), a), min(float(t) + float(d), b)
        if hi - lo > 0.05:
            leaks.append([r6(lo - a), r6(hi - lo), k])
    out["leaks"] = leaks
    ec = plan.get("endcard")
    if keep_endcard and isinstance(ec, dict) and a < float(ec["t"]) < b - 0.05:
        out["endcard"] = dict(copy.deepcopy(ec), t=r6(float(ec["t"]) - a))
    return out


def add_endcard_tail(plan: dict, derived: dict, tail: float) -> dict:
    """Append the reel's end card (over the shot it plays on) as a tail of `tail` seconds."""
    ec = plan["endcard"]
    t_ec = float(ec["t"])
    s = shot_at(plan, t_ec)
    lo, hi = t_ec, min(float(s["t1"]), t_ec + tail)
    sh = _clip_shot(s, lo, max(hi, lo + 0.1), lo)
    dur = float(derived["duration"])
    sh["t0"], sh["t1"] = r6(dur), r6(dur + tail)
    sh["tr"] = "fade"
    derived["shots"].append(sh)
    derived["endcard"] = dict(copy.deepcopy(ec), t=r6(dur))
    derived["duration"] = r6(dur + tail)
    return derived


def hook_for(plan: dict, text: str, duration: float) -> dict:
    """Frame-zero hook text in the reel's hook style, at least 1.5 s, inside the derived duration."""
    src = plan.get("hook") or {}
    t1 = float(src.get("t1", 2.0))
    t1 = max(1.5, min(t1, duration - 0.3))
    h = {"text": text, "t1": r3(min(t1, duration))}
    if "y" in src:
        h["y"] = src["y"]
    return h


def reach_plan(plan: dict, rc: dict) -> tuple[dict, list[tuple[float, float]]]:
    """Derived reach plan and the reel-audio segments that play under it."""
    a, b = float(rc["t0"]), float(rc["t1"])
    lo, hi = nc.config_value("render.length_s.reach_cut", [8, 12])
    d = clip_plan(plan, a, b)
    segments = [(a, b)]
    ec = plan.get("endcard")
    if isinstance(ec, dict) and "endcard" not in d and b <= float(ec["t"]) + 0.05:
        room = hi - (b - a)
        tail = min(ENDCARD_TAIL_PREF_S, room, float(plan["duration"]) - float(ec["t"]))
        if tail >= ENDCARD_TAIL_MIN_S - EPS:
            tail = r3(tail)
            d = add_endcard_tail(plan, d, tail)
            segments.append((float(ec["t"]), float(ec["t"]) + tail))
    d["hook"] = hook_for(plan, rc["hook"], float(d["duration"]))
    return d, segments


def opening_length(plan: dict) -> float:
    """Hook-variant length: the shot boundary in 3-5 s nearest 4 s, else 4 s (never past the content)."""
    lo, hi, pref = HOOK_VARIANT_S
    ce = content_end(plan)
    cands = [float(s["t1"]) for s in sorted_shots(plan) if lo - EPS <= float(s["t1"]) <= min(hi, ce) + EPS]
    if cands:
        return r6(min(cands, key=lambda x: (abs(x - pref), x)))
    return r6(min(pref, ce if ce >= lo else float(plan["duration"])))


def hook_variant_plan(plan: dict, hv: dict, length: float) -> dict:
    d = clip_plan(plan, 0.0, length)
    if hv.get("src"):
        src = hv["src"]
        first = d["shots"][0]
        for k in FRAMING_KEYS:
            first.pop(k, None)
        fr = framing_of(plan, src)
        if fr:
            first.update(fr)
        first["kind"] = media_kind(src)
        first["src"] = src
        if first["kind"] == "video":
            first["start"] = r6(float(hv.get("start", fr.get("start", 0.0) if fr else 0.0)))
        else:
            first.pop("start", None)
            first.pop("speed", None)
        first["tr"] = "cut"
    d["hook"] = hook_for(plan, hv["text"], float(d["duration"]))
    return d


def still_plan(plan: dict, t: float, text: str | None) -> dict:
    """The reel at time t without its hook, captions and end card, plus one line of text."""
    d = _base(plan)
    if text:
        D = float(plan["duration"])
        n = len(et.hook_words(text))
        appear = max(0.0, t - TEXT_LEAD_S - 0.01 * n)
        d["lines"] = [{"words": text_words(text, appear), "end": r6(min(D, t + 0.5))}]
    return d


def source_still_plan(plan: dict, src: str, text: str | None) -> tuple[dict, float]:
    """A one-shot plan showing a source photo (or clip) for a carousel slide; returns (plan, frame time)."""
    d = _base(plan)
    dur = 2.0
    shot = {"src": src, "kind": media_kind(src), "t0": 0.0, "t1": dur, "tr": "cut", "z": [1.0, 1.06]}
    fr = framing_of(plan, src)
    if fr:
        fr.pop("kind", None)
        shot.update(fr)
        shot["t0"], shot["t1"], shot["tr"] = 0.0, dur, "cut"
    d["shots"] = [shot]
    d["duration"] = dur
    d["leaks"] = []
    t = 1.0
    if text:
        n = len(et.hook_words(text))
        d["lines"] = [{"words": text_words(text, t - TEXT_LEAD_S - 0.01 * n), "end": r6(t + 0.5)}]
    return d, t


def cover_plan(plan: dict, title: str) -> dict:
    """The reel without captions or end card, the title as hook text centred in the plan frame."""
    d = _base(plan)
    _, ph = plan_size(plan)
    d["hook"] = {"text": title, "t1": r3(float(plan["duration"])), "y": r3(ph / 2)}
    return d


def story_clip_plan(plan: dict, t: float, text: str, length: float) -> dict:
    d = clip_plan(plan, t, t + length, keep_endcard=False, keep_lines=False)
    n = len(et.hook_words(text))
    d["lines"] = [{"words": text_words(text, 0.0, 0.01), "end": r6(max(0.01 * n, length - 0.5))}]
    return d


# ---------------------------------------------------------------------------
# Defaults for missing formats entries
# ---------------------------------------------------------------------------
def _lines(plan: dict) -> list[dict]:
    return [ln for ln in plan.get("lines") or [] if ln.get("words")]


def _text_pool(plan: dict) -> list[str]:
    """Fallback texts in order of preference, distinct."""
    pool = []
    hook = (plan.get("hook") or {}).get("text")
    title = (plan.get("meta") or {}).get("title")
    ec = plan.get("endcard") if isinstance(plan.get("endcard"), dict) else {}
    for t in (hook, title, *(line_text(ln) for ln in _lines(plan)), ec.get("subtitle"),
              nc.brand_value("endcard.default_subtitle", None), ec.get("tagline"),
              nc.brand_value("endcard.tagline", None)):
        if t and norm(t) and norm(t) not in {norm(p) for p in pool}:
            pool.append(str(t))
    return pool


def _content_shots(plan: dict) -> list[dict]:
    ce = content_end(plan)
    return [s for s in sorted_shots(plan) if float(s["t0"]) < ce - 0.05]


def _mid(s: dict, ce: float) -> float:
    t0, t1 = float(s["t0"]), min(float(s["t1"]), ce)
    return t0 + 0.55 * (t1 - t0)


def default_reach(plan: dict) -> dict:
    lo, hi = nc.config_value("render.length_s.reach_cut", [8, 12])
    D = float(plan["duration"])
    if D < lo - EPS:
        raise nc.UserError(f"the reel is {D:g} s long; a reach cut needs at least {lo:g} s")
    ce = content_end(plan)
    has_ec = isinstance(plan.get("endcard"), dict) and ce < D
    target = hi - ENDCARD_TAIL_PREF_S if has_ec else (lo + hi) / 2
    target = max(lo, target)
    lines = _lines(plan)
    spans = [(float(ln["words"][0][1]), float(ln["end"])) for ln in lines]
    peaks = [(float(s["t0"]), float(s["t1"])) for s in sorted_shots(plan) if s.get("peak")]
    starts = sorted({0.0} | {float(s["t0"]) for s in sorted_shots(plan) if float(s["t0"]) <= ce - lo + EPS}
                    | {round(f, 6) for f, _ in spans if f <= ce - lo + EPS})
    ends = sorted({float(s["t1"]) for s in sorted_shots(plan)} | {round(e + 0.3, 6) for _, e in spans} | {ce})
    best = None
    for a in starts:
        cands = [e for e in ends if lo - EPS <= e - a <= hi + EPS and e <= ce + EPS] + \
                [x for x in (a + target,) if x <= ce + EPS]
        for b in cands:
            score = 0.0
            for f, e in spans:
                if a - EPS <= f and e <= b + 0.3 + EPS:
                    score += 1.0
                elif f < b and e > a:
                    score -= 2.0
            if any(a - EPS <= f <= a + 0.6 for f, _ in spans):
                score += 0.5
            score += 0.5 * sum(1 for p0, p1 in peaks if p0 < b and p1 > a)
            score -= 0.15 * abs((b - a) - target)
            key = (-round(score, 6), a, b)
            if best is None or key < best[0]:
                best = (key, a, b)
    if best is None:  # the content alone is shorter than a reach cut: take the opening through the end card
        a, b = 0.0, min(D, float(hi))
    else:
        _, a, b = best
    hook_text = plan.get("hook", {}).get("text") if isinstance(plan.get("hook"), dict) else None
    new = None
    title = (plan.get("meta") or {}).get("title")
    if title and norm(title) != norm(hook_text or ""):
        new = title
    else:
        for (f, e), ln in zip(spans, lines):
            if a - EPS <= f and e <= b + EPS and norm(line_text(ln)) != norm(hook_text or ""):
                new = line_text(ln)
                break
    new = new or hook_text or (_text_pool(plan) or [None])[0]
    if not new:
        raise nc.UserError("no text for the reach cut's hook: add formats.reach_cut.hook, a hook or meta.title")
    return {"t0": r3(a), "t1": r3(b), "hook": new}


def default_story(plan: dict) -> list[dict]:
    ce = content_end(plan)
    lines = [ln for ln in _lines(plan) if float(ln["words"][0][1]) < ce]
    n = 3 if len(lines) <= 4 else 4 if len(lines) <= 8 else 5
    out: list[dict] = []
    used: set[str] = set()
    if lines:
        k = min(n, len(lines))
        picks = sorted({round(i * (len(lines) - 1) / max(1, k - 1)) for i in range(k)})
        for i in picks:
            ln = lines[i]
            t = min(float(ln["words"][-1][1]) + 0.35, float(ln["end"]), ce - 0.2)
            out.append({"t": still_time(plan, t), "text": line_text(ln)})
            used.add(norm(line_text(ln)))
    shots = _content_shots(plan)
    pool = [t for t in _text_pool(plan) if norm(t) not in used]
    j = 0
    while len(out) < n and pool:
        s = shots[(len(out) * max(1, len(shots) // n) + j) % len(shots)]
        t = still_time(plan, _mid(s, ce))
        out.append({"t": t, "text": pool.pop(0)})
        j += 1
    if len(out) < 3:
        raise nc.UserError("not enough text for a story set (3 lines needed): add formats.story or captions")
    return sorted(out, key=lambda e: e["t"])


def default_carousel(plan: dict) -> list[dict]:
    ce = content_end(plan)
    shots = _content_shots(plan)
    times: list[float] = []
    for s in shots:
        times.append(still_time(plan, _mid(s, ce)))
    if len(shots) < 5:   # few shots: more frames from the longest ones
        for s in sorted(shots, key=lambda s: -(min(float(s["t1"]), ce) - float(s["t0"]))):
            t0, t1 = float(s["t0"]), min(float(s["t1"]), ce)
            for f in (0.2, 0.85):
                if len(times) >= 5:
                    break
                times.append(still_time(plan, t0 + f * (t1 - t0)))
    times = sorted(set(times))
    if len(times) > 8:
        times = [times[round(i * (len(times) - 1) / 7)] for i in range(8)]
    lines = _lines(plan)
    hook = (plan.get("hook") or {}).get("text") or (plan.get("meta") or {}).get("title")
    used_lines: set[int] = set()
    used: set[str] = set()
    pool = _text_pool(plan)
    out = []
    for k, t in enumerate(times):
        text = None
        if k == 0 and hook:
            text = hook
        else:
            on = [i for i, ln in enumerate(lines) if float(ln["words"][0][1]) - 0.3 <= t <= float(ln["end"]) + 0.3]
            near = sorted(range(len(lines)),
                          key=lambda i: (abs((float(lines[i]["words"][0][1]) + float(lines[i]["end"])) / 2 - t), i))
            for i in on + near:
                cand = shorten(line_text(lines[i]))
                if i not in used_lines and norm(cand) not in used:
                    text = cand
                    used_lines.add(i)
                    break
            if text is None:
                text = next((shorten(p) for p in pool if norm(shorten(p)) not in used), None)
        if text is None or norm(text) in used:
            continue
        used.add(norm(text))
        out.append({"t": t, "text": text})
    if len(out) < 5:
        raise nc.UserError("not enough shots or text for a 5-slide carousel: add formats.carousel")
    return out


def default_cover(plan: dict) -> dict:
    ce = content_end(plan)
    shots = _content_shots(plan)
    s = next((s for s in shots if s.get("peak")), shots[0])
    title = (plan.get("meta") or {}).get("title") or (plan.get("hook") or {}).get("text") \
        or (_text_pool(plan) or [None])[0]
    if not title:
        raise nc.UserError("no cover title: add formats.cover.title, meta.title or a hook")
    return {"t": still_time(plan, _mid(s, ce)), "title": title}


def default_hook_variants(plan: dict, have: list[dict]) -> list[dict]:
    """Fill hook variants up to config formats.hook_variants.count (new text or a new first shot)."""
    lo_n, hi_n = nc.config_value("formats.hook_variants.count", [2, 3])
    want = hi_n if not have else max(lo_n, len(have))
    hook = (plan.get("hook") or {}).get("text")
    title = (plan.get("meta") or {}).get("title")
    shots = _content_shots(plan)
    first = sorted_shots(plan)[0]
    others = [s for s in shots if s["src"] != first["src"]]
    alt = next((s for s in others if s.get("peak")), others[0] if others else None)
    lines = _lines(plan)
    cands: list[dict] = []
    if title:
        cands.append({"text": title})
    if alt is not None and hook:
        c = {"text": hook, "src": alt["src"]}
        if alt.get("kind") == "video":
            c["start"] = float(alt.get("start", 0.0))
        cands.append(c)
    # whole sentences first (a caption line can be half a sentence), in reel order
    ranked = sorted(lines, key=lambda ln: (line_text(ln).rstrip()[-1:] not in ".?!", len(line_text(ln)) > 60))
    for ln in ranked[:3]:
        cands.append({"text": line_text(ln)})
    if alt is not None:
        for ln in ranked[:2]:
            c = {"text": line_text(ln), "src": alt["src"]}
            if alt.get("kind") == "video":
                c["start"] = float(alt.get("start", 0.0))
            cands.append(c)
    seen = {(norm(hook or ""), first["src"])} | {(norm(h["text"]), h.get("src", first["src"])) for h in have}
    out = list(have)
    for c in cands:
        if len(out) >= want:
            break
        key = (norm(c["text"]), c.get("src", first["src"]))
        if key in seen or not norm(c["text"]):
            continue
        seen.add(key)
        out.append(c)
    return out


def resolve_formats(plan: dict, kinds: set[str], warnings: list[str]) -> tuple[dict, list[str]]:
    """The formats to render: the plan's entries, defaults for missing ones. Returns (formats, defaulted)."""
    fm = copy.deepcopy(plan.get("formats") or {})
    defaulted = []
    if "reach" in kinds and "reach_cut" not in fm:
        fm["reach_cut"] = default_reach(plan)
        defaulted.append("reach_cut")
    if "story" in kinds and "story" not in fm:
        fm["story"] = default_story(plan)
        defaulted.append("story")
    if "carousel" in kinds and "carousel" not in fm:
        fm["carousel"] = default_carousel(plan)
        defaulted.append("carousel")
    if "cover" in kinds and "cover" not in fm:
        fm["cover"] = default_cover(plan)
        defaulted.append("cover")
    if "hooks" in kinds:
        have = fm.get("hook_variants") or []
        full = default_hook_variants(plan, have)
        if len(full) != len(have):
            defaulted.append("hook_variants")
        fm["hook_variants"] = full
        if len(full) < 2:
            warnings.append(f"hook variants: only {len(full)} distinct opening(s) could be made from this plan "
                            f"(add formats.hook_variants, meta.title or more shots)")
    rc = fm.get("reach_cut")
    hook = (plan.get("hook") or {}).get("text")
    if "reach" in kinds and rc and hook and norm(rc["hook"]) == norm(hook):
        warnings.append("formats.reach_cut.hook is the reel's own hook; a reach cut should open on new hook text")
    return fm, defaulted


def check_formats(plan: dict, fm: dict) -> None:
    """Schema + validate_plan rules on the formats actually rendered (rule 36 times, rule 27 claims)."""
    probe = copy.deepcopy(plan)
    probe["formats"] = {k: v for k, v in fm.items() if v not in (None, [], {})}
    errors = []
    for line in nc.schema_errors("plan", probe):
        if line.startswith("formats"):
            errors.append(line)
    for i in validate_plan.validate(probe):
        if i.level == "ERROR" and (i.rule == 36 or (i.rule in (4, 5, 27) and i.where.startswith("formats"))):
            errors.append(i.line())
        elif i.level == "WARN" and i.rule == 27 and i.where.startswith("formats"):
            nc.warn(i.line())
    if errors:
        raise nc.UserError("formats: " + "; ".join(errors[:4]) + (f" (+{len(errors) - 4} more)" if len(errors) > 4 else ""))


def check_derived(d: dict, what: str, warnings: list[str], still: bool = False) -> dict:
    """Schema (via the engine) + validate_plan rules for a derived plan; returns the prepared plan."""
    ignored = STILL_IGNORED_ERRORS if still else DERIVED_IGNORED_ERRORS
    issues = validate_plan.validate(d)
    errs = [i for i in issues if i.level == "ERROR" and i.rule not in ignored]
    if errs:
        more = f" (+{len(errs) - 3} more)" if len(errs) > 3 else ""
        raise nc.UserError(f"{what}: " + "; ".join(i.line() for i in errs[:3]) + more)
    for i in issues:
        if i.level == "WARN" and i.rule in DERIVED_SHOWN_WARNINGS:
            msg = f"{what}: {i.line()}"
            if msg not in warnings:
                warnings.append(msg)
    return engine.prepare_plan(d, d.get("out_dir"))


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------
def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_rows(text: str, width: int = SRT_ROW_CHARS) -> list[str]:
    """One row, or two balanced rows when longer than a subtitle row."""
    words = text.split()
    if len(text) <= width or len(words) < 2:
        return [text]
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        key = (max(len(a), len(b)), abs(len(a) - len(b)))
        if best is None or key < best[0]:
            best = (key, [a, b])
    return best[1]


def srt_cues(plan: dict, analysis: dict | None) -> list[tuple[float, float, str]]:
    """(start, end, text) per caption line; analysis words grouped into sentences when the plan has none."""
    cues: list[tuple[float, float, str]] = []
    for ln in _lines(plan):
        cues.append((float(ln["words"][0][1]), float(ln["end"]), plain(line_text(ln))))
    if not cues and analysis:
        group: list[dict] = []
        words = [w for w in analysis.get("words") or [] if isinstance(w, dict) and str(w.get("w", "")).strip()]
        for k, w in enumerate(words):
            group.append(w)
            nxt = words[k + 1] if k + 1 < len(words) else None
            gap = (float(nxt["appear"]) - float(w["end"])) if nxt else 0.0
            if nxt is None or str(w["w"]).rstrip()[-1:] in ".?!" or len(group) >= 10 or gap > 0.8:
                cues.append((float(group[0]["appear"]), float(group[-1]["end"]),
                             plain(" ".join(str(x["w"]) for x in group))))
                group = []
    cues.sort(key=lambda c: c[0])
    out = []
    for k, (a, b, text) in enumerate(cues):
        if k + 1 < len(cues) and b > cues[k + 1][0]:
            b = cues[k + 1][0]          # players show one cue at a time
        b = max(b, a + 0.1)
        out.append((a, b, text))
    return out


def write_srt(path: Path, cues: list[tuple[float, float, str]]) -> Path:
    blocks = [f"{k}\n{srt_time(a)} --> {srt_time(b)}\n" + "\n".join(srt_rows(text)) + "\n"
              for k, (a, b, text) in enumerate(cues, 1)]
    tmp = path.with_name(f".{path.name}.partial")
    tmp.write_text("\n".join(blocks), encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    """Read cues back (used by tests and as a self-check)."""
    def sec(s: str) -> float:
        h, m, rest = s.strip().split(":")
        s_, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s_) + int(ms) / 1000
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = block.strip().splitlines()
        if len(rows) < 3 or not rows[0].strip().isdigit() or "-->" not in rows[1]:
            raise ValueError(f"bad SRT block: {block[:40]!r}")
        a, b = rows[1].split("-->")
        cues.append((sec(a), sec(b), " ".join(r.strip() for r in rows[2:])))
    return cues


# ---------------------------------------------------------------------------
# Audio: slices of the finished reel, back to the loudness spec
# ---------------------------------------------------------------------------
def audio_source(reel: Path, plan: dict, warnings: list[str]) -> Path:
    if reel.is_file():
        info = nc.media_info(reel)
        if info["has_audio"]:
            D = float(plan["duration"])
            if info["duration"] and abs(info["duration"] - D) > 0.25:
                warnings.append(f"{reel.name} is {info['duration']:.2f} s but the plan is {D:g} s; "
                                f"audio slices may not line up (re-run finish.py)")
            return reel
    master = Path(plan.get("out_dir") or reel.parent) / "master.wav"
    if master.is_file():
        warnings.append(f"{reel.name} has no audio (or is missing): using {master} for the sound")
        return master
    raise nc.UserError(f"no audio for the video formats: {reel} has no audio track and {master} is missing "
                       f"(run finish.py first)")


def build_slice(src: Path, segments: list[tuple[float, float]], duration: float, out_wav: Path) -> None:
    """Concatenate audio segments of src (short fades at the joins), fade in/out -> float WAV of `duration`."""
    sr = finish.SR
    fmt = f"aresample={sr},aformat=sample_fmts=fltp:channel_layouts=stereo"
    graph = []
    parts = []
    n = len(segments)
    for k, (a, b) in enumerate(segments):
        L = b - a
        fades = []
        if k > 0:
            fades.append(f"afade=t=in:d={min(AUDIO_JOIN_FADE_S, L / 4):.3f}")
        if k < n - 1:
            f = min(AUDIO_JOIN_FADE_S, L / 4)
            fades.append(f"afade=t=out:st={L - f:.4f}:d={f:.3f}")
        chain = ",".join([fmt, f"atrim=start={a:.4f}:end={b:.4f}", "asetpts=N/SR/TB", *fades])
        graph.append(f"[0:a]{chain}[s{k}]")
        parts.append(f"[s{k}]")
    d = f"{duration:.6f}"
    fade_out = min(engine.FADE_OUT_S, duration / 3)
    tail = (f"apad=whole_dur={d},atrim=end={d},asetpts=N/SR/TB,"
            f"afade=t=in:d={AUDIO_FADE_IN_S},afade=t=out:st={duration - fade_out:.4f}:d={fade_out:.3f}")
    if n == 1:
        graph[-1] = graph[-1][:-len("[s0]")] + "," + tail + "[out]"
    else:
        graph.append(f"{''.join(parts)}concat=n={n}:v=0:a=1,{tail}[out]")
    nc.ffmpeg("-i", str(src), "-filter_complex", ";".join(graph), "-map", "[out]", "-t", d,
              "-c:a", "pcm_f32le", "-ar", str(sr), "-ac", "2", "-fflags", "+bitexact", str(out_wav),
              what="ffmpeg audio slice")


def master_slice(pre: Path, duration: float, out_m4a: Path, tmp: Path, what: str,
                 warnings: list[str]) -> dict:
    """Linear gain + true-peak limiter to -15 LUFS (config), AAC 192k; returns the measured loudness."""
    cfg = nc.load_config()
    loud_cfg = nc.dig(cfg, "render.loudness", {}) or {}
    audio_cfg = nc.dig(cfg, "render.audio", {}) or {}
    target = {"i": float(loud_cfg.get("integrated_lufs", -15)), "tp": float(loud_cfg.get("true_peak_db", -1.5)),
              "lra": float(loud_cfg.get("lra", 9))}
    tol = float(loud_cfg.get("tolerance_lu", 1))
    m = finish.measure_pass(pre, target)
    in_i, in_tp = finish.to_float(m.get("input_i")), finish.to_float(m.get("input_tp"))
    aud = tmp / "slice_norm.wav"
    if in_tp is None or in_tp < finish.SILENT_PEAK_DB:
        warnings.append(f"{what}: the audio slice is silent")
        finish.normalize_pass(pre, None, target["tp"], aud, duration)
        finish.encode_audio(aud, out_m4a, duration, audio_cfg)
        return check_output.measure_audio(out_m4a)
    gain = target["i"] - in_i if in_i is not None else finish.QUIET_START_PEAK_DB - in_tp
    gain = max(-finish.MAX_GAIN_DB, min(finish.MAX_GAIN_DB, gain))
    ceiling = target["tp"] - finish.TP_HEADROOM_DB
    best: tuple[float, Path] | None = None
    loud: dict = {}
    for k in range(LOUDNESS_PASSES):
        finish.normalize_pass(pre, gain, ceiling, aud, duration)
        cand = tmp / f"slice_{k}.m4a"
        finish.encode_audio(aud, cand, duration, audio_cfg)
        loud = check_output.measure_audio(cand)
        i_now, tp_now = loud["integrated_lufs"], loud["true_peak_db"]
        if i_now is None or not math.isfinite(i_now):
            break
        tp_over = tp_now is not None and tp_now > target["tp"]
        if not tp_over and abs(i_now - target["i"]) <= tol and (best is None or abs(i_now - target["i"]) < best[0]):
            best = (abs(i_now - target["i"]), cand)
        if not tp_over and abs(i_now - target["i"]) <= LOUDNESS_SETTLE_LU:
            break
        if tp_over:
            ceiling = max(-24.0, ceiling - (tp_now - target["tp"]) - finish.TP_MARGIN_DB)
        gain = max(-finish.MAX_GAIN_DB, min(finish.MAX_GAIN_DB, gain + (target["i"] - i_now)))
    chosen = best[1] if best else cand
    shutil.copyfile(chosen, out_m4a)
    return check_output.measure_audio(out_m4a)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
class Job:
    """One formats run: plan, reel, output folder, options, and what it produced."""

    def __init__(self, plan: dict, plan_path: Path, reel: Path, out_dir: Path, slug: str, draft: bool,
                 workers: int | None = None, progress: bool = True):
        self.plan = plan
        self.plan_path = plan_path
        self.reel = reel
        self.out = out_dir
        self.slug = slug
        self.draft = draft
        self.workers = workers
        self.progress = progress
        self.files: dict[str, list[str]] = {}
        self.warnings: dict[str, list[str]] = {}
        self.checks: dict[str, dict] = {}
        self.failed: list[str] = []
        self._audio: Path | None = None

    def name(self, kind: str, n: int | None = None, ext: str | None = None) -> Path:
        return self.out / nc.deliverable_name(self.slug, kind, n, ext)

    def clear(self, kind: str, exts: tuple[str, ...]) -> None:
        """Remove this script's earlier outputs of one kind (a re-run may make fewer)."""
        stem = nc.slugify(self.slug)
        pat = {"story": r"_story_\d+", "carousel": r"_carousel_\d+", "hook": r"_hook_\d+"}[kind]
        rx = re.compile(rf"^{re.escape(stem)}{pat}\.({'|'.join(exts)})$")
        for p in self.out.iterdir():
            if p.is_file() and rx.match(p.name):
                p.unlink()

    def audio(self, warnings: list[str]) -> Path:
        if self._audio is None:
            self._audio = audio_source(self.reel, self.plan, warnings)
        return self._audio

    def video_size(self, size: tuple[int, int]) -> tuple[int, int]:
        return engine.output_size(self.plan, size, self.draft)

    def still(self, d: dict, t: float, size: tuple[int, int], path: Path) -> Path:
        with engine.Renderer(d, size=size, draft=self.draft, quiet=True) as r:
            rgb = r.frame(t)
        return engine.save_image(rgb, path, quality=92)

    def video(self, d: dict, segments: list[tuple[float, float]], kind: str, path: Path,
              warnings: list[str]) -> Path:
        """Render a derived plan, add the reel-audio slice, mux, check against the output spec."""
        size = plan_size(self.plan)
        with tempfile.TemporaryDirectory(prefix=".numa-formats-", dir=str(self.out)) as tmpd:
            tmp = Path(tmpd)
            silent = tmp / "video.mp4"
            info = engine.render_video(d, silent, size=size, draft=self.draft, workers=self.workers,
                                       progress=False)
            duration = float(info["duration"])
            pre = tmp / "slice.wav"
            build_slice(self.audio(warnings), segments, duration, pre)
            m4a = tmp / "audio.m4a"
            master_slice(pre, duration, m4a, tmp, path.name, warnings)
            finish.mux(silent, m4a, path, duration)
            plan_file = tmp / "plan.json"
            nc.write_json(plan_file, d)
            res = check_output.check_file(path, kind, tuple(info["size"]), plan_file)
        self.checks[path.name] = res
        for w in res["warnings"]:
            warnings.append(f"{path.name}: {w}")
        if not res["ok"]:
            self.failed += [f"{path.name}: {e}" for e in res["errors"]]
        return path

    def add(self, kind: str, path: Path) -> None:
        self.files.setdefault(kind, []).append(str(path))
        if self.progress:
            nc.info(f"formats: wrote {path.name}")


def render_reach(job: Job, fm: dict) -> None:
    w = job.warnings.setdefault("reach", [])
    rc = fm["reach_cut"]
    d, segments = reach_plan(job.plan, rc)
    d = check_derived(d, "reach cut", w)
    out = job.name("reach")
    job.video(d, segments, "reach", out, w)
    job.add("reach", out)


def render_story(job: Job, fm: dict) -> None:
    w = job.warnings.setdefault("story", [])
    job.clear("story", ("jpg", "mp4"))
    size = plan_size(job.plan)
    clip_s = float(output_cfg("story").get("clip_s", STORY_CLIP_DEFAULT_S))
    D = float(job.plan["duration"])
    for n, st in enumerate(fm["story"], 1):
        if st.get("clip"):
            length = min(clip_s, D)
            t = min(float(st["t"]), D - length)
            d = check_derived(story_clip_plan(job.plan, t, st["text"], length), f"story {n}", w)
            out = job.name("story", n, "mp4")
            job.video(d, [(t, t + length)], "story", out, w)
        else:
            t = still_time(job.plan, st["t"])
            d = check_derived(still_plan(job.plan, t, st["text"]), f"story {n}", w, still=True)
            out = job.still(d, t, size, job.name("story", n, "jpg"))
        job.add("story", out)


def render_carousel(job: Job, fm: dict) -> None:
    w = job.warnings.setdefault("carousel", [])
    job.clear("carousel", ("jpg",))
    size = carousel_size(job.plan)
    for n, c in enumerate(fm["carousel"], 1):
        if "src" in c:
            d, t = source_still_plan(job.plan, c["src"], c["text"])
        else:
            t = still_time(job.plan, c["t"])
            d = still_plan(job.plan, t, c["text"])
        if len(plain(c["text"])) > SHORT_CAPTION_CHARS + 12:
            w.append(f"carousel {n}: caption is {len(plain(c['text']))} characters; carousel captions read best short")
        d = check_derived(d, f"carousel {n}", w, still=True)
        job.add("carousel", job.still(d, t, size, job.name("carousel", n)))


def cover_title_band(plan: dict, title: str) -> tuple[float, float, bool]:
    """(top, bottom, fits) of the cover title block in plan pixels, laid out as the engine lays out a hook."""
    pw, ph = plan_size(plan)
    s = min(pw, ph) / 1080.0
    reg = plan.get("font_regular") or str(nc.brand_font("regular"))
    ita = plan.get("font_italic") or str(nc.brand_font("italic"))
    words = [(t, g, 0.0) for t, g in et.hook_words(title)]
    blk = et.layout_words(words, reg, ita, 100 * s, pw, 0.86 * pw, 3, ((255, 255, 255), (255, 255, 255)),
                          12 * s, 3 * s)
    top = ph / 2 - blk.height / 2
    return top, top + blk.height, blk.fit


def render_cover(job: Job, fm: dict) -> None:
    w = job.warnings.setdefault("cover", [])
    cv = fm["cover"]
    lo, hi = cover_box(job.plan)
    top, bottom, fits = cover_title_band(job.plan, cv["title"])
    if not fits or top < lo - 0.5 or bottom > hi + 0.5:
        raise nc.UserError(f"formats.cover.title: {plain(cv['title'])!r} is too long to stay inside the centre "
                           f"square (3 rows max); shorten it")
    t = still_time(job.plan, cv["t"])
    d = check_derived(cover_plan(job.plan, cv["title"]), "cover", w, still=True)
    out = job.still(d, t, plan_size(job.plan), job.name("cover"))
    job.add("cover", out)


def render_srt(job: Job) -> None:
    w = job.warnings.setdefault("srt", [])
    analysis = None
    for cand in (job.plan_path.parent / "analysis.json", Path(job.plan.get("out_dir", "")) / "analysis.json"):
        if cand.is_file():
            try:
                analysis = nc.read_json(cand, "analysis")
            except nc.UserError as e:
                w.append(f"srt: {e}")
            break
    cues = srt_cues(job.plan, analysis)
    out = job.name("srt")
    if not cues:
        if out.exists():
            out.unlink()
        w.append("srt: the plan has no caption lines and there is no transcript (music-only reel): no .srt written")
        return
    write_srt(out, cues)
    job.add("srt", out)


def render_hooks(job: Job, fm: dict) -> None:
    w = job.warnings.setdefault("hooks", [])
    job.clear("hook", ("mp4",))
    length = opening_length(job.plan)
    for n, hv in enumerate(fm["hook_variants"], 1):
        d = check_derived(hook_variant_plan(job.plan, hv, length), f"hook variant {n}", w)
        out = job.name("hook", n)
        job.video(d, [(0.0, length)], "hook", out, w)
        job.add("hooks", out)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def default_slug(plan: dict, plan_path: Path) -> str:
    meta_slug = (plan.get("meta") or {}).get("slug")
    if meta_slug:
        return meta_slug
    work = Path(plan.get("out_dir") or plan_path.parent)
    job = work.parent if work.name == "work" else work
    return nc.slugify(job.name) or "reel"


def parse_only(text: str | None) -> list[str]:
    if not text:
        return list(KINDS)
    kinds = [k.strip() for k in text.split(",") if k.strip()]
    bad = [k for k in kinds if k not in KINDS]
    if bad or not kinds:
        raise nc.UsageError(f"--only: unknown kind {', '.join(bad) or '(none)'}; use some of {','.join(KINDS)}")
    return [k for k in KINDS if k in kinds]


def run(plan_path: str | Path, reel: str | Path, out_dir: str | Path | None = None, slug: str | None = None,
        only: list[str] | None = None, draft: bool = False, workers: int | None = None,
        progress: bool = True) -> dict:
    """Render the formats; returns the report section (also written to OUT_DIR/report.json)."""
    plan_path = Path(plan_path).expanduser().resolve()
    reel = Path(reel).expanduser().resolve()
    plan = engine.load_plan(plan_path)
    out = Path(out_dir).expanduser().resolve() if out_dir else reel.parent
    out.mkdir(parents=True, exist_ok=True)
    kinds = list(only or KINDS)
    slug_ = nc.slugify(slug) if slug else default_slug(plan, plan_path)
    if not slug_:
        raise nc.UsageError("--slug: give a name with letters or digits")
    run_warn: list[str] = []
    fm, defaulted = resolve_formats(plan, set(kinds), run_warn)
    check_formats(plan, fm)
    job = Job(plan, plan_path, reel, out, slug_, draft, workers, progress)
    job.warnings["formats"] = run_warn
    if "reach" in kinds or "hooks" in kinds or ("story" in kinds and any(st.get("clip") for st in fm["story"])):
        job.audio(run_warn)   # fail before rendering anything when there is no sound to cut
    steps = {"reach": lambda: render_reach(job, fm), "story": lambda: render_story(job, fm),
             "carousel": lambda: render_carousel(job, fm), "cover": lambda: render_cover(job, fm),
             "srt": lambda: render_srt(job), "hooks": lambda: render_hooks(job, fm)}
    for k in kinds:
        if progress:
            nc.info(f"formats: {k} ...")
        steps[k]()
    for ws in job.warnings.values():
        for msg in ws:
            nc.warn(msg)
    return write_report(job, kinds, fm, defaulted)


def write_report(job: Job, kinds: list[str], fm: dict, defaulted: list[str]) -> dict:
    rp = job.out / "report.json"
    existing = nc.read_json(rp, "report") if rp.exists() else {}
    if not isinstance(existing, dict):
        raise nc.UserError(f"{rp} is not a JSON object")
    prev = existing.get("formats") if isinstance(existing.get("formats"), dict) else {}
    outputs = {k: v for k, v in (prev.get("outputs") or {}).items() if k not in kinds and isinstance(v, dict)}
    key_of = {"reach": "reach_cut", "story": "story", "carousel": "carousel", "cover": "cover",
              "hooks": "hook_variants", "srt": None}
    for k in kinds:
        spec_key = key_of[k]
        outputs[k] = {
            "files": job.files.get(k, []),
            "warnings": job.warnings.get(k, []),
            "spec": fm.get(spec_key) if spec_key else None,
            "defaulted": spec_key in defaulted if spec_key else False,
        }
    order = [k for k in KINDS if k in outputs]
    names_now = {Path(f).name for k in order for f in outputs[k]["files"]}
    checks = {n: r for n, r in (prev.get("checks") or {}).items() if n in names_now and n not in job.checks}
    checks.update({n: {"ok": r["ok"], "errors": r["errors"], "warnings": r["warnings"]} for n, r in job.checks.items()})
    section = {
        "files": [f for k in order for f in outputs[k]["files"]],
        "warnings": job.warnings.get("formats", []) + [m for k in order for m in outputs[k]["warnings"]],
        "outputs": {k: outputs[k] for k in order},
        "checks": checks,
        "slug": job.slug,
        "draft": job.draft,
        "ok": all(c["ok"] for c in checks.values()),
    }
    nc.update_report(job.out, "formats", section)
    if job.checks:
        existing = nc.read_json(rp, "report")
        co = dict(existing.get("check_output") or {})
        co.update(job.checks)
        nc.update_report(job.out, "check_output", co)
    section["errors"] = list(job.failed)
    return section


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="formats.py",
                      description="Render the reach cut, story set, carousel, cover, .srt and hook variants "
                                  "from the same plan.")
    ap.add_argument("plan", metavar="PLAN_JSON", help="the reel's plan.json")
    ap.add_argument("reel", metavar="REEL_MP4", help="the finished reel (its audio is cut for the video formats)")
    ap.add_argument("--out", metavar="DIR", help="output folder (default: the reel's folder)")
    ap.add_argument("--slug", help="file name stem (default: plan meta.slug, else the job folder name)")
    ap.add_argument("--only", metavar="KINDS", help=f"comma list of {','.join(KINDS)} (default: all)")
    ap.add_argument("--draft", action="store_true", help="draft size and encoder (quick look)")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    args = ap.parse_args(argv)
    only = parse_only(args.only)
    section = run(args.plan, args.reel, args.out, args.slug, only, args.draft, progress=not args.json)
    for e in section["errors"]:
        nc.error_line(e)
    if args.json:
        nc.print_json(section)
    else:
        for k, o in section["outputs"].items():
            if k in only:
                names = ", ".join(Path(f).name for f in o["files"]) or "none"
                print(f"{k}: {names}{' (defaults)' if o['defaulted'] else ''}")
        print(f"{'OK' if not section['errors'] else 'FAILED'}: {len(section['files'])} files in "
              f"{Path(section['files'][0]).parent if section['files'] else args.out or Path(args.reel).parent}")
    return 1 if section["errors"] else 0


if __name__ == "__main__":
    nc.run_cli(main)
