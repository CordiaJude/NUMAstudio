#!/usr/bin/env python3
"""Render NUMA component carousels: Claude Design canvas -> 1080x1350 slides (R328-R332, DECISIONS D21).

Usage:
    design_render.py validate CAROUSEL_JSON [--json]
    design_render.py build    CAROUSEL_JSON --root ROOT [--uploads-only] [--created-at ISO] [--json]
    design_render.py canvas   DIR --out OUT [--slug SLUG] [--runtime FILE] [--format jpg|png] [--list-blobs] [--json]
    design_render.py spec     CAROUSEL_JSON --out OUT [--format jpg|png] [--json]

A component carousel is designed on a Claude Design canvas (Artifact type "Design"):
one canvas per carousel, one 1080x1350 artboard (`project/*.dc.html`) per slide.
The canvas is where Katie and Jude look and edit; there is no approval step and
no Export click. The slides are rendered here, locally, with headless Chromium.

validate  Checks carousel.json (schemas/carousel.schema.json): the components and
          their fields, the photos exist, 2-10 slides, every text field and the
          caption pass the claims scanner (claims_scan.py as a module), offer
          prices come from brand.json (a price that is `needs_katie` is an ERROR).
build     Writes the canvas files for a new canvas under ROOT, ready for one
          Artifact publish per file: `ROOT/project/canvas.json` and one
          `ROOT/project/<board>.dc.html` per slide (Main.dc.html, Slide02.dc.html, ...)
          from the bundled `.dc.html` components, every field filled in as literal
          markup (so it can be retyped on the canvas) and the brand palette applied.
          Images must be uploaded first: `--uploads-only` copies each image that
          needs an upload (slide photos, the wordmark) to `ROOT/uploads/` and lists
          them; record each upload's `/_blob/<id>` in carousel.json `canvas.blobs`.
canvas    Renders a canvas folder read back with the Artifact tool: `canvas.json`
          and the `.dc.html` artboards (in `DIR/project/` or `DIR/`), the Design
          type's `artifact-type/dc-runtime.js` (served as `project/support.js`;
          or `--runtime FILE`) and the uploaded images (`/_blob/<id>` -> a file named
          `<id>` or `<id>.<ext>` in `DIR/_blob/`, `DIR/project/_blob/` or `DIR/`).
          Slides are taken in reading order (rows top to bottom, each left to
          right). Google Fonts links are served from the bundled fonts; nothing is
          fetched from the network. `--list-blobs` prints the image ids the artboards
          use and whether each is present, then exits.
spec      The fallback (R331): renders carousel.json straight from the bundled
          plain-HTML components, the same markup as the artboards.

Checks on every slide (an ERROR fails the run, exit 1):
  1080x1350 exactly; every font the slide uses is loaded (no system fallback);
  not blank or near-uniform; no text overflowing its box (scrollHeight /
  scrollWidth against the box, measured in the page); the claims scanner on the
  slide's text; no "[PRICE]" placeholder left; 2-10 slides (outside config
  formats `carousel` count: WARN); JPG quality >= 90, 4:4:4, sRGB profile embedded.

Output: `OUT/<slug>_carousel_<N>.<jpg|png>` (numa_common.deliverable_name, the
formats.py names; earlier slides of this slug are removed first), a contact sheet
`OUT/carousel_sheet.jpg` to LOOK at, and the `design_render` section of
`OUT/report.json`: {"mode", "source", "slug", "ok", "files", "sheet", "slides":
[{"n", "file", "board"|"component", "ok", "errors", "warnings", "fonts", "text"}],
"errors", "warnings"}.

Needs Python Playwright and its Chromium: `pip install -r requirements.txt`, then
`python -m playwright install chromium` (macOS and Linux). PLAYWRIGHT_BROWSERS_PATH
points at an existing browser folder when one is preinstalled.
"""
from __future__ import annotations

import html
import io
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import claims_scan  # noqa: E402

COMPONENTS_DIR = nc.ASSETS_DIR / "carousel"
COMPONENTS = ("cover", "point", "stat", "myth_fact", "quote", "steps", "offer", "photo", "cta")
LABELS = {"cover": "Cover", "point": "Point", "stat": "Stat", "myth_fact": "Myth vs fact", "quote": "Quote",
          "steps": "Steps", "offer": "Offer", "photo": "Photo", "cta": "End slide"}
SCHEMA = "carousel.schema.json"
SIZE = (1080, 1350)
MIN_SLIDES, MAX_SLIDES = 2, 10
BOARD_GAP = 80                       # Design canvas: 80 px between frames in a row
NOTE_GAP = 120                       # and 120 px between rows
JPEG_QUALITY = 92
MIN_JPEG_QUALITY = 90
BLANK_MIN_DETAIL = 0.003             # share of pixels that differ from the background colour
BLANK_TOLERANCE = 12                 # 0-255 per channel
LOAD_TIMEOUT_MS = 30000
SETTLE_TIMEOUT_MS = 20000
PRICE_PLACEHOLDER = "[PRICE]"
INK_DEFAULT = "#133037"              # the wordmark's ink; brand.json palette has no text colour yet
INSTALL_FIX = "pip install -r requirements.txt, then python -m playwright install chromium"
# Bundled open-licensed fonts (SIL OFL 1.1; assets/fonts/OFL-*.txt): family -> {style: file}.
BUNDLED_FONTS = {
    "fraunces": ("Fraunces", {"normal": "Fraunces.woff2", "italic": "Fraunces-Italic.woff2"}),
    "inter": ("Inter", {"normal": "Inter.woff2"}),
}
AUTO_FIELDS = {"component", "slide_title", "page", "brand_name", "wordmark", "photo", "photo_alt", "photo_position",
               "price", "price_note"}
TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
IF_BLOCK = re.compile(r"[ \t]*<!--if:([a-z0-9_]+)-->\n?(.*?)<!--/if:\1-->\n?", re.S)
SLIDE_MARKERS = re.compile(r"<!--/?slide-->\n?")
BLOB_REF = re.compile(r"/_blob/([A-Za-z0-9_.-]+)")
SAFE_BOARD = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*\.dc\.html$")
DOLLARS = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")


