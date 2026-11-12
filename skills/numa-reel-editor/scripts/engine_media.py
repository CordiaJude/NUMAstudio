#!/usr/bin/env python3
"""Picture sources for engine.py: loading, blur regions, grading, framing and video decoding.

Internal helper module of the render engine (see engine.py for the public API).
Everything here works in RGB uint8 arrays (H x W x 3).

* ``grade(img, look)``: the spec p.19 looks (``before``, ``warm``, ``none``) as a
  saturation mix plus one per-channel lookup table, so a full frame grades in a
  few milliseconds.
* ``blur_regions(img, boxes)``: pixelate-then-blur with feathered edges inside
  normalized ``[x, y, w, h]`` boxes (people not on the consent list, R106).
* ``Framing``: the view of one shot over time. The view never samples outside
  the source plate: zoom is kept >= 1 relative to a cover fit and the centre is
  clamped, so there are no black bars and no mirrored edges. Landscape sources
  pan across automatically; extreme panoramas use a blurred fill (last resort).
* ``build_image_plate``: a still prepared once per shot (EXIF orientation, blur
  regions, crop, resize to the resolution the shot needs, light sharpening).
* ``decode_video``: one sequential ffmpeg decode per shot (a single seek), frames
  delivered at the reel's frame cadence and the plate size.
"""
from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

try:  # HEIC stills straight from an iPhone (analyze.py normally converts them first)
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001 - optional codec; JPG/PNG work without it
    pass

# A source whose cover fit would show less than this fraction of its width is
# treated as a panorama and framed over a blurred fill instead (spec p.8 last resort).
PANORAMA_VISIBLE_FRACTION = 0.25
FILL_FOREGROUND_HEIGHT = 0.62  # panorama foreground height as a fraction of the canvas
AUTO_PAN_MIN_TRAVEL = 0.12     # auto pan when the spare width is at least 12% of the view
AUTO_PAN_SPAN = 0.8            # fraction of the available travel an auto pan covers


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------
def clamp01(p: float) -> float:
    return 0.0 if p < 0 else 1.0 if p > 1 else p


def smooth(p: float) -> float:
    """Smoothstep (zero velocity at both ends) for fades and slides."""
    p = clamp01(p)
    return p * p * (3 - 2 * p)


def ease_out(p: float) -> float:
    """Cubic ease-out: fast start, gentle landing (punch snap-back, text rise)."""
    p = clamp01(p)
    return 1 - (1 - p) ** 3


def motion_ease(p: float) -> float:
    """Shot motion: half linear, half cubic ease-out.

    Starts moving on frame 1 (velocity 2 at p=0, spec p.20 "movement from frame 1"),
    lands softly but never dead-stops (velocity 0.5 at p=1), and keeps drifting at
    that speed past the shot end so an outgoing shot under a crossfade or wipe is
    never frozen.
    """
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0 + 0.5 * (p - 1)
    return 0.5 * p + 0.5 * (1 - (1 - p) ** 3)


# ---------------------------------------------------------------------------
# Colour looks (spec p.19)
# ---------------------------------------------------------------------------
def _look_tables(look: str) -> tuple[float, np.ndarray | None]:
    x = np.arange(256, dtype=np.float64) / 255.0
    if look == "before":
        # 55% saturation, cool shift, lifted blacks
        sat, gains = 0.55, (0.94, 0.98, 1.05)
        chans = [np.clip((0.06 + 0.90 * np.clip(x * g, 0, 1)), 0, 1) ** 1.08 for g in gains]
    elif look == "warm":
        # slightly richer saturation, warm shift, gentle S-curve
        sat, gains = 1.08, (1.04, 1.0, 0.93)
        chans = []
        for g in gains:
            a = np.clip(x * g, 0, 1)
            a = a + 0.06 * np.sin(np.pi * a) * (a - 0.5) * 2
            chans.append(np.clip(0.02 + 0.97 * a, 0, 1))
    else:
        return 1.0, None
    lut = np.stack([np.round(c * 255) for c in chans], axis=-1).astype(np.uint8)
    return sat, lut.reshape(256, 1, 3)


_LOOKS = {name: _look_tables(name) for name in ("before", "warm", "none")}


def grade(img: np.ndarray, look: str) -> np.ndarray:
    """Apply a colour look to an RGB uint8 image (returns a new array; 'none' returns img)."""
    sat, lut = _LOOKS.get(look, _LOOKS["warm"])
    if lut is None:
        return img
    if sat != 1.0:
        gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
        img = cv2.addWeighted(img, sat, gray, 1.0 - sat, 0.0)
    return cv2.LUT(img, lut)


