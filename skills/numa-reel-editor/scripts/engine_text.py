#!/usr/bin/env python3
"""Text for engine.py: caption, hook and end-card sprites, layout and compositing.

Internal helper module of the render engine (see engine.py for the public API).

* ``make_sprite``: one pre-rendered piece of text (alpha mask + soft shadow,
  optional letter tracking for the spaced end-card tagline).
* ``draw_sprite``: composites a sprite onto an RGB uint8 frame in place,
  touching only its region.
* ``layout_words``: a caption line or the hook as balanced rows inside a box
  (captions: at most 2 rows in 960 px at a 1080-wide frame), shrinking the
  font a little when needed; ``balanced_rows``/``greedy_rows`` do the splitting.
* ``hook_words``: hook text with gold italic accent words marked ``*like this*``
  (default: the last word).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

CAPTION_BOX_PX = 960        # caption row width at a 1080-wide frame (spec p.19 / validator rule 22)
WORD_GAP_EM = 0.28          # space between words, in font sizes
ROW_HEIGHT_EM = 1.35        # 124 px rows at 92 px (v1)
ITALIC_SCALE = 1.08         # gold italic key words are drawn slightly larger (v1: 100 px vs 92)
MIN_FONT_SCALE = 0.78       # shrink a long line down to ~72 px before giving up on 2 rows
SHADOW_OPACITY = 0.75


@lru_cache(maxsize=64)
def font(path: str, px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, max(4, int(px)))
    except OSError:
        raise nc.UserError(f"cannot load font {path}") from None


@dataclass
class Sprite:
    alpha: np.ndarray        # float32 h x w, 0..1
    shadow: np.ndarray       # float32 h x w, 0..1 (already scaled by opacity)
    color: tuple[float, float, float]  # RGB 0..1
    baseline: int            # baseline row inside the sprite
    left: int                # x of the pen origin inside the sprite
    advance: float           # pen advance (text width)
    ink_top: int             # first row with ink
    ink_bottom: int          # last row with ink + 1


def make_sprite(text: str, font_path: str, px: float, color, shadow_sigma: float,
                shadow_dy: float = 0.0, tracking: float = 0.0, shadow_opacity: float = SHADOW_OPACITY) -> Sprite:
    """Render text (pen origin on the baseline) to an alpha mask with a soft shadow."""
    f = font(font_path, int(round(px)))
    ascent, descent = f.getmetrics()
    pad = int(np.ceil(shadow_sigma * 3 + abs(shadow_dy) + 4))
    if tracking:
        widths = [f.getlength(ch) for ch in text]
        adv = sum(widths) + tracking * max(0, len(text) - 1)
    else:
        adv = f.getlength(text)
    w = int(np.ceil(adv + 0.25 * px)) + 2 * pad   # italic overhang
    h = ascent + descent + 2 * pad
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    base = pad + ascent
    if tracking:
        x = float(pad)
        for ch, cw in zip(text, widths):
            d.text((x, base), ch, font=f, fill=255, anchor="ls")
            x += cw + tracking
    else:
        d.text((pad, base), text, font=f, fill=255, anchor="ls")
    a = np.asarray(im, dtype=np.float32) / 255.0
    rows = np.nonzero(a.max(axis=1) > 0.02)[0]
    ink_top, ink_bottom = (int(rows[0]), int(rows[-1]) + 1) if rows.size else (base, base)
    sh = cv2.GaussianBlur(a, (0, 0), max(0.5, shadow_sigma)) if shadow_sigma > 0 else np.zeros_like(a)
    if shadow_dy:
        M = np.float32([[1, 0, 0], [0, 1, shadow_dy]])
        sh = cv2.warpAffine(sh, M, (w, h))
    return Sprite(a, np.clip(sh * shadow_opacity, 0, 1).astype(np.float32), tuple(c / 255.0 for c in color),
                  base, pad, adv, ink_top, ink_bottom)


def draw_sprite(img: np.ndarray, sp: Sprite, x: float, y_baseline: float, opacity: float,
                color=None) -> None:
    """Composite a sprite onto img (RGB uint8, in place): pen origin at (x, baseline)."""
    if opacity <= 0.002:
        return
    H, W = img.shape[:2]
    x0 = int(round(x)) - sp.left
    y0 = int(round(y_baseline)) - sp.baseline
    h, w = sp.alpha.shape
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if X0 >= X1 or Y0 >= Y1:
        return
    sx, sy = X0 - x0, Y0 - y0
    a = sp.alpha[sy:sy + Y1 - Y0, sx:sx + X1 - X0] * opacity
    s = sp.shadow[sy:sy + Y1 - Y0, sx:sx + X1 - X0] * opacity
    roi = img[Y0:Y1, X0:X1].astype(np.float32)
    roi *= (1.0 - s)[..., None]
    col = np.array(color if color is not None else sp.color, np.float32) * 255.0
    roi = roi * (1.0 - a)[..., None] + col * a[..., None]
    img[Y0:Y1, X0:X1] = (roi + 0.5).astype(np.uint8)


# ---------------------------------------------------------------------------
# Row layout
# ---------------------------------------------------------------------------
def _widths(words, reg_path, ita_path, px):
    out = []
    for text, gold in words:
        f = font(ita_path if gold else reg_path, int(round(px * (ITALIC_SCALE if gold else 1.0))))
        out.append(f.getlength(text))
    return out


def _rows_width(ws, gap):
    return sum(ws) + gap * max(0, len(ws) - 1)


def balanced_rows(ws: list[float], gap: float, box: float, max_rows: int) -> list[list[int]] | None:
    """Split word widths into <= max_rows rows that fit the box, minimizing the widest row."""
    n = len(ws)
    if _rows_width(ws, gap) <= box:
        return [list(range(n))]
    best = None
    if max_rows >= 2:
        for k in range(1, n):
            a, b = _rows_width(ws[:k], gap), _rows_width(ws[k:], gap)
            if a <= box and b <= box:
                score = (max(a, b), abs(a - b))
                if best is None or score < best[0]:
                    best = (score, [list(range(k)), list(range(k, n))])
    if best:
        return best[1]
    if max_rows >= 3:
        for k in range(1, n - 1):
            for j in range(k + 1, n):
                parts = [ws[:k], ws[k:j], ws[j:]]
                widths = [_rows_width(p, gap) for p in parts]
                if max(widths) <= box:
                    score = (max(widths), max(widths) - min(widths))
                    if best is None or score < best[0]:
                        best = (score, [list(range(k)), list(range(k, j)), list(range(j, n))])
        if best:
            return best[1]
    return None


def greedy_rows(ws, gap, box):
    rows, cur, cw = [], [], 0.0
    for i, w in enumerate(ws):
        add = w if not cur else gap + w
        if cur and cw + add > box:
            rows.append(cur)
            cur, cw = [], 0.0
            add = w
        cur.append(i)
        cw += add
    if cur:
        rows.append(cur)
    return rows


@dataclass
class TextBlock:
    """Laid-out multi-row text: words with sprite, x (pen origin) and row index."""
    words: list = field(default_factory=list)   # [(Sprite, x, row, appear_time)]
    rows: int = 0
    row_h: float = 0.0
    ascent: float = 0.0
    descent: float = 0.0
    px: float = 0.0
    x_min: float = 0.0
    x_max: float = 0.0
    fit: bool = True

    def baseline(self, top: float, row: int) -> float:
        return top + row * self.row_h + (self.row_h - (self.ascent + self.descent)) / 2 + self.ascent

    @property
    def height(self) -> float:
        return self.rows * self.row_h


def layout_words(words, reg_path, ita_path, base_px, W, box, max_rows, colors, shadow_sigma,
                 shadow_dy, shadow_opacity: float = SHADOW_OPACITY) -> TextBlock:
    """words: [(text, gold, appear_time)]. Tries full size, then shrinks to MIN_FONT_SCALE."""
    pairs = [(t, g) for t, g, _ in words]
    chosen = None
    scale = 1.0
    while scale >= MIN_FONT_SCALE - 1e-9:
        px = base_px * scale
        ws = _widths(pairs, reg_path, ita_path, px)
        rows = balanced_rows(ws, WORD_GAP_EM * px, box, max_rows)
        if rows:
            chosen = (px, ws, rows, True)
            break
        scale -= 0.04
    if chosen is None:
        px = base_px * MIN_FONT_SCALE
        ws = _widths(pairs, reg_path, ita_path, px)
        chosen = (px, ws, greedy_rows(ws, WORD_GAP_EM * px, box), False)
    px, ws, rows, fit = chosen
    gap = WORD_GAP_EM * px
    f = font(reg_path, int(round(px)))
    asc, desc = f.getmetrics()
    blk = TextBlock(rows=len(rows), row_h=ROW_HEIGHT_EM * px, ascent=asc, descent=desc, px=px, fit=fit)
    blk.x_min, blk.x_max = W, 0
    white, gold = colors
    for r, idx in enumerate(rows):
        rw = _rows_width([ws[i] for i in idx], gap)
        x = (W - rw) / 2
        blk.x_min, blk.x_max = min(blk.x_min, x), max(blk.x_max, x + rw)
        for i in idx:
            text, g, t = words[i]
            sp = make_sprite(text, ita_path if g else reg_path, px * (ITALIC_SCALE if g else 1.0),
                             gold if g else white, shadow_sigma, shadow_dy, shadow_opacity=shadow_opacity)
            blk.words.append((sp, x, r, t))
            x += ws[i] + gap
    return blk


def hook_words(text: str) -> list[tuple[str, bool]]:
    """'Your *first* plunge.' -> [('Your', F), ('first', T), ('plunge.', F)]. No markup: last word gold.

    Markup may span words ('*first plunge*') and keep punctuation attached ('*cold*.')."""
    out: list[tuple[str, bool]] = []
    in_mark = False
    marked = "*" in text
    for tok in text.split():
        stars = tok.count("*")
        gold = in_mark or stars > 0
        if stars % 2:
            in_mark = not in_mark
        word = tok.replace("*", "")
        if word:
            out.append((word, gold))
    if not marked and out:
        out[-1] = (out[-1][0], True)
    return out