# --------------------------------------------------------------------------- brand data
def palette(brand: dict) -> dict[str, str]:
    colors = dict(nc.fact(brand.get("palette")) or {})
    for key in ("cream", "cedar_ember", "water_teal", "caption_gold"):
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colors.get(key, ""))):
            raise nc.UserError(f"brand.json palette.{key} must be a #RRGGBB colour")
    colors.setdefault("ink", INK_DEFAULT)
    return {k: v for k, v in colors.items() if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)}


def brand_name(brand: dict) -> str:
    name = nc.fact(nc.dig(brand, "business.name")) or {}
    return name.get("full") or name.get("short") or "NUMA"


def _price_text(price: dict) -> str | None:
    if not isinstance(price, dict) or price.get("status") == "needs_katie" or price.get("value") is None:
        return None
    if price.get("display"):
        return str(price["display"])
    value = price["value"]
    amount = f"{value:g}" if isinstance(value, (int, float)) else str(value)
    return f"${amount}" if price.get("currency", "USD") == "USD" else f"{amount} {price['currency']}"


def offers(brand: dict) -> list[dict]:
    """Every priced thing in brand.json: offerings.offers[] then offerings.sessions[]."""
    out = []
    for o in nc.fact(nc.dig(brand, "offerings.offers")) or []:
        out.append({"name": o.get("name", ""), "price": _price_text(o.get("price")), "note": o.get("what") or ""})
    for s in nc.fact(nc.dig(brand, "offerings.sessions")) or []:
        price = s.get("price") or {}
        out.append({"name": s.get("name", ""), "price": _price_text(price), "note": price.get("unit") or ""})
    return [o for o in out if o["name"]]


def find_offer(brand: dict, name: str) -> dict | None:
    key = " ".join(name.lower().split())
    return next((o for o in offers(brand) if " ".join(o["name"].lower().split()) == key), None)


def known_prices(brand: dict) -> set[str]:
    return {re.sub(r"\s", "", o["price"]) for o in offers(brand) if o["price"]}


# --------------------------------------------------------------------------- templates
def template_path(component: str, kind: str) -> Path:
    return COMPONENTS_DIR / f"{component}.{'dc.html' if kind == 'dc' else 'html'}"


def template_text(component: str, kind: str) -> str:
    p = template_path(component, kind)
    if not p.is_file():
        raise nc.UserError(f"component template missing: {p}")
    return p.read_text(encoding="utf-8")


def slide_markup(text: str) -> str:
    m = re.search(r"<!--slide-->\n(.*?)\n<!--/slide-->", text, re.S)
    if not m:
        raise nc.UserError("component template has no <!--slide--> ... <!--/slide--> block")
    return m.group(1)


def template_fields(component: str) -> tuple[set[str], set[str]]:
    """(required, optional) spec fields of a component, read from its template."""
    markup = slide_markup(template_text(component, "html"))
    optional_blocks = {m.group(1): m.group(2) for m in IF_BLOCK.finditer(markup)}
    outside = IF_BLOCK.sub("", markup)

    def spec_tokens(s: str) -> set[str]:
        return {t for t in TOKEN.findall(s) if t not in AUTO_FIELDS and not t.startswith("color.")}

    required = spec_tokens(outside)
    optional = set().union(*[spec_tokens(b) for b in optional_blocks.values()]) - required if optional_blocks else set()
    return required, optional


def rich(text: str, accent: str) -> str:
    """Field text -> markup: HTML-escaped, *emphasis* in italic accent, line breaks kept."""
    out = html.escape(str(text).strip(), quote=False)
    out = re.sub(r"\*([^*\n]+)\*", lambda m: f'<em style="font-style: italic; color: {accent}">{m.group(1)}</em>', out)
    return out.replace("\n", "<br>")


def plain(text: str) -> str:
    return re.sub(r"\*([^*\n]+)\*", r"\1", str(text)).replace("\n", " ").strip()


def fill(template: str, values: dict[str, str], present: set[str]) -> str:
    """Resolve <!--if:field--> blocks (kept when the field is given) and every {{token}}."""
    out = IF_BLOCK.sub(lambda m: m.group(2) if m.group(1) in present else "", template)
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return ""
        return values[key]

    out = TOKEN.sub(sub, out)
    if missing:
        raise nc.UserError(f"no value for {', '.join(sorted(set(missing)))}")
    return out


# --------------------------------------------------------------------------- carousel.json
class Problems:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def load_spec(path: str | Path) -> dict:
    spec = nc.read_json(path, "carousel.json")
    errs = nc.schema_errors(SCHEMA, spec)
    if errs:
        shown = "; ".join(errs[:6]) + (f"; and {len(errs) - 6} more" if len(errs) > 6 else "")
        raise nc.UserError(f"{path}: not a valid carousel.json: {shown}")
    return spec


def resolve_photo(raw: str, spec_dir: Path) -> Path | None:
    p = Path(raw).expanduser()
    for cand in ([p] if p.is_absolute() else [spec_dir / p, nc.PLUGIN_ROOT / p]):
        if cand.is_file():
            return cand.resolve()
    return None


def count_rule(n: int, probs: Problems) -> None:
    if not MIN_SLIDES <= n <= MAX_SLIDES:
        probs.error(f"{n} slides: an Instagram carousel has {MIN_SLIDES}-{MAX_SLIDES}")
        return
    out = next((o for o in nc.config_value("formats.outputs", []) if o.get("id") == "carousel"), {})
    lo, hi = (out.get("count") or [MIN_SLIDES, MAX_SLIDES])[:2]
    if not lo <= n <= hi:
        probs.warn(f"{n} slides; config formats carousel count is {lo}-{hi}")


