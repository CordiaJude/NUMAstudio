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


def test_sentences_fit_text_and_markup():
    plan = {"lines": [{"words": [["I", 3.24], ["don't", 3.5], ["know", 3.8], ["how", 4.0], ["she", 4.2], ["does", 4.4],
                                 ["it,", 4.6]], "end": 5.06},
                      {"words": [["but", 5.38], ["she", 5.6], ["does.", 5.9]], "end": 6.96},
                      {"words": [["and", 7.0], ["then", 7.2]], "end": 8.0}]}
    ss = formats.sentences(plan)
    assert [s["text"] for s in ss] == ["I don't know how she does it, but she does.", "and then"]
    assert ss[0]["complete"] and not ss[1]["complete"]
    assert ss[0]["first"] == 3.24 and ss[0]["last_line"] == 5.38 and ss[0]["end"] == 6.96
    assert formats.fit_text("Short one.", 48) == "Short one."
    assert formats.fit_text("Three minutes feels long, until it is over and you walk out into the light.", 30) \
        == "Three minutes feels long."      # a whole first clause, never an ellipsis
    assert formats.fit_text("but she does.", 48) is None and formats.fit_text("no ending", 48) is None
    assert formats.fit_text("Breathe in slowly and let the cold settle around you now.", 30) is None  # no clause
    w = formats.text_words("Your *first* plunge.", 1.0)
    assert [x[0] for x in w] == ["Your", "first", "plunge."] and w[1][2] == 1 and len(w[0]) == 2


YEAR_ONE_LINES = [("This is what Katie saw.", 0.68, 2.74), ("I don't know how she does it,", 3.24, 5.06),
                  ("but she does.", 5.38, 6.96), ("We took a chance.", 7.38, 9.5),
                  ("It's been one whole year", 10.76, 13.5), ("and now we're beginning to see.", 15.11, 18.01),
                  ("We are so grateful for you, Mobile.", 19.3, 21.9),
                  ("Thank you for making this year awesome.", 22.6, 26.22),
                  ("Looking forward to so many more.", 27.02, 29.9)]


def year_one_like(job, make_image, lines=True) -> dict:
    """38.97 s, eight photo shots, the end card at 34.71 s on the ripple image, Year One's caption lines."""
    names = ["cold-plunge.jpg", "breathwork-class.jpg", "red-light.jpg", "mats-bolsters.jpg", "sauna-people.jpg"]
    photos = [str(make_image(job.raw / f"y{i}.jpg", size=(360, 640), photo=n)) for i, n in enumerate(names)]
    cuts = [0.0, 3.0, 7.2, 10.6, 15.0, 19.1, 22.4, 26.8, 34.71, 38.97]
    srcs = photos + photos[:3] + [str(Path(numa_common.ASSETS_DIR) / "heroimage.jpg")]
    shots = [{"src": src, "t0": cuts[i], "t1": cuts[i + 1], "tr": "cut" if i in (0, 4) else "fade"}
             for i, src in enumerate(srcs)]

    def line(text, t0, end):
        ws = text.split()
        step = min(0.3, (end - t0 - 0.2) / len(ws))
        return {"words": [[w, round(t0 + step * k, 3)] for k, w in enumerate(ws)], "end": end}

    return {"schema_version": 2, "duration": 38.97, "out_dir": str(job.work), "fps": 30, "size": SMALL,
            "caption_y": 355, "hook": {"text": "This is what Katie saw.", "t1": 2.0}, "shots": shots,
            "lines": [line(*x) for x in YEAR_ONE_LINES] if lines else [],
            "endcard": {"t": 34.71, "tagline": "Wellness Collective", "subtitle": "Less noise. More presence."},
            "music": {"source": "folder", "path": None, "license": "NUMA's own track"}, "meta": {"slug": "year-one"}}


def test_default_texts_are_whole_sentences(job, make_image, nc):
    plan = engine.prepare_plan(year_one_like(job, make_image), job.work)
    fm, defaulted, skipped = formats.resolve_formats(plan, set(formats.KINDS), [])
    assert not skipped
    texts = [fm["reach_cut"]["hook"], fm["cover"]["title"]] + [s["text"] for s in fm["story"]] + \
        [c["text"] for c in fm["carousel"]] + [h["text"] for h in fm["hook_variants"]]
    banned = {"wellness collective", "less noise more presence"}
    for t in texts:
        p = formats.plain(t)
        assert not p[0].islower() and not p.endswith(",") and p[-1] in ".?!\u2026", p
        assert formats.norm(p) not in banned
    assert "I don't know how she does it, but she does." in texts       # two caption lines joined
    assert formats.norm(fm["reach_cut"]["hook"]) != formats.norm(plan["hook"]["text"])
    sents = {s["text"]: s for s in formats.sentences(plan)}
    for st in fm["story"]:                       # each still sits on its sentence's last line
        s = sents[st["text"]]
        assert s["last_line"] - 1e-6 <= st["t"] <= s["end"] + 1e-6
    for c in fm["carousel"][1:]:                 # slides are near when their sentence is spoken
        s = sents[c["text"]]
        assert s["first"] - 1e-6 <= c["t"] <= s["end"] + 1e-6



