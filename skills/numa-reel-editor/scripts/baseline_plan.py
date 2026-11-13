#!/usr/bin/env python3
"""Build a valid, beat-synced schema_version 2 starting plan from analysis.json.

Usage:
    baseline_plan.py WORK_DIR [--duration S] [--hook TEXT] [--subtitle TEXT] [--seed N]
                     [--prefs FILE] [--out FILE] [--script FILE] [--before ID --after ID] [--turn S]
                     [--template NAME] [--library FILE]

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
  out, a pan across wide photos. Looks: the 'before' look only when the reel
  has a before/after arc (--turn, or --before/--after, whose wipe is the turn);
  shots up to the turn are 'before', the rest 'warm'. Without one, everything
  is warm: a voiceover reel with no before material should not look cold, and
  the tense section keeps only its 2-beat rhythm.
* The brand wordmark/phoenix in the material is left out (the end card carries
  the logo); photos with a logo in them never open the reel.
* Music from the folder gets its license from WORK/sources.json when sources.py
  recorded one, else null (validate_plan warns: NUMA's own file).
* End card on the last beats, held 3.5-5 s, over the bundled ripple image.
* Captions: one sentence per line (2 rows max), 1-2 gold key words per line.
  Music-only material with --script FILE (one sentence per line) gets the
  script as timed on-screen lines at about 2.3 words a second, on the beats.
* No photos or clips: the bundled brand photos are used.
* `formats` defaults: an 8-12 s reach cut around the signature moment, 3-5
  story stills, 5-8 carousel slides and a cover, when there is text for them.

* --template NAME (skills/numa-scriptwriter/templates.json, R194): the
  template's default length, arc, pacing (beats per shot, hook and outro
  seconds), turn, looks, signature position, transitions, hook style and, for
  kinetic-type templates, large text cards on their beats (plan `cards`, R195).
* --prefs (R278): every numeric feedback limit is applied where the material
  allows, so validate_plan rule 38 passes.
* Consent (rule 41): faces are shown only with recorded consent (analysis item
  `consent`, or --library); otherwise left out, or blurred when there is too
  little other material.

Duration = min(--duration, audio, 60 s). Deterministic: same inputs, same plan.
"""
from __future__ import annotations

import hashlib
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
MIN_LEN_S = 15.0              # config render.length_s.main_reel[0]: the shortest main reel
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
    consent: bool | None = None   # True: everyone recognizable is on the consent list; False: known not
    blur: list = field(default_factory=list)


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
def _sha1(path: str | Path) -> str | None:
    try:
        p = Path(path)
        return hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() and p.stat().st_size < 20_000_000 else None
    except OSError:
        return None


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001 - unreadable file: no size, no pan
        return None


def _consent_value(v: Any) -> bool | None:
    if v is True or (isinstance(v, str) and v.strip().lower() == "yes"):
        return True
    if v is False or (isinstance(v, str) and v.strip().lower() == "no"):
        return False
    return None


def _src_faces(item: dict) -> list:
    """Faces of the file used as the shot source (faces describe prepared_path when set; else orig_faces)."""
    return [list(b) for b in (item.get("faces") or item.get("orig_faces") or [])]


def library_consent(path: str | Path | None) -> dict[str, bool]:
    """{resolved path: consent} from a library.py index (consent yes/no); unknown entries are left out."""
    if not path:
        return {}
    data = nc.read_json(Path(path).expanduser().resolve(), "library index")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise nc.UserError(f"library index {path}: expected an object with an 'items' list")
    out: dict[str, bool] = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("path"), str):
            c = _consent_value(it.get("consent"))
            if c is not None:
                out[str(Path(it["path"]).expanduser().resolve())] = c
    return out


def collect_media(A: dict, library: dict[str, bool] | None = None) -> list[Media]:
    library = library or {}
    items: list[Media] = []
    sharp = [p.get("sharpness") for p in A.get("photos", []) + A.get("clips", []) if p.get("sharpness") is not None]
    top = max(sharp) if sharp else 0.0
    logos: set[str] = set()
    for key in ("wordmark", "secondary_mark", "wordmark_light"):
        try:
            logos.add(str(nc.brand_asset(key).resolve()))
        except nc.UserError:
            pass
    logo_hashes = {h for h in map(_sha1, logos) if h}

    def is_mark(path: str) -> bool:
        """The brand wordmark/phoenix itself (same file, same bytes, or named like it): never a shot."""
        stem = Path(path).stem.lower()
        return (str(Path(path).resolve()) in logos or _sha1(path) in logo_hashes
                or bool(re.search(r"(word|work)[ _-]?mark|phoenix", stem)))

    def is_logo(path: str) -> bool:
        """A photo with the logo in it (e.g. sauna-logo.jpg): fine in the body, never the opener."""
        return "logo" in Path(path).stem.lower()

    def consent_of(item: dict) -> bool | None:
        c = _consent_value(item.get("consent"))
        if c is None:
            for key in ("path", "orig_path", "prepared_path"):
                if item.get(key) and str(Path(item[key]).resolve()) in library:
                    return library[str(Path(item[key]).resolve())]
        return c

    for p in A.get("photos", []):
        src = p.get("prepared_path") or p["path"]
        s = (p.get("sharpness") or 0.0) / top if top else 0.0
        s += 0.15 * min(1.0, len(p.get("faces") or []))
        items.append(Media(p["id"], "image", src, tuple(p["size"]) if p.get("size") else None, s,
                           faces=_src_faces(p), focus=p.get("focus"), logo=is_logo(src), consent=consent_of(p)))
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
                           faces=_src_faces(c), focus=c.get("focus"), logo=is_logo(src), consent=consent_of(c)))
    if not any(p.get("sharpness") is not None or p.get("windows") or p.get("faces")
               for p in A.get("photos", []) + A.get("clips", [])):
        for m in items:  # no analysis scores: folder order decides
            m.score = 0.0
    items = [m for m in items if m.kind == "image" or m.duration > 0.1]
    marks = [m for m in items if is_mark(m.src)]
    for m in marks:
        nc.warn(f"{m.id} {Path(m.src).name} is the brand logo: left out (the end card carries the logo)")
    items = [m for m in items if m not in marks]
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
    """Counts caption rows the way the engine wraps them (92 px font, or the caption_px pref, 960 px box).

    Also carries the caption preferences: max_chars per line and max_gold words per line."""

    def __init__(self, px: float | None = None, max_chars: int = 70, max_gold: int = 2) -> None:
        from PIL import ImageFont
        px = int(round(px or _cfg("render.captions.font_px", 92)))
        self.max_chars, self.max_gold = max_chars, max_gold
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


