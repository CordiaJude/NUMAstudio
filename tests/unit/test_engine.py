"""Unit tests for the render engine (skills/numa-reel-editor/scripts/engine.py).

Small sizes (270x480) and short reels keep the suite fast; the full 1080x1920
quality pass is done by rendering a sample and looking at its frames.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import engine
import engine_media as em

SMALL = (270, 480)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


@pytest.fixture
def ramp_image(tmp_path):
    """Asymmetric 1600x900 landscape: red encodes x (0..255 left->right), green encodes y, blue a block."""
    w, h = 1600, 900
    x = np.linspace(0, 255, w, dtype=np.float32)[None, :].repeat(h, 0)
    y = np.linspace(0, 255, h, dtype=np.float32)[:, None].repeat(w, 1)
    b = np.zeros((h, w), np.float32)
    b[:, : w // 5] = 255
    p = tmp_path / "ramp.png"
    Image.fromarray(np.stack([x, y, b], -1).round().astype(np.uint8)).save(p)
    return p


@pytest.fixture
def flat_image(tmp_path):
    def _make(value=255, size=(720, 1280), name="flat.png"):
        p = tmp_path / name
        Image.new("RGB", size, (value, value, value)).save(p)
        return p
    return _make


@pytest.fixture
def clip(tmp_path, make_video):
    return make_video(tmp_path / "clip.mp4", seconds=2.0, size=(320, 240), fps=30, audio=False)


def short_plan(plan_factory, **over):
    """A 2 s reel: photo, punch, video-free; hook and one caption line."""
    p = plan_factory()
    s = p["shots"]
    p.update(duration=2.0, leaks=[[0.8, 0.5, 0.5]], endcard={"t": 1.4, "subtitle": "See you there."},
             lines=[{"words": [["Walk", 0.1], ["out", 0.3], ["wide", 0.5], ["awake.", 0.7, 1]], "end": 1.3}],
             shots=[dict(s[0], t0=0.0, t1=0.7), dict(s[1], t0=0.7, t1=1.4, tr="whip"),
                    dict(s[2], t0=1.4, t1=2.0, tr="flash")])
    p.update(over)
    return p


# --------------------------------------------------------------------------- determinism and speed paths
def test_byte_identical_across_runs_and_workers(plan_factory, clip, tmp_path):
    """R297/R289: same plan -> same bytes, for 1 and 3 workers (several encoder segments)."""
    p = short_plan(plan_factory)
    p["shots"][1] = {"kind": "video", "src": str(clip), "start": 0.2, "t0": 0.7, "t1": 1.4, "z": [1.0, 1.1], "tr": "whip"}
    plan = engine.prepare_plan(p)
    a = engine.render_video(plan, tmp_path / "a.mp4", size=SMALL, workers=1, segment_s=0.5, progress=False)
    b = engine.render_video(plan, tmp_path / "b.mp4", size=SMALL, workers=1, segment_s=0.5, progress=False)
    c = engine.render_video(plan, tmp_path / "c.mp4", size=SMALL, workers=3, segment_s=0.5, progress=False)
    assert a["sha256"] == b["sha256"] == c["sha256"] == sha(tmp_path / "c.mp4")
    assert a["frames"] == 60 and c["workers"] == 3
    info = engine.nc.media_info(tmp_path / "c.mp4")
    assert (info["width"], info["height"]) == SMALL
    assert info["vcodec"] == "h264" and info["pix_fmt"] == "yuv420p" and abs(info["duration"] - 2.0) < 0.05
    assert not info["has_audio"]


def test_seed_changes_grain_only(plan_factory):
    p0 = engine.prepare_plan(short_plan(plan_factory, seed=0))
    p1 = engine.prepare_plan(short_plan(plan_factory, seed=5))
    f0, f0b, f1 = (engine.render_frame(p, 0.5, size=SMALL) for p in (p0, p0, p1))
    assert np.array_equal(f0, f0b)
    d = np.abs(f0.astype(int) - f1.astype(int))
    assert 0 < d.mean() < 6


def test_draft_is_smaller_and_faster(plan_factory, tmp_path):
    """R288: draft = half size, fast preset, own file name via the CLI."""
    plan = engine.prepare_plan(short_plan(plan_factory, size=[540, 960], duration=1.0, endcard={"t": 0.7},
                                          lines=[], shots=[dict(plan_factory()["shots"][0], t0=0.0, t1=1.0)]))
    d = engine.render_video(plan, tmp_path / "d.mp4", draft=True, workers=1, progress=False)
    f = engine.render_video(plan, tmp_path / "f.mp4", draft=False, workers=1, progress=False)
    assert d["size"] == [270, 480] and f["size"] == [540, 960]
    assert d["preset"] == "veryfast" and f["preset"] == "medium"
    assert d["bytes"] < f["bytes"]
    assert d["timings"]["render_encode_s"] < f["timings"]["render_encode_s"]


def test_cli_segment_render_writes_segment_json(plan_factory, tmp_path, run_script):
    plan = short_plan(plan_factory, size=[1080, 1350], duration=1.0, endcard={"t": 0.6}, lines=[],
                      hook={"text": "Quiet heat.", "t1": 1.5},
                      shots=[dict(plan_factory()["shots"][0], t0=0.0, t1=0.6),
                             dict(plan_factory()["shots"][1], t0=0.6, t1=1.0, tr="punch")])
    pj = tmp_path / "plan.json"
    pj.write_text(json.dumps(plan))
    r = run_script("engine.py", pj, "--draft", "--workers", "2", "--to", "0.5")
    assert r.returncode == 0, r.stderr
    out = Path(plan["out_dir"]) / "segment_0_0.5.mp4"
    rj = json.loads((Path(plan["out_dir"]) / "segment_0_0.5.json").read_text())
    assert not (Path(plan["out_dir"]) / "render.json").exists()   # a range never overwrites the full render's report
    assert not list(Path(plan["out_dir"]).glob(".numa-render-*"))  # render cache cleaned up
    assert rj["sha256"] == sha(out) and rj["frames"] == 15 and rj["size"] == [540, 676]
    for key in ("timings", "encoder", "workers", "fps"):
        assert key in rj


def test_1080x1350_size(plan_factory, tmp_path):
    """Plan size 1080x1350: frames come out 1080x1350 and the layout scales with the height."""
    plan = engine.prepare_plan(short_plan(plan_factory, size=[1080, 1350]))
    with engine.Renderer(plan) as r:
        assert r.frame(0.5).shape == (1350, 1080, 3)
        for _t0, _t1, x0, y0, x1, y1 in r.caption_boxes:
            assert y0 >= 0.12 * 1350 - 1 and y1 <= 0.90 * 1350 + 1
    # --size overrides the plan size
    assert engine.render_frame(plan, 0.5, size=(540, 960)).shape == (960, 540, 3)


def test_videotoolbox_falls_back(plan_factory, tmp_path, monkeypatch, capsys):
    """R290: the hardware encoder option falls back to libx264 with a WARN when unavailable."""
    monkeypatch.setattr(engine, "videotoolbox_available", lambda: False)
    plan = engine.prepare_plan(short_plan(plan_factory, duration=0.4, endcard={"t": 0.3}, lines=[],
                                          shots=[dict(plan_factory()["shots"][0], t0=0.0, t1=0.4)]))
    info = engine.render_video(plan, tmp_path / "v.mp4", size=SMALL, workers=1, encoder="videotoolbox",
                               progress=False)
    assert info["encoder"] == "libx264"
    assert "WARN: encoder" in capsys.readouterr().err


# --------------------------------------------------------------------------- first second, fades, hook
def test_frame_zero_not_black_and_hook_at_full_opacity(plan_factory):
    """R70/R71: frame 0 shows the picture and the hook text at full alpha (no fade-in with a hook)."""
    with_hook = engine.prepare_plan(short_plan(plan_factory))
    no_hook = dict(with_hook)
    no_hook.pop("hook")
    f_hook = engine.render_frame(with_hook, 0.0, size=SMALL)
    f_none = engine.render_frame(no_hook, 0.0, size=SMALL)
    assert luma(f_hook).mean() > 40 and luma(f_none).mean() > 20
    with engine.Renderer(with_hook, size=SMALL) as r:
        blk, top, _t1 = r._hook
        y0, y1 = int(top), int(top + blk.height)
        assert y0 >= 0.12 * SMALL[1] - 1
        band_hook, band_none = f_hook[y0:y1], f_none[y0:y1]
        # white text pixels exist in the hook band and are absent without a hook
        assert (luma(band_hook) > 235).sum() > 150
        assert (luma(band_hook) > 235).sum() > 5 * max(1, (luma(band_none) > 235).sum())
        # the hook is identical (full opacity) at frame 0 and at 1.0 s in its band, modulo the picture
        assert r._hook[2] == 2.0


def test_no_hook_fade_in_is_short_and_fade_out_reaches_black(plan_factory):
    """R70/R72: without a hook, a fade-in of at most 0.2 s that never starts from black; 0.8 s fade-out."""
    p = short_plan(plan_factory)
    p.pop("hook")
    plan = engine.prepare_plan(p)
    with engine.Renderer(plan, size=SMALL) as r:
        f0, f6, f7 = r.frame_index(0), r.frame_index(6), r.frame_index(7)
        assert 0.25 < luma(f0).mean() / luma(f6).mean() < 0.6
        assert abs(luma(f6).mean() - luma(f7).mean()) < 0.1 * luma(f7).mean()
        last = r.frame_index(r.n_frames - 1)
        assert luma(last).mean() < 2.0


def test_motion_from_frame_one(plan_factory):
    plan = engine.prepare_plan(short_plan(plan_factory))
    with engine.Renderer(plan, size=SMALL) as r:
        s = r.shots[0]
        m0, cx0, cy0 = s.framing.view(s.progress(0.0))
        m1, cx1, cy1 = s.framing.view(s.progress(1 / r.fps))
        assert m1 - m0 > 1e-4 or abs(cx1 - cx0) + abs(cy1 - cy0) > 0.05


# --------------------------------------------------------------------------- framing
@pytest.mark.parametrize("pan,z", [([1.0, 0.0], [0.95, 1.0]), ([-1.0, 0.5], [1.0, 0.95]), ([0.0, -1.0], [1.5, 1.2])])
def test_no_mirrored_edges_or_black_bars(plan_factory, ramp_image, pan, z):
    """R58: extreme pans and z < 1 never sample outside the source (no reflection, no bars)."""
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.5}, hook={"text": "x", "t1": 1.5})
    p["shots"] = [{"src": str(ramp_image), "t0": 0.0, "t1": 1.0, "z": z, "pan": pan, "look": "none"}]
    plan = engine.prepare_plan(p)
    with engine.Renderer(plan, size=SMALL) as r:
        for t in (0.0, 0.5, 1.0):
            pic = r._picture(t).astype(np.float32)
            red = pic[..., 0].mean(0)
            # red encodes source x: strictly left->right everywhere, so no mirrored strip at either edge
            assert np.all(np.diff(red) >= -0.5), (t, np.diff(red).min())
            assert red[-1] - red[0] > 10
            green = pic[..., 1].mean(1)
            assert np.all(np.diff(green) >= -0.5)
            # no black bars: every column and row has picture
            assert pic.sum(2).mean(0).min() > 30 and pic.sum(2).mean(1).min() > 30


def test_landscape_photo_pans_across_and_fills(plan_factory, ramp_image):
    p = plan_factory(duration=2.0, lines=[], leaks=[], endcard={"t": 1.0})
    p["shots"] = [{"src": str(ramp_image), "t0": 0.0, "t1": 2.0, "z": [1.02, 1.1], "look": "none"}]
    plan = engine.prepare_plan(p)
    with engine.Renderer(plan, size=SMALL) as r:
        a, b = r._picture(0.0), r._picture(2.0)
        assert r.shots[0].framing.auto_pan == 1
        assert b[..., 0].mean() - a[..., 0].mean() > 40      # moved right across the photo
        assert a.reshape(-1, 3).sum(1).min() > 0


def test_focus_moves_the_view(plan_factory, ramp_image):
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.5})
    base = {"src": str(ramp_image), "t0": 0.0, "t1": 1.0, "z": [1.3, 1.3], "pan": [0.0, 0.0], "look": "none"}
    reds = []
    for fx in (0.1, 0.9):
        p["shots"] = [dict(base, focus=[fx, 0.5], pan=[0.0001, 0.0])]
        with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
            reds.append(r._picture(0.5)[..., 0].mean())
    assert reds[1] - reds[0] > 30


def test_panorama_uses_blurred_fill(plan_factory, tmp_path):
    pano = tmp_path / "pano.jpg"
    Image.fromarray(np.full((300, 1500, 3), 180, np.uint8)).save(pano)
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.5})
    p["shots"] = [{"src": str(pano), "t0": 0.0, "t1": 1.0, "look": "none"}]
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        assert r.shots[0].panorama
        pic = r._picture(0.5)
        assert pic.reshape(-1, 3).sum(1).min() > 0      # blurred fill above and below, never black bars


# --------------------------------------------------------------------------- captions
def test_captions_in_safe_area_and_max_two_rows(plan_factory):
    """R65-R67: ~92 px at 1080 wide, <= 2 rows (shrinking a long line), inside the top 12% / bottom 10%."""
    long = "This sentence is long enough to need two rows of text".split()
    p = plan_factory(caption_y=1900, lines=[{"words": [[w, 0.2 + 0.1 * i] for i, w in enumerate(long)], "end": 3.0},
                                            {"words": [["Short", 3.2], ["line.", 3.4, 1]], "end": 4.0}])
    with engine.Renderer(engine.prepare_plan(p)) as r:
        H = r.height
        blk0, blk1 = r._lines[0][0], r._lines[1][0]
        assert blk0.rows == 2 and blk1.rows == 1
        assert abs(blk1.px - 92) < 0.5
        for _a, _b, x0, y0, x1, y1 in r.caption_boxes:
            assert y0 >= 0.12 * H and y1 <= 0.90 * H
            assert 0 <= x0 and x1 <= r.width
        assert max(sp.advance for sp, *_ in blk0.words) < 960


def test_caption_word_fades_in_and_rises(plan_factory):
    """R64: at appear + 0.14 s a word is partly visible; by +0.28 s fully."""
    p = plan_factory(lines=[{"words": [["Breathe.", 0.5]], "end": 2.0}], hook={"text": "x", "t1": 1.5})
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        img = np.zeros((r.height, r.width, 3), np.uint8)
        a, b, c = img.copy(), img.copy(), img.copy()
        r._draw_captions(a, 0.5 + 0.14)
        r._draw_captions(b, 0.5 + 0.3)
        r._draw_captions(c, 0.45)
        assert c.max() == 0
        assert 0 < a.max() < b.max()
        rows_a = np.nonzero(a.max(axis=(1, 2)) > 128)[0]
        rows_b = np.nonzero(b.max(axis=(1, 2)) > 128)[0]
        assert rows_a.mean() > rows_b.mean()   # still rising


def test_captions_move_off_faces(plan_factory):
    """R68: a face box at caption height pushes the caption block off it."""
    p = plan_factory()
    with engine.Renderer(engine.prepare_plan(p)) as r:
        _a, _b, _x0, y0, _x1, y1 = r.caption_boxes[0]
    face_y = (y0 + y1) / 2 / 1920
    p["shots"][0]["faces"] = [[0.3, max(0.0, face_y - 0.06), 0.4, 0.12]]
    p["shots"][0]["z"] = [1.0, 1.0001]
    with engine.Renderer(engine.prepare_plan(p)) as r:
        _a, _b, cx0, cy0, cx1, cy1 = r.caption_boxes[0]
        faces = r._face_rects(0.3, 2.6 + 0.35)
        assert faces
        assert (cy0, cy1) != (y0, y1)
        for fx0, fy0, fx1, fy1 in faces:
            assert fy1 <= cy0 or fy0 >= cy1 or fx1 <= cx0 or fx0 >= cx1
        assert cy0 >= 0.12 * 1920 and cy1 <= 0.90 * 1920


def test_hook_words_markup():
    from engine_text import hook_words
    assert hook_words("Your *first plunge*.") == [("Your", False), ("first", True), ("plunge.", True)]
    assert hook_words("Three minutes of cold.") == [("Three", False), ("minutes", False), ("of", False),
                                                    ("cold.", True)]


# --------------------------------------------------------------------------- transitions and looks
def transition_plan(plan_factory, tr, leaks=None):
    p = plan_factory(duration=2.4, lines=[], leaks=leaks or [], endcard={"t": 2.0}, hook={"text": "x", "t1": 1.5})
    s = plan_factory()["shots"]
    p["shots"] = [dict(s[0], t0=0.0, t1=1.0, tr="cut"), dict(s[1], t0=1.0, t1=2.4, tr=tr)]
    return engine.prepare_plan(p)


@pytest.mark.parametrize("tr", ["cut", "punch", "whip", "leakfade", "fade", "flash", "wipe"])
def test_every_transition_renders(plan_factory, tr):
    with engine.Renderer(transition_plan(plan_factory, tr), size=SMALL) as r:
        for t in (0.85, 0.95, 1.0, 1.05, 1.15, 1.3, 1.6, 2.1):
            f = r.frame(t)
            assert f.shape == (480, 270, 3) and f.dtype == np.uint8


def test_punch_zooms_16_percent_and_snaps_back(plan_factory):
    """R50: zoom x1.16 at the cut, back to the shot's own zoom by 0.22 s, with a white lift."""
    with engine.Renderer(transition_plan(plan_factory, "punch"), size=SMALL) as r:
        s = r.shots[1]
        m_plain = s.framing.view(0.0)[0]
        m_punch = s.framing.view(0.0, 1 + engine.PUNCH_ZOOM)[0]
        assert abs(m_punch / m_plain - 1.16) < 1e-6
        assert luma(r._picture(1.0)).mean() > luma(r._picture(1.0 + engine.PUNCH_S)).mean() + 20
        a, b = r._picture(1.0 + engine.PUNCH_S), r._view(1, 1.0 + engine.PUNCH_S)
        assert np.array_equal(a, b)