# ---------------------------------------------------------------------------
# Blur regions (R106: people not on the consent list)
# ---------------------------------------------------------------------------
def blur_regions(img: np.ndarray, boxes) -> np.ndarray:
    """Blur normalized [x, y, w, h] boxes beyond recognition (pixelate, then blur, feathered edges)."""
    if not boxes:
        return img
    out = img.copy()
    h, w = img.shape[:2]
    for bx, by, bw, bh in boxes:
        x0, y0 = int(math.floor(bx * w)), int(math.floor(by * h))
        x1, y1 = int(math.ceil((bx + bw) * w)), int(math.ceil((by + bh) * h))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        feather = max(2, int(0.12 * min(x1 - x0, y1 - y0)))
        # work on the box plus a feather margin so the edge fades into the picture
        X0, Y0 = max(0, x0 - feather), max(0, y0 - feather)
        X1, Y1 = min(w, x1 + feather), min(h, y1 + feather)
        roi = out[Y0:Y1, X0:X1]
        rh, rw = roi.shape[:2]
        blocks = 8
        sw = max(1, round(rw * blocks / max(1, min(rw, rh))))
        sh = max(1, round(rh * blocks / max(1, min(rw, rh))))
        small = cv2.resize(roi, (sw, sh), interpolation=cv2.INTER_AREA)
        big = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_LINEAR)
        sigma = max(1.0, min(rw, rh) / 10)
        big = cv2.GaussianBlur(big, (0, 0), sigma)
        mask = np.zeros((rh, rw), np.float32)
        mask[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = 1.0
        mask = cv2.GaussianBlur(mask, (0, 0), feather / 2.0)
        mask = np.maximum(mask, _inner_box(rh, rw, x0 - X0, y0 - Y0, x1 - X0, y1 - Y0, feather))[..., None]
        out[Y0:Y1, X0:X1] = (big.astype(np.float32) * mask + roi.astype(np.float32) * (1 - mask) + 0.5).astype(np.uint8)
    return out


def _inner_box(rh, rw, x0, y0, x1, y1, feather) -> np.ndarray:
    """1 inside the box shrunk by half the feather, so its core is fully blurred."""
    m = np.zeros((rh, rw), np.float32)
    f = feather // 2
    if x1 - x0 > 2 * f and y1 - y0 > 2 * f:
        m[y0 + f:y1 - f, x0 + f:x1 - f] = 1.0
    return m


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------
@dataclass
class Framing:
    """How one shot's plate maps onto the output frame over the shot.

    pw, ph: plate size; W, H: output size. Zoom 1.0 = the plate covers the frame
    exactly (cover fit); the effective zoom never goes below 1.0, so the view
    always lies inside the plate.
    """

    pw: int
    ph: int
    W: int
    H: int
    z0: float
    z1: float
    pan: tuple[float, float]
    focus: tuple[float, float]   # plate px
    auto_pan: int                # 0 = none, +1 = left->right, -1 = right->left

    @property
    def cover(self) -> float:
        return max(self.W / self.pw, self.H / self.ph)

    def view(self, p: float, extra: float = 1.0) -> tuple[float, float, float]:
        """(m, cx, cy): output px per plate px and view centre in plate px at shot progress p."""
        pe = motion_ease(p)
        z = max(1.0, (self.z0 + (self.z1 - self.z0) * pe) * extra)
        m = self.cover * z
        hw, hh = self.W / (2 * m), self.H / (2 * m)
        lo_x, hi_x = hw, self.pw - hw
        lo_y, hi_y = hh, self.ph - hh
        span_x = (self.W / self.cover)  # output frame width in plate px at zoom 1
        span_y = (self.H / self.cover)
        if self.auto_pan and hi_x > lo_x:
            u_end = clamp01((self.focus[0] - lo_x) / (hi_x - lo_x)) if hi_x > lo_x else 0.5
            if self.auto_pan > 0:
                u_end = max(u_end, AUTO_PAN_SPAN)
                u_start = u_end - AUTO_PAN_SPAN
            else:
                u_end = min(u_end, 1 - AUTO_PAN_SPAN)
                u_start = u_end + AUTO_PAN_SPAN
            u = u_start + (u_end - u_start) * min(pe, 1.0 + 0.1 * max(0.0, pe - 1.0))
            cx = lo_x + (hi_x - lo_x) * clamp01(u)
        else:
            cx = self.focus[0] + self.pan[0] * span_x * pe
        cy = self.focus[1] + self.pan[1] * span_y * pe
        cx = min(max(cx, lo_x), hi_x) if hi_x >= lo_x else self.pw / 2
        cy = min(max(cy, lo_y), hi_y) if hi_y >= lo_y else self.ph / 2
        return m, cx, cy

    def matrix(self, p: float, extra: float = 1.0) -> np.ndarray:
        """Inverse affine (output pixel -> plate pixel) for cv2.warpAffine(WARP_INVERSE_MAP)."""
        m, cx, cy = self.view(p, extra)
        a = 1.0 / m
        return np.array([[a, 0.0, cx - 0.5 + (0.5 - self.W / 2) * a],
                         [0.0, a, cy - 0.5 + (0.5 - self.H / 2) * a]], dtype=np.float64)

    def to_screen(self, p: float, x: float, y: float) -> tuple[float, float]:
        """Plate point -> output point at shot progress p."""
        m, cx, cy = self.view(p)
        return (x - cx) * m + self.W / 2, (y - cy) * m + self.H / 2

    def warp(self, plate: np.ndarray, p: float, extra: float = 1.0) -> np.ndarray:
        return cv2.warpAffine(plate, self.matrix(p, extra), (self.W, self.H),
                              flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE)


def effective_zoom(z) -> tuple[float, float]:
    """Plan z -> zoom >= 1 everywhere, keeping the motion: a range dipping below 1 is shifted up."""
    z0, z1 = float(z[0]), float(z[1])
    lift = max(0.0, 1.0 - min(z0, z1))
    return z0 + lift, z1 + lift


def is_panorama(sw: int, sh: int, W: int, H: int) -> bool:
    return (W / H) / (sw / sh) < PANORAMA_VISIBLE_FRACTION


def plate_geometry(sw: int, sh: int, W: int, H: int, zmax: float, panorama: bool) -> tuple[int, int]:
    """Plate size for a source of sw x sh: just enough resolution for the deepest zoom, never upscaled
    (cover-fit sources); panoramas get a canvas sized for the output."""
    if panorama:
        ch = int(round(H * zmax))
        fh = FILL_FOREGROUND_HEIGHT * ch
        fw = fh * sw / sh
        cw = max(int(round(fw)), int(math.ceil(ch * W / H)))
        return cw + (cw & 1), ch + (ch & 1)
    c = max(W / sw, H / sh)
    k = min(1.0, c * zmax)
    return max(2, int(round(sw * k))), max(2, int(round(sh * k)))


def make_framing(pw: int, ph: int, W: int, H: int, z, pan, focus_norm, index: int, panorama: bool,
                 src_aspect: float) -> Framing:
    z0, z1 = effective_zoom(z)
    focus = (focus_norm[0] * pw, focus_norm[1] * ph)
    if panorama:
        # focus is normalized to the source, which sits centred in the canvas
        fh = FILL_FOREGROUND_HEIGHT * ph
        fw = fh * src_aspect
        focus = ((pw - fw) / 2 + focus_norm[0] * fw, (ph - fh) / 2 + focus_norm[1] * fh)
    fr = Framing(pw, ph, W, H, z0, z1, (float(pan[0]), float(pan[1])), focus, 0)
    if float(pan[0]) == 0.0:
        view_w = W / (fr.cover * min(z0, z1))
        if pw - view_w >= AUTO_PAN_MIN_TRAVEL * view_w:
            fr.auto_pan = 1 if index % 2 == 0 else -1
    return fr


# ---------------------------------------------------------------------------
# Stills
# ---------------------------------------------------------------------------
def open_image(path: str | Path, what: str) -> Image.Image:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (0, 0, 0))
                bg.paste(rgba, mask=rgba.getchannel("A"))
                return bg
            return im.convert("RGB")
    except FileNotFoundError:
        raise nc.UserError(f"{what}: file not found: {path}") from None
    except Exception as e:  # noqa: BLE001 - PIL raises many types for unreadable files
        raise nc.UserError(f"{what}: cannot read image {path}: {type(e).__name__}") from None


