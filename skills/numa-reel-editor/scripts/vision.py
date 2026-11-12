#!/usr/bin/env python3
"""Smart framing and clip intelligence for a reel's media (R279, R282).

Usage:
    vision.py ANALYSIS_JSON [--no-clips] [--json]

For every photo and clip listed in analysis.json (written by analyze.py) this
adds, in place:

  faces     face boxes [x, y, w, h], normalized 0-1 of the source (YuNet face
            detector bundled in assets/models, run at two scales, filtered by
            size, confidence, landmark geometry and non-maximum suppression;
            OpenCV's built-in Haar cascades are the fallback when YuNet is unavailable)
  focus     the main subject point [x, y]: the largest faces first, else the
            centroid of a saliency + edge-energy map with a mild centre prior
  flags     weak-media signals for the Director's fallbacks: landscape,
            low_res, blurry, shaky (clips), dark
  scores    clips only: one entry per clip second {t, sharpness, motion, faces,
            score} from frames sampled at 2 fps
  windows   clips only: up to 3 best non-overlapping windows [t0, t1, score]
            of 2-5 s, best first; the clip's faces/focus come from the best one

Deterministic and idempotent: the same analysis.json gives the same result and
re-running overwrites only these fields. The file is validated against
schemas/analysis.schema.json before it is written. Thresholds can be tuned in
config/studio.json under `vision` (see DEFAULTS).

See docs/CONTRACTS.md sections 3 and 9.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

MODEL_PATH = nc.ASSETS_DIR / "models" / "face_detection_yunet_2023mar.onnx"
FLAG_ORDER = ("landscape", "low_res", "blurry", "shaky", "dark")

# Tunable thresholds (config/studio.json `vision.<key>` overrides each one).
DEFAULTS: dict[str, float] = {
    "min_short_side": 1080,        # px: a shorter side below this is low_res (needs upscale)
    "landscape_aspect": 1.0,       # w/h above this is landscape (needs outpaint or a pan)
    "dark_brightness": 0.25,       # mean luma 0-1 below this is dark ...
    "dark_highlights": 0.6,        # ... when its 95th-percentile luma is also below this (low-key shots with
                                   # lit highlights, e.g. a glowing sauna, are moody, not underexposed)
    "blurry_photo_peak": 60.0,     # 90th-percentile tile Laplacian variance (<= 1080 px wide) below this is blurry
    "blurry_clip_sharpness": 25.0,  # median contrast-normalized Laplacian variance of 540-wide clip frames
                                    # below this is blurry
    "shaky_clip_shake": 0.6,       # analyze.py shake (% of width) above this is shaky
    "face_score": 0.75,            # YuNet confidence to accept a face found at one scale only
    "face_score_multi": 0.64,      # mean confidence to accept a face both scales found
    "face_min_frac": 0.022,        # smallest face side as a fraction of the image's shorter side
}

CLIP_FPS = 2.0                 # clip frames sampled per second
CLIP_WIDTH = 540               # sampled frames are this wide (analyze.py samples at 540 too)
FLOW_WIDTH = 160               # optical flow runs on this width
DETECT_SIZES = (640, 1280)     # longer side of the two detection passes (never upscaled past 1x)
MAX_FACES = 40
WINDOW_LENGTHS = (2, 3, 4, 5)
MAX_WINDOWS = 3
SHARP_HALF = 100.0             # sharpness giving a 0.5 sharpness score (540-wide frames)


def cfg(key: str) -> float:
    value = nc.config_value(f"vision.{key}", DEFAULTS[key])
    try:
        return float(value)
    except (TypeError, ValueError):
        raise nc.UserError(f"config vision.{key} must be a number, got {value!r}") from None


def r4(x: float) -> float:
    return round(min(1.0, max(0.0, float(x))), 4)


# ---------------------------------------------------------------------------
# Face detection
# ---------------------------------------------------------------------------
class FaceDetector:
    """Deterministic face detection with false-positive filters.

    Primary: YuNet (cv2.FaceDetectorYN, MIT model bundled in assets/models) at
    two scales. Filters: minimum face size relative to the image, confidence
    (the mean of both scales when both found the face), plausible box aspect,
    landmark geometry (both eyes above the nose, nose above the mouth, eye
    distance a sensible fraction of the box) and NMS / containment suppression.

    Fallback (YuNet unavailable, or backend="haar"): OpenCV's built-in Haar
    cascades, frontal (default + alt2) and profile (both directions), multi-scale,
    with the same size floor; a frontal face is kept when both frontal cascades
    agree or an eye is found in its upper half, a profile face needs more
    neighbours. `backend` is "yunet", "haar" or None (no detector at all)."""

    def __init__(self, backend: str = "auto") -> None:
        import cv2
        self.cv2 = cv2
        self.backend: str | None = None
        self.reason = ""
        self.score1 = cfg("face_score")
        self.score2 = cfg("face_score_multi")
        self.min_frac = cfg("face_min_frac")
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:  # noqa: BLE001 - older builds without the logging module
            pass
        if backend in ("auto", "yunet"):
            if not hasattr(cv2, "FaceDetectorYN"):
                self.reason = f"OpenCV {cv2.__version__} has no FaceDetectorYN"
            elif not MODEL_PATH.is_file():
                self.reason = f"face model missing: {MODEL_PATH}"
            else:
                try:
                    self.net = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (320, 320), 0.5, 0.3, 5000)
                    self.backend = "yunet"
                    return
                except Exception as e:  # noqa: BLE001 - unreadable model or unsupported build
                    self.reason = f"cannot load the face model ({type(e).__name__}: {e})"
        if backend in ("auto", "haar"):
            self._init_haar()

    def _init_haar(self) -> None:
        cv2 = self.cv2
        folder = Path(getattr(getattr(cv2, "data", None), "haarcascades", "") or "")
        names = {"frontal": "haarcascade_frontalface_default.xml", "alt2": "haarcascade_frontalface_alt2.xml",
                 "profile": "haarcascade_profileface.xml", "eye": "haarcascade_eye.xml"}
        if not hasattr(cv2, "CascadeClassifier") or not all((folder / n).is_file() for n in names.values()):
            self.reason = (self.reason + "; " if self.reason else "") + \
                f"OpenCV {cv2.__version__} has no built-in Haar cascades"
            return
        self.cascades = {k: cv2.CascadeClassifier(str(folder / n)) for k, n in names.items()}
        if any(c.empty() for c in self.cascades.values()):
            self.reason = (self.reason + "; " if self.reason else "") + "cannot load the Haar cascades"
            return
        self.backend = "haar"

    @property
    def available(self) -> bool:
        return self.backend is not None

    def _raw(self, bgr) -> list[tuple[float, float, float, float, float]]:
        """Raw detections at this image's size: (x, y, w, h, score) in px, after the geometry check."""
        h, w = bgr.shape[:2]
        self.net.setInputSize((w, h))
        _, res = self.net.detect(bgr)
        out = []
        if res is None:
            return out
        for row in res:
            x, y, bw, bh = (float(v) for v in row[:4])
            lm = [(float(row[4 + 2 * k]), float(row[5 + 2 * k])) for k in range(5)]
            if bw <= 0 or bh <= 0 or not _plausible(x, y, bw, bh, lm):
                continue
            out.append((x, y, bw, bh, float(row[14])))
        return out

    def detect(self, bgr) -> list[list[float]]:
        """Face boxes [x, y, w, h] normalized to the image, largest first."""
        if self.backend == "haar":
            return self._detect_haar(bgr)
        if not self.available:
            return []
        cv2 = self.cv2
        H, W = bgr.shape[:2]
        long_side = max(H, W)
        sizes = sorted({min(s, long_side) for s in DETECT_SIZES})
        cands: list[tuple[float, float, float, float, float, int]] = []
        for k, size in enumerate(sizes):
            scale = size / long_side
            img = bgr if scale == 1.0 else cv2.resize(bgr, (max(1, round(W * scale)), max(1, round(H * scale))),
                                                      interpolation=cv2.INTER_AREA)
            for x, y, bw, bh, s in self._raw(img):
                cands.append((x / scale, y / scale, bw / scale, bh / scale, s, k))
        min_side = self.min_frac * min(H, W)
        cands = [c for c in cands if min(c[2], c[3]) >= min_side]
        # cross-scale agreement: a face both passes found is judged on its mean confidence (a hand or
        # a pattern that looks like a face at one scale rarely does at the other); a face only one
        # pass found (too small for the coarse pass, or too large for the fine one) needs a higher score
        kept = []
        for c in cands:
            other = [o[4] for o in cands if o[5] != c[5] and _iou(c, o) >= 0.4]
            if (other and (c[4] + max(other)) / 2 >= self.score2) or (not other and c[4] >= self.score1):
                kept.append(c)
        kept.sort(key=lambda c: (-c[4], -c[2] * c[3], c[0], c[1]))
        chosen: list[tuple] = []
        for c in kept:
            if all(_iou(c, o) < 0.3 and _contain(c, o) < 0.6 for o in chosen):
                chosen.append(c)
        return self._normalize(chosen, W, H)

    def _detect_haar(self, bgr) -> list[list[float]]:
        cv2 = self.cv2
        H, W = bgr.shape[:2]
        scale = min(1.0, 640 / max(H, W))
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if scale < 1.0:
            gray = cv2.resize(gray, (round(W * scale), round(H * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.equalizeHist(gray)
        gw = gray.shape[1]
        min_px = max(16, int(self.min_frac * min(gray.shape[:2])))

        def run(name, img, neighbours):
            found = self.cascades[name].detectMultiScale(img, scaleFactor=1.15, minNeighbors=neighbours,
                                                         minSize=(min_px, min_px))
            return [tuple(float(v) for v in r) for r in (found if len(found) else [])]

        frontal, alt2 = run("frontal", gray, 5), run("alt2", gray, 3)
        cands = []
        for b in frontal:
            agree = any(_iou((*b, 0), (*o, 0)) >= 0.4 for o in alt2)
            agree_eye = False
            if not agree:
                x, y, w, h = (int(v) for v in b)
                upper = gray[y:y + h // 2 + 1, x:x + w]
                agree_eye = len(self.cascades["eye"].detectMultiScale(
                    upper, scaleFactor=1.1, minNeighbors=4, minSize=(max(4, w // 8), max(4, w // 8)))) > 0
            if agree or agree_eye:
                cands.append((*b, 1.0 if agree else 0.9, 0))
        for b in run("profile", gray, 10):
            cands.append((*b, 0.8, 0))
        for x, y, w, h in run("profile", cv2.flip(gray, 1), 10):
            cands.append((gw - x - w, y, w, h, 0.8, 0))
        cands.sort(key=lambda c: (-c[4], -c[2] * c[3], c[0], c[1]))
        chosen: list[tuple] = []
        for c in cands:
            if all(_iou(c, o) < 0.3 and _contain(c, o) < 0.6 for o in chosen):
                chosen.append(c)
        chosen = [(x / scale, y / scale, w / scale, h / scale, s, k) for x, y, w, h, s, k in chosen]
        return self._normalize(chosen, W, H)

    @staticmethod
    def _normalize(chosen: list[tuple], W: int, H: int) -> list[list[float]]:
        chosen = sorted(chosen, key=lambda c: (-round(c[2] * c[3]), round(c[0]), round(c[1])))
        boxes = []
        for x, y, bw, bh, _s, _k in chosen[:MAX_FACES]:
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(float(W), x + bw), min(float(H), y + bh)
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            boxes.append([r4(x0 / W), r4(y0 / H), r4((x1 - x0) / W), r4((y1 - y0) / H)])
        return boxes


def _plausible(x: float, y: float, w: float, h: float, lm: list[tuple[float, float]]) -> bool:
    """Box aspect and landmark geometry of a real face (frontal or three-quarter)."""
    if not 0.75 <= h / w <= 2.2:
        return False
    (rex, rey), (lex, ley), (nx, ny), (rmx, rmy), (lmx, lmy) = lm
    pad_x, pad_y = 0.2 * w, 0.2 * h
    if any(not (x - pad_x <= px <= x + w + pad_x and y - pad_y <= py <= y + h + pad_y) for px, py in lm):
        return False
    eye_y, mouth_y = (rey + ley) / 2, (rmy + lmy) / 2
    if not eye_y < ny < mouth_y:
        return False
    eye_d = math.hypot(lex - rex, ley - rey)
    if not 0.12 * w <= eye_d <= 0.85 * w:
        return False
    if (mouth_y - eye_y) < 0.15 * h:
        return False
    return True


def _iou(a, b) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _contain(a, b) -> float:
    """Intersection over the smaller box's area."""
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    small = min(a[2] * a[3], b[2] * b[3])
    return ix * iy / small if small > 0 else 0.0


# ---------------------------------------------------------------------------
# Focus point
# ---------------------------------------------------------------------------
def face_focus(faces: Sequence[Sequence[float]]) -> list[float] | None:
    """Centre of the main faces (those at least 35% of the largest face's area), weighted by face size."""
    if not faces:
        return None
    areas = [b[2] * b[3] for b in faces]
    top = max(areas)
    main = [(b, math.sqrt(a)) for b, a in zip(faces, areas) if a >= 0.35 * top]
    total = sum(a for _, a in main)
    fx = sum((b[0] + b[2] / 2) * a for b, a in main) / total
    fy = sum((b[1] + b[3] / 2) * a for b, a in main) / total
    return [r4(fx), r4(fy)]


def saliency_focus(bgr) -> list[float]:
    """Centroid of the most salient 15% of a spectral-residual + edge-energy map (centre prior)."""
    import cv2
    import numpy as np
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    sw = 128
    sh = max(8, round(H * sw / W))
    small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    # spectral residual (Hou & Zhang 2007) on a 64-px copy
    sr_in = cv2.resize(small, (64, 64), interpolation=cv2.INTER_AREA)
    spec = np.fft.fft2(sr_in)
    log_amp = np.log(np.abs(spec) + 1e-6)
    residual = log_amp - cv2.blur(log_amp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(spec)))) ** 2
    sal = cv2.GaussianBlur(cv2.resize(sal.astype(np.float32), (sw, sh)), (0, 0), 3)
    # edge energy
    blur = cv2.GaussianBlur(small, (0, 0), 1.0)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    edge = cv2.GaussianBlur(np.sqrt(gx * gx + gy * gy), (0, 0), 4)

    def norm(a):
        lo, hi = float(a.min()), float(a.max())
        return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)

    m = 0.5 * norm(sal) + 0.5 * norm(edge)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    prior = np.exp(-(((xx + 0.5) / sw - 0.5) ** 2 + ((yy + 0.5) / sh - 0.5) ** 2) / (2 * 0.3 ** 2))
    m = m * prior
    if float(m.max()) <= 0:
        return [0.5, 0.5]
    thr = float(np.quantile(m, 0.85))
    wgt = np.where(m >= thr, m, 0.0).astype(np.float64)
    total = float(wgt.sum())
    if total <= 0:
        return [0.5, 0.5]
    fx = float((wgt * (xx + 0.5)).sum() / total / sw)
    fy = float((wgt * (yy + 0.5)).sum() / total / sh)
    return [r4(min(0.95, max(0.05, fx))), r4(min(0.95, max(0.05, fy)))]


# ---------------------------------------------------------------------------
# Image metrics and flags
# ---------------------------------------------------------------------------
def stretch(gray):
    """Contrast-normalized copy (1st..99th percentile -> 0..255) so a dark or flat exposure is not
    mistaken for blur: the Laplacian variance scales with the square of the contrast."""
    import numpy as np
    lo, hi = np.percentile(gray, (1, 99))
    if hi - lo < 1:
        return gray.astype(np.float32)
    return np.clip((gray.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)


def peak_sharpness(gray) -> float:
    """90th percentile of the Laplacian variance over a 4x4 tile grid, on a copy at most 1080 px wide.

    A shallow-depth-of-field portrait has a sharp subject and a soft background,
    so the sharpest tiles (not the global mean) decide whether a photo is blurry."""
    import cv2
    import numpy as np
    H, W = gray.shape[:2]
    if W > 1080:
        gray = cv2.resize(gray, (1080, max(1, round(H * 1080 / W))), interpolation=cv2.INTER_AREA)
        H, W = gray.shape[:2]
    lap = cv2.Laplacian(stretch(gray), cv2.CV_64F)
    vals = []
    for i in range(4):
        for j in range(4):
            tile = lap[i * H // 4:(i + 1) * H // 4, j * W // 4:(j + 1) * W // 4]
            if tile.size:
                vals.append(float(tile.var()))
    return round(float(np.quantile(vals, 0.9)), 2) if vals else 0.0


def size_flags(size: Sequence[int]) -> list[str]:
    w, h = int(size[0]), int(size[1])
    flags = []
    if h > 0 and w / h > cfg("landscape_aspect"):
        flags.append("landscape")
    if min(w, h) < cfg("min_short_side"):
        flags.append("low_res")
    return flags


def is_dark(brightness: float | None, highlights: float | None) -> bool:
    if brightness is None or float(brightness) >= cfg("dark_brightness"):
        return False
    return highlights is None or float(highlights) < cfg("dark_highlights")


def photo_flags(entry: dict, peak: float | None, highlights: float | None = None) -> list[str]:
    flags = size_flags(entry["size"])
    if peak is not None and peak < cfg("blurry_photo_peak"):
        flags.append("blurry")
    if is_dark(entry.get("brightness"), highlights):
        flags.append("dark")
    return [f for f in FLAG_ORDER if f in flags]


def clip_flags(entry: dict, median_sharpness: float | None, highlights: float | None = None) -> list[str]:
    flags = size_flags(entry["size"])
    if median_sharpness is not None and median_sharpness < cfg("blurry_clip_sharpness"):
        flags.append("blurry")
    if entry.get("shake") is not None and float(entry["shake"]) > cfg("shaky_clip_shake"):
        flags.append("shaky")
    if is_dark(entry.get("brightness"), highlights):
        flags.append("dark")
    return [f for f in FLAG_ORDER if f in flags]


def luma_p95(gray) -> float:
    import numpy as np
    return float(np.percentile(gray, 95)) / 255.0


def needs_stabilize(entry: dict) -> bool:
    """True when a clip is shaky (its `flags`, else its analyze.py shake metric)."""
    if "flags" in entry:
        return "shaky" in entry["flags"]
    return entry.get("shake") is not None and float(entry["shake"]) > cfg("shaky_clip_shake")


def needs_brighten(entry: dict) -> bool:
    """True when a photo or clip is dark (its `flags`, else its mean luma)."""
    if "flags" in entry:
        return "dark" in entry["flags"]
    return entry.get("brightness") is not None and float(entry["brightness"]) < cfg("dark_brightness")


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
def read_image(path: str):
    """BGR image the right way up (EXIF orientation applied, like analyze.py's `size`)."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as im:
            im.load()
            up = ImageOps.exif_transpose(im)
            if up.mode in ("RGBA", "LA", "P"):
                rgba = up.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (0, 0, 0))
                bg.paste(rgba, mask=rgba.split()[3])
                up = bg
            rgb = np.asarray(up.convert("RGB"), dtype=np.uint8)
    except FileNotFoundError:
        raise nc.UserError(f"photo not found: {path}") from None
    except Exception as e:  # noqa: BLE001 - unreadable image
        raise nc.UserError(f"cannot read photo {path}: {type(e).__name__}") from None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def process_photo(entry: dict, det: FaceDetector) -> None:
    import cv2
    bgr = read_image(entry.get("path"))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if entry.get("brightness") is None:
        entry["brightness"] = round(float(gray.mean()) / 255.0, 4)
    faces = det.detect(bgr)
    entry["faces"] = faces
    entry["focus"] = face_focus(faces) or saliency_focus(bgr)
    entry["flags"] = photo_flags(entry, peak_sharpness(gray), luma_p95(gray))


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------
def sample_clip(path: str, size: Sequence[int], duration: float):
    """Frames at CLIP_FPS, CLIP_WIDTH wide (display orientation): (times, uint8 array N x h x w x 3)."""
    import numpy as np
    w0, h0 = int(size[0]), int(size[1])
    w = CLIP_WIDTH
    h = max(2, int(round(h0 * w / w0 / 2)) * 2)
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-an", "-sn",
                   "-t", f"{duration:.3f}", "-vf", f"fps={CLIP_FPS:g},scale={w}:{h}:flags=area,format=bgr24",
                   "-f", "rawvideo", "-"], what=f"ffmpeg frames {Path(path).name}")
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = data.size // (w * h * 3)
    frames = data[: n * w * h * 3].reshape(n, h, w, 3)
    times = [round(k / CLIP_FPS, 3) for k in range(n)]
    return times, frames


def motion_score(m: float) -> float:
    """Movement preference: gentle movement best, a static frame fair, a whip pan poor (m in % of width per s)."""
    if m < 2.0:
        return 0.6 + 0.2 * m
    if m <= 15.0:
        return 1.0
    return max(0.2, 1.0 - (m - 15.0) / 40.0)


def second_score(sharp: float, motion: float, faces: int, bright: float) -> float:
    s = 0.45 * (sharp / (sharp + SHARP_HALF)) + 0.25 * motion_score(motion) + 0.30 * (1.0 if faces else 0.0)
    s *= 0.6 + 0.4 * min(1.0, bright / 0.3)
    return round(min(1.0, max(0.0, s)), 3)


def best_windows(scores: list[dict], duration: float) -> list[list[float]]:
    """Up to MAX_WINDOWS non-overlapping windows of 2-5 whole seconds, best first.

    Ranked by the mean per-second score with a small bonus per extra second (a
    longer good stretch is more useful to the editor); the reported score is the mean."""
    if not scores:
        return []
    vals = [float(s["score"]) for s in scores]
    n = len(vals)
    if duration < WINDOW_LENGTHS[0] or n < WINDOW_LENGTHS[0]:
        return [[0.0, round(duration, 2), round(sum(vals) / n, 3)]]
    cands = []
    for L in WINDOW_LENGTHS:
        if L > n or L > duration + 1e-6:
            continue
        for s0 in range(0, n - L + 1):
            if s0 + L > duration + 0.5:
                continue
            mean = sum(vals[s0:s0 + L]) / L
            cands.append((mean + 0.01 * (L - WINDOW_LENGTHS[0]), mean, s0, L))
    cands.sort(key=lambda c: (-round(c[0], 6), c[2], -c[3]))
    chosen: list[tuple[float, float]] = []
    out = []
    for _rank, mean, s0, L in cands:
        t0, t1 = float(s0), min(float(s0 + L), duration)
        if t1 - t0 < 1.0:
            continue
        if any(t0 < b and a < t1 for a, b in chosen):
            continue
        chosen.append((t0, t1))
        out.append([round(t0, 2), round(t1, 2), round(min(1.0, mean), 3)])
        if len(out) == MAX_WINDOWS:
            break
    return out


def process_clip(entry: dict, det: FaceDetector) -> None:
    import cv2
    import numpy as np
    path = entry.get("path")
    if not path or not Path(path).is_file():
        raise nc.UserError(f"clip not found: {path}")
    duration = float(entry.get("duration") or 0.0)
    if duration <= 0:
        raise nc.UserError(f"{entry.get('id')}: clip has no duration")
    times, frames = sample_clip(path, entry["size"], duration)
    if len(frames) == 0:
        raise nc.UserError(f"{entry.get('id')}: no decodable frames in {path}")
    h, w = frames.shape[1:3]
    fh = max(2, round(h * FLOW_WIDTH / w))
    sharp, sharp_norm, bright, highs, faces, motion, small = [], [], [], [], [], [], []
    for fr in frames:
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        sharp_norm.append(float(cv2.Laplacian(stretch(g), cv2.CV_64F).var()))
        bright.append(float(g.mean()) / 255.0)
        highs.append(luma_p95(g))
        faces.append(det.detect(fr))
        small.append(cv2.resize(g, (FLOW_WIDTH, fh), interpolation=cv2.INTER_AREA))
    for k in range(len(small)):
        if k == 0:
            motion.append(0.0)
            continue
        flow = cv2.calcOpticalFlowFarneback(small[k - 1], small[k], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag = float(np.sqrt((flow ** 2).sum(axis=2)).mean())
        motion.append(mag / FLOW_WIDTH * 100.0 * CLIP_FPS)   # % of width per second
    if len(motion) > 1:
        motion[0] = motion[1]
    # per-second aggregation
    scores = []
    n_sec = max(1, int(math.ceil(duration - 1e-6)))
    for t in range(n_sec):
        idx = [k for k, tk in enumerate(times) if t <= tk < t + 1]
        if not idx:
            continue
        sh = float(np.mean([sharp[k] for k in idx]))
        mo = float(np.mean([motion[k] for k in idx]))
        fc = max(len(faces[k]) for k in idx)
        br = float(np.mean([bright[k] for k in idx]))
        scores.append({"t": float(t), "sharpness": round(sh, 1), "motion": round(mo, 2), "faces": int(fc),
                       "score": second_score(sh, mo, fc, br)})
    windows = best_windows(scores, duration)
    entry["scores"] = scores
    entry["windows"] = windows
    # faces and focus from the best window: its frame with the most (then largest) faces
    t0, t1 = (windows[0][0], windows[0][1]) if windows else (0.0, duration)
    in_win = [k for k, tk in enumerate(times) if t0 <= tk < t1] or list(range(len(times)))
    best = min(in_win, key=lambda k: (-len(faces[k]), -sum(b[2] * b[3] for b in faces[k]), k))
    entry["faces"] = faces[best]
    focus = face_focus(faces[best])
    if focus is None:
        pts = [saliency_focus(frames[k]) for k in in_win]
        focus = [r4(sum(p[0] for p in pts) / len(pts)), r4(sum(p[1] for p in pts) / len(pts))]
    entry["focus"] = focus
    if entry.get("brightness") is None:
        entry["brightness"] = r4(float(np.mean(bright)))
    entry["flags"] = clip_flags(entry, float(np.median(sharp_norm)), float(np.median(highs)))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run_vision(analysis_path: Path, *, clips: bool = True, backend: str = "auto") -> dict:
    """Amend analysis.json in place; returns the report. `backend`: auto (YuNet, else Haar), yunet or haar."""
    import cv2
    started = time.monotonic()
    analysis_path = Path(analysis_path)
    A = nc.read_json(analysis_path, "analysis.json")
    if not isinstance(A, dict):
        raise nc.UserError(f"{analysis_path}: not a JSON object")
    errs = nc.schema_errors("analysis", A)
    if errs:
        raise nc.UserError(f"{analysis_path}: not a valid analysis.json ({errs[0]}); re-run analyze.py")
    cv2.setNumThreads(1)   # identical results on every run and machine core count
    det = FaceDetector(backend)
    warnings = list(A.get("warnings") or [])
    msg = None
    if not det.available:
        msg = f"face detection unavailable ({det.reason}): focus points come from saliency only"
    elif det.backend == "haar" and det.reason:
        msg = f"YuNet face detector unavailable ({det.reason}): using OpenCV Haar cascades (more missed faces)"
    if msg:
        nc.warn(msg)
        if msg not in warnings:
            warnings.append(msg)
    report: dict[str, Any] = {"analysis": str(analysis_path), "detector": det.backend,
                              "photos": [], "clips": []}
    for p in A.get("photos", []):
        process_photo(p, det)
        report["photos"].append({"id": p["id"], "faces": len(p["faces"]), "focus": p["focus"], "flags": p["flags"]})
    if clips:
        for c in A.get("clips", []):
            process_clip(c, det)
            report["clips"].append({"id": c["id"], "faces": len(c["faces"]), "focus": c["focus"],
                                    "windows": c["windows"], "flags": c["flags"]})
    if warnings:
        A["warnings"] = warnings
    nc.validate_against("analysis", A, "analysis.json")
    nc.write_json(analysis_path, A)
    report["seconds"] = round(time.monotonic() - started, 2)
    return report


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="vision.py", description="Detect faces and the main subject in every photo and clip, "
                                                    "score clip seconds and pick best windows; amends analysis.json.")
    ap.add_argument("analysis", metavar="ANALYSIS_JSON", help="the job's work/analysis.json (edited in place)")
    ap.add_argument("--no-clips", action="store_true", help="photos only (leave clip fields as they are)")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    report = run_vision(Path(args.analysis).expanduser().resolve(), clips=not args.no_clips)
    if args.json:
        nc.print_json(report)
        return 0
    print(f"analysis: {report['analysis']} ({report['seconds']:.1f} s)")
    for kind in ("photos", "clips"):
        for item in report[kind]:
            extra = f", best window {item['windows'][0][:2]}" if item.get("windows") else ""
            print(f"{item['id']}: {item['faces']} face(s), focus {item['focus']}{extra}, "
                  f"flags {', '.join(item['flags']) or 'none'}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