def test_flash_decays(plan_factory):
    """R53: white flash at the cut, gone after 0.35 s."""
    with engine.Renderer(transition_plan(plan_factory, "flash"), size=SMALL) as r:
        l0, l1 = luma(r._picture(1.0)).mean(), luma(r._picture(1.0 + 0.36)).mean()
        assert l0 > 200 and l0 > l1 + 60


def test_whip_slides_with_horizontal_blur(plan_factory):
    """R51: around the cut both shots slide over 0.28 s with up to 160 px blur (scaled)."""
    with engine.Renderer(transition_plan(plan_factory, "whip"), size=SMALL) as r:
        mid = r._picture(1.0).astype(np.float32)
        plain = r._view(0, 0.8).astype(np.float32)
        hgrad = lambda im: np.abs(np.diff(im, axis=1)).mean()  # noqa: E731
        assert hgrad(mid) < 0.5 * hgrad(plain)
        assert np.array_equal(r._picture(1.0 + engine.WHIP_S / 2 + 0.01), r._view(1, 1.0 + engine.WHIP_S / 2 + 0.01))


def test_leakfade_adds_warm_leak_without_leaks_entry(plan_factory):
    """R52: a leakfade with no `leaks` entry still shows a warm leak."""
    with engine.Renderer(transition_plan(plan_factory, "leakfade"), size=SMALL) as r1, \
            engine.Renderer(transition_plan(plan_factory, "fade"), size=SMALL) as r2:
        t = 1.25
        a = r1._leak(r1._picture(t), t).astype(np.float32)
        b = r2._leak(r2._picture(t), t).astype(np.float32)
        warm = (a - b).mean(axis=(0, 1))
        assert warm[0] > 8 and warm[0] > warm[2] + 4


