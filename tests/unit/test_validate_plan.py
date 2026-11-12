"""validate_plan.py: schema + every cross-field rule in docs/CONTRACTS.md section 5 (R45-R49, R82-R89, R128, R141)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

import claims_scan
import validate_plan as vp

ASSETS = Path(__file__).resolve().parents[2] / "skills" / "numa-reel-editor" / "assets"


@pytest.fixture(autouse=True)
def _fresh(nc):
    claims_scan._rules_for.cache_clear()
    yield
    claims_scan._rules_for.cache_clear()


@pytest.fixture
def base(plan_factory):
    """A clean v2 plan: music recorded, flash reveal outside the end card."""
    def _make(**kw):
        kw.setdefault("music", {"source": "natural", "path": None, "license": None, "title": None})
        plan = plan_factory(**kw)
        plan["shots"][1]["tr"] = "flash"
        plan["shots"][2]["tr"] = "leakfade"
        return plan
    return _make


def analysis(beats=(), words=(), clips=(), photos=()):
    return {"schema_version": 2, "duration": 9.0, "bpm": 100.0, "beats": list(beats), "words": list(words),
            "transcript": " ".join(w["w"] for w in words), "voice_present": bool(words),
            "audio": {"voice": None, "music": None, "master": None}, "photos": list(photos), "clips": list(clips)}


def run(plan, A=None, prefs=None):
    return vp.validate(plan, A, prefs)


def find(issues, rule, level=None, where=None, text=None):
    return [i for i in issues if i.rule == rule and (level is None or i.level == level)
            and (where is None or i.where == where) and (text is None or text in i.message)]


def errors(issues):
    return [i for i in issues if i.level == "ERROR"]


def test_base_plan_is_clean(base):
    iss = run(base())
    assert errors(iss) == []
    assert [i.rule for i in iss] == [7]  # 9 s is short for a main reel (warning only)


# ---- rule 1: schema --------------------------------------------------------
def test_rule1_bad_enum(base):
    p = base()
    p["shots"][1]["tr"] = "zoom"
    (i,) = find(run(p), 1, "ERROR", "shots[1].tr")
    assert "'zoom' is not one of" in i.message


def test_rule1_one_element_word_is_error_not_traceback(base):
    p = base()
    p["lines"][0]["words"][0] = ["Walk"]
    assert find(run(p), 1, "ERROR", "lines[0].words[0]")


def test_rule1_unknown_key_and_bad_analysis(base):
    p = base()
    p["shots"][0]["zoom"] = [1, 2]
    assert find(run(p), 1, "ERROR", "shots[0]", "unknown field 'zoom'")
    iss = run(base(), {"duration": 3})
    assert any(i.rule == 1 and i.where.startswith("analysis") for i in iss)


def test_rule1_leak_strength_up_to_1_is_schema_valid(base):
    p = base(leaks=[[3.0, 0.8, 1.0]])
    iss = run(p)
    assert not errors(iss) and find(iss, 33, "WARN", "leaks[0]", "above 0.6")
    p = base(leaks=[[3.0, 0.8, 1.2]])
    assert find(run(p), 1, "ERROR", "leaks[0][2]")


# ---- rules 2-3: tiling ---------------------------------------------------------
def test_rule2_gap(base):
    p = base()
    p["shots"][1]["t0"] = 3.2
    (i,) = find(run(p), 2, "ERROR", "shots[1].t0")
    assert "gap" in i.message


def test_rule2_overlap(base):
    p = base()
    p["shots"][1]["t0"] = 2.8
    assert find(run(p), 2, "ERROR", "shots[1].t0", "overlap")


def test_rule2_first_and_last(base):
    p = base()
    p["shots"][0]["t0"] = 0.5
    p["shots"][2]["t1"] = 8.5
    iss = run(p)
    assert find(iss, 2, "ERROR", "shots[0].t0", "must be 0")
    assert find(iss, 2, "ERROR", "shots[2].t1", "duration is 9")


def test_rule2_empty_shot(base):
    p = base()
    p["shots"][1]["t1"] = 3.0
    p["shots"][2]["t0"] = 3.0
    assert find(run(p), 2, "ERROR", "shots[1]", "must be after t0")


def test_rule3_short_shot(base):
    p = base()
    p["shots"][1]["t1"] = 3.2
    p["shots"][2]["t0"] = 3.2
    p["endcard"]["t"] = 3.2
    assert find(run(p), 3, "WARN", "shots[1]")


# ---- rules 4-7: paths, files, duration ---------------------------------------------
def test_rule4_relative_path(base):
    p = base()
    p["shots"][1]["src"] = "raw/p1.jpg"
    assert find(run(p), 4, "ERROR", "shots[1].src", "absolute")


def test_rule5_missing_files(base, tmp_path):
    p = base()
    p["font_regular"] = str(tmp_path / "missing.ttf")
    p["endcard"]["logo"] = str(tmp_path / "logo.png")
    p["shots"][1]["src"] = str(tmp_path / "gone.jpg")
    iss = run(p)
    assert find(iss, 5, "ERROR", "font_regular", "file not found")
    assert find(iss, 5, "ERROR", "endcard.logo")
    assert find(iss, 5, "ERROR", "shots[1].src")


def test_rule5_brand_default_font_missing(base, nc, tmp_path, monkeypatch):
    brand = copy.deepcopy(nc.load_brand())
    brand["fonts"]["value"]["caption_italic"] = str(tmp_path / "nope.ttf")
    bp = tmp_path / "brand.json"
    bp.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(bp))
    nc.clear_caches()
    assert find(run(base()), 5, "ERROR", "font_italic", "brand.json default font")


def test_rule6_duration_cap(base):
    p = base(duration=200.0)
    p["shots"][2]["t1"] = 200.0
    p["endcard"]["t"] = 196.0
    p["shots"][2]["t0"] = p["shots"][1]["t1"] = 196.0
    assert find(run(p), 6, "ERROR", "duration", "over the 180 s cap")


def test_rule7_duration_range(base):
    assert find(run(base()), 7, "WARN", "duration")


# ---- rules 8-13: first shot, zoom, clips, crop ----------------------------------------
@pytest.mark.parametrize("tr", ["whip", "wipe", "fade", "leakfade"])
def test_rule8_first_transition_error(base, tr):
    p = base()
    p["shots"][0]["tr"] = tr
    assert find(run(p), 8, "ERROR", "shots[0].tr")


@pytest.mark.parametrize("tr", ["punch", "flash"])
def test_rule9_first_transition_warn(base, tr):
    p = base()
    p["shots"][0]["tr"] = tr
    assert find(run(p), 9, "WARN", "shots[0].tr")


def test_rule10_and_11_zoom(base):
    p = base()
    p["shots"][1]["z"] = [1.0, 1.6]
    p["shots"][2]["z"] = [1.05, 1.05]
    iss = run(p)
    assert find(iss, 10, "ERROR", "shots[1].z")
    assert find(iss, 11, "WARN", "shots[2].z", "static")


def test_rule12_video_past_clip_end(base, job, make_video):
    clip = make_video(job.raw / "c.mp4", seconds=2.0, size=(64, 112))
    p = base()
    p["shots"][1].update(kind="video", src=str(clip), start=1.0)
    (i,) = find(run(p), 12, "WARN", "shots[1]")
    assert "past the clip's end" in i.message
    p["shots"][1].update(start=0.0, speed=0.5)
    assert not find(run(p), 12)


def test_rule12_uses_analysis_duration(base, job, make_video):
    clip = make_video(job.raw / "c.mp4", seconds=1.0, size=(64, 112))
    p = base()
    p["shots"][1].update(kind="video", src=str(clip), start=0.0)
    A = analysis(clips=[{"id": "C0", "path": str(clip), "duration": 10.0, "has_audio": True, "fps": 30, "size": [64, 112]}])
    assert not find(run(p, A), 12)


def test_rule13_crop(base, job, make_video):
    p = base()
    p["shots"][1]["crop"] = [0, 0, 5000, 100]  # image is 720x1280
    assert find(run(p), 13, "ERROR", "shots[1].crop", "outside the 720x1280 image")
    clip = make_video(job.raw / "c.mp4", seconds=3.0, size=(64, 112))
    p = base()
    p["shots"][1].update(kind="video", src=str(clip), crop=[0, 0, 10, 10])
    assert find(run(p), 13, "ERROR", "shots[1].crop", "images only")


def test_rule13_blur_and_face_boxes(base):
    p = base()
    p["shots"][1]["blur"] = [[0.8, 0.1, 0.4, 0.2]]
    p["shots"][2]["faces"] = [[0.1, 0.1, 0.0, 0.2]]
    iss = run(p)
    assert find(iss, 13, "ERROR", "shots[1].blur[0]")
    assert find(iss, 13, "ERROR", "shots[2].faces[0]")


# ---- rules 14-17: beats and transitions -------------------------------------------------
@pytest.fixture
def beat_plan(base):
    """Cuts on a 0.6 s beat grid: 0, 2.4 (4 beats), 4.8 end card."""
    def _make():
        p = base()
        p["shots"][0]["t1"] = p["shots"][1]["t0"] = 2.4
        p["shots"][1]["t1"] = p["shots"][2]["t0"] = p["endcard"]["t"] = 4.8
        return p
    return _make


BEATS = [round(0.6 * i, 3) for i in range(16)]


def test_rule14_on_beat_is_clean(beat_plan):
    assert not find(run(beat_plan(), analysis(BEATS)), 14)
    assert not find(run(beat_plan(), analysis(BEATS)), 15)


def test_rule14_off_beat_cut_warns(beat_plan):
    p = beat_plan()
    p["shots"][0]["t1"] = p["shots"][1]["t0"] = 2.5  # 100 ms off, more than one frame at 30 fps
    (i,) = find(run(p, analysis(BEATS)), 14, "WARN", "shots[1].t0")
    assert "100 ms off" in i.message


def test_rule14_within_one_frame_ok(beat_plan):
    p = beat_plan()
    p["shots"][0]["t1"] = p["shots"][1]["t0"] = 2.43
    assert not find(run(p, analysis(BEATS)), 14)


def test_rule15_six_beat_shot(beat_plan):
    p = beat_plan()
    p["shots"][0]["t1"] = p["shots"][1]["t0"] = 3.6  # 6 beats
    (i,) = find(run(p, analysis(BEATS)), 15, "WARN", "shots[0]")
    assert "holds 6 beats" in i.message
    p["shots"][0]["peak"] = True
    assert not find(run(p, analysis(BEATS)), 15)


def _many_shots(base, trs):
    p = base(duration=12.0)
    src = p["shots"][0]["src"]
    n = len(trs)
    step = 8.0 / n
    p["shots"] = [{"src": src, "t0": round(i * step, 3), "t1": round((i + 1) * step, 3), "z": [1.0, 1.1], "tr": t}
                  for i, t in enumerate(trs)]
    p["shots"].append({"src": src, "t0": 8.0, "t1": 12.0, "z": [1.0, 1.08], "tr": "flash"})
    p["endcard"]["t"] = 8.0
    return p


def test_rule16_whips(base):
    p = _many_shots(base, ["cut", "whip", "punch", "whip", "whip", "flash", "whip"])
    iss = run(p)
    assert find(iss, 16, "WARN", "shots", "4 whips in 7 cuts")
    assert find(iss, 16, "WARN", "shots[3].tr", "every third cut")
    p = _many_shots(base, ["cut", "punch", "whip", "punch", "flash", "whip", "punch"])
    assert not find(run(p), 16)


def test_rule17_variety(base):
    p = _many_shots(base, ["cut"] + ["punch"] * 7)
    assert find(run(p), 17, "WARN", "shots", "transition type")
    p = _many_shots(base, ["cut", "punch", "leakfade", "punch", "flash", "whip", "punch", "punch"])
    assert not find(run(p), 17)


# ---- rule 18: signature -------------------------------------------------------------
def test_rule18_no_signature(base):
    p = base()
    p["shots"][1]["tr"] = "punch"
    assert find(run(p), 18, "WARN", "shots", "no signature moment")


def test_rule18_two_wipes(base):
    p = _many_shots(base, ["cut", "wipe", "punch", "wipe"])
    assert find(run(p), 18, "WARN", "shots", "2 wipes")


def test_rule18_signature_must_match_a_boundary(base):
    p = base(signature={"type": "wipe", "t": 3.0})
    assert find(run(p), 18, "ERROR", "signature", "no shot starts at 3 s with tr 'wipe'")
    p = base(signature={"type": "flash", "t": 3.0})
    assert not find(run(p), 18)


# ---- rules 19-23: captions -----------------------------------------------------------
def test_rule19_word_order(base):
    p = base()
    p["lines"][0]["words"][2][1] = 0.1
    assert find(run(p), 19, "ERROR", "lines[0]", "ascending")


def test_rule19_line_before_previous_words(base):
    p = base()
    p["lines"].append({"words": [["Again", 1.0]], "end": 2.8})
    assert find(run(p), 19, "ERROR", "lines[1]", "before line 0's last word")


def test_rule20_end(base):
    p = base()
    p["lines"][0]["end"] = 1.0
    assert find(run(p), 20, "ERROR", "lines[0].end", "before its last word")
    p = base()
    p["lines"][0]["end"] = 9.5
    assert find(run(p), 20, "ERROR", "lines[0].end", "after the reel ends")


def test_rule21_overlap(base):
    p = base()
    p["lines"].append({"words": [["Again", 2.0]], "end": 2.8})
    assert find(run(p), 21, "WARN", "lines[1]")


def test_rule22_three_rows(base):
    p = base()
    p["lines"][0]["words"] = [[w, 0.1 * i] for i, w in enumerate(
        "Every single morning the cold water waits for us right here in Midtown".split())]
    p["lines"][0]["end"] = 2.6
    assert find(run(p), 22, "ERROR", "lines[0]", "rows")


def test_rule23_long_line(base):
    p = base(caption_y=1400)
    words = "a b c d e f g h i j k l m n o p q r s t u v w x y z a b c d e f g h i j k l m n o p".split()
    p["lines"][0]["words"] = [[w, 0.01 * i] for i, w in enumerate(words)]
    assert find(run(p), 23, "WARN", "lines[0]", "over 80")


# ---- rule 24: transcript ----------------------------------------------------------------
def _words(pairs):
    return [{"w": w, "appear": t, "end": t + 0.25} for w, t in pairs]


TRANSCRIPT = _words([("Walk", 0.3), ("out", 0.6), ("wide", 0.9), ("awake.", 1.2)])


def test_rule24_matching_transcript_is_clean(base):
    assert not find(run(base(), analysis(words=TRANSCRIPT)), 24)


def test_rule24_shifted_words(base):
    p = base()
    p["lines"][0]["words"][1][1] = 0.9   # 0.3 s late: warn
    p["lines"][0]["words"][2][1] = 1.0   # 0.1 s: fine
    p["lines"][0]["words"][3][1] = 1.9   # 0.7 s late: error
    iss = run(p, analysis(words=TRANSCRIPT))
    assert find(iss, 24, "WARN", "lines[0].words[1]", "0.30 s off")
    assert find(iss, 24, "ERROR", "lines[0].words[3]", "0.70 s off")
    assert not find(iss, 24, where="lines[0].words[2]")


def test_rule24_misspelled_and_extra_words(base):
    p = base()
    p["lines"][0]["words"][2][0] = "wild"
    p["lines"][0]["words"].insert(3, ["truly", 1.1])
    iss = run(p, analysis(words=TRANSCRIPT))
    assert find(iss, 24, "WARN", "lines[0].words[2]", "does not match the transcript word 'wide'")
    assert find(iss, 24, "ERROR", "lines[0].words[3]", "'truly' is not in the transcript")


def test_rule24_missing_words(base):
    long = _words([(f"w{i}", 0.3 + i * 0.05) for i in range(4)] + [(f"x{i}", 3 + i * 0.1) for i in range(10)])
    p = base()
    p["lines"][0]["words"] = [[f"w{i}", round(0.3 + i * 0.05, 2)] for i in range(4)]
    assert find(run(p, analysis(words=long)), 24, "WARN", "lines", "captions show 4 of 14")


# ---- rules 25-26: safe area and faces --------------------------------------------------
def test_rule25_safe_area(base):
    assert find(run(base(caption_y=1800)), 25, "ERROR", "lines[0]", "safe area")
    p = base()
    p["hook"]["y"] = 60
    assert find(run(p), 25, "ERROR", "hook.y")


def test_rule26_face_under_caption(base):
    p = base()
    p["shots"][0]["faces"] = [[0.3, 0.68, 0.4, 0.1]]  # lower middle of a 720x1280 portrait
    assert find(run(p), 26, "WARN", "lines[0]", "covers a face in shots[0]")
    p["shots"][0]["faces"] = [[0.3, 0.1, 0.4, 0.1]]
    assert not find(run(p), 26)


# ---- rule 27: claims -------------------------------------------------------------------
def test_rule27_banned_claim_in_caption(base):
    p = base()
    p["lines"][0]["words"][3][0] = "detoxed."
    (i,) = find(run(p), 27, "ERROR", "lines[0]")
    assert 'banned claim "detox or toxins"' in i.message


@pytest.mark.parametrize("where, setter", [
    ("hook.text", lambda p: p["hook"].update(text="Burn calories fast")),
    ("endcard.subtitle", lambda p: p["endcard"].update(subtitle="Science-backed calm")),
    ("formats.cover.title", lambda p: p.update(formats={"cover": {"t": 1.0, "title": "Anti-aging glow"}})),
])
def test_rule27_every_text_surface(base, where, setter):
    p = base()
    setter(p)
    assert find(run(p), 27, "ERROR", where)


def test_rule27_warn_severity(base):
    p = base()
    p["endcard"]["subtitle"] = "The cure for Monday."
    iss = run(p)
    assert find(iss, 27, "WARN", "endcard.subtitle") and not find(iss, 27, "ERROR")


def test_rule27_reads_brand_json(base, nc, tmp_path, monkeypatch):
    """R128: one banned list. A term added to brand.json is caught by the validator."""
    p = base()
    p["endcard"]["subtitle"] = "Feel the zorbitron glow"
    assert not find(run(p), 27)
    brand = copy.deepcopy(nc.load_brand())
    brand["claims"]["banned"].append({"id": "zorb", "label": "zorbitron", "severity": "fail",
                                      "patterns": [r"\bzorbitron\b"], "applies_to": "all"})
    bp = tmp_path / "brand.json"
    bp.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(bp))
    nc.clear_caches()
    claims_scan._rules_for.cache_clear()
    assert find(run(p), 27, "ERROR", "endcard.subtitle", "zorbitron")


# ---- rules 28-30: consent, music, AI -------------------------------------------------------
def test_rule28_people_without_consent(base):
    p = base()
    p["shots"][1].update(people=True, consent=False)
    assert find(run(p), 28, "ERROR", "shots[1]")
    p["shots"][1]["consent"] = True
    assert not find(run(p), 28)


def test_rule29_music(base, plan_factory):
    assert find(run(plan_factory()), 29, "ERROR", "music", "missing")
    p = base(music={"source": "library", "path": None, "license": "", "title": None})
    assert find(run(p), 29, "ERROR", "music.license")
    v1 = plan_factory()
    del v1["schema_version"]
    for k in ("hook", "meta"):
        v1.pop(k)
    assert not find(run(v1), 29)


def test_rule30_ai_label(base):
    p = base(ai={"people": True, "scenes": False, "label_required": False})
    assert find(run(p), 30, "ERROR", "ai.label_required")
    p = base()
    p["shots"][1]["ai_generated"] = True
    assert find(run(p), 30, "ERROR", "ai.label_required", "ai_generated")


# ---- rules 31-35 ---------------------------------------------------------------------------
def test_rule31_endcard_outside(base):
    p = base()
    p["endcard"]["t"] = 9.0
    assert find(run(p), 31, "ERROR", "endcard.t")


def test_rule32_endcard_hold(base):
    p = base()
    p["shots"][1]["t1"] = p["shots"][2]["t0"] = p["endcard"]["t"] = 6.0
    assert find(run(p), 32, "WARN", "endcard.t", "less than 3.5 s")
    p = base()
    p["endcard"]["t"] = 5.0
    assert find(run(p), 32, "WARN", "endcard.t", "not on a shot boundary")


def test_rule33_leak_past_end(base):
    assert find(run(base(leaks=[[8.5, 1.0, 0.3]])), 33, "WARN", "leaks[0]", "past the end")


def test_rule34_hook(base):
    p = base()
    p["hook"]["t1"] = 12.0
    assert find(run(p), 34, "ERROR", "hook.t1")
    p = base()
    del p["hook"]
    assert find(run(p), 34, "WARN", "hook")


def test_rule35_nat(base, job, make_video):
    silent = make_video(job.raw / "silent.mp4", seconds=2.0, size=(64, 112), audio=False)
    p = base(nat=[{"src": str(silent), "start": 1.5, "t": 8.5, "dur": 1.0}])
    iss = run(p)
    assert find(iss, 35, "WARN", "nat[0]", "past the reel end")
    assert find(iss, 35, "WARN", "nat[0]", "past the clip's end")
    assert find(iss, 35, "WARN", "nat[0].src", "no audio")


# ---- rules 36-40 -------------------------------------------------------------------------
def test_rule36_formats(base):
    p = base(formats={"reach_cut": {"t0": 0.0, "t1": 5.0, "hook": "Wide awake."},
                      "story": [{"t": 1, "text": "a"}, {"t": 2, "text": "b"}, {"t": 30, "text": "c"}]})
    iss = run(p)
    assert find(iss, 36, "ERROR", "formats.reach_cut", "5.00 s long")
    assert find(iss, 36, "ERROR", "formats.story[2].t")


def test_rule37_output_spec(base):
    iss = run(base(fps=25, size=[720, 1280]))
    assert find(iss, 37, "WARN", "fps") and find(iss, 37, "WARN", "size")


def test_rule38_prefs(base):
    p = base()
    p["shots"][1]["tr"] = "whip"
    assert find(run(p, prefs={"max_whips": 0}), 38, "WARN", "prefs", "max_whips")
    assert not find(run(p, prefs={"max_whips": 1}), 38)


@pytest.mark.parametrize("mark", ["Numa_Workmark_Dark.png", "Numa-Phoenix-transparent.png"])
def test_rule39_never_open_on_the_logo(base, mark):
    p = base()
    p["shots"][0]["src"] = str(ASSETS / mark)
    assert find(run(p), 39, "ERROR", "shots[0].src", "opens on the logo")


def test_rule40_movement_from_frame_1(base):
    p = base()
    del p["hook"]
    p["shots"][0].update(z=[1.0, 1.0], pan=[0, 0], tr="cut")
    assert find(run(p), 40, "ERROR", "shots[0]")
    p["shots"][0]["pan"] = [0.03, 0]
    assert not find(run(p), 40)


# ---- example plans -----------------------------------------------------------------------
def _materialize(plan_text: str, tmp: Path, make_image, make_video, make_audio, prefixes: dict) -> dict:
    """Rewrite the example's absolute prefixes into tmp and create every referenced file."""
    for old, new in prefixes.items():
        plan_text = plan_text.replace(old, new)
    plan = json.loads(plan_text)
    for s in plan["shots"]:
        path = Path(s["src"])
        if path.exists():
            continue
        if s.get("kind") == "video":
            make_video(path, seconds=40.0, size=(64, 112), fps=10, audio=False)
        else:
            l, t, r, b = s.get("crop", [0, 0, 720, 1280])
            make_image(path, size=(max(r, 720), max(b, 720)))
    m = plan.get("music") or {}
    if m.get("path"):
        make_audio(m["path"], seconds=1.0, kind="silence")
    Path(plan["out_dir"]).mkdir(parents=True, exist_ok=True)
    return plan


