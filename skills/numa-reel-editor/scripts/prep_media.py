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

Writes WORK/prep/<id>.mp4 (H.264 High, yuv420p, source frame rate, the clip's
audio kept) or WORK/prep/<id>.jpg and sets the item's `prepared_path`, which
the Editor and baseline_plan.py use as the shot `src`. WORK/prep/index.json
records each source's SHA-256 and the steps applied, so an unchanged source is
not processed again. An item whose steps all turn out off loses its
`prepared_path`. Outputs are deterministic (fixed encoder threads, bit-exact
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

PREP_VERSION = 1
TARGET_LUMA = 0.40            # brighten to about this mean luma (0-1)
MAX_GAMMA = 2.2               # strongest lift (out = in ** (1 / gamma))
CHROMA_BOOST = 1.06           # saturation lift that goes with a brighten
SMOOTH_RADIUS_S = 0.5         # OpenCV fallback: camera path moving-average radius (s)
MAX_CORRECTION = 0.06         # OpenCV fallback: largest shift correction (fraction of the frame)
MAX_ANGLE = math.radians(2.0)  # OpenCV fallback: largest rotation correction
X264 = ["-c:v", "libx264", "-preset", "fast", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-threads", "4", "-x264-params", "threads=4:lookahead_threads=1"]
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


def full_range(info: dict) -> bool:
    return str(info.get("pix_fmt") or "").startswith("yuvj")


def brighten_filter(gamma: float, full: bool) -> str:
    """lutyuv: gamma on luma in the clip's own range (white stays white), chroma boosted around neutral."""
    if full:
        y = f"clip(255*pow(val/255\\,{1 / gamma:.6f})\\,0\\,255)"
    else:
        y = f"clip(16+219*pow(clip((val-16)/219\\,0\\,1)\\,{1 / gamma:.6f})\\,16\\,235)"
    uv = f"clip(128+(val-128)*{CHROMA_BOOST:g}\\,0\\,255)"
    return f"lutyuv=y='{y}':u='{uv}':v='{uv}'"


def clip_luma(path: str, info: dict, duration: float):
    """Luma samples (0-1 in the clip's range) from frames at 2 fps, 320 px wide."""
    import numpy as np
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-an", "-sn",
                   "-t", f"{duration:.3f}", "-vf", "fps=2,scale=320:-2,format=gray", "-f", "rawvideo", "-"],
                  what=f"ffmpeg luma {Path(path).name}")
    y = np.frombuffer(proc.stdout, dtype=np.uint8).astype(np.float64)
    return y / 255.0 if full_range(info) else np.clip((y - 16.0) / 219.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
def brighten_photo(src: str, dst: Path) -> dict:
    import cv2
    import numpy as np
    from PIL import Image
    bgr = vision.read_image(src)
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    y = ycc[:, :, 0]
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


def stabilize_vidstab(src: str, info: dict, dst: Path, post: str | None, scratch: Path) -> None:
    """Two-pass vid.stab; optzoom=1 picks the static zoom that hides every border."""
    trf = "transforms.trf"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src, "-an", "-sn",
            "-vf", f"vidstabdetect=shakiness=8:accuracy=15:stepsize=6:result={trf}", "-f", "null", "-"],
           cwd=scratch, what="ffmpeg vidstabdetect")
    chain = f"vidstabtransform=input={trf}:smoothing=15:optzoom=1:zoomspeed=0:interpol=bicubic:crop=black"
    chain += ",unsharp=5:5:0.5:3:3:0"
    if post:
        chain += "," + post
    tmp = scratch / "out.mp4"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src,
            "-map", "0:v:0", *audio_args(info, 0), "-vf", chain, "-fps_mode", "passthrough", *_encode_out(tmp)],
           cwd=scratch, what="ffmpeg vidstabtransform")
    shutil.move(str(tmp), str(dst))