def scan(text: str, where: str, probs: Problems) -> None:
    for hit in claims_scan.scan_text(text, where=where):
        (probs.error if hit.severity == "fail" else probs.warn)(hit.line())


def price_rules(text: str, where: str, prices: set[str], probs: Problems) -> None:
    if PRICE_PLACEHOLDER in text:
        probs.error(f"{where}: price placeholder {PRICE_PLACEHOLDER} left; set the price in brand.json "
                    f"(/brand-setup) or use another slide")
    for m in DOLLARS.findall(text):
        if re.sub(r"\s", "", m) not in prices:
            probs.warn(f"{where}: price {m} is not a brand.json price; prices come from brand.json (offer component)")


def prepare(spec: dict, spec_dir: Path, brand: dict, probs: Problems, *, image: Callable[[str, Path | None], str],
            price_missing: Callable[[str], None]) -> list[dict]:
    """Per slide: the values to fill the template with. `image(key, path)` gives an image url."""
    colors = palette(brand)
    accent = colors["cedar_ember"]
    total = len(spec["slides"])
    slides = []
    for n, s in enumerate(spec["slides"], 1):
        comp = s["component"]
        where = f"slide {n} ({comp})"
        fields = {k: v for k, v in (s.get("fields") or {}).items() if isinstance(v, str) and v.strip()}
        required, optional = template_fields(comp)
        for f in sorted(required - set(fields)):
            probs.error(f"{where}: field {f!r} is required")
        values = {f"color.{k}": v for k, v in colors.items()}
        values.update({k: rich(v, accent) for k, v in fields.items()})
        values.update(component=comp, slide_title=html.escape(f"{n} · {LABELS[comp]}"), page=f"{n} / {total}",
                      brand_name=html.escape(brand_name(brand)))
        values["wordmark"] = image("wordmark", nc.brand_asset("wordmark")) if comp == "cta" else ""
        values["photo"] = values["photo_alt"] = values["photo_position"] = ""
        if comp == "photo":
            path = resolve_photo(s["photo"], spec_dir)
            if path is None:
                probs.error(f"{where}: photo not found: {s['photo']}")
            values["photo"] = image(s["photo"], path)
            values["photo_alt"] = html.escape(s.get("photo_alt") or plain(fields.get("caption", "")))
            values["photo_position"] = s.get("photo_position", "50% 50%")
        values["price"] = values["price_note"] = ""
        if comp == "offer" and "offer" in fields:
            offer = find_offer(brand, fields["offer"])
            if offer is None:
                names = ", ".join(o["name"] for o in offers(brand))
                probs.error(f"{where}: offer {fields['offer']!r} is not in brand.json offerings ({names})")
            else:
                values["offer"] = html.escape(offer["name"])
                values["price_note"] = html.escape(offer["note"])
                if offer["price"]:
                    values["price"] = html.escape(offer["price"])
                else:
                    values["price"] = PRICE_PLACEHOLDER
                    price_missing(f"{where}: the price of {offer['name']!r} is needs_katie in brand.json")
        text = " ".join(plain(fields[k]) for k in fields)
        scan(" ".join(plain(v) for v in fields.values()), where, probs)
        slides.append({"n": n, "component": comp, "values": values, "present": set(fields) & (required | optional),
                       "text": text, "photo_key": s.get("photo")})
    scan(spec["caption"], "caption", probs)
    for tag in spec.get("hashtags") or []:
        scan(tag, "hashtags", probs)
    prices = known_prices(brand)
    for sl in slides:
        price_rules(sl["text"], f"slide {sl['n']}", prices, probs)
    price_rules(spec["caption"], "caption", prices, probs)
    count_rule(len(slides), probs)
    return slides


def validate_spec(path: Path) -> tuple[dict, list[dict], Problems]:
    spec = load_spec(path)
    probs = Problems()
    slides = prepare(spec, path.parent, nc.load_brand(), probs,
                     image=lambda key, p: p.as_uri() if p else "", price_missing=probs.error)
    return spec, slides, probs


# --------------------------------------------------------------------------- build (canvas files)
def board_file(n: int) -> str:
    return "Main.dc.html" if n == 1 else f"Slide{n:02d}.dc.html"


def canvas_index(spec: dict, slides: list[dict], created_at: str) -> dict:
    w, h = SIZE
    boards, order = {}, []
    for sl in slides:
        f = board_file(sl["n"])
        boards[f] = {"x": (sl["n"] - 1) * (w + BOARD_GAP), "y": 0, "w": w, "h": h,
                     "title": f"{sl['n']} · {LABELS[sl['component']]}"}
        order.append(f)
    when = f"Posts {spec['date']}. " if spec.get("date") else ""
    note = (f"{when}Edit any slide right here; the post is rendered from this canvas at posting time, "
            f"so your edits go out as they are.\n\nCaption:\n{spec['caption']}")
    return {"v": 3, "createdOnFiles": {"v": 1, "at": created_at}, "title": spec["title"], "launch": {"view": "canvas"},
            "pages": [], "boards": boards, "order": order,
            "notes": {"brief": {"x": 0, "y": h + NOTE_GAP, "w": w, "text": note}}, "designSystems": []}


def upload_name(key: str, path: Path) -> str:
    stem = "wordmark" if key == "wordmark" else nc.slugify(path.stem, 40)
    return f"{stem}{path.suffix.lower()}"


