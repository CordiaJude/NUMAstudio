#!/usr/bin/env python3
"""Check a finished video against NUMA's output spec (spec p.48, config `render`).

    check_output.py FILE.mp4 [--kind reel|reach|story|hook] [--size WxH] [--plan PLAN_JSON]
                    [--report OUT_DIR] [--json]

Checks: MP4 container, H.264 High, frame size, 30 fps, yuv420p, video bitrate
<= about 14 Mbps, AAC ~192 kbps 48 kHz stereo, moov before mdat (+faststart),
under 100 MB, length for the kind (reel 15-60 s, reach 8-12 s, story/hook
<= 15 s), loudness -15 +/- 1 LUFS, true peak <= -1.5 dB, audio not silent and
not clipped, no black bars, no frozen frames (the end-card hold is exempt when
--plan names it). One ERROR line per violation and exit 1; mean level below
-28 dB is a WARN. --report merges the result into OUT_DIR/report.json
(`check_output` section, keyed by file name). Works without ffprobe.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

KINDS = ("reel", "reach", "story", "hook")
FALLBACK_LENGTHS = {"reel": (15.0, 60.0), "reach": (8.0, 12.0), "story": (0.0, 15.0), "hook": (0.0, 15.0)}
LENGTH_TOLERANCE_S = 0.05
VIDEO_BITRATE_TOLERANCE = 1.05      # "about 14 Mbps max"
AUDIO_BITRATE_RANGE = (0.8, 1.2)    # AAC 192k is average bitrate; outside +/- 20 % is a WARN
SILENT_LUFS = -60.0                 # integrated loudness below this (or -inf) = silent
SILENT_MAX_DB = -50.0               # or no sample louder than this
CLIP_SAMPLE_DB = -0.1               # a sample at full scale = clipped
FREEZE_MIN_S = 1.0
FREEZE_NOISE = "-60dB"
BAR_FRACTION = 0.02                 # a border band wider than 2 % of the frame can be a bar
BAR_LUMA = 40.0                     # dark: graded "black" bars sit up to about luma 40 (0-255)
BAR_STD = 6.0                       # flat: grain allowed, picture detail not
BAR_DRIFT = 4.0                     # uniform: every row of the band within this of the band's level
BAR_EDGE = 15.0                     # sharp: the rows just inside differ by at least this (mean shift + std)
BAR_INTERIOR = 20.0                 # the picture inside is clearly brighter or busier than the band
BAR_PAIR_LUMA = 10.0                # both bars of a pair have about the same level
BAR_SIZE_MATCH = 0.02               # a bar keeps its size (fraction) across the frames it is seen on
ANALYSIS_SIZE = (270, 480)          # frames are downscaled for bar detection


# --------------------------------------------------------------------------- measurement helpers
def _num(text: str | None) -> float | None:
    if text is None:
        return None
    t = text.strip().lower()
    if t in ("-inf", "-infinity"):
        return -math.inf
    if t in ("inf", "+inf"):
        return math.inf
    try:
        return float(t)
    except ValueError:
        return None


def measure_audio(path: str | Path) -> dict[str, Any]:
    """Integrated loudness, true peak, LRA (ffmpeg ebur128) plus mean/max sample level (volumedetect).

    Returns {"integrated_lufs", "true_peak_db", "lra", "mean_db", "max_db"}; silent audio gives
    -inf values (callers must handle them; they are not JSON-safe)."""
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-map", "0:a:0",
                   "-af", "ebur128=peak=true:framelog=quiet,volumedetect", "-f", "null", "-"],
                  what="ffmpeg loudness measurement")
    text = proc.stderr.decode("utf-8", "replace")
    summary = text[text.rfind("Summary:"):] if "Summary:" in text else ""
    if not summary:
        raise nc.UserError(f"could not measure the loudness of {path}")

    def grab(pattern: str, src: str) -> float | None:
        m = re.findall(pattern, src)
        return _num(m[-1]) if m else None

    return {
        "integrated_lufs": grab(r"I:\s*(-?inf|-?[\d.]+)\s*LUFS", summary),
        "true_peak_db": grab(r"Peak:\s*(-?inf|-?[\d.]+)\s*dBFS", summary),
        "lra": grab(r"LRA:\s*(-?inf|-?[\d.]+)\s*LU\b", summary),
        "mean_db": grab(r"mean_volume:\s*(-?inf|-?[\d.]+)\s*dB", text),
        "max_db": grab(r"max_volume:\s*(-?inf|-?[\d.]+)\s*dB", text),
    }


def json_safe(values: dict[str, Any]) -> dict[str, Any]:
    """Replace +/-inf/NaN by None and round floats to 0.01 for reports."""
    out = {}
    for k, v in values.items():
        if isinstance(v, float):
            out[k] = round(v, 2) if math.isfinite(v) else None
        else:
            out[k] = v
    return out


def mp4_top_boxes(path: str | Path) -> list[str]:
    """Top-level MP4 box types in file order (ftyp, moov, mdat, ...)."""
    boxes: list[str] = []
    p = Path(path)
    size_total = p.stat().st_size
    with p.open("rb") as f:
        pos = 0
        while pos + 8 <= size_total and len(boxes) < 64:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                break
            size = int.from_bytes(head[:4], "big")
            kind = head[4:8].decode("latin-1")
            if size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                size = int.from_bytes(ext, "big")
            elif size == 0:
                size = size_total - pos
            if size < 8 or not re.fullmatch(r"[\x20-\x7e]{4}", kind):
                break
            boxes.append(kind)
            pos += size
    return boxes


def detect_freezes(path: str | Path, min_s: float = FREEZE_MIN_S) -> list[tuple[float, float]]:
    """[(start, end)] of stretches with no picture change for >= min_s (ffmpeg freezedetect)."""
    w, h = ANALYSIS_SIZE
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:v:0", "-an",
                   "-vf", f"scale={w}:{h},freezedetect=n={FREEZE_NOISE}:d={min_s}", "-f", "null", "-"],
                  what="ffmpeg freeze detection")
    text = proc.stderr.decode("utf-8", "replace")
    out: list[tuple[float, float]] = []
    start: float | None = None
    for m in re.finditer(r"lavfi\.freezedetect\.freeze_(start|end):\s*(-?[\d.]+)", text):
        kind, val = m.group(1), float(m.group(2))
        if kind == "start":
            start = val
        elif start is not None:
            out.append((start, val))
            start = None
    if start is not None:  # frozen through the end of the file
        out.append((start, float("inf")))
    return out


def _gray_frames(path: str | Path, times: list[float]):
    import numpy as np
    w, h = ANALYSIS_SIZE
    frames = []
    for t in times:
        proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{t:.3f}",
                       "-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-vf", f"scale={w}:{h},format=gray",
                       "-f", "rawvideo", "-"], what="ffmpeg frame grab", check=False)
        if proc.returncode == 0 and len(proc.stdout) == w * h:
            frames.append((t, np.frombuffer(proc.stdout, dtype=np.uint8).reshape(h, w).astype(np.float32)))
    return frames


def _band(lines) -> tuple[float, float]:
    """(fraction, level) of a bar along one edge of a 2-D array whose first row is the edge; (0, 0) when none.

    A bar is a run of rows that are dark (mean <= BAR_LUMA), flat (std <= BAR_STD) and uniform
    (all within BAR_DRIFT of each other), ending in a sharp edge, with a picture beyond it that is
    clearly brighter or busier than the band."""
    total = lines.shape[0]
    means = lines.mean(axis=1)
    stds = lines.std(axis=1)
    if means[0] > BAR_LUMA or stds[0] > BAR_STD:
        return 0.0, 0.0
    level = float(means[0])
    n = 0
    while n < total and means[n] <= BAR_LUMA and stds[n] <= BAR_STD and abs(means[n] - level) <= BAR_DRIFT:
        n += 1
    if n == 0 or n >= total - 2:
        return 0.0, 0.0
    level = float(means[:n].mean())
    flat = float(stds[:n].mean())
    edge = max(abs(float(means[k]) - level) + float(stds[k]) for k in range(n, min(n + 3, total)))
    inner = lines[n:min(total, n + max(8, n))]
    interior = max(float(inner.mean()) - level, float(inner.std()) - flat)
    if edge < BAR_EDGE or interior < BAR_INTERIOR:
        return 0.0, 0.0
    return n / total, level


def bar_sizes(frame) -> dict[str, tuple[float, float]]:
    """{side: (fraction, level)} for top/bottom (fraction of height) and left/right (of width)."""
    return {
        "top": _band(frame),
        "bottom": _band(frame[::-1]),
        "left": _band(frame.T),
        "right": _band(frame.T[::-1]),
    }


def _pair(sizes: dict, a: str, b: str) -> tuple[float, float] | None:
    (fa, la), (fb, lb) = sizes[a], sizes[b]
    if fa > BAR_FRACTION and fb > BAR_FRACTION and abs(la - lb) <= BAR_PAIR_LUMA:
        return fa, fb
    return None


def detect_black_bars(path: str | Path, duration: float,
                      exempt: list[tuple[float, float]] | None = None) -> list[str]:
    """Descriptions of letterbox/pillarbox bars on frames sampled once a second (skipping fades and exempt windows).

    Bars come in matching pairs (top+bottom or left+right, same level) and must be stable: the same
    size on at least two sampled frames (or on the only frame sampled). A dark sky or a dark top
    region alone is a picture, not a bar."""
    exempt = exempt or []
    end = duration - 1.0  # the global fade-out
    times = []
    t = 0.5
    while t < end:
        if not any(a <= t <= b for a, b in exempt):
            times.append(round(t, 3))
        t += 1.0
    if not times and duration > 0.4:
        times = [round(duration / 2, 3)]
    frames = _gray_frames(path, times)
    hits: dict[str, list[tuple[float, float, float]]] = {"letterbox": [], "pillarbox": []}
    for t, frame in frames:
        sizes = bar_sizes(frame)
        lb = _pair(sizes, "top", "bottom")
        if lb:
            hits["letterbox"].append((t, *lb))
        pb = _pair(sizes, "left", "right")
        if pb:
            hits["pillarbox"].append((t, *pb))
    found: list[str] = []
    for kind, seen in hits.items():
        if not seen:
            continue
        # stable: group frames whose bar sizes match, keep groups seen at least twice
        groups: list[list[tuple[float, float, float]]] = []
        for h in seen:
            for g in groups:
                if abs(g[0][1] - h[1]) <= BAR_SIZE_MATCH and abs(g[0][2] - h[2]) <= BAR_SIZE_MATCH:
                    g.append(h)
                    break
            else:
                groups.append([h])
        need = 1 if len(frames) == 1 else 2
        for g in groups:
            if len(g) < need:
                continue
            a, b = max(h[1] for h in g), max(h[2] for h in g)
            sides = ("top", "bottom", "height") if kind == "letterbox" else ("left", "right", "width")
            found.append(f"black bars ({kind}, {sides[0]} {a:.0%} and {sides[1]} {b:.0%} of the {sides[2]}) "
                         f"at {_times(h[0] for h in g)}")
    return found


def _times(ts) -> str:
    ts = list(ts)
    shown = ", ".join(f"{x:.1f}" for x in ts[:5])
    return f"{shown}{' ...' if len(ts) > 5 else ''} s"


# --------------------------------------------------------------------------- plan helpers
def endcard_window(plan_path: str | Path | None, duration: float) -> list[tuple[float, float]]:
    """[(endcard.t, duration)] from the plan, or [] without a plan / end card."""
    if not plan_path:
        return []
    plan = nc.read_json(plan_path, "plan")
    if not isinstance(plan, dict):
        raise nc.UserError(f"plan {plan_path} is not a JSON object")
    ec = plan.get("endcard")
    if isinstance(ec, dict) and isinstance(ec.get("t"), (int, float)):
        return [(float(ec["t"]), max(duration, float(plan.get("duration") or 0)) + 1.0)]
    return []


def _overlap_outside(a: float, b: float, exempt: list[tuple[float, float]]) -> float:
    """Length of [a, b] not covered by the exempt windows."""
    length = b - a
    for x, y in exempt:
        lo, hi = max(a, x), min(b, y)
        if hi > lo:
            length -= hi - lo
    return length


# --------------------------------------------------------------------------- the check
def kind_lengths(kind: str) -> tuple[float, float]:
    cfg = nc.load_config()
    if kind == "reel":
        rng = nc.dig(cfg, "render.length_s.main_reel")
    elif kind == "reach":
        rng = nc.dig(cfg, "render.length_s.reach_cut")
    else:
        rng = None
    if isinstance(rng, list) and len(rng) == 2:
        return float(rng[0]), float(rng[1])
    return FALLBACK_LENGTHS[kind]


def check_file(path: str | Path, kind: str = "reel", size: tuple[int, int] | None = None,
               plan: str | Path | None = None) -> dict[str, Any]:
    """Run every check; returns {"ok", "errors", "warnings", "probe", "loudness"}."""
    p = Path(path)
    if not p.is_file():
        raise nc.UserError(f"video not found: {p}")
    cfg = nc.load_config()
    video_cfg = nc.dig(cfg, "render.video", {}) or {}
    audio_cfg = nc.dig(cfg, "render.audio", {}) or {}
    loud_cfg = nc.dig(cfg, "render.loudness", {}) or {}
    want_size = tuple(size) if size else tuple(nc.dig(cfg, "render.size", [1080, 1920]))
    want_fps = float(nc.dig(cfg, "render.fps", 30))
    errors: list[str] = []
    warnings: list[str] = []

    info = nc.media_info(p)
    dur = info["duration"] or 0.0
    size_mb = p.stat().st_size / 1e6
    boxes = mp4_top_boxes(p)

    # container
    if p.suffix.lower() != ".mp4" or "mp4" not in str(info.get("format_name") or "") or (boxes[:1] != ["ftyp"]):
        errors.append(f"container: expected an MP4 file, got {info.get('format_name') or 'unknown'} ({p.suffix or 'no extension'})")
    if "moov" not in boxes or "mdat" not in boxes:
        errors.append(f"container: MP4 boxes missing (found {', '.join(boxes) or 'none'})")
    elif video_cfg.get("faststart", True) and boxes.index("moov") > boxes.index("mdat"):
        errors.append("faststart: moov atom is after mdat (mux with -movflags +faststart)")
    max_mb = float(video_cfg.get("max_file_mb", 100))
    if size_mb >= max_mb:
        errors.append(f"file size: {size_mb:.1f} MB, must be under {max_mb:g} MB")

    # video stream
    if not info["has_video"]:
        errors.append("video: no video stream")
    else:
        if info["vcodec"] != "h264":
            errors.append(f"video codec: {info['vcodec']}, expected h264")
        want_profile = str(video_cfg.get("profile", "high")).lower()
        if str(info.get("profile") or "").lower() != want_profile:
            errors.append(f"video profile: {info.get('profile') or 'unknown'}, expected H.264 {want_profile.title()}")
        if (info["width"], info["height"]) != want_size:
            errors.append(f"video size: {info['width']}x{info['height']}, expected {want_size[0]}x{want_size[1]}")
        if info["fps"] is None or abs(info["fps"] - want_fps) > 0.01:
            errors.append(f"frame rate: {info['fps'] if info['fps'] is None else round(info['fps'], 3)} fps, expected {want_fps:g}")
        want_pix = video_cfg.get("pix_fmt", "yuv420p")
        if info["pix_fmt"] != want_pix:
            errors.append(f"pixel format: {info['pix_fmt']}, expected {want_pix}")
        vbr = _video_bitrate(p, info, dur)
        max_rate = _rate_value(video_cfg.get("maxrate", "14M"))
        if vbr is not None and vbr > max_rate * VIDEO_BITRATE_TOLERANCE:
            errors.append(f"video bitrate: {vbr / 1e6:.1f} Mbps, max about {max_rate / 1e6:g} Mbps")

    # length
    lo, hi = kind_lengths(kind)
    if dur < lo - LENGTH_TOLERANCE_S or dur > hi + LENGTH_TOLERANCE_S:
        errors.append(f"length: {dur:.2f} s, a {kind} must be {lo:g}-{hi:g} s" if lo > 0
                      else f"length: {dur:.2f} s, a {kind} must be at most {hi:g} s")

    # audio stream
    loud: dict[str, Any] = {}
    if not info["has_audio"]:
        errors.append("audio: no audio stream")
    else:
        if info["acodec"] != audio_cfg.get("codec", "aac"):
            errors.append(f"audio codec: {info['acodec']}, expected {audio_cfg.get('codec', 'aac')}")
        want_sr = int(audio_cfg.get("sample_rate", 48000))
        if info["sample_rate"] != want_sr:
            errors.append(f"audio sample rate: {info['sample_rate']} Hz, expected {want_sr} Hz")
        want_ch = int(audio_cfg.get("channels", 2))
        if info["channels"] != want_ch:
            errors.append(f"audio channels: {info['channels']}, expected {want_ch} (stereo)")
        abr = _audio_bitrate(p)
        want_abr = _rate_value(audio_cfg.get("bitrate", "192k"))
        if abr is not None and not (want_abr * AUDIO_BITRATE_RANGE[0] <= abr <= want_abr * AUDIO_BITRATE_RANGE[1]):
            # AAC is average-bitrate: sparse or quiet audio legitimately encodes far below the setting
            warnings.append(f"audio bitrate: {abr / 1000:.0f} kbps, expected about {want_abr / 1000:.0f} kbps")

        loud = measure_audio(p)
        i_lufs, tp, mean, mx = loud["integrated_lufs"], loud["true_peak_db"], loud["mean_db"], loud["max_db"]
        target = float(loud_cfg.get("integrated_lufs", -15))
        tol = float(loud_cfg.get("tolerance_lu", 1))
        tp_max = float(loud_cfg.get("true_peak_db", -1.5))
        silent = (i_lufs is None or i_lufs < SILENT_LUFS) or (mx is not None and mx < SILENT_MAX_DB)
        if silent:
            errors.append(f"audio is silent (integrated {_fmt(i_lufs)} LUFS, max {_fmt(mx)} dB)")
        elif abs(i_lufs - target) > tol:
            errors.append(f"loudness: {i_lufs:.1f} LUFS integrated, expected {target:g} +/- {tol:g}")
        if tp is not None and tp > tp_max:
            errors.append(f"true peak: {tp:.1f} dBTP, must be <= {tp_max:g} dB")
        if mx is not None and mx >= CLIP_SAMPLE_DB:
            errors.append(f"audio is clipped (sample peak {mx:.1f} dBFS)")
        warn_db = float(loud_cfg.get("mean_level_warn_db", -28))
        if not silent and mean is not None and mean < warn_db:
            warnings.append(f"audio mean level {mean:.1f} dB is below {warn_db:g} dB (very quiet)")

    # picture gates (R209)
    if info["has_video"] and dur > 0:
        exempt = endcard_window(plan, dur)
        for a, b in detect_freezes(p):
            b = min(b, dur)
            if _overlap_outside(a, b, exempt) >= FREEZE_MIN_S:
                errors.append(f"frozen frame from {a:.2f} s to {b:.2f} s ({b - a:.1f} s with no change)")
        for bar in detect_black_bars(p, dur, exempt):
            errors.append(bar)

    probe = {k: info.get(k) for k in ("duration", "width", "height", "fps", "vcodec", "profile", "pix_fmt",
                                      "acodec", "sample_rate", "channels", "bit_rate", "format_name")}
    probe["size_mb"] = round(size_mb, 2)
    probe["faststart"] = "moov" in boxes and "mdat" in boxes and boxes.index("moov") < boxes.index("mdat")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "probe": probe,
            "loudness": json_safe(loud) if loud else None}


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else ("-inf" if v == -math.inf else f"{v:.1f}")


def _rate_value(text: Any) -> float:
    s = str(text).strip().lower()
    mult = {"k": 1e3, "m": 1e6}.get(s[-1:], 1.0)
    return float(s[:-1] if s[-1:] in "km" else s) * mult


def _stream_bitrate(path: Path, selector: str) -> float | None:
    probe = nc.ffprobe_bin()
    if probe:
        proc = nc.run([probe, "-v", "error", "-select_streams", selector, "-show_entries", "stream=bit_rate",
                       "-of", "default=nw=1:nk=1", str(path)], what="ffprobe", check=False)
        val = proc.stdout.decode("utf-8", "replace").strip().splitlines()
        if val and val[0].isdigit():
            return float(val[0])
        return None
    data = nc.ffprobe_json(path)
    kind = "video" if selector.startswith("v") else "audio"
    st = next((s for s in data.get("streams", []) if s.get("codec_type") == kind), None)
    br = (st or {}).get("bit_rate")
    return float(br) if br and str(br).isdigit() else None


def _video_bitrate(path: Path, info: dict, dur: float) -> float | None:
    br = _stream_bitrate(path, "v:0")
    if br is None and dur > 0:
        audio = _stream_bitrate(path, "a:0") or 0.0
        br = path.stat().st_size * 8 / dur - audio
    return br


def _audio_bitrate(path: Path) -> float | None:
    return _stream_bitrate(path, "a:0")


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="check_output.py", description="Check a finished video against the output spec.")
    ap.add_argument("file", help="the MP4 to check")
    ap.add_argument("--kind", choices=KINDS, default="reel", help="output kind (sets the allowed length)")
    ap.add_argument("--size", help="expected frame size WxH (default from config render.size, 1080x1920)")
    ap.add_argument("--plan", help="plan.json: its end card may hold a still frame")
    ap.add_argument("--report", metavar="OUT_DIR", help="merge the result into OUT_DIR/report.json")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    args = ap.parse_args(argv)
    size = nc.parse_size(args.size) if args.size else None
    path = Path(args.file).expanduser().resolve()
    plan = Path(args.plan).expanduser().resolve() if args.plan else None
    result = check_file(path, args.kind, size, plan)

    for e in result["errors"]:
        nc.error_line(f"{path.name}: {e}")
    for w in result["warnings"]:
        nc.warn(f"{path.name}: {w}")
    if args.report:
        out_dir = Path(args.report).expanduser().resolve()
        rp = out_dir / "report.json"
        existing = nc.read_json(rp, "report") if rp.exists() else {}
        section = dict(existing.get("check_output") or {}) if isinstance(existing, dict) else {}
        section[path.name] = result
        nc.update_report(out_dir, "check_output", section)
    if args.json:
        nc.print_json({"file": str(path), "kind": args.kind, **result})
    else:
        lo = result["loudness"] or {}

        def show(key: str, unit: str) -> str:
            v = lo.get(key)
            return "n/a" if v is None else f"{v} {unit}"

        state = "OK" if result["ok"] else f"FAIL ({len(result['errors'])} errors)"
        print(f"{state} {path.name}: {result['probe']['width']}x{result['probe']['height']} "
              f"{result['probe']['duration'] or 0:.2f} s {result['probe']['size_mb']} MB, "
              f"loudness {show('integrated_lufs', 'LUFS')}, true peak {show('true_peak_db', 'dB')}, "
              f"mean {show('mean_db', 'dB')}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    nc.run_cli(main)
