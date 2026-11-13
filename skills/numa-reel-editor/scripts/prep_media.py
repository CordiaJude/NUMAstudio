#!/usr/bin/env python3
"""Stabilize shaky clips and brighten dark clips/photos before a render (R287, D13).

Usage:
    prep_media.py ANALYSIS_JSON [--ids C0,P3,...] [--stabilize auto|on|off]
                  [--brighten auto|on|off] [--json]

Items are chosen from analysis.json: with `auto` (the default) a clip is
stabilized when vision.py flagged it `shaky` (or, before vision.py ran, when
analyze.py's shake metric is above the threshold) and a photo or clip is
brightened when it is flagged `dark`; `on` forces the step for every selected
item, `off` skips it. `--ids` limits the run to those items.

  stabilize   ffmpeg vidstabdetect + vidstabtransform when the ffmpeg build has
              them, else OpenCV feature tracking (Shi-Tomasi corners, pyramidal
              Lucas-Kanade, similarity fit) with a moving-average camera path.
              Both zoom just enough that no black border shows.
  brighten    a luma gamma lift found by bisection so the mean luma reaches
              about 0.40, capped so noise is not pulled up too far. Gamma maps
              white to white, so highlights are never blown; chroma gets a small
              boost so the lift does not look washed out.

Writes WORK/prep/<id>.mp4 (H.264 High, yuv420p, the clip's audio kept, scaled
so the shorter side is at most 1080) or WORK/prep/<id>.jpg and sets the item's
`prepared_path`, which the Editor and baseline_plan.py use as the shot `src`.
Faces are then detected again on the prepared copy: `faces`, `focus` and each
clip second's `faces` count describe the prepared file, and the original
file's boxes stay in `orig_faces` / `orig_focus` (blur boxes must match the
file the engine renders). vid.stab results with a jolt (a frame-to-frame jump
over 4% of the width) are replaced by the OpenCV result when that is steadier.
WORK/prep/index.json records each source's SHA-256, the steps applied and the
steps forced with `on` (a later `auto` run keeps them), so an unchanged source
is not processed again. An item whose steps all turn out off loses its
`prepared_path` and gets its faces from `path` again. Outputs are deterministic (fixed encoder threads, bit-exact
flags, no metadata timestamps).

See docs/CONTRACTS.md sections 2, 3 and 9 and DECISIONS.md D13.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import vision  # noqa: E402

PREP_VERSION = 2
MAX_SHORT_SIDE = 1080         # prepared clips are scaled down so the shorter side is at most this
VIDSTAB_SMOOTHING = 30        # vid.stab smoothing window (frames each side)
JUMP_LIMIT = 0.04             # a stabilized frame-to-frame jump above this fraction of the width is a failure
TARGET_LUMA = 0.40            # brighten to about this mean luma (0-1)
MAX_GAMMA = 2.2               # strongest lift (out = in ** (1 / gamma))
CHROMA_BOOST = 1.06           # saturation lift that goes with a brighten
SMOOTH_RADIUS_S = 1.0         # OpenCV fallback: camera path Gaussian smoothing radius (s)
MAX_CORRECTION = 0.08         # OpenCV fallback: largest shift correction (fraction of the frame)
MAX_ANGLE = math.radians(2.0)  # OpenCV fallback: largest rotation correction
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-threads", "4", "-x264-params", "threads=4:lookahead_threads=1"]
OPENCV_COLOR_TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
                     "-color_trc", "bt709"]
# the same tags on the frames themselves: ffmpeg 7+ takes the encoder's colour description from the
# frames (piped raw RGB frames have none) and drops primaries/transfer set only as output options
OPENCV_COLOR_FRAMES = "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
BITEXACT = ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-flags:a", "+bitexact", "-movflags", "+faststart"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=1)
def has_vidstab() -> bool:
    """True when this ffmpeg build has the vid.stab filters."""
    try:
        proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-filters"], what="ffmpeg -filters")
    except nc.UserError:
        return False
    text = proc.stdout.decode("utf-8", "replace")
    return "vidstabdetect" in text and "vidstabtransform" in text


def gamma_for(luma, target: float = TARGET_LUMA) -> float:
    """Gamma (>= 1) that lifts the mean of `luma` (values 0-1) to about `target`, capped at MAX_GAMMA."""
    import numpy as np
    v = np.clip(np.asarray(luma, dtype=np.float64).ravel(), 0.0, 1.0)
    if v.size == 0 or float(v.mean()) >= target:
        return 1.0
    lo, hi = 1.0, MAX_GAMMA
    if float(np.power(v, 1.0 / hi).mean()) <= target:
        return MAX_GAMMA
    for _ in range(40):
        mid = (lo + hi) / 2
        if float(np.power(v, 1.0 / mid).mean()) < target:
            lo = mid
        else:
            hi = mid
    return round(hi, 3)


def audio_args(info: dict, input_index: int) -> list[str]:
    if not info.get("has_audio"):
        return ["-an"]
    codec = ["-c:a", "copy"] if info.get("acodec") == "aac" else ["-c:a", "aac", "-b:a", "192k"]
    return ["-map", f"{input_index}:a:0", *codec]


_RANGE: dict[str, str | None] = {}


def color_range(path: str) -> str | None:
    """The video stream's color_range tag ('tv', 'pc', ...; None when unknown or without ffprobe)."""
    fp = Path(path).resolve()
    try:
        st = fp.stat()
        key = f"{fp}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        return None
    if key not in _RANGE:
        val = None
        try:
            data = nc.ffprobe_json(fp)
        except nc.UserError:
            data = {}
        for st in data.get("streams") or []:
            if st.get("codec_type") == "video":
                val = st.get("color_range") or None
                break
        _RANGE[key] = val
    return _RANGE[key]


