#!/usr/bin/env python3
"""Generate the Numa carousel component library (developer tool; T14, R329).

Writes skills/numa-reel-editor/assets/carousel/<component>.html (plain HTML, the spec fallback)
and <component>.dc.html (a Claude Design artboard) for every component. The two files of a
component share byte-identical slide markup between <!--slide--> and <!--/slide-->, so the canvas
and the fallback render the same pixels. Edit the components here, never the generated files;
tests/unit/test_design_render.py checks that the committed files match this generator.

Usage:
    python3 tools/gen_carousel_components.py [--check] [--charset]

--check    exit 1 when a committed file differs from what this script generates (writes nothing)
--charset  also rewrite assets/fonts/carousel_charset.json from the bundled fonts' cmaps
           (needs fontTools: pip install fonttools brotli)

Tokens: {{field}} spec fields; {{color.<role>}} brand palette roles (design_render.PALETTE_ROLES);
{{component}}, {{slide_title}}, {{page}}, {{brand_name}}, {{photo}}, {{photo_alt}},
{{photo_position}}, {{wordmark}}, {{price}}, {{price_note}} filled by design_render.py.
<!--if:field--> ... <!--/if:field--> blocks are dropped when the optional field is not given.

Look (owners' brief, 2026-11): photo-led by default; text-led slides restrained and editorial,
large light display type that fills the band between header and footer; no flyer or poster
devices (no dark price cards, badges or quote cards). Display: Hanken Grotesk Light (stand-in for
Domaine Sans Text Light); body: Nunito Sans (stand-in for Avenir Next).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "skills" / "numa-reel-editor" / "assets" / "carousel"
FONTS = REPO / "skills" / "numa-reel-editor" / "assets" / "fonts"

DISPLAY = "'Hanken Grotesk', 'Helvetica Neue', Arial, sans-serif"
BODY = "'Nunito Sans', 'Avenir Next', Avenir, sans-serif"
GOOGLE_FONTS = ("https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@200..700"
                "&amp;family=Nunito+Sans:wght@300..800&amp;display=swap")

ROOT = ('<div data-slide="{{component}}" style="width: 1080px; height: 1350px; box-sizing: border-box; '
        'padding: 96px 96px 80px; display: flex; flex-direction: column; gap: 48px; overflow: hidden; '
        'background: {{color.bg}}; color: {{color.ink}}; font-family: ' + BODY + '">')
PHOTO_ROOT = ('<div data-slide="{{component}}" style="width: 1080px; height: 1350px; box-sizing: border-box; '
              'display: flex; flex-direction: column; overflow: hidden; background: {{color.bg}}; '
              'color: {{color.ink}}; font-family: ' + BODY + '">')

HEADER = (
    '<div style="display: flex; align-items: center; gap: 18px; height: 40px; flex-shrink: 0">\n'
    '<div style="width: 48px; height: 4px; flex-shrink: 0; background: {{color.accent}}"></div>\n'
    '<p data-fit="kicker" style="margin: 0; max-width: 820px; overflow: hidden; white-space: nowrap; font-size: 26px; '
    'line-height: 40px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: {{color.ink}}">{{kicker}}</p>\n'
    '</div>'
)

FOOTER = (
    '<div style="display: flex; align-items: center; justify-content: space-between; gap: 32px; height: 72px; flex-shrink: 0; '
    'box-sizing: border-box; border-top: 2px solid {{color.rule}}; padding-top: 26px">\n'
    '<p style="margin: 0; font-size: 28px; line-height: 44px; font-weight: 400; letter-spacing: 0.02em; color: {{color.ink}}">{{brand_name}}</p>\n'
    '<p style="margin: 0; font-size: 28px; line-height: 44px; font-weight: 600; letter-spacing: 0.08em; color: {{color.ink}}">{{page}}</p>\n'
    '</div>'
)


def content(inner: str, justify: str = "center", gap: int = 40, extra: str = "") -> str:
    return ('<div data-fit="content" style="flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; '
            f'justify-content: {justify}; gap: {gap}px{extra}">\n{inner}\n</div>')


def text(tag: str, field: str, *, font: str, size: int, lh: float, lines: int, weight: int = 400,
         color: str = "{{color.ink}}", extra: str = "") -> str:
    lhpx = round(size * lh)
    wrap = "; text-wrap: pretty" if font == BODY else ""
    return (f'<{tag} data-fit="{field}" style="margin: 0; max-height: {lhpx * lines}px; overflow: hidden; font-family: {font}; '
            f'font-size: {size}px; line-height: {lhpx}px; font-weight: {weight}; color: {color}{wrap}{extra}">{{{{{field}}}}}</{tag}>')


def opt(field: str, markup: str) -> str:
    return f"<!--if:{field}-->\n{markup}\n<!--/if:{field}-->"


RULE = '<div style="width: 120px; height: 4px; flex-shrink: 0; background: {{color.accent}}"></div>'
TIGHT = "; letter-spacing: -0.02em; text-wrap: balance"


def slide(*parts: str) -> str:
    return "\n".join([ROOT, *parts, "</div>"])


def photo_slide(height: int, *panel: str, gap: int = 28) -> str:
    return "\n".join([
        PHOTO_ROOT,
        ('<img src="{{photo}}" alt="{{photo_alt}}" style="display: block; width: 1080px; height: ' + str(height) +
         'px; flex-shrink: 0; object-fit: cover; object-position: {{photo_position}}">'),
        ('<div style="flex: 1; min-height: 0; box-sizing: border-box; padding: 52px 96px 80px; display: flex; '
         f'flex-direction: column; gap: {gap}px">'),
        HEADER,
        *panel,
        FOOTER,
        "</div>",
        "</div>",
    ])


C: dict[str, tuple[str, str]] = {}

C["cover"] = ("Cover (text)", slide(
    HEADER,
    content("\n".join([
        text("h1", "title", font=DISPLAY, size=132, lh=1.0, lines=5, weight=300, extra=TIGHT),
        RULE,
        opt("subtitle", text("p", "subtitle", font=BODY, size=44, lh=1.36, lines=3)),
    ]), gap=52),
    FOOTER,
))

C["cover_photo"] = ("Cover (photo)", photo_slide(
    800,
    content(text("h1", "title", font=DISPLAY, size=84, lh=1.04, lines=3, weight=300, extra=TIGHT), justify="flex-start"),
))

C["point"] = ("Numbered point", slide(
    HEADER,
    content("\n".join([
        '<p data-fit="number" style="margin: 0; max-width: 400px; overflow: hidden; white-space: nowrap; font-family: '
        + DISPLAY + '; font-weight: 300; font-size: 200px; line-height: 200px; color: {{color.accent}}">{{number}}</p>',
        text("h2", "title", font=DISPLAY, size=88, lh=1.04, lines=3, weight=300, extra=TIGHT),
        text("p", "body", font=BODY, size=42, lh=1.45, lines=6),
    ]), gap=48),
    FOOTER,
))

C["stat"] = ("Stat callout", slide(
    HEADER,
    content("\n".join([
        '<p data-fit="stat" style="margin: 0; max-height: 280px; overflow: hidden; white-space: nowrap; font-family: '
        + DISPLAY + '; font-weight: 200; font-size: 260px; line-height: 280px; letter-spacing: -0.04em; color: {{color.ink}}">{{stat}}</p>',
        RULE,
        text("h2", "label", font=DISPLAY, size=76, lh=1.08, lines=3, weight=300, extra=TIGHT),
        opt("body", text("p", "body", font=BODY, size=42, lh=1.45, lines=4)),
        opt("source", text("p", "source", font=BODY, size=28, lh=1.4, lines=2)),
    ]), gap=44),
    FOOTER,
))

C["myth_fact"] = ("Myth vs fact", slide(
    HEADER,
    content("\n".join([
        '<div style="display: flex; flex-direction: column; gap: 22px">',
        '<p style="margin: 0; font-size: 28px; line-height: 40px; font-weight: 700; letter-spacing: 0.16em; '
        'text-transform: uppercase; color: {{color.ink}}">Myth</p>',
        text("p", "myth", font=DISPLAY, size=68, lh=1.12, lines=4, weight=300,
             extra="; text-decoration: line-through; text-decoration-thickness: 3px; text-decoration-color: {{color.accent}}"),
        '</div>',
        '<div style="display: flex; flex-direction: column; gap: 22px; box-sizing: border-box; padding: 52px 56px; '
        'background: {{color.panel}}">',
        '<p style="margin: 0; font-size: 28px; line-height: 40px; font-weight: 700; letter-spacing: 0.16em; '
        'text-transform: uppercase; color: {{color.ink}}">Fact</p>',
        text("p", "fact", font=DISPLAY, size=68, lh=1.12, lines=5, weight=400),
        '</div>',
    ]), gap=56),
    FOOTER,
))

C["faq"] = ("First-timer FAQ", slide(
    HEADER,
    content("\n".join([
        text("h2", "question", font=DISPLAY, size=124, lh=1.0, lines=3, weight=300, extra=TIGHT),
        RULE,
        text("p", "answer", font=BODY, size=50, lh=1.46, lines=6),
    ]), gap=64),
    FOOTER,
))


def step(n: int) -> str:
    return "\n".join([
        '<div style="display: flex; align-items: baseline; gap: 36px">',
        '<p style="margin: 0; width: 64px; flex-shrink: 0; font-family: ' + DISPLAY + '; font-weight: 300; font-size: 72px; '
        'line-height: 72px; color: {{color.accent}}">' + str(n) + '</p>',
        text("p", f"step{n}", font=BODY, size=46, lh=1.36, lines=3, weight=400, extra="; flex: 1; min-width: 0"),
        '</div>',
    ])


C["steps"] = ("Steps list", slide(
    HEADER,
    content("\n".join([
        text("h2", "title", font=DISPLAY, size=92, lh=1.04, lines=3, weight=300, extra=TIGHT),
        '<div style="display: flex; flex-direction: column; gap: 44px; border-top: 2px solid {{color.rule}}; padding-top: 48px">',
        step(1), step(2), step(3),
        opt("step4", step(4)),
        '</div>',
    ]), gap=56),
    FOOTER,
))

C["photo"] = ("Photo + caption", photo_slide(
    820,
    content(text("p", "caption", font=DISPLAY, size=60, lh=1.14, lines=4, weight=300, extra=TIGHT), justify="flex-start"),
))

C["quote"] = ("Quote over the member's photo", photo_slide(
    760,
    content("\n".join([
        text("p", "quote", font=DISPLAY, size=54, lh=1.2, lines=4, weight=300, extra=TIGHT),
        '<p style="margin: 0; font-size: 30px; line-height: 40px; font-weight: 700; color: {{color.ink}}">{{name}}'
        '<!--if:role--><span style="font-weight: 400"> · {{role}}</span><!--/if:role--></p>',
    ]), justify="flex-start", gap=24),
))

C["offer"] = ("Offer (photo, calm)", photo_slide(
    660,
    content("\n".join([
        text("h2", "title", font=DISPLAY, size=68, lh=1.06, lines=2, weight=300, extra=TIGHT),
        '<p data-fit="offer" style="margin: 0; max-height: 96px; overflow: hidden; font-size: 36px; line-height: 48px; '
        'font-weight: 400; color: {{color.ink}}"><span style="font-weight: 700">{{offer}}</span> · {{price}} {{price_note}}</p>',
        opt("details", text("p", "details", font=BODY, size=34, lh=1.42, lines=2)),
        text("p", "cta", font=BODY, size=34, lh=1.42, lines=1, weight=600,
             extra="; white-space: nowrap; text-decoration: underline; text-decoration-color: {{color.accent}}; "
                   "text-decoration-thickness: 3px; text-underline-offset: 10px"),
    ]), justify="flex-start", gap=22),
))

C["cta"] = ("End slide", "\n".join([
    ROOT,
    content("\n".join([
        '<img src="{{wordmark}}" alt="Numa" style="display: block; width: 400px; height: 88px; flex-shrink: 0">',
        RULE,
        text("h2", "title", font=DISPLAY, size=96, lh=1.04, lines=4, weight=300, extra=TIGHT + "; text-align: center"),
        opt("body", text("p", "body", font=BODY, size=42, lh=1.4, lines=3, extra="; text-align: center")),
        ('<p data-fit="button" style="margin: 0; max-width: 888px; box-sizing: border-box; overflow: hidden; '
         'white-space: nowrap; padding: 0 48px; border: 2px solid {{color.ink}}; border-radius: 48px; color: {{color.ink}}; '
         'font-size: 34px; line-height: 88px; font-weight: 600">{{button}}</p>'),
    ]), justify="center", gap=48, extra="; align-items: center; padding-bottom: 96px"),
    FOOTER,
    "</div>",
]))

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="numa-component" content="{name}">
<title>{{{{slide_title}}}}</title>
<link rel="stylesheet" href="carousel.css">
</head>
<body>
<!--slide-->
{markup}
<!--/slide-->
</body>
</html>
"""