def cmd_build(args) -> int:
    path = Path(args.carousel).expanduser().resolve()
    root = Path(args.root).expanduser().resolve()
    spec = load_spec(path)
    brand = nc.load_brand()
    probs = Problems()
    blobs = (spec.get("canvas") or {}).get("blobs") or {}
    uploads: dict[str, Path] = {}

    def image(key: str, p: Path | None) -> str:
        if p is not None:
            uploads[key] = p
        return blobs.get(key, "")

    slides = prepare(spec, path.parent, brand, probs, image=image, price_missing=probs.warn)
    up_dir = root / "uploads"
    needed = []
    for key, p in uploads.items():
        target = up_dir / upload_name(key, p)
        if args.uploads_only or key not in blobs:
            up_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        needed.append({"key": key, "file": str(target), "blob": blobs.get(key)})
    if args.uploads_only:
        result = {"ok": not probs.errors, "uploads": needed, "errors": probs.errors, "warnings": probs.warnings}
        return finish_simple(result, args.json, lambda: [f"upload {u['file']}  (canvas.blobs key {u['key']!r})" for u in needed])
    missing = [u for u in needed if not u["blob"]]
    for u in missing:
        probs.error(f"image {u['key']!r} is not uploaded yet: upload {u['file']} as an asset and record its "
                    f"/_blob/<id> url in carousel.json canvas.blobs[{u['key']!r}]")
    if probs.errors:
        return finish_simple({"ok": False, "errors": probs.errors, "warnings": probs.warnings}, args.json, list)
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    for old in project.glob("*.dc.html"):
        old.unlink()
    files = {}
    for sl in slides:
        doc = SLIDE_MARKERS.sub("", fill(template_text(sl["component"], "dc"), sl["values"], sl["present"]))
        f = board_file(sl["n"])
        (project / f).write_text(doc, encoding="utf-8")
        files[f"project/{f}"] = f"project/{f}"
    created = args.created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    nc.write_json(project / "canvas.json", canvas_index(spec, slides, created))
    result = {"ok": True, "root": str(root), "index": str(project / "canvas.json"), "boards": list(files),
              "files": files, "uploads": needed, "warnings": probs.warnings}
    return finish_simple(result, args.json, lambda: [f"wrote {root / f}" for f in ["project/canvas.json", *files]])


def finish_simple(result: dict, as_json: bool, lines: Callable[[], list[str]]) -> int:
    for w in result.get("warnings", []):
        nc.warn(w)
    for e in result.get("errors", []):
        nc.error_line(e)
    if as_json:
        nc.print_json(result)
    elif result.get("ok"):
        for line in lines():
            print(line)
    return 0 if result.get("ok") else 1


# --------------------------------------------------------------------------- browser
PROBE_JS = r"""
() => {
  const W = 1080, H = 1350, GLYPH_SLACK_EM = 0.3;
  const slide = document.querySelector('[data-slide]') || (() => {
    let best = null, area = 0;
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect(), a = r.width * r.height;
      if (a > area + 1) { area = a; best = el; }
    }
    return best;
  })();
  const scope = slide || document.body;
  const r = scope.getBoundingClientRect();
  const out = {doc: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
               root: [r.x, r.y, r.width, r.height], text: scope.innerText || '', used: [], failed: [], overflow: []};
  const loaded = {};
  for (const f of document.fonts) {
    const fam = f.family.replace(/^["']|["']$/g, '').toLowerCase();
    const style = f.style === 'normal' ? 'normal' : 'italic';
    if (f.status === 'loaded') { (loaded[fam] = loaded[fam] || {})[style] = true; }
    else if (f.status === 'error') { out.failed.push(f.family + ' ' + f.style); }
  }
  const decorative = (el) => !!el.closest('[aria-hidden="true"]');
  const textEls = new Set();
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.nodeValue.trim() && n.parentElement) textEls.add(n.parentElement);
  }
  const used = new Map();
  for (const el of textEls) {
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const fam = cs.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '');
    const style = cs.fontStyle === 'normal' ? 'normal' : 'italic';
    const key = fam.toLowerCase() + '|' + style;
    if (!used.has(key)) used.set(key, {family: fam, style: style,
      loaded: !!(loaded[fam.toLowerCase()] && loaded[fam.toLowerCase()][style]),
      sample: el.textContent.trim().slice(0, 40)});
  }
  out.used = [...used.values()];
  const boxes = new Set();
  for (const el of scope.querySelectorAll('[data-fit]')) boxes.add(el);
  for (const el of [scope, ...scope.querySelectorAll('*')]) {
    const cs = getComputedStyle(el);
    if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') boxes.add(el);
  }
  const seen = new Set();
  for (const el of boxes) {
    if (decorative(el) || !(el.innerText || '').trim()) continue;
    // glyphs of a tight line-height or an italic overhang poke a few px past the line box: allow 0.3 em;
    // a clipped line or word is always more than that
    let em = parseFloat(getComputedStyle(el).fontSize) || 16;
    for (const t of textEls) if (el.contains(t)) em = Math.max(em, parseFloat(getComputedStyle(t).fontSize) || 0);
    const dx = el.scrollWidth - el.clientWidth, dy = el.scrollHeight - el.clientHeight;
    if (dx > Math.max(1, GLYPH_SLACK_EM * em) || dy > Math.max(1, GLYPH_SLACK_EM * em)) {
      const field = el.getAttribute('data-fit') || el.tagName.toLowerCase();
      const text = el.innerText.trim().replace(/\s+/g, ' ').slice(0, 70);
      if (seen.has(field + text)) continue;
      seen.add(field + text);
      out.overflow.push({field: field, text: text, over_x: dx, over_y: dy});
    }
  }
  for (const el of textEls) {
    if (decorative(el)) continue;
    const b = el.getBoundingClientRect();
    if (b.width > 0 && (b.left < r.left - 1 || b.top < r.top - 1 || b.right > r.right + 1 || b.bottom > r.bottom + 1)) {
      out.overflow.push({field: el.getAttribute('data-fit') || el.tagName.toLowerCase(),
                         text: el.innerText.trim().replace(/\s+/g, ' ').slice(0, 70), over_x: 0, over_y: 0, outside: true});
    }
  }
  return out;
}
"""

SETTLE_JS = r"""
() => document.body && (document.body.innerText || '').trim().length > 0
      && document.fonts.status === 'loaded'
      && [...document.images].every((i) => i.complete)
"""


