"""baseline_plan.py: a valid, beat-synced v2 plan that follows the edit grammar (R42-R49, R92, R96)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import baseline_plan as bp
import validate_plan as vp

PERIOD = 0.6  # 100 BPM
VOICE = ("This is what Katie saw. I don't know how she does it, but she does. "
         "Every morning the cold was waiting for us. Thank you, Mobile, for one whole year of showing up.")


def _words(text: str, t0: float = 0.5) -> list[dict]:
    out, t = [], t0
    for w in text.split():
        out.append({"w": w, "appear": round(t, 3), "end": round(t + 0.3, 3), "start": round(t - 0.05, 3)})
        t += 0.42 + (0.5 if w.endswith(".") else 0)
    return out


@pytest.fixture
def make_job(job, make_image, make_video, make_audio):
    """analysis.json for one fixture shape; every referenced file exists."""
    def _make(shape: str, duration: float = 30.0) -> tuple[Path, dict]:
        photos, clips = [], []
        if shape in ("photos", "voice_music", "music_only", "heic", "no_audio"):
            for i in range(6):
                size = (1200, 800) if i % 2 else (720, 1280)
                p = make_image(job.work / "media" / f"p{i}.jpg" if shape == "heic" else job.raw / f"p{i}.jpg", size=size)
                item = {"id": f"P{i}", "path": str(p), "size": list(size), "sharpness": 100.0 + (37 * i) % 50}
                if shape == "heic":
                    item["orig_path"] = str(job.raw / f"IMG_{i}.HEIC")
                photos.append(item)
        if shape == "clips":
            for i in range(2):
                c = make_video(job.raw / f"c{i}.mp4", seconds=4.0, size=(64, 112), fps=10, audio=False)
                clips.append({"id": f"C{i}", "path": str(c), "duration": 4.0, "has_audio": False, "fps": 10,
                              "size": [64, 112], "windows": [[1.0, 3.0, 0.4 + 0.3 * i]]})
        music = make_audio(job.raw / "music.wav", seconds=0.5, kind="silence")
        words = _words(VOICE) if shape in ("voice_music", "audio_only") else []
        A = {"schema_version": 2, "duration": duration, "bpm": 100.0,
             "beats": [round(0.25 + i * PERIOD, 3) for i in range(int(duration / PERIOD))],
             "words": words, "transcript": " ".join(w["w"] for w in words), "voice_present": bool(words),
             "audio": {"voice": str(music) if words else None, "music": str(music), "master": str(music)},
             "photos": photos, "clips": clips}
        if shape == "no_audio":
            A.update(duration=0, bpm=None, beats=[], audio={"voice": None, "music": None, "master": None})
        (job.work / "analysis.json").write_text(json.dumps(A))
        return job.work, A
    return _make


def build(work, A, **kw):
    return bp.build_plan(work, A, **kw)


def errors(issues):
    return [i for i in issues if i.level == "ERROR"]


def rules(issues):
    return sorted({i.rule for i in issues})


@pytest.mark.parametrize("shape", ["photos", "clips", "voice_music", "music_only", "heic", "no_audio", "audio_only"])
def test_every_fixture_shape_validates_clean(make_job, shape):
    work, A = make_job(shape)
    plan = build(work, A)
    iss = vp.validate(plan, A)
    assert errors(iss) == [], errors(iss)
    assert plan["schema_version"] == 2 and plan["out_dir"] == str(work)
    assert not set(rules(iss)) & {14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 32}, iss


def test_voice_music_follows_the_edit_grammar(make_job):
    work, A = make_job("voice_music")
    plan = build(work, A)
    shots, lines = plan["shots"], plan["lines"]
    # hook = first caption line, from frame 0
    assert plan["hook"]["text"] == "This is what Katie saw." and plan["hook"]["t1"] >= 1.5
    # strongest image first (P1 has the top sharpness), never the logo, moving from frame 1
    best = max(A["photos"], key=lambda p: p["sharpness"])["path"]
    assert shots[0]["src"] == best and shots[0]["tr"] == "cut" and shots[0]["z"][0] != shots[0]["z"][1]
    # one sentence per line, 1-2 gold words each
    assert [" ".join(w[0] for w in ln["words"]) for ln in lines][:3] == [
        "This is what Katie saw.", "I don't know how she does it, but she does.",
        "Every morning the cold was waiting for us."]
    for ln in lines:
        assert 1 <= sum(1 for w in ln["words"] if len(w) > 2) <= 2
    # every cut on a beat
    beats = A["beats"]
    for s in shots[1:]:
        assert min(abs(s["t0"] - b) for b in beats) < 1 / 30
    # exactly one signature moment: a flash on the biggest line
    sig = plan["signature"]
    assert sig["type"] == "flash"
    ec = plan["endcard"]
    flashes = [s for s in shots if s["tr"] == "flash" and s["t0"] != ec["t"]]
    assert len(flashes) == 1 and flashes[0]["t0"] == sig["t"]
    assert not any(s["tr"] == "wipe" for s in shots)
    # whips at most every third cut, alternating zooms, pan on wide photos
    whips = [i for i, s in enumerate(shots) if s["tr"] == "whip"]
    assert whips and all(b - a >= 3 for a, b in zip(whips, whips[1:]))
    body = [s for s in shots[1:] if s["t0"] < ec["t"]]
    dirs = [s["z"][1] > s["z"][0] for s in body]
    assert all(a != b for a, b in zip(dirs, dirs[1:]))
    for s in body:
        if s["src"].endswith(("p1.jpg", "p3.jpg", "p5.jpg")):  # 1200x800 photos
            assert s["pan"][0] != 0
    # end card on the last beats, held 3.5-5 s, over the ripple image
    assert 3.5 <= plan["duration"] - ec["t"] <= 5.0
    assert shots[-1]["src"].endswith("heroimage.jpg") and shots[-1]["t0"] == ec["t"]
    assert ec["logo"].endswith("Numa_Workmark_Dark.png") and ec["tagline"] == "Wellness Collective"
    # music recorded, formats defaults
    assert plan["music"]["source"] == "folder" and plan["music"]["license"] is None  # no record in sources.json
    fm = plan["formats"]
    assert 8 <= fm["reach_cut"]["t1"] - fm["reach_cut"]["t0"] <= 12
    assert 3 <= len(fm["story"]) <= 5 and fm["cover"]["title"]
    assert "carousel" not in fm   # 4 whole sentences (one is the hook): too few for 5 slides


def test_outro_recap_montage_two_beats_each(make_job):
    work, A = make_job("voice_music")
    plan = build(work, A)
    last_word = max(w["end"] for w in A["words"])
    ec = plan["endcard"]["t"]
    montage = [s for s in plan["shots"] if s["t0"] > last_word and s["t0"] < ec]
    assert 5 <= len(montage) <= 8
    for s in montage:
        assert abs((s["t1"] - s["t0"]) - 2 * PERIOD) < 1e-3


def test_tense_two_beats_then_four_beat_holds(make_job):
    work, A = make_job("photos")
    plan = build(work, A, turn=6.0)
    shots = plan["shots"]
    turn = min((s["t0"] for s in shots[1:]), key=lambda t: abs(t - 6.0))
    for s in shots[1:]:
        beats = round((s["t1"] - s["t0"]) / PERIOD)
        if s["t1"] <= turn + 1e-6:
            assert beats <= 2 and s["look"] == "before"
        elif s["t0"] < plan["endcard"]["t"]:
            assert beats <= 4 and s["look"] == "warm"
    assert any(round((s["t1"] - s["t0"]) / PERIOD) == 4 for s in shots if s["t0"] > turn)


def test_before_after_wipe(make_job):
    work, A = make_job("photos")
    plan = build(work, A, before="P2", after="P4", turn=9.0)
    shots = plan["shots"]
    wipes = [i for i, s in enumerate(shots) if s["tr"] == "wipe"]
    assert len(wipes) == 1
    i = wipes[0]
    assert shots[i - 1]["src"].endswith("p2.jpg") and shots[i - 1]["look"] == "before"
    assert shots[i]["src"].endswith("p4.jpg") and shots[i]["look"] == "warm"
    assert plan["signature"] == {"type": "wipe", "t": shots[i]["t0"]}
    ec = plan["endcard"]["t"]
    assert not [s for s in shots if s["tr"] == "flash" and s["t0"] != ec]
    assert errors(vp.validate(plan, A)) == []


def test_hook_override_and_never_open_on_logo(make_job):
    work, A = make_job("audio_only")
    plan = build(work, A, hook="Your first plunge.")
    assert plan["hook"]["text"] == "Your first plunge."
    srcs = [s["src"] for s in plan["shots"][:-1]]
    assert all("/assets/brand-photos/" in s for s in srcs)  # R96
    assert "logo" not in Path(srcs[0]).name


def test_music_only_script_captions_r92(make_job, tmp_path):
    work, A = make_job("music_only")
    script = "Three minutes of cold.\nWalk out wide awake.\nPairs well with the sauna for contrast.\n"
    plan = build(work, A, script=script)
    lines = plan["lines"]
    assert [" ".join(w[0] for w in ln["words"]) for ln in lines] == [
        "Three minutes of cold.", "Walk out wide awake.", "Pairs well with the sauna for contrast."]
    for ln in lines:
        assert min(abs(ln["words"][0][1] - b) for b in A["beats"]) < 1e-3  # each line starts on a beat
        gaps = [b[1] - a[1] for a, b in zip(ln["words"], ln["words"][1:])]
        assert all(abs(g - 1 / 2.3) < 0.01 for g in gaps)
    assert plan["hook"]["text"] == "Three minutes of cold."
    assert errors(vp.validate(plan, A)) == []


def test_long_script_is_compressed_or_trimmed(make_job):
    work, A = make_job("music_only", duration=16.0)
    script = "\n".join(f"Sentence number {i} is right here." for i in range(12))
    plan = build(work, A, script=script)
    assert plan["lines"] and plan["lines"][-1]["end"] <= plan["endcard"]["t"]
    assert errors(vp.validate(plan, A)) == []


def test_no_audio_and_music_sources(make_job):
    work, A = make_job("no_audio")
    plan = build(work, A)
    assert plan["duration"] == 30.0 and plan["music"]["source"] == "natural"
    work, A = make_job("photos")
    A["audio"]["generated_pad"] = True
    assert build(work, A)["music"]["source"] == "pad"


def test_duration_and_prefs(make_job):
    work, A = make_job("photos", duration=50.0)
    plan = build(work, A, duration=20.0, prefs={"max_whips": 0})
    assert plan["duration"] == 20.0
    assert not [s for s in plan["shots"] if s["tr"] == "whip"]
    assert errors(vp.validate(plan, A)) == []


def test_heic_uses_converted_copies(make_job):
    work, A = make_job("heic")
    plan = build(work, A)
    assert all(s["src"].endswith((".jpg", "heroimage.jpg")) for s in plan["shots"])


def test_clip_spans_stay_inside_the_clip(make_job):
    work, A = make_job("clips")
    plan = build(work, A)
    for s in plan["shots"]:
        if s.get("kind") == "video":
            assert s["start"] + (s["t1"] - s["t0"]) * s.get("speed", 1.0) <= 4.0 + 1e-6
    assert Path(plan["shots"][0]["src"]).name == "c1.mp4"  # higher window score opens


# ---- CLI ---------------------------------------------------------------------
def test_cli_writes_deterministic_plan(make_job, run_script, tmp_path):
    work, A = make_job("voice_music")
    r1 = run_script("baseline_plan.py", work, "--subtitle", "Year one. Thank you, Mobile.")
    assert r1.returncode == 0, r1.stderr
    first = (work / "plan.json").read_bytes()
    out = tmp_path / "again.json"
    r2 = run_script("baseline_plan.py", work, "--subtitle", "Year one. Thank you, Mobile.", "--out", out)
    assert r2.returncode == 0 and out.read_bytes() == first
    plan = json.loads(first)
    assert plan["endcard"]["subtitle"] == "Year one. Thank you, Mobile."
    r = run_script("validate_plan.py", work / "plan.json")
    assert r.returncode == 0, r.stderr


def test_cli_errors(make_job, run_script, tmp_path):
    r = run_script("baseline_plan.py", tmp_path / "missing")
    assert r.returncode == 1 and "ERROR: work folder not found" in r.stderr
    work, A = make_job("photos")
    r = run_script("baseline_plan.py", work, "--before", "P9", "--after", "P1")
    assert r.returncode == 1 and "no photo or clip with id P9" in r.stderr
    r = run_script("baseline_plan.py", work, "--before", "P1")
    assert r.returncode == 2
    (work / "analysis.json").write_text("{broken")
    r = run_script("baseline_plan.py", work)
    assert r.returncode == 1 and "invalid JSON" in r.stderr and "Traceback" not in r.stderr
    r = run_script("baseline_plan.py")
    assert r.returncode == 2


# ---- revision 2 ------------------------------------------------------------------
def _beats(s):
    return round((s["t1"] - s["t0"]) / PERIOD, 2)


@pytest.mark.parametrize("shape", ["voice_music", "photos", "music_only"])
def test_shots_are_two_or_four_beats(make_job, shape):
    work, A = make_job(shape)
    plan = build(work, A, duration=30.0,
                 script="Three minutes of cold.\nWalk out wide awake.\nRelax, breathe, disconnect.")
    ec = plan["endcard"]["t"]
    lengths = [_beats(s) for s in plan["shots"][1:] if s["t0"] < ec and s["t1"] <= ec]
    odd = [n for n in lengths if n not in (2, 4)]
    assert len(odd) <= 1 and all(n >= 2 for n in odd), lengths
    assert not [i for i in vp.validate(plan, A) if i.rule == 3]


def test_merge_anchors_and_pieces():
    assert bp.merge_anchors([0, 1, 3, 4, 9, 10], fixed={0, 10}) == [0, 3, 10]
    assert bp.merge_anchors([0, 5, 6], fixed={0, 5, 6}) == [0, 5, 6]
    assert bp.pieces(8, 2) == [2, 2, 2, 2] and bp.pieces(10, 4) == [4, 4, 2] and bp.pieces(7, 4) == [4, 3]


def test_looks(make_job):
    work, A = make_job("voice_music")
    assert {s["look"] for s in build(work, A)["shots"][:-1]} == {"warm"}  # no before material: never cold
    work, A = make_job("photos")
    plan = build(work, A, before="P2", after="P4")
    wipe_t = plan["signature"]["t"]
    for s in plan["shots"][:-1]:
        assert s["look"] == ("before" if s["t1"] <= wipe_t + 1e-6 else "warm")


def test_wordmark_in_material_is_left_out(make_job, job):
    import shutil
    work, A = make_job("photos")
    mark = job.raw / "brand.png"
    shutil.copy(Path(bp.nc.brand_asset("wordmark")), mark)
    A["photos"].insert(0, {"id": "P9", "path": str(mark), "size": [800, 300], "sharpness": 999.0})
    plan = build(work, A)
    assert not [s for s in plan["shots"] if s["src"] == str(mark)]


def test_music_license_from_sources_json(make_job):
    work, A = make_job("photos")
    (work / "sources.json").write_text(json.dumps([{"kind": "music", "path": A["audio"]["music"],
                                                    "source": "NUMA Drive", "license": "Owned by NUMA"}]))
    plan = build(work, A)
    assert plan["music"]["license"] == "Owned by NUMA"
    assert not [i for i in vp.validate(plan, A) if i.rule == 29]


# ---- templates (R194), text cards (R195), preferences (R278), consent (rule 41) ------------------
SCRIPT = ("3 things to know before your first cold plunge.\nOne: start with three minutes.\n"
          "Two: breathe out slowly.\nThree: walk out wide awake.\nSave this for your first visit.")
TEMPLATE_IDS = [t["id"] for key in ("templates", "presets")
                for t in json.loads(bp.TEMPLATES_PATH.read_text())[key]]


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
@pytest.mark.parametrize("shape", ["voice_music", "music_only"])
def test_every_template_yields_a_valid_plan(make_job, tid, shape):
    work, A = make_job(shape, duration=60.0)
    T = bp.load_template(tid)
    plan = build(work, A, template=T, script=SCRIPT if shape == "music_only" else None)
    iss = vp.validate(plan, A)
    assert errors(iss) == [], errors(iss)
    assert plan["template"] == tid and plan["meta"]["hook_type"] == T["hook_style"]
    lo_t, hi_t = T["typical_length_s"]   # the default, moved to a sentence end when it would cut the voice
    assert plan["duration"] == T["default_length_s"] or lo_t <= plan["duration"] <= hi_t
    assert plan["signature"]["type"] == "flash"  # a wipe needs a true before/after pair
    allowed = set(T["transitions"]) | {"flash", "fade"}   # flash/fade: the end card
    assert {s["tr"] for s in plan["shots"]} <= allowed | {"cut"}
    if T["kinetic_type"]:
        assert plan["cards"], "kinetic template without text cards"
    else:
        assert "cards" not in plan
    if "reach_cut" in plan.get("formats", {}):
        assert plan["formats"]["reach_cut"]["hook"] != plan["hook"]["text"]


def test_template_pacing_and_signature_position(make_job):
    work, A = make_job("voice_music", duration=60.0)
    fast = build(work, A, template=bp.load_template("event_teaser"))      # 1-3 beats a shot
    slow = build(work, A, template=bp.load_template("founder_message"))   # 3-4 beats a shot
    assert len(fast["shots"]) / fast["duration"] > len(slow["shots"]) / slow["duration"]
    T = bp.load_template("myth_vs_fact")
    plan = build(work, A, template=T)
    assert plan["signature"]["t"] < 0.5 * plan["duration"]  # at 0.35 of the voiced part


def test_transformation_template_wipe_and_before_look(make_job):
    work, A = make_job("photos", duration=60.0)
    plan = build(work, A, template=bp.load_template("transformation"), before="P2", after="P4")
    assert plan["signature"]["type"] == "wipe"
    wipe_t = plan["signature"]["t"]
    assert {s["look"] for s in plan["shots"][:-1] if s["t1"] <= wipe_t + 1e-6} == {"before"}
    assert errors(vp.validate(plan, A)) == []


def test_education_preset_number_cards(make_job):
    work, A = make_job("music_only", duration=60.0)
    plan = build(work, A, template=bp.load_template("education_three_things"), script=SCRIPT)
    cards = plan["cards"]
    assert [c["text"] for c in cards if c["style"] == "number"] == ["1", "2", "3"]
    assert cards[0]["t0"] == 0.0 and cards[0]["style"] == "statement" and "*" in cards[0]["text"]
    cuts = {s["t0"] for s in plan["shots"]}
    assert all(c["t0"] in cuts for c in cards)
    assert all(a["t1"] <= b["t0"] for a, b in zip(cards, cards[1:]))
    assert cards[-1]["t1"] <= plan["endcard"]["t"]
    assert plan["meta"]["goal"] == "education" and plan["meta"]["length_class"] == "growth"


def test_unknown_template_is_a_clean_error(make_job, run_script):
    work, _ = make_job("photos")
    r = run_script("baseline_plan.py", work, "--template", "nope")
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert "unknown template 'nope'" in r.stderr and "education_three_things" in r.stderr
    r = run_script("baseline_plan.py", work, "--template", "education_three_things", "--duration", "45")
    assert r.returncode == 0, r.stderr
    assert json.loads((work / "plan.json").read_text())["template"] == "education_three_things"


@pytest.mark.parametrize("key,value,check", [
    ("max_whips", 0, lambda p: not [s for s in p["shots"] if s["tr"] == "whip"]),
    ("max_flashes", 1, lambda p: sum(s["tr"] == "flash" for s in p["shots"]) == 1),
    ("max_flashes", 0, lambda p: not [s for s in p["shots"] if s["tr"] == "flash"] and "signature" not in p),
    ("max_leaks", 0, lambda p: not p["leaks"] and not [s for s in p["shots"] if s["tr"] == "leakfade"]),
    ("max_leak_strength", 0.2, lambda p: all(lk[2] <= 0.2 for lk in p["leaks"])),
    ("caption_px", 104, lambda p: p.get("caption_px") == 104),
    ("max_hook_words", 3, lambda p: len(p["hook"]["text"].split()) <= 3),
    ("max_caption_chars", 25, lambda p: max(len(" ".join(w[0] for w in ln["words"])) for ln in p["lines"]) <= 25),
    ("max_gold_words", 1, lambda p: all(sum(len(w) > 2 for w in ln["words"]) <= 1 for ln in p["lines"])),
    ("max_duration", 20, lambda p: p["duration"] == 20),
    ("min_duration", 40, lambda p: p["duration"] == 40),
    ("max_shot_seconds", 1.5, lambda p: max(s["t1"] - s["t0"] for s in p["shots"][:-1]) <= 1.5 + 1e-6),
    ("min_shot_seconds", 2.0, lambda p: sorted(s["t1"] - s["t0"] for s in p["shots"][:-1])[1] >= 2.0 - 1e-6),
])
def test_each_pref_changes_the_plan(make_job, key, value, check):
    work, A = make_job("voice_music", duration=60.0)
    plain = build(work, A, duration=35.0)
    assert not check(plain), f"{key}: the default plan already satisfies the check"
    plan = build(work, A, duration=35.0, prefs={key: value})
    assert check(plan), key
    iss = vp.validate(plan, A, {key: value})
    assert errors(iss) == [], errors(iss)
    assert not [i for i in iss if i.rule == 38 and key in i.message], iss


def _faces_job(make_job, consent=None, n_faced=2):
    work, A = make_job("photos", duration=40.0)
    for p in A["photos"][:n_faced]:
        p["faces"] = [[0.4, 0.2, 0.2, 0.15]]
        p["sharpness"] = 500.0
        if consent is not None:
            p["consent"] = consent
    return work, A


def test_faces_with_consent_are_marked_people(make_job):
    work, A = _faces_job(make_job, consent=True)
    plan = build(work, A)
    faced = {p["path"] for p in A["photos"][:2]}
    shots = [s for s in plan["shots"] if s["src"] in faced]
    assert shots and all(s["people"] is True and s["consent"] is True for s in shots)
    assert errors(vp.validate(plan, A)) == []


def test_faces_without_consent_are_left_out_or_blurred(make_job, capsys):
    work, A = _faces_job(make_job)
    plan = build(work, A)
    faced = {p["path"] for p in A["photos"][:2]}
    assert not [s for s in plan["shots"] if s["src"] in faced]
    assert "no recorded consent" in capsys.readouterr().err
    assert errors(vp.validate(plan, A)) == []
    work, A = _faces_job(make_job, n_faced=5)   # too little other material: blur instead
    plan = build(work, A)
    blurred = [s for s in plan["shots"] if s.get("faces")]
    assert blurred and all(s["blur"] and "people" not in s for s in blurred)
    assert errors(vp.validate(plan, A)) == []


def test_library_consent_and_min_people_shots(make_job, tmp_path):
    work, A = _faces_job(make_job)
    lib = tmp_path / "library.json"
    lib.write_text(json.dumps({"schema_version": 1, "items": [
        {"id": "L1", "path": A["photos"][0]["path"], "kind": "photo", "consent": "yes"}]}))
    consent = bp.library_consent(lib)
    plan = build(work, A, library=consent)
    base_people = sum(1 for s in plan["shots"] if s.get("people"))
    more = build(work, A, library=consent, prefs={"min_people_shots": base_people + 2})
    assert sum(1 for s in more["shots"] if s.get("people")) == base_people + 2
    assert errors(vp.validate(more, A)) == []


LONG_VO = ("Katie walked into an empty room in Mobile. The floors were cracked and the walls were cold. "
           "She saw a place where people could breathe together. Every morning she showed up anyway, before "
           "anyone else. Today the sauna is warm and the plunge is ready for you. Thank you, Mobile, for one "
           "whole year of showing up. Send this to the friend who needs a reset.")


def _vo_job(make_job, text=LONG_VO, duration=60.0):
    work, A = make_job("voice_music", duration=duration)
    A["words"] = _words(text, 0.9)
    A["transcript"] = " ".join(w["w"] for w in A["words"])
    return work, A


def test_template_length_never_cuts_a_sentence(make_job, capsys):
    work, A = _vo_job(make_job, duration=39.0)
    T = bp.load_template("holiday_hours")
    plan = build(work, A, template=T)
    lo_t, hi_t = T["typical_length_s"]
    assert lo_t <= plan["duration"] <= hi_t and plan["duration"] != T["default_length_s"]
    shown = " ".join(w[0] for ln in plan["lines"] for w in ln["words"])
    assert shown.rstrip().endswith((".", "!", "?")), shown
    assert "mid-sentence" in capsys.readouterr().err
    assert errors(vp.validate(plan, A)) == []


def test_formats_text_is_whole_sentences(make_job):
    work, A = _vo_job(make_job, text=VOICE + " " + LONG_VO)
    plan = build(work, A)
    fm = plan["formats"]
    assert fm["story"] and fm["carousel"]
    for item in fm["story"] + fm["carousel"]:
        t = item["text"]
        assert t[0].isupper() and t.endswith((".", "!", "?", "\u2026")), t
    texts = [x["text"] for x in fm["story"] + fm["carousel"]]
    assert "but she does." not in texts and "I don't know how she does it," not in texts


def test_statement_card_replaces_its_caption(make_job):
    work, A = _vo_job(make_job, duration=60.0)
    plan = build(work, A, template=bp.load_template("myth_vs_fact"))
    plan2 = build(work, A, template=bp.load_template("holiday_hours"))
    for p in (plan, plan2):
        captions = {bp._hook_key(" ".join(w[0] for w in ln["words"])) for ln in p["lines"]}
        for c in p.get("cards", []):
            if c["style"] == "statement":
                assert bp._hook_key(c["text"]) not in captions   # no caption repeats a card
    # whole clauses on cards: a whole sentence only up to max_words + 2 (with a WARN), else the first clause
    assert bp.card_text("Katie walked into an empty room in Mobile.", 6) == "Katie walked into an empty room in Mobile."
    assert len(bp.card_text("Katie walked into an empty room in Mobile.", 4).split()) <= 4
    assert bp.card_text("Thank you, Mobile, for one whole year of showing up.", 4) == "Thank you."


def test_before_after_with_faces_and_no_consent_is_blurred(make_job, capsys):
    work, A = make_job("photos", duration=40.0)
    A["photos"][1]["faces"] = [[0.4, 0.2, 0.2, 0.15]]
    plan = build(work, A, template=bp.load_template("transformation"), before="P1", after="P2")
    shot = next(s for s in plan["shots"] if s["src"] == A["photos"][1]["path"])
    assert shot["blur"] and "people" not in shot
    assert "faces are blurred" in capsys.readouterr().err
    assert errors(vp.validate(plan, A)) == []


def test_cli_exits_1_when_its_plan_fails_validation(make_job, run_script, monkeypatch):
    work, A = make_job("photos")
    A["photos"][0]["faces"] = [[0.4, 0.2, 0.2, 0.15]]
    A["photos"][0]["consent"] = True
    (work / "analysis.json").write_text(json.dumps(A))
    ok = run_script("baseline_plan.py", work)
    assert ok.returncode == 0, ok.stderr
    # a plan the validator rejects (here: a banned claim in the hook) must not exit 0
    bad = run_script("baseline_plan.py", work, "--hook", "Sauna cures stress.")
    assert bad.returncode == 1 and "ERROR: plan check:" in bad.stderr and "Traceback" not in bad.stderr
    assert (work / "plan.json").is_file()


def test_min_shot_seconds_holds_at_most_4_beats_or_peak(make_job):
    work, A = make_job("voice_music", duration=60.0)
    plan = build(work, A, duration=35.0, prefs={"min_shot_seconds": 2.0})
    iss = vp.validate(plan, A, {"min_shot_seconds": 2.0})
    assert not [i for i in iss if i.rule in (15, 38)], iss


# ---- polish P2 -------------------------------------------------------------------
@pytest.mark.parametrize("shape", ["voice_music", "music_only"])
def test_myth_card_never_hides_the_hook_on_frame_zero(make_job, shape):
    work, A = make_job(shape, duration=60.0)
    plan = build(work, A, template=bp.load_template("myth_vs_fact"), script=SCRIPT if shape == "music_only" else None)
    hook = plan["hook"]
    assert hook["text"] and hook["t1"] >= 1.5
    cards = plan["cards"]
    assert [c["text"] for c in cards][:1] == ["MYTH"]
    cuts = {s["t0"] for s in plan["shots"]}
    for c in cards:   # a card before hook.t1 must itself show the hook text; MYTH waits for the hook
        assert c["t0"] >= hook["t1"] or bp._hook_key(c["text"]) in bp._hook_key(hook["text"]), (c, hook)
        assert c["t0"] in cuts
    assert errors(vp.validate(plan, A)) == []


def test_script_without_duration_ends_after_its_outro(make_job):
    work, A = make_job("music_only", duration=60.0)
    script = "Three minutes of cold.\nWalk out wide awake.\nRelax, breathe, disconnect."
    plan = build(work, A, script=script)
    last = max(ln["end"] for ln in plan["lines"])
    assert plan["duration"] == pytest.approx(max(15.0, last + 7.5), abs=0.01) and plan["duration"] < 30
    assert plan["endcard"]["t"] >= last          # the end card sits inside the music-only outro
    long_script = "\n".join(f"Line number {i} of a long and careful script for the reel." for i in range(12))
    long_plan = build(work, A, script=long_script)
    assert long_plan["duration"] == 60.0         # capped by the audio (and 60 s)
    work2, A2 = make_job("music_only", duration=40.0)
    assert build(work2, A2, script=long_script)["duration"] == 40.0
    assert build(work2, A2, script=script, duration=35.0)["duration"] == 35.0   # --duration still wins
    assert errors(vp.validate(plan, A)) == []


def test_card_text_prefers_a_whole_clause_within_max_words(capsys):
    # a first clause up to 2 words over max_words wins over a later clause (it carries the context), WARN
    assert bp.card_text("Colder is not always better for you, but it isn't.", 6) \
        == "Colder is not always better for you."
    assert "over 6" in capsys.readouterr().err
    # a later whole clause only when the first one is more than 2 words over
    assert bp.card_text("Most people think the colder the water the better it works, but it isn't.", 6) \
        == "But it isn't."
    assert "WARN" not in capsys.readouterr().err
    # no clause at all: the sentence up to max_words + 2, with a WARN
    assert bp.card_text("Start with three minutes in the water.", 5) == "Start with three minutes in the water."
    assert "over 5" in capsys.readouterr().err
    # more than 2 over: never the whole clause
    assert len(bp.card_text("Start slowly with three easy minutes in the cold water today.", 5).split()) <= 5
