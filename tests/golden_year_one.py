#!/usr/bin/env python3
"""NUMA Studio golden test (milestone M2): the "2026-11-09 Year One" test pack, end to end.

The test pack holds founder and member photos, so it is never committed (spec p.49); pass its
path with --pack or the NUMA_TEST_PACK environment variable. Either the test-pack folder or the
dated folder inside it works. Without a pack the harness prints SKIP and exits 0.

What it does, with no other input:
  1. copies the pack into a fresh job folder (raw/ is never modified);
  2. analyze -> fix_transcript -> vision -> prep_media, checking BPM ~ 107.7 (+-2) and that the
     transcript contains "Mobile" (spec p.28);
  3. builds two plans and runs each through validate_plan (0 ERRORs) -> engine -> finish ->
     check_output -> qa_frames -> formats:
       example   assets/example-plan-year-one-v2.json (the hand-built Year One edit) rewritten to
                 the pack: /YEAR_ONE_PACK and /NUMA_PLUGIN prefixes, the build machine's file
                 names mapped to the pack's, crops dropped where the pack photo is already cropped;
       baseline  baseline_plan.py --template transformation with the before/after pair the
                 Director would pick (old house -> finished exterior) and the pack's consent
                 recorded through library.py (stands in for the Consent List);
  4. checks each plan and reel: drop-to-file under 15 min, story arc (before look, turn, warm look,
     hook from frame 0, end card), a before/after wipe, cuts on beats, every caption word within
     0.1 s of the transcript, check_output passes, length ~ the 39 s track;
  5. with the hand-built reference reel (--reference, NUMA_REFERENCE_REEL, or found next to the
     pack's kit), prints objective proxies (duration +-1 s, loudness, detected cut count) and
     writes comparison.jpg (reference vs both reels, frame by frame) for Jude's rating, which is a
     manual step (instructions are printed and written to the report).

Writes golden_report.json and golden_report.md (plus the reels, QA strips and comparison sheet)
to --out (default: a new folder in the system temp folder, printed at the end).

Usage:
    python3 tests/golden_year_one.py [--pack PATH] [--reference MP4] [--out DIR]
                                     [--plans example,baseline] [--keep]
Exit 0 when every check passes (or SKIP), 1 when any check fails, 2 on usage errors.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "numa-reel-editor" / "scripts"
EXAMPLE_PLAN = ROOT / "skills" / "numa-reel-editor" / "assets" / "example-plan-year-one-v2.json"
sys.path.insert(0, str(SCRIPTS))

import numa_common as nc  # noqa: E402

PY = sys.executable
MEDIA = re.compile(r"\.(jpe?g|png|heic|webp|mp4|mov|m4v|mp3|wav|m4a|aac)$", re.I)
TARGET_BPM, BPM_TOL = 107.7, 2.0
MAX_DROP_TO_FILE_S = 15 * 60
CAPTION_TOL_S = 0.1
REFERENCE_NAME = "Year_One_hand_built_reference.mp4"

# The v2 example plan names files as they were on the original build machine. The pack holds the
# same pictures under descriptive names (matched frame by frame against the reference reel); the
# original phone clip is not in the pack, so its slot shows the founders' photo the reference
# shows there. Pack photos are already cropped, so the plan's crop boxes are dropped for them.
EXAMPLE_NAME_MAP = {
    "raw0.png": "01_old-house.jpg", "raw1.png": "02_before-entry.jpg", "raw2.png": "03_gutted-interior.jpg",
    "raw3.png": "04_demo-floor.jpg", "raw4.png": "05_sauna-build.jpg", "raw5.png": "06_sauna-finished.jpg",
    "raw6.png": "07_plunge-room.jpg", "raw8.png": "09_ribbon-cutting.jpg", "raw9.png": "10_first-class.jpg",
    "raw10.png": "11_finished-exterior.jpg", "clip.mp4": "08_katie-and-scott.jpg",
    "9N0A9906.jpg": "13_brand_sauna-logo.jpg", "9N0A0061.jpg": "16_brand_sauna-people.jpg",
    "9N0A0014.jpg": "14_brand_cold-plunge.jpg", "9N0A0139.jpg": "15_brand_red-light.jpg",
    "9N0A0072.jpg": "17_brand_breathwork.jpg", "371A4425.jpg": "18_brand_mats.jpg",
}
BEFORE_NAME, AFTER_NAME = "01_old-house", "11_finished-exterior"

RATING_STEPS = """\
Jude's rating (manual step, milestone M2 pass criterion):
  1. Open comparison.jpg: the hand-built reference (top row) against the example-plan reel and the
     baseline reel at the same moments.
  2. Watch year_one_example_reel.mp4 and year_one_baseline_reel.mp4 next to the reference on a phone,
     sound on, at full screen.
  3. Rate each reel against the reference: better / as good / worse, for the hook (first 2 s), the
     before/after story, cuts on the beat, captions in sync, colour, end card, sound.
  4. Record the verdict in CHANGELOG.md under the release ("Golden test: example as good, baseline
     worse: ..."). A "worse" on the reel the release ships means the release does not ship (spec p.52)."""


class Failed(Exception):
    pass


# ---------------------------------------------------------------- helpers

def find_pack(arg: str | None) -> Path | None:
    raw = arg or os.environ.get("NUMA_TEST_PACK")
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise SystemExit(f"ERROR: test pack: no such folder: {p}")

    def has_media(d: Path) -> bool:
        return any(MEDIA.search(f.name) for f in d.iterdir() if f.is_file())

    if has_media(p):
        return p
    subs = sorted(d for d in p.iterdir() if d.is_dir() and has_media(d))
    year_one = [d for d in subs if "year one" in d.name.lower()]
    if year_one or len(subs) == 1:
        return (year_one or subs)[0]
    raise SystemExit(f"ERROR: test pack: no media folder in {p} (expected '2026-11-09 Year One')")


def find_reference(arg: str | None, pack: Path) -> Path | None:
    raw = arg or os.environ.get("NUMA_REFERENCE_REEL")
    if raw:
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"ERROR: reference reel: no such file: {p}")
        return p
    # the developer kits keep the reference beside the test pack: look up to four folders up
    base = pack
    for _ in range(4):
        base = base.parent
        for hit in sorted(base.glob(f"*/*/{REFERENCE_NAME}")) + sorted(base.glob(f"*/{REFERENCE_NAME}")) \
                + sorted(base.glob(f"*/*/*/{REFERENCE_NAME}")):
            return hit.resolve()
    return None


