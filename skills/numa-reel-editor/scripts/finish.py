#!/usr/bin/env python3
"""Master the audio, mix natural sound, mux with the rendered video, measure, QA strip.

    finish.py WORK_DIR OUTPUT_MP4 [--video FILE] [--plan PLAN_JSON] [--clean-voice] [--no-qa] [--json]

Steps (spec p.18-19, p.48; docs/CONTRACTS.md §9):

1. Audio bed: WORK/master.wav; without it, the plan's `music.path`, else
   WORK/pad.wav, else a soft pad generated here (deterministic, config
   `render.pad` when present), so a reel is never silent.
2. Voice chain, only when a voice is present (analysis.json `voice_present`):
   high-pass 85 Hz, -2.5 dB at 180 Hz, -4 dB at 3.8 kHz, -2.5 dB at 7 kHz,
   low-pass 11 kHz, a short room echo (dropped by --clean-voice), 2:1
   compression. Music-only reels get no voice EQ.
3. Natural sound: the plan's `nat` bursts (clip audio from `start`, at reel
   time `t`, `dur` long, `gain_db`) with short fades, ducked under the voice
   and mixed under the bed.
4. Fades, then two-pass loudnorm to -15 LUFS integrated / true peak -1.5 dB
   (pass 1 measures, pass 2 applies linear normalization), 48 kHz -> WORK/aud.wav.
5. Mux: H.264 copy + AAC 192k 48 kHz stereo, +faststart, bitexact (same inputs
   give a byte-identical file).
6. Measure the final file (integrated LUFS, true peak, LRA, mean dB); if the
   AAC encode pushed the true peak over the limit, re-master with a lower
   ceiling. WARN when the mean level is below -28 dB.
7. qa_strip.jpg (6 frames, 1620x480) and the `finish` section of report.json,
   both next to OUTPUT_MP4.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
from check_output import json_safe, measure_audio  # noqa: E402
from qa_frames import grab_frame  # noqa: E402

SR = 48000
FADE_IN_S = 0.15
FADE_OUT_S = 1.2
NAT_FADE_S = 0.08
NAT_DEFAULT_GAIN_DB = -6.0
STRIP_TILE = (270, 480)
STRIP_AT = (0.05, 0.25, 0.45, 0.65, 0.85, 0.97)
MAX_PASSES = 8              # gain/ceiling refinement passes (each: gain+limit, AAC encode, measure)
TP_HEADROOM_DB = 0.5        # first limiter ceiling sits this far under the limit (AAC overshoot)
TP_MARGIN_DB = 0.2          # extra step when the encoded true peak is still over
LUFS_SETTLE = 0.3           # stop refining once within this of the target
MAX_GAIN_DB = 40.0
LIMITER_OVERSAMPLE = 4      # limit at 192 kHz so inter-sample (true) peaks are caught
SILENT_INPUT_LUFS = -60.0   # an audio file quieter than this counts as missing
# Soft pad used only when there is no audio at all (failure table: "natural sound from the clips plus a soft pad").
PAD_DEFAULT = {"chord_hz": [110.0, 164.81, 220.0, 277.18], "level_db": -20.0, "swell_hz": 0.08,
               "detune_hz": 0.35, "lowpass_hz": 1400}
# Ducking of natural sound under the voice.
DUCK = "threshold=0.1:ratio=3:attack=10:release=350"


# --------------------------------------------------------------------------- filter builders
def voice_chain(clean: bool = False) -> str:
    """The voice mastering chain (before loudness normalization)."""
    room = "" if clean else "aecho=0.85:0.5:28|55|90:0.14|0.09|0.05,"
    return ("highpass=f=85,"
            "equalizer=f=180:t=q:w=1:g=-2.5,"
            "equalizer=f=3800:t=q:w=1.4:g=-4,"
            "equalizer=f=7000:t=q:w=1:g=-2.5,"
            "lowpass=f=11000,"
            f"{room}"
            "acompressor=threshold=-20dB:ratio=2:attack=15:release=200")


def to_float(x: Any) -> float | None:
    """float(x) for finite numbers, else None ('-inf', 'nan', junk)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def loudnorm_measure_filter(target: dict) -> str:
    """Pass 1: loudnorm in analysis mode (measures integrated loudness, true peak, LRA)."""
    return f"loudnorm=I={target['i']:g}:TP={target['tp']:g}:LRA={target['lra']:g}:print_format=json"