def file_url_path(url: str) -> Path:
    raw = url[len("file://"):].split("?")[0].split("#")[0]
    data = re.sub(rb"%([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw.encode("utf-8"))
    return Path(data.decode("utf-8", "replace"))


def sniff_type(data: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    by_ext = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".gif": "image/gif", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
              ".ttf": "font/ttf", ".otf": "font/otf", ".css": "text/css", ".js": "text/javascript",
              ".json": "application/json"}
    if ext in by_ext:
        return by_ext[ext]
    for magic, kind in ((b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg"), (b"GIF8", "image/gif"),
                        (b"wOF2", "font/woff2"), (b"wOFF", "font/woff")):
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:512]:
        return "image/svg+xml"
    return "application/octet-stream"


def google_fonts_css(url: str) -> tuple[str, list[str]]:
    """CSS for a Google Fonts css2 link, pointing at the bundled files; and the families not bundled."""
    css, unknown = [], []
    for raw in re.findall(r"[?&]family=([^:&]+)", url):
        fam = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw.replace("+", " ")).strip()
        bundled = BUNDLED_FONTS.get(fam.lower())
        if not bundled:
            unknown.append(fam)
            continue
        name, files = bundled
        for style, file in files.items():
            src = (nc.FONTS_DIR / file).as_uri()
            css.append(f'@font-face {{ font-family: "{name}"; src: url("{src}") format("woff2"); '
                       f"font-weight: 100 900; font-style: {style}; }}")
    return "\n".join(css) + "\n", unknown


class Browser:
    """One headless Chromium for a run; pages are served from local files only."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise nc.UserError(f"Python Playwright is not installed: {INSTALL_FIX}") from None
        self._pw_cm = sync_playwright()
        self._pw = self._pw_cm.__enter__()
        try:
            self._browser = self._pw.chromium.launch(args=["--force-color-profile=srgb", "--disable-lcd-text"])
        except Exception as e:  # noqa: BLE001 - playwright raises its own Error type
            self._pw_cm.__exit__(None, None, None)
            msg = " ".join(str(e).split())
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                raise nc.UserError(f"Chromium for Playwright is not installed: {INSTALL_FIX}") from None
            raise nc.UserError(f"headless Chromium did not start ({msg[:160]}); fix: {INSTALL_FIX}") from None
        self._ctx = self._browser.new_context(viewport={"width": SIZE[0], "height": SIZE[1]}, device_scale_factor=1)
        self.virtual: dict[str, tuple[bytes, str]] = {}
        self.files: dict[str, Path] = {}
        self.blobs: dict[str, Path] = {}
        self.roots: list[Path] = []
        self.blocked: list[str] = []
        self.missing_blobs: list[str] = []
        self.unknown_fonts: list[str] = []
        self._ctx.route("**/*", self._route)

    def close(self) -> None:
        try:
            self._ctx.close()
            self._browser.close()
        finally:
            self._pw_cm.__exit__(None, None, None)

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _route(self, route) -> None:
        url = route.request.url
        try:
            if url in self.virtual:
                body, kind = self.virtual[url]
                route.fulfill(status=200, body=body, content_type=kind)
            elif url in self.files:
                data = self.files[url].read_bytes()
                route.fulfill(status=200, body=data, content_type=sniff_type(data, self.files[url].name))
            elif url.startswith("file:") and "/_blob/" in url:
                bid = url.split("/_blob/", 1)[1].split("?")[0].split("/")[0]
                path = self.blobs.get(bid)
                if path is None:
                    self.missing_blobs.append(bid)
                    route.abort()
                else:
                    data = path.read_bytes()
                    route.fulfill(status=200, body=data, content_type=sniff_type(data, path.name))
            elif "fonts.googleapis.com/css" in url:
                css, unknown = google_fonts_css(url)
                self.unknown_fonts.extend(f for f in unknown if f not in self.unknown_fonts)
                route.fulfill(status=200, body=css, content_type="text/css; charset=utf-8")
            elif url.startswith("file:"):
                path = file_url_path(url)
                if path.is_file() and any(path.resolve().is_relative_to(r) for r in self.roots):
                    route.continue_()
                else:
                    self.blocked.append(url)
                    route.abort()
            else:
                self.blocked.append(url)
                route.abort()
        except Exception:  # noqa: BLE001 - a closed page while routing; nothing to serve
            pass

    def render(self, url: str) -> tuple[bytes, dict, list[str]]:
        """Load url, wait for content, fonts and images; return (png, probe, page errors)."""
        from playwright.sync_api import TimeoutError as PwTimeout
        page = self._ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(" ".join(str(e).split())[:200]))
        try:
            page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT_MS)
            try:
                page.wait_for_function(SETTLE_JS, timeout=SETTLE_TIMEOUT_MS)
            except PwTimeout:
                errors.append("the slide did not finish loading (text, fonts or images) within "
                              f"{SETTLE_TIMEOUT_MS // 1000} s")
            page.evaluate("document.fonts.ready.then(() => new Promise((r) => requestAnimationFrame(() => "
                          "requestAnimationFrame(r))))")
            probe = page.evaluate(PROBE_JS)
            png = page.screenshot(clip={"x": 0, "y": 0, "width": SIZE[0], "height": SIZE[1]}, type="png")
        finally:
            page.close()
        return png, probe, errors


# --------------------------------------------------------------------------- slide checks and output
def check_probe(probe: dict, page_errors: list[str], where: str, probs: Problems) -> list[dict]:
    w, h = SIZE
    x, y, rw, rh = probe["root"]
    if abs(rw - w) > 1 or abs(rh - h) > 1 or abs(x) > 1 or abs(y) > 1:
        probs.error(f"{where}: the slide is {round(rw)}x{round(rh)} at ({round(x)},{round(y)}), expected {w}x{h} at (0,0)")
    dw, dh = probe["doc"]
    if dw > w + 1 or dh > h + 1:
        probs.error(f"{where}: the page is {dw}x{dh}, larger than {w}x{h}")
    for f in probe["failed"]:
        probs.error(f"{where}: font {f} failed to load")
    for u in probe["used"]:
        if not u["loaded"]:
            probs.error(f"{where}: font {u['family']} ({u['style']}) is not loaded, text such as {u['sample']!r} would "
                        f"render in a system font; use the bundled Fraunces / Inter")
    for o in probe["overflow"]:
        if o.get("outside"):
            probs.error(f"{where}: text {o['text']!r} ({o['field']}) runs outside the slide")
        else:
            over = max(o["over_x"], o["over_y"])
            probs.error(f"{where}: text does not fit its box ({o['field']}, {over}px over): {o['text']!r}; shorten it")
    for e in page_errors:
        probs.warn(f"{where}: {e}")
    return probe["used"]


def detail_share(img) -> float:
    import numpy as np
    a = np.asarray(img.convert("RGB").resize((270, 338)), dtype=np.int16)
    flat = a.reshape(-1, 3)
    colors, counts = np.unique(flat // 8, axis=0, return_counts=True)
    bg = colors[counts.argmax()] * 8 + 4
    diff = np.abs(flat - bg).max(axis=1)
    return float((diff > BLANK_TOLERANCE).mean())


def srgb_icc() -> bytes | None:
    """littlecms' built-in sRGB profile with its creation date and profile id zeroed (byte-identical output)."""
    try:
        from PIL import ImageCms
        data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    except Exception:  # noqa: BLE001 - Pillow built without littlecms
        return None
    data[24:36] = bytes(12)   # dateTimeNumber
    data[84:100] = bytes(16)  # profile ID (all zero = not computed)
    return bytes(data)


