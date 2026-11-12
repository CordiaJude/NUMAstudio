#!/usr/bin/env python3
"""NUMA Studio end-to-end suite: the five material folders of milestone M3 (spec p.51).

Each case builds a synthetic material folder from the bundled brand photos and
ffmpeg-generated audio (no member photos, no network, no credits), then runs the
real pipeline with no human input:

    analyze -> fix_transcript (when a script exists) -> vision -> prep_media
    -> baseline_plan -> validate_plan (0 ERRORs) -> engine -> finish
    -> check_output -> qa_frames -> formats

and asserts the reel is postable: check_output passes, 1080x1920, 48 kHz AAC,
loudness in spec, audio not silent, 12 Critic frames, the format files exist.

Cases (REQUIREMENTS.md interpretation 7):
    photos_only      photos, no audio at all (offline music pad fallback)
    clips_only       phone clips that carry their own sound, nothing else
    voice_and_music  photos + a separate voiceover + a music track
    music_only       photos + music, no voice; captions come from a --script text
    heic_photos      iPhone HEIC photos (one rotated by EXIF) + music
Extra (with --extra): combined_track, one file holding voice and music.

The voiceover is synthesized with ffmpeg's flite filter when the build has it
(real words, so caption sync is checked), else a gated tone (no words).

Usage:
    python3 tests/run_tests.py [--only NAME[,NAME]] [--seconds S] [--draft]
                               [--extra] [--keep] [--voice FILE] [--json FILE]
Exit 0 when every case passes, 1 when any fails, 2 on usage errors.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "numa-reel-editor" / "scripts"
BRAND_PHOTOS = sorted((ROOT / "skills" / "numa-reel-editor" / "assets" / "brand-photos").glob("*.jpg"))
sys.path.insert(0, str(SCRIPTS))

import numa_common as nc  # noqa: E402

CASES = ["photos_only", "clips_only", "voice_and_music", "music_only", "heic_photos"]
EXTRA = ["combined_track"]
PY = sys.executable

VOICE_TEXT = ("Welcome to NUMA in Mobile. Heat first, then the cold plunge. "
              "Breathe slow and stay with it. This is how you reset.")
SCRIPT_LINES = ["Heat first, then the cold.", "Breathe slow and stay with it.",
                "This is how you reset.", "Come try it in Mobile."]


class StepFailed(Exception):
    pass


# ---------------------------------------------------------------- fixtures

def ff(*args: str) -> None:
    r = subprocess.run([nc.ffmpeg_bin(), "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        raise StepFailed(f"fixture ffmpeg: {r.stderr.strip()[-300:]}")


def has_flite() -> bool:
    r = subprocess.run([nc.ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True)
    return bool(re.search(r"^\s*\S+\s+flite\s", r.stdout, re.M))


def make_music(path: Path, secs: float) -> None:
    """100 BPM chord pad with a kick on every beat (beat tracking has something to find)."""
    ff("-f", "lavfi", "-i",
       f"aevalsrc='0.12*sin(2*PI*220*t)+0.1*sin(2*PI*277*t)+0.08*sin(2*PI*330*t)"
       f"+0.7*sin(2*PI*55*t)*exp(-18*mod(t,0.6))':s=44100:d={secs:.2f}",
       "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(path))


def make_voice(path: Path, secs: float, real: Path | None) -> bool:
    """Voiceover: a real file (trimmed), flite speech, or a gated tone. Returns True when it has words."""
    if real:
        ff("-i", str(real), "-t", f"{secs:.2f}", "-ac", "1", "-ar", "24000", str(path))
        return True
    if has_flite():
        ff("-f", "lavfi", "-i", f"flite=text='{VOICE_TEXT}':voice=slt", "-af",
           f"atempo=0.92,apad=pad_dur=0.6,adelay=400:all=1,atrim=0:{secs:.2f}", "-ar", "24000", str(path))
        return True
    ff("-f", "lavfi", "-i",
       f"aevalsrc='0.4*sin(2*PI*(170+35*sin(2*PI*3*t))*t)*lt(mod(t,0.45),0.3)*lt(t,{secs - 1:.2f})':s=24000:d={secs:.2f}",
       str(path))
    return False


def make_photos(dst: Path, n: int = 5, heic: bool = False) -> None:
    from PIL import Image
    dst.mkdir(parents=True, exist_ok=True)
    for k, src in enumerate(BRAND_PHOTOS[:n]):
        im = Image.open(src).convert("RGB")
        if k == 1:  # one landscape frame among the portraits
            top = int(im.height * 0.3)
            im = im.crop((0, top, im.width, min(im.height, top + int(im.width * 0.66))))
        if heic:
            import pillow_heif
            pillow_heif.register_heif_opener()
            exif = None
            if k == 2:  # stored sideways with an EXIF rotation, the way iPhones save them
                im = im.transpose(Image.Transpose.ROTATE_90)
                ex = Image.Exif()
                ex[0x0112] = 6
                exif = ex.tobytes()
            kw = {"quality": 85}
            if exif:
                kw["exif"] = exif
            im.save(dst / f"IMG_{4100 + k}.HEIC", format="HEIF", **kw)
        else:
            im.save(dst / f"photo_{k}.jpg", quality=92)


def make_clips(dst: Path, seconds: float) -> None:
    """Three phone clips with their own sound (splash-like noise bursts, a voice-ish hum, room tone)."""
    dst.mkdir(parents=True, exist_ok=True)
    each = max(5.0, seconds / 3 + 1.5)
    sounds = [
        "anoisesrc=c=pink:a=0.25:d={d},highpass=f=400,volume='0.4+0.6*lt(mod(t,1.8),0.35)':eval=frame",
        "aevalsrc='0.25*sin(2*PI*(190+40*sin(2*PI*2.5*t))*t)*lt(mod(t,0.5),0.32)':s=48000:d={d}",
        "anoisesrc=c=brown:a=0.2:d={d},lowpass=f=900",
    ]
    shapes = [("1080:1920", "1080x1920", "clip_vertical.mp4"), ("1920:1080", "1920x1080", "clip_landscape.mov"),
              ("1080:1920", "1080x1920", "IMG_0042.MOV")]
    for k, ((crop, size, name), snd) in enumerate(zip(shapes, sounds)):
        photo = BRAND_PHOTOS[k % len(BRAND_PHOTOS)]
        frames = int(each * 30)
        ff("-loop", "1", "-i", str(photo), "-f", "lavfi", "-i", snd.format(d=f"{each:.2f}"),
           "-vf", f"scale={crop}:force_original_aspect_ratio=increase,crop={crop},"
                  f"zoompan=z='1+0.0015*on':x='iw/2-(iw/zoom/2)+4*sin(on/6)':y='ih/2-(ih/zoom/2)':d={frames}:s={size}:fps=30",
           "-t", f"{each:.2f}", "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dst / name))


def build_case(name: str, job: Path, args) -> dict:
    """Create JOB/raw for one case; returns facts the checks need."""
    raw = job / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    secs = args.seconds
    facts = {"script": None, "words_expected": False, "master": None}
    if name == "photos_only":
        make_photos(raw / "photos")
    elif name == "clips_only":
        make_clips(raw / "clips", secs)
    elif name == "voice_and_music":
        make_photos(raw / "photos")
        make_music(raw / "music.mp3", secs + 25)
        facts["words_expected"] = make_voice(raw / "voiceover.wav", secs - 2, args.voice)
    elif name == "music_only":
        make_photos(raw)
        make_music(raw / "song.mp3", secs + 25)
        script = job / "work" / "script.txt"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("\n".join(SCRIPT_LINES) + "\n", encoding="utf-8")
        facts["script"] = script
    elif name == "heic_photos":
        make_photos(raw, heic=True)
        make_music(raw / "music.mp3", secs + 25)
    elif name == "combined_track":
        make_photos(raw)
        if args.voice:
            ff("-i", str(args.voice), "-t", f"{secs + 10:.2f}", str(raw / "voiceover_and_music.mp3"))
            facts["words_expected"] = True
        else:
            v = job / "v.wav"
            m = job / "m.mp3"
            facts["words_expected"] = make_voice(v, secs - 2, None)
            make_music(m, secs + 10)
            ff("-i", str(m), "-i", str(v), "-filter_complex",
               "[1:a]aresample=44100,pan=stereo|c0=c0|c1=c0,volume=1.6[v];[0:a][v]amix=inputs=2:duration=first:normalize=0",
               str(raw / "voiceover_and_music.mp3"))
            v.unlink()
            m.unlink()
        facts["master"] = raw / "voiceover_and_music.mp3"
    return facts


# ---------------------------------------------------------------- pipeline

def step(log: list, what: str, script: str, *args, json_out: bool = False, timeout: float = 1800):
    t = time.time()
    cmd = [PY, str(SCRIPTS / script), *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log.append((what, round(time.time() - t, 1), r.returncode))
    if "Traceback (most recent call last)" in r.stderr:
        raise StepFailed(f"{what}: traceback: {r.stderr.strip()[-400:]}")
    if r.returncode:
        errs = [ln for ln in (r.stderr + r.stdout).splitlines() if ln.startswith("ERROR")]
        raise StepFailed(f"{what} exit {r.returncode}: " + (" | ".join(errs[:4]) or r.stderr.strip()[-300:]))
    if json_out:
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise StepFailed(f"{what}: --json output is not JSON ({e})")
    return r


def volume_stats(path: Path) -> tuple[float, float]:
    r = subprocess.run([nc.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", r.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", r.stderr)
    to_f = lambda m: float("-inf") if not m or m.group(1) == "-inf" else float(m.group(1))  # noqa: E731
    return to_f(mean), to_f(peak)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise StepFailed(msg)


def run_case(name: str, root: Path, args) -> tuple[str, list]:
    job = nc.JobPaths(root / f"2026-12-01 {name.replace('_', ' ').title()}").make()
    log: list = []
    t = time.time()
    facts = build_case(name, job.job, args)
    log.append(("fixtures", round(time.time() - t, 1), 0))
    work, out = job.work, job.out
    analysis, plan = work / "analysis.json", work / "plan.json"

    a_args = [job.raw, work]
    if facts["master"]:
        a_args += ["--master", facts["master"]]
    if name == "photos_only":
        a_args += ["--pad-seconds", max(30.0, args.seconds + 8)]
    step(log, "analyze", "analyze.py", *a_args)
    if facts["script"]:
        step(log, "fix_transcript", "fix_transcript.py", analysis, "--script", facts["script"])
    step(log, "vision", "vision.py", analysis)
    step(log, "prep_media", "prep_media.py", analysis)
    A = json.loads(analysis.read_text())
    check(bool(A.get("beats")), "analysis: no beats detected")
    if name == "photos_only":
        check(bool(A.get("audio", {}).get("generated_pad")), "photos_only: no offline music pad generated")
    if name == "clips_only":
        check(bool(A.get("audio", {}).get("clip_audio")), "clips_only: the clips' own sound was not used")
    if name == "heic_photos":
        conv = [p for p in A.get("photos", []) if str(p.get("path", "")).lower().endswith(".jpg")]
        check(len(conv) == len(A.get("photos", [])) > 0, "heic_photos: HEIC photos were not converted to JPG")
    if facts["words_expected"]:
        check(len(A.get("words", [])) >= 5, f"voice: transcript has {len(A.get('words', []))} words")

    b_args = [work, "--duration", args.seconds]
    if facts["script"]:
        b_args += ["--script", facts["script"]]
    step(log, "baseline_plan", "baseline_plan.py", *b_args)
    v = step(log, "validate_plan", "validate_plan.py", plan, analysis, "--json", json_out=True)
    check(v.get("ok") is True and not v.get("errors"), f"validate_plan: {v.get('errors')}")
    P = json.loads(plan.read_text())
    if facts["script"]:
        check(len(P.get("lines", [])) > 0, "music_only: no captions from the --script text")

    if args.draft:
        step(log, "engine --draft", "engine.py", plan, "--draft")
        video = work / "video_noaudio_draft.mp4"
    else:
        step(log, "engine", "engine.py", plan)
        video = work / "video_noaudio.mp4"
    slug = job.slug
    reel = job.deliverable("reel")
    step(log, "finish", "finish.py", work, reel, "--video", video, "--plan", plan)

    ck = [reel, "--kind", "reel", "--plan", plan, "--report", out, "--json"]
    if args.draft:
        w, h = nc.config_value("render.size", [1080, 1920])
        scale = float(nc.config_value("render.draft.scale", 0.5))
        ck += ["--size", f"{int(round(w * scale / 2) * 2)}x{int(round(h * scale / 2) * 2)}"]
    co = step(log, "check_output", "check_output.py", *ck, json_out=True)
    check(co.get("ok") is True, f"check_output: {'; '.join(co.get('errors') or [])}")

    info = nc.media_info(reel)
    if not args.draft:
        check((info.get("width"), info.get("height")) == (1080, 1920), f"video size {info.get('width')}x{info.get('height')}")
    check(int(info.get("sample_rate") or 0) == 48000, f"audio {info.get('sample_rate')} Hz")
    dur = float(info.get("duration") or 0)
    check(15.0 <= dur <= 60.0, f"reel length {dur:.2f} s")
    check(abs(dur - float(P["duration"])) < 0.25, f"reel {dur:.2f} s vs plan {P['duration']} s")
    mean, peak = volume_stats(reel)
    check(mean > -28.0 and peak > -12.0, f"audio too quiet or silent (mean {mean} dB, peak {peak} dB)")

    step(log, "qa_frames", "qa_frames.py", reel, plan)
    frames = sorted((out / "critic_frames").glob("frame_*.jpg"))
    check(len(frames) == 12, f"qa_frames: {len(frames)} critic frames, expected 12")
    check((out / "critic_frames" / "index.json").is_file(), "qa_frames: no index.json")
    check((out / "qa_strip.jpg").is_file(), "finish: no qa_strip.jpg")

    f_args = [plan, reel, "--json"] + (["--draft"] if args.draft else [])
    fm = step(log, "formats", "formats.py", *f_args, json_out=True)
    check(fm.get("ok") is not False and not fm.get("errors"), f"formats: {fm.get('errors')}")
    produced = {p.name for p in out.iterdir()}
    for kind, pattern in (("reach cut", rf"^{slug}_reach\.mp4$"), ("story set", rf"^{slug}_story_1\.(jpg|mp4)$"),
                          ("carousel", rf"^{slug}_carousel_1\.jpg$"), ("cover", rf"^{slug}_cover\.jpg$")):
        check(any(re.match(pattern, n) for n in produced), f"formats: no {kind} in out/ ({sorted(produced)})")
    if P.get("lines"):
        check(f"{slug}.srt" in produced, "formats: no .srt although the plan has captions")

    loud = co.get("loudness") or {}
    lufs = next((loud[k] for k in ("integrated_lufs", "integrated", "lufs", "i") if isinstance(loud.get(k), (int, float))), None)
    summary = (f"{len(A.get('photos', []))}P {len(A.get('clips', []))}C {len(A.get('words', []))}w "
               f"{float(A.get('bpm') or 0):.0f}bpm {dur:.1f}s {len(P['shots'])} shots {len(P.get('lines', []))} lines"
               + (f" {float(lufs):.1f} LUFS" if isinstance(lufs, (int, float)) else ""))
    return summary, log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NUMA Studio five-folder end-to-end suite (milestone M3).")
    ap.add_argument("--only", help="comma list of case names to run: " + ",".join(CASES + EXTRA))
    ap.add_argument("--seconds", type=float, default=16.0, help="reel length per case (15-60, default 16)")
    ap.add_argument("--draft", action="store_true", help="draft renders (half size, faster; skips the 1080x1920 check)")
    ap.add_argument("--extra", action="store_true", help="also run the combined voice+music track case")
    ap.add_argument("--keep", action="store_true", help="keep the job folders and print where they are")
    ap.add_argument("--voice", type=Path, help="a real voiceover file to use instead of the synthesized voice")
    ap.add_argument("--json", type=Path, metavar="FILE", help="also write the results table as JSON")
    args = ap.parse_args(argv)
    if not 15.0 <= args.seconds <= 60.0:
        ap.error("--seconds must be between 15 and 60 (a reel is 15-60 s)")
    if args.voice and not args.voice.is_file():
        ap.error(f"--voice: no such file: {args.voice}")
    names = CASES + (EXTRA if args.extra else [])
    if args.only:
        wanted = [n.strip() for n in args.only.split(",") if n.strip()]
        bad = [n for n in wanted if n not in CASES + EXTRA]
        if bad:
            ap.error(f"--only: unknown case(s) {', '.join(bad)}; valid: {', '.join(CASES + EXTRA)}")
        names = [n for n in CASES + EXTRA if n in wanted]

    root = Path(tempfile.mkdtemp(prefix="numa_e2e_"))
    results = []
    t_all = time.time()
    print(f"NUMA Studio end-to-end suite: {len(names)} case(s), {args.seconds:g} s reels"
          f"{' (draft)' if args.draft else ''}, voice: {'file' if args.voice else ('flite' if has_flite() else 'tone')}",
          flush=True)
    for name in names:
        t = time.time()
        try:
            why, log = run_case(name, root, args)
            ok = True
        except StepFailed as e:
            ok, why, log = False, str(e), []
        except subprocess.TimeoutExpired as e:
            ok, why, log = False, f"timeout: {e.cmd[1] if e.cmd else ''}", []
        secs = time.time() - t
        results.append({"case": name, "pass": ok, "seconds": round(secs, 1), "detail": why,
                        "steps": [{"step": s, "seconds": d, "exit": c} for s, d, c in log]})
        print(f"{'PASS' if ok else 'FAIL'}  {name:16s} {secs:6.1f}s  {why}", flush=True)

    passed = sum(r["pass"] for r in results)
    print("\n| Case | Result | Time | Detail |\n|------|--------|------|--------|")
    for r in results:
        print(f"| {r['case']} | {'PASS' if r['pass'] else 'FAIL'} | {r['seconds']:.0f} s | {r['detail']} |")
    print(f"\n{passed}/{len(results)} passed in {time.time() - t_all:.0f} s"
          + (f"  (job folders kept in {root})" if args.keep else ""))
    if args.json:
        args.json.write_text(json.dumps({"passed": passed, "total": len(results), "results": results}, indent=2) + "\n")
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