def gain_limiter_filter(gain_db: float, ceiling_db: float) -> str:
    """Pass 2: one linear gain to the target, then a true-peak limiter (oversampled) at the ceiling."""
    limit = max(0.0625, min(1.0, 10 ** (ceiling_db / 20)))
    return (f"volume={gain_db:.3f}dB,aresample={SR * LIMITER_OVERSAMPLE},"
            f"alimiter=limit={limit:.6f}:attack=2:release=60:level=false:latency=true,aresample={SR}")


def mastering_filters(voice: bool, clean: bool, duration: float, target: dict,
                      gain_db: float | None = None, ceiling_db: float | None = None) -> str:
    """Human-readable full chain (reported; normalization runs as measure pass + gain/limiter pass)."""
    stages = ([voice_chain(clean)] if voice else []) + [
        f"afade=t=in:d={FADE_IN_S}", f"afade=t=out:st={max(duration - FADE_OUT_S, 0):.3f}:d={FADE_OUT_S}",
        loudnorm_measure_filter(target).replace(":print_format=json", " (pass 1: measure)"),
        gain_limiter_filter(gain_db if gain_db is not None else 0.0,
                            ceiling_db if ceiling_db is not None else target["tp"] - TP_HEADROOM_DB)
        + " (pass 2: linear gain to target + true-peak limiter)"]
    return ",".join(stages)


def pad_source(duration: float) -> tuple[str, int]:
    """aevalsrc expression for the soft generated pad (deterministic; config render.pad overrides)."""
    cfg = dict(PAD_DEFAULT)
    over = nc.config_value("render.pad")
    if isinstance(over, dict):
        cfg.update({k: v for k, v in over.items() if not k.startswith("_")})
    freqs = [float(f) for f in cfg["chord_hz"]] or PAD_DEFAULT["chord_hz"]
    weights = [1.0 / (k + 1) for k in range(len(freqs))]
    amp = 10 ** (float(cfg["level_db"]) / 20) / sum(weights)
    swell = f"(0.75+0.25*sin(2*PI*{float(cfg['swell_hz']):g}*t))"

    def chan(detune: float) -> str:
        parts = [f"{w * amp:.6f}*sin(2*PI*{f + detune:.3f}*t)" for f, w in zip(freqs, weights)]
        return f"({'+'.join(parts)})*{swell}"

    expr = f"{chan(0.0)}|{chan(float(cfg['detune_hz']))}"
    return f"aevalsrc='{expr}':s={SR}:d={duration:.3f}", int(cfg["lowpass_hz"])


# --------------------------------------------------------------------------- inputs
def load_optional_json(path: Path, what: str) -> dict | None:
    if not path.is_file():
        return None
    data = nc.read_json(path, what)
    if not isinstance(data, dict):
        raise nc.UserError(f"{what} {path} is not a JSON object")
    return data


def plan_bursts(plan: dict | None, duration: float, warnings: list[str]) -> list[dict]:
    """Usable nat bursts, clamped to the reel and the clip; unusable ones become warnings."""
    out: list[dict] = []
    if not plan:
        return out
    infos: dict[str, dict] = {}
    nat = plan.get("nat") or []
    if not isinstance(nat, list):
        warnings.append(f"plan 'nat' must be a list of bursts, got {type(nat).__name__}; natural sound skipped")
        return out
    for k, b in enumerate(nat):
        where = f"nat[{k}]"
        if not isinstance(b, dict):
            warnings.append(f"{where}: must be an object; skipped")
            continue
        try:
            src, start, t, dur = b["src"], float(b["start"]), float(b["t"]), float(b["dur"])
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{where}: needs src, start, t and dur; skipped")
            continue
        gain = float(b.get("gain_db", NAT_DEFAULT_GAIN_DB))
        if not os.path.isabs(src) or not Path(src).is_file():
            warnings.append(f"{where}: clip not found ({src}); skipped")
            continue
        if src not in infos:
            infos[src] = nc.media_info(src)
        info = infos[src]
        if not info["has_audio"]:
            warnings.append(f"{where}: {Path(src).name} has no audio; skipped")
            continue
        if t >= duration:
            warnings.append(f"{where}: starts at {t:g} s, after the reel ends ({duration:.2f} s); skipped")
            continue
        clip_d = info["duration"] or 0.0
        avail = min(dur, duration - t, clip_d - start)
        if avail < 0.1:
            warnings.append(f"{where}: no clip audio at {start:g} s in {Path(src).name}; skipped")
            continue
        if avail < dur - 1e-3:
            warnings.append(f"{where}: shortened from {dur:g} s to {avail:.2f} s (reel or clip end)")
        out.append({"src": src, "start": start, "t": t, "dur": round(avail, 4), "gain_db": gain})
    return out