def full_range(info: dict) -> bool:
    """Full-range (0-255) luma: a yuvj* pixel format (ffmpeg 6 and older) or a yuv* stream tagged
    color_range pc/jpeg (ffmpeg 7+ writes full range that way, as do some phones)."""
    if str(info.get("pix_fmt") or "").startswith("yuvj"):
        return True
    rng = info["color_range"] if "color_range" in info else (color_range(info["path"]) if info.get("path") else None)
    return str(rng or "").lower() in ("pc", "jpeg", "full")


def brighten_filter(gamma: float, full: bool) -> str:
    """lutyuv: gamma on luma in the clip's own range (white stays white), chroma boosted around neutral."""
    if full:
        y = f"clip(255*pow(val/255\\,{1 / gamma:.6f})\\,0\\,255)"
    else:
        y = f"clip(16+219*pow(clip((val-16)/219\\,0\\,1)\\,{1 / gamma:.6f})\\,16\\,235)"
    uv = f"clip(128+(val-128)*{CHROMA_BOOST:g}\\,0\\,255)"
    return f"lutyuv=y='{y}':u='{uv}':v='{uv}'"


def clip_luma(path: str, info: dict, duration: float):
    """Luma samples (0-1, black to white) from frames at 2 fps, 320 px wide.

    ffmpeg's gray conversion already maps the clip's own range (limited 16-235 or full 0-255, whatever
    its tags say) onto 0-255, so the samples are the real luma for either range; scaling them again
    for a limited-range clip would read every clip darker than it is."""
    import numpy as np
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-an", "-sn",
                   "-t", f"{duration:.3f}", "-vf", "fps=2,scale=320:-2,format=gray", "-f", "rawvideo", "-"],
                  what=f"ffmpeg luma {Path(path).name}")
    return np.frombuffer(proc.stdout, dtype=np.uint8).astype(np.float64) / 255.0


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
def brighten_photo(src: str, dst: Path) -> dict:
    import cv2
    import numpy as np
    from PIL import Image
    bgr = vision.read_image(src)
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    y = ycc[:, :, 0].copy()
    small = cv2.resize(y, (min(512, y.shape[1]), max(1, round(y.shape[0] * min(512, y.shape[1]) / y.shape[1]))),
                       interpolation=cv2.INTER_AREA)
    g = gamma_for(small.astype(np.float64) / 255.0)
    lut = np.clip(np.round(255.0 * np.power(np.arange(256) / 255.0, 1.0 / g)), 0, 255).astype(np.uint8)
    ycc[:, :, 0] = cv2.LUT(y, lut)
    chroma = ycc[:, :, 1:].astype(np.float32)
    ycc[:, :, 1:] = np.clip(np.round(128.0 + (chroma - 128.0) * CHROMA_BOOST), 0, 255).astype(np.uint8)
    out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
    tmp = dst.with_name(f".{dst.stem}.tmp.jpg")
    Image.fromarray(out).save(tmp, "JPEG", quality=95)
    os.replace(tmp, dst)
    return {"gamma": g, "brightness_before": round(float(y.mean()) / 255.0, 4),
            "brightness_after": round(float(ycc[:, :, 0].mean()) / 255.0, 4)}


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------
def _encode_out(tmp: Path) -> list[str]:
    return [*X264, *BITEXACT, str(tmp)]