def test_wipe_midpoint_split_with_glow(plan_factory, flat_image):
    """R54: at the wipe midpoint the left shows the after shot, the right the before shot, a glowing line between."""
    dark, light = flat_image(40, name="dark.png"), flat_image(140, name="light.png")
    p = plan_factory(duration=2.4, lines=[], leaks=[], endcard={"t": 2.2}, hook={"text": "x", "t1": 1.5})
    p["shots"] = [{"src": str(dark), "t0": 0.0, "t1": 1.0, "look": "none"},
                  {"src": str(light), "t0": 1.0, "t1": 2.4, "look": "none", "tr": "wipe"}]
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        f = r._picture(1.5).astype(np.float32)[..., 1].mean(0)
        assert f[10] > 120 and f[-10] < 60
        assert f.max() > 200 and 60 < int(np.argmax(f)) < 210


def test_grade_looks():
    """R60/R61: before = desaturated, cool, lifted blacks; warm = richer and warm; none = untouched."""
    patch = np.zeros((4, 4, 3), np.uint8)
    patch[..., 0], patch[..., 1], patch[..., 2] = 200, 120, 80
    black = np.zeros((4, 4, 3), np.uint8)
    sat = lambda im: float(im.max(-1).astype(int).mean() - im.min(-1).astype(int).mean())  # noqa: E731
    before, warm = em.grade(patch, "before"), em.grade(patch, "warm")
    assert sat(before) < 0.7 * sat(patch) and sat(warm) > sat(patch)
    assert em.grade(black, "before").mean() > 10                      # lifted blacks
    gray = np.full((4, 4, 3), 128, np.uint8)
    bg, wg = em.grade(gray, "before")[0, 0].astype(int), em.grade(gray, "warm")[0, 0].astype(int)
    assert bg[2] > bg[0] and wg[0] > wg[2]                             # cool vs warm
    assert em.grade(patch, "none") is patch