# a sentence with commas that wraps to 3 caption rows whole (64 characters), one without a clause break
# that still wraps to 3 rows (62 characters: the CI voice's transcript of the voice_and_music case), and
# a 38-word sentence with no clause break; each spread over caption lines that fit on their own
LONG_LINES = [("This is what Katie saw.", 0.68, 2.74), ("I don't know how she does it,", 3.24, 5.06),
              ("but she does.", 5.38, 6.96),
              ("Heat first, then the cold plunge,", 7.38, 8.6), ("breathe slow and stay with it.", 8.7, 9.9),
              ("Heat first then the cold plunge", 10.76, 13.5), ("breathe slow and stay with it.", 15.11, 18.01),
              ("Every single morning we open the doors early so that the people", 19.3, 20.5),
              ("of this town can come in out of the heat and sit in", 20.6, 21.8),
              ("the quiet room for as long as they would like before work begins.", 21.9, 23.0),
              ("We took a chance.", 23.2, 26.2), ("Looking forward to so many more.", 27.02, 29.9)]


def test_default_story_and_carousel_text_always_fits_the_caption_rows(job, make_image, nc):
    plan = year_one_like(job, make_image)
    plan["lines"] = [{"words": [[w, round(t0 + min(0.3, (end - t0 - 0.2) / len(text.split())) * k, 3)]
                                for k, w in enumerate(text.split())], "end": end} for text, t0, end in LONG_LINES]
    plan = engine.prepare_plan(plan, job.work)
    fits = formats.caption_fit(plan)
    whole_commas = "Heat first, then the cold plunge, breathe slow and stay with it."
    no_clause = "Heat first then the cold plunge breathe slow and stay with it."
    assert not fits(whole_commas) and not fits(no_clause)          # rule 22's measure: 3 rows each
    assert len(" ".join(LONG_LINES[7][0].split() + LONG_LINES[8][0].split() + LONG_LINES[9][0].split()).split()) >= 25
    warnings = []
    fm, defaulted, skipped = formats.resolve_formats(plan, {"story", "carousel"}, warnings)
    assert not skipped and set(defaulted) == {"story", "carousel"}, warnings
    texts = [x["text"] for x in fm["story"] + fm["carousel"]]
    # the commas sentence is shortened to its leading whole clauses, the others are left out with a WARN
    assert "Heat first, then the cold plunge." in texts
    assert not any(formats.norm(t) in (formats.norm(whole_commas), formats.norm(no_clause)) for t in texts)
    assert not any("Every single morning" in t for t in texts)
    for kind in ("story", "carousel"):
        notes = [w for w in warnings if w.startswith(f"{kind}: left out")]
        assert any("Heat first then the cold plunge" in w for w in notes), warnings
        assert any("Every single morning" in w for w in notes), warnings
    # every default still passes validate_plan (rule 22 included) as formats renders it: never an ERROR
    for n, st in enumerate(fm["story"], 1):
        t = formats.still_time(plan, st["t"])
        formats.check_derived(formats.still_plan(plan, t, st["text"]), f"story {n}", [], still=True)
    for n, c in enumerate(fm["carousel"], 1):
        t = formats.still_time(plan, c["t"])
        formats.check_derived(formats.still_plan(plan, t, c["text"]), f"carousel {n}", [], still=True)
    # the same choice when baseline_plan writes the defaults into the plan
    assert [x["text"] for x in formats.default_story(plan)] == [x["text"] for x in fm["story"]]


def test_plan_supplied_story_text_too_long_is_still_an_error(job, make_image, nc):
    plan = year_one_like(job, make_image)
    plan["formats"] = {"story": [{"t": 1.5, "text": "Heat first then the cold plunge breathe slow and stay with it."},
                                 {"t": 5.5, "text": "But she does."}, {"t": 28.0, "text": "So many more."}]}
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    with pytest.raises(numa_common.UserError, match=r"story 1: .*rule 22"):
        formats.run(plan_path, job.out / "year-one_reel.mp4", only=["story"], progress=False)