def out_size(info: dict) -> tuple[int, int]:
    """Prepared size: the display size scaled so the shorter side is at most MAX_SHORT_SIDE, even numbers."""
    W, H = int(info["width"]), int(info["height"])
    k = min(1.0, MAX_SHORT_SIDE / min(W, H))
    return max(2, int(round(W * k / 2)) * 2), max(2, int(round(H * k / 2)) * 2)


def _scale(w: int, h: int) -> str:
    return f"scale={w}:{h}:flags=lanczos"


def stabilize_vidstab(src: str, info: dict, dst: Path, post: str | None, scratch: Path) -> None:
    """Two-pass vid.stab at the output size; optzoom=1 picks the static zoom that hides every border."""
    w, h = out_size(info)
    trf = "transforms.trf"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src, "-an", "-sn",
            "-vf", f"{_scale(w, h)},vidstabdetect=shakiness=10:accuracy=15:stepsize=6:result={trf}",
            "-f", "null", "-"], cwd=scratch, what="ffmpeg vidstabdetect")
    chain = (f"{_scale(w, h)},vidstabtransform=input={trf}:relative=1:smoothing={VIDSTAB_SMOOTHING}:optzoom=1:"
             f"zoomspeed=0:interpol=bilinear:crop=black,unsharp=5:5:0.5:3:3:0")
    if post:
        chain += "," + post
    tmp = scratch / "vidstab.mp4"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src,
            "-map", "0:v:0", *audio_args(info, 0), "-vf", chain, "-fps_mode", "passthrough", *_encode_out(tmp)],
           cwd=scratch, what="ffmpeg vidstabtransform")
    shutil.move(str(tmp), str(dst))


def _read_frames(src: str, w: int, h: int, rate: float | None = None, gray: bool = False):
    """Yield frames (h x w x 3 BGR, or h x w grey) of the clip in display orientation, one at a time.

    With `rate`, frames are resampled to that constant rate (a variable-rate phone clip keeps its timing)."""
    import numpy as np
    vf = (f"fps={rate:.6f}," if rate else "") + f"scale={w}:{h}:flags=area,format={'gray' if gray else 'bgr24'}"
    proc = subprocess.Popen([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", src, "-an", "-sn",
                             "-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    shape = (h, w) if gray else (h, w, 3)
    size = w * h * (1 if gray else 3)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(shape)
    finally:
        proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
        code = proc.wait()
        if code != 0:
            raise nc.UserError(f"ffmpeg decode {Path(src).name} failed (exit {code}): "
                               f"{err.decode('utf-8', 'replace').strip()[-300:]}")


def camera_path(src: str, W: int, H: int, rate: float | None = None) -> "Any":
    """Frame-to-frame similarity motion (dx, dy in px of W x H, angle in rad) from a 320-wide grey copy."""
    import cv2
    import numpy as np
    sw = 320
    sh = max(2, int(round(H * sw / W / 2)) * 2)
    k = W / sw
    motions = [(0.0, 0.0, 0.0)]
    prev = None
    for g in _read_frames(src, sw, sh, rate, gray=True):
        if prev is not None:
            dx = dy = da = 0.0
            pts = cv2.goodFeaturesToTrack(prev, maxCorners=300, qualityLevel=0.01, minDistance=7, blockSize=7)
            if pts is not None and len(pts) >= 8:
                nxt, status, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None, winSize=(31, 31), maxLevel=4)
                good = status.ravel() == 1
                if int(good.sum()) >= 8:
                    m, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC,
                                                       ransacReprojThreshold=2.0, maxIters=2000, confidence=0.99)
                    if m is not None:
                        dx, dy = float(m[0, 2]) * k, float(m[1, 2]) * k
                        da = math.atan2(float(m[1, 0]), float(m[0, 0]))
            motions.append((dx, dy, da))
        prev = g
    return np.array(motions, dtype=np.float64)