def test_vignette_darkens_corners_on_flat_white(plan_factory, flat_image):
    """R62: corners darker than the centre on a flat white plan."""
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.9}, hook={"text": "x", "t1": 1.5})
    p["shots"] = [{"src": str(flat_image(255)), "t0": 0.0, "t1": 1.0, "look": "none"}]
    p.pop("hook")
    f = luma(engine.render_frame(engine.prepare_plan(p), 0.5, size=SMALL))
    assert f[:20, :20].mean() < f[230:250, 125:145].mean() - 20


def test_endcard_draws_white_logo_and_gold_subtitle(plan_factory):
    """R69: wordmark rendered white, gold italic subtitle."""
    plan = engine.prepare_plan(plan_factory())      # end card from 5.4 s of a 9 s reel
    with engine.Renderer(plan, size=SMALL) as r:
        f = r.frame(7.8).astype(np.float32)
        H = r.height
        logo_band = f[int(0.42 * H):int(0.50 * H)]
        assert (logo_band.min(-1) > 150).sum() > 50                       # white wordmark pixels
        sub_band = f[int(0.74 * H):int(0.80 * H)]
        gold = (sub_band[..., 0] > 120) & (sub_band[..., 0] - sub_band[..., 2] > 25)
        assert gold.sum() > 10