def run_step(timings: dict, what: str, script: str, *args, json_out: bool = False, allow_fail: bool = False):
    t = time.time()
    r = subprocess.run([PY, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    timings[what] = round(time.time() - t, 1)
    print(f"  {what:<26s} {timings[what]:7.1f} s  exit {r.returncode}", flush=True)
    if "Traceback (most recent call last)" in r.stderr:
        raise Failed(f"{what}: traceback: {r.stderr.strip()[-500:]}")
    if r.returncode and not allow_fail:
        errs = [ln for ln in (r.stderr + r.stdout).splitlines() if ln.startswith("ERROR")]
        raise Failed(f"{what} exit {r.returncode}: " + (" | ".join(errs[:6]) or r.stderr.strip()[-400:]))
    if json_out:
        try:
            return json.loads(r.stdout), r
        except json.JSONDecodeError:
            raise Failed(f"{what}: --json output is not JSON: {r.stdout[:200]!r} {r.stderr[-300:]!r}")
    return r


def norm_word(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def caption_sync(plan: dict, words: list[dict]) -> tuple[float, list[str]]:
    """Largest gap between a caption word's appear time and the same word in the transcript."""
    by_word: dict[str, list[float]] = {}
    for w in words:
        by_word.setdefault(norm_word(w["w"]), []).append(float(w.get("appear", w.get("start", 0.0))))
    worst, bad = 0.0, []
    for line in plan.get("lines", []):
        for item in line.get("words", []):
            text, t = item[0], float(item[1])
            key = norm_word(text)
            if not key:
                continue
            cands = by_word.get(key)
            if not cands:
                bad.append(f"'{text}' @{t:.2f} not in the transcript")
                continue
            d = min(abs(t - c) for c in cands)
            worst = max(worst, d)
            if d > CAPTION_TOL_S + 1e-6:
                bad.append(f"'{text}' @{t:.2f} is {d:.2f} s off")
    return worst, bad


def cut_times(plan: dict) -> list[float]:
    return sorted(float(s["t0"]) for s in plan["shots"] if float(s["t0"]) > 1e-6)


def beat_alignment(plan: dict, beats: list[float], fps: float) -> tuple[int, int, float]:
    """(cuts within one frame of a beat, cuts, worst offset)."""
    tol = 1.0 / fps + 1e-3
    cuts = cut_times(plan)
    if not beats or not cuts:
        return 0, len(cuts), float("inf")
    offs = [min(abs(c - b) for b in beats) for c in cuts]
    return sum(o <= tol for o in offs), len(cuts), max(offs)


def detect_cuts(video: Path, threshold: float = 0.3) -> int:
    """Scene changes found by ffmpeg's scene score (same detector for every reel, so counts compare)."""
    r = subprocess.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(video), "-an", "-vf",
                        f"scale=270:480,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return len(re.findall(r"pts_time:", r.stderr))


def loudness(video: Path) -> dict:
    import check_output
    vals = check_output.measure_audio(video)
    return check_output.json_safe(vals)


def frame_at(video: Path, t: float, w: int = 270, h: int = 480):
    from PIL import Image
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run([nc.ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
                        tmp], capture_output=True, check=True)
        return Image.open(tmp).convert("RGB")
    except (subprocess.CalledProcessError, OSError):
        return Image.new("RGB", (w, h), (40, 40, 40))
    finally:
        Path(tmp).unlink(missing_ok=True)


def comparison_sheet(rows: list[tuple[str, Path]], times: list[float], out: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    w, h, label_w, head = 270, 480, 170, 34
    sheet = Image.new("RGB", (label_w + w * len(times), head + h * len(rows)), (16, 16, 16))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(nc.brand_font("regular")), 24)
    except (OSError, nc.UserError):
        font = ImageFont.load_default()
    for j, t in enumerate(times):
        d.text((label_w + j * w + 8, 4), f"{t:.1f} s", fill=(235, 235, 235), font=font)
    for i, (name, video) in enumerate(rows):
        d.text((8, head + i * h + h // 2 - 12), name, fill=(235, 235, 235), font=font)
        for j, t in enumerate(times):
            sheet.paste(frame_at(video, t), (label_w + j * w, head + i * h))
    sheet.save(out, quality=88)
    return out


# ---------------------------------------------------------------- plans

def example_plan(job: nc.JobPaths, analysis: dict, out_dir: Path) -> dict:
    from PIL import Image
    text = EXAMPLE_PLAN.read_text(encoding="utf-8")
    plan = json.loads(text)
    plan.pop("_note", None)
    raw = job.raw

    def remap(src: str) -> str:
        if src.startswith("/NUMA_PLUGIN/"):
            return str(ROOT / src[len("/NUMA_PLUGIN/"):])
        if src.startswith("/YEAR_ONE_PACK/"):
            name = Path(src).name
            mapped = EXAMPLE_NAME_MAP.get(name, name)
            hit = raw / mapped
            if not hit.exists():
                raise Failed(f"example plan: {name} -> {mapped} is not in the test pack")
            return str(hit)
        return src

    for key in ("font_regular", "font_italic"):
        if key in plan:
            plan[key] = remap(plan[key])
    if isinstance(plan.get("endcard"), dict):
        for k, v in list(plan["endcard"].items()):
            if isinstance(v, str) and v.startswith("/"):
                plan["endcard"][k] = remap(v)
    faces = {}
    for item in analysis.get("photos", []) + analysis.get("clips", []):
        for key in ("path", "orig_path", "prepared_path"):
            if item.get(key):
                faces[str(Path(item[key]).resolve())] = bool(item.get("faces") or item.get("orig_faces"))
    for s in plan["shots"]:
        orig = s["src"]
        s["src"] = remap(orig)
        if Path(orig).name == "clip.mp4":  # the clip slot becomes a still
            s.pop("kind", None)
            s.pop("start", None)
        if "crop" in s:
            with Image.open(s["src"]) as im:
                cw, ch = s["crop"][2] - s["crop"][0], s["crop"][3] - s["crop"][1]
                if abs(im.width - cw) <= 2 and abs(im.height - ch) <= 2:
                    s.pop("crop")
        if faces.get(str(Path(s["src"]).resolve())):
            # NUMA's own founders and brand-shoot models: consented (the harness's Consent List)
            s["people"], s["consent"] = True, True
    plan["out_dir"] = str(out_dir)
    if isinstance(plan.get("music"), dict) and plan["music"].get("path"):
        tracks = sorted(f for f in raw.iterdir() if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac"))
        if tracks:
            plan["music"]["path"] = str(tracks[0])
        plan["music"]["source"] = "folder"
    plan.setdefault("meta", {})["slug"] = "year-one-example"
    return plan


def story_arc(plan: dict) -> list[str]:
    """What is missing from the before -> turn -> after arc."""
    problems = []
    shots = sorted(plan["shots"], key=lambda s: float(s["t0"]))
    looks = [s.get("look", "none") for s in shots]
    if "before" not in looks[: max(2, len(looks) // 3)]:
        problems.append("no 'before' look in the opening third")
    if "warm" not in looks[len(looks) // 3:]:
        problems.append("no 'warm' look after the turn")
    if "before" in looks and "warm" in looks:
        last_before = max(i for i, lk in enumerate(looks) if lk == "before")
        first_warm = min(i for i, lk in enumerate(looks) if lk == "warm")
        if first_warm > last_before + 4 and last_before > len(looks) // 2:
            problems.append("the warm 'after' half never takes over")
    hook = plan.get("hook")
    if not (isinstance(hook, dict) and hook.get("text")) and not plan.get("lines"):
        problems.append("no hook text from frame 0")
    if not isinstance(plan.get("endcard"), dict):
        problems.append("no end card")
    return problems


# ---------------------------------------------------------------- main

def run_plan(name: str, job: nc.JobPaths, plan_path: Path, analysis: dict, base_timings: dict,
             report_dir: Path) -> dict:
    res: dict = {"plan": name, "checks": {}, "timings": {}, "ok": False}
    T = res["timings"]
    print(f"\n[{name}]", flush=True)
    plan = json.loads(plan_path.read_text())
    out_dir = Path(plan["out_dir"])
    checks = res["checks"]

    def ok(key: str, cond: bool, detail: str) -> None:
        checks[key] = {"pass": bool(cond), "detail": detail}

    v, _ = run_step(T, "validate_plan", "validate_plan.py", plan_path, job.analysis, "--json", json_out=True,
                    allow_fail=True)
    ok("validate_plan: 0 ERRORs", v.get("ok") is True and not v.get("errors"),
       f"{len(v.get('errors') or [])} errors, {len(v.get('warnings') or [])} warnings"
       + (": " + "; ".join(e.get("message", str(e)) if isinstance(e, dict) else str(e)
                           for e in (v.get("errors") or [])[:4]) if v.get("errors") else ""))
    if v.get("errors"):
        raise Failed(f"{name}: validate_plan errors: {checks['validate_plan: 0 ERRORs']['detail']}")

    has_wipe = any(s.get("tr") == "wipe" for s in plan["shots"])
    sig = plan.get("signature") or {}
    ok("before/after wipe", has_wipe, f"wipe at {[s['t0'] for s in plan['shots'] if s.get('tr') == 'wipe']}, "
       f"signature {sig.get('type', sig.get('kind', '-'))}")
    arc = story_arc(plan)
    ok("story arc", not arc, "; ".join(arc) or "before look -> turn -> warm look, hook from frame 0, end card")
    on, n, worst = beat_alignment(plan, analysis.get("beats", []), float(plan.get("fps", 30)))
    ok("cuts on beats", n > 0 and on / n >= 0.9, f"{on}/{n} cuts within one frame of a beat (worst {worst:.3f} s)")
    worst_cap, bad = caption_sync(plan, analysis.get("words", []))
    n_words = sum(len(ln.get("words", [])) for ln in plan.get("lines", []))
    ok("captions synced (0.1 s)", n_words > 0 and not bad,
       f"{n_words} caption words, worst {worst_cap:.3f} s" + (": " + "; ".join(bad[:5]) if bad else ""))

    run_step(T, "engine", "engine.py", plan_path)
    reel = report_dir / f"year_one_{name}_reel.mp4"
    run_step(T, "finish", "finish.py", job.work, reel, "--video", out_dir / "video_noaudio.mp4", "--plan", plan_path)
    drop = sum(base_timings.values()) + T["validate_plan"] + T["engine"] + T["finish"]
    res["drop_to_file_s"] = round(drop, 1)
    ok("drop-to-file < 15 min", drop < MAX_DROP_TO_FILE_S,
       f"{drop / 60:.1f} min (analysis {sum(base_timings.values()):.0f} s + render {T['engine']:.0f} s + finish {T['finish']:.0f} s)")
    co, _ = run_step(T, "check_output", "check_output.py", reel, "--kind", "reel", "--plan", plan_path,
                     "--report", report_dir / f"{name}_report", "--json", json_out=True, allow_fail=True)
    ok("check_output passes", co.get("ok") is True, "; ".join(co.get("errors") or []) or "output spec met")
    probe = co.get("probe") or {}
    res["loudness"] = co.get("loudness")
    res["duration"] = probe.get("duration")
    ok("1080x1920, 48 kHz", (probe.get("width"), probe.get("height"), probe.get("sample_rate")) == (1080, 1920, 48000),
       f"{probe.get('width')}x{probe.get('height')}, {probe.get('sample_rate')} Hz")
    adur = float(analysis.get("duration") or 0)
    ok("length matches the track", abs(float(probe.get("duration") or 0) - min(adur, 60.0)) <= 1.0,
       f"reel {probe.get('duration')} s, track {adur:.2f} s")

    qa_dir = report_dir / f"{name}_critic_frames"
    run_step(T, "qa_frames", "qa_frames.py", reel, plan_path, "--out", qa_dir)
    frames = sorted(qa_dir.glob("frame_*.jpg"))
    ok("12 critic frames", len(frames) == 12, f"{len(frames)} frames")
    strip = reel.parent / "qa_strip.jpg"
    if strip.is_file():
        strip.rename(report_dir / f"{name}_qa_strip.jpg")
    res["qa_strip"] = str(report_dir / f"{name}_qa_strip.jpg")

    fm_dir = report_dir / f"{name}_formats"
    fm_dir.mkdir(exist_ok=True)
    fm, _ = run_step(T, "formats", "formats.py", plan_path, reel, "--out", fm_dir, "--json", json_out=True,
                     allow_fail=True)
    files = [f for f in fm.get("files") or [] if Path(f).is_file()]
    kinds = sorted(k for k, o in (fm.get("outputs") or {}).items() if o.get("files"))
    ok("formats", fm.get("ok") is not False and not fm.get("errors") and {"reach", "cover"} <= set(kinds),
       f"{len(files)} files ({', '.join(kinds) or 'none'})"
       + (f"; errors: {fm.get('errors')}" if fm.get("errors") else ""))
    res["reel"] = str(reel)
    res["cuts_planned"] = len(cut_times(plan))
    res["cuts_detected"] = detect_cuts(reel)
    res["ok"] = all(c["pass"] for c in checks.values())
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NUMA Studio golden test: the Year One test pack (milestone M2).")
    ap.add_argument("--pack", help="test pack folder (or the dated folder inside it); default $NUMA_TEST_PACK")
    ap.add_argument("--reference", help="hand-built reference reel; default $NUMA_REFERENCE_REEL or found near the pack")
    ap.add_argument("--out", type=Path, help="report folder (default: a new folder in the system temp folder)")
    ap.add_argument("--plans", default="example,baseline", help="comma list: example, baseline (default both)")
    ap.add_argument("--keep", action="store_true", help="keep the job folder (raw/work) next to the report")
    args = ap.parse_args(argv)
    plans = [p.strip() for p in args.plans.split(",") if p.strip()]
    if not plans or any(p not in ("example", "baseline") for p in plans):
        ap.error("--plans takes example and/or baseline")

    pack = find_pack(args.pack)
    if pack is None:
        print("SKIP: golden test needs the Year One test pack: pass --pack PATH or set NUMA_TEST_PACK "
              "(never commit the pack; spec p.49).")
        return 0
    reference = find_reference(args.reference, pack)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = (args.out or Path(tempfile.gettempdir()) / f"numa_golden_{stamp}").resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="numa_golden_job_"))
    job = nc.JobPaths(scratch / pack.name).make()
    report: dict = {"pack": str(pack), "reference": str(reference) if reference else None, "started": stamp,
                    "plugin_version": json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"],
                    "analysis": {}, "plans": [], "ok": False}
    t_all = time.time()
    print(f"Golden test (M2): {pack}\n  job {job.job}\n  report {report_dir}", flush=True)
    try:
        for f in sorted(pack.iterdir()):
            if f.is_file() and MEDIA.search(f.name):
                shutil.copy2(f, job.raw / f.name)
        base: dict = {}
        print("\n[analysis]", flush=True)
        run_step(base, "analyze", "analyze.py", job.raw, job.work)
        run_step(base, "fix_transcript", "fix_transcript.py", job.analysis)
        run_step(base, "vision", "vision.py", job.analysis)
        run_step(base, "prep_media", "prep_media.py", job.analysis)
        A = json.loads(job.analysis.read_text())
        bpm = float(A.get("bpm") or 0)
        an = report["analysis"]
        an["timings"] = base
        an["checks"] = {
            "BPM ~ 107.7": {"pass": abs(bpm - TARGET_BPM) <= BPM_TOL, "detail": f"{bpm:.1f} BPM"},
            "transcript has 'Mobile'": {"pass": "Mobile" in (A.get("transcript") or ""),
                                        "detail": (A.get("transcript") or "")[:160]},
            "voice found": {"pass": bool(A.get("voice_present")), "detail": f"{len(A.get('words', []))} words"},
        }
        an.update(bpm=round(bpm, 2), duration=A.get("duration"), words=len(A.get("words", [])),
                  photos=len(A.get("photos", [])), clips=len(A.get("clips", [])))

        for name in plans:
            out_dir = job.work / name
            out_dir.mkdir(exist_ok=True)
            plan_path = out_dir / "plan.json"
            t0 = time.time()
            try:
                if name == "example":
                    nc.write_json(plan_path, example_plan(job, A, out_dir))
                else:
                    idx = job.work / "library.json"
                    pics = [str(job.raw / f) for f in sorted(os.listdir(job.raw)) if MEDIA.search(f)
                            and not f.lower().endswith((".mp3", ".wav", ".m4a", ".aac"))]
                    run_step({}, "library consent", "library.py", "add", "--index", idx, "--consent", "yes",
                             "--tags", "year-one", "--no-faces", *pics)
                    ids = {Path(p.get("orig_path") or p["path"]).stem: p["id"] for p in A.get("photos", [])}
                    b_args = [job.work, "--out", plan_path, "--library", idx, "--template", "transformation"]
                    if BEFORE_NAME in ids and AFTER_NAME in ids:
                        b_args += ["--before", ids[BEFORE_NAME], "--after", ids[AFTER_NAME]]
                    T: dict = {}
                    run_step(T, "baseline_plan", "baseline_plan.py", *b_args)
                    P = json.loads(plan_path.read_text())
                    P["out_dir"] = str(out_dir)
                    P.setdefault("meta", {})["slug"] = "year-one-baseline"
                    nc.write_json(plan_path, P)
                plan_s = time.time() - t0
                res = run_plan(name, job, plan_path, A, {**base, "plan": plan_s}, report_dir)
            except Failed as e:
                res = {"plan": name, "ok": False, "error": str(e), "checks": {}}
                print(f"  FAILED: {e}", flush=True)
            report["plans"].append(res)

        if reference:
            ref: dict = {"path": str(reference)}
            ref["duration"] = nc.media_info(reference).get("duration")
            ref["loudness"] = loudness(reference)
            ref["cuts_detected"] = detect_cuts(reference)
            report["reference_proxies"] = ref
            rows = [("reference", reference)] + [(p["plan"], Path(p["reel"])) for p in report["plans"] if p.get("reel")]
            dur = float(ref["duration"] or 39.0)
            times = [0.4, 2.0, 5.4, 8.0, 12.0, 15.4, 18.3, 23.0, 29.2, min(dur - 1.0, 36.5)]
            report["comparison_sheet"] = str(comparison_sheet(rows, times, report_dir / "comparison.jpg"))
            for p in report["plans"]:
                if not p.get("reel"):
                    continue
                d = abs(float(p.get("duration") or 0) - dur)
                p["vs_reference"] = {
                    "duration_diff_s": round(d, 2), "duration_within_1s": d <= 1.0,
                    "lufs_diff": (round(p["loudness"]["integrated_lufs"] - ref["loudness"]["integrated_lufs"], 2)
                                  if (p.get("loudness") or {}).get("integrated_lufs") is not None
                                  and ref["loudness"].get("integrated_lufs") is not None else None),
                    "cuts_detected": p["cuts_detected"], "reference_cuts_detected": ref["cuts_detected"],
                }
                p["checks"]["duration within 1 s of the reference"] = {
                    "pass": d <= 1.0, "detail": f"{p.get('duration')} s vs {dur:.2f} s"}
                p["ok"] = all(c["pass"] for c in p["checks"].values())
    finally:
        report["total_s"] = round(time.time() - t_all, 1)
        if args.keep:
            kept = report_dir / "job"
            shutil.move(str(job.job), str(kept))
            report["job"] = str(kept)
        shutil.rmtree(scratch, ignore_errors=True)

    an_ok = all(c["pass"] for c in report["analysis"].get("checks", {}).values())
    report["ok"] = an_ok and bool(report["plans"]) and all(p.get("ok") for p in report["plans"])
    report["rating_instructions"] = RATING_STEPS
    nc.write_json(report_dir / "golden_report.json", report)
    md = render_markdown(report)
    (report_dir / "golden_report.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Report: {report_dir / 'golden_report.md'}")
    return 0 if report["ok"] else 1


def render_markdown(r: dict) -> str:
    L = [f"# Golden test (M2): Year One, NUMA Studio {r['plugin_version']}", "",
         f"Pack: `{r['pack']}`  ", f"Total: {r['total_s'] / 60:.1f} min. Result: **{'PASS' if r['ok'] else 'FAIL'}**", ""]
    a = r.get("analysis") or {}
    L += ["## Analysis", "", "| Check | Result | Detail |", "|---|---|---|"]
    for k, c in (a.get("checks") or {}).items():
        L.append(f"| {k} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |")
    L += ["", "Timings: " + ", ".join(f"{k} {v:g} s" for k, v in (a.get("timings") or {}).items()), ""]
    for p in r.get("plans", []):
        L += [f"## Plan: {p['plan']}", ""]
        if p.get("error"):
            L += [f"FAILED: {p['error']}", ""]
        L += ["| Check | Result | Detail |", "|---|---|---|"]
        for k, c in p.get("checks", {}).items():
            L.append(f"| {k} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |")
        if p.get("timings"):
            L += ["", "Timings: " + ", ".join(f"{k} {v:g} s" for k, v in p["timings"].items())
                  + (f"; drop-to-file {p['drop_to_file_s'] / 60:.1f} min" if p.get("drop_to_file_s") else "")]
        if p.get("vs_reference"):
            v = p["vs_reference"]
            L += ["", f"Against the reference: length diff {v['duration_diff_s']} s, loudness diff {v['lufs_diff']} LU, "
                      f"detected cuts {v['cuts_detected']} vs {v['reference_cuts_detected']}"]
        L.append("")
    ref = r.get("reference_proxies")
    if ref:
        lo = ref.get("loudness") or {}
        L += ["## Reference reel (objective proxies)", "",
              f"{ref['duration']:.2f} s, {lo.get('integrated_lufs')} LUFS, true peak {lo.get('true_peak_db')} dB, "
              f"{ref['cuts_detected']} detected cuts. Comparison sheet: `{r.get('comparison_sheet')}`", ""]
    else:
        L += ["Reference reel not found: pass --reference or set NUMA_REFERENCE_REEL for the comparison sheet.", ""]
    L += ["## " + r["rating_instructions"].splitlines()[0], ""] + r["rating_instructions"].splitlines()[1:] + [""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
