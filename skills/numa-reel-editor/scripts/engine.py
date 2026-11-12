#!/usr/bin/env python3
"""NUMA Studio render engine: plan.json -> silent H.264 reel, single frames or a preview grid.

Command line (docs/CONTRACTS.md section 9):

    engine.py PLAN_JSON [--draft] [--workers N] [--size WxH] [--from S] [--to S]
              [--out FILE] [--encoder libx264|videotoolbox]
    engine.py PLAN_JSON preview T1 [T2 ...] [--size WxH] [--out FILE]

Full render -> OUT_DIR/video_noaudio.mp4 (``--draft``: video_noaudio_draft.mp4;
``--from/--to``: segment_<from>_<to>.mp4) plus OUT_DIR/render.json (timings,
frames, size, workers, encoder, sha256). Preview -> OUT_DIR/preview.jpg, 5 tiles
per row. OUT_DIR is the plan's ``out_dir`` (default: the plan's folder).

Python API (import with ``sys.path.insert(0, <scripts dir>)``; ``import engine``):

    plan = engine.load_plan(path)                      # read + schema-validate, paths resolved
    plan = engine.prepare_plan(plan_dict, base_dir)    # same for an in-memory (e.g. edited) plan
    with engine.Renderer(plan, size=(1080, 1350), draft=False) as r:
        rgb = r.frame(t)                               # H x W x 3 RGB uint8 at reel time t
        r.width, r.height, r.fps, r.duration
    rgb = engine.render_frame(plan, t, size=None)      # one-off frame
    info = engine.render_video(plan, out_mp4, t_from=None, t_to=None, size=None,
                               draft=False, workers=None, encoder="libx264")
    path = engine.render_preview(plan, [t1, t2, ...], out_jpg, size=None)
    engine.save_image(rgb, path)                       # JPG/PNG writer for frames

``size`` is any even WxH; pixel fields of the plan (caption_y, hook.y,
logo_width) are in the plan's own ``size`` and scale with the render. Layout
constants (caption font ~92 px at 1080 wide, safe areas = top 12% / bottom 10%,
end-card positions) scale with the frame. ``render_video`` returns the dict
that the CLI writes to render.json.

Per frame (spec p.18-20): active shot(s) framed with an eased sub-pixel zoom/pan
(cubic warp, the view never leaves the source: no bars, no mirrored edges), the
colour look, the transition (punch, whip, leakfade, fade, flash, wipe, cut),
bloom, light leaks (plan ``leaks`` + automatic on leakfade), vignette and bottom
gradient, the frame-zero hook text, word-by-word captions (safe areas, off
faces), the end card, seeded film grain and the global fades (fade-in <= 0.2 s
and none with a hook, so frame 0 is never black; 0.8 s fade-out).

Determinism: the picture is a pure function of (plan, size, frame index);
grain and leak motion are seeded by ``plan.seed``. Frames rendered by N worker
processes are identical to a single process, the encoder runs with fixed
parameters and thread count and bit-exact muxing, so the same plan gives a
byte-identical MP4 for any ``--workers``.

Video shots are decoded once per render with one seek per shot into a per-shot
frame cache (memory-mapped, shared by the workers) at the resolution the shot
needs; stills are prepared once per shot the same way.
"""
from __future__ import annotations

import copy
import hashlib
import math
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import engine_media as em  # noqa: E402
import engine_text as et  # noqa: E402

ENGINE_VERSION = "2.0.0"

# Transition timings (spec p.19)
PUNCH_S, PUNCH_ZOOM, PUNCH_LIFT = 0.22, 0.16, 0.28
WHIP_S, WHIP_BLUR_PX = 0.28, 160
CROSSFADE_S = 0.5
FLASH_S, FLASH_PEAK = 0.35, 0.9
WIPE_S = 1.0
# how long the outgoing shot stays on screen after the incoming shot's t0
TRANSITION_TAIL = {"whip": WHIP_S / 2, "fade": CROSSFADE_S, "leakfade": CROSSFADE_S, "wipe": WIPE_S}
AUTO_LEAK_STRENGTH = 0.55
FADE_OUT_S = 0.8
FADE_IN_FLOOR = 0.35         # brightness of frame 0 without a hook (never a black frame)
HOOK_FADE_OUT_S = 0.3
LINE_FADE_OUT_S = 0.35
PREVIEW_TILE_W = 360
GRAIN_SIGMA = 3.0            # light film grain (8-bit levels), seeded by plan.seed
GRAIN_BANK = 4


# ---------------------------------------------------------------------------
# Plan loading
# ---------------------------------------------------------------------------
def _resolve(p: str, base: Path) -> str:
    q = Path(p).expanduser()
    return str(q if q.is_absolute() else (base / q).resolve())


def prepare_plan(plan: dict, base_dir: str | os.PathLike | None = None) -> dict:
    """Schema-validate a plan dict and return a copy with every path absolute.

    Relative paths (the validator rejects them, the engine is lenient) resolve
    against base_dir; out_dir defaults to base_dir."""
    if not isinstance(plan, dict):
        raise nc.UserError("plan must be a JSON object")
    nc.validate_against("plan", plan, what="plan")
    out = copy.deepcopy(plan)
    base = Path(base_dir).resolve() if base_dir else Path.cwd()
    for sh in out["shots"]:
        sh["src"] = _resolve(sh["src"], base)
    for key in ("font_regular", "font_italic"):
        if out.get(key):
            out[key] = _resolve(out[key], base)
    if out.get("endcard", {}).get("logo"):
        out["endcard"]["logo"] = _resolve(out["endcard"]["logo"], base)
    out["out_dir"] = _resolve(out["out_dir"], base) if out.get("out_dir") else str(base)
    return out


def load_plan(path: str | os.PathLike) -> dict:
    """Read, schema-validate and path-resolve plan.json (UserError on any problem)."""
    p = Path(path).expanduser().resolve()
    plan = nc.read_json(p, "plan")
    return prepare_plan(plan, p.parent)


def _even(x: float) -> int:
    return max(16, int(round(x / 2.0)) * 2)