def is_srgb(profile: bytes) -> bool:
    try:
        from PIL import ImageCms
        return "srgb" in ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile))).lower()
    except Exception:  # noqa: BLE001 - unreadable profile
        return False


STD_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
            14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
            49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]


def jpeg_quality(img) -> int | None:
    """Estimate the libjpeg quality of an opened JPEG from its luminance table."""
    q = getattr(img, "quantization", None)
    if not q or 0 not in q:
        return None
    scale = sum(q[0]) * 100.0 / sum(STD_LUMA)
    return round(5000 / scale) if scale > 100 else round((200 - scale) / 2)


def save_slide(png: bytes, path: Path, fmt: str, where: str, probs: Problems) -> None:
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if detail_share(img) < BLANK_MIN_DETAIL:
        probs.error(f"{where}: the slide is blank or near-uniform")
    icc = srgb_icc()
    kw: dict[str, Any] = {"icc_profile": icc} if icc else {}
    if fmt == "jpg":
        img.save(path, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=False, **kw)
    else:
        img.save(path, "PNG", **kw)
    with Image.open(path) as back:
        if back.size != SIZE:
            probs.error(f"{where}: {path.name} is {back.size[0]}x{back.size[1]}, expected {SIZE[0]}x{SIZE[1]}")
        if back.mode != "RGB":
            probs.error(f"{where}: {path.name} is {back.mode}, expected RGB")
        if fmt == "jpg":
            quality = jpeg_quality(back)
            if quality is None or quality < MIN_JPEG_QUALITY:
                probs.error(f"{where}: {path.name} JPEG quality {quality} is under {MIN_JPEG_QUALITY}")
        profile = back.info.get("icc_profile")
        if not profile:
            probs.warn(f"{where}: {path.name} has no embedded sRGB profile (Pillow without littlecms)")
        elif not is_srgb(profile):
            probs.error(f"{where}: {path.name} carries a colour profile that is not sRGB")


def contact_sheet(files: list[Path], out: Path) -> Path | None:
    if not files:
        return None
    from PIL import Image, ImageDraw
    tw, th, pad, cols = 270, 338, 16, min(5, len(files))
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + rows * (th + pad + 28)), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        with Image.open(f) as im:
            thumb = im.convert("RGB").resize((tw, th))
        x, y = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + pad + 28)
        sheet.paste(thumb, (x, y))
        draw.text((x, y + th + 6), str(i + 1), fill=(240, 240, 240))
    path = out / "carousel_sheet.jpg"
    sheet.save(path, "JPEG", quality=88)
    return path


def clear_old(out: Path, slug: str) -> None:
    pat = re.compile(rf"^{re.escape(nc.slugify(slug))}_carousel_\d+\.(jpg|png)$")
    for f in out.iterdir():
        if f.is_file() and pat.match(f.name):
            f.unlink()


def run_render(jobs: list[dict], browser: Browser, out: Path, slug: str, fmt: str, probs: Problems,
               scan_text: bool) -> tuple[list[dict], list[Path]]:
    """Render each job {n, url, label, extra} into OUT and check it."""
    out.mkdir(parents=True, exist_ok=True)
    clear_old(out, slug)
    prices = known_prices(nc.load_brand())
    results, files = [], []
    for job in jobs:
        where = f"slide {job['n']}"
        slide_probs = Problems()
        png, probe, page_errors = browser.render(job["url"])
        fonts = check_probe(probe, page_errors, where, slide_probs)
        text = " ".join(probe["text"].split())
        if scan_text:
            scan(text, where, slide_probs)
        price_rules(text, where, prices, slide_probs)
        path = out / nc.deliverable_name(slug, "carousel", job["n"], fmt)
        save_slide(png, path, fmt, where, slide_probs)
        files.append(path)
        probs.errors.extend(slide_probs.errors)
        probs.warnings.extend(slide_probs.warnings)
        results.append({"n": job["n"], "file": str(path), **job["extra"], "ok": not slide_probs.errors,
                        "errors": slide_probs.errors, "warnings": slide_probs.warnings,
                        "fonts": [f"{u['family']} {u['style']}" for u in fonts], "text": text})
    for bid in sorted(set(browser.missing_blobs)):
        probs.error(f"image /_blob/{bid} is missing locally: read it with the Artifact tool (action read, path {bid}) "
                    f"into the canvas folder's _blob/")
    for fam in browser.unknown_fonts:
        probs.error(f"font family {fam!r} is linked but not bundled (assets/fonts has Fraunces and Inter)")
    for url in sorted(set(browser.blocked)):
        probs.warn(f"blocked a request the slides made: {url[:120]}")
    return results, files


