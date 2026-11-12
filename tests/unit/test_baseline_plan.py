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
    assert 3 <= len(fm["story"]) <= 5 and 5 <= len(fm["carousel"]) <= 8 and fm["cover"]["title"]


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
    plan = build(work, A, script="Three minutes of cold.\nWalk out wide awake.\nRelax, breathe, disconnect.")
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