def test_fit_text_keeps_the_longest_whole_clause_run_that_fits():
    t = "Heat first, then the cold plunge, breathe slow and stay with it."
    assert formats.fit_text(t, 64) == t                                  # characters alone allow it
    plan = {"size": [1080, 1920]}

    def full_size(x):                                                    # rows at the plan's own caption size
        return formats._rows_fit(plan, x, None)
    assert formats.fit_text(t, 64, full_size) == "Heat first, then the cold plunge."
    assert formats.fit_text(t, 20, full_size) == "Heat first."
    assert formats.fit_text("Heat first then the cold plunge breathe slow and stay with it.", 64, full_size) is None
    # a still may shrink its caption to the floor size instead: the whole sentence fits then
    assert formats.fit_text(t, 64, formats.caption_fit(plan)) == t


CI_SENTENCE = "He first then the cold plunge breathe solo and stay with it."   # CI's voice_and_music transcript


def full_size_plan(job, make_image, lines) -> dict:
    """year_one_like at the real 1080x1920 plan size with the given (text, first, end) caption lines."""
    plan = year_one_like(job, make_image)
    plan.update(size=[1080, 1920], caption_y=1420)

    def line(text, t0, end):
        ws = text.split()
        step = min(0.3, (end - t0 - 0.2) / len(ws))
        return {"words": [[w, round(t0 + step * k, 3)] for k, w in enumerate(ws)], "end": end}
    plan["lines"] = [line(*x) for x in lines]
    return engine.prepare_plan(plan, job.work)


def test_still_text_shrinks_to_fit_before_it_is_dropped(job, make_image, nc):
    # CI's three voice sentences: the 12-word one wraps to 3 rows at 92 px; at 76 px it fits in 2
    plan = full_size_plan(job, make_image, [("Welcome to moon mobile.", 0.68, 2.6), (CI_SENTENCE, 3.24, 8.5),
                                            ("This is how you reset.", 10.76, 13.5)])
    assert not formats._rows_fit(plan, CI_SENTENCE, None)
    assert formats.still_caption_px(plan, CI_SENTENCE) == (True, 76.0)
    assert formats.still_caption_px(plan, "This is how you reset.") == (True, None)    # fits as it is
    too_long = " ".join(["Breathe in slowly and let the cold settle"] * 3) + "."
    assert formats.still_caption_px(plan, too_long) == (False, None)                    # not even at 64 px
    warnings = []
    fm, _, skipped = formats.resolve_formats(plan, {"story", "carousel"}, warnings)
    # story: all three sentences, the long one with a smaller caption; never left out
    assert "story" not in skipped and [x["text"] for x in fm["story"]] == \
        ["Welcome to moon mobile.", CI_SENTENCE, "This is how you reset."]
    assert all(x[formats.FIT_KEY] for x in fm["story"])
    assert not any("left out" in w for w in warnings), warnings
    for n, st in enumerate(fm["story"], 1):
        t = formats.still_time(plan, st["t"])
        d = formats.still_plan(plan, t, st["text"], fit=True)
        assert d.get("caption_px") == (76.0 if st["text"] == CI_SENTENCE else None)
        formats.check_derived(d, f"story {n}", [], still=True)                       # no rule 22 ERROR
    # carousel: the same sentence fits its rows too (it is only longer than a short carousel caption);
    # three sentences, one of them the hook, cannot make five slides: skipped with the reason
    t = formats.still_time(plan, 5.0)
    formats.check_derived(formats.still_plan(plan, t, CI_SENTENCE, fit=True), "carousel 1", [], still=True)
    assert "carousel" in skipped and any(w.startswith("carousel: skipped: only") for w in warnings)
    # plan-supplied text keeps the plan's caption size, so it stays a rule 22 ERROR
    with pytest.raises(numa_common.UserError, match="rule 22"):
        formats.check_derived(formats.still_plan(plan, t, CI_SENTENCE), "story 1", [], still=True)


