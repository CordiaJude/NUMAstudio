"""formats.py: reach cut, story set, carousel, cover, .srt and hook variants from one plan (R229-R237, R280)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import numa_common
import engine
import finish
import formats
import validate_plan

SMALL = [270, 480]


def frame_at(path: Path, t: float = 0.0) -> np.ndarray:
    """One decoded RGB frame of a video (at its own size)."""
    info = numa_common.media_info(path)
    w, h = info["width"], info["height"]
    proc = numa_common.run([numa_common.ffmpeg_bin(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(proc.stdout, np.uint8)[: w * h * 3].reshape(h, w, 3)


def small_plan(job, make_image, make_video, duration: float = 14.0) -> dict:
    """A 270x480 v2 plan: four photo shots, one clip, six caption lines, an end card on the ripple image."""
    names = ["cold-plunge.jpg", "breathwork-class.jpg", "red-light.jpg", "mats-bolsters.jpg"]
    photos = [str(make_image(job.raw / f"p{i}.jpg", size=(360, 640), photo=n)) for i, n in enumerate(names)]
    clip = str(make_video(job.raw / "c0.mp4", seconds=4.0, size=(270, 480)))
    hero = str(Path(numa_common.ASSETS_DIR) / "heroimage.jpg")
    cuts = [0.0, 2.0, 4.0, 6.5, 8.5, 10.0, duration]
    srcs = [photos[0], photos[1], clip, photos[2], photos[3], hero]
    trs = ["cut", "punch", "fade", "flash", "cut", "fade"]
    shots = []
    for i, src in enumerate(srcs):
        s = {"src": src, "t0": cuts[i], "t1": cuts[i + 1], "tr": trs[i], "z": [1.0, 1.1] if i % 2 else [1.1, 1.0]}
        if src == clip:
            s.update(kind="video", start=0.5)
        shots.append(s)
    shots[3]["peak"] = True

    def line(text, t0, end, gold=-1):
        ws = text.split()
        return {"words": [[w, round(t0 + 0.25 * k, 3)] + ([1] if k == (gold % len(ws)) else [])
                          for k, w in enumerate(ws)], "end": end}

    return {
        "schema_version": 2, "duration": duration, "out_dir": str(job.work), "fps": 30, "size": SMALL,
        "seed": 3, "caption_y": 355,
        "hook": {"text": "Your *first* plunge.", "t1": 2.0},
        "shots": shots,
        "lines": [line("The water is colder than you think.", 0.3, 1.9),
                  line("Your breath catches.", 2.1, 3.6),
                  line("Then it slows.", 3.8, 5.0),
                  line("Three minutes feels long.", 5.2, 6.9),
                  line("You walk out wide awake.", 7.1, 8.6),
                  line("This is NUMA.", 8.7, 9.8)],
        "endcard": {"t": 10.0, "tagline": "Wellness Collective", "subtitle": "Less noise. More presence."},
        "music": {"source": "folder", "path": None, "license": "NUMA's own track"},
        "meta": {"slug": "first-plunge", "title": "Cold, then calm"},
    }


@pytest.fixture
def small_job(job, make_image, make_video, make_audio, nc):
    """Plan + rendered and finished reel at 270x480 (job/out/first-plunge_reel.mp4)."""
    plan = small_plan(job, make_image, make_video)
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    make_audio(job.work / "master.wav", plan["duration"], kind="music")
    engine.render_video(str(plan_path), job.work / "video_noaudio.mp4", workers=2, progress=False)
    reel = job.out / "first-plunge_reel.mp4"
    finish.finish(job.work, reel, plan_path=plan_path, qa=False)
    return job, plan_path, reel


# --------------------------------------------------------------------------- pure functions
def test_srt_one_cue_per_line_with_plan_times(tmp_path):
    plan = {"lines": [{"words": [["Café", 0.3], ["*calm*", 0.6, 1]], "end": 1.8},
                      {"words": [["A", 2.0], ["very", 2.2], ["long", 2.4], ["line", 2.6], ["that", 2.8], ["wraps", 3.0],
                                 ["onto", 3.2], ["two", 3.4], ["rows", 3.6], ["for", 3.8], ["players.", 4.0]],
                       "end": 4.5}]}
    cues = formats.srt_cues(plan, None)
    p = formats.write_srt(tmp_path / "x.srt", cues)
    text = p.read_bytes().decode("utf-8")
    assert not text.startswith("﻿")
    back = formats.parse_srt(text)
    assert len(back) == 2
    assert back[0] == (0.3, 1.8, "Café calm")
    assert back[1][:2] == (2.0, 4.5)
    assert text.splitlines()[:3] == ["1", "00:00:00,300 --> 00:00:01,800", "Café calm"]
    rows = text.split("\n\n")[1].splitlines()[2:]
    assert len(rows) == 2 and all(len(r) <= formats.SRT_ROW_CHARS for r in rows)


def test_srt_clips_overlap_and_falls_back_to_transcript():
    plan = {"lines": [{"words": [["One.", 0.0]], "end": 2.5}, {"words": [["Two.", 2.0]], "end": 3.0}]}
    cues = formats.srt_cues(plan, None)
    assert cues[0][1] == 2.0                         # one cue on screen at a time
    analysis = {"words": [{"w": "Hello", "appear": 0.5, "end": 0.8}, {"w": "there.", "appear": 0.9, "end": 1.2},
                          {"w": "Breathe", "appear": 2.0, "end": 2.4}, {"w": "out.", "appear": 2.5, "end": 2.9}]}
    cues = formats.srt_cues({"lines": []}, analysis)
    assert [c[2] for c in cues] == ["Hello there.", "Breathe out."]
    assert cues[0][:2] == (0.5, 1.2)
    assert formats.srt_time(3723.4567) == "01:02:03,457"


def test_shorten_and_markup():
    assert formats.shorten("Short one.") == "Short one."
    s = formats.shorten("Three minutes feels long, until it is over and you walk out into the morning light")
    assert s == "Three minutes feels long"
    long_word_run = formats.shorten("word " * 30)
    assert len(long_word_run) <= formats.SHORT_CAPTION_CHARS + 1 and long_word_run.endswith("…")
    w = formats.text_words("Your *first* plunge.", 1.0)
    assert [x[0] for x in w] == ["Your", "first", "plunge."] and w[1][2] == 1 and len(w[0]) == 2


def test_clip_plan_retiles_shifts_and_validates(job, make_image, make_video, nc):
    plan = engine.prepare_plan(small_plan(job, make_image, make_video), job.work)
    d = formats.clip_plan(plan, 3.0, 9.0)
    shots = d["shots"]
    assert d["duration"] == 6.0 and shots[0]["t0"] == 0.0 and shots[-1]["t1"] == 6.0 and shots[0]["tr"] == "cut"
    assert all(abs(a["t1"] - b["t0"]) < 1e-9 for a, b in zip(shots, shots[1:]))
    # the clipped first shot (photo 1, 2-4 s) keeps its zoom path; the clip's start is unchanged (it starts at 4)
    assert shots[0]["src"] == plan["shots"][1]["src"] and 1.0 < shots[0]["z"][0] < 1.1
    vid = next(s for s in shots if s.get("kind") == "video")
    assert vid["t0"] == 1.0 and vid["start"] == 0.5
    d2 = formats.clip_plan(plan, 5.0, 9.0)
    assert d2["shots"][0]["kind"] == "video" and d2["shots"][0]["start"] == pytest.approx(1.5)
    # captions: words before the window are dropped, times shift by -3
    firsts = [ln["words"][0] for ln in d["lines"]]
    assert firsts[0] == ["Then", pytest.approx(0.8)]     # "Your breath catches." (2.1-2.6 s) is before the window
    assert [w[0] for w in d["lines"][-1]["words"]] == ["This"]   # words in the last 50 ms are cut
    assert all(ln["end"] <= d["duration"] for ln in d["lines"])
    assert "endcard" not in d and "hook" not in d
    errs = [i for i in validate_plan.validate(d) if i.level == "ERROR"]
    assert not errs, errs


def test_reach_plan_appends_endcard_tail(job, make_image, make_video, nc):
    plan = engine.prepare_plan(small_plan(job, make_image, make_video), job.work)
    d, segs = formats.reach_plan(plan, {"t0": 0.0, "t1": 8.5, "hook": "Three minutes. That's all."})
    assert segs == [(0.0, 8.5), (10.0, 10.0 + d["duration"] - 8.5)]
    assert 8.0 <= d["duration"] <= 12.0 and d["duration"] - 8.5 >= formats.ENDCARD_TAIL_MIN_S
    assert d["endcard"]["t"] == 8.5 and d["shots"][-1]["src"].endswith("heroimage.jpg")
    assert d["hook"]["text"] == "Three minutes. That's all." and d["hook"]["t1"] >= 1.5
    # a window that already holds the end card keeps it and gets no tail
    d2, segs2 = formats.reach_plan(plan, {"t0": 3.0, "t1": 14.0, "hook": "New"})
    assert segs2 == [(3.0, 14.0)] and d2["endcard"]["t"] == 7.0 and d2["duration"] == 11.0
    for x in (d, d2):
        errs = [i for i in validate_plan.validate(x) if i.level == "ERROR" and i.rule != 29]
        assert not errs, errs


def test_defaults_fill_every_missing_format(job, make_image, make_video, nc):
    plan = engine.prepare_plan(small_plan(job, make_image, make_video), job.work)
    warnings = []
    fm, defaulted = formats.resolve_formats(plan, set(formats.KINDS), warnings)
    assert set(defaulted) == {"reach_cut", "story", "carousel", "cover", "hook_variants"}
    rc = fm["reach_cut"]
    assert 8.0 <= rc["t1"] - rc["t0"] <= 12.0 and rc["hook"] == "Cold, then calm"
    assert 3 <= len(fm["story"]) <= 5 and len({formats.norm(s["text"]) for s in fm["story"]}) == len(fm["story"])
    assert 5 <= len(fm["carousel"]) <= 8
    assert all(len(c["text"]) <= formats.SHORT_CAPTION_CHARS + 1 for c in fm["carousel"])
    assert fm["cover"]["title"] == "Cold, then calm"
    hv = fm["hook_variants"]
    assert 2 <= len(hv) <= 3
    keys = {(formats.norm(h["text"]), h.get("src", plan["shots"][0]["src"])) for h in hv}
    assert len(keys) == len(hv) and (formats.norm(plan["hook"]["text"]), plan["shots"][0]["src"]) not in keys
    assert any(h.get("src") for h in hv)            # one opening with a different first shot
    formats.check_formats(plan, fm)                 # schema + rules 27/36 pass
    # a plan entry is used as given and padded to two hook variants
    plan["formats"] = {"hook_variants": [{"text": "Colder than you think."}]}
    fm2, defaulted2 = formats.resolve_formats(plan, {"hooks"}, [])
    assert fm2["hook_variants"][0] == {"text": "Colder than you think."} and len(fm2["hook_variants"]) >= 2


def test_formats_claims_and_times_are_checked(job, make_image, make_video, nc):
    plan = engine.prepare_plan(small_plan(job, make_image, make_video), job.work)
    with pytest.raises(numa_common.UserError, match="rule 27"):
        formats.check_formats(plan, {"cover": {"t": 1.0, "title": "Detox your body"}})
    with pytest.raises(numa_common.UserError, match="rule 36"):
        formats.check_formats(plan, {"reach_cut": {"t0": 0.0, "t1": 5.0, "hook": "Too short"}})


# --------------------------------------------------------------------------- real size stills
def test_cover_title_inside_centre_square_and_carousel_size_real(plan_factory, job, nc, tmp_path):
    plan = plan_factory()
    plan["formats"] = {"cover": {"t": 1.0, "title": "Three minutes of *cold*, then calm"}}
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    sec = formats.run(plan_path, job.out / "test-reel_reel.mp4", only=["cover", "carousel"], progress=False)
    cover = job.out / "test-reel_cover.jpg"
    assert sec["outputs"]["cover"]["files"] == [str(cover)]
    with Image.open(cover) as im:
        assert im.size == (1080, 1920)
        with_title = np.asarray(im.convert("RGB")).astype(np.int16)
    slides = sec["outputs"]["carousel"]["files"]
    assert 5 <= len(slides) <= 8
    for f in slides:
        with Image.open(f) as im:
            assert im.size == (1080, 1350)
    # title pixels: where the cover is clearly brighter than the same frame without a title
    prepared = engine.prepare_plan(plan, job.work)
    bare = formats._base(prepared)
    no_title = engine.render_frame(bare, formats.still_time(prepared, 1.0)).astype(np.int16)
    ink = (with_title - no_title).max(axis=2) > 60
    rows = np.nonzero(ink.any(axis=1))[0]
    assert rows.size > 0
    assert rows.min() >= 420 and rows.max() <= 1500, (rows.min(), rows.max())
    # deterministic: a second run writes the same bytes
    first = hashlib.sha256(cover.read_bytes()).hexdigest()
    formats.run(plan_path, job.out / "test-reel_reel.mp4", only=["cover"], progress=False)
    assert hashlib.sha256(cover.read_bytes()).hexdigest() == first
    # report merged: the carousel section from the first run survives a cover-only run
    rep = json.loads((job.out / "report.json").read_text())["formats"]
    assert set(rep["outputs"]) == {"carousel", "cover"} and len(rep["files"]) == 1 + len(slides)


def test_cover_title_too_long_is_a_clean_error(plan_factory, job, nc):
    plan = plan_factory()
    plan["formats"] = {"cover": {"t": 1.0, "title": " ".join(["Breathe in slowly and let the cold settle"] * 4)}}
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    with pytest.raises(numa_common.UserError, match="centre square"):
        formats.run(plan_path, job.out / "x.mp4", only=["cover"], progress=False)


# --------------------------------------------------------------------------- end to end, small size
def test_full_run_small(small_job, run_script, nc):
    job, plan_path, reel = small_job
    plan = json.loads(plan_path.read_text())
    clip_src = plan["shots"][0]["src"]
    plan["formats"] = {
        "reach_cut": {"t0": 2.0, "t1": 10.5, "hook": "Three minutes. *Wide* awake."},
        "story": [{"t": 1.5, "text": "Colder than you think."}, {"t": 5.5, "text": "Breathe *slow*."},
                  {"t": 7.5, "text": "Walk out awake.", "clip": True}],
        "carousel": [{"t": 1.0, "text": "Your *first* plunge."}, {"src": clip_src, "text": "The water"},
                     {"t": 3.0, "text": "The breath"}, {"t": 7.0, "text": "The calm"}, {"t": 9.0, "text": "Come in"}],
    }
    numa_common.write_json(plan_path, plan)
    stale = job.out / "first-plunge_story_9.jpg"
    stale.write_bytes(b"old")
    res = run_script("formats.py", plan_path, reel, "--json", timeout=600)
    assert res.returncode == 0, res.stderr
    sec = json.loads(res.stdout)
    out = sec["outputs"]
    assert not stale.exists()

    reach = Path(out["reach"]["files"][0])
    info = numa_common.media_info(reach)
    assert (info["width"], info["height"]) == tuple(SMALL) and info["has_audio"]
    assert 8.0 <= info["duration"] <= 12.0 and info["duration"] == pytest.approx(10.5 - 2.0 + 2.0, abs=0.05)
    assert sec["checks"][reach.name]["ok"], sec["checks"][reach.name]
    # the new hook text is on frame 0: the top band differs from the same frame rendered without it
    d, _ = formats.reach_plan(engine.load_plan(plan_path), plan["formats"]["reach_cut"])
    bare = dict(d)
    bare.pop("hook")
    top = slice(0, int(0.3 * SMALL[1]))
    diff = np.abs(frame_at(reach).astype(int) - engine.render_frame(bare, 0.0).astype(int))[top].mean()
    assert diff > 4.0, diff

    stories = out["story"]["files"]
    assert [Path(f).suffix for f in stories] == [".jpg", ".jpg", ".mp4"]
    for f in stories[:2]:
        with Image.open(f) as im:
            assert im.size == tuple(SMALL)
    sinfo = numa_common.media_info(stories[2])
    assert sinfo["duration"] == pytest.approx(5.0, abs=0.05) and sec["checks"][Path(stories[2]).name]["ok"]

    slides = out["carousel"]["files"]
    assert len(slides) == 5
    for f in slides:
        with Image.open(f) as im:
            assert im.size == (270, 338)

    with Image.open(out["cover"]["files"][0]) as im:
        assert im.size == tuple(SMALL)

    srt = Path(out["srt"]["files"][0])
    cues = formats.parse_srt(srt.read_text(encoding="utf-8"))
    assert len(cues) == len(plan["lines"])
    for (a, b, text), ln in zip(cues, plan["lines"]):
        assert a == pytest.approx(ln["words"][0][1], abs=1e-3) and b == pytest.approx(ln["end"], abs=1e-3)
        assert text == " ".join(w[0] for w in ln["words"])

    hooks = out["hooks"]["files"]
    assert 2 <= len(hooks) <= 3
    for f in hooks:
        hi = numa_common.media_info(f)
        assert 3.0 - 0.05 <= hi["duration"] <= 5.0 + 0.05 and sec["checks"][Path(f).name]["ok"]
    assert len({hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in hooks}) == len(hooks)

    report = json.loads((job.out / "report.json").read_text())
    assert "finish" in report and report["formats"]["ok"] is True
    assert reach.name in report["check_output"]
    assert set(report["formats"]["files"]) == {str(Path(f)) for k in out for f in out[k]["files"]}

    # an --only re-run keeps the other kinds in the report
    res2 = run_script("formats.py", plan_path, reel, "--only", "srt", timeout=120)
    assert res2.returncode == 0, res2.stderr
    rep2 = json.loads((job.out / "report.json").read_text())["formats"]
    assert set(rep2["outputs"]) == set(formats.KINDS) and str(reach) in rep2["files"]
    assert reach.name in rep2["checks"]


def test_draft_passes_through(small_job, nc):
    job, plan_path, reel = small_job
    sec = formats.run(plan_path, reel, out_dir=job.out / "draft", only=["hooks", "carousel"], draft=True,
                      progress=False)
    f = sec["outputs"]["hooks"]["files"][0]
    info = numa_common.media_info(f)
    k = numa_common.config_value("render.draft.scale")
    assert (info["width"], info["height"]) == (engine._even(SMALL[0] * k), engine._even(SMALL[1] * k))
    with Image.open(sec["outputs"]["carousel"]["files"][0]) as im:
        assert im.size == (engine._even(270 * k), engine._even(338 * k))
    assert sec["draft"] is True and sec["ok"], sec["checks"]


# --------------------------------------------------------------------------- CLI
def test_cli_usage_and_errors(run_script, tmp_path, job, make_image, make_video, nc):
    res = run_script("formats.py")
    assert res.returncode == 2 and "ERROR:" in res.stderr and "usage" in res.stderr.lower()
    res = run_script("formats.py", tmp_path / "missing.json", tmp_path / "r.mp4")
    assert res.returncode == 1 and res.stderr.strip().startswith("ERROR:") and "Traceback" not in res.stderr
    plan = small_plan(job, make_image, make_video)
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    res = run_script("formats.py", plan_path, job.out / "r.mp4", "--only", "story,gif")
    assert res.returncode == 2 and "gif" in res.stderr
    # no reel and no master.wav: the video formats have no sound to cut
    res = run_script("formats.py", plan_path, job.out / "r.mp4", "--only", "reach")
    assert res.returncode == 1 and "no audio" in res.stderr and "Traceback" not in res.stderr
    bad = copy.deepcopy(plan)
    bad["formats"] = {"story": [{"t": 1.0, "text": "Detox in three minutes"}, {"t": 2.0, "text": "b"},
                                {"t": 3.0, "text": "c"}]}
    numa_common.write_json(plan_path, bad)
    res = run_script("formats.py", plan_path, job.out / "r.mp4", "--only", "story")
    assert res.returncode == 1 and "rule 27" in res.stderr