def pick_gold(words: list[str], max_gold: int = 2) -> set[int]:
    """1-2 key words: the longest content words (later wins ties); 2 for lines of 6+ words."""
    cand = [(len(_clean(w)), i) for i, w in enumerate(words) if _clean(w) not in STOP and len(_clean(w)) >= 4]
    if not cand:
        cand = [(len(_clean(w)), i) for i, w in enumerate(words) if _clean(w)]
    if not cand:
        return set()
    cand.sort(key=lambda x: (-x[0], -x[1]))
    n = min(max_gold, 2 if len(words) >= 6 and len(cand) >= 2 else 1)
    return {i for _, i in cand[:max(0, n)]}


def split_sentences(words: list[dict], meter: RowMeter, max_chars: int | None = None) -> list[list[dict]]:
    """Words -> lines: one sentence per line, split at pauses, then at commas/midpoints to stay within 2 rows."""
    max_chars = meter.max_chars if max_chars is None else max_chars
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


def make_line(group: list[dict], end: float, max_gold: int = 2) -> dict:
    texts = [x["w"] for x in group]
    gold = pick_gold(texts, max_gold)
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
        lines.append(make_line(g, max(end, last), meter.max_gold))
    return lines


def lines_from_script(script: str, grid: list[float], body_end: float, meter: RowMeter,
                      spread_to: float | None = None) -> list[dict]:
    """R92: script sentences as timed on-screen lines, starting on beats, ~2.3 words a second.

    spread_to (template reels): the lines start evenly across 0.3 s..spread_to (one per story beat) instead
    of back to back, each held until shortly before the next."""
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
    hold = 0.0
    if spread_to is not None and lay and lay[-1][2] < spread_to - 0.2:
        spread: list[tuple[list[str], float, float]] = []
        prev_end = 0.0
        for j, (g, _, _) in enumerate(lay):
            t = max(on_beat(0.3 + j * (spread_to - 0.3) / len(lay)), prev_end + 0.1)
            prev_end = t + (len(g) - 1) / rate + 0.8
            spread.append((g, t, prev_end))
        if spread[-1][2] <= body_end - 0.2:
            lay, hold = spread, 2.0
    lines = []
    for j, (g, t, end) in enumerate(lay):
        nxt = lay[j + 1][1] if j + 1 < len(lay) else body_end
        if hold:
            end = max(end, min(end + hold, nxt - 0.1))
        group = [{"w": w, "appear": t + i / rate} for i, w in enumerate(g)]
        lines.append(make_line(group, min(end, nxt), meter.max_gold))
    return lines


def script_length(script: str, A: dict, meter: RowMeter) -> float:
    """Music-only reel length for a --script without --duration: the script's caption timing (~2.3 words
    a second, lines starting on beats) plus the music-only outro (config render.outro_music_only_s.default,
    with the 3.5-5 s end card inside it, REQUIREMENTS interpretation 5), at most the audio (and 60 s), at
    least 15 s."""
    audio_d = float(A.get("duration") or 0.0)
    cap = min(audio_d, MAX_LEN_S) if audio_d > 0 else MAX_LEN_S
    grid, _ = beat_grid(A, 4 * MAX_LEN_S)
    lines = lines_from_script(script, grid, 4 * MAX_LEN_S, meter)
    if not lines:
        return cap if audio_d > 0 else DEFAULT_NO_AUDIO_S
    spoken = float(lines[-1]["end"])
    outro = float(_cfg("render.outro_music_only_s.default", 7.5))
    lo = float((_cfg("render.length_s.main_reel", [MIN_LEN_S, MAX_LEN_S]) or [MIN_LEN_S])[0])
    return min(cap, max(lo, spoken + outro))


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
def snap(t: float, points: list[float]) -> int:
    return min(range(len(points)), key=lambda i: (abs(points[i] - t), i))


def merge_anchors(anchors: list[int], fixed: set[int], min_gap: int = 2) -> list[int]:
    """Drop optional anchors (caption-line starts) less than `min_gap` beats from a kept one."""
    kept: list[int] = []
    for a in sorted(set(anchors)):
        if kept and a - kept[-1] < min_gap:
            if a in fixed and kept[-1] not in fixed:
                kept[-1] = a  # a fixed anchor (start, signature, turn, end) wins over a line start
                if len(kept) > 1 and kept[-1] - kept[-2] < min_gap and kept[-2] not in fixed:
                    del kept[-2]
            elif a in fixed:
                kept.append(a)  # two fixed anchors: keep both
            continue
        kept.append(a)
    return kept