def test_story_set_and_carousel_made_when_there_are_enough_sentences(job, make_image, nc):
    lines = [("Welcome to moon mobile.", 0.68, 2.6), (CI_SENTENCE, 3.24, 6.9), ("We took a chance.", 7.38, 9.5),
             ("Rest between rounds.", 10.76, 13.5), ("Leave lighter than you came.", 15.11, 18.01),
             ("This is how you reset.", 19.3, 21.9), ("Come try it in Mobile.", 22.6, 26.22)]
    plan = full_size_plan(job, make_image, lines)
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    sec = formats.run(plan_path, job.out / "year-one_reel.mp4", only=["story", "carousel"], progress=False)
    assert sec["ok"] and not sec["skipped"], sec
    assert 3 <= len(sec["outputs"]["story"]["files"]) <= 5
    assert 5 <= len(sec["outputs"]["carousel"]["files"]) <= 8
    # the long sentence is a candidate (at a smaller caption), not left out
    cands = formats.sentence_texts(plan, formats.STORY_TEXT_CHARS, fits=formats.caption_fit(plan))
    assert CI_SENTENCE in [t for _, t in cands]


def test_reach_window_never_cuts_a_caption_and_avoids_a_tiny_last_segment(job, make_image, nc):
    plan = engine.prepare_plan(year_one_like(job, make_image), job.work)
    warnings = []
    a, b = formats.snap_reach_window(plan, 19.09, 29.16, warnings)   # ends on "Looking forward to"
    assert (a, b) == (19.09, 30.2) and not warnings
    lo, hi = formats.snap_reach_window(plan, 0.0, 11.5)              # cuts "It's been one whole year" at the end
    assert 8.0 <= hi - lo <= 12.0
    assert not any(f < hi - 0.05 and e + 0.3 > hi + 0.01 for _, f, e in YEAR_ONE_LINES)
    assert not any(f < lo and e > lo + 0.05 for _, f, e in YEAR_ONE_LINES)
    # 19.09-29.16 is 302 frames: the last 2 s encoder segment would be 2 frames long
    assert formats._bad_tail_frames(29.16 - 19.09, 30) == 2
    d, segs = formats.reach_plan(plan, {"t0": 19.09, "t1": 29.16, "hook": "One whole year."})
    assert formats._bad_tail_frames(d["duration"], 30) == 0 and 8.0 <= d["duration"] <= 12.0
    assert segs[0][1] - segs[0][0] == pytest.approx(d["duration"])
    # frame 0 shows the hook only: no caption inside the hook window, none repeating the hook
    gone = d["hook"]["t1"] + 0.3
    assert all(ln["words"][0][1] >= gone for ln in d["lines"])
    hv = formats.hook_variant_plan(plan, {"text": "One whole year."}, formats.opening_length(plan))
    assert all(formats.norm(formats.line_text(ln)) != formats.norm("This is what Katie saw.") for ln in hv["lines"])


def test_music_only_plan_skips_what_it_cannot_make(job, make_image, nc):
    plan = engine.prepare_plan(year_one_like(job, make_image, lines=False), job.work)
    warnings = []
    fm, defaulted, skipped = formats.resolve_formats(plan, set(formats.KINDS), warnings)
    assert skipped == {"reach", "story", "carousel"} and "cover" in fm      # never the reel's own hook
    assert all(w.split(":")[0] in ("reach", "story", "carousel", "hook variants") for w in warnings)
    # a shoot-card script gives the reach cut new hook text
    (job.work / "script.txt").write_text("This is what Katie saw. One year of NUMA in Mobile.", encoding="utf-8")
    fm, _, skipped = formats.resolve_formats(plan, {"reach"}, [], job.work)
    assert not skipped and fm["reach_cut"]["hook"] == "One year of NUMA in Mobile."


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
    fm, defaulted, skipped = formats.resolve_formats(plan, set(formats.KINDS), warnings)
    assert not skipped and set(defaulted) == {"reach_cut", "story", "carousel", "cover", "hook_variants"}
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
    fm2, defaulted2, _ = formats.resolve_formats(plan, {"hooks"}, [])
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
    plan["formats"] = {"cover": {"t": 1.0, "title": "Three minutes of *cold*, then calm"},
                       "carousel": [{"t": t, "text": x} for t, x in ((0.8, "Cold."), (2.0, "Breathe."), (3.5, "Slow."),
                                                                  (4.5, "Calm."), (5.0, "Awake."))]}
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
        "reach_cut": {"t0": 1.0, "t1": 9.5, "hook": "Three minutes. *Wide* awake."},
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
    assert 8.0 <= info["duration"] <= 12.0 and info["duration"] == pytest.approx(10.0 - 1.0 + 3.0, abs=0.05)
    # t1 9.5 cut "This is NUMA." (8.7-9.8 s): played out to the end card at 10 s, then the end-card tail
    assert sec["outputs"]["reach"]["spec"]["t1"] == 10.0
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


