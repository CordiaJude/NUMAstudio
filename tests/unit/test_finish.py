"""finish.py: voice chain, two-pass loudness, natural sound, mux spec, determinism, fallbacks (R37-R40, R284, R291, R292, R297)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import numa_common
import finish

FF = numa_common.ffmpeg_bin()
DUR = 4.0


def ff(*args):
    subprocess.run([FF, "-hide_banner", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True)


def make_video(path: Path, seconds=DUR, size=(1080, 1920)):
    ff("-f", "lavfi", "-i", f"testsrc2=size={size[0]}x{size[1]}:rate=30:duration={seconds}",
       "-c:v", "libx264", "-profile:v", "high", "-preset", "superfast", "-crf", "30", "-pix_fmt", "yuv420p", path)
    return path


def lavfi_audio(path: Path, src: str):
    ff("-f", "lavfi", "-i", src, "-ac", "2", "-ar", "48000", path)
    return path


VOICE = "aevalsrc='0.5*sin(2*PI*(180+40*sin(2*PI*3*t))*t)*gt(sin(2*PI*1.7*t),-0.3)':s=48000:d={d}"
MUSIC = ("aevalsrc='0.15*sin(2*PI*220*t)+0.1*sin(2*PI*277*t)+0.1*sin(2*PI*330*t)"
         "+0.6*exp(-30*mod(t,0.6))*sin(2*PI*60*t)':s=48000:d={d}")


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """Shared synthetic material: rendered video, voice, music, master mix and a clip with pink-noise sound."""
    root = tmp_path_factory.mktemp("finish_media")
    video = make_video(root / "video_noaudio.mp4")
    voice = lavfi_audio(root / "voice.wav", VOICE.format(d=DUR))
    music = lavfi_audio(root / "music.wav", MUSIC.format(d=DUR))
    master = root / "master.wav"
    ff("-i", voice, "-i", music, "-filter_complex", "[1]volume=-14dB[m];[0][m]amix=inputs=2:normalize=0",
       "-ar", "48000", "-ac", "2", master)
    clip = root / "clip.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=size=160x284:rate=30:duration=3", "-f", "lavfi",
       "-i", "anoisesrc=color=pink:amplitude=0.6:seed=7:d=3:r=48000", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", clip)
    return {"video": video, "voice": voice, "music": music, "master": master, "clip": clip}


def make_job(root: Path, media, *, master=True, voice=True, nat=True, music_path=True, analysis=True):
    work = root / "work"
    work.mkdir(parents=True)
    shutil.copy(media["video"], work / "video_noaudio.mp4")
    if master:
        shutil.copy(media["master"], work / "master.wav")
    plan = {
        "schema_version": 2, "duration": DUR, "out_dir": str(work),
        "shots": [{"src": str(media["clip"]), "kind": "video", "t0": 0.0, "t1": 2.0, "tr": "cut"},
                  {"src": str(media["clip"]), "kind": "video", "t0": 2.0, "t1": DUR, "tr": "punch"}],
        "nat": [{"src": str(media["clip"]), "start": 0.5, "t": 1.5, "dur": 1.0, "gain_db": 0}] if nat else [],
        "music": {"source": "folder", "path": str(media["music"]) if music_path else None, "license": "test"},
    }
    (work / "plan.json").write_text(json.dumps(plan))
    if analysis:
        (work / "analysis.json").write_text(json.dumps({
            "schema_version": 2, "duration": DUR, "bpm": None, "beats": [], "words": [], "transcript": "",
            "voice_present": voice,
            "audio": {"voice": str(media["voice"]) if voice else None, "music": str(media["music"]),
                      "master": str(work / "master.wav") if master else None},
            "photos": [], "clips": []}))
    return work


def ebur128(path: Path) -> tuple[float, float]:
    """Independent measurement: integrated LUFS and true peak with ffmpeg ebur128."""
    p = subprocess.run([FF, "-hide_banner", "-nostdin", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    s = p.stderr[p.stderr.rfind("Summary:"):]
    return (float(re.search(r"I:\s*(-?[\d.]+) LUFS", s).group(1)),
            float(re.search(r"Peak:\s*(-?[\d.]+) dBFS", s).group(1)))


def pcm(path: Path, af: str = "anull") -> np.ndarray:
    p = subprocess.run([FF, "-v", "error", "-i", str(path), "-af", af, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def rms(x: np.ndarray, t0: float, t1: float) -> float:
    seg = x[int(t0 * 48000):int(t1 * 48000)]
    return float(np.sqrt(np.mean(seg.astype(np.float64) ** 2)))


def probe(path: Path) -> dict:
    out = subprocess.run([numa_common.ffprobe_bin() or "ffprobe", "-v", "error", "-show_streams", "-show_format",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def finished(media, tmp_path_factory):
    root = tmp_path_factory.mktemp("finished")
    work = make_job(root, media)
    out = root / "out" / "test_reel.mp4"
    (root / "out").mkdir()
    numa_common.write_json(root / "out" / "report.json", {"schema_version": 1, "formats": {"files": []}})
    proc = subprocess.run([sys.executable, str(Path(finish.__file__)), str(work), str(out), "--json"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return {"root": root, "work": work, "out": out, "report": json.loads(proc.stdout), "stderr": proc.stderr}


# --------------------------------------------------------------------------- chain (R37)
def test_voice_chain_has_every_stage():
    chain = finish.voice_chain()
    for stage in ("highpass=f=85", "equalizer=f=180", "g=-2.5", "equalizer=f=3800", "g=-4", "equalizer=f=7000",
                  "lowpass=f=11000", "aecho=", "acompressor=", "ratio=2"):
        assert stage in chain
    assert "aecho" not in finish.voice_chain(clean=True)
    full = finish.mastering_filters(True, False, 30.0, {"i": -15, "tp": -1.5, "lra": 9})
    assert "loudnorm=I=-15:TP=-1.5" in full and "aresample=48000" in full and "afade=t=out" in full
    assert "highpass" not in finish.mastering_filters(False, False, 30.0, {"i": -15, "tp": -1.5, "lra": 9})


def test_pass_two_is_linear_gain_plus_oversampled_limiter():
    f = finish.gain_limiter_filter(7.5, -2.0)
    assert f.startswith("volume=7.500dB,aresample=192000,alimiter=limit=0.794328")
    assert "level=false" in f and f.endswith("aresample=48000")
    assert "loudnorm=I=-15:TP=-1.5" in finish.loudnorm_measure_filter({"i": -15, "tp": -1.5, "lra": 9})


# --------------------------------------------------------------------------- output (R38, R39, R40, R291, R292)
def test_output_spec_by_ffprobe(finished):
    data = probe(finished["out"])
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next(s for s in data["streams"] if s["codec_type"] == "audio")
    assert "mp4" in data["format"]["format_name"]
    assert (v["codec_name"], v["profile"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == \
        ("h264", "High", 1080, 1920, "yuv420p", "30/1")
    assert (a["codec_name"], a["sample_rate"], a["channels"]) == ("aac", "48000", 2)
    assert 150_000 < int(a["bit_rate"]) < 230_000
    assert abs(float(data["format"]["duration"]) - DUR) < 0.1
    blob = finished["out"].read_bytes()
    assert blob.find(b"moov") < blob.find(b"mdat"), "moov must come before mdat (+faststart)"
    assert finished["out"].stat().st_size < 100e6


def test_loudness_measured_independently(finished):
    i_lufs, tp = ebur128(finished["out"])
    assert abs(i_lufs - (-15)) <= 1.0
    assert tp <= -1.5
    lo = finished["report"]["loudness"]
    assert abs(lo["integrated_lufs"] - i_lufs) < 0.2 and set(lo) == {"integrated_lufs", "true_peak_db", "lra", "mean_db"}


def test_aud_wav_and_qa_strip_and_report(finished):
    from PIL import Image
    assert numa_common.media_info(finished["work"] / "aud.wav")["sample_rate"] == 48000
    with Image.open(finished["out"].parent / "qa_strip.jpg") as im:
        assert im.size == (1620, 480)
    report = json.loads((finished["out"].parent / "report.json").read_text())
    assert report["formats"] == {"files": []}, "other sections must survive"
    sec = report["finish"]
    assert sec["output"] == str(finished["out"]) and sec["nat_bursts"] == 1 and sec["voice_chain"] is True
    assert sec["normalization"] == "linear gain + true-peak limiter" and sec["ok"] and sec["errors"] == []


def test_byte_identical_reruns(finished, tmp_path):
    out2 = tmp_path / "again.mp4"
    finish.main([str(finished["work"]), str(out2), "--no-qa"])
    assert hashlib.sha256(out2.read_bytes()).hexdigest() == hashlib.sha256(finished["out"].read_bytes()).hexdigest()


# --------------------------------------------------------------------------- natural sound (R284)
def test_nat_burst_audible_at_its_time(finished, media, tmp_path):
    work = make_job(tmp_path, media, nat=False)
    plain = tmp_path / "plain.mp4"
    finish.main([str(work), str(plain), "--no-qa"])
    # the clip's pink noise is the only content above 3 kHz (voice and music are low tones)
    hp = "highpass=f=3000:poles=2,highpass=f=3000:poles=2"
    with_nat, without = pcm(finished["out"], hp), pcm(plain, hp)
    # the burst plays 1.5-2.5 s; normalize by a window before it (0.2-1.3 s) since loudnorm rescales each mix
    ratio_with = rms(with_nat, 1.6, 2.4) / rms(with_nat, 0.2, 1.3)
    ratio_without = rms(without, 1.6, 2.4) / rms(without, 0.2, 1.3)
    assert ratio_with > 3 * ratio_without, (ratio_with, ratio_without)
    full = pcm(finished["out"])
    assert rms(full, 1.6, 2.4) > rms(full, 0.2, 1.3) * 1.15, "burst raises the overall level too"


def test_nat_bad_entries_are_warnings(media, tmp_path):
    warnings: list[str] = []
    plan = {"nat": [{"src": "/nope/clip.mp4", "start": 0, "t": 1, "dur": 1},
                    {"src": str(media["clip"]), "start": 0, "t": 99, "dur": 1},
                    {"src": str(media["clip"]), "start": 2.5, "t": 1, "dur": 2}]}
    bursts = finish.plan_bursts(plan, DUR, warnings)
    assert len(bursts) == 1 and bursts[0]["dur"] == pytest.approx(0.5, abs=0.05)
    assert len(warnings) == 3


# --------------------------------------------------------------------------- music-only and fallbacks
def test_music_only_gets_no_voice_eq(media, tmp_path):
    work = make_job(tmp_path, media, voice=False, nat=False)
    sec = finish.finish(work, tmp_path / "out" / "m.mp4", qa=False)
    assert sec["voice_chain"] is False and "highpass" not in sec["chain"]


@pytest.mark.parametrize("music_path,bed", [(True, "music"), (False, "generated_pad")])
def test_no_master_falls_back_and_is_never_silent(media, tmp_path, music_path, bed):
    work = make_job(tmp_path, media, master=False, nat=True, music_path=music_path, analysis=False)
    out = tmp_path / "out" / "fb.mp4"
    sec = finish.finish(work, out, qa=False)
    assert sec["audio_bed"] == bed and sec["voice_chain"] is False
    i_lufs, tp = ebur128(out)
    assert abs(i_lufs + 15) <= 1.0 and tp <= -1.5
    assert any("pad" in w or "music file" in w for w in sec["warnings"])


def fake_final(monkeypatch, **override):
    """Make finish's measurement of the delivered .mp4 report other numbers (passes stay real)."""
    real = finish.measure_audio
    calls: list[str] = []

    def fake(path):
        res = real(path)
        calls.append(Path(path).suffix)
        return dict(res, **override) if Path(path).suffix == ".mp4" else res

    monkeypatch.setattr(finish, "measure_audio", fake)
    return calls