def image_size(path: str | Path, crop, what: str) -> tuple[int, int]:
    """Displayed size after EXIF orientation and crop, without decoding the pixels."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            orient = im.getexif().get(0x0112, 1)
    except FileNotFoundError:
        raise nc.UserError(f"{what}: file not found: {path}") from None
    except Exception as e:  # noqa: BLE001
        raise nc.UserError(f"{what}: cannot read image {path}: {type(e).__name__}") from None
    if orient in (5, 6, 7, 8):
        w, h = h, w
    if crop:
        l, t, r, b = crop
        if not (0 <= l < r <= w and 0 <= t < b <= h):
            raise nc.UserError(f"{what}: crop {list(crop)} is outside the {w}x{h} image")
        w, h = r - l, b - t
    return w, h


def build_image_plate(path, crop, blur, pw: int, ph: int, panorama: bool, what: str) -> np.ndarray:
    """Load a still and prepare its plate (RGB uint8, ph x pw)."""
    im = open_image(path, what)
    if blur:
        im = Image.fromarray(blur_regions(np.asarray(im), blur))
    if crop:
        im = im.crop(tuple(crop))
    if panorama:
        return _panorama_plate(im, pw, ph)
    resample = Image.LANCZOS
    if im.size != (pw, ph):
        im = im.resize((pw, ph), resample)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=45, threshold=2))
    return np.ascontiguousarray(np.asarray(im, dtype=np.uint8))


def _panorama_plate(im: Image.Image, pw: int, ph: int) -> np.ndarray:
    fh = int(round(FILL_FOREGROUND_HEIGHT * ph))
    fw = max(2, int(round(fh * im.width / im.height)))
    src = np.asarray(im, dtype=np.uint8)
    # background: cover fit, heavily blurred and darkened
    k = max(pw / im.width, ph / im.height)
    small_w, small_h = max(8, int(im.width * k / 8)), max(8, int(im.height * k / 8))
    small = cv2.resize(src, (small_w, small_h), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 6)
    bg = cv2.resize(small, (max(pw, int(im.width * k + 1)), max(ph, int(im.height * k + 1))),
                    interpolation=cv2.INTER_LINEAR)
    oy, ox = (bg.shape[0] - ph) // 2, (bg.shape[1] - pw) // 2
    bg = (bg[oy:oy + ph, ox:ox + pw].astype(np.float32) * 0.45)
    fg = np.asarray(im.resize((fw, fh), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=45, threshold=2)), dtype=np.float32)
    fade = max(4, fh // 14)
    mask = np.ones((fh, 1), np.float32)
    ramp = (np.arange(fade, dtype=np.float32) + 0.5) / fade
    mask[:fade, 0] = ramp
    mask[-fade:, 0] = ramp[::-1]
    mask = mask[..., None]
    x0, y0 = (pw - fw) // 2, (ph - fh) // 2
    region = bg[y0:y0 + fh, max(0, x0):max(0, x0) + min(fw, pw)]
    fgc = fg[:, max(0, -x0):max(0, -x0) + region.shape[1]]
    bg[y0:y0 + fh, max(0, x0):max(0, x0) + region.shape[1]] = fgc * mask + region * (1 - mask)
    return np.ascontiguousarray(np.clip(bg + 0.5, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
def video_info(path, what: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise nc.UserError(f"{what}: file not found: {p}")
    try:
        info = nc.media_info(p)
    except nc.UserError as e:
        raise nc.UserError(f"{what}: {e}") from None
    if not info.get("has_video") or not info.get("width") or not info.get("height"):
        raise nc.UserError(f"{what}: no video stream in {p}")
    return info


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def decode_video(path, start: float, rate: float, count: int, pw: int, ph: int, blur=None,
                 sink=None, what: str = "video", _fallback: bool = True) -> np.ndarray | None:
    """Decode `count` frames of a clip from clip time `start`, one every 1/rate s, scaled to pw x ph.

    One ffmpeg process, one seek, sequential decode. When `sink` (an array of shape
    (count, ph, pw, 3), e.g. a memmap) is given, frames are written there and None is
    returned; otherwise a new array is returned. A clip that ends early repeats its
    last frame; a clip that yields no frame at all is a UserError.
    """
    out = sink if sink is not None else np.empty((count, ph, pw, 3), np.uint8)
    vf = f"fps={_fmt(rate)},scale={pw}:{ph}:flags=bicubic,format=rgb24"
    cmd = [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error",
           "-ss", _fmt(max(0.0, start)), "-i", str(path), "-an", "-sn",
           "-vf", vf, "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise nc.UserError(f"{what}: cannot start ffmpeg: {e}") from None
    size = pw * ph * 3
    got = 0
    assert proc.stdout is not None
    while got < count:
        buf = proc.stdout.read(size)
        if not buf or len(buf) < size:
            break
        out[got] = np.frombuffer(buf, np.uint8).reshape(ph, pw, 3)
        got += 1
    proc.stdout.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    proc.wait()
    if got == 0:
        # a start past the end of a short clip: fall back to its very last frame
        if start > 0 and _fallback:
            return _decode_last(path, rate, count, pw, ph, blur, out, sink, what)
        detail = " | ".join(err.strip().splitlines()[-2:]) or "no frames decoded"
        raise nc.UserError(f"{what}: cannot decode video {path}: {detail}")
    for k in range(got, count):
        out[k] = out[got - 1]
    if blur:
        for k in range(count):
            out[k] = blur_regions(out[k], blur)
    return None if sink is not None else out


def _decode_last(path, rate, count, pw, ph, blur, out, sink, what):
    info = video_info(path, what)
    dur = info.get("duration") or 0.0
    fps = info.get("fps") or 30.0
    t = max(0.0, dur - 1.5 / fps)
    one = decode_video(path, t, rate, 1, pw, ph, blur=blur, what=what, _fallback=False)
    if one is None:  # pragma: no cover - decode_video returns an array without a sink
        raise nc.UserError(f"{what}: cannot decode video {path}")
    out[:] = one[0]
    return None if sink is not None else out