# --------------------------------------------------------------------------- polish P2
def test_reach_defence_warns_when_it_lengthens_the_window(job, make_image, nc):
    plan = engine.prepare_plan(year_one_like(job, make_image), job.work)
    warnings: list[str] = []
    d, _ = formats.reach_plan(plan, {"t0": 19.09, "t1": 29.16, "hook": "One whole year."}, warnings)
    assert d["duration"] > 29.16 - 19.09 + 0.01
    assert any("lengthened" in w and "10.07 s" in w for w in warnings), warnings
    quiet: list[str] = []
    formats.reach_plan(plan, {"t0": 0.0, "t1": 10.0, "hook": "One whole year."}, quiet)   # 300 frames: no change
    assert not any("lengthened" in w for w in quiet)


def test_reach_drops_an_early_caption_that_repeats_its_hook():
    def ln(text, t0):
        return {"words": [[w, round(t0 + 0.2 * k, 3)] for k, w in enumerate(text.split())], "end": t0 + 1.5}
    d = {"hook": {"text": "Three minutes. *Wide* awake.", "t1": 2.0},
         "lines": [ln("You walk out wide awake.", 2.4), ln("Three minutes feels long.", 3.2),
                   ln("Wide awake.", 5.0), ln("Then it slows.", 6.0)]}
    out = formats.clear_hook_window(copy.deepcopy(d), formats.REPEAT_WINDOW_S)
    texts = [formats.line_text(x) for x in out["lines"]]
    assert texts == ["Wide awake.", "Then it slows."]          # repeats inside the first 4 s are gone
    assert len(formats.clear_hook_window(copy.deepcopy(d))["lines"]) == 4   # hook variants: unchanged
    assert formats.repeats("Wide awake.", "You walk out wide awake.")
    assert formats.repeats("You walk out wide awake.", "Three minutes. Wide awake.")
    assert not formats.repeats("Then it slows.", "Three minutes. Wide awake.")


def test_default_carousel_never_puts_the_same_picture_side_by_side(job, make_image, nc):
    plan = year_one_like(job, make_image)
    # shots 2-4 show one photo, a re-saved copy of it and the photo again: a near-duplicate run
    same = plan["shots"][2]["src"]
    with Image.open(same) as im:
        np_im = np.asarray(im).astype(np.int16)
    copy_path = job.raw / "y2-copy.jpg"
    Image.fromarray(np.clip(np_im + 6, 0, 255).astype(np.uint8)).save(copy_path, quality=80)
    plan["shots"][3]["src"] = str(copy_path)
    plan["shots"][4]["src"] = same
    plan = engine.prepare_plan(plan, job.work)
    assert formats.same_picture(plan, 8.0, 12.0) and formats.same_picture(plan, 8.0, 17.0)
    assert not formats.same_picture(plan, 1.0, 5.0)
    slides = formats.default_carousel(plan)
    assert 5 <= len(slides) <= 8
    for a, b in zip(slides, slides[1:]):
        assert not formats.same_picture(plan, a["t"], b["t"]), (a, b)
    assert all("…" not in s["text"] for s in slides)


def test_report_lists_skipped_outputs_and_ok_means_requested_succeeded(job, make_image, nc):
    plan = year_one_like(job, make_image, lines=False)
    plan_path = job.work / "plan.json"
    numa_common.write_json(plan_path, plan)
    sec = formats.run(plan_path, job.out / "year-one_reel.mp4", only=["cover", "srt"], progress=False)
    assert sec["skipped"] == [{"kind": "srt", "reason": sec["skipped"][0]["reason"]}]
    assert "no caption lines" in sec["skipped"][0]["reason"]
    assert sec["ok"] is False and any("srt: requested but skipped" in e for e in sec["errors"])
    rep = json.loads((job.out / "report.json").read_text())["formats"]
    assert rep["skipped"] == sec["skipped"] and rep["ok"] is False
    # not asked for by name: a default that is not possible is skipped, not failed
    (job.out / "b").mkdir()
    j = formats.Job(engine.load_plan(plan_path), plan_path, job.out / "year-one_reel.mp4", job.out / "b",
                    "year-one", False, progress=False)
    j.skipped = {"reach": "no new hook text", "story": "not enough whole sentences"}
    sec2 = formats.write_report(j, ["reach", "story", "cover"], {}, [])
    assert [x["kind"] for x in sec2["skipped"]] == ["reach", "story"] and sec2["ok"] is True and not sec2["errors"]