def test_quiet_output_warns(media, tmp_path, monkeypatch, capsys):
    fake_final(monkeypatch, mean_db=-33.0)
    work = make_job(tmp_path, media, nat=False)
    assert finish.main([str(work), str(tmp_path / "q.mp4"), "--no-qa"]) == 0
    assert re.search(r"WARN: .*very quiet: mean level -33.0 dB", capsys.readouterr().err)


def test_out_of_spec_result_is_an_error(media, tmp_path, monkeypatch, capsys):
    fake_final(monkeypatch, integrated_lufs=-21.9, true_peak_db=-0.5)
    work = make_job(tmp_path, media, nat=False)
    assert finish.main([str(work), str(tmp_path / "e.mp4"), "--no-qa"]) == 1
    cap = capsys.readouterr()
    assert "ERROR: e.mp4: true peak -0.5 dB" in cap.err and "ERROR: e.mp4: integrated loudness -21.9 LUFS" in cap.err
    assert cap.out.startswith("FAIL")
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["finish"]["ok"] is False and len(report["finish"]["errors"]) == 2


def test_silent_master_falls_back(media, tmp_path):
    work = make_job(tmp_path, media, nat=False, music_path=False)
    ff("-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={DUR}", work / "master.wav")
    out = tmp_path / "out" / "s.mp4"
    sec = finish.finish(work, out, qa=False)
    assert sec["audio_bed"] == "generated_pad" and sec["ok"]
    assert any("master.wav is silent (peak below -80 dBFS)" in w for w in sec["warnings"])
    i_lufs, tp = ebur128(out)
    assert abs(i_lufs + 15) <= 1.0 and tp <= -1.5