def audible(path: Path) -> bool:
    """True when the file has audio louder than SILENT_INPUT_LUFS integrated."""
    try:
        i = measure_audio(path)["integrated_lufs"]
    except nc.UserError:
        return False
    return i is not None and math.isfinite(i) and i >= SILENT_INPUT_LUFS


def pick_bed(work: Path, plan: dict | None, warnings: list[str]) -> tuple[str, list[str]]:
    """(kind, ffmpeg input args) for the audio bed."""
    master = work / "master.wav"
    why = "no master.wav"
    if master.is_file():
        if audible(master):
            return "master", ["-i", str(master)]
        why = "master.wav is silent"
    music = (plan or {}).get("music") or {}
    mpath = music.get("path") if isinstance(music, dict) else None
    if isinstance(mpath, str) and Path(mpath).is_file() and audible(Path(mpath)):
        warnings.append(f"{why}: using the plan's music file {Path(mpath).name}")
        return "music", ["-stream_loop", "-1", "-i", str(mpath)]
    pad = work / "pad.wav"
    if pad.is_file() and audible(pad):
        warnings.append(f"{why}: using the offline pad (work/pad.wav)")
        return "pad", ["-stream_loop", "-1", "-i", str(pad)]
    warnings.append(f"{why} and no usable music: using natural sound from the clips plus a soft generated pad")
    return "generated_pad", []


def voice_presence(analysis: dict | None, bed: str, warnings: list[str]) -> tuple[bool, str | None]:
    """(voice present?, voice file for ducking or None)."""
    if bed != "master":
        return False, None
    if analysis is None:
        warnings.append("no analysis.json: assuming the master holds a voice (voice chain on)")
        return True, None
    present = bool(analysis.get("voice_present"))
    audio = analysis.get("audio") or {}
    vfile = audio.get("voice") if isinstance(audio, dict) else None
    if present and vfile and not audio.get("combined") and Path(vfile).is_file():
        return True, vfile
    return present, None


# --------------------------------------------------------------------------- audio passes
def build_premix(bed: str, bed_args: list[str], voice: bool, duck_file: str | None,
                 bursts: list[dict], clean: bool, duration: float, out_wav: Path) -> None:
    """Bed (+ voice chain) + ducked natural sound + fades -> float WAV, exactly `duration` long."""
    d = f"{duration:.6f}"
    fmt = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"
    fit = f"asetpts=N/SR/TB,apad=whole_dur={d},atrim=end={d},asetpts=N/SR/TB"
    inputs: list[str] = []
    graph: list[str] = []
    if bed == "generated_pad":
        src, lp = pad_source(duration)
        inputs += ["-f", "lavfi", "-i", src]
        bed_pre = f"[0:a]{fmt},lowpass=f={lp}"
    else:
        inputs += bed_args
        bed_pre = f"[0:a]{fmt}"
    n_in = 1
    key = None
    if bursts and voice:
        if duck_file:
            inputs += ["-i", duck_file]
            graph.append(f"[{n_in}:a]{fmt},{fit}[key]")
            n_in += 1
            key = "[key]"
        else:
            bed_pre += ",asplit=2[bsrc][keyraw]"
            graph.append(f"[keyraw]{fit}[key]")
            key = "[key]"
    if bed_pre.endswith("[keyraw]"):
        graph.append(bed_pre)
        graph.append(f"[bsrc]{(voice_chain(clean) + ',') if voice else ''}{fit}[bed]")
    else:
        graph.append(f"{bed_pre},{(voice_chain(clean) + ',') if voice else ''}{fit}[bed]")

    labels = []
    for k, b in enumerate(bursts):
        inputs += ["-i", b["src"]]
        f = min(NAT_FADE_S, b["dur"] / 4)
        ms = int(round(b["t"] * 1000))
        graph.append(f"[{n_in}:a]{fmt},atrim=start={b['start']:.4f}:duration={b['dur']:.4f},asetpts=N/SR/TB,"
                     f"volume={b['gain_db']:g}dB,afade=t=in:d={f:.3f},afade=t=out:st={b['dur'] - f:.4f}:d={f:.3f},"
                     f"adelay=delays={ms}:all=1[n{k}]")
        labels.append(f"[n{k}]")
        n_in += 1
    if labels:
        mixed = labels[0] if len(labels) == 1 else None
        if mixed is None:
            graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[natm]")
            mixed = "[natm]"
        graph.append(f"{mixed}{fit}[nat]")
        if key:
            graph.append(f"[nat]{key}sidechaincompress={DUCK}[natd]")
            nat = "[natd]"
        else:
            nat = "[nat]"
        graph.append(f"[bed]{nat}amix=inputs=2:normalize=0:duration=first[mix]")
        last = "[mix]"
    else:
        last = "[bed]"
    graph.append(f"{last}afade=t=in:d={FADE_IN_S},"
                 f"afade=t=out:st={max(duration - FADE_OUT_S, 0):.4f}:d={min(FADE_OUT_S, duration):.4f}[out]")
    nc.ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", "[out]", "-t", d,
              "-c:a", "pcm_f32le", "-ar", str(SR), "-ac", "2", "-fflags", "+bitexact", str(out_wav),
              what="ffmpeg audio premix")