DC = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{{{slide_title}}}}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="{fonts}">
<style>
body{{margin:0}}
a{{color:{{{{color.ink}}}}}}a:hover{{color:{{{{color.ink}}}}}}
</style>
</helmet>
<!--slide-->
{markup}
<!--/slide-->
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":1080,"height":1350}}}}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
"""

CSS = """/* Numa carousel components: bundled open-licensed stand-in fonts (SIL OFL 1.1, ../fonts/OFL-*.txt).
   Hanken Grotesk stands in for Domaine Sans Text Light, Nunito Sans for Avenir Next. Rendering
   needs no network; design_render.py serves the brand's own font files in their place when
   NUMA_BRAND_FONTS points at them. The .dc.html artboards load the same families from Google
   Fonts in Claude Design. Generated by tools/gen_carousel_components.py. */
@font-face {
  font-family: "Hanken Grotesk";
  src: url("../fonts/HankenGrotesk.woff2");
  font-weight: 100 900;
  font-style: normal;
}
@font-face {
  font-family: "Nunito Sans";
  src: url("../fonts/NunitoSans.woff2");
  font-weight: 200 1000;
  font-style: normal;
}
body { margin: 0; }
"""


def outputs() -> dict[Path, str]:
    files = {OUT / "carousel.css": CSS}
    for name, (_label, markup) in C.items():
        files[OUT / f"{name}.html"] = HTML.format(name=name, markup=markup)
        files[OUT / f"{name}.dc.html"] = DC.format(markup=markup, fonts=GOOGLE_FONTS)
    return files


def write_charset() -> None:
    from fontTools.ttLib import TTFont
    fonts = {"Hanken Grotesk": "HankenGrotesk.woff2", "Nunito Sans": "NunitoSans.woff2"}
    common = None
    for file in fonts.values():
        cmap = set(TTFont(str(FONTS / file)).getBestCmap())
        common = cmap if common is None else common & cmap
    cps = sorted(common or ())
    ranges: list[list[int]] = []
    for c in cps:
        if ranges and c == ranges[-1][1] + 1:
            ranges[-1][1] = c
        else:
            ranges.append([c, c])
    doc = {"_readme": "Characters every bundled carousel font draws (the intersection of their cmaps), as inclusive "
                      "code point ranges. design_render.py rejects slide text outside it, so no glyph ever falls back "
                      "to a system font. Regenerate when the bundled fonts change: "
                      "python3 tools/gen_carousel_components.py --charset",
           "fonts": fonts, "ranges": ranges}
    (FONTS / "carousel_charset.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    files = outputs()
    if "--check" in argv:
        stale = [p.name for p, text in files.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        extra = sorted(p.name for p in OUT.glob("*.html") if p not in files)
        if stale or extra:
            print(f"out of date: {', '.join(stale + extra)}", file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.html"):
        if old not in files:
            old.unlink()
    for p, text in files.items():
        p.write_text(text, encoding="utf-8")
    if "--charset" in argv:
        write_charset()
    print(f"wrote {len(files)} files to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