def output_size(plan: dict, size: tuple[int, int] | None = None, draft: bool | None = None) -> tuple[int, int]:
    """Render size for a plan: --size or plan size (default config render.size), halved-ish for drafts."""
    cfg = nc.config_value("render")
    w, h = size or tuple(plan.get("size") or cfg["size"])
    if draft if draft is not None else plan.get("quality") == "draft":
        k = float(cfg["draft"]["scale"])
        w, h = _even(w * k), _even(h * k)
    if w % 2 or h % 2 or w < 16 or h < 16:
        raise nc.UsageError(f"size {w}x{h}: width and height must be even and at least 16")
    return int(w), int(h)


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------
class Shot:
    """One plan shot: its source, framing and (lazily) its plate."""

    def __init__(self, i: int, d: dict, W: int, H: int, fps: float, next_tr: str | None, warn=nc.warn):
        self.i, self.d = i, d
        self.what = f"shots[{i}].src"
        self.kind = d.get("kind", "image")
        self.src = d["src"]
        self.t0, self.t1 = float(d["t0"]), float(d["t1"])
        self.len = max(1e-6, self.t1 - self.t0)
        self.look = d.get("look", "warm")
        self.tr = d.get("tr", "cut")
        self.fps = fps
        self.blur = d.get("blur") or []
        self.tail = TRANSITION_TAIL.get(next_tr or "", 0.0)
        z = d.get("z", [1.02, 1.14])
        zmax = max(em.effective_zoom(z)) * (1 + PUNCH_ZOOM if self.tr == "punch" else 1.0) * 1.03
        focus = list(d.get("focus") or [0.5, 0.5])
        faces = [list(b) for b in d.get("faces") or []]
        self.panorama = False
        if self.kind == "video":
            info = em.video_info(self.src, self.what)
            sw, sh = int(info["width"]), int(info["height"])
            self.speed = float(d.get("speed", 1.0))
            self.start = float(d.get("start", 0.0))
            self.clip_duration = info.get("duration")
            dur = self.clip_duration
            if dur:
                need = self.start + self.len * self.speed
                if self.start >= dur:
                    warn(f"shots[{i}].start {self.start:g} s is past the end of the {dur:.2f} s clip; "
                         f"its last frame is held")
                elif need > dur + 0.05:
                    warn(f"shots[{i}]: the clip ends at {dur:.2f} s but the shot needs {need:.2f} s; "
                         f"its last frame is held for {(need - dur) / self.speed:.2f} s")
        else:
            crop = d.get("crop")
            fw, fh = em.image_size(self.src, None, self.what)
            sw, sh = em.image_size(self.src, crop, self.what)
            if crop:
                l, t = crop[0], crop[1]
                focus = [(focus[0] * fw - l) / sw, (focus[1] * fh - t) / sh]
                faces = [[(b[0] * fw - l) / sw, (b[1] * fh - t) / sh, b[2] * fw / sw, b[3] * fh / sh] for b in faces]
            self.panorama = em.is_panorama(sw, sh, W, H)
        focus = [min(1.0, max(0.0, focus[0])), min(1.0, max(0.0, focus[1]))]
        self.aspect = sw / sh
        self.pw, self.ph = em.plate_geometry(sw, sh, W, H, zmax, self.panorama)
        self.framing = em.make_framing(self.pw, self.ph, W, H, z, d.get("pan", [0, 0]), focus, i,
                                       self.panorama, sw / sh, self.len)
        self.faces_plate = [self._to_plate(b) for b in faces]
        # video: frames at the reel cadence from t0 through the outgoing transition tail
        self.n_frames = int(math.ceil((self.len + self.tail) * fps)) + 2 if self.kind == "video" else 0
        self.plate: np.ndarray | None = None
        self.frames: np.ndarray | None = None
        self._single: dict[int, np.ndarray] = {}

    def _to_plate(self, b):
        x, y, w, h = b
        if self.panorama:
            fh = em.FILL_FOREGROUND_HEIGHT * self.ph
            fw = fh * self.aspect
            ox, oy = (self.pw - fw) / 2, (self.ph - fh) / 2
            return (ox + x * fw, oy + y * fh, w * fw, h * fh)
        return (x * self.pw, y * self.ph, w * self.pw, h * self.ph)

    def progress(self, t: float) -> float:
        return (t - self.t0) / self.len

    def frame_index(self, t: float) -> int:
        j = int(math.floor((t - self.t0) * self.fps + 0.5))
        return min(max(j, 0), self.n_frames - 1)

    def visible(self, a: float, b: float) -> bool:
        return self.t0 - WHIP_S / 2 - 1e-6 <= b and a <= self.t1 + self.tail + 1e-6

    # plates --------------------------------------------------------------
    def build_plate(self) -> np.ndarray:
        return em.build_image_plate(self.src, self.d.get("crop"), self.blur, self.pw, self.ph,
                                    self.panorama, self.what)

    def picture(self, t: float) -> np.ndarray:
        """The plate to frame at reel time t."""
        if self.kind != "video":
            if self.plate is None:
                self.plate = self.build_plate()
            return self.plate
        j = self.frame_index(t)
        if self.frames is not None:
            return self.frames[j]
        if j not in self._single:
            if len(self._single) > 8:
                self._single.clear()
            one = em.decode_video(self.src, self.start + j * self.speed / self.fps, self.fps / self.speed, 1,
                                  self.pw, self.ph, blur=self.blur, what=self.what)
            self._single[j] = one[0]
        return self._single[j]

    def cache(self, folder: Path) -> None:
        """Write this shot's plate (still) or decoded frames (video) to folder."""
        if self.kind == "video":
            arr = np.lib.format.open_memmap(folder / f"shot_{self.i}.npy", mode="w+", dtype=np.uint8,
                                            shape=(self.n_frames, self.ph, self.pw, 3))
            em.decode_video(self.src, self.start, self.fps / self.speed, self.n_frames, self.pw, self.ph,
                            blur=self.blur, sink=arr, what=self.what)
            arr.flush()
            del arr
        else:
            np.save(folder / f"shot_{self.i}.npy", self.build_plate())

    def attach(self, folder: Path) -> None:
        f = folder / f"shot_{self.i}.npy"
        if not f.is_file():
            return
        arr = np.load(f, mmap_mode="r")
        if self.kind == "video":
            self.frames = arr
        else:
            self.plate = arr


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
class Renderer:
    """Renders frames of one plan at one size. See the module docstring."""

    def __init__(self, plan: dict, *, size: tuple[int, int] | None = None, draft: bool | None = None,
                 base_dir: str | os.PathLike | None = None, quiet: bool = False):
        self.quiet = quiet
        if not plan.get("out_dir") or not Path(plan["shots"][0]["src"]).is_absolute():
            plan = prepare_plan(plan, base_dir)
        else:
            nc.validate_against("plan", plan, what="plan")
        self.plan = plan
        cfg = nc.config_value("render")
        self.cfg = cfg
        self.draft = bool(draft if draft is not None else plan.get("quality") == "draft")
        self.width, self.height = output_size(plan, size, self.draft)
        W, H = self.width, self.height
        pw_, ph_ = tuple(plan.get("size") or cfg["size"])
        self.sx, self.sy = W / pw_, H / ph_
        self.s = min(W, H) / 1080.0          # layout unit: 1 px at a 1080-wide portrait frame
        self.sw = W / 1080.0
        self.fps = float(plan.get("fps") or cfg["fps"])
        self.duration = float(plan["duration"])
        self.seed = int(plan.get("seed", 0))
        self.n_frames = max(1, int(round(self.duration * self.fps)))
        self.safe_top = cfg["safe_area"]["top_fraction"] * H
        self.safe_bottom = (1 - cfg["safe_area"]["bottom_fraction"]) * H
        self.accent = tuple(plan.get("accent_rgb") or nc.accent_rgb())
        self.white = tuple(nc.brand_color("caption_text"))
        self.font_regular = plan.get("font_regular") or str(nc.brand_font("regular"))
        self.font_italic = plan.get("font_italic") or str(nc.brand_font("italic"))
        for f in (self.font_regular, self.font_italic):
            if not Path(f).is_file():
                raise nc.UserError(f"font not found: {f}")
        shots = sorted(plan["shots"], key=lambda d: float(d["t0"]))
        if shots[0].get("tr", "cut") != "cut":
            self._warn(f"shots[0].tr: {shots[0]['tr']!r} on the first shot is rendered as a plain cut")
            shots[0] = dict(shots[0], tr="cut")
        self.shots = [Shot(i, d, W, H, self.fps, shots[i + 1].get("tr", "cut") if i + 1 < len(shots) else None,
                           warn=self._warn)
                      for i, d in enumerate(shots)]
        self._t0s = [s.t0 for s in self.shots]
        self._build_masks()
        self._build_grain()
        self._build_leaks()
        self._build_hook()
        self._build_captions()
        self._build_endcard()
        self._cache_dir: Path | None = None

    def _warn(self, msg: str) -> None:
        if not self.quiet:
            nc.warn(msg)

    # context manager: nothing to free but caches
    def __enter__(self) -> "Renderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for s in self.shots:
            s.frames = None
            s.plate = None
            s._single.clear()

    # caches -----------------------------------------------------------------
    def build_cache(self, folder: str | os.PathLike, t_from: float = 0.0, t_to: float | None = None) -> None:
        """Prepare every shot visible in [t_from, t_to] into folder (one decode/seek per video shot)."""
        folder = Path(folder)
        t_to = self.duration if t_to is None else t_to
        for s in self.shots:
            if s.visible(t_from, t_to):
                s.cache(folder)
        self.attach_cache(folder)

    def attach_cache(self, folder: str | os.PathLike) -> None:
        self._cache_dir = Path(folder)
        for s in self.shots:
            s.attach(self._cache_dir)

    # precomputed layers ------------------------------------------------------
    def _build_masks(self) -> None:
        W, H = self.width, self.height
        y = (np.arange(H, dtype=np.float32) + 0.5) / H
        x = (np.arange(W, dtype=np.float32) + 0.5) / W
        r = np.sqrt(((x[None, :] - 0.5) ** 2) * 1.6 * (W / H) ** 2 / (9 / 16) ** 2 + (y[:, None] - 0.5) ** 2)
        vig = 1 - 0.42 * np.clip((r - 0.3) / 0.45, 0, 1) ** 1.6
        grad = 1 - 0.42 * np.clip((y - 0.547) / 0.365, 0, 1) ** 1.3       # bottom gradient (v1: 1050..1750 of 1920)
        m = np.clip(vig * grad[:, None] * 255 + 0.5, 0, 255).astype(np.uint8)
        self._mask = cv2.merge([m, m, m])
        top_rows = int(0.36 * H)
        prof = 1 - 0.50 * np.clip((0.36 - y[:top_rows]) / 0.36, 0, 1) ** 1.2   # shade behind the hook
        self._hook_shade = prof.astype(np.float32)

    def _build_grain(self) -> None:
        """A small bank of seeded grain fields (luma only), stored as +/- uint8 parts for fast saturating adds."""
        W, H = self.width, self.height
        rng = np.random.default_rng([self.seed, 0x6A41])
        hw, hh = (W + 64) // 2, (H + 64) // 2
        self._grain = []
        for _ in range(GRAIN_BANK):
            g = rng.standard_normal((hh, hw), dtype=np.float32)
            g = np.round(cv2.resize(g, (hw * 2, hh * 2), interpolation=cv2.INTER_LINEAR) * GRAIN_SIGMA)
            pos = np.clip(g, 0, 255).astype(np.uint8)
            neg = np.clip(-g, 0, 255).astype(np.uint8)
            self._grain.append((cv2.merge([pos, pos, pos]), cv2.merge([neg, neg, neg])))

    def _build_leaks(self) -> None:
        rng = np.random.default_rng([self.seed, 0x1EA4])
        self._leak_phase = rng.uniform(0, 2 * math.pi, size=(3, 2)).astype(np.float64)
        lw = 48
        lh = max(8, int(round(lw * self.height / self.width)))
        yy, xx = np.mgrid[0:lh, 0:lw].astype(np.float32)
        self._leak_grid = (lw, lh, xx, yy)
        leaks = [tuple(map(float, lk)) for lk in self.plan.get("leaks", [])]
        for s in self.shots:  # leakfade: automatic warm leak over the crossfade
            if s.tr == "leakfade" and s.i > 0:
                leaks.append((s.t0 - 0.05, CROSSFADE_S + 0.1, AUTO_LEAK_STRENGTH))
        self._leaks = leaks

    def _build_hook(self) -> None:
        hook = self.plan.get("hook")
        self._hook = None
        if not hook:
            return
        W, H = self.width, self.height
        words = [(t, g, 0.0) for t, g in et.hook_words(hook["text"])]
        if not words:
            return
        blk = et.layout_words(words, self.font_regular, self.font_italic, 100 * self.s, W, 0.86 * W, 3,
                              (self.white, self.accent), 12 * self.s, 3 * self.s, shadow_opacity=1.3)
        if "y" in hook:
            top = float(hook["y"]) * self.sy - blk.height / 2
        else:
            top = self.safe_top + 0.012 * H
        top = min(max(top, self.safe_top), self.safe_bottom - blk.height)
        self._hook = (blk, top, float(hook.get("t1", 2.0)))

    def _shot_at(self, t: float) -> int:
        i = 0
        for k, t0 in enumerate(self._t0s):
            if t0 <= t + 1e-9:
                i = k
            else:
                break
        return i

    def _face_rects(self, a: float, b: float) -> list[tuple[float, float, float, float]]:
        """Screen rectangles of every face on screen during [a, b] (sampled every 0.1 s)."""
        rects = []
        n = max(2, int(math.ceil((b - a) / 0.1)) + 1)
        for k in range(n):
            t = a + (b - a) * k / (n - 1)
            s = self.shots[self._shot_at(t)]
            if not s.faces_plate:
                continue
            p = s.progress(t)
            for (x, y, w, h) in s.faces_plate:
                x0, y0 = s.framing.to_screen(p, x, y)
                x1, y1 = s.framing.to_screen(p, x + w, y + h)
                rects.append((x0, y0, x1, y1))
        return rects

    def _build_captions(self) -> None:
        cfg = self.cfg["captions"]
        W, H = self.width, self.height
        self.rise = cfg["rise_px"] * H / 1920   # 22 px at 1920 high
        self.word_fade = float(cfg["fade_in_s"])
        default_y = self.plan.get("caption_y")
        pw_, ph_ = tuple(self.plan.get("size") or self.cfg["size"])
        cy = (float(default_y) if default_y is not None else cfg["default_y"] * ph_ / 1920) * self.sy
        self._lines = []
        self.caption_boxes = []   # (t_first, t_end, x0, y0, x1, y1) after placement, for tests/QA
        margin = 0.015 * H
        plan_lines = self.plan.get("lines", [])
        firsts = [float(ln["words"][0][1]) for ln in plan_lines]
        for li, ln in enumerate(plan_lines):
            words = [(str(w[0]), bool(len(w) > 2 and w[2]), float(w[1])) for w in ln["words"]]
            blk = et.layout_words(words, self.font_regular, self.font_italic, cfg["font_px"] * self.s, W,
                                  et.CAPTION_BOX_PX * self.s, int(cfg["max_rows"]),
                                  (self.white, self.accent), 8 * self.s, 3 * self.s)
            if not blk.fit:
                self._warn(f"lines[{li}]: caption does not fit in {cfg['max_rows']} rows; it wraps to {blk.rows}")
            # ink extents relative to the block top (top = 0)
            ink_top = min(blk.baseline(0, r) - (sp.baseline - sp.ink_top) for sp, _, r, _ in blk.words)
            ink_bot = max(blk.baseline(0, r) + (sp.ink_bottom - sp.baseline) for sp, _, r, _ in blk.words) + self.rise
            lo, hi = self.safe_top - ink_top, self.safe_bottom - ink_bot
            top0 = cy - blk.height / 2
            top = min(max(top0, lo), hi) if hi >= lo else lo
            t_first, t_end = words[0][2], float(ln["end"])
            # the fade-out ends by the next line's first word, so two lines never share the spot
            gone = t_end + LINE_FADE_OUT_S
            later = [f for f in firsts[li + 1:] if f > t_first]
            if later:
                gone = min(gone, later[0])
            fade_start = min(t_end, gone - 0.08)
            faces = self._face_rects(t_first, gone)

            def clear(tp: float) -> bool:
                y0, y1 = tp + ink_top - margin, tp + ink_bot + margin
                return not any(fx0 < blk.x_max and fx1 > blk.x_min and fy0 < y1 and fy1 > y0
                               for fx0, fy0, fx1, fy1 in faces)

            if faces and not clear(top) and hi >= lo:
                step = max(1.0, 2 * self.s)
                cands = [lo + k * step for k in range(int((hi - lo) / step) + 1)] + [hi]
                ok = [c for c in cands if clear(c)]
                if ok:
                    top = min(ok, key=lambda c: (abs(c - top), c))
            self._lines.append((blk, top, t_first, fade_start, gone))
            self.caption_boxes.append((t_first, t_end, blk.x_min, top + ink_top, blk.x_max, top + ink_bot))

    def _build_endcard(self) -> None:
        ec = self.plan.get("endcard")
        self._ec = None
        if not ec:
            return
        W, H, s = self.width, self.height, self.s
        logo_path = ec.get("logo") or str(nc.brand_asset("wordmark"))
        pw_ = (self.plan.get("size") or self.cfg["size"])[0]
        lw = min(0.86 * W, float(ec.get("logo_width", 820)) * W / pw_)
        logo = None
        try:
            with Image.open(logo_path) as im:
                lg = im.convert("RGBA")
        except FileNotFoundError:
            raise nc.UserError(f"endcard.logo: file not found: {logo_path}") from None
        except Exception as e:  # noqa: BLE001
            raise nc.UserError(f"endcard.logo: cannot read image {logo_path}: {type(e).__name__}") from None
        bbox = lg.getchannel("A").getbbox()
        if bbox:
            lg = lg.crop(bbox)
        lh = max(2, int(round(lg.height * lw / lg.width)))
        lg = lg.resize((max(2, int(round(lw))), lh), Image.LANCZOS)
        la = np.asarray(lg, dtype=np.float32) / 255.0
        # rendered white: use the alpha channel; an opaque logo uses its inverted luminance
        alpha = la[..., 3] if la[..., 3].min() < 0.99 else np.clip(1 - la[..., :3].mean(2) * 1.15, 0, 1)
        pad = int(30 * s)
        a = np.pad(alpha, pad)
        sh = cv2.GaussianBlur(a, (0, 0), 10 * s) * 0.55
        logo = et.Sprite(a.astype(np.float32), sh.astype(np.float32), (1.0, 1.0, 1.0), pad + a.shape[0] // 2 - pad,
                         pad, alpha.shape[1], 0, a.shape[0])
        tagline = ec.get("tagline", nc.brand_value("endcard.tagline", ""))
        subtitle = ec.get("subtitle", nc.brand_value("endcard.default_subtitle", ""))
        tag = None
        if tagline:
            px = 36 * s
            tag = et.make_sprite(tagline.upper(), self.font_regular, px, self.white, 6 * s, 2 * s, tracking=0.32 * px)
            while tag.advance > 0.86 * W and px > 12:
                px *= 0.92
                tag = et.make_sprite(tagline.upper(), self.font_regular, px, self.white, 6 * s, 2 * s,
                                     tracking=0.32 * px)
        sub = None
        if subtitle:
            px = 60 * s
            sub = et.make_sprite(subtitle, self.font_italic, px, self.accent, 8 * s, 3 * s)
            while sub.advance > 0.86 * W and px > 12:
                px *= 0.94
                sub = et.make_sprite(subtitle, self.font_italic, px, self.accent, 8 * s, 3 * s)
        self._ec = {"t": float(ec["t"]), "logo": logo, "tag": tag, "sub": sub}

    # frame -------------------------------------------------------------------
    def _view(self, i: int, t: float, extra: float = 1.0) -> np.ndarray:
        s = self.shots[i]
        img = s.framing.warp(s.picture(t), s.progress(t), extra)
        return em.grade(img, s.look)

    def _whip(self, a: int, b: int, t: float) -> np.ndarray:
        W = self.width
        tc = self.shots[b].t0
        p = em.clamp01((t - (tc - WHIP_S / 2)) / WHIP_S)
        off = int(round(em.smooth(p) * W))
        A, B = self._view(a, t), self._view(b, t)
        out = np.empty_like(A)
        out[:, :W - off] = A[:, off:]
        out[:, W - off:] = B[:, :off]
        n = int(round(WHIP_BLUR_PX * self.sw * math.sin(math.pi * p)))
        if n >= 3:
            out = cv2.blur(out, (n, 1), borderType=cv2.BORDER_REPLICATE)
        return out

    def _wipe(self, before: np.ndarray, after: np.ndarray, q: float) -> np.ndarray:
        W = self.width
        k = 18 * self.sw                      # edge softness
        sig = 14 * self.sw                    # glow width
        reach = int(math.ceil(8 * max(k, sig)))
        xpos = -reach + em.smooth(q) * (W + 2 * reach)
        out = before.copy()
        a0 = max(0, int(xpos - reach))
        a1 = min(W, int(xpos + reach) + 1)
        if a0 > 0:
            out[:, :a0] = after[:, :a0]
        if a1 > a0:
            x = np.arange(a0, a1, dtype=np.float32) + 0.5
            m = 1.0 / (1.0 + np.exp(np.clip((x - xpos) / k, -60, 60)))
            g = np.exp(-0.5 * ((x - xpos) / sig) ** 2) + 0.9 * np.exp(-0.5 * ((x - xpos) / (1.6 * self.sw)) ** 2)
            band = after[:, a0:a1].astype(np.float32) * m[None, :, None] + \
                before[:, a0:a1].astype(np.float32) * (1 - m)[None, :, None]
            glow = np.clip(g, 0, 1)[None, :, None] * np.array([1.0, 0.94, 0.84], np.float32)[None, None, :] * 0.95
            band = band + (255.0 - band) * glow
            out[:, a0:a1] = np.clip(band + 0.5, 0, 255).astype(np.uint8)
        return out

    def _picture(self, t: float) -> np.ndarray:
        i = self._shot_at(t)
        s = self.shots[i]
        dt = t - s.t0
        nxt = i + 1
        if nxt < len(self.shots) and self.shots[nxt].tr == "whip" and t >= self.shots[nxt].t0 - WHIP_S / 2:
            return self._whip(i, nxt, t)
        if s.tr == "whip" and i > 0 and dt < WHIP_S / 2:
            return self._whip(i - 1, i, t)
        if s.tr == "punch" and dt < PUNCH_S:
            q = em.ease_out(dt / PUNCH_S)
            img = self._view(i, t, 1 + PUNCH_ZOOM * (1 - q))
            return cv2.addWeighted(img, 1.0, img, 0.0, 255.0 * PUNCH_LIFT * (1 - q))
        img = self._view(i, t)
        if s.tr in ("fade", "leakfade") and i > 0 and dt < CROSSFADE_S:
            a = em.smooth(dt / CROSSFADE_S)
            return cv2.addWeighted(self._view(i - 1, t), 1 - a, img, a, 0.0)
        if s.tr == "flash" and dt < FLASH_S:
            w = FLASH_PEAK * (1 - em.ease_out(dt / FLASH_S))
            return cv2.addWeighted(img, 1 - w, img, 0.0, 255.0 * w)
        if s.tr == "wipe" and i > 0 and dt < WIPE_S:
            return self._wipe(self._view(i - 1, t), img, dt / WIPE_S)
        return img

    def _bloom(self, img: np.ndarray) -> np.ndarray:
        W, H = self.width, self.height
        small = cv2.resize(img, (max(4, W // 4), max(4, H // 4)), interpolation=cv2.INTER_AREA)
        hi = np.clip((small.astype(np.float32) - 158.0) * (255.0 / 97.0), 0, 255)
        hi = cv2.GaussianBlur(hi, (0, 0), max(1.0, 9 * self.sw))
        hi = cv2.resize(hi, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.uint8)
        return self._screen(img, hi, 0.2)

    @staticmethod
    def _screen(img: np.ndarray, layer: np.ndarray, amount: float) -> np.ndarray:
        inv = cv2.subtract(np.full_like(img, 255), img)
        return cv2.add(img, cv2.multiply(inv, layer, scale=amount / 255.0))

    def _leak(self, img: np.ndarray, t: float) -> np.ndarray:
        strength = 0.0
        for tc, d, a in self._leaks:
            if tc - 0.2 < t < tc + d:
                strength = max(strength, a * math.sin(math.pi * (t - tc + 0.2) / (d + 0.2)))
        if strength <= 0.01:
            return img
        lw, lh, xx, yy = self._leak_grid
        out = np.zeros((lh, lw, 3), np.float32)
        cols = [(1.0, 0.55, 0.25), (1.0, 0.30, 0.35), (1.0, 0.75, 0.10)]   # warm: amber, rose, gold
        for j, (col, sp) in enumerate(zip(cols, (0.6, -0.45, 0.3))):
            ph = self._leak_phase[j]
            cx = lw * (0.5 + 0.6 * math.sin(t * sp + ph[0]))
            cy = lh * (0.5 + 0.5 * math.cos(t * sp * 0.7 + ph[1]))
            r = lw * (0.55 + 0.15 * j)
            out += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))[..., None] * np.array(col, np.float32)
        layer = cv2.resize(np.clip(out * strength, 0, 1) * 255.0, (self.width, self.height),
                           interpolation=cv2.INTER_CUBIC)
        layer = np.clip(layer + 0.5, 0, 255).astype(np.uint8)
        return self._screen(img, layer, 1.0)

    def _draw_hook(self, img: np.ndarray, t: float) -> None:
        if not self._hook:
            return
        blk, top, t1 = self._hook
        a = 1.0 if t <= t1 else 1.0 - em.smooth((t - t1) / HOOK_FADE_OUT_S)
        if a <= 0:
            return
        rows = self._hook_shade.shape[0]
        shade = 1.0 - (1.0 - self._hook_shade) * a
        roi = img[:rows].astype(np.float32) * shade[:, None, None]
        img[:rows] = (roi + 0.5).astype(np.uint8)
        for sp, x, r, _ in blk.words:
            et.draw_sprite(img, sp, x, blk.baseline(top, r), a)

    def _draw_captions(self, img: np.ndarray, t: float) -> None:
        for blk, top, t_first, fade_start, gone in self._lines:
            if t < t_first - 0.01 or t >= gone:
                continue
            lo = 1.0 - em.smooth((t - fade_start) / max(1e-3, gone - fade_start)) if t > fade_start else 1.0
            for sp, x, r, ts in blk.words:
                p = (t - ts) / self.word_fade
                if p <= 0:
                    continue
                q = em.ease_out(p)
                et.draw_sprite(img, sp, x, blk.baseline(top, r) + self.rise * (1 - q), q * lo)

    def _draw_endcard(self, img: np.ndarray, t: float) -> np.ndarray:
        ec = self._ec
        if not ec or t < ec["t"]:
            return img
        W, H, s = self.width, self.height, self.s
        T = ec["t"]
        veil = 1.0 - 0.22 * em.smooth((t - T) / 0.6)
        img = cv2.convertScaleAbs(img, alpha=veil)
        if ec["logo"] is not None:
            q = em.ease_out((t - T - 0.30) / 0.9)
            lg = ec["logo"]
            et.draw_sprite(img, lg, W / 2 - lg.advance / 2, 0.469 * H + 14 * s * (1 - q), q)
        if ec["tag"] is not None:
            q = em.ease_out((t - T - 0.80) / 0.8)
            tg = ec["tag"]
            et.draw_sprite(img, tg, W / 2 - tg.advance / 2, 0.556 * H + 10 * s * (1 - q), q)
        if ec["sub"] is not None:
            q = em.ease_out((t - T - 1.40) / 0.9)
            sb = ec["sub"]
            et.draw_sprite(img, sb, W / 2 - sb.advance / 2, 0.78 * H + 14 * s * (1 - q), q)
        return img

    def _add_grain(self, img: np.ndarray, n: int) -> np.ndarray:
        pos, neg = self._grain[(n * 7 + self.seed) % len(self._grain)]
        ox = (n * 37 + self.seed * 11) % 64
        oy = (n * 53 + self.seed * 5) % 64
        H, W = self.height, self.width
        # pos and neg never overlap, so this equals clip(img + grain)
        img = cv2.add(img, pos[oy:oy + H, ox:ox + W])
        return cv2.subtract(img, neg[oy:oy + H, ox:ox + W])

    def frame_index(self, n: int) -> np.ndarray:
        """Frame number n of the reel (t = n / fps)."""
        return self.frame(n / self.fps, n)

    def frame(self, t: float, n: int | None = None) -> np.ndarray:
        """The finished picture at reel time t: H x W x 3 RGB uint8."""
        if n is None:
            n = int(round(t * self.fps))
        t = min(max(float(t), 0.0), self.duration)
        img = self._picture(t)
        img = self._bloom(img)
        img = self._leak(img, t)
        img = cv2.multiply(img, self._mask, scale=1 / 255.0)
        img = self._draw_endcard_veil_and_text(img, t)
        img = self._add_grain(img, n)
        fade_in = float(self.cfg["hook"]["max_black_fade_in_s"]) if not self._hook else 0.0
        k = 1.0
        if fade_in > 0 and t < fade_in:
            k *= FADE_IN_FLOOR + (1 - FADE_IN_FLOOR) * em.smooth(t / fade_in)
        if t > self.duration - FADE_OUT_S:
            k *= 1.0 - em.smooth((t - (self.duration - FADE_OUT_S)) / FADE_OUT_S)
        if k < 1.0:
            img = cv2.convertScaleAbs(img, alpha=k)
        return img

    def _draw_endcard_veil_and_text(self, img: np.ndarray, t: float) -> np.ndarray:
        img = np.ascontiguousarray(img)
        if self._ec and t >= self._ec["t"]:
            img = self._draw_endcard(img, t)
            self._draw_captions(img, t)
            return img
        self._draw_hook(img, t)
        self._draw_captions(img, t)
        return img


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
# The reel is encoded in fixed segments of SEGMENT_S seconds (one GOP each), every
# segment by its own single-threaded encoder, then the segments are joined into
# one stream and muxed. Segment boundaries depend only on the frame range, never
# on the worker count, so any --workers gives the same bytes, and encoding scales
# across cores (x264's own threading barely does at 1080x1920).
SEGMENT_S = 2.0


def videotoolbox_available() -> bool:
    try:
        out = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-encoders"], check=False)
    except nc.UserError:
        return False
    return b"h264_videotoolbox" in (out.stdout or b"")


def encoder_args(encoder: str, draft: bool, fps: float, segment_s: float = SEGMENT_S) -> tuple[list[str], dict]:
    """ffmpeg output arguments for one segment's video stream, plus a summary for render.json."""
    cfg = nc.config_value("render")
    v = cfg["video"]
    preset = cfg["draft"]["preset"] if draft else v.get("preset", "medium")
    crf = cfg["draft"]["crf"] if draft else v["crf"]
    gop = str(max(1, int(round(fps * segment_s))))
    color = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    if encoder == "videotoolbox":
        args = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-b:v", "10M", "-maxrate", v["maxrate"],
                "-bufsize", v["bufsize"], "-allow_sw", "1", "-g", gop]
        info = {"encoder": "h264_videotoolbox", "bitrate": "10M"}
    else:
        args = ["-c:v", "libx264", "-profile:v", v.get("profile", "high"), "-preset", preset, "-crf", str(crf),
                "-maxrate", v["maxrate"], "-bufsize", v["bufsize"], "-g", gop, "-threads", "1"]
        info = {"encoder": "libx264", "preset": preset, "crf": crf, "encoder_threads": 1}
    args += ["-pix_fmt", v.get("pix_fmt", "yuv420p"), *color]
    info["segment_s"] = segment_s
    return args, info