def _loudnorm_json(stderr: bytes) -> dict:
    text = stderr.decode("utf-8", "replace")
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, flags=re.S)
    if not m:
        raise nc.UserError("loudnorm did not report its measurements")
    return json.loads(m[-1])


def measure_pass(wav: Path, target: dict) -> dict:
    """Pass 1: {"input_i", "input_tp", "input_lra", ...} of the pre-mix (strings, as loudnorm prints them)."""
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(wav), "-af",
                   loudnorm_measure_filter(target), "-f", "null", "-"], what="ffmpeg loudnorm pass 1")
    return _loudnorm_json(proc.stderr)


def normalize_pass(wav: Path, gain_db: float | None, ceiling_db: float, out_wav: Path, duration: float) -> None:
    """Pass 2 -> 48 kHz WAV: linear gain + oversampled true-peak limiter (gain None = copy as is)."""
    common = ["-t", f"{duration:.6f}", "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", "-fflags", "+bitexact"]
    if gain_db is None:
        nc.ffmpeg("-i", str(wav), *common, str(out_wav), what="ffmpeg audio copy")
        return
    nc.ffmpeg("-i", str(wav), "-af", gain_limiter_filter(gain_db, ceiling_db), *common, str(out_wav),
              what="ffmpeg loudness pass 2")


def encode_audio(aud: Path, out_m4a: Path, duration: float, audio_cfg: dict) -> None:
    """AAC 192k 48 kHz stereo, bitexact (measured as is, then stream-copied into the final MP4)."""
    nc.ffmpeg("-i", str(aud), "-map", "0:a:0", "-c:a", "aac", "-b:a", str(audio_cfg.get("bitrate", "192k")),
              "-ar", str(audio_cfg.get("sample_rate", SR)), "-ac", str(audio_cfg.get("channels", 2)),
              "-t", f"{duration:.6f}", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
              "-f", "mp4", str(out_m4a), what="ffmpeg AAC encode")


def mux(video: Path, m4a: Path, out: Path, duration: float) -> None:
    """H.264 copy + the encoded AAC copy, +faststart, bitexact; written atomically."""
    tmp = out.with_name(f".{out.stem}.partial.mp4")
    try:
        nc.ffmpeg("-i", str(video), "-i", str(m4a), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                  "-t", f"{duration:.6f}", "-map_metadata", "-1", "-map_chapters", "-1",
                  "-fflags", "+bitexact", "-movflags", "+faststart", "-f", "mp4", str(tmp), what="ffmpeg mux")
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()


def qa_strip(video: Path, duration: float, out_path: Path) -> Path:
    from PIL import Image
    w, h = STRIP_TILE
    strip = Image.new("RGB", (w * len(STRIP_AT), h))
    for k, x in enumerate(STRIP_AT):
        strip.paste(grab_frame(video, duration * x, (w, h)), (w * k, 0))
    strip.save(out_path, quality=90)
    return out_path