@pytest.mark.parametrize("src,codec", [
    # high crest: sparse full-scale clicks over a quiet tone (needs gain + limiting)
    ("aevalsrc='0.01*sin(2*PI*220*t)+0.98*lt(mod(t,0.5),0.003)*sin(2*PI*2500*t)':s=48000:d={d}", "pcm_s16le"),
    # pre-mix far above 0 LUFS (float WAV beyond full scale)
    ("aevalsrc='4*sgn(sin(2*PI*110*t))':s=48000:d={d}", "pcm_f32le"),
])
def test_extreme_inputs_still_meet_spec(media, tmp_path, src, codec):
    work = make_job(tmp_path, media, nat=False, voice=False)
    ff("-f", "lavfi", "-i", src.format(d=DUR), "-ac", "2", "-c:a", codec, work / "master.wav")
    out = tmp_path / "out" / "x.mp4"
    sec = finish.finish(work, out, qa=False)
    i_lufs, tp = ebur128(out)
    assert abs(i_lufs + 15) <= 1.0 and tp <= -1.5, (i_lufs, tp, sec)
    assert sec["ok"]


def test_very_quiet_master_is_normalized_not_replaced(media, tmp_path):
    work = make_job(tmp_path, media, nat=False, voice=False)
    # about -68 LUFS, peak about -57 dBFS: below loudnorm's -70 LUFS gate after EQ, but a real recording
    ff("-f", "lavfi", "-i", f"aevalsrc='0.0014*sin(2*PI*220*t)':s=48000:d={DUR}", "-ac", "2", work / "master.wav")
    out = tmp_path / "out" / "quiet.mp4"
    sec = finish.finish(work, out, qa=False)
    assert sec["audio_bed"] == "master" and sec["ok"]
    i_lufs, tp = ebur128(out)
    assert abs(i_lufs + 15) <= 1.0 and tp <= -1.5


