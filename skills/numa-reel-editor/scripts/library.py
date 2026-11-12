#!/usr/bin/env python3
"""Media library index: every past photo and clip with probe data and tags (spec p.30 #7, p.37).

Usage:
    library.py add   --index FILE PATH ... [--tags a,b] [--link URL] [--consent yes|no|unknown]
                     [--people yes|no|auto] [--no-faces]
    library.py tag   --index FILE ITEM ... [--add a,b] [--remove c,d] [--link URL] [--consent yes|no|unknown]
                     [--people yes|no]
    library.py query --index FILE [--tags "cold plunge, morning"] [--kind photo|clip]
                     [--orientation vertical|horizontal|square] [--people yes|no] [--consent yes|no|unknown]
                     [--min-duration S] [--usable] [--limit N] [--json]
    library.py list  --index FILE [--json]

`add` probes each file (a folder adds every photo/clip inside it, recursively):
width/height after rotation, orientation, duration (clips), sharpness
(variance of the Laplacian on a 1080-wide grey copy, the same measure as
analyze.py; clips use a frame from the middle) and a face count from OpenCV's
frontal-face detector (people = yes when any face is found, unless --people is
given). Re-adding a path refreshes the probe and keeps its tags. Consent
defaults to "unknown" for items with people and "n/a" without.

`ITEM` is an item id (M + 10 hex digits) or its path. Tags are lower-case
phrases separated by commas ("cold plunge, morning, smiling, group"); room
names (plunge room, sauna, class studio, front of house, outside) are tags too.

`query` keeps items carrying every requested tag (a tag matches whole words
of an item tag, so "plunge" finds "cold plunge"), filters by kind,
orientation, people, consent and minimum duration, and ranks by sharpness
(sharpest first, then path). `--usable` drops people shots without consent
"yes" (B-roll fallback and batched-shoot reuse may only use those).

Index shape: {"schema_version": 1, "items": [{"id", "path", "name", "kind",
"width", "height", "orientation", "duration", "sharpness", "faces", "people",
"consent", "tags", "link", "size_bytes"}]} sorted by path. The Librarian
mirrors it to Drive; the file itself is the local copy.
"""
from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

INDEX_SCHEMA_VERSION = 1
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
CLIP_EXT = {".mp4", ".mov", ".m4v"}
CONSENT = ("yes", "no", "unknown", "n/a")


def split_tags(text: str | None) -> list[str]:
    if not text:
        return []
    out = []
    for t in re.split(r"[,;]", text):
        t = " ".join(t.strip().lower().split())
        if t and t not in out:
            out.append(t)
    return out


def item_id(path: Path) -> str:
    return "M" + hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]


def orientation(w: int, h: int) -> str:
    if h > w * 1.05:
        return "vertical"
    if w > h * 1.05:
        return "horizontal"
    return "square"


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------
def _open_image(path: Path):
    from PIL import Image, ImageOps
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise nc.UserError(f"{path}: HEIC needs pillow-heif (pip install pillow-heif)") from None
    try:
        with Image.open(path) as im:
            return ImageOps.exif_transpose(im).convert("RGB")
    except OSError as e:
        raise nc.UserError(f"{path}: cannot read image: {e}") from None


def _clip_frame(path: Path, t: float):
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "frame.png"
        nc.ffmpeg("-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", "-y", str(out),
                  what=f"frame from {path.name}")
        if not out.exists():
            raise nc.UserError(f"{path}: no video frame at {t:.2f} s")
        with Image.open(out) as im:
            return im.convert("RGB")


def sharpness(im) -> float:
    import cv2
    import numpy as np
    g = im.convert("L")
    if g.width != 1080:
        g = g.resize((1080, max(1, round(g.height * 1080 / g.width))), resample=3)
    return round(float(cv2.Laplacian(np.asarray(g, dtype=np.uint8), cv2.CV_64F).var()), 2)


