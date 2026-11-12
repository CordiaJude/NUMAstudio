"""qa_frames.py: the Critic's 12 frames (R207, interpretation 13)."""
from __future__ import annotations

import json
import subprocess

import pytest

import numa_common
import qa_frames


def plan_with_cuts(n_shots: int, duration: float, trs=("cut", "punch", "whip", "flash", "fade", "wipe")):
    step = duration / n_shots
    shots = [{"src": "/x.jpg", "t0": round(i * step, 3), "t1": round((i + 1) * step, 3), "tr": trs[i % len(trs)]}
             for i in range(n_shots)]
    shots[0]["tr"] = "cut"
    shots[-1]["t1"] = duration
    return {"duration": duration, "shots": shots}


def test_more_cuts_than_slots_is_even_and_keeps_first_and_last():
    plan = plan_with_cuts(25, 50.0)  # 24 cuts, 10 slots
    sel = qa_frames.select_times(plan, 50.0, 12)
    assert len(sel) == 12
    assert sel[0] == {"t": 0.0, "why": "first second"} and sel[-1]["why"] == "last second"
    assert sel[-1]["t"] == pytest.approx(49.5)
    cuts = [s for s in sel if s["why"].startswith("cut")]
    assert len(cuts) == 10
    assert cuts[0]["why"].startswith("cut 1 ") and cuts[-1]["why"].startswith("cut 24 ")
    assert sel == qa_frames.select_times(plan, 50.0, 12), "deterministic"
    assert [s["t"] for s in sel] == sorted(s["t"] for s in sel)


def test_cut_frames_are_past_the_transition():
    plan = plan_with_cuts(4, 12.0, trs=("cut", "punch", "fade", "wipe"))
    sel = {s["why"]: s["t"] for s in qa_frames.select_times(plan, 12.0, 12)}
    assert sel["cut 1 (punch)"] == pytest.approx(3.3)
    assert sel["cut 2 (fade)"] == pytest.approx(6.55)
    assert sel["cut 3 (wipe)"] == pytest.approx(10.05)


def test_few_cuts_still_give_count_frames_spread_out():
    plan = plan_with_cuts(3, 10.0)
    sel = qa_frames.select_times(plan, 10.0, 12)
    ts = [s["t"] for s in sel]
    assert len(sel) == 12 and len(set(ts)) == 12
    assert min(b - a for a, b in zip(ts, ts[1:])) >= qa_frames.MIN_GAP_S
    assert max(ts) == pytest.approx(9.5) and sel[-1]["why"] == "last second"


def test_last_second_stays_last_after_a_late_cut():
    plan = {"duration": 10.0, "shots": [{"t0": 0.0, "t1": 9.2, "tr": "cut"}, {"t0": 9.2, "t1": 10.0, "tr": "fade"}]}
    sel = qa_frames.select_times(plan, 10.0, 12)
    assert sel[-1] == {"t": 9.5, "why": "last second"}
    cut = next(s for s in sel if s["why"].startswith("cut 1"))
    assert 9.2 < cut["t"] <= 9.5 - qa_frames.MIN_GAP_S
    # a cut too close to the end to show apart from the last-second frame is dropped
    late = {"duration": 10.0, "shots": [{"t0": 0.0, "t1": 9.4, "tr": "cut"}, {"t0": 9.4, "t1": 10.0, "tr": "punch"}]}
    sel = qa_frames.select_times(late, 10.0, 12)
    assert not any(s["why"].startswith("cut") for s in sel)
    ts = [s["t"] for s in sel]
    assert min(b - a for a, b in zip(ts, ts[1:])) >= qa_frames.MIN_GAP_S
    assert [s["t"] for s in sel] == sorted(s["t"] for s in sel)


def test_count_below_two_is_a_usage_error():
    with pytest.raises(numa_common.UsageError):
        qa_frames.select_times(plan_with_cuts(2, 4.0), 4.0, 1)


def test_cli_writes_frames_and_index(tmp_path, run_script):
    video = tmp_path / "out" / "reel.mp4"
    video.parent.mkdir()
    subprocess.run([numa_common.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=216x384:rate=30:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(plan_with_cuts(4, 6.0)))
    stale = video.parent / "critic_frames" / "frame_40.jpg"
    stale.parent.mkdir()
    stale.write_bytes(b"old")
    r = run_script("qa_frames.py", video, plan)
    assert r.returncode == 0, r.stderr
    out = video.parent / "critic_frames"
    index = json.loads((out / "index.json").read_text())
    assert len(index) == 12 and [e["file"] for e in index] == [f"frame_{i:02d}.jpg" for i in range(1, 13)]
    assert sorted(p.name for p in out.glob("frame_*.jpg")) == [e["file"] for e in index]
    assert index[0]["why"] == "first second" and index[-1]["why"] == "last second"
    assert sum(e["why"].startswith("cut") for e in index) == 3
    from PIL import Image
    with Image.open(out / "frame_05.jpg") as im:
        assert im.size == (216, 384)
    report = json.loads((video.parent / "report.json").read_text())
    assert report["qa_frames"] == {"dir": str(out), "count": 12}
    r = run_script("qa_frames.py", video, plan, "--count", "5", "--out", tmp_path / "five")
    assert r.returncode == 0 and len(json.loads((tmp_path / "five" / "index.json").read_text())) == 5


def test_cli_errors(tmp_path, run_script):
    assert run_script("qa_frames.py").returncode == 2
    r = run_script("qa_frames.py", tmp_path / "none.mp4", tmp_path / "plan.json")
    assert r.returncode == 1 and r.stderr.startswith("ERROR:")