def test_true_peak_over_limit_is_corrected(media, tmp_path, monkeypatch):
    real = finish.measure_audio
    encoded = []

    def fake(path):
        res = real(path)
        if Path(path).suffix == ".m4a":
            encoded.append(res)
            if len(encoded) == 1:
                res = dict(res, true_peak_db=-0.8)  # pretend the AAC encode overshot
        return res

    monkeypatch.setattr(finish, "measure_audio", fake)
    work = make_job(tmp_path, media, nat=False)
    sec = finish.finish(work, tmp_path / "out" / "tp.mp4", qa=False)
    assert len(encoded) == 2 and sec["passes"] == 2
    assert sec["true_peak_ceiling_db"] < -1.5 - finish.TP_HEADROOM_DB and sec["ok"]


def test_non_list_nat_is_a_warning():
    warnings: list[str] = []
    assert finish.plan_bursts({"nat": "splash"}, DUR, warnings) == []
    assert len(warnings) == 1 and "must be a list" in warnings[0]
    warnings.clear()
    assert finish.plan_bursts({"nat": [5]}, DUR, warnings) == [] and "must be an object" in warnings[0]


# --------------------------------------------------------------------------- CLI errors
def test_cli_errors(tmp_path, run_script):
    r = run_script("finish.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    (tmp_path / "work").mkdir()
    r = run_script("finish.py", tmp_path / "work", tmp_path / "o.mp4")
    assert r.returncode == 1 and "ERROR: rendered video not found" in r.stderr and "Traceback" not in r.stderr


def scripted_passes(monkeypatch, values):
    """Each AAC pass measures as the next (integrated_lufs, true_peak_db) in `values`."""
    real = finish.measure_audio
    encoded: list[dict] = []

    def fake(path):
        res = real(path)
        if Path(path).suffix == ".m4a":
            i, tp = values[min(len(encoded), len(values) - 1)]
            res = dict(res, integrated_lufs=i, true_peak_db=tp)
            encoded.append(res)
        return res

    monkeypatch.setattr(finish, "measure_audio", fake)
    return encoded


def test_loudness_stops_on_first_in_spec_pass(media, tmp_path, monkeypatch, capsys):
    encoded = scripted_passes(monkeypatch, [(-15.4, -2.0), (-15.0, -2.0)])
    work = make_job(tmp_path, media, nat=False)
    sec = finish.finish(work, tmp_path / "out" / "a.mp4", qa=False)
    assert len(encoded) == 1 and sec["passes"] == 1 and sec["delivered_pass"] == 1
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["finish"]["delivered_pass"] == 1
    # the log line shows what pass 1 used and measured
    logs = capsys.readouterr()
    line = (f"loudness pass 1: gain {sec['gain_db']:+.2f} dB, limiter ceiling "
            f"{-1.5 - finish.TP_HEADROOM_DB:.2f} dB -> -15.40 LUFS, true peak -2.00 dB")
    assert line in logs.out + logs.err
    assert "loudness pass 2" not in logs.out + logs.err


def test_loudness_stops_after_two_passes_without_improvement(media, tmp_path, monkeypatch, capsys):
    # pass 2 is the closest (0.8 LU off, inside tolerance but outside the 0.5 LU spec);
    # passes 3 and 4 do not beat it, so the loop stops and delivers pass 2
    encoded = scripted_passes(monkeypatch, [(-16.2, -3.0), (-15.8, -3.0), (-15.9, -3.0), (-16.0, -3.0)])
    work = make_job(tmp_path, media, nat=False)
    sec = finish.finish(work, tmp_path / "out" / "b.mp4", qa=False)
    assert len(encoded) == 4 and sec["passes"] == 4 and sec["delivered_pass"] == 2
    logs = capsys.readouterr()
    text = logs.out + logs.err
    lines = re.findall(r"loudness pass (\d): gain ([+-]\d+\.\d\d) dB, limiter ceiling (-?\d+\.\d\d) dB -> "
                       r"(-?\d+\.\d\d) LUFS, true peak (-?\d+\.\d\d) dB", text)
    assert [(n, i, tp) for n, _, _, i, tp in lines] == [
        ("1", "-16.20", "-3.00"), ("2", "-15.80", "-3.00"), ("3", "-15.90", "-3.00"), ("4", "-16.00", "-3.00")]
    # the reported gain is the one pass 2 used, as its own log line shows
    assert f"{sec['gain_db']:+.2f}" == lines[1][1]
    assert "using loudness pass 2" in text