def _rate(fps: float) -> str:
    r = Fraction(fps).limit_denominator(1001)
    return f"{r.numerator}/{r.denominator}"


def _segment_cmd(out: Path, W: int, H: int, fps: float, enc_args: list[str]) -> list[str]:
    return [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", _rate(fps),
            "-i", "pipe:0", "-an", "-sn",
            "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic+accurate_rnd+full_chroma_int",
            *enc_args, "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1",
            "-f", "mp4", str(out)]


def _encode_segment(r: "Renderer", frames: range, out: Path, enc_args: list[str]) -> None:
    """Render frames and encode them into one H.264 elementary-stream segment."""
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(_segment_cmd(out, r.width, r.height, r.fps, enc_args),
                            stdin=subprocess.PIPE, stderr=errf)
    assert proc.stdin is not None
    try:
        for n in frames:
            proc.stdin.write(r.frame_index(n).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        proc.kill()
        proc.wait()
        errf.close()
        raise
    rc = proc.wait()
    errf.seek(0)
    err = errf.read().decode("utf-8", "replace")
    errf.close()
    if rc != 0:
        detail = " | ".join(err.strip().splitlines()[-3:]) or f"exit {rc}"
        raise nc.UserError(f"ffmpeg encoder failed: {detail}")


# ---------------------------------------------------------------------------
# Parallel segments
# ---------------------------------------------------------------------------
_WORKER: "Renderer | None" = None
_WORKER_ARGS: list[str] = []


def _worker_init(plan: dict, size, draft, cache_dir: str, enc_args: list[str]) -> None:
    global _WORKER, _WORKER_ARGS
    cv2.setNumThreads(1)
    _WORKER = Renderer(plan, size=size, draft=draft, quiet=True)
    _WORKER.attach_cache(cache_dir)
    _WORKER_ARGS = enc_args


def _worker_segment(job: tuple[int, int, int, str]) -> int:
    k, a, b, out = job
    assert _WORKER is not None
    try:
        _encode_segment(_WORKER, range(a, b), Path(out), _WORKER_ARGS)
    except nc.UserError as e:
        # exceptions cross the process boundary as plain text
        raise RuntimeError(f"USERERROR:{e}") from None
    return k


def _frame_range(fps: float, duration: float, t_from: float | None, t_to: float | None) -> range:
    total = max(1, int(round(duration * fps)))
    a = 0 if t_from is None else int(math.ceil(t_from * fps - 1e-6))
    b = total if t_to is None else min(total, int(math.ceil(t_to * fps - 1e-6)))
    return range(max(0, a), max(a + 1, b))


def _as_plan(plan: dict | str | os.PathLike) -> dict:
    return load_plan(plan) if isinstance(plan, (str, os.PathLike)) else plan


def render_frame(plan: dict | str | os.PathLike, t: float, size: tuple[int, int] | None = None,
                 draft: bool | None = None) -> np.ndarray:
    """One finished frame (RGB uint8) at reel time t."""
    with Renderer(_as_plan(plan), size=size, draft=draft) as r:
        return r.frame(t)


def _mux(segments: list[Path], out: Path) -> None:
    """Join the segment MP4s (concat demuxer, stream copy) into one faststart MP4."""
    lst = out.with_name("segments.txt")
    lst.write_text("ffconcat version 1.0\n" + "".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")
    nc.ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0:v", "-c:v", "copy",
              "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1",
              "-movflags", "+faststart", "-f", "mp4", str(out), what="ffmpeg mux")


def render_video(plan: dict | str | os.PathLike, out_path: str | os.PathLike, *, t_from: float | None = None,
                 t_to: float | None = None, size: tuple[int, int] | None = None, draft: bool | None = None,
                 workers: int | None = None, encoder: str = "libx264", progress: bool = True,
                 segment_s: float = SEGMENT_S) -> dict:
    """Render [t_from, t_to) (default: the whole reel) to an MP4 without audio. Returns the render.json dict.

    segment_s is the encoder segment (GOP) length; the bytes depend on it, never on workers."""
    t_start = time.perf_counter()
    plan = _as_plan(plan)
    workers = max(1, int(workers or os.cpu_count() or 1))
    if encoder not in ("libx264", "videotoolbox"):
        raise nc.UsageError(f"--encoder must be libx264 or videotoolbox, got {encoder!r}")
    if encoder == "videotoolbox" and not videotoolbox_available():
        nc.warn("encoder: h264_videotoolbox is not available here; using libx264")
        encoder = "libx264"
    r = Renderer(plan, size=size, draft=draft)
    duration = r.duration
    if t_from is not None and not 0 <= t_from < duration:
        raise nc.UserError(f"--from {t_from:g} is outside the reel (0-{duration:g} s)")
    if t_to is not None and not (t_from or 0) < t_to <= duration + 1e-9:
        raise nc.UserError(f"--to {t_to:g} must be after --from and at most the duration ({duration:g} s)")
    frames = _frame_range(r.fps, duration, t_from, t_to)
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    enc_args, enc_info = encoder_args(encoder, r.draft, r.fps, segment_s)
    seg_len = max(1, int(round(r.fps * segment_s)))
    starts = list(range(frames.start, frames.stop, seg_len))
    timings: dict[str, float] = {}
    old_threads = cv2.getNumThreads()
    with tempfile.TemporaryDirectory(prefix="numa-render-") as tmp:
        tmpd = Path(tmp)
        cache = tmpd / "cache"
        cache.mkdir()
        t0 = time.perf_counter()
        r.build_cache(cache, frames.start / r.fps, (frames.stop - 1) / r.fps)
        timings["prepare_s"] = round(time.perf_counter() - t0, 3)
        t1 = time.perf_counter()
        jobs = [(k, a, min(a + seg_len, frames.stop), str(tmpd / f"seg_{k:05d}.mp4")) for k, a in enumerate(starts)]
        pool_n = min(workers, len(jobs))
        try:
            if pool_n > 1:
                ctx = mp.get_context("spawn")
                with ctx.Pool(pool_n, initializer=_worker_init,
                              initargs=(plan, size, r.draft, str(cache), enc_args)) as pool:
                    try:
                        for done, _k in enumerate(pool.imap_unordered(_worker_segment, jobs), 1):
                            if progress:
                                nc.info(f"engine: segment {done}/{len(jobs)}")
                    except RuntimeError as e:
                        msg = str(e)
                        if msg.startswith("USERERROR:"):
                            raise nc.UserError(msg[len("USERERROR:"):]) from None
                        raise
            else:
                cv2.setNumThreads(1)
                for k, a, b, path in jobs:
                    _encode_segment(r, range(a, b), Path(path), enc_args)
                    if progress:
                        nc.info(f"engine: segment {k + 1}/{len(jobs)}")
        finally:
            cv2.setNumThreads(old_threads)
            r.close()
        timings["render_encode_s"] = round(time.perf_counter() - t1, 3)
        t2 = time.perf_counter()
        tmp_out = tmpd / "joined.mp4"
        _mux([Path(j[3]) for j in jobs], tmp_out)
        os.replace(tmp_out, out) if tmp_out.stat().st_dev == out.parent.stat().st_dev else \
            out.write_bytes(tmp_out.read_bytes())
        timings["mux_s"] = round(time.perf_counter() - t2, 3)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    timings["total_s"] = round(time.perf_counter() - t_start, 3)
    n = len(frames)
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "output": str(out),
        "sha256": digest,
        "bytes": out.stat().st_size,
        "frames": n,
        "fps": r.fps,
        "size": [r.width, r.height],
        "range": [frames.start / r.fps, frames.stop / r.fps],
        "duration": round(n / r.fps, 6),
        "draft": r.draft,
        "workers": workers,
        **enc_info,
        "seed": r.seed,
        "timings": timings,
        "frames_per_second": round(n / max(1e-9, timings["total_s"]), 2),
    }


