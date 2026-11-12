#!/usr/bin/env python3
"""Extract the Critic's frames from a rendered reel (spec p.40, interpretation 13).

    qa_frames.py VIDEO_MP4 PLAN_JSON [--out DIR] [--count 12]

The set is the first second, every cut (taken just after its transition has
settled) and the last second, `--count` frames in all. With more cuts than
slots the cuts are subsampled evenly (first and last cut kept); with fewer,
the remaining slots go to the middles of the longest shots, so the Critic
always gets `--count` frames. Writes DIR/frame_01.jpg ... and DIR/index.json
([{"file", "t", "why"}], in time order); DIR defaults to
<video folder>/critic_frames/. Also sets the `qa_frames` section of the
report.json next to the video. Deterministic: same video + plan = same frames.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

# How long after a cut the incoming transition has settled (engine transition timings, CONTRACTS §4).
SETTLE_S = {"cut": 0.10, "punch": 0.30, "whip": 0.20, "flash": 0.40, "fade": 0.55, "leakfade": 0.55, "wipe": 1.05}
LAST_BEFORE_END_S = 0.5  # "last second" frame time before the end
MIN_GAP_S = 0.25        # filler frames keep at least this far from frames already chosen
JPEG_QUALITY = 90


def grab_frame(video: str | Path, t: float, scale: tuple[int, int] | None = None):
    """The frame at time t as a PIL RGB image (exact seek; steps back a little near the end)."""
    from PIL import Image
    vf = ["-vf", f"scale={scale[0]}:{scale[1]}:flags=bicubic"] if scale else []
    for back in (0.0, 0.05, 0.15, 0.4):
        tt = max(0.0, t - back)
        proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{tt:.3f}",
                       "-i", str(video), "-map", "0:v:0", "-frames:v", "1", *vf, "-c:v", "png",
                       "-f", "image2pipe", "-"], what="ffmpeg frame grab", check=False)
        if proc.returncode == 0 and proc.stdout:
            with Image.open(io.BytesIO(proc.stdout)) as im:
                return im.convert("RGB")
    raise nc.UserError(f"could not read a frame at {t:.2f} s from {video}")


def evenly(items: list, k: int) -> list:
    """k items spread evenly over the list, first and last kept (deterministic)."""
    n = len(items)
    if k >= n:
        return list(items)
    if k <= 0:
        return []
    if k == 1:
        return [items[0]]
    idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return [items[i] for i in idx]


def select_times(plan: dict, duration: float, count: int = 12, fps: float = 30.0) -> list[dict[str, Any]]:
    """The frame list [{"t", "why"}] in time order, `count` long when the video allows it."""
    if count < 2:
        raise nc.UsageError("--count must be at least 2 (first and last second)")
    shots = [s for s in plan.get("shots") or [] if isinstance(s, dict)]
    frame = 1.0 / (fps or 30.0)
    last_t = max(0.0, duration - 2 * frame)
    first = {"t": 0.0, "why": "first second"}
    # the last second: its final settled frame, half a second before the end
    last = {"t": round(max(0.0, min(duration - LAST_BEFORE_END_S, last_t)), 3), "why": "last second"}

    cuts: list[dict[str, Any]] = []
    for i, shot in enumerate(shots[1:], start=1):
        t0 = float(shot.get("t0", 0.0))
        t1 = float(shot.get("t1", duration))
        tr = shot.get("tr", "cut")
        t = t0 + SETTLE_S.get(tr, 0.10)
        t = min(t, t0 + max(frame, (t1 - t0) - frame), last["t"] - frame)
        if 0.0 < t < last["t"]:
            cuts.append({"t": round(t, 3), "why": f"cut {i} ({tr})"})
    chosen = [first] + evenly(cuts, count - 2) + [last]

    if len(chosen) < count:
        # fill the free slots farthest-point first: shot middles, then an even grid (deterministic)
        fillers = [{"t": round((float(s.get("t0", 0)) + float(s.get("t1", 0))) / 2, 3), "why": f"mid shot {i}", "rank": 0}
                   for i, s in enumerate(shots)]
        steps = max(count * 4, 8)
        fillers += [{"t": round(duration * (k + 0.5) / steps, 3), "why": "even spread", "rank": 1} for k in range(steps)]
        fillers = [f for f in fillers if 0.0 <= f["t"] <= last["t"]]
        while len(chosen) < count and fillers:
            def gap(f):
                return min(abs(f["t"] - c["t"]) for c in chosen)
            best = max(fillers, key=lambda f: (round(gap(f), 3), -f["rank"], -f["t"]))
            fillers.remove(best)
            if gap(best) < MIN_GAP_S:
                break
            chosen.append({"t": best["t"], "why": best["why"]})
    chosen.sort(key=lambda c: (c["t"], c["why"]))
    return chosen


def extract(video: Path, plan: dict, out_dir: Path, count: int = 12) -> list[dict[str, Any]]:
    info = nc.media_info(video)
    if not info["has_video"]:
        raise nc.UserError(f"no video stream in {video}")
    duration = info["duration"] or float(plan.get("duration") or 0)
    plan_d = plan.get("duration")
    if isinstance(plan_d, (int, float)) and plan_d > 0:
        duration = min(duration, float(plan_d))
    if duration <= 0:
        raise nc.UserError(f"cannot read a duration from {video}")
    frames = select_times(plan, duration, count, info["fps"] or float(plan.get("fps") or 30))
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()
    index = []
    for n, f in enumerate(frames, start=1):
        name = f"frame_{n:02d}.jpg"
        grab_frame(video, f["t"]).save(out_dir / name, quality=JPEG_QUALITY)
        index.append({"file": name, "t": f["t"], "why": f["why"]})
    nc.write_json(out_dir / "index.json", index)
    return index


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="qa_frames.py", description="Extract the Critic's frames (first second, every cut, last second).")
    ap.add_argument("video", help="the rendered MP4")
    ap.add_argument("plan", help="plan.json the video was rendered from")
    ap.add_argument("--out", help="output folder (default <video folder>/critic_frames)")
    ap.add_argument("--count", type=int, default=None, help="number of frames (default config critic.frames.count, 12)")
    args = ap.parse_args(argv)
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        raise nc.UserError(f"video not found: {video}")
    plan = nc.read_json(Path(args.plan).expanduser().resolve(), "plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
        raise nc.UserError(f"plan {args.plan} has no shots list")
    count = args.count if args.count is not None else int(nc.config_value("critic.frames.count", 12))
    out_dir = Path(args.out).expanduser().resolve() if args.out else video.parent / "critic_frames"
    index = extract(video, plan, out_dir, count)
    nc.update_report(video.parent, "qa_frames", {"dir": str(out_dir), "count": len(index)})
    print(f"OK {len(index)} frames in {out_dir}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
