"""check_output.py: every output-spec item, black bars and frozen frames (R209, R291, R292)."""
from __future__ import annotations

import json
import subprocess

import pytest

import numa_common
import check_output
import finish

FF = numa_common.ffmpeg_bin()
DUR = 3


def ff(*args):
    subprocess.run([FF, "-hide_banner", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True)


def h264(*extra):
    return ["-c:v", "libx264", "-profile:v", "high", "-preset", "superfast", "-crf", "30", "-pix_fmt", "yuv420p", *extra]


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    """A spec-compliant 4 s file (made by finish.py) plus one fixture per violation."""
    root = tmp_path_factory.mktemp("check")
    work = root / "work"
    work.mkdir()
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={DUR}", *h264(), work / "video_noaudio.mp4")
    ff("-f", "lavfi", "-i", f"aevalsrc='0.3*sin(2*PI*220*t)+0.2*sin(2*PI*330*t)*sin(2*PI*0.5*t)':s=48000:d={DUR}",
       "-ac", "2", work / "master.wav")
    good = root / "good.mp4"
    finish.finish(work, good, qa=False)
    f = {"good": good}
    aud = ["-map", "1:a", "-c:a", "copy", "-movflags", "+faststart"]
    f["rate441"] = root / "rate441.mp4"
    ff("-i", good, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
       "-movflags", "+faststart", f["rate441"])
    f["landscape"] = root / "landscape.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={DUR}", "-i", good, "-map", "0:v",
       *h264(), *aud, f["landscape"])
    f["no_faststart"] = root / "no_faststart.mp4"
    ff("-i", good, "-c", "copy", f["no_faststart"])
    f["silent"] = root / "silent.mp4"
    ff("-i", good, "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={DUR}", "-map", "0:v", "-map", "1:a",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", f["silent"])
    f["letterbox"] = root / "letterbox.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1500:rate=30:duration={DUR}", "-i", good, "-map", "0:v",
       "-vf", "pad=1080:1920:0:210:black", *h264(), *aud, f["letterbox"])
    f["graded_bars"] = root / "graded_bars.mp4"  # lifted, grainy "black" (luma ~22) letterbox
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1500:rate=30:duration={DUR}", "-i", good, "-map", "0:v",
       "-vf", "pad=1080:1920:0:210:color=0x161616,noise=alls=6:allf=t", *h264(), *aud, f["graded_bars"])
    f["dark_top"] = root / "dark_top.mp4"  # a dark, flat region on one side only: picture, not a bar
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1440:rate=30:duration={DUR}", "-i", good, "-map", "0:v",
       "-vf", "pad=1080:1920:0:480:color=0x080808", *h264(), *aud, f["dark_top"])
    f["top_bar"] = root / "top_bar.mp4"  # crop/pan overshoot: an 11 % strip on one edge only
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1708:rate=30:duration={DUR}", "-i", good, "-map", "0:v",
       "-vf", "pad=1080:1920:0:212:color=0x101010", *h264(), *aud, f["top_bar"])
    f["frozen"] = root / "frozen.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={DUR},loop=loop=45:size=1:start=15",
       "-i", good, "-map", "0:v", "-t", str(DUR), *h264(), *aud, f["frozen"])
    return f


def errors_of(path, **kw):
    return check_output.check_file(path, kw.pop("kind", "story"), **kw)["errors"]


def test_good_file_passes(files):
    res = check_output.check_file(files["good"], "story")
    assert res["ok"], res["errors"]
    assert res["probe"]["faststart"] and res["probe"]["sample_rate"] == 48000
    assert abs(res["loudness"]["integrated_lufs"] + 15) <= 1 and res["loudness"]["true_peak_db"] <= -1.5


def test_good_file_passes_without_ffprobe(files, monkeypatch):
    monkeypatch.setattr(numa_common, "ffprobe_bin", lambda: None)
    res = check_output.check_file(files["good"], "story")
    assert res["ok"], res["errors"]


def test_reel_length_rule(files):
    errs = errors_of(files["good"], kind="reel")
    assert len(errs) == 1 and "length" in errs[0] and "15-60" in errs[0]


@pytest.mark.parametrize("name,needle", [
    ("rate441", "sample rate: 44100"),
    ("landscape", "video size: 1920x1080"),
    ("no_faststart", "faststart"),
    ("silent", "silent"),
    ("letterbox", "letterbox"),
    ("graded_bars", "letterbox"),
    ("top_bar", "black bar on the top edge"),
    ("frozen", "frozen frame"),
])
def test_each_violation_is_caught(files, name, needle):
    errs = errors_of(files[name])
    assert any(needle in e for e in errs), errs


def test_landscape_passes_with_matching_size(files):
    errs = errors_of(files["landscape"], size=(1920, 1080))
    assert not any("video size" in e for e in errs)


def test_endcard_hold_is_exempt_from_freeze(files, tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"duration": DUR, "shots": [], "endcard": {"t": 0.4}}))
    assert not any("frozen" in e for e in errors_of(files["frozen"], plan=plan))


def test_dark_region_on_one_side_is_not_a_bar(files):
    assert not any("bar" in e for e in errors_of(files["dark_top"]))


def test_bar_sizes_on_synthetic_frames():
    import numpy as np
    rng = np.random.default_rng(0)
    frame = rng.uniform(40, 220, size=(480, 270)).astype(np.float32)  # busy picture
    frame[:30] = 22 + rng.normal(0, 1.5, size=(30, 270))                # graded, grainy bars
    frame[-30:] = 22 + rng.normal(0, 1.5, size=(30, 270))
    s = check_output.bar_sizes(frame)
    assert s["top"][0] == pytest.approx(30 / 480) and s["bottom"][0] == pytest.approx(30 / 480)
    assert s["left"][0] == 0
    textured = frame.copy()
    textured[:30] = np.tile([0, 40], (30, 135))  # dark but textured: not a bar
    assert check_output.bar_sizes(textured)["top"][0] == 0
    ramp = frame.copy()
    ramp[:60] = np.linspace(2, 38, 60)[:, None]  # a soft gradient into the picture: not uniform
    assert check_output.bar_sizes(ramp)["top"][0] < 0.02


def test_mp4_box_order(files):
    assert check_output.mp4_top_boxes(files["good"])[:2] == ["ftyp", "moov"]
    boxes = check_output.mp4_top_boxes(files["no_faststart"])
    assert boxes.index("mdat") < boxes.index("moov")


def test_cli_json_report_and_exit_codes(files, tmp_path, run_script):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    numa_common.write_json(out_dir / "report.json", {"schema_version": 1, "finish": {"x": 1}})
    r = run_script("check_output.py", files["good"], "--kind", "story", "--json", "--report", out_dir)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["ok"] and data["errors"] == []
    r = run_script("check_output.py", files["rate441"], "--kind", "story", "--report", out_dir)
    assert r.returncode == 1
    lines = [ln for ln in r.stderr.splitlines() if ln.startswith("ERROR:")]
    assert lines and all("rate441.mp4" in ln for ln in lines)
    report = json.loads((out_dir / "report.json").read_text())
    assert report["finish"] == {"x": 1}
    assert report["check_output"]["good.mp4"]["ok"] and not report["check_output"]["rate441.mp4"]["ok"]
    assert run_script("check_output.py").returncode == 2
    r = run_script("check_output.py", tmp_path / "missing.mp4")
    assert r.returncode == 1 and r.stderr.startswith("ERROR:")