def _read_frames(src: str, w: int, h: int, extra_vf: str = ""):
    """Yield BGR frames (h x w x 3) of the clip in display orientation, one at a time."""
    import numpy as np
    vf = f"scale={w}:{h}:flags=area{',' + extra_vf if extra_vf else ''},format=bgr24"
    proc = subprocess.Popen([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", src, "-an", "-sn",
                             "-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
        code = proc.wait()
        if code != 0:
            raise nc.UserError(f"ffmpeg decode {Path(src).name} failed (exit {code}): "
                               f"{err.decode('utf-8', 'replace').strip()[-300:]}")


def camera_path(src: str, W: int, H: int) -> "Any":
    """Frame-to-frame similarity motion (dx, dy in px of W x H, angle in rad) from a 320-wide grey copy."""
    import cv2
    import numpy as np
    sw = 320
    sh = max(2, int(round(H * sw / W / 2)) * 2)
    k = W / sw
    motions = [(0.0, 0.0, 0.0)]
    prev = None
    for frame in _read_frames(src, sw, sh, "format=gray"):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            dx = dy = da = 0.0
            pts = cv2.goodFeaturesToTrack(prev, maxCorners=300, qualityLevel=0.01, minDistance=7, blockSize=7)
            if pts is not None and len(pts) >= 8:
                nxt, status, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None, winSize=(21, 21), maxLevel=3)
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


def smooth_corrections(motions, fps: float, W: int, H: int):
    """Per-frame corrections (tx, ty, angle) that move the camera path onto its moving average, plus the zoom."""
    import numpy as np
    traj = np.cumsum(motions, axis=0)
    r = max(1, int(round(SMOOTH_RADIUS_S * (fps or 30.0))))
    kernel = np.ones(2 * r + 1) / (2 * r + 1)
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


def stabilize_opencv(src: str, info: dict, dst: Path, post: str | None, scratch: Path) -> None:
    import cv2
    W, H = int(info["width"]), int(info["height"])
    W2, H2 = W - W % 2, H - H % 2
    fps = float(info.get("fps") or 30.0)
    motions = camera_path(src, W2, H2)
    corr, zoom = smooth_corrections(motions, fps, W2, H2)
    tmp = scratch / "out.mp4"
    cmd = [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W2}x{H2}", "-framerate", f"{fps:.6f}", "-i", "-",
           "-i", src, "-map", "0:v:0", *audio_args(info, 1)]
    if post:
        cmd += ["-vf", post]
    cmd += _encode_out(tmp)
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    cx, cy = W2 / 2.0, H2 / 2.0
    try:
        for i, frame in enumerate(_read_frames(src, W2, H2)):
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
    tmp = scratch / "out.mp4"
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", src,
            "-map", "0:v:0", *audio_args(info, 0), "-vf", brighten_filter(gamma, full_range(info)),
            "-fps_mode", "passthrough", *_encode_out(tmp)], what="ffmpeg brighten")
    shutil.move(str(tmp), str(dst))


def prepare_clip(entry: dict, stabilize: bool, brighten: bool, dst: Path, method: str | None = None) -> dict:
    """Write the prepared clip to dst; returns details for the report."""
    src = entry["path"]
    info = nc.media_info(src)
    duration = float(info.get("duration") or entry.get("duration") or 0.0)
    details: dict[str, Any] = {}
    post = None
    if brighten:
        luma = clip_luma(src, info, duration)
        gamma = gamma_for(luma)
        details["gamma"] = gamma
        if gamma > 1.0:
            post = brighten_filter(gamma, full_range(info))
    with tempfile.TemporaryDirectory(prefix="numa_prep_") as td:
        scratch = Path(td)
        part = scratch / "result.mp4"
        if stabilize:
            how = method or ("vidstab" if has_vidstab() else "opencv")
            details["method"] = how
            if how == "vidstab":
                stabilize_vidstab(src, info, part, post, scratch)
            else:
                stabilize_opencv(src, info, part, post, scratch)
        else:
            brighten_clip(src, info, part, details.get("gamma", 1.0), scratch)
        shutil.move(str(part), str(dst.with_name(f".{dst.name}.tmp")))
    os.replace(dst.with_name(f".{dst.name}.tmp"), dst)
    return details


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def decide(entry: dict, kind: str, stabilize: str, brighten: str) -> list[str]:
    ops = []
    if kind == "clip" and (stabilize == "on" or (stabilize == "auto" and vision.needs_stabilize(entry))):
        ops.append("stabilize")
    if brighten == "on" or (brighten == "auto" and vision.needs_brighten(entry)):
        ops.append("brighten")
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
    report: dict[str, Any] = {"analysis": str(analysis_path), "items": []}
    for kind, e in items:
        if chosen is not None and e["id"] not in chosen:
            continue
        ops = decide(e, kind, stabilize, brighten)
        row: dict[str, Any] = {"id": e["id"], "ops": ops}
        if not ops:
            if e.pop("prepared_path", None):
                row["status"] = "removed"
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
        rec = index.get(e["id"]) or {}
        wanted = {"version": PREP_VERSION, "src": str(src), "sha256": src_hash, "ops": ops,
                  "method": method if "stabilize" in ops else None}
        if (all(rec.get(k) == v for k, v in wanted.items()) and dst.is_file()
                and rec.get("out_sha256") == sha256_file(dst)):
            e["prepared_path"] = str(dst)
            row.update(status="unchanged", prepared_path=str(dst), **(rec.get("details") or {}))
            report["items"].append(row)
            continue
        prep_dir.mkdir(parents=True, exist_ok=True)
        nc.info(f"{e['id']}: {' + '.join(ops)} {src.name}")
        if kind == "clip":
            details = prepare_clip(e, "stabilize" in ops, "brighten" in ops, dst, method)
        else:
            details = brighten_photo(str(src), dst)
        e["prepared_path"] = str(dst)
        index[e["id"]] = {**wanted, "out": str(dst), "out_sha256": sha256_file(dst), "details": details}
        row.update(status="prepared", prepared_path=str(dst), **details)
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