# ---------------------------------------------------------------------------
# Preview and images
# ---------------------------------------------------------------------------
def save_image(rgb: np.ndarray, path: str | os.PathLike, quality: int = 92) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(np.ascontiguousarray(rgb))
    if p.suffix.lower() in (".jpg", ".jpeg"):
        im.save(p, quality=quality, subsampling=0)
    else:
        im.save(p)
    return p


def render_preview(plan: dict | str | os.PathLike, times: Sequence[float], out_path: str | os.PathLike,
                   size: tuple[int, int] | None = None, cols: int = 5) -> Path:
    """Render the given reel times into one grid image (cols tiles per row, labelled with the time)."""
    plan = _as_plan(plan)
    if not times:
        raise nc.UsageError("preview needs at least one time")
    with Renderer(plan, size=size, draft=False) as r:
        for t in times:
            if not 0 <= t <= r.duration:
                raise nc.UserError(f"preview time {t:g} is outside the reel (0-{r.duration:g} s)")
        tw = PREVIEW_TILE_W
        th = int(round(tw * r.height / r.width))
        tiles = []
        for t in times:
            fr = r.frame(t)
            tile = Image.fromarray(cv2.resize(fr, (tw, th), interpolation=cv2.INTER_AREA))
            d = ImageDraw.Draw(tile)
            label = f"{t:.2f}s"
            d.rectangle((0, 0, 8 * len(label) + 10, 20), fill=(0, 0, 0))
            d.text((5, 4), label, fill=(255, 255, 255))
            tiles.append(np.asarray(tile))
    rows = int(math.ceil(len(tiles) / cols))
    grid = np.full((rows * th, cols * tw, 3), 24, np.uint8)
    for k, tile in enumerate(tiles):
        y, x = divmod(k, cols)
        grid[y * th:(y + 1) * th, x * tw:(x + 1) * tw] = tile
    return save_image(grid, out_path, quality=90)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser() -> nc.ArgParser:
    p = nc.ArgParser(
        prog="engine.py",
        description="Render a NUMA reel from plan.json (silent MP4), or a preview grid of chosen times.",
        epilog="Preview: engine.py PLAN_JSON preview T1 [T2 ...] [--size WxH] [--out FILE]")
    p.add_argument("plan", help="plan.json")
    p.add_argument("mode", nargs="*", help="'preview' followed by reel times in seconds")
    p.add_argument("--draft", action="store_true", help="lower resolution and fast preset (config render.draft)")
    p.add_argument("--workers", type=int, default=None, help="parallel frame workers (default: CPU count)")
    p.add_argument("--size", default=None, help="output size WxH (default: the plan's size)")
    p.add_argument("--from", dest="t_from", type=float, default=None, help="render from this reel time (s)")
    p.add_argument("--to", dest="t_to", type=float, default=None, help="render up to this reel time (s)")
    p.add_argument("--out", default=None, help="output file (default: in the plan's out_dir)")
    p.add_argument("--encoder", choices=("libx264", "videotoolbox"), default="libx264",
                   help="videotoolbox = macOS hardware encoder (falls back to libx264)")
    return p


