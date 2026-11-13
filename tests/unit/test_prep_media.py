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


# The dark clips darken a full-range JPEG with eq, which works on the YUV values it is given. ffmpeg 6
# hands eq limited-range YUV; ffmpeg 7+ keeps the JPEG's full range, so the same eq settings leave the
# clip noticeably brighter (mean luma 0.26 instead of 0.22, no longer dark). Convert to limited range
# explicitly first: the same pixels on every ffmpeg version (identical to ffmpeg 6's frames).
TO_LIMITED = "out_range=tv,format=yuv420p"


def ffmpeg(*args, data: bytes | None = None) -> None:
    subprocess.run([numa_common.ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", *map(str, args)],
                   input=data, check=True)


def walk_clip(path: Path, *, amp: float, seconds: float = 3.0, fps: int = 30, size=(240, 426), seed: int = 11,
              photo: str = "breathwork-class.jpg") -> Path:
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
           "-vf", f"scale=480:-2:{TO_LIMITED},crop=240:320,eq=brightness=-0.3:contrast=0.6,fps=30",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           raw / "c1_dark.mp4")
    walk_clip(raw / "c2_shaky_face.mp4", amp=0.01, size=(360, 640), photo="cold-plunge.jpg")
    ffmpeg("-loop", "1", "-i", BRAND / "sauna-people.jpg", "-t", "2",
           "-vf", f"scale=360:540:{TO_LIMITED},eq=brightness=-0.3:contrast=0.5,fps=30",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", raw / "c3_dark_faces.mp4")
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


def fresh_focus(e) -> tuple[list, list]:
    """Independent detection on the prepared file's frames in the clip's best window."""
    det = vision.FaceDetector()
    info = numa_common.media_info(e["prepared_path"])
    times, frames = vision.sample_clip(e["prepared_path"], [info["width"], info["height"]], e["duration"])
    t0, t1 = e["windows"][0][:2]
    found = [det.detect(f) for t, f in zip(times, frames) if t0 <= t < t1]
    best = min(found, key=lambda fs: (-len(fs), -sum(b[2] * b[3] for b in fs)))   # the frame vision.py uses
    return best, vision.face_focus(best)


def test_faces_follow_the_prepared_copy(job):
    e = item(job["A"], "c2_shaky_face")
    assert e["prepared_path"] and e["orig_faces"] and e["orig_focus"]
    faces, focus = fresh_focus(e)
    assert faces and e["faces"]
    assert abs(e["focus"][0] - focus[0]) <= 0.03 and abs(e["focus"][1] - focus[1]) <= 0.03
    assert e["focus"][0] > 0.55, "the fixture face is right of centre"


def test_brightened_dark_clip_gains_faces(job):
    e = item(job["A"], "c3_dark_faces")
    assert e["prepared_path"]
    assert len(e["faces"]) > len(e["orig_faces"])
    assert max(s["faces"] for s in e["scores"]) >= len(e["faces"])


def test_forced_op_survives_auto_and_off_restores_faces(job, tmp_path, nc):
    A = json.loads(job["path"].read_text())
    path = tmp_path / "work" / "analysis.json"
    nc.write_json(path, A)
    fine = item(A, "p_fine")
    pm.run_prep(path, ids=fine["id"], brighten="on")
    B = json.loads(path.read_text())
    assert item(B, "p_fine")["prepared_path"] and "orig_faces" in item(B, "p_fine")
    r = pm.run_prep(path)                              # a later auto run keeps the forced step
    row = next(x for x in r["items"] if x["id"] == fine["id"])
    assert row["ops"] == ["brighten"] and row["status"] == "unchanged"
    pm.run_prep(path, ids=fine["id"], brighten="off")
    C = json.loads(path.read_text())
    e = item(C, "p_fine")
    assert "prepared_path" not in e and "orig_faces" not in e and "orig_focus" not in e
    assert e["faces"] == fine["faces"] and e["focus"] == fine["focus"]
    r = pm.run_prep(path, ids=fine["id"])              # forced record gone: auto leaves it alone
    assert r["items"][0]["ops"] == []


def test_large_clips_are_scaled_down(tmp_path):
    assert pm.out_size({"width": 3840, "height": 2160}) == (1920, 1080)
    assert pm.out_size({"width": 2160, "height": 3840}) == (1080, 1920)
    assert pm.out_size({"width": 720, "height": 1280}) == (720, 1280)
    src = tmp_path / "big.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1440x1200:rate=30:duration=1", "-c:v", "libx264",
           "-preset", "ultrafast", "-pix_fmt", "yuv420p", src)
    out = tmp_path / "out.mp4"
    pm.prepare_clip({"path": str(src), "duration": 1.0}, False, True, out)
    info = numa_common.media_info(out)
    assert (info["width"], info["height"]) == (1296, 1080)


def test_opencv_output_keeps_timing(job, tmp_path):
    e = item(job["A"], "c0_shaky")
    out = tmp_path / "cv.mp4"
    pm.prepare_clip(e, True, True, out, method="opencv")
    a, b = numa_common.media_info(e["path"]), numa_common.media_info(out)
    assert abs(a["duration"] - b["duration"]) < 0.1 and abs((b["fps"] or 0) - a["fps"]) < 0.5


def test_shaky_motion_is_not_rewarded():
    assert vision.second_score(150, 20, 0, 0.5, shaky=True) < vision.second_score(150, 0, 0, 0.5)


@pytest.mark.parametrize("gamma", [1.0, 1.6])
def test_opencv_output_is_tagged_limited_range_bt709(tmp_path, gamma):
    # a flat mid-grey BT.709 clip: the OpenCV path must tag the range and colour, and keep the level
    src = tmp_path / "grey.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:s=240x426:r=30:d=1", "-vf", "format=yuv420p",
           "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:v", "libx264", "-crf", "10", str(src))
    out = tmp_path / "grey_cv.mp4"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    pm.stabilize_opencv(str(src), numa_common.media_info(src), out, gamma, scratch)
    probe = json.loads(subprocess.run(
        [numa_common.ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_range,color_space,color_primaries,color_transfer", "-of", "json", str(out)],
        capture_output=True, check=True).stdout)["streams"][0]
    assert probe == {"color_range": "tv", "color_space": "bt709", "color_primaries": "bt709",
                     "color_transfer": "bt709"}
    if gamma == 1.0:
        y_src, y_out = frame(src, 0.5), frame(out, 0.5)
        assert abs(float(y_src.mean()) - float(y_out.mean())) < 3