def test_v2_example_plan_validates(tmp_path, make_image, make_video, make_audio, repo_root):
    text = (ASSETS / "example-plan-year-one-v2.json").read_text()
    raw = vp.validate(json.loads(text))
    assert not [i for i in raw if i.rule == 1]  # schema-valid as is
    plan = _materialize(text, tmp_path, make_image, make_video, make_audio,
                        {"/YEAR_ONE_PACK": str(tmp_path / "pack"), "/NUMA_PLUGIN": str(repo_root)})
    assert errors(vp.validate(plan)) == []


def test_v1_example_plan_validates(tmp_path, make_image, make_video, make_audio):
    text = (ASSETS / "example-plan-year-one.json").read_text()
    text = re.sub(r"/mnt/user-data/uploads/[^\"]+\.mp4", str(tmp_path / "clip.mp4"), text)
    plan = _materialize(text, tmp_path, make_image, make_video, make_audio, {"/home/claude/w": str(tmp_path / "w")})
    make_image(Path(plan["endcard"]["logo"]), size=(200, 80))
    assert "schema_version" not in plan
    iss = vp.validate(plan)
    assert errors(iss) == [], errors(iss)
    assert not find(iss, 29) and not find(iss, 34)  # v2-only rules don't apply to v1


# ---- CLI -------------------------------------------------------------------------------
def test_cli_ok_and_analysis_next_to_plan(base, job, run_script):
    p = base()
    pp = job.work / "plan.json"
    pp.write_text(json.dumps(p))
    r = run_script("validate_plan.py", pp)
    assert r.returncode == 0 and r.stdout.startswith("OK: 3 shots, 9 s, 1 warnings")
    bad = analysis(words=_words([("Run", 0.3), ("out", 0.6), ("wide", 0.9), ("awake.", 1.2)]))
    (job.work / "analysis.json").write_text(json.dumps(bad))
    r = run_script("validate_plan.py", pp)
    assert r.returncode == 0 and "does not match the transcript word 'Run'" in r.stderr
    r = run_script("validate_plan.py", pp, "--strict")
    assert r.returncode == 1