def max_jump(path: str) -> float:
    """Largest frame-to-frame camera shift of a clip, as a fraction of its width."""
    import numpy as np
    info = nc.media_info(path)
    W, H = int(info["width"]) // 2 * 2, int(info["height"]) // 2 * 2
    m = camera_path(path, W, H)
    return float(np.hypot(m[1:, 0], m[1:, 1]).max()) / W if len(m) > 1 else 0.0


def smooth_corrections(motions, fps: float, W: int, H: int):
    """Per-frame corrections (tx, ty, angle) that move the camera path onto a Gaussian-smoothed copy, plus the zoom."""
    import numpy as np
    traj = np.cumsum(motions, axis=0)
    r = max(1, int(round(SMOOTH_RADIUS_S * (fps or 30.0))))
    x = np.arange(-r, r + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / (r / 2.0)) ** 2)
    kernel /= kernel.sum()
    smooth = np.stack([np.convolve(np.pad(traj[:, i], (r, r), mode="edge"), kernel, mode="valid")
                       for i in range(3)], axis=1)
    corr = smooth - traj
    corr[:, 0] = np.clip(corr[:, 0], -MAX_CORRECTION * W, MAX_CORRECTION * W)
    corr[:, 1] = np.clip(corr[:, 1], -MAX_CORRECTION * H, MAX_CORRECTION * H)
    corr[:, 2] = np.clip(corr[:, 2], -MAX_ANGLE, MAX_ANGLE)
    # zoom about the centre so the shifted, rotated frame still covers the output
    zoom = 1.0
    for tx, ty, a in corr:
        c, s = abs(math.cos(a)), abs(math.sin(a))
        need_w = (W * c + H * s + 2 * abs(tx)) / W
        need_h = (W * s + H * c + 2 * abs(ty)) / H
        zoom = max(zoom, need_w, need_h)
    return corr, round(zoom + 0.004, 4)


