"""Unit tests for scripts/vision.py (R279 smart framing, R282 clip scores, weak-media flags).

Fixtures are synthetic: crops of the bundled brand photos and short clips made
from them (a seeded random-walk crop for the shaky clip, a darkened still for the
dark clip). analyze.py runs first, exactly as in the pipeline.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

import analyze as an
import numa_common
import vision

BRAND = Path(numa_common.BRAND_PHOTOS_DIR)


def ffmpeg(*args, data: bytes | None = None) -> None:
    subprocess.run([numa_common.ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", *map(str, args)],
                   input=data, check=True)


def walk_clip(path: Path, *, amp: float, seconds: float = 3.0, fps: int = 30, size=(240, 426), seed: int = 7,
              photo: str = "breathwork-class.jpg") -> Path:
    """A clip cropped from a still photo along a seeded random walk (amp = step std, fraction of the frame)."""
    W, H = size
    with Image.open(BRAND / photo) as im:
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


def dark_clip(path: Path, seconds: float = 3.0) -> Path:
    # eq darkens the YUV values it is given: ffmpeg 6 converts the full-range JPEG to limited range
    # before eq, ffmpeg 7+ keeps full range and the same settings leave the clip too bright to be dark
    # (mean luma 0.26, not 0.22). Convert to limited range explicitly: the same pixels on every version.
    ffmpeg("-loop", "1", "-i", BRAND / "breathwork-class.jpg", "-f", "lavfi",
           "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}", "-t", seconds,
           "-vf", "scale=480:-2:out_range=tv,format=yuv420p,crop=240:320,eq=brightness=-0.3:contrast=0.6,fps=30",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path)
    return path


def off_centre_face(path: Path) -> tuple[Path, tuple[float, float]]:
    """cold-plunge.jpg cropped so its one face sits left of centre; returns the face centre (normalized)."""
    with Image.open(BRAND / "cold-plunge.jpg") as im:
        box = (380, 400, 1024, 1300)
        im.convert("RGB").crop(box).save(path, quality=92)
    # the face is at about (590, 810) in the original
    return path, ((590 - box[0]) / (box[2] - box[0]), (810 - box[1]) / (box[3] - box[1]))


@pytest.fixture(scope="module")
def job(tmp_path_factory):
    root = tmp_path_factory.mktemp("vision")
    raw, work = root / "raw", root / "work"
    raw.mkdir()
    face, centre = off_centre_face(raw / "a_face.jpg")
    with Image.open(BRAND / "cold-plunge.jpg") as im:
        im.convert("RGB").resize((1080, 1620)).save(raw / "b_tall.jpg", quality=92)
        im.convert("RGB").resize((1080, 1620)).filter(ImageFilter.GaussianBlur(8)).save(raw / "c_blurry.jpg")
        dark = np.asarray(im.convert("RGB").resize((1080, 1620))).astype(np.float32) * 0.28
        Image.fromarray(dark.astype(np.uint8)).save(raw / "d_dark.jpg", quality=92)
    with Image.open(BRAND / "breathwork-class.jpg") as im:
        im.convert("RGB").save(raw / "e_landscape.jpg", quality=92)
    walk_clip(raw / "c0_shaky.mp4", amp=0.012)
    walk_clip(raw / "c1_steady.mp4", amp=0.0, photo="sauna-people.jpg")
    dark_clip(raw / "c2_dark.mp4")
    an.analyze(raw, work, transcribe_audio=False, pad_seconds=0)
    path = work / "analysis.json"
    report = vision.run_vision(path)
    return {"path": path, "report": report, "centre": centre,
            "A": json.loads(path.read_text()), "first_bytes": path.read_bytes()}


def by_name(A: dict, kind: str, stem: str) -> dict:
    return next(e for e in A[kind] if Path(e["path"]).stem == stem)


def test_focus_lands_on_off_centre_face_r279(job):
    p = by_name(job["A"], "photos", "a_face")
    assert len(p["faces"]) == 1
    x, y, w, h = p["faces"][0]
    cx, cy = job["centre"]
    assert x <= cx <= x + w and y <= cy <= y + h, "face box misses the face"
    fx, fy = p["focus"]
    assert x <= fx <= x + w and y <= fy <= y + h, "focus is not on the face"
    assert fx < 0.42, "the fixture face is off-centre; focus must follow it"


def test_no_faces_on_empty_scenes(job):
    for stem in ("c_blurry", "e_landscape"):
        assert by_name(job["A"], "photos", stem)["faces"] == []


def test_saliency_focus_without_faces():
    img = np.full((400, 300, 3), 120, np.uint8)
    rng = np.random.default_rng(1)
    img[60:140, 180:260] = rng.integers(0, 255, (80, 80, 3), dtype=np.uint8)  # a busy patch upper right
    fx, fy = vision.saliency_focus(img)
    assert fx > 0.6 and fy < 0.4


def test_photo_flags(job):
    A = job["A"]
    assert by_name(A, "photos", "b_tall")["flags"] == []
    assert by_name(A, "photos", "c_blurry")["flags"] == ["blurry"]
    assert by_name(A, "photos", "d_dark")["flags"] == ["dark"]
    assert by_name(A, "photos", "e_landscape")["flags"] == ["landscape", "low_res"]
    assert "low_res" in by_name(A, "photos", "a_face")["flags"]


def test_clip_flags(job):
    A = job["A"]
    assert "shaky" in by_name(A, "clips", "c0_shaky")["flags"]
    steady = by_name(A, "clips", "c1_steady")["flags"]
    assert "shaky" not in steady and "dark" not in steady
    assert "dark" in by_name(A, "clips", "c2_dark")["flags"]
    assert all("low_res" in c["flags"] for c in A["clips"])


def test_dark_rule_spares_low_key_photos(nc):
    assert vision.is_dark(0.2, 0.4)
    assert not vision.is_dark(0.2, 0.75)   # moody shot with lit highlights
    assert not vision.is_dark(0.3, 0.4)


def test_clip_scores_and_windows_r282(job):
    for c in job["A"]["clips"]:
        secs = [s["t"] for s in c["scores"]]
        assert secs == [float(t) for t in range(len(secs))] and len(secs) == 3
        for s in c["scores"]:
            assert set(s) == {"t", "sharpness", "motion", "faces", "score"}
            assert 0.0 <= s["score"] <= 1.0
        assert 1 <= len(c["windows"]) <= 3
        t0, t1, score = c["windows"][0]
        assert 0.0 <= t0 < t1 <= c["duration"] + 1e-6 and 2.0 <= t1 - t0 <= 5.0 and 0 <= score <= 1
        assert c["focus"] and len(c["focus"]) == 2
    shaky, steady = by_name(job["A"], "clips", "c0_shaky"), by_name(job["A"], "clips", "c1_steady")
    assert np.mean([s["motion"] for s in shaky["scores"]]) > 3 * np.mean([s["motion"] for s in steady["scores"]])
    assert steady["faces"], "the sauna-people still has faces"
    assert max(s["faces"] for s in steady["scores"]) >= 1


def test_best_windows_pick_the_good_stretch():
    scores = [{"t": float(t), "score": v} for t, v in enumerate([0.1, 0.1, 0.9, 0.9, 0.9, 0.2, 0.1, 0.1])]
    wins = vision.best_windows(scores, 8.0)
    assert wins[0][:2] == [2.0, 5.0]
    spans = [(a, b) for a, b, _ in wins]
    assert all(not (a < d and c < b) for i, (a, b) in enumerate(spans) for c, d in spans[i + 1:])
    assert vision.best_windows([{"t": 0.0, "score": 0.5}], 1.2) == [[0.0, 1.2, 0.5]]


def test_output_validates_and_is_idempotent(job, nc):
    assert nc.schema_errors("analysis", job["A"]) == []
    vision.run_vision(job["path"])
    assert job["path"].read_bytes() == job["first_bytes"]


def test_photos_only_leaves_clips(job, tmp_path, nc):
    A = json.loads(job["first_bytes"])
    for c in A["clips"]:
        for key in ("faces", "focus", "scores", "windows", "flags"):
            c.pop(key)
    path = tmp_path / "analysis.json"
    nc.write_json(path, A)
    report = vision.run_vision(path, clips=False)
    assert report["clips"] == []
    B = json.loads(path.read_text())
    assert all("scores" not in c for c in B["clips"]) and all("focus" in p for p in B["photos"])


def test_cli(job, run_script, tmp_path):
    r = run_script("vision.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    r = run_script("vision.py", tmp_path / "missing.json")
    assert r.returncode == 1 and r.stderr.startswith("ERROR:") and "Traceback" not in r.stderr
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1}')
    r = run_script("vision.py", bad)
    assert r.returncode == 1 and "analyze.py" in r.stderr
    r = run_script("vision.py", job["path"], "--no-clips", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["detector"] == "yunet" and len(rep["photos"]) == 5


def test_haar_fallback_backend(job, tmp_path, nc):
    det = vision.FaceDetector("haar")
    if not det.available:
        pytest.skip(f"no Haar cascades in this OpenCV build: {det.reason}")
    img = vision.read_image(str(BRAND / "mats-bolsters.jpg"))
    assert det.detect(img) == []                     # an empty room: no faces
    path = tmp_path / "analysis.json"
    path.write_bytes(job["first_bytes"])
    report = vision.run_vision(path, clips=False, backend="haar")
    assert report["detector"] == "haar"
    B = json.loads(path.read_text())
    assert nc.schema_errors("analysis", B) == []
    for p in B["photos"]:
        assert all(len(b) == 4 and all(0 <= v <= 1 for v in b) for b in p["faces"])
