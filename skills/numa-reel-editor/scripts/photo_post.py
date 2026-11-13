#!/usr/bin/env python3
"""Feed photo posts from the render engine: one single-photo post or a photo carousel (R333, R334).

Usage:
    photo_post.py single PHOTO --out OUT [--text TEXT] [--look warm|none] [--slug S]
                  [--consent] [--library FILE] [--blur-faces] [--people-free] [--json]
    photo_post.py carousel PHOTOS... --out OUT [--texts FILE] [--look warm|none] [--slug S]
                  [--consent] [--library FILE] [--blur-faces] [--people-free PHOTO ...] [--json]

Every picture is a 1080x1350 (4:5) JPG rendered by engine.py from a one-shot
plan, so it carries the reels' look: the colour look (``--look``, default warm),
bloom, vignette and bottom gradient, and the seeded film grain.

* Framing: vision.py finds the faces and the main subject (the largest faces,
  else the saliency centre); the engine crops the 4:5 view around that point
  (cover fit, the view never leaves the photo; very wide photos get the
  engine's blurred-fill panorama treatment).
* Text (optional, one short line of at most TEXT_MAX_CHARS characters, ``*word*`` marks
  the gold accent; no markup: the last word is gold) is the engine's frame-zero
  hook: the brand serif, at most 3 rows, inside the safe areas (config
  ``render.safe_area``), with the engine's legibility scrim when the picture
  under it would give white text less than 4.5:1. It sits at the top; when an
  unblurred face is under the top text it moves to the bottom of the safe area.
  Every text is claims-scanned (claims_scan.py): a banned claim is an ERROR,
  a wording warning a WARN.
* People and consent (brand.json ``consent``). Face detection can only ever
  say yes: finding no face never proves a photo is people-free (backs, people
  lying down, profiles, small figures). So every photo needs a recorded basis,
  reported as ``people_basis``:
    consent           ``--consent``: the Director checked STATE/consent_list.json
                      (everyone recognizable is on it, scope covers social posts)
    library_consent   a library.py index (``--library``) records consent yes
    library_tag_no    the index records people "no" set by ``library.py tag``
                      (people_source "tag": someone looked at the picture)
    people_free_flag  ``--people-free``: the Director LOOKED and there are truly
                      no people (single: the flag; carousel: ``--people-free PHOTO``,
                      repeatable, a path or file name)
    blurred           ``--blur-faces`` with detected faces: every detected face
                      (with a margin for hair and ears) is blurred beyond
                      recognition and the framing follows the rest of the picture
  Without one the run is an ERROR. ``--blur-faces`` alone never passes a photo
  with no detected face (there is nothing to blur, the people may still be
  there). Faces found on a photo marked people-free (tag or flag) need
  ``--blur-faces`` or consent. A photo marked people-free with no detected face
  keeps that basis even with ``--consent`` (so it never counts as showing
  members). A library entry with consent ``no`` is never
  overridden by ``--consent`` or ``--people-free``. Detection misses faces:
  LOOK at the output.

single: OUT is the JPG to write (a folder gets ``<slug>_photo.jpg``).
carousel: PHOTOS are 2-10 photos, or folders of photos (their images in name
order); OUT is a folder that gets ``<slug>_carousel_NN.jpg`` (01, 02, ... in
the given order; earlier ``<slug>_carousel_*.jpg`` files are replaced). The
same naming as Claude Design component carousels, so /post-reel posts either.
``--texts FILE``: one text per slide, as a JSON list (strings or null) or a
plain-text file with one line per slide (an empty line = no text).

``--slug`` defaults to the photo's (single) or the first folder's or photo's
(carousel) name. Output is deterministic: the same inputs give the same bytes.
``--json`` prints {"ok", "kind", "files", "slides": [{file, src, text, faces,
consent, people_basis, blurred, focus, text_position, upscale}]} on stdout.
Exit 1 on an unusable photo, missing consent, a banned claim or text that
does not fit; exit 2 on usage errors.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

POST_SIZE = (1080, 1350)
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10        # Instagram: 2-10 items per carousel
TEXT_MAX_CHARS = 60                       # one short line: at most 3 rows of the hook serif
PLAN_DURATION = 3.0                       # a one-shot plan; the post is its frame 0 (hook fully on)
NO_AUTO_PAN = [1e-4, 0.0]                 # any non-zero pan turns the engine's auto pan off (still at t=0)
FACE_MARGIN = (0.35, 0.55, 0.25)          # blur box growth: sides, top (hair), bottom, x the face box size
TEXT_FACE_GAP = 0.02                      # face within 2% of the frame height of the text counts as under it
UPSCALE_WARN = 1.5                        # WARN when the photo is enlarged more than this
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif", ".bmp"}
LOOKS = ("warm", "none")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def photo_files(items: Sequence[str]) -> list[Path]:
    """Photos in the given order; a folder adds its images in name order."""
    out: list[Path] = []
    for it in items:
        p = Path(it).expanduser().resolve()
        if p.is_dir():
            found = sorted((q for q in p.iterdir() if q.is_file() and q.suffix.lower() in IMAGE_EXT
                            and not q.name.startswith(".")), key=lambda q: q.name.lower())
            if not found:
                raise nc.UserError(f"no photos in folder {p}")
            out += found
        elif p.is_file():
            if p.suffix.lower() not in IMAGE_EXT:
                raise nc.UserError(f"{p.name}: not a photo (expected one of {', '.join(sorted(IMAGE_EXT))})")
            out.append(p)
        else:
            raise nc.UserError(f"photo not found: {p}")
    return out


def read_texts(path: str, n: int) -> list[str | None]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise nc.UserError(f"--texts: file not found: {p}")
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, list) or not all(x is None or isinstance(x, str) for x in data):
            raise nc.UserError(f"--texts {p.name}: expected a JSON list of texts (strings or null)")
        texts = data
    else:
        texts = raw.splitlines()
        while texts and not texts[-1].strip():
            texts.pop()
    if len(texts) != n:
        raise nc.UserError(f"--texts {p.name}: {len(texts)} text(s) for {n} slide(s); give one per slide "
                           f"(an empty line or null for no text)")
    return [t.strip() if isinstance(t, str) and t.strip() else None for t in texts]


def library_consent(path: str | None) -> dict[str, dict]:
    """{resolved path: {"consent": True|False|None, "people_no": bool}} from a library.py index.

    people_no is true only for people "no" set by a tag (someone looked); a detector never sets it."""
    if not path:
        return {}
    import baseline_plan
    data = nc.read_json(Path(path).expanduser().resolve(), "library index")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise nc.UserError(f"library index {path}: expected an object with an 'items' list")
    out: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("path"), str):
            people_no = it.get("people") in (False, "no") and it.get("people_source") == "tag"
            out[str(Path(it["path"]).expanduser().resolve())] = {
                "consent": baseline_plan._consent_value(it.get("consent")), "people_no": people_no}
    return out


def people_free_set(values: Sequence[str] | None, photos: Sequence[Path]) -> set[Path]:
    """The carousel photos named by --people-free (a path or a file name); an unknown name is a usage error."""
    chosen: set[Path] = set()
    for v in values or []:
        p = Path(v).expanduser()
        hits = [q for q in photos if q == p.resolve() or q.name == v]
        if not hits:
            raise nc.UsageError(f"--people-free {v}: not one of the carousel's photos")
        chosen.update(hits)
    return chosen


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_text(text: str, where: str) -> None:
    """Length, words and the claims scan (banned claim -> UserError, wording -> WARN)."""
    import claims_scan
    import engine_text as et
    shown = " ".join(text.replace("*", "").split())
    if not et.hook_words(text):
        raise nc.UserError(f"{where}: the text has no words")
    if len(shown) > TEXT_MAX_CHARS:
        raise nc.UserError(f"{where}: text is {len(shown)} characters; a photo post's text is at most "
                           f"{TEXT_MAX_CHARS} (shorten it: {shown!r})")
    if text.count("*") % 2:
        raise nc.UserError(f"{where}: unbalanced *gold* markup in {text!r}")
    hits = claims_scan.scan_text(text, where=where)
    for h in hits:
        if h.severity != "fail":
            nc.warn(h.line())
    fails = [h for h in hits if h.severity == "fail"]
    if fails:
        raise nc.UserError(fails[0].line())


def blur_box(face: Sequence[float]) -> list[float]:
    """A face box grown to cover the head (hair, ears, chin), clipped to the photo."""
    x, y, w, h = (float(v) for v in face)
    side, top, bottom = FACE_MARGIN
    x0, y0 = max(0.0, x - side * w), max(0.0, y - top * h)
    x1, y1 = min(1.0, x + w + side * w), min(1.0, y + h + bottom * h)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


class Photo:
    """One analysed photo: faces, focus and the consent decision."""

    def __init__(self, path: Path, det, consent_flag: bool, library: dict[str, dict], blur_faces: bool,
                 people_free: bool = False):
        import cv2
        import vision
        self.path = path
        bgr = vision.read_image(str(path))
        self.h, self.w = bgr.shape[:2]
        self.faces = [list(map(float, b)) for b in (det.detect(bgr) if det.backend else [])]
        lib = library.get(str(path)) or {}
        self.blur: list[list[float]] = []
        self.people_basis: str | None = None
        n = len(self.faces)
        marked_free = "library_tag_no" if lib.get("people_no") else "people_free_flag" if people_free else None
        if lib.get("consent") is False:
            self.consent = False           # the library says no: never overridden by --consent / --people-free
        elif marked_free and not n:
            self.consent = True if lib.get("consent") is True else None
            self.people_basis = marked_free  # looked at and no people: no member hold, whatever --consent says
        elif lib.get("consent") is True or consent_flag:
            self.consent = True
            self.people_basis = "library_consent" if lib.get("consent") is True else "consent"
        else:
            self.consent = None
        if self.people_basis is None:
            if n and blur_faces:
                self.people_basis = "blurred"
                self.blur = [blur_box(b) for b in self.faces]
            elif self.consent is False:
                raise nc.UserError(
                    f"{path.name}: the library records consent no" + (f" and {n} face(s) were found" if n else "")
                    + ". Fix: use a different photo" + (", or pass --blur-faces" if n else ""))
            elif marked_free and not n:
                self.people_basis = marked_free
            elif n:
                how = " though it is marked people-free" if marked_free else " and no recorded consent"
                raise nc.UserError(
                    f"{path.name}: {n} face(s){how} (brand.json consent). Fix: check STATE/consent_list.json and "
                    f"pass --consent (or record it with library.py --consent yes), or pass --blur-faces")
            else:
                raise nc.UserError(
                    f"{path.name}: no recorded consent and nothing records it as people-free (finding no face "
                    f"never proves there are no people). Fix: LOOK at it; pass --people-free only when it truly "
                    f"shows no people (or tag it with library.py --people no), else --consent after checking "
                    f"STATE/consent_list.json")
        if self.faces and not self.blur:
            self.focus = vision.face_focus(self.faces)
        else:
            self.focus = vision.saliency_focus(cv2.GaussianBlur(bgr, (0, 0), 3) if self.blur else bgr)
        self.focus = [min(1.0, max(0.0, float(v))) for v in self.focus]

    def upscale(self, size: tuple[int, int]) -> float:
        """How much the engine enlarges the photo to cover the post (cover fit, zoom 1)."""
        return max(size[0] / self.w, size[1] / self.h)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def post_plan(ph: Photo, text: str | None, look: str, out_dir: Path, hook_y: float | None = None) -> dict:
    shot: dict[str, Any] = {"src": str(ph.path), "kind": "image", "t0": 0.0, "t1": PLAN_DURATION, "tr": "cut",
                            "look": look, "z": [1.0, 1.0], "pan": list(NO_AUTO_PAN), "focus": ph.focus}
    if ph.faces:
        shot["people"] = True
        shot["faces"] = ph.faces
        if ph.consent is True:
            shot["consent"] = True
    elif ph.people_basis in ("consent", "library_consent"):
        shot["people"] = True
        shot["consent"] = True
    if ph.blur:
        shot["blur"] = ph.blur
    plan: dict[str, Any] = {"duration": PLAN_DURATION, "size": list(POST_SIZE), "seed": 1, "out_dir": str(out_dir),
                            "shots": [shot], "lines": [], "leaks": []}
    if text:
        plan["hook"] = {"text": text, "t1": 2.0}
        if hook_y is not None:
            plan["hook"]["y"] = round(hook_y, 2)
    return plan


def _faces_under(r, y0: float, y1: float) -> bool:
    """An unblurred face on screen overlaps the band [y0, y1] (output px)."""
    gap = TEXT_FACE_GAP * r.height
    return any(fy1 > y0 - gap and fy0 < y1 + gap for _, fy0, _, fy1 in r._face_rects(0.0, 0.0))


def render_post(ph: Photo, text: str | None, look: str, out: Path, where: str) -> dict:
    """Render one 1080x1350 post to out; returns its report entry."""
    import engine
    position = None
    plan = post_plan(ph, text, look, out.parent)
    r = engine.Renderer(engine.prepare_plan(plan, out.parent), size=POST_SIZE, quiet=True)
    try:
        if text:
            blk, top, _ = r._hook
            if not blk.fit:
                raise nc.UserError(f"{where}: text {text!r} does not fit 3 rows of the post; shorten it")
            position = "top"
            h0, h1 = r._hook_ink
            if not ph.blur and ph.faces and _faces_under(r, h0, h1):
                # bottom of the safe area: the block's centre so its last row sits on the safe line
                y = r.safe_bottom - blk.height / 2
                r.close()
                plan = post_plan(ph, text, look, out.parent, hook_y=y)
                r = engine.Renderer(engine.prepare_plan(plan, out.parent), size=POST_SIZE, quiet=True)
                position = "bottom"
                b0, b1 = r._hook_ink
                if _faces_under(r, b0, b1):
                    nc.warn(f"{where}: faces fill the frame; the text sits over a face at the top (LOOK at it)")
                    r.close()
                    plan = post_plan(ph, text, look, out.parent)
                    r = engine.Renderer(engine.prepare_plan(plan, out.parent), size=POST_SIZE, quiet=True)
                    position = "top"
        rgb = r.frame(0.0, 0)
    finally:
        r.close()
    engine.save_image(rgb, out, quality=92)
    up = ph.upscale(POST_SIZE)
    if up > UPSCALE_WARN:
        nc.warn(f"{where}: {ph.path.name} is {ph.w}x{ph.h}; the post enlarges it {up:.1f}x and may look soft")
    return {"file": str(out), "src": str(ph.path), "text": text, "faces": len(ph.faces), "consent": ph.consent,
            "people_basis": ph.people_basis,
            "blurred": bool(ph.blur), "focus": ph.focus, "text_position": position, "upscale": round(up, 3)}


def detector():
    import vision
    det = vision.FaceDetector()
    if not det.backend:
        nc.warn(f"no face detector ({det.reason}); faces cannot be checked: LOOK at every post for people")
    return det


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_single(args) -> dict:
    src = photo_files([args.photo])
    if len(src) != 1 or Path(args.photo).expanduser().is_dir():
        raise nc.UsageError("single takes one photo file (use carousel for a folder)")
    photo = src[0]
    slug = nc.slugify(args.slug or photo.stem)
    if not slug:
        raise nc.UsageError("--slug must contain letters or digits")
    out = Path(args.out).expanduser().resolve()
    if out.is_dir() or out.suffix.lower() not in (".jpg", ".jpeg"):
        if out.suffix:
            raise nc.UsageError(f"--out {out.name}: a single post is a .jpg file (or a folder)")
        out = out / f"{slug}_photo.jpg"
    text = args.text.strip() if args.text and args.text.strip() else None
    if text:
        check_text(text, "--text")
    ph = Photo(photo, detector(), args.consent, library_consent(args.library), args.blur_faces, args.people_free)
    out.parent.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "kind": "single", "files": [str(out)],
            "slides": [render_post(ph, text, args.look, out, photo.name)]}


def carousel_name(slug: str, n: int) -> str:
    return f"{slug}_carousel_{n:02d}.jpg"


def cmd_carousel(args) -> dict:
    photos = photo_files(args.photos)
    if not CAROUSEL_MIN <= len(photos) <= CAROUSEL_MAX:
        raise nc.UserError(f"a carousel has {CAROUSEL_MIN}-{CAROUSEL_MAX} slides; got {len(photos)} photo(s)")
    first = Path(args.photos[0]).expanduser().resolve()
    slug = nc.slugify(args.slug or (first.name if first.is_dir() else first.stem))
    if not slug:
        raise nc.UsageError("--slug must contain letters or digits")
    seen: dict[Path, int] = {}
    for i, p in enumerate(photos, 1):
        if p in seen:
            nc.warn(f"slide {i} repeats slide {seen[p]} ({p.name})")
        seen.setdefault(p, i)
    texts = read_texts(args.texts, len(photos)) if args.texts else [None] * len(photos)
    for i, t in enumerate(texts, 1):
        if t:
            check_text(t, f"slide {i}")
    det, lib = detector(), library_consent(args.library)
    free = people_free_set(args.people_free, photos)
    analysed = [Photo(p, det, args.consent, lib, args.blur_faces, p in free)
                for p in photos]   # every consent check first, before anything is written
    out = Path(args.out).expanduser().resolve()
    if out.exists() and not out.is_dir():
        raise nc.UsageError(f"--out {out}: a carousel goes to a folder")
    out.mkdir(parents=True, exist_ok=True)
    rx = re.compile(rf"^{re.escape(slug)}_carousel_\d+\.jpg$")
    for old in out.iterdir():
        if old.is_file() and rx.match(old.name):
            old.unlink()
    slides = [render_post(ph, t, args.look, out / carousel_name(slug, i), f"slide {i}")
              for i, (ph, t) in enumerate(zip(analysed, texts), 1)]
    return {"ok": True, "kind": "carousel", "files": [s["file"] for s in slides], "slides": slides}


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="photo_post.py",
                      description="Single-photo posts and photo carousels (1080x1350) with the reels' look.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)

    def common(p):
        p.add_argument("--out", required=True, help="single: the .jpg (or a folder); carousel: the folder")
        p.add_argument("--look", choices=LOOKS, default="warm", help="colour look (default warm, as the reels)")
        p.add_argument("--slug", help="file-name stem (default: from the photo or folder name)")
        p.add_argument("--consent", action="store_true",
                       help="everyone recognizable in these photos is on the Consent List (checked by the Director)")
        p.add_argument("--library", metavar="FILE",
                       help="library.py index: consent yes/no, or people no set by a tag, per photo path")
        p.add_argument("--blur-faces", action="store_true", help="blur faces without recorded consent instead of failing")
        p.add_argument("--json", action="store_true", help="print the JSON report on stdout")
    s = sub.add_parser("single", help="one 1080x1350 photo post")
    s.add_argument("photo", metavar="PHOTO")
    s.add_argument("--text", help=f"short text over the photo (at most {TEXT_MAX_CHARS} characters; *word* = gold)")
    s.add_argument("--people-free", action="store_true",
                   help="the Director LOOKED: the photo truly shows no people (detectors cannot prove it)")
    common(s)
    c = sub.add_parser("carousel", help=f"a {CAROUSEL_MIN}-{CAROUSEL_MAX} slide photo carousel")
    c.add_argument("photos", nargs="+", metavar="PHOTOS", help="photos or folders of photos, in slide order")
    c.add_argument("--texts", metavar="FILE", help="one text per slide: JSON list, or one line per slide")
    c.add_argument("--people-free", action="append", metavar="PHOTO",
                   help="this photo (path or file name) was LOOKED at and truly shows no people; repeatable")
    common(c)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: single or carousel")
    nc.load_brand()
    report = cmd_single(args) if args.cmd == "single" else cmd_carousel(args)
    if args.json:
        nc.print_json(report)
    else:
        for s in report["slides"]:
            extra = []
            extra.append(f"{s['faces']} face(s), people: {s['people_basis']}")
            if s["text"]:
                extra.append(f"text {s['text_position']}")
            print(f"Wrote {s['file']}" + (f" ({', '.join(extra)})" if extra else ""))
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