def test_cli_json_and_errors(base, job, run_script):
    p = base()
    p["shots"][1]["t0"] = 3.5
    pp = job.work / "plan.json"
    pp.write_text(json.dumps(p))
    r = run_script("validate_plan.py", pp, "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert report["ok"] is False and report["errors"][0]["rule"] == 2
    assert "ERROR: shots[1].t0:" in r.stderr and "[rule 2]" in r.stderr


@pytest.mark.parametrize("content", ["{not json", "", "[1, 2]", '{"duration": 3}'])
def test_cli_malformed_input_no_traceback(job, run_script, content):
    pp = job.work / "plan.json"
    pp.write_text(content)
    r = run_script("validate_plan.py", pp)
    assert r.returncode == 1
    assert "ERROR" in r.stderr and "Traceback" not in r.stderr


def test_cli_missing_plan_and_usage(run_script, tmp_path):
    r = run_script("validate_plan.py", tmp_path / "nope.json")
    assert r.returncode == 1 and "ERROR: plan not found" in r.stderr
    r = run_script("validate_plan.py")
    assert r.returncode == 2


def test_cli_prefs_file(base, job, run_script, tmp_path):
    p = base()
    p["shots"][1]["tr"] = "whip"
    pp = job.work / "plan.json"
    pp.write_text(json.dumps(p))
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"limits": {"max_whips": 0}}))
    r = run_script("validate_plan.py", pp, "--prefs", prefs)
    assert r.returncode == 0 and "[rule 38]" in r.stderr