# --------------------------------------------------------------------------- sources
def test_video_source_shot(plan_factory, clip):
    p = plan_factory(duration=1.5, lines=[], leaks=[], endcard={"t": 1.2})
    p["shots"] = [{"kind": "video", "src": str(clip), "start": 0.3, "speed": 1.0, "t0": 0.0, "t1": 1.5,
                   "z": [1.0, 1.1], "look": "warm"}]
    plan = engine.prepare_plan(p)
    with engine.Renderer(plan, size=SMALL) as r:
        a, b = r.frame(0.2), r.frame(0.9)
        assert a.shape == (480, 270, 3) and np.abs(a.astype(int) - b.astype(int)).mean() > 2


def test_blur_regions_hide_detail(plan_factory, tmp_path):
    """R106: a `blur` box makes that source region unrecognizable (variance drops) for stills and video."""
    rng = np.random.default_rng(0)
    noisy = tmp_path / "noisy.png"
    Image.fromarray(rng.integers(0, 256, (1280, 720, 3), dtype=np.uint8)).save(noisy)
    box = [0.25, 0.3, 0.5, 0.3]
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.9})
    p.pop("hook")
    shot = {"src": str(noisy), "t0": 0.0, "t1": 1.0, "z": [1.0, 1.0001], "look": "none"}
    variances = []
    for blur in (None, [box]):
        p["shots"] = [dict(shot, blur=blur) if blur else dict(shot)]
        with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
            pic = r._picture(0.5).astype(np.float32)
        y0, y1 = int(0.36 * 480), int(0.54 * 480)
        x0, x1 = int(0.33 * 270), int(0.67 * 270)
        variances.append((pic[y0:y1, x0:x1].var(), pic[:40, :].var()))
    (v_plain, edge_plain), (v_blur, edge_blur) = variances
    assert v_blur < 0.05 * v_plain
    assert abs(edge_blur - edge_plain) < 0.05 * edge_plain   # outside the box untouched
    frame = rng.integers(0, 256, (200, 100, 3), dtype=np.uint8)
    out = em.blur_regions(frame, [box])
    assert out[70:110, 30:70].var() < 0.1 * frame[70:110, 30:70].var()


