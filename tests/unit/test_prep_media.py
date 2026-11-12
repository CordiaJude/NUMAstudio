"""Unit tests for scripts/prep_media.py (R287 stabilize/brighten, D13).

Fixtures: a seeded random-walk crop of a bundled brand photo (shaky), a darkened
still clip and a darkened photo, all with audio where it matters.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import analyze as an
import numa_common
import prep_media as pm
import vision

BRAND = Path(numa_common.BRAND_PHOTOS_DIR)


def ffmpeg(*args, data: bytes | None = None) -> None:
    subprocess.run([numa_common.ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", *map(str, args)],
                   input=data, check=True)


def walk_clip(path: Path, *, amp: float, seconds: float = 3.0, fps: int = 30, size=(240, 426), seed: int = 11) -> Path:
    W, H = size
    with Image.open(BRAND / "breathwork-class.jpg") as im:
        big = np.asarray(im.convert("RGB").resize((int(H * 1.35 * im.width / im.height), int(H * 1.35))))
    Hb, Wb = big.shape[:2]
    n = int(seconds * fps)
    rng = np.random.default_rng(seed)
    pos = np.cumsum(rng.normal(0.0, amp, (n, 2)) * [W, H], axis=0)
    pos -= pos.mean(axis=0)
    pos = np.clip(pos + [(Wb - W) / 2, (Hb - H) / 2], 0, [Wb - W, Hb - H]).round().astype(int)
    data = b"".join(big[y:y + H, x:x + W].tobytes() for x, y in pos)
    ffmpeg("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", fps, "-i", "-",
           "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path,
           data=data)
    return path


def jitter(path) -> float:
    """Mean frame-to-frame camera shift (px), from the same robust feature tracker the fallback uses."""
    info = numa_common.media_info(path)
    m = pm.camera_path(str(path), info["width"] // 2 * 2, info["height"] // 2 * 2)
    return float(np.abs(m[1:, :2]).mean())


def frame(path, t: float = 1.5) -> np.ndarray:
    out = subprocess.run([numa_common.ffmpeg_bin(), "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    info = numa_common.media_info(path)
    return np.frombuffer(out, np.uint8).reshape(info["height"], info["width"])


@pytest.fixture(scope="module")
def job(tmp_path_factory):
    root = tmp_path_factory.mktemp("prep")
    raw, work = root / "raw", root / "work"
    raw.mkdir()
    walk_clip(raw / "c0_shaky.mp4", amp=0.012)
    ffmpeg("-loop", "1", "-i", BRAND / "breathwork-class.jpg", "-f", "lavfi",
           "-i", "sine=frequency=300:sample_rate=48000:duration=3", "-t", "3",
           "-vf", "scale=480:-2,crop=240:320,eq=brightness=-0.3:contrast=0.6,fps=30",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           raw / "c1_dark.mp4")
    with Image.open(BRAND / "sauna-people.jpg") as im:
        rgb = np.asarray(im.convert("RGB").resize((360, 540))).astype(np.float32)
    Image.fromarray((rgb * 0.45).astype(np.uint8)).save(raw / "p_dark.jpg", quality=95)
    with Image.open(BRAND / "cold-plunge.jpg") as im:
        im.convert("RGB").resize((360, 540)).save(raw / "p_fine.jpg", quality=95)
    an.analyze(raw, work, transcribe_audio=False, pad_seconds=0)
    path = work / "analysis.json"
    vision.run_vision(path)
    report = pm.run_prep(path)
    return {"path": path, "work": work, "report": report, "A": json.loads(path.read_text())}


def item(A, stem):
    return next(e for e in A["photos"] + A["clips"] if Path(e["path"]).stem == stem)


def test_auto_selects_flagged_items(job):
    rows = {r["id"]: r for r in job["report"]["items"]}
    A = job["A"]
    assert rows[item(A, "c0_shaky")["id"]]["ops"] == ["stabilize"]
    assert rows[item(A, "c1_dark")["id"]]["ops"] == ["brighten"]
    assert rows[item(A, "p_dark")["id"]]["ops"] == ["brighten"]
    fine = item(A, "p_fine")
    assert rows[fine["id"]]["ops"] == [] and "prepared_path" not in fine
    for stem, ext in (("c0_shaky", ".mp4"), ("c1_dark", ".mp4"), ("p_dark", ".jpg")):
        e = item(A, stem)
        assert e["prepared_path"] == str(job["work"] / "prep" / f"{e['id']}{ext}")
        assert Path(e["prepared_path"]).is_file()
    assert numa_common.schema_errors("analysis", A) == []


def test_stabilize_reduces_motion_and_keeps_audio_r287(job):
    e = item(job["A"], "c0_shaky")
    before, after = jitter(e["path"]), jitter(e["prepared_path"])
    assert after < 0.5 * before, (before, after)
    src, out = numa_common.media_info(e["path"]), numa_common.media_info(e["prepared_path"])
    assert out["has_audio"] and out["acodec"] == "aac"
    assert (out["width"], out["height"]) == (src["width"], src["height"])
    assert abs(out["duration"] - src["duration"]) < 0.1
    g = frame(e["prepared_path"])
    assert g[:, :3].mean() > 25 and g[:, -3:].mean() > 25 and g[:3].mean() > 25 and g[-3:].mean() > 25, \
        "black border"


def test_opencv_fallback_stabilizes(job, tmp_path):
    e = item(job["A"], "c0_shaky")
    out = tmp_path / "cv.mp4"
    details = pm.prepare_clip(e, True, False, out, method="opencv")
    assert details["method"] == "opencv"
    assert jitter(out) < 0.5 * jitter(e["path"])
    assert numa_common.media_info(out)["has_audio"]
    g = frame(out)
    assert min(g[:, :3].mean(), g[:, -3:].mean(), g[:3].mean(), g[-3:].mean()) > 25


def test_brighten_clip_raises_luma(job):
    e = item(job["A"], "c1_dark")
    a, b = frame(e["path"]).astype(float), frame(e["prepared_path"]).astype(float)
    assert b.mean() > a.mean() + 15
    assert (b >= 250).mean() <= (a >= 250).mean() + 0.001, "highlights blown"
    assert numa_common.media_info(e["prepared_path"])["has_audio"]


def test_brighten_photo_raises_luma_without_clipping(job):
    e = item(job["A"], "p_dark")
    a = np.asarray(Image.open(e["path"]).convert("L"), float)
    b = np.asarray(Image.open(e["prepared_path"]).convert("L"), float)
    assert a.shape == b.shape
    assert b.mean() > a.mean() + 20
    assert (b >= 254).mean() <= (a >= 254).mean() + 0.001


def test_gamma_for():
    assert pm.gamma_for(np.full(100, 0.6)) == 1.0
    g = pm.gamma_for(np.linspace(0.0, 0.5, 1000))
    assert 1.0 < g <= pm.MAX_GAMMA
    assert pm.gamma_for(np.zeros(10)) == pm.MAX_GAMMA


def test_idempotent_and_deterministic(job):
    before = job["path"].read_bytes()
    outs = {p: p.read_bytes() for p in (job["work"] / "prep").glob("*.*") if p.suffix in (".mp4", ".jpg")}
    report = pm.run_prep(job["path"])
    statuses = {r["status"] for r in report["items"] if r["ops"]}
    assert statuses == {"unchanged"}
    assert job["path"].read_bytes() == before
    for p, data in outs.items():
        assert p.read_bytes() == data


def test_reprocess_when_forced_and_remove_when_off(job, tmp_path, nc):
    A = json.loads(job["path"].read_text())
    path = tmp_path / "work" / "analysis.json"
    nc.write_json(path, A)
    pid = item(A, "p_dark")["id"]
    r1 = pm.run_prep(path, ids=pid)
    assert r1["items"][0]["status"] == "prepared"
    first = Path(r1["items"][0]["prepared_path"]).read_bytes()
    r2 = pm.run_prep(path, ids=pid.lower())
    assert r2["items"][0]["status"] == "unchanged"
    pm.run_prep(path, ids=pid, brighten="off")
    B = json.loads(path.read_text())
    assert "prepared_path" not in item(B, "p_dark")
    r3 = pm.run_prep(path, ids=pid)
    assert r3["items"][0]["status"] == "prepared"
    assert Path(r3["items"][0]["prepared_path"]).read_bytes() == first


def test_cli(job, run_script, tmp_path):
    r = run_script("prep_media.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    r = run_script("prep_media.py", job["path"], "--stabilize", "maybe")
    assert r.returncode == 2
    r = run_script("prep_media.py", job["path"], "--ids", "C99")
    assert r.returncode == 1 and "C99" in r.stderr and "Traceback" not in r.stderr
    r = run_script("prep_media.py", tmp_path / "nope.json")
    assert r.returncode == 1 and r.stderr.startswith("ERROR:")
    r = run_script("prep_media.py", job["path"], "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert {x["status"] for x in rep["items"] if x["ops"]} == {"unchanged"}