# ---- revision 2: NaN/Infinity, --json on fatal input, folder license, logo copies ----
def test_non_finite_numbers_are_errors(base):
    p = base(duration=float("nan"))
    (i,) = find(run(p), 1, "ERROR", "duration")
    assert "not a finite number" in i.message
    p = base()
    p["shots"][1]["t1"] = float("inf")
    p["leaks"] = [[1.0, float("-inf"), 0.3]]
    iss = run(p)
    assert find(iss, 1, "ERROR", "shots[1].t1") and find(iss, 1, "ERROR", "leaks[0][1]")
    A = analysis(BEATS)
    A["beats"][3] = float("nan")
    assert find(run(base(), A), 1, "ERROR", "analysis beats[3]")


def test_cli_nan_plan(base, job, run_script):
    text = json.dumps(base()).replace('"t1": 3.0', '"t1": NaN', 1)
    pp = job.work / "plan.json"
    pp.write_text(text)
    r = run_script("validate_plan.py", pp)
    assert r.returncode == 1 and "not a finite number" in r.stderr and "unexpected" not in r.stderr


@pytest.mark.parametrize("content", ["{not json", '{"duration": 3}'])
def test_cli_json_reports_fatal_input(job, run_script, content):
    pp = job.work / "plan.json"
    pp.write_text(content)
    r = run_script("validate_plan.py", pp, "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert report["ok"] is False and report["errors"] and report["errors"][0]["level"] == "ERROR"


def test_cli_json_missing_plan(run_script, tmp_path):
    r = run_script("validate_plan.py", tmp_path / "nope.json", "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False


def test_rule29_folder_music_without_license_warns(base, job, make_audio):
    music = make_audio(job.raw / "music.wav", seconds=0.5, kind="silence")
    p = base(music={"source": "folder", "path": str(music), "license": None, "title": None})
    iss = run(p)
    assert find(iss, 29, "WARN", "music.license", "NUMA's own file") and not find(iss, 29, "ERROR")


def test_rule39_copy_of_wordmark_in_material(base, job):
    import shutil
    copy_path = job.raw / "IMG_0001.png"
    shutil.copy(ASSETS / "Numa_Workmark_Dark.png", copy_path)
    p = base()
    p["shots"][0]["src"] = str(copy_path)
    assert find(run(p), 39, "ERROR", "shots[0].src")