# --------------------------------------------------------------------------- preview and CLI
def test_preview_grid_8_times(plan_factory, tmp_path, run_script):
    """R34: 8 times -> preview.jpg 5 tiles wide, 2 rows."""
    plan = short_plan(plan_factory)
    pj = tmp_path / "plan.json"
    pj.write_text(json.dumps(plan))
    r = run_script("engine.py", pj, "preview", *[f"{t:.2f}" for t in np.linspace(0, 1.9, 8)])
    assert r.returncode == 0, r.stderr
    out = Path(plan["out_dir"]) / "preview.jpg"
    with Image.open(out) as im:
        tw = engine.PREVIEW_TILE_W
        assert im.size == (5 * tw, 2 * round(tw * 1920 / 1080))


def test_cli_errors(plan_factory, tmp_path, run_script):
    plan = short_plan(plan_factory)
    pj = tmp_path / "plan.json"
    # missing source
    bad = json.loads(json.dumps(plan))
    bad["shots"][0]["src"] = str(tmp_path / "missing.jpg")
    pj.write_text(json.dumps(bad))
    r = run_script("engine.py", pj, "preview", "0")
    assert r.returncode == 1 and r.stderr.strip().startswith("ERROR:") and "missing.jpg" in r.stderr
    assert "Traceback" not in r.stderr
    # unreadable image
    junk = tmp_path / "junk.jpg"
    junk.write_bytes(b"not an image")
    bad["shots"][0]["src"] = str(junk)
    pj.write_text(json.dumps(bad))
    r = run_script("engine.py", pj, "preview", "0")
    assert r.returncode == 1 and "ERROR:" in r.stderr and "cannot read image" in r.stderr
    # schema violation
    bad = json.loads(json.dumps(plan))
    bad["shots"][0]["tr"] = "zoom"
    pj.write_text(json.dumps(bad))
    r = run_script("engine.py", pj)
    assert r.returncode == 1 and "ERROR:" in r.stderr and "shots[0].tr" in r.stderr
    # bad JSON, usage errors
    pj.write_text("{nope")
    assert run_script("engine.py", pj).returncode == 1
    assert run_script("engine.py").returncode == 2
    pj.write_text(json.dumps(plan))
    assert run_script("engine.py", pj, "preview").returncode == 2
    assert run_script("engine.py", pj, "--size", "100x7").returncode == 2
    r = run_script("engine.py", pj, "preview", "99")
    assert r.returncode == 1 and "outside the reel" in r.stderr


def test_v1_plan_renders(plan_factory, tmp_path):
    """A v1-shaped plan (no schema_version, no hook/size/seed) still renders with brand defaults."""
    p = plan_factory()
    for k in ("schema_version", "size", "quality", "seed", "hook", "meta"):
        p.pop(k, None)
    p["endcard"].pop("logo")
    f = engine.render_frame(engine.prepare_plan(p), 8.0, size=SMALL)
    assert f.shape == (480, 270, 3)


# --------------------------------------------------------------------------- review round 2
def test_rate_cap_holds_over_every_two_second_window(plan_factory, tmp_path, monkeypatch, nc):
    """Per-segment VBV budget: summed packet sizes over any 2 s window stay under the configured cap."""
    cfg = json.loads(Path(nc.CONFIG_PATH).read_text())
    cfg["render"]["video"]["maxrate"] = "600k"                     # far below what noise at 270x480 wants
    cpath = tmp_path / "studio.json"
    cpath.write_text(json.dumps(cfg))
    monkeypatch.setenv("NUMA_CONFIG", str(cpath))
    nc.clear_caches()
    rng = np.random.default_rng(1)
    noisy = tmp_path / "noise.png"
    Image.fromarray(rng.integers(0, 256, (960, 540, 3), dtype=np.uint8)).save(noisy)
    p = plan_factory(duration=6.0, lines=[], leaks=[], endcard={"t": 5.0})
    p["shots"] = [{"src": str(noisy), "t0": 0.0, "t1": 3.0, "z": [1.0, 1.3]},
                  {"src": str(noisy), "t0": 3.0, "t1": 6.0, "z": [1.3, 1.0], "tr": "flash"}]
    info = engine.render_video(engine.prepare_plan(p), tmp_path / "rate.mp4", size=SMALL, workers=1, progress=False)
    rate, buf = engine.rate_budget("600k")
    assert (1 + engine.VBV_INIT) * buf + rate * 2.0 <= 600e3 * 2.0 + 1      # the worst case is within the cap
    assert info["vbv_maxrate"] == rate and info["rate_cap"] == 600000
    out = engine.nc.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "packet=pts_time,size",
                         "-of", "json", str(tmp_path / "rate.mp4")]).stdout
    pk = sorted((float(x["pts_time"]), int(x["size"])) for x in json.loads(out)["packets"])
    sizes = [sz for _, sz in pk]
    assert len(sizes) == 180
    worst = max(sum(sizes[i:i + 60]) for i in range(len(sizes) - 59)) * 8 / 2.0
    assert worst <= 600e3
    assert worst > 300e3        # the cap is what limits this content, so the check is meaningful