def face_count(im) -> int:
    import cv2
    import numpy as np
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    if cascade.empty():
        return 0
    g = im.convert("L")
    if g.width > 720:
        g = g.resize((720, max(1, round(g.height * 720 / g.width))), resample=3)
    a = np.asarray(g, dtype=np.uint8)
    side = max(24, min(a.shape) // 12)
    faces = cascade.detectMultiScale(a, scaleFactor=1.1, minNeighbors=6, minSize=(side, side))
    return int(len(faces))


def probe(path: Path, detect_faces: bool = True) -> dict:
    ext = path.suffix.lower()
    if ext in PHOTO_EXT:
        im = _open_image(path)
        w, h = im.size
        info = {"kind": "photo", "width": w, "height": h, "duration": None, "sharpness": sharpness(im)}
    elif ext in CLIP_EXT:
        mi = nc.media_info(path)
        if not mi.get("has_video") or not mi.get("width"):
            raise nc.UserError(f"{path}: no video stream")
        dur = float(mi["duration"] or 0.0)
        im = _clip_frame(path, dur / 2 if dur > 0 else 0.0)
        w, h = int(mi["width"]), int(mi["height"])
        info = {"kind": "clip", "width": w, "height": h, "duration": round(dur, 3), "sharpness": sharpness(im)}
    else:
        raise nc.UserError(f"{path}: not a photo or clip ({', '.join(sorted(PHOTO_EXT | CLIP_EXT))})")
    info["orientation"] = orientation(info["width"], info["height"])
    info["faces"] = face_count(im) if detect_faces else None
    return info


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
def load_index(path: Path, create: bool = False) -> dict:
    if not path.exists() and create:
        return {"schema_version": INDEX_SCHEMA_VERSION, "items": []}
    data = nc.read_json(path, "library index")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise nc.UserError(f"library index {path}: expected an object with an 'items' list")
    for i, it in enumerate(data["items"]):
        if not isinstance(it, dict) or not it.get("id") or not it.get("path") or it.get("kind") not in ("photo", "clip"):
            raise nc.UserError(f"library index {path}: items[{i}] needs id, path and kind photo|clip")
        if not isinstance(it.get("tags", []), list):
            raise nc.UserError(f"library index {path}: items[{i}].tags must be a list")
    return data


def save_index(path: Path, data: dict) -> None:
    data["items"].sort(key=lambda it: it["path"])
    data["schema_version"] = INDEX_SCHEMA_VERSION
    nc.write_json(path, data)


def expand(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if path.is_dir():
            out += sorted(f for f in path.rglob("*") if f.is_file() and f.suffix.lower() in PHOTO_EXT | CLIP_EXT
                          and not any(part.startswith(".") for part in f.relative_to(path).parts))
        elif path.is_file():
            out.append(path)
        else:
            raise nc.UserError(f"not found: {path}")
    return out


def find(data: dict, ref: str) -> dict:
    for it in data["items"]:
        if it["id"] == ref:
            return it
    p = str(Path(ref).expanduser().resolve())
    for it in data["items"]:
        if it["path"] == p:
            return it
    raise nc.UserError(f"not in the index: {ref}")


def yes_no(v: str | None) -> bool | None:
    return None if v in (None, "auto") else v == "yes"


def tag_matches(want: str, tags: list[str]) -> bool:
    pat = re.compile(r"\b" + r"\s+".join(map(re.escape, want.split())) + r"\b")
    return any(pat.search(t) for t in tags)


def query(data: dict, tags: list[str], kind: str | None = None, orient: str | None = None,
          people: bool | None = None, consent: str | None = None, min_duration: float | None = None,
          usable: bool = False, limit: int | None = None) -> list[dict]:
    out = []
    for it in data["items"]:
        if kind and it["kind"] != kind:
            continue
        if orient and it.get("orientation") != orient:
            continue
        if people is not None and bool(it.get("people")) != people:
            continue
        if consent and it.get("consent") != consent:
            continue
        if min_duration is not None and (it["kind"] != "clip" or (it.get("duration") or 0) < min_duration):
            continue
        if usable and it.get("people") and it.get("consent") != "yes":
            continue
        if not all(tag_matches(t, it.get("tags", [])) for t in tags):
            continue
        out.append(it)
    out.sort(key=lambda it: (-(it.get("sharpness") or 0.0), it["path"]))
    return out[:limit] if limit else out


def line(it: dict) -> str:
    dur = f" {it['duration']:.1f}s" if it.get("duration") else ""
    ppl = " people" + (f"(consent {it.get('consent')})" if it.get("people") else "") if it.get("people") else ""
    return (f"{it['id']}  {it['kind']:<5} {it['width']}x{it['height']} {it['orientation']:<10}{dur}  sharp {it.get('sharpness', 0):g}"
            f"{ppl}  [{', '.join(it.get('tags', []))}]  {it['path']}")


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="library.py", description="Media library index of past photos and clips.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    a = sub.add_parser("add", help="probe and index files or folders")
    a.add_argument("--index", required=True)
    a.add_argument("paths", nargs="+", metavar="PATH")
    a.add_argument("--tags", help="comma-separated tags")
    a.add_argument("--link", help="Drive link (only with a single file)")
    a.add_argument("--consent", choices=("yes", "no", "unknown"))
    a.add_argument("--people", choices=("yes", "no", "auto"), default="auto")
    a.add_argument("--no-faces", action="store_true", help="skip face detection")
    t = sub.add_parser("tag", help="add/remove tags or set link, consent, people")
    t.add_argument("--index", required=True)
    t.add_argument("items", nargs="+", metavar="ITEM")
    t.add_argument("--add")
    t.add_argument("--remove")
    t.add_argument("--link")
    t.add_argument("--consent", choices=("yes", "no", "unknown"))
    t.add_argument("--people", choices=("yes", "no"))
    q = sub.add_parser("query", help="find media by tags, best first")
    q.add_argument("--index", required=True)
    q.add_argument("--tags")
    q.add_argument("--kind", choices=("photo", "clip"))
    q.add_argument("--orientation", choices=("vertical", "horizontal", "square"))
    q.add_argument("--people", choices=("yes", "no"))
    q.add_argument("--consent", choices=CONSENT)
    q.add_argument("--min-duration", type=float)
    q.add_argument("--usable", action="store_true", help="drop people shots without consent yes")
    q.add_argument("--limit", type=int)
    q.add_argument("--json", action="store_true")
    li = sub.add_parser("list", help="every indexed item")
    li.add_argument("--index", required=True)
    li.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: add, tag, query or list")
    index = Path(args.index).expanduser().resolve()

    if args.cmd == "add":
        files = expand(args.paths)
        if not files:
            raise nc.UserError("no photos or clips found in " + ", ".join(args.paths))
        if args.link and len(files) > 1:
            raise nc.UsageError("--link needs a single file")
        data = load_index(index, create=True)
        by_path = {it["path"]: it for it in data["items"]}
        new_tags = split_tags(args.tags)
        for f in files:
            info = probe(f, detect_faces=not args.no_faces)
            it = by_path.get(str(f)) or {"id": item_id(f), "path": str(f), "tags": [], "link": None, "consent": None}
            people = yes_no(args.people)
            if people is None:
                people = bool(info["faces"]) if info["faces"] is not None else bool(it.get("people"))
            it.update({"name": f.name, **info, "people": people, "size_bytes": f.stat().st_size})
            it["tags"] = it.get("tags", []) + [t for t in new_tags if t not in it.get("tags", [])]
            if args.link:
                it["link"] = args.link
            if args.consent:
                it["consent"] = args.consent
            elif it.get("consent") in (None, "n/a") or (not people and it.get("consent") == "unknown"):
                it["consent"] = "unknown" if people else "n/a"
            if str(f) not in by_path:
                data["items"].append(it)
                by_path[str(f)] = it
            print(line(it))
        save_index(index, data)
        print(f"Indexed {len(files)} file(s); {len(data['items'])} in the library")
        return 0

    data = load_index(index)
    if args.cmd == "tag":
        add, remove = split_tags(args.add), split_tags(args.remove)
        if not (add or remove or args.link or args.consent or args.people):
            raise nc.UsageError("nothing to change: give --add, --remove, --link, --consent or --people")
        for ref in args.items:
            it = find(data, ref)
            it["tags"] = [t for t in it.get("tags", []) if t not in remove] + [t for t in add if t not in it.get("tags", [])]
            if args.link:
                it["link"] = args.link
            if args.people:
                it["people"] = args.people == "yes"
                if not it["people"] and it.get("consent") == "unknown":
                    it["consent"] = "n/a"
                elif it["people"] and it.get("consent") == "n/a":
                    it["consent"] = "unknown"
            if args.consent:
                it["consent"] = args.consent
            print(line(it))
        save_index(index, data)
        return 0
    if args.cmd == "query":
        if args.limit is not None and args.limit < 1:
            raise nc.UsageError("--limit must be at least 1")
        res = query(data, split_tags(args.tags), args.kind, args.orientation, yes_no(args.people), args.consent,
                    args.min_duration, args.usable, args.limit)
        if args.json:
            nc.print_json(res)
        elif not res:
            print("No matching media.")
        else:
            for it in res:
                print(line(it))
        return 0
    if args.cmd == "list":
        if args.json:
            nc.print_json(data["items"])
        else:
            for it in data["items"]:
                print(line(it))
            print(f"{len(data['items'])} item(s)")
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