def stabilize_opencv(src: str, info: dict, dst: Path, gamma: float, scratch: Path) -> None:
    """Feature-tracked stabilization at the output size, at a constant frame rate (the source's average)."""
    import cv2
    W2, H2 = out_size(info)
    fps = float(info.get("fps") or 30.0)
    motions = camera_path(src, W2, H2, fps)
    corr, zoom = smooth_corrections(motions, fps, W2, H2)
    tmp = scratch / "opencv.mp4"
    cmd = [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W2}x{H2}", "-framerate", f"{fps:.6f}", "-i", "-",
           "-i", src, "-map", "0:v:0", *audio_args(info, 1)]
    # the piped RGB frames carry no colour tags: convert them to limited-range BT.709 YUV
    # explicitly and tag the stream so players and the renderer read the range right
    vf = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    if gamma > 1.0:
        vf += "," + brighten_filter(gamma, full=False)
    vf += "," + OPENCV_COLOR_FRAMES
    cmd += ["-vf", vf, *OPENCV_COLOR_TAGS, "-fps_mode", "cfr", *_encode_out(tmp)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    cx, cy = W2 / 2.0, H2 / 2.0
    try:
        for i, frame in enumerate(_read_frames(src, W2, H2, fps)):
            tx, ty, a = corr[min(i, len(corr) - 1)]
            m = cv2.getRotationMatrix2D((cx, cy), math.degrees(a), zoom)
            m[0, 2] += tx * zoom
            m[1, 2] += ty * zoom
            out = cv2.warpAffine(frame, m, (W2, H2), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            enc.stdin.write(out.tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            enc.stdin.close()
        except BrokenPipeError:
            pass
        err = enc.stderr.read()
        enc.stderr.close()
        code = enc.wait()
    if code != 0:
        raise nc.UserError(f"ffmpeg encode failed (exit {code}): {err.decode('utf-8', 'replace').strip()[-300:]}")
    shutil.move(str(tmp), str(dst))


def brighten_clip(src: str, info: dict, dst: Path, gamma: float, scratch: Path) -> None:
    w, h = out_size(info)
    tmp = scratch / "bright.mp4"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src,
            "-map", "0:v:0", *audio_args(info, 0),
            "-vf", f"{_scale(w, h)},{brighten_filter(gamma, full_range(info))}",
            "-fps_mode", "passthrough", *_encode_out(tmp)], what="ffmpeg brighten")
    shutil.move(str(tmp), str(dst))


def prepare_clip(entry: dict, stabilize: bool, brighten: bool, dst: Path, method: str | None = None) -> dict:
    """Write the prepared clip to dst; returns details for the report.

    vid.stab can lose track on a very large jump (it then leaves a jolt in the output); when its
    result still has a frame-to-frame jump above JUMP_LIMIT of the width, the OpenCV stabilizer
    runs too and the result with the smaller largest jump is kept."""
    src = str(Path(entry["path"]).resolve())
    info = nc.media_info(src)
    duration = float(info.get("duration") or entry.get("duration") or 0.0)
    details: dict[str, Any] = {"size": list(out_size(info))}
    gamma = 1.0
    if brighten:
        gamma = gamma_for(clip_luma(src, info, duration))
        details["gamma"] = gamma
    with tempfile.TemporaryDirectory(prefix="numa_prep_") as td:
        scratch = Path(td)
        part = scratch / "result.mp4"
        if stabilize:
            how = method or ("vidstab" if has_vidstab() else "opencv")
            if how == "vidstab":
                post = brighten_filter(gamma, full_range(info)) if gamma > 1.0 else None
                stabilize_vidstab(src, info, part, post, scratch)
                jump = max_jump(str(part))
                if method is None and jump > JUMP_LIMIT:
                    alt = scratch / "alt.mp4"
                    stabilize_opencv(src, info, alt, gamma, scratch)
                    alt_jump = max_jump(str(alt))
                    if alt_jump < jump:
                        how, jump = "opencv", alt_jump
                        shutil.move(str(alt), str(part))
            else:
                stabilize_opencv(src, info, part, gamma, scratch)
                jump = max_jump(str(part))
            details["method"] = how
            details["max_jump"] = round(jump, 4)
        else:
            brighten_clip(src, info, part, gamma, scratch)
        shutil.move(str(part), str(dst.with_name(f".{dst.name}.tmp")))
    os.replace(dst.with_name(f".{dst.name}.tmp"), dst)
    return details


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
OPS = ("stabilize", "brighten")


def decide(entry: dict, kind: str, stabilize: str, brighten: str, forced: Sequence[str] = ()) -> list[str]:
    """Steps for one item. `on` forces a step, `off` drops it; with `auto` a step runs when the item is
    flagged for it or when an earlier run forced it (recorded in prep/index.json)."""
    modes = {"stabilize": stabilize, "brighten": brighten}
    auto = {"stabilize": kind == "clip" and vision.needs_stabilize(entry), "brighten": vision.needs_brighten(entry)}
    ops = []
    for op in OPS:
        if op == "stabilize" and kind != "clip":
            continue
        mode = modes[op]
        if mode == "on" or (mode == "auto" and (auto[op] or op in forced)):
            ops.append(op)
    return ops


def parse_ids(text: str | None, known: set[str]) -> list[str] | None:
    if text is None:
        return None
    ids = [t.strip().upper() for t in text.split(",") if t.strip()]
    if not ids:
        raise nc.UsageError("--ids needs at least one id, e.g. --ids C0,P3")
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise nc.UserError(f"--ids: not in analysis.json: {', '.join(unknown)}")
    return ids


def run_prep(analysis_path: Path, *, ids: str | None = None, stabilize: str = "auto", brighten: str = "auto",
             method: str | None = None) -> dict:
    """Prepare the selected items and amend analysis.json; returns the report.

    After an item is prepared its `faces`/`focus` (and clip seconds' face counts) are detected again
    on the prepared copy, which is the shot source; the original file's stay in `orig_faces`/`orig_focus`.
    `method` forces the stabilizer ("vidstab" or "opencv"); None picks vidstab when available."""
    analysis_path = Path(analysis_path)
    A = nc.read_json(analysis_path, "analysis.json")
    if not isinstance(A, dict):
        raise nc.UserError(f"{analysis_path}: not a JSON object")
    errs = nc.schema_errors("analysis", A)
    if errs:
        raise nc.UserError(f"{analysis_path}: not a valid analysis.json ({errs[0]}); re-run analyze.py")
    items = [("photo", p) for p in A.get("photos", [])] + [("clip", c) for c in A.get("clips", [])]
    chosen = parse_ids(ids, {e["id"] for _, e in items})
    prep_dir = analysis_path.parent / "prep"
    index_path = prep_dir / "index.json"
    index = nc.read_json(index_path, "prep index") if index_path.is_file() else {}
    if not isinstance(index, dict):
        index = {}
    modes = {"stabilize": stabilize, "brighten": brighten}
    det = None

    def detector():
        nonlocal det
        if det is None:
            import cv2
            cv2.setNumThreads(1)
            det = vision.FaceDetector()
        return det

    report: dict[str, Any] = {"analysis": str(analysis_path), "items": []}
    for kind, e in items:
        if chosen is not None and e["id"] not in chosen:
            continue
        rec = index.get(e["id"]) or {}
        forced_before = [op for op in rec.get("forced") or [] if modes.get(op) == "auto"]
        ops = decide(e, kind, stabilize, brighten, forced_before)
        forced = [op for op in ops if modes[op] == "on" or op in forced_before]
        row: dict[str, Any] = {"id": e["id"], "ops": ops}
        if not ops:
            if e.pop("prepared_path", None):
                row["status"] = "removed"
                vision.drop_prepared(e, kind, detector())
            else:
                row["status"] = "not needed"
            index.pop(e["id"], None)
            report["items"].append(row)
            continue
        src = Path(e["path"])
        if not src.is_file():
            raise nc.UserError(f"{e['id']}: source not found: {src}")
        dst = prep_dir / f"{e['id']}{'.mp4' if kind == 'clip' else '.jpg'}"
        src_hash = sha256_file(src)
        wanted = {"version": PREP_VERSION, "src": str(src), "sha256": src_hash, "ops": ops,
                  "method": method if "stabilize" in ops else None}
        if (all(rec.get(k) == v for k, v in wanted.items()) and dst.is_file()
                and rec.get("out_sha256") == sha256_file(dst)):
            status, details = "unchanged", rec.get("details") or {}
        else:
            prep_dir.mkdir(parents=True, exist_ok=True)
            nc.info(f"{e['id']}: {' + '.join(ops)} {src.name}")
            if kind == "clip":
                details = prepare_clip(e, "stabilize" in ops, "brighten" in ops, dst, method)
            else:
                details = brighten_photo(str(src), dst)
            status = "prepared"
        e["prepared_path"] = str(dst)
        vision.use_prepared(e, kind, detector())
        index[e["id"]] = {**wanted, "forced": forced, "out": str(dst), "out_sha256": sha256_file(dst),
                          "details": details}
        row.update(status=status, prepared_path=str(dst), faces=len(e["faces"]), **details)
        report["items"].append(row)
    nc.validate_against("analysis", A, "analysis.json")
    if index or index_path.is_file():
        nc.write_json(index_path, dict(sorted(index.items())))
    nc.write_json(analysis_path, A)
    return report


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="prep_media.py", description="Stabilize shaky clips and brighten dark clips/photos; "
                                                        "sets prepared_path in analysis.json.")
    ap.add_argument("analysis", metavar="ANALYSIS_JSON", help="the job's work/analysis.json (edited in place)")
    ap.add_argument("--ids", metavar="C0,P3,...", help="only these photos/clips (default: all)")
    ap.add_argument("--stabilize", choices=("auto", "on", "off"), default="auto",
                    help="stabilize clips: auto = shaky clips only (default)")
    ap.add_argument("--brighten", choices=("auto", "on", "off"), default="auto",
                    help="brighten photos and clips: auto = dark ones only (default)")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    report = run_prep(Path(args.analysis).expanduser().resolve(), ids=args.ids, stabilize=args.stabilize,
                      brighten=args.brighten)
    if args.json:
        nc.print_json(report)
        return 0
    print(f"analysis: {report['analysis']}")
    if not report["items"]:
        print("nothing selected")
    for row in report["items"]:
        what = " + ".join(row["ops"]) or "nothing to do"
        extra = f" -> {row['prepared_path']}" if row.get("prepared_path") else ""
        print(f"{row['id']}: {what} ({row['status']}){extra}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