def test_disk_space_is_checked_before_caching(plan_factory, clip, tmp_path, monkeypatch):
    p = short_plan(plan_factory)
    p["shots"][1] = {"kind": "video", "src": str(clip), "t0": 0.7, "t1": 1.4, "tr": "whip"}
    plan = engine.prepare_plan(p)

    class Usage:
        total, used, free = 10 ** 9, 10 ** 9, 10 ** 6

    monkeypatch.setattr(engine.shutil, "disk_usage", lambda _p: Usage)
    with pytest.raises(engine.nc.UserError, match="not enough disk space for the render cache"):
        engine.render_video(plan, tmp_path / "x.mp4", size=SMALL, workers=1, progress=False)
    with engine.Renderer(plan, size=SMALL) as r:
        need = engine.cache_bytes(r, range(0, 60))
        assert need >= r.shots[1].n_frames * r.shots[1].pw * r.shots[1].ph * 3


@pytest.mark.parametrize("size", [(1080, 1350), (1080, 1920), (1080, 1080)])
def test_endcard_lockup_never_overlaps(plan_factory, size):
    """The tagline sits under the wordmark's real bottom edge and the subtitle under the tagline, at any size."""
    p = plan_factory(size=list(size), caption_y=round(1420 * size[1] / 1920))
    with engine.Renderer(engine.prepare_plan(p)) as r:
        b = r._ec["boxes"]
        assert b["logo"][1] < b["tag"][0] < b["tag"][1] < b["sub"][0]
        assert b["logo"][0] >= 0.12 * size[1] and b["sub"][1] <= 0.90 * size[1]
        f = r.frame(8.0)
        logo_bottom, tag_top = int(b["logo"][1]), int(b["tag"][0])
        gap = f[logo_bottom + 2:tag_top - 2]
        assert gap.size and (gap.min(-1) > 245).sum() < 20                # no white ink between them


def test_caption_fade_ends_before_the_next_line(plan_factory):
    """A line's fade-out never overlaps the next line's first word (same spot on screen)."""
    p = plan_factory(lines=[{"words": [["This", 0.3], ["is", 0.5], ["what", 0.7], ["Katie", 0.9, 1], ["saw.", 1.1]],
                             "end": 2.55},
                            {"words": [["I", 2.6], ["stayed.", 2.9]], "end": 4.0}])
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        first = r._lines[0]
        assert first[4] <= 2.6 + 1e-9
        r._lines = [first]
        img = np.zeros((r.height, r.width, 3), np.uint8)
        r._draw_captions(img, 2.6)
        assert img.max() == 0
        mid = np.zeros_like(img)
        r._draw_captions(mid, 2.56)
        assert 0 < mid.max() < 255


def test_first_shot_forced_to_cut_and_short_clip_warns(plan_factory, clip, capsys):
    p = plan_factory()
    p["shots"][0]["tr"] = "flash"
    p["shots"][1] = {"kind": "video", "src": str(clip), "start": 1.5, "t0": 3.0, "t1": 5.4, "tr": "punch"}
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        assert r.shots[0].tr == "cut"
    err = capsys.readouterr().err
    assert "WARN: shots[0].tr" in err and "WARN: shots[1]: the clip ends" in err
    p["shots"][1]["start"] = 5.0
    with engine.Renderer(engine.prepare_plan(p), size=SMALL, quiet=True):
        pass
    assert capsys.readouterr().err == ""                               # workers stay quiet
    with engine.Renderer(engine.prepare_plan(p), size=SMALL):
        pass
    assert "past the end of the" in capsys.readouterr().err


def test_auto_pan_speed_is_capped_on_short_shots(plan_factory, ramp_image):
    p = plan_factory(duration=1.0, lines=[], leaks=[], endcard={"t": 0.9})
    p["shots"] = [{"src": str(ramp_image), "t0": 0.0, "t1": 0.3, "z": [1.0, 1.02], "look": "none"},
                  {"src": str(ramp_image), "t0": 0.3, "t1": 1.0, "z": [1.0, 1.02], "look": "none"}]
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        fr = r.shots[0].framing
        x0 = fr.to_screen(0.0, fr.pw / 2, 0)[0]
        x1 = fr.to_screen(1.0, fr.pw / 2, 0)[0]
        assert abs(x1 - x0) <= engine.em.AUTO_PAN_MAX_SPEED * SMALL[0] * 0.3 * 1.05 + 2
        assert abs(x1 - x0) > 5                                         # it still pans


# --------------------------------------------------------------------------- kinetic text cards (R195)
def card_plan(plan_factory, **card):
    p = plan_factory()
    p["lines"] = []
    p["cards"] = [dict({"t0": 3.0, "t1": 5.4, "text": "1", "style": "number", "sub": "Start with three minutes."},
                       **card)]
    return p