def _num(x: float) -> str:
    return f"{x:g}"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    size = nc.parse_size(args.size) if args.size else None
    if args.workers is not None and args.workers < 1:
        raise nc.UsageError("--workers must be at least 1")
    plan = load_plan(args.plan)
    out_dir = Path(plan["out_dir"])
    if args.mode:
        if args.mode[0] != "preview":
            raise nc.UsageError(f"unknown mode {args.mode[0]!r}; the only mode is 'preview'")
        try:
            times = [float(x) for x in args.mode[1:]]
        except ValueError:
            raise nc.UsageError("preview times must be numbers (seconds)") from None
        if not times:
            raise nc.UsageError("preview needs at least one time, e.g. preview 0 1.5 3")
        out = Path(args.out).expanduser().resolve() if args.out else out_dir / "preview.jpg"
        path = render_preview(plan, times, out, size=size)
        print(path)
        return 0
    draft = True if args.draft else None
    if args.out:
        out = Path(args.out).expanduser().resolve()
    elif args.t_from is not None or args.t_to is not None:
        a = args.t_from or 0.0
        b = args.t_to if args.t_to is not None else float(plan["duration"])
        out = out_dir / f"segment_{_num(a)}_{_num(b)}.mp4"
    else:
        is_draft = args.draft or plan.get("quality") == "draft"
        out = out_dir / ("video_noaudio_draft.mp4" if is_draft else "video_noaudio.mp4")
    info = render_video(plan, out, t_from=args.t_from, t_to=args.t_to, size=size, draft=draft,
                        workers=args.workers, encoder=args.encoder)
    info["plan"] = str(Path(args.plan).expanduser().resolve())
    nc.write_json(out_dir / "render.json", info)
    tm = info["timings"]
    print(f"{info['output']}  {info['size'][0]}x{info['size'][1]}  {info['frames']} frames  "
          f"{tm['total_s']:.1f} s ({info['workers']} workers, {info['encoder']})")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