# --------------------------------------------------------------------------- main
def finish(work: Path, out: Path, video: Path | None = None, plan_path: Path | None = None,
           clean: bool = False, qa: bool = True) -> dict[str, Any]:
    if not work.is_dir():
        raise nc.UserError(f"work folder not found: {work}")
    video = video or work / "video_noaudio.mp4"
    if not video.is_file():
        raise nc.UserError(f"rendered video not found: {video} (run engine.py first)")
    vinfo = nc.media_info(video)
    if not vinfo["has_video"]:
        raise nc.UserError(f"no video stream in {video}")
    duration = vinfo["duration"]
    if not duration or duration <= 0:
        raise nc.UserError(f"cannot read the length of {video}")
    cfg = nc.load_config()
    loud_cfg = nc.dig(cfg, "render.loudness", {}) or {}
    audio_cfg = nc.dig(cfg, "render.audio", {}) or {}
    target = {"i": float(loud_cfg.get("integrated_lufs", -15)), "tp": float(loud_cfg.get("true_peak_db", -1.5)),
              "lra": float(loud_cfg.get("lra", 9))}
    tol = float(loud_cfg.get("tolerance_lu", 1))
    warn_db = float(loud_cfg.get("mean_level_warn_db", -28))

    warnings: list[str] = []
    plan_path = plan_path or (work / "plan.json")
    plan = load_optional_json(plan_path, "plan")
    analysis = load_optional_json(work / "analysis.json", "analysis")
    bed, bed_args = pick_bed(work, plan, warnings)
    voice, duck_file = voice_presence(analysis, bed, warnings)
    bursts = plan_bursts(plan, duration, warnings)
    for w in warnings:
        nc.warn(w)

    out.parent.mkdir(parents=True, exist_ok=True)
    aud = work / "aud.wav"
    with tempfile.TemporaryDirectory(prefix="numa_finish_") as tmpd:
        pre = Path(tmpd) / "premix.wav"
        build_premix(bed, bed_args, voice, duck_file, bursts, clean, duration, pre)
        measured = measure_pass(pre, target)
        in_i = to_float(measured.get("input_i"))
        gain: float | None = None
        if in_i is None or in_i < -70:
            msg = "the audio is silent before normalization; left as is"
            warnings.append(msg)
            nc.warn(msg)
        else:
            gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, target["i"] - in_i))
        ceiling = target["tp"] - TP_HEADROOM_DB
        loud: dict[str, Any] = {}
        passes = 0
        prev: tuple[float, float, float] | None = None
        m4a = Path(tmpd) / "audio.m4a"
        for passes in range(1, MAX_PASSES + 1):
            used = (gain, ceiling)
            normalize_pass(pre, gain, ceiling, aud, duration)
            encode_audio(aud, m4a, duration, audio_cfg)
            loud = measure_audio(m4a)
            if gain is None:
                break
            i_now, tp_now = loud["integrated_lufs"], loud["true_peak_db"]
            tp_over = tp_now is not None and tp_now > target["tp"]
            i_off = i_now is not None and math.isfinite(i_now) and abs(i_now - target["i"]) > LUFS_SETTLE
            if not tp_over and not i_off:
                break
            if passes == MAX_PASSES:
                break
            if tp_over:
                ceiling = max(-24.0, ceiling - (tp_now - target["tp"]) - TP_MARGIN_DB)
            elif i_off and i_now < target["i"] and tp_now is not None and tp_now < target["tp"] - 1.5:
                # quiet and with peak headroom left: give some of it back to the limiter
                ceiling = min(target["tp"] - TP_MARGIN_DB, ceiling + (target["tp"] - tp_now) / 2)
            if i_off:
                # secant step: under heavy limiting 1 dB of gain buys less than 1 LU
                slope = 1.0
                if prev is not None and prev[2] == used[1] and abs(used[0] - prev[0]) > 0.05:
                    slope = min(1.0, max(0.25, (i_now - prev[1]) / (used[0] - prev[0])))
                prev = (used[0], i_now, used[1])
                gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain + (target["i"] - i_now) / slope))
            else:
                prev = None
            nc.info(f"loudness pass {passes}: {i_now:.2f} LUFS, true peak {tp_now:.2f} dB; "
                    f"gain {gain:+.2f} dB, limiter ceiling {ceiling:.2f} dB")
        mux(video, m4a, out, duration)
    loud = measure_audio(out)  # the delivered file, measured independently of the passes

    i_lufs, tp, mean = loud["integrated_lufs"], loud["true_peak_db"], loud["mean_db"]
    n_before = len(warnings)
    errors: list[str] = []
    if tp is not None and tp > target["tp"]:
        errors.append(f"true peak {tp:.1f} dB is above {target['tp']:g} dB")
    if i_lufs is None or not math.isfinite(i_lufs) or abs(i_lufs - target["i"]) > tol:
        shown = "silent" if i_lufs is None or not math.isfinite(i_lufs) else f"{i_lufs:.1f} LUFS"
        errors.append(f"integrated loudness {shown} is outside {target['i']:g} +/- {tol:g} LUFS")
    if mean is None or mean < warn_db:
        warnings.append(f"audio is very quiet: mean level {mean if mean is None else round(mean, 1)} dB "
                        f"is below {warn_db:g} dB")
    for w in warnings[n_before:]:
        nc.warn(w)
    strip = None
    if qa:
        strip = qa_strip(out, duration, out.parent / "qa_strip.jpg")

    section = {
        "output": str(out),
        "video": str(video),
        "duration": round(duration, 3),
        "size_mb": round(out.stat().st_size / 1e6, 2),
        "audio_bed": bed,
        "voice_chain": voice,
        "clean_voice": clean,
        "chain": mastering_filters(voice, clean, duration, target, gain, ceiling),
        "normalization": "none" if gain is None else "linear gain + true-peak limiter",
        "gain_db": None if gain is None else round(gain, 2),
        "true_peak_ceiling_db": round(ceiling, 2),
        "passes": passes,
        "loudness": json_safe({k: loud[k] for k in ("integrated_lufs", "true_peak_db", "lra", "mean_db")}),
        "nat_bursts": len(bursts),
        "qa_strip": str(strip) if strip else None,
        "warnings": warnings,
        "errors": errors,
        "ok": not errors,
    }
    nc.update_report(out.parent, "finish", section)
    return section


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="finish.py", description="Master audio, mix natural sound, mux, measure, QA strip.")
    ap.add_argument("work", help="the job's work folder (master.wav, video_noaudio.mp4, plan.json)")
    ap.add_argument("output", help="final MP4 to write")
    ap.add_argument("--video", help="rendered video (default WORK/video_noaudio.mp4)")
    ap.add_argument("--plan", help="plan.json for natural-sound bursts and music (default WORK/plan.json)")
    ap.add_argument("--clean-voice", action="store_true", help="no room echo on the voice")
    ap.add_argument("--no-qa", action="store_true", help="skip qa_strip.jpg")
    ap.add_argument("--json", action="store_true", help="print the finish report as JSON")
    args = ap.parse_args(argv)
    work = Path(args.work).expanduser().resolve()
    out = Path(args.output).expanduser().resolve()
    if out.suffix.lower() != ".mp4":
        raise nc.UsageError(f"OUTPUT_MP4 must end in .mp4: {out}")
    section = finish(work, out,
                     Path(args.video).expanduser().resolve() if args.video else None,
                     Path(args.plan).expanduser().resolve() if args.plan else None,
                     clean=args.clean_voice, qa=not args.no_qa)
    lo = section["loudness"]

    def show(v, unit):
        return "n/a" if v is None else f"{v} {unit}"

    for e in section["errors"]:
        nc.error_line(f"{out.name}: {e}")
    if args.json:
        nc.print_json(section)
    else:
        print(f"{'OK' if section['ok'] else 'FAIL'} {out}  duration {section['duration']:.1f}s  "
              f"size {section['size_mb']} MB  loudness {show(lo['integrated_lufs'], 'LUFS')}  "
              f"true peak {show(lo['true_peak_db'], 'dB')}  LRA {show(lo['lra'], 'LU')}  "
              f"mean {show(lo['mean_db'], 'dB')}  nat bursts {section['nat_bursts']}")
    return 0 if section["ok"] else 1

if __name__ == "__main__":
    nc.run_cli(main)