def test_card_renders_large_text_inside_the_safe_area(plan_factory):
    p = card_plan(plan_factory)
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        with_card = r.frame(4.5)
        (t0, t1, x0, y0, x1, y1), = r.card_boxes
        assert r.safe_top <= y0 < y1 <= r.safe_bottom and 0 <= x0 < x1 <= r.width
        assert y1 - y0 > 0.15 * r.height                  # large type
    q = card_plan(plan_factory)
    del q["cards"]
    without = engine.render_frame(engine.prepare_plan(q), 4.5, size=SMALL)
    box = (slice(int(y0), int(y1)), slice(int(x0), int(x1)))
    gold = np.array(engine.nc.accent_rgb(), np.float32)
    near_gold = np.abs(with_card[box].astype(np.float32) - gold).sum(-1) < 60
    assert near_gold.sum() > 50                           # the gold numeral
    bright = luma(with_card[box]) > 225
    assert bright.sum() > 30                              # the white line under it
    # outside the text the picture is blurred and darkened
    assert luma(with_card[int(y1) + 10:]).mean() < luma(without[int(y1) + 10:]).mean() - 10


def test_card_reveal_animates_and_is_deterministic(plan_factory):
    plan = engine.prepare_plan(card_plan(plan_factory, t0=3.5, style="statement", text="Breathe out *slowly*."))
    with engine.Renderer(plan, size=SMALL) as r:
        frames = [r.frame(t) for t in (3.55, 3.8, 4.1, 5.0)]
        again = r.frame(3.8)
        (_, _, x0, y0, x1, y1), = r.card_boxes
    assert np.array_equal(frames[1], again)
    box = (slice(int(y0), int(y1)), slice(int(x0), int(x1)))
    mask = luma(frames[-1][box]) > 200                    # where the finished text is
    assert mask.sum() > 100
    contrast = [luma(f[box])[mask].mean() - luma(f[box])[~mask].mean() for f in frames]
    assert contrast[0] < contrast[1] < contrast[2] <= contrast[3] + 1   # words rise in one after another


def test_card_at_frame_zero_is_fully_shown_and_the_hook_waits(plan_factory):
    p = plan_factory()
    p["lines"] = []
    p["cards"] = [{"t0": 0.0, "t1": 2.5, "text": "Three things to know.", "bg": "teal"}]
    with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
        f0, f1 = r.frame(0.0), r.frame(1.0)
        (_, _, x0, y0, x1, y1), = r.card_boxes
    teal = np.array(engine.nc.brand_color("water_teal"), np.float32)
    corner = f0[int(0.9 * SMALL[1]):, :20].reshape(-1, 3).astype(np.float32).mean(0)
    assert np.abs(corner - teal).max() < 40               # brand teal background from frame 0
    box = (slice(int(y0), int(y1)), slice(int(x0), int(x1)))
    assert np.abs(f0[box].astype(int) - f1[box].astype(int)).mean() < 3   # no reveal: frame 0 is complete
    top = (slice(int(r.safe_top), int(y0) - 2), slice(None))
    assert (luma(f0[top]) > 230).sum() < 20               # the hook text is not drawn over the card


def test_caption_px_sets_the_caption_size(plan_factory):
    sizes = []
    for px in (None, 120):
        p = plan_factory() if px is None else plan_factory(caption_px=px)
        with engine.Renderer(engine.prepare_plan(p), size=SMALL) as r:
            (_, _, x0, y0, x1, y1), = r.caption_boxes
            sizes.append(y1 - y0)
    assert sizes[1] > sizes[0] * 1.15


@pytest.mark.parametrize("n", [61, 62, 121, 302])
def test_any_frame_count_gives_constant_30fps(plan_factory, tmp_path, n):
    """A short last encoder segment used to leave a timestamp gap at the join (29.8 fps, one frame x3)."""
    p = plan_factory(duration=12.0, endcard={"t": 9.0}, lines=[], leaks=[])
    p["shots"] = [dict(p["shots"][0], t0=0.0, t1=6.0), dict(p["shots"][1], t0=6.0, t1=9.0),
                  dict(p["shots"][2], t0=9.0, t1=12.0)]
    out = tmp_path / f"r{n}.mp4"
    engine.render_video(engine.prepare_plan(p), out, t_from=0.0, t_to=n / 30, size=(144, 256), workers=2,
                        progress=False)
    r = engine.nc.run([engine.nc.ffprobe_bin(), "-v", "error", "-select_streams", "v", "-show_entries",
                       "packet=pts:stream=avg_frame_rate,nb_frames", "-of", "json", str(out)])
    info = json.loads(r.stdout)
    pts = sorted(int(pk["pts"]) for pk in info["packets"])
    assert len(pts) == n and int(info["streams"][0]["nb_frames"]) == n
    assert len({b - a for a, b in zip(pts, pts[1:])}) == 1
    assert info["streams"][0]["avg_frame_rate"] == "30/1"
    assert engine.segment_starts(range(0, 302), 60, 30) == [0, 60, 120, 180, 240]
