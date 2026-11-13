"""photo_post.py: single-photo posts and photo carousels from the render engine (R333, R334)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

import engine
import numa_common
import photo_post as pp
import vision


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(pp.main, argv)
    return e.value.code


def synthetic(path, size=(1200, 1600), seed=0):
    """A face-free photo: soft gradient plus a few warm blocks (deterministic)."""
    rng = np.random.default_rng(seed)
    w, h = size
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([120 + 80 * x / w, 90 + 60 * y / h, 70 + 40 * (1 - y / h)], axis=-1)
    for _ in range(4):
        x0, y0 = int(rng.integers(0, w - 200)), int(rng.integers(0, h - 200))
        img[y0:y0 + 180, x0:x0 + 180] = rng.integers(30, 220, size=3)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path, quality=92)
    return path


@pytest.fixture
def photo(tmp_path):
    return synthetic(tmp_path / "plunge.jpg")


@pytest.fixture
def people(assets_dir):
    return assets_dir / "brand-photos" / "sauna-people.jpg"


def test_single_is_4x5_and_deterministic(nc, photo, tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    assert run(["single", str(photo), "--people-free", "--out", str(a), "--text", "Three minutes. Walk out wide *awake*."]) == 0
    assert run(["single", str(photo), "--people-free", "--out", str(b), "--text", "Three minutes. Walk out wide *awake*."]) == 0
    assert Image.open(a).size == (1080, 1350)
    assert a.read_bytes() == b.read_bytes()


def test_single_is_the_engine_frame(nc, photo, tmp_path, capsys):
    """The post is the engine's frame 0 of the one-shot plan: the reels' grade, vignette and grain."""
    out = tmp_path / "p.jpg"
    assert run(["single", str(photo), "--people-free", "--out", str(out), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    s = rep["slides"][0]
    assert rep["kind"] == "single" and s["faces"] == 0 and s["text_position"] is None
    ph = pp.Photo(photo, vision.FaceDetector(), False, {}, False, True)
    plan = pp.post_plan(ph, None, "warm", tmp_path)
    rgb = engine.render_frame(engine.prepare_plan(plan, tmp_path), 0.0, size=(1080, 1350))
    got = np.asarray(Image.open(out)).astype(int)
    assert np.abs(got - rgb.astype(int)).mean() < 2.0          # JPEG round trip only
    none = tmp_path / "n.jpg"
    assert run(["single", str(photo), "--people-free", "--out", str(none), "--look", "none"]) == 0
    assert np.abs(np.asarray(Image.open(none)).astype(int) - got).mean() > 2.0   # the look is applied


def test_folder_out_and_slug(nc, photo, tmp_path):
    d = tmp_path / "posts"
    d.mkdir()
    assert run(["single", str(photo), "--people-free", "--out", str(d), "--slug", "Cold Morning"]) == 0
    assert (d / "cold-morning_photo.jpg").is_file()
    assert run(["single", str(photo), "--people-free", "--out", str(tmp_path / "x.png")]) == 2


def test_text_rules(nc, photo, tmp_path, capsys):
    out = str(tmp_path / "t.jpg")
    assert run(["single", str(photo), "--people-free", "--out", out, "--text", "Sauna cures stress"]) == 1
    assert "banned claim" in capsys.readouterr().err
    assert run(["single", str(photo), "--people-free", "--out", out, "--text", "word " * 20]) == 1
    assert "at most" in capsys.readouterr().err
    assert run(["single", str(photo), "--people-free", "--out", out, "--text", "Unbalanced *gold"]) == 1


def test_consent_gate(nc, people, tmp_path, capsys):
    out = tmp_path / "p.jpg"
    assert run(["single", str(people), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "face(s) and no recorded consent" in err and "--blur-faces" in err and not out.exists()
    assert run(["single", str(people), "--out", str(out), "--blur-faces", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)["slides"][0]
    assert s["faces"] >= 1 and s["blurred"] and s["consent"] is None
    assert run(["single", str(people), "--out", str(out), "--consent", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)["slides"][0]
    assert s["consent"] is True and not s["blurred"]
    # a library "no" is never overridden by --consent; a library "yes" is consent
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"items": [{"path": str(people), "consent": "no"}]}))
    assert run(["single", str(people), "--out", str(out), "--consent", "--library", str(lib)]) == 1
    assert "consent no" in capsys.readouterr().err
    lib.write_text(json.dumps({"items": [{"path": str(people), "consent": "yes"}]}))
    assert run(["single", str(people), "--out", str(out), "--library", str(lib)]) == 0


def test_blur_hides_the_faces(nc, people, tmp_path):
    ph = pp.Photo(people, vision.FaceDetector(), False, {}, True)
    assert ph.blur and all(b[2] > f[2] and b[3] > f[3] for b, f in zip(ph.blur, ph.faces))
    plain = pp.post_plan(ph, None, "warm", tmp_path)
    plain["shots"][0].pop("blur")
    a = engine.render_frame(engine.prepare_plan(plain, tmp_path), 0.0, size=(540, 676))
    b = engine.render_frame(engine.prepare_plan(pp.post_plan(ph, None, "warm", tmp_path), tmp_path), 0.0,
                            size=(540, 676))
    import cv2
    diff = np.abs(a.astype(int) - b.astype(int)).max(axis=2)
    assert diff.mean() > 0.2 and (diff > 8).mean() < 0.25        # changed, but only where the faces are
    detail = [cv2.Laplacian(cv2.cvtColor(x, cv2.COLOR_RGB2GRAY), cv2.CV_64F)[diff > 8].var() for x in (a, b)]
    assert detail[1] < 0.5 * detail[0]                           # the face areas lost their detail


def test_text_moves_below_a_face_at_the_top(nc, photo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vision.FaceDetector, "detect", lambda self, bgr: [[0.4, 0.1, 0.2, 0.15]])
    out = tmp_path / "f.jpg"
    assert run(["single", str(photo), "--out", str(out), "--consent", "--text", "Your first *plunge*.", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)["slides"][0]
    assert s["text_position"] == "bottom" and s["faces"] == 1
    monkeypatch.setattr(vision.FaceDetector, "detect", lambda self, bgr: [[0.4, 0.75, 0.2, 0.15]])
    assert run(["single", str(photo), "--out", str(out), "--consent", "--text", "Your first *plunge*.", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["slides"][0]["text_position"] == "top"


def test_carousel_names_texts_and_rerun(nc, tmp_path, capsys):
    src = tmp_path / "photos"
    src.mkdir()
    for i in range(3):
        synthetic(src / f"p{i}.jpg", size=(1400, 1000), seed=i)
    texts = tmp_path / "t.txt"
    texts.write_text("Cold *first*.\n\nThen the *heat*.\n")
    out = tmp_path / "out"
    assert run(["carousel", str(src), "--out", str(out), "--texts", str(texts), "--slug", "rituals", "--json"]
               + [x for i in range(3) for x in ("--people-free", f"p{i}.jpg")]) == 0
    rep = json.loads(capsys.readouterr().out)
    names = sorted(p.name for p in out.iterdir())
    assert names == ["rituals_carousel_01.jpg", "rituals_carousel_02.jpg", "rituals_carousel_03.jpg"]
    assert [s["text"] for s in rep["slides"]] == ["Cold *first*.", None, "Then the *heat*."]
    assert all(Image.open(out / n).size == (1080, 1350) for n in names)
    # a re-run with fewer slides replaces the old set
    assert run(["carousel", str(src / "p0.jpg"), str(src / "p1.jpg"), "--out", str(out), "--slug", "rituals",
                "--people-free", "p0.jpg", "--people-free", str(src / "p1.jpg")]) == 0
    assert sorted(p.name for p in out.iterdir()) == names[:2]
    # JSON texts, wrong count
    bad = tmp_path / "t.json"
    bad.write_text(json.dumps(["One.", None]))
    assert run(["carousel", str(src), "--out", str(out), "--texts", str(bad), "--people-free", "p0.jpg"]) == 1
    assert "2 text(s) for 3 slide(s)" in capsys.readouterr().err


def test_carousel_limits_and_consent(nc, tmp_path, people, capsys):
    one = synthetic(tmp_path / "one.jpg", size=(800, 1000))
    assert run(["carousel", str(one), "--out", str(tmp_path / "o")]) == 1
    assert run(["carousel"] + [str(one)] * 11 + ["--out", str(tmp_path / "o")]) == 1
    # one photo with faces stops the whole carousel before anything is written
    assert run(["carousel", str(one), str(people), "--out", str(tmp_path / "c")]) == 1
    assert not (tmp_path / "c").exists()
    assert run(["carousel", str(one), str(people), "--out", str(tmp_path / "c"), "--blur-faces"]) == 1  # one.jpg: no basis
    assert run(["carousel", str(one), str(people), "--out", str(tmp_path / "c"), "--blur-faces",
                "--people-free", "one.jpg", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [s["people_basis"] for s in rep["slides"]] == ["people_free_flag", "blurred"]
    assert run(["carousel", str(one), str(people), "--out", str(tmp_path / "c"), "--people-free", "nope.jpg"]) == 2
    assert run(["carousel", str(tmp_path / "missing.jpg"), str(one), "--out", str(tmp_path / "c")]) == 1
    assert run([]) == 2


BREATHWORK = "breathwork-class.jpg"   # three people lying down: no face is detected


def test_no_face_is_not_people_free(nc, assets_dir, tmp_path, capsys):
    """B1: detectors only ever say yes. A 0-face photo needs consent, a people:no tag or --people-free."""
    bw = assets_dir / "brand-photos" / BREATHWORK
    out = tmp_path / "bw.jpg"
    assert run(["single", str(bw), "--out", str(out)]) == 1
    assert "never proves there are no people" in capsys.readouterr().err and not out.exists()
    assert run(["single", str(bw), "--out", str(out), "--blur-faces"]) == 1          # nothing to blur
    capsys.readouterr()
    assert run(["single", str(bw), "--out", str(out), "--people-free", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)["slides"][0]
    assert s["faces"] == 0 and s["people_basis"] == "people_free_flag"
    assert run(["single", str(bw), "--out", str(out), "--consent", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["slides"][0]["people_basis"] == "consent"


def test_library_people_tag(nc, assets_dir, tmp_path, capsys):
    bw = assets_dir / "brand-photos" / BREATHWORK
    out, lib = tmp_path / "bw.jpg", tmp_path / "lib.json"
    lib.write_text(json.dumps({"items": [{"path": str(bw), "people": False, "people_source": "tag", "consent": "n/a"}]}))
    assert run(["single", str(bw), "--out", str(out), "--library", str(lib), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["slides"][0]["people_basis"] == "library_tag_no"
    # people "no" from anything but a tag (a detector) proves nothing
    lib.write_text(json.dumps({"items": [{"path": str(bw), "people": False, "people_source": "detector"}]}))
    assert run(["single", str(bw), "--out", str(out), "--library", str(lib)]) == 1
    lib.write_text(json.dumps({"items": [{"path": str(bw), "consent": "yes"}]}))
    assert run(["single", str(bw), "--out", str(out), "--library", str(lib), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["slides"][0]["people_basis"] == "library_consent"
    # consent no is never overridden by --people-free
    lib.write_text(json.dumps({"items": [{"path": str(bw), "consent": "no"}]}))
    assert run(["single", str(bw), "--out", str(out), "--library", str(lib), "--people-free"]) == 1


def test_faces_on_a_people_free_photo(nc, people, tmp_path):
    assert run(["single", str(people), "--out", str(tmp_path / "p.jpg"), "--people-free"]) == 1
    assert run(["single", str(people), "--out", str(tmp_path / "p.jpg"), "--people-free", "--blur-faces"]) == 0