def finish_render(mode: str, source: Path, slug: str, out: Path, results: list[dict], files: list[Path],
                  probs: Problems, as_json: bool) -> int:
    sheet = contact_sheet(files, out)
    data = {"mode": mode, "source": str(source), "slug": slug, "ok": not probs.errors,
            "files": [str(f) for f in files], "sheet": str(sheet) if sheet else None, "slides": results,
            "errors": probs.errors, "warnings": probs.warnings}
    nc.update_report(out, "design_render", data)
    for w in probs.warnings:
        nc.warn(w)
    for e in probs.errors:
        nc.error_line(e)
    if as_json:
        nc.print_json(data)
    else:
        for f in files:
            print(f)
        if sheet:
            print(f"contact sheet: {sheet}")
        print(("OK: " if data["ok"] else "FAILED: ") + f"{len(files)} slides, {len(probs.errors)} errors, "
              f"{len(probs.warnings)} warnings")
    return 0 if data["ok"] else 1


# --------------------------------------------------------------------------- spec mode (fallback)
def spec_pages(slides: list[dict]) -> list[tuple[str, str]]:
    """(virtual url next to the templates, html) per slide: relative links (carousel.css, ../fonts) resolve."""
    pages = []
    for sl in slides:
        doc = fill(template_text(sl["component"], "html"), sl["values"], sl["present"])
        pages.append(((COMPONENTS_DIR / f"_render_{sl['n']:02d}.html").as_uri(), doc))
    return pages


def render_spec(path: Path, out: Path, fmt: str, *, as_json: bool) -> int:
    spec, slides, probs = validate_spec(path)
    if probs.errors:
        for w in probs.warnings:
            nc.warn(w)
        for e in probs.errors:
            nc.error_line(e)
        if as_json:
            nc.print_json({"mode": "spec", "ok": False, "errors": probs.errors, "warnings": probs.warnings})
        return 1
    with Browser() as browser:
        browser.roots = [COMPONENTS_DIR.resolve(), nc.FONTS_DIR.resolve(), nc.ASSETS_DIR.resolve()]
        for sl in slides:
            for key in ("photo", "wordmark"):
                if sl["values"].get(key, "").startswith("file:"):
                    p = file_url_path(sl["values"][key])
                    browser.roots.append(p.parent.resolve())
        jobs = []
        for sl, (url, doc) in zip(slides, spec_pages(slides)):
            browser.virtual[url] = (doc.encode("utf-8"), "text/html; charset=utf-8")
            jobs.append({"n": sl["n"], "url": url, "extra": {"component": sl["component"]}})
        results, files = run_render(jobs, browser, out, spec["slug"], fmt, probs, scan_text=False)
    return finish_render("spec", path, spec["slug"], out, results, files, probs, as_json)


# --------------------------------------------------------------------------- canvas mode
def canvas_layout(folder: Path) -> tuple[Path, dict]:
    for project in (folder / "project", folder):
        if (project / "canvas.json").is_file():
            return project, nc.read_json(project / "canvas.json", "canvas.json")
    raise nc.UserError(f"no canvas.json in {folder} or {folder / 'project'}: read project/canvas.json from the "
                       f"canvas with the Artifact tool first")