def pieces(g: int, step: int, lo: int = 2, hi: int = 4, strict_lo: bool = False) -> list[int]:
    """Split a gap of g beats into shots. Default pacing (2-4 beats): 2-beat (step 2) or 4-beat pieces, an odd
    gap gets one 3-beat (or 1-beat) piece. Other pacing (a template's beats_per_shot, shot-length prefs):
    pieces of about `step` beats, each within lo..hi where the gap allows."""
    if (lo, hi) != (2, 4) or strict_lo:
        if g <= max(lo, 1) or g <= step:
            return [g]
        n = max(1, round(g / step))
        while g / n > hi:
            n += 1
        while n > 1 and g / n < lo and (strict_lo or g / (n - 1) <= hi):
            n -= 1
        base, rem = divmod(g, n)
        return [base + 1] * rem + [base] * (n - rem)
    if g <= 2:
        return [g]
    out: list[int] = []
    odd = 3 if g % 2 else 0
    rest = g - odd
    if step == 2:
        out = [2] * (rest // 2)
    else:
        out = [4] * (rest // 4) + ([2] if rest % 4 else [])
    if odd:
        out.append(odd)
    return out


def fill(points: list[float], anchors: list[int], tense_end: float, lo: int = 2, hi: int = 4,
         calm: int | None = None, strict_lo: bool = False) -> list[int]:
    """Cut indices into `points`: anchors kept, gaps filled with short (tense, `lo` beats) or long (`calm`,
    default `hi`) pieces, every piece within lo..hi beats where the gap allows."""
    cuts = [anchors[0]]
    for a, b in zip(anchors, anchors[1:]):
        step = lo if points[a] < tense_end - 1e-6 else (calm or hi)
        idx = a
        for n in pieces(b - a, step, lo, hi, strict_lo):
            idx += n
            cuts.append(idx)
    return cuts


# ---------------------------------------------------------------------------
# Templates (skills/numa-scriptwriter/templates.json, R194)
# ---------------------------------------------------------------------------
TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "numa-scriptwriter" / "templates.json"


def load_template(name: str, path: Path | None = None) -> dict:
    """A template or preset from the scriptwriter's library by id; UserError listing the valid ids otherwise."""
    p = path or TEMPLATES_PATH
    data = nc.read_json(p, "template library")
    entries = [t for key in ("templates", "presets") for t in (data.get(key) or []) if isinstance(t, dict)]
    for t in entries:
        if t.get("id") == name:
            return t
    ids = ", ".join(sorted(str(t.get("id")) for t in entries))
    raise nc.UserError(f"unknown template {name!r}; valid templates: {ids}")


DETERMINERS = {"a", "an", "the", "your", "our", "my", "their", "his", "her", "its", "this", "that", "these", "those"}


def shorten(text: str, n: int) -> str:
    """At most n words: the first clause when it fits, else the first words without a dangling stop word."""
    words = text.replace("*", "").split()
    if len(words) <= n:
        return " ".join(words)
    clause = re.split(r"[,;:\u2014]|\s-\s", " ".join(words))[0].split()
    if 2 <= len(clause) <= n:
        return " ".join(clause).rstrip(".,;:!?") + "."
    lean = [w for w in words if _clean(w) not in DETERMINERS]   # "before your first plunge" -> "before first plunge"
    if 2 <= len(lean) <= n:
        return " ".join(lean)
    cut = words[:n]
    while len(cut) > 1 and _clean(cut[-1]) in STOP:
        cut.pop()
    return " ".join(cut).rstrip(".,;:!?") + "."


CARD_MAX_WORDS = 12   # validate_plan rule 42: a statement card holds at most 12 words


CARD_OVER_WORDS = 2   # a whole first clause may run this many words over max_words (with a WARN)


def _clause_text(words: list[str]) -> str:
    return " ".join(words).rstrip(",;:\u2014").rstrip() + ("" if words[-1][-1:] in ".!?" else ".")


def card_text(text: str, n: int) -> str:
    """Statement-card text within n words: the whole line when it fits, else the first whole clause that
    fits; only when no clause fits, the first clause up to CARD_OVER_WORDS over n (WARN); clipped words
    as a last resort."""
    words = text.replace("*", "").split()
    if len(words) <= n:
        return " ".join(words)
    clauses = [c.split() for c in re.split(r"(?<=[,;:.!?\u2014])\s+|\s-\s", " ".join(words)) if c.strip()]
    for c in clauses:
        if 2 <= len(c) <= n:
            return _clause_text(c)
    first = clauses[0] if clauses else words
    if 2 <= len(first) <= min(n + CARD_OVER_WORDS, CARD_MAX_WORDS):
        short = _clause_text(first)
        nc.warn(f"text card: no clause of \"{' '.join(words)}\" fits {n} words; the card shows its first "
                f"clause, {len(first)} words: \"{short}\"")
        return short
    return shorten(text, n)


def card_statement(text: str, max_words: int) -> str:
    """A spoken line as statement-card text: shortened at a clause, its key word marked gold."""
    short = card_text(text, max_words)
    words = short.split()
    gold = pick_gold(words, 1)
    return " ".join(f"*{w}*" if i in gold else w for i, w in enumerate(words))


def beat_windows(arc: list[dict], lines: list[dict], voiced: float) -> list[tuple[str, float, float, dict | None]]:
    """(beat, start, end, first line) for each spoken beat of the arc (the music-only outro is left out).

    One spoken line per beat; extra lines go to the beats in order; beats without a line split the
    remaining voiced time evenly."""
    names = [b.get("beat") for b in arc if b.get("beat") != "outro"]
    nb = len(names)
    if nb == 0:
        return []
    owner: dict[int, list[dict]] = {}
    if lines:
        for j, ln in enumerate(lines):
            k = min(nb - 1, j * nb // len(lines)) if len(lines) >= nb else j
            owner.setdefault(k, []).append(ln)
    known = {k: float(v[0]["words"][0][1]) for k, v in owner.items()}
    starts: list[float] = []
    for k in range(nb):
        if k == 0:
            starts.append(0.0)
        elif k in known:
            starts.append(max(known[k], starts[-1]))
        else:  # no line of its own: an even share of the time up to the next beat that has one
            nk = next((j for j in range(k + 1, nb) if j in known), None)
            nxt_t, nxt_i = (known[nk], nk) if nk is not None else (voiced, nb)
            starts.append(starts[-1] + max(0.0, nxt_t - starts[-1]) / (nxt_i - (k - 1)))
    out = []
    for k in range(nb):
        end = starts[k + 1] if k + 1 < nb else voiced
        out.append((names[k], r3(starts[k]), r3(max(end, starts[k])), owner[k][0] if k in owner else None))
    return out


TAIL_S = 4.6   # from the last spoken word to the reel end: a short pause and the 3.5-5 s end card


def sentence_safe_length(words: list[dict], D: float, T: dict, audio_d: float) -> tuple[float, float | None]:
    """A template's default length must not cut the voice mid-sentence: end after the next sentence when that
    stays inside typical_length_s (and the audio), else after the last whole sentence. Returns (length, the last
    spoken word end to caption, or None when nothing changes)."""
    ends = [float(w["end"]) for w in words if str(w["w"]).rstrip("\"')\u201d\u2019").endswith((".", "!", "?"))]
    cut = D - TAIL_S
    said = [w for w in words if float(w["appear"]) < cut]
    if not said or not ends:
        return D, None
    last = float(said[-1]["end"])
    if any(abs(e - last) < 1e-6 for e in ends) or last >= max(ends):
        return D, None
    hi = min(float((T.get("typical_length_s") or [0, D])[1]), audio_d if audio_d > 0 else MAX_LEN_S, MAX_LEN_S)
    longer = [e for e in ends if e > last and e + TAIL_S <= hi + 1e-6]
    if longer:
        e = min(longer)
        nc.warn(f"template {T['id']}: {D:g} s would cut the voiceover mid-sentence; {e + TAIL_S:g} s ends "
                f"after the sentence")
        return e + TAIL_S, e
    shorter = [e for e in ends if e < last]
    if shorter:
        e = max(shorter)
        nc.warn(f"template {T['id']}: {D:g} s would cut the voiceover mid-sentence and the next sentence ends "
                f"past {hi:g} s; the reel ends after the last whole sentence ({e + TAIL_S:g} s)")
        return e + TAIL_S, e
    return D, None


def _num_pref(prefs: dict, key: str) -> float | None:
    v = prefs.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def face_blur(faces: list) -> list[list[float]]:
    """Blur boxes over face boxes, 15% bigger on every side, inside the frame."""
    out = []
    for x, y, w, h in faces:
        x0, y0 = max(0.0, x - 0.15 * w), max(0.0, y - 0.15 * h)
        x1, y1 = min(1.0, x + 1.15 * w), min(1.0, y + 1.15 * h)
        out.append([r3(x0), r3(y0), r3(x1 - x0), r3(y1 - y0)])
    return out


def consent_gate(media: list[Media]) -> list[Media]:
    """Rule 41: material with faces is used only with consent. Faces without known consent are left out when
    there is enough other material, else blurred."""
    risky = [m for m in media if m.faces and m.consent is not True]
    if not risky:
        return media
    safe = [m for m in media if m not in risky]
    if len(safe) >= 3:
        nc.warn(f"left out {len(risky)} photo(s)/clip(s) with faces and no recorded consent "
                f"({', '.join(m.id for m in risky)}); record consent to use them")
        return safe
    for m in risky:
        m.blur = face_blur(m.faces)
    nc.warn(f"faces without recorded consent are blurred in {', '.join(m.id for m in risky)} "
            f"(not enough other material); record consent to show them")
    return media


def build_plan(work: Path, A: dict, *, duration: float | None = None, hook: str | None = None,
               subtitle: str | None = None, seed: int = 0, prefs: dict | None = None,
               script: str | None = None, before: str | None = None, after: str | None = None,
               turn: float | None = None, template: dict | None = None,
               library: dict[str, bool] | None = None) -> dict:
    prefs = prefs or {}
    T = template or {}
    pacing = T.get("pacing") or {}
    from_template = bool(T and duration is None and T.get("default_length_s"))
    if from_template:
        duration = float(T["default_length_s"])
    elif T and duration is not None and T.get("typical_length_s"):
        lo_t, hi_t = T["typical_length_s"]
        if not lo_t <= duration <= hi_t:
            nc.warn(f"--duration {duration:g} s is outside the {T['id']} template's typical {lo_t:g}-{hi_t:g} s")
    audio_d = float(A.get("duration") or 0.0)
    caption_px = _num_pref(prefs, "caption_px")
    max_chars = int(_num_pref(prefs, "max_caption_chars") or 70)
    max_gold = int(_num_pref(prefs, "max_gold_words") if _num_pref(prefs, "max_gold_words") is not None else 2)
    meter = RowMeter(caption_px, max_chars, max_gold)
    voiced_analysis = bool(A.get("voice_present", True) and A.get("words"))
    if duration is None and not from_template and script and not voiced_analysis:
        duration = script_length(script, A, meter)   # not the whole track: the script plus its outro
    if audio_d > 0:
        D = min(x for x in (duration, audio_d, MAX_LEN_S) if x)
    else:
        D = min(duration or DEFAULT_NO_AUDIO_S, MAX_LEN_S)
        nc.warn(f"analysis has no audio: building a {D:g} s plan without music")
    if _num_pref(prefs, "min_duration") is not None:
        D = max(D, min(_num_pref(prefs, "min_duration"), audio_d if audio_d > 0 else MAX_LEN_S, MAX_LEN_S))
    if _num_pref(prefs, "max_duration") is not None:
        D = min(D, _num_pref(prefs, "max_duration"))
    voice_limit = None
    if from_template and A.get("voice_present", True) and A.get("words"):
        D, voice_limit = sentence_safe_length(A["words"], D, T, audio_d)
    D = r3(D)
    if D <= 1.0:
        raise nc.UserError(f"reel length {D:g} s is too short to build a plan")
    fps = int(_cfg("render.fps", 30))
    grid, period = beat_grid(A, D)
    material = collect_media(A, library)
    by_id = {m.id: m for m in material}
    media = consent_gate(material)

    # shot lengths in beats: the template's pacing, then the shot-length preferences
    max_beats = int(_cfg("render.max_shot_beats", 4))
    lo_b, hi_b = (int(x) for x in (pacing.get("beats_per_shot") or [2, 4]))
    hi_b = max(1, min(hi_b, max_beats))
    lo_b = max(1, min(lo_b, hi_b))
    if _num_pref(prefs, "max_shot_seconds"):
        hi_b = max(1, min(hi_b, int(math.floor(_num_pref(prefs, "max_shot_seconds") / period + 1e-6))))
        lo_b = min(lo_b, hi_b)
    calm_b = hi_b
    if _num_pref(prefs, "min_shot_seconds"):
        lo_b = max(lo_b, int(math.ceil(_num_pref(prefs, "min_shot_seconds") / period - 1e-6)))
        calm_b = hi_b = max(hi_b, lo_b)

    # end card on the last beats, held 3.5-5 s
    lo, hi = float(_cfg("render.endcard.min_hold_s", 3.5)), float(_cfg("render.endcard.max_hold_s", 5.0))
    end_t: float | None = None
    if D >= lo + 1.5:
        cands = [g for g in grid if lo - 1e-6 <= D - g <= hi + 1e-6]
        end_t = min(cands, key=lambda g: (abs(D - 4.0 - g), g)) if cands else r3(D - 4.0)
    body_end = end_t if end_t is not None else D

    # captions
    voice_words = [w for w in A.get("words") or [] if A.get("voice_present", True)
                   and (voice_limit is None or float(w["end"]) <= voice_limit + 1e-6)]
    outro_s = float(pacing.get("outro_s") or 0.0)
    if voice_words:
        lines = lines_from_words(voice_words, body_end, D, meter)
    elif script:
        spread = None
        if T and outro_s:
            spread = max(0.5 * body_end, min(body_end, D - outro_s) - 2.5)
        lines = lines_from_script(script, grid, body_end, meter, spread_to=spread)
    else:
        lines = []

    # outro montage (music after the last word)
    body_pts = [g for g in grid if 0.3 <= g <= body_end - 0.3]
    montage_start = None
    montage_pts: list[float] = []
    stride = max(2, lo_b) if (lo_b, hi_b) != (2, 4) else 2
    stride = max(1, min(stride, hi_b))
    if voice_words and lines:
        last_word = max(float(w["end"]) for w in voice_words if float(w["appear"]) < body_end)
        tail = [g for g in body_pts if g >= last_word + 0.1]
        n = min(8, len(tail) // stride)
        if n >= 3:
            montage_pts = tail[len(tail) - stride * n::stride]
            montage_start = montage_pts[0]
    story_end = montage_start if montage_start is not None else body_end
    points = [0.0] + [g for g in body_pts if 0.3 <= g <= story_end - 0.3] + [story_end]

    # the voiced part and the template's story beats
    if voice_words:
        voiced = max(float(w["end"]) for w in voice_words if float(w["appear"]) < body_end)
    elif lines:
        voiced = max(float(lines[-1]["end"]), min(body_end, D - outro_s) if outro_s else 0.0)
    else:
        voiced = max(0.3 * D, D - outro_s) if outro_s else story_end
    voiced = min(voiced, story_end)
    windows = beat_windows(T.get("arc") or [], lines, voiced) if T else []
    win_by_beat = {w[0]: w for w in windows}
    if T and turn is None and isinstance(T.get("turn"), dict):
        turn = float(T["turn"]["at"]) * voiced
    card_specs = []
    if T.get("kinetic_type"):
        for spec in T.get("text_cards") or []:
            w = win_by_beat.get(spec.get("beat"))
            if w is None:
                nc.warn(f"template {T['id']}: text card beat {spec.get('beat')!r} has no place in this reel")
                continue
            card_specs.append((spec, w))

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
    card_anchor = [snap(w[1], points) for _, w in card_specs if w[1] > 0]
    card_anchor = [i for i in card_anchor if 0 < i < len(points) - 1]
    big = None
    cands = [(i, ln) for i, ln in line_anchor if 0 < i < len(points) - 1]
    if cands:
        big = max(cands, key=lambda x: (len(" ".join(w[0] for w in x[1]["words"])), -x[0]))[0]
    mid = snap(story_end * 0.5, points) if len(points) > 2 else None
    if mid is not None and not (0 < mid < len(points) - 1):
        mid = None
    tsig = None
    if isinstance(T.get("signature_moment"), dict) and len(points) > 2:
        target = float(T["signature_moment"]["at"]) * voiced
        near = [i for i in card_anchor if abs(points[i] - target) <= 1.5]
        tsig = min(near, key=lambda i: (abs(points[i] - target), i)) if near else snap(target, points)
        if not 0 < tsig < len(points) - 1:
            tsig = None
    sig_idx = turn_idx if (before and turn_idx) else (tsig if tsig is not None else (big if big is not None else mid))
    if before and turn_idx is None and sig_idx is not None:
        turn_idx = sig_idx
    if turn_idx is not None:
        tense_end = points[turn_idx]
    else:
        first_end = float(lines[0]["end"]) if lines else 0.0
        tense_end = min(0.3 * story_end, max(0.15 * story_end, first_end))

    fixed = {0, len(points) - 1, *([sig_idx] if sig_idx is not None else []),
             *([turn_idx] if turn_idx is not None else []), *card_anchor}
    anchors = sorted({*fixed, *(i for i, _ in line_anchor)})
    cut_idx = fill(points, merge_anchors(anchors, fixed, max(2, lo_b) if (lo_b, hi_b) != (2, 4) else 2),
                   tense_end, lo_b, hi_b, calm_b, strict_lo=bool(_num_pref(prefs, "min_shot_seconds")))
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
            for pick in (by_id[before], by_id[after]):
                if pick.faces and pick.consent is not True and not pick.blur:
                    pick.blur = face_blur(pick.faces)
                    nc.warn(f"--before/--after {pick.id} has faces and no recorded consent: its faces are blurred")
            assign[wipe_i - 1] = by_id[before]
            assign[wipe_i] = by_id[after]
        else:
            wipe_i = None
    min_people = _num_pref(prefs, "min_people_shots")
    if min_people:
        assign = more_people(assign, media, int(min_people), {0, endcard_i, wipe_i, (wipe_i or 0) - 1})

    max_flashes = _num_pref(prefs, "max_flashes")
    flash_i = None if wipe_i is not None else (times.index(sig_t) if sig_t in times and times.index(sig_t) > 0 else None)
    no_flash = flash_i is not None and max_flashes is not None and max_flashes < 1
    if no_flash:
        nc.warn("preference max_flashes = 0: the reel has no flash reveal (signature moment)")
        flash_i = None
    flashes = 1 if flash_i is not None else 0
    endcard_tr = "flash" if max_flashes is None or flashes < max_flashes else "fade"

    leaks = []
    if sig_t is not None and not no_flash:
        leaks.append([sig_t, r3(min(1.0, D - sig_t)), 0.35])
    if end_t is not None:
        leaks.append([r3(end_t), r3(min(1.4, D - end_t)), 0.4])
    max_leaks = _num_pref(prefs, "max_leaks")
    if max_leaks is not None:
        leaks = leaks[: int(max_leaks)]
    max_strength = _num_pref(prefs, "max_leak_strength")
    if max_strength is not None:
        leaks = [[t, d, r3(min(a, max_strength))] for t, d, a in leaks]
    leakfade_budget = None if max_leaks is None else max(0, int(max_leaks) - len(leaks))
    if max_strength is not None and max_strength < 0.55:  # engine's automatic leakfade leak strength
        leakfade_budget = 0

    allowed = list(T.get("transitions") or [])
    rotation = [t for t in allowed if t not in ("wipe", "flash", "whip")] or (["cut"] if T else [])
    whip_ok = not T or "whip" in allowed
    plain = next((t for t in rotation if t in ("cut", "punch")), "cut")

    max_whips = prefs.get("max_whips")
    clip_cursor: dict[str, float] = {}
    shots = []
    last_whip = -99
    whips = 0
    zoom_dir = 0
    look_default = (T.get("look") or {}).get("default") or "warm"
    look_before = (T.get("look") or {}).get("before_turn") if T else "before"
    for i in range(n_shots):
        t0, t1 = times[i], times[i + 1]
        if i == endcard_i:
            shots.append({"src": str(nc.brand_asset("endcard_background")), "look": "none", "t0": t0, "t1": t1,
                          "z": [1.0, 1.08], "pan": [0, 0], "tr": endcard_tr})
            continue
        m = assign[i]
        short = (t1 - t0) < 1.0 or (i > 0 and (times[i] - times[i - 1]) < 1.0)
        if i == 0:
            tr = "cut"
        elif i == wipe_i:
            tr = "wipe"
        elif i == flash_i:
            tr = "flash"
        elif whip_ok and i - last_whip >= 3 and i % 3 == 0 and (max_whips is None or whips < max_whips) \
                and i + 1 != wipe_i and i + 1 != flash_i:
            tr = "whip"
        elif i in montage_set:
            if T:
                tr = rotation[i % len(rotation)]
            else:
                tr = "punch" if i % 2 else "cut"
        elif T:
            tr = rotation[i % len(rotation)]
        else:
            tr = ["punch", "leakfade", "punch", "cut"][i % 4]
        if tr in ("leakfade", "fade") and short:
            tr = "punch" if (not T or "punch" in allowed) else plain
        if tr == "leakfade" and leakfade_budget is not None:
            if leakfade_budget > 0:
                leakfade_budget -= 1
            else:
                tr = "fade" if (not T or "fade" in allowed) else plain
        if tr == "whip":
            last_whip, whips = i, whips + 1
        if T:
            look = (look_before or look_default) if turn_t is not None and t1 <= turn_t + 1e-6 else look_default
        elif turn_t is not None:
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
        if _num_pref(prefs, "min_shot_seconds") and round((t1 - t0) / period) > max_beats:
            shot["peak"] = True   # min_shot_seconds left no shorter split: a deliberate long hold
        if m.focus:
            shot["focus"] = list(m.focus)
        if m.faces:
            shot["faces"] = [list(b) for b in m.faces]
            if m.consent is True:
                shot["people"] = True
                shot["consent"] = True
            elif m.blur:
                shot["blur"] = [list(b) for b in m.blur]
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
    if caption_px:
        plan["caption_px"] = caption_px
    if T:
        plan["template"] = T["id"]
    hook_text = hook.strip() if hook and hook.strip() else (" ".join(w[0] for w in lines[0]["words"]) if lines else None)
    max_hook = _num_pref(prefs, "max_hook_words")
    if hook_text and max_hook and len(hook_text.replace("*", "").split()) > max_hook:
        short_hook = shorten(hook_text, int(max_hook))
        nc.warn(f"preference max_hook_words = {max_hook:g}: hook shortened to \"{short_hook}\"")
        hook_text = short_hook
    if hook_text:
        hook_s = float(pacing.get("hook_s") or 2.0)
        plan["hook"] = {"text": hook_text,
                        "t1": r3(min(D, max(float(_cfg("render.hook.min_visible_s", 1.5)), hook_s)))}
    plan["shots"] = shots
    plan["lines"] = lines
    if card_specs:
        cards, shown = make_cards(card_specs, times, end_t if end_t is not None else D, lines,
                                  after=float(plan["hook"]["t1"]) if plan.get("hook") else 0.0)
        if cards:
            plan["cards"] = cards
        if shown:   # the card is that line's on-screen text (rule 24 counts card words as shown)
            plan["lines"] = [ln for ln in lines if all(ln is not x for x in shown)]
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
    if T and (T.get("signature_moment") or {}).get("type") == "wipe" and wipe_i is None:
        nc.warn(f"template {T['id']}: its signature is a before/after wipe; without --before/--after it is a flash")

    audio = A.get("audio") or {}
    if audio.get("generated_pad") and audio.get("music"):
        plan["music"] = {"source": "pad", "path": audio["music"], "license": None,
                         "title": "Offline generated pad (last resort)"}
    elif audio.get("music") or (audio.get("combined") and audio.get("master")):
        path = audio.get("music") or audio["master"]
        plan["music"] = {"source": "folder", "path": path, "license": recorded_license(work, path), "title": None}
    else:
        plan["music"] = {"source": "natural", "path": None, "license": None, "title": None}
    plan["ai"] = {"people": False, "scenes": False, "label_required": False}
    job_name = work.parent.name if work.name == "work" else work.name
    plan["meta"] = {"slug": nc.slugify(job_name)}
    if T:
        for key, val in (("hook_type", T.get("hook_style")), ("goal", T.get("goal")),
                         ("pillar", (T.get("pillars") or [None])[0]), ("length_class", T.get("length_class"))):
            if val:
                plan["meta"][key] = val
    formats = make_formats(plan, lines, sig_t, story_end, grid, hook_text)
    if formats:
        plan["formats"] = formats
    return plan


def more_people(assign: list, media: list[Media], want: int, keep: set) -> list:
    """min_people_shots: swap body shots to consented people material until `want` shots show people."""
    people = [m for m in media if m.faces and m.consent is True]
    have = sum(1 for m in assign if m is not None and m in people)
    if have >= want:
        return assign
    if not people:
        nc.warn(f"preference min_people_shots = {want}: no photos or clips with consented people in the material")
        return assign
    out = list(assign)
    k = 0
    for i in range(len(out)):
        if have >= want:
            break
        if i in keep or out[i] is None or out[i] in people:
            continue
        cand = people[k % len(people)]
        if (i > 0 and out[i - 1] is cand) or (i + 1 < len(out) and out[i + 1] is cand):
            if len(people) == 1:
                continue
            k += 1
            cand = people[k % len(people)]
        out[i] = cand
        k += 1
        have += 1
    if have < want:
        nc.warn(f"preference min_people_shots = {want}: only {have} shot(s) with consented people fit")
    return out


def sentence_of(lines: list[dict], line: dict) -> tuple[str, list[dict]]:
    """The whole sentence a caption line starts: it and the following lines up to the sentence end."""
    k = next(i for i, ln in enumerate(lines) if ln is line)
    group = []
    for ln in lines[k:]:
        group.append(ln)
        if ln["words"][-1][0].rstrip("\"')\u201d\u2019").endswith((".", "!", "?")):
            break
    return " ".join(w[0] for ln in group for w in ln["words"]), group


def make_cards(specs: list, times: list[float], limit: float,
               lines: list[dict] | None = None, after: float = 0.0) -> tuple[list[dict], list[dict]]:
    """Text cards for a kinetic-type template: one per text_cards entry, on its beat, starting on a cut.

    after: no card starts before this time (the hook's t1), so the hook text owns frame 0 and the first
    second (a card on screen hides the hook). Returns (cards, the caption lines that statement cards show)."""
    cards: list[dict] = []
    shown: list[dict] = []
    cuts = [t for t in times if t < limit - 1e-6]
    for j, (spec, (beat, start, end, line)) in enumerate(specs):
        max_words = int(spec.get("max_words") or 8)
        if spec.get("source") == "label" and spec.get("text"):
            text = str(spec["text"])
            style = "number" if len(text.split()) == 1 and len(text) <= 5 else "statement"
        elif line is not None:
            sentence, group = sentence_of(lines or [line], line) if lines else \
                (" ".join(w[0] for w in line["words"]), [line])
            text = card_statement(sentence, max_words)
            style = "statement"
        else:
            nc.warn(f"text card for beat {beat!r}: no spoken or script line to show; left out")
            continue
        t0 = 0.0 if start <= 1e-6 else min(cuts, key=lambda c: (abs(c - start), c))
        if t0 < after - 1e-6:   # the hook owns the opening: start on the first cut after it
            later = [c for c in cuts if c >= after - 1e-6]
            t0 = later[0] if later else after
        nxt = [s for _, (_, s, _, _) in specs[j + 1:] if s > t0 + 0.5]
        n = len(text.replace("*", "").split())
        need = 0.6 + 0.25 * n
        t1 = min(max(end, t0 + need + 0.6), t0 + 3.5, limit)
        if nxt:
            t1 = min(t1, min(cuts, key=lambda c: (abs(c - nxt[0]), c)))
        if cards and t0 < cards[-1]["t1"]:
            t0 = cards[-1]["t1"]
        if t1 - t0 < need:
            nc.warn(f"text card for beat {beat!r}: only {max(0.0, t1 - t0):.1f} s free; left out")
            continue
        cards.append({"t0": r3(t0), "t1": r3(t1), "text": text, "style": style})
        if style == "statement" and spec.get("source") != "label" and line is not None and \
                _hook_key(text) == _hook_key(sentence):
            shown += group   # the card shows the whole sentence: its captions would only repeat it
    return cards, shown


def recorded_license(work: Path, path: str) -> str | None:
    """The license recorded for this file in WORK/sources.json (sources.py), else None for the Director to fill."""
    src = work / "sources.json"
    if not src.is_file():
        return None
    try:
        entries = nc.read_json(src, "sources file")
    except nc.UserError as e:
        nc.warn(f"cannot read {src}: {e}")
        return None
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("path") and Path(str(e["path"])).resolve() == Path(path).resolve():
            lic = e.get("license")
            return lic.strip() if isinstance(lic, str) and lic.strip() else None
    return None


def _hook_key(text: str) -> str:
    return " ".join(re.sub(r"[^\w' ]+", " ", text.replace("*", "").lower()).split())


def make_formats(plan: dict, lines: list[dict], sig_t: float | None, story_end: float, grid: list[float],
                 hook_text: str | None) -> dict:
    D = plan["duration"]
    out: dict[str, Any] = {}
    texts = [" ".join(w[0] for w in ln["words"]) for ln in lines]
    longest = max(texts, key=len) if texts else None
    centre = sig_t if sig_t is not None else story_end / 2
    lo, hi = _cfg("render.length_s.reach_cut", [8, 12])
    # the reach cut opens on new hook text (formats.py warns when it repeats the reel's hook): the meta
    # title, else the strongest other line (the longest one that still reads as a hook)
    own = _hook_key(hook_text or "")
    others = [t for t in texts if _hook_key(t) != own and len(t.split()) >= 3]
    title = (plan.get("meta") or {}).get("title")
    reach_hook = title if title and _hook_key(title) != own else \
        (max(others, key=lambda t: (len(t) <= 60, len(t))) if others else None)
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
    # story stills and carousel slides: whole sentences only (caption lines joined), chosen the way
    # formats.py chooses its defaults
    import formats  # noqa: PLC0415 - heavy (engine); only needed here
    for key, make in (("story", formats.default_story), ("carousel", formats.default_carousel)):
        try:
            out[key] = [{"t": r3(e["t"]), "text": e["text"]} for e in make(plan)]
        except formats.NoDefault:
            pass
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
    ap.add_argument("--template", metavar="NAME", help="reel template or preset id from the scriptwriter's "
                    "templates.json (arc, length, pacing, look, signature, transitions, hook style, text cards)")
    ap.add_argument("--library", metavar="FILE", help="library.py index: consent per photo/clip path")
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
    template = load_template(args.template) if args.template else None
    library = library_consent(args.library) if args.library else None
    script = None
    if args.script:
        sp = Path(args.script).expanduser().resolve()
        if not sp.is_file():
            raise nc.UserError(f"script file not found: {sp}")
        script = sp.read_text(encoding="utf-8", errors="replace")
        if A.get("words"):
            nc.info("script given but the analysis has a transcript: captions follow the voice")

    plan = build_plan(work, A, duration=args.duration, hook=args.hook, subtitle=args.subtitle, seed=args.seed,
                      prefs=prefs, script=script, before=args.before, after=args.after, turn=args.turn,
                      template=template, library=library)
    errs = nc.schema_errors("plan", plan)
    if errs:
        raise nc.UserError("built plan does not match plan.schema.json: " + "; ".join(errs[:5]))
    out = Path(args.out).expanduser().resolve() if args.out else work / "plan.json"
    nc.write_json(out, plan)
    issues = validate_plan.validate(plan, A, prefs, out)
    for i in issues:
        if i.level == "ERROR":
            nc.error_line(f"plan check: {i.line()}")
        else:
            nc.warn(f"plan check: {i.line()}")
    n_err = sum(1 for i in issues if i.level == "ERROR")
    print(f"{out}: {len(plan['shots'])} shots, {len(plan['lines'])} caption lines, {plan['duration']:g} s"
          + (f", {n_err} validation error(s) to fix" if n_err else ""))
    return 1 if n_err else 0


if __name__ == "__main__":
    nc.run_cli(main)