def canvas_boards(project: Path, index: dict, probs: Problems) -> list[str]:
    boards = index.get("boards")
    if not isinstance(boards, dict) or not boards:
        raise nc.UserError("canvas.json has no boards (an empty canvas)")
    names = []
    for name, b in boards.items():
        if not name.endswith(".dc.html") or name.startswith("ds/"):
            continue
        if not SAFE_BOARD.match(name) or ".." in name.split("/"):
            raise nc.UserError(f"canvas.json names an unsafe artboard path: {name!r}")
        if not (project / name).is_file():
            probs.error(f"artboard {name} is in canvas.json but was not read into {project}")
            continue
        if (b.get("w"), b.get("h")) != SIZE:
            probs.error(f"artboard {name} is {b.get('w')}x{b.get('h')}, expected {SIZE[0]}x{SIZE[1]}")
        names.append(name)
    rows: dict[int, list[str]] = {}
    for name in names:
        b = boards[name]
        rows.setdefault(int(b.get("y", 0)) // (SIZE[1] // 2), []).append(name)
    return [n for key in sorted(rows) for n in sorted(rows[key], key=lambda m: (boards[m].get("x", 0), m))]


def find_runtime(folder: Path, project: Path, given: str | None) -> Path:
    cands = [Path(given).expanduser()] if given else [project / "support.js", folder / "artifact-type" / "dc-runtime.js",
                                                       project.parent / "artifact-type" / "dc-runtime.js"]
    for c in cands:
        if c.is_file():
            return c.resolve()
    raise nc.UserError("the Design runtime is missing: read artifact-type/dc-runtime.js from the canvas with the "
                       f"Artifact tool into {folder / 'artifact-type'} (or pass --runtime FILE)")


def blob_refs(project: Path, boards: list[str]) -> list[str]:
    ids: list[str] = []
    for name in boards:
        for bid in BLOB_REF.findall((project / name).read_text(encoding="utf-8")):
            if bid not in ids:
                ids.append(bid)
    return ids


def find_blob(bid: str, folder: Path, project: Path) -> Path | None:
    for d in (folder / "_blob", project / "_blob", folder, project):
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and (f.name == bid or f.name.split(".")[0] == bid.split(".")[0]):
                return f.resolve()
    return None


def render_canvas(args) -> int:
    folder = Path(args.dir).expanduser().resolve()
    if not folder.is_dir():
        raise nc.UserError(f"canvas folder not found: {folder}")
    project, index = canvas_layout(folder)
    probs = Problems()
    boards = canvas_boards(project, index, probs)
    ids = blob_refs(project, boards)
    found = {bid: find_blob(bid, folder, project) for bid in ids}
    if args.list_blobs:
        rows = [{"id": bid, "file": str(p) if p else None} for bid, p in found.items()]
        if args.json:
            nc.print_json({"blobs": rows})
        else:
            for r in rows:
                print(f"{r['id']}\t{r['file'] or 'MISSING'}")
        return 0
    runtime = find_runtime(folder, project, args.runtime)
    missing = [bid for bid, p in found.items() if p is None]
    if missing:
        raise nc.UserError(f"{len(missing)} image(s) used on the canvas are not in {folder / '_blob'}: "
                           f"{', '.join(missing)}; read each with the Artifact tool (action read, path <id>)")
    slug = nc.slugify(args.slug or index.get("title") or folder.name)
    count_rule(len(boards), probs)
    if not boards:
        raise nc.UserError("; ".join(probs.errors) or "the canvas has no 1080x1350 artboards")
    with Browser() as browser:
        browser.roots = [project.resolve(), folder]
        browser.files[(project / "support.js").as_uri()] = runtime
        browser.blobs = {bid: p for bid, p in found.items() if p}
        jobs = [{"n": n, "url": (project / name).as_uri(),
                 "extra": {"board": name, "title": (index["boards"][name] or {}).get("title")}}
                for n, name in enumerate(boards, 1)]
        results, files = run_render(jobs, browser, Path(args.out).expanduser().resolve(), slug, args.format, probs,
                                    scan_text=True)
    return finish_render("canvas", folder, slug, Path(args.out).expanduser().resolve(), results, files, probs, args.json)


# --------------------------------------------------------------------------- setup check hook
def selftest(work: Path) -> tuple[bool, str]:
    """Render a 2-slide carousel (cover + end slide) through the spec path: (ok, one-line detail)."""
    spec = {"schema_version": 1, "slug": "setup-check", "title": "Setup check", "caption": "Setup check.",
            "slides": [{"component": "cover", "fields": {"kicker": "Setup check", "title": "Slides render here",
                                                         "subtitle": "Bundled fonts, no network."}},
                       {"component": "cta", "fields": {"title": "Ready for carousels.", "button": "numawellness.org"}}]}
    work.mkdir(parents=True, exist_ok=True)
    path = work / "carousel.json"
    nc.write_json(path, spec)
    out = work / "out"
    try:
        _, slides, probs = validate_spec(path)
        if probs.errors:
            return False, probs.errors[0]
        with Browser() as browser:
            browser.roots = [COMPONENTS_DIR.resolve(), nc.FONTS_DIR.resolve(), nc.ASSETS_DIR.resolve()]
            jobs = []
            for sl, (url, doc) in zip(slides, spec_pages(slides)):
                browser.virtual[url] = (doc.encode("utf-8"), "text/html; charset=utf-8")
                jobs.append({"n": sl["n"], "url": url, "extra": {}})
            results, files = run_render(jobs, browser, out, "setup-check", "jpg", probs, scan_text=False)
    except nc.UserError as e:
        return False, str(e)
    if probs.errors:
        return False, probs.errors[0]
    return True, f"headless Chromium rendered {len(files)} slides at {SIZE[0]}x{SIZE[1]} with the bundled fonts ({out})"


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="design_render.py", description="Build and render NUMA component carousels "
                      "(Claude Design canvas or the bundled components) as 1080x1350 slides.")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=nc.ArgParser)
    v = sub.add_parser("validate", help="check carousel.json: schema, claims, prices, photos")
    v.add_argument("carousel", metavar="CAROUSEL_JSON")
    v.add_argument("--json", action="store_true", help="print one JSON report")
    b = sub.add_parser("build", help="write the canvas files (canvas.json + one .dc.html per slide) under ROOT")
    b.add_argument("carousel", metavar="CAROUSEL_JSON")
    b.add_argument("--root", required=True, help="folder that will hold project/ (inside the scratchpad or working directory)")
    b.add_argument("--uploads-only", action="store_true", help="copy the images to upload into ROOT/uploads and list them")
    b.add_argument("--created-at", help="createdOnFiles timestamp (ISO 8601, default now in UTC)")
    b.add_argument("--json", action="store_true", help="print one JSON report")
    c = sub.add_parser("canvas", help="render a canvas folder read back with the Artifact tool")
    c.add_argument("dir", metavar="DIR")
    c.add_argument("--out", help="output folder for the slides and report.json")
    c.add_argument("--slug", help="file-name stem (default: from the canvas title)")
    c.add_argument("--runtime", help="the Design type's dc-runtime.js (default: DIR/artifact-type/dc-runtime.js)")
    c.add_argument("--format", choices=("jpg", "png"), default="jpg")
    c.add_argument("--list-blobs", action="store_true", help="list the /_blob/ image ids the artboards use, then exit")
    c.add_argument("--json", action="store_true", help="print one JSON report")
    s = sub.add_parser("spec", help="fallback: render carousel.json with the bundled components")
    s.add_argument("carousel", metavar="CAROUSEL_JSON")
    s.add_argument("--out", required=True, help="output folder for the slides and report.json")
    s.add_argument("--format", choices=("jpg", "png"), default="jpg")
    s.add_argument("--json", action="store_true", help="print one JSON report")
    args = ap.parse_args(argv)

    if args.cmd == "validate":
        path = Path(args.carousel).expanduser().resolve()
        spec, slides, probs = validate_spec(path)
        result = {"ok": not probs.errors, "slides": len(slides), "errors": probs.errors, "warnings": probs.warnings}
        return finish_simple(result, args.json, lambda: [f"OK: {spec['slug']}: {len(slides)} slides pass the schema, "
                                                         f"claims and price checks"])
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "canvas":
        if not args.list_blobs and not args.out:
            raise nc.UsageError("canvas needs --out (or --list-blobs)")
        return render_canvas(args)
    return render_spec(Path(args.carousel).expanduser().resolve(), Path(args.out).expanduser().resolve(),
                       args.format, as_json=args.json)


if __name__ == "__main__":
    nc.run_cli(main)
