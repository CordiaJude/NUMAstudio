"""shoot_card.py: month skeleton, shoot cards, planning-rule checks, script.json checks, Sheet rows (T9).

R156, R158, R159, R162, R164-R168, R175-R180, R183, R184 and the digest hand-off (R181, R240).
"""
from __future__ import annotations

import copy
import csv
import io
import json
from datetime import date

import pytest

import digest_data as dd
import numa_common
import shoot_card as sc

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
ROOM = {"ask_the_dpt_reel": "sauna", "community_reel": "plunge room", "trial_reel": "outside",
        "offer_event_collab_reel": "front of house", "regulate_reel": "class studio"}
TITLES = ["Why we plunge", "Sauna vs infrared", "Gulf water in winter", "Plunge temperature", "Box breathing",
          "What red light does", "Your first plunge", "Cold snap calm", "Sweat there recover here",
          "Numa Nights tease", "Numa Nights recap", "Contrast flow basics", "Member moment", "Midtown mornings",
          "Steam and stillness", "Desk breath reset", "Heat then cold", "Plunge buddy", "New Year reset",
          "Meet Kandi", "Four count breath", "Sauna etiquette", "The front door", "Year in review",
          "Free Flow explained", "Hold the exhale", "Breath before bed"]

SPEC_EXAMPLE = {
    "day": 9, "date": "2026-12-09", "title": "Your first plunge", "series": "first_plunge", "pillar": "community",
    "goal": "community", "template": "member_story_reel", "length_s": 45, "hook_text": "Three minutes.",
    "lines": ["Three minutes. That's all it takes.", "The first ten seconds are loud. Then it gets quiet.",
              "You come out different than you went in.",
              "Try a month with Discover NUMA, $49. Send this to your plunge buddy."],
    "shots": [
        {"n": 1, "line": 1, "what": "a hand touching the water surface, slow", "framing": "close", "seconds": 5,
         "people": False, "ai_motion": False},
        {"n": 2, "line": 2, "what": "someone stepping into the plunge, shoulders down", "framing": "medium",
         "seconds": 5, "people": False, "ai_motion": False},
        {"n": 3, "line": 3, "what": "face after, eyes closed, calm", "framing": "close", "seconds": 5,
         "people": True, "ai_motion": False},
        {"n": 4, "line": 4, "what": "the plunge room, lights on, nobody in it", "framing": "wide", "seconds": 5,
         "people": False, "ai_motion": False, "library_tags": ["plunge room", "empty"]},
        {"n": 5, "line": 4, "what": "the plunge from above", "framing": "overhead", "seconds": 5, "kind": "photo",
         "people": False, "ai_motion": True},
        {"n": 6, "line": 2, "what": "steam over the sauna stones", "framing": "close", "seconds": 5,
         "people": False, "ai_motion": False, "source": "library"},
    ],
    "photos": ["a candle by the plunge"],
    "music": {"mood": "calm, warm piano", "bpm": [90, 100], "source": "generate"},
    "cta": "Try a month with Discover NUMA, $49.", "share_line": "Send this to your plunge buddy.",
    "safety_line": True, "needs_consent": True, "film_by": "2026-12-07", "batch_room": "plunge room",
}


def script_for(row: dict, title: str) -> dict:
    room = ROOM.get(row["slot"], "plunge room")
    edu = row.get("goal") == "education"
    return {
        "title": title, "topic": title, "length_s": 45 if row.get("length_class") == "growth" else 30,
        "hook_text": f"{title}.",
        "lines": [f"{title}.", "The first ten seconds are loud.", "Then it gets quiet.", "Send this to your plunge buddy."],
        "shots": [
            {"n": 1, "line": 1, "what": "a hand touching the water surface, slow", "framing": "close", "seconds": 5,
             "people": False, "ai_motion": False, "room": room, "time_of_day": "morning"},
            {"n": 2, "line": 2, "what": "someone stepping in, shoulders down", "framing": "medium", "seconds": 5,
             "people": True, "ai_motion": False, "room": room},
            {"n": 3, "line": 3, "what": "the room empty, lights on", "framing": "wide", "seconds": 5,
             "people": False, "ai_motion": False, "source": "library"},
            {"n": 4, "line": 4, "what": "the plunge from above", "framing": "overhead", "seconds": 5, "kind": "photo",
             "people": False, "ai_motion": True, "room": room},
        ],
        "music": {"mood": "calm, warm piano", "bpm": [90, 100], "source": "generate"},
        "cta": "Save this for your first visit." if edu or row.get("goal") != "offer" else "Try a month with Discover NUMA, $49.",
        "share_line": "Send this to your plunge buddy.", "safety_line": True, "needs_consent": True, "batch_room": room,
    }


def december() -> dict:
    """A complete, rule-abiding December 2026 plan built on the skeleton."""
    sk = sc.skeleton(2026, 12)
    titles = iter(TITLES)
    for r in sk["rows"]:
        if r["kind"] in ("reel", "trial_reel"):
            r.update(script_for(r, next(titles)))
        else:
            r["title"] = f"{r['post']} {r['day']}"
        r["folder"] = sc.day_folder(r["day"], date.fromisoformat(r["date"]), r["title"])
    rows = {r["day"]: r for r in sk["rows"]}
    rows[11].update(collab="Mission Fitness")
    rows[25].update(series="meet_the_collective", collab="Kandi Roemhildt", pillar="collective_collabs")
    rows[16].update(template="transformation", signature=True)
    rows[10].update(event="Numa Nights", event_role="teaser", template="event_teaser", goal="offer", sales=True,
                    pillar="offers_events", cta="Friday 7 pm. Book your spot.")
    rows[13].update(event="Numa Nights", event_role="recap", template="numa_nights_recap", series=None,
                    pillar="offers_events", goal="community", length_class="atmosphere", length_s=25)
    sk["events"] = [{"name": "Numa Nights", "date": "2026-12-12"}]
    return sk


def row(plan: dict, day: int) -> dict:
    return next(r for r in plan["rows"] if r["day"] == day)


def run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(sc.main, argv)
    return e.value.code


def write(tmp_path, obj, name="plan.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def check(tmp_path, plan, *extra):
    """Run `check --json`; return (exit code, report)."""
    return run(["check", write(tmp_path, plan), *extra, "--json"])


def violations(tmp_path, capsys, plan, *extra) -> tuple[int, list[dict]]:
    capsys.readouterr()
    code = check(tmp_path, plan, *extra)
    rep = json.loads(capsys.readouterr().out)
    return code, rep["violations"]


def rules(vs: list[dict]) -> set[str]:
    return {v["rule"] for v in vs}


# ---------------------------------------------------------------------------
# month skeleton (R158, R162)
# ---------------------------------------------------------------------------
def test_december_2026_skeleton(capsys):
    assert run(["month", "2026-12", "--json"]) == 0
    sk = json.loads(capsys.readouterr().out)
    rows = sk["rows"]
    assert sk["month"] == "2026-12" and sk["month_folder"] == "2026-12 December" and len(rows) == 31
    assert [r["day"] for r in rows] == list(range(1, 32))
    assert rows[0]["folder"] == "Day 01 - 2026-12-01 - <Title>" and rows[30]["folder"] == "Day 31 - 2026-12-31 - <Title>"
    assert rows[0]["weekday"] == "Tue" and rows[0]["kind"] == "carousel"
    want = {"Mon": ("ask_the_dpt_reel", "reel", "ask_the_dpt"), "Tue": ("carousel", "carousel", None),
            "Wed": ("community_reel", "reel", "first_plunge"), "Thu": ("trial_reel", "trial_reel", "too_hot_for_a_diy_plunge"),
            "Fri": ("offer_event_collab_reel", "reel", None), "Sat": ("stories", "stories", None),
            "Sun": ("regulate_reel", "reel", "regulate")}
    for r in rows:
        assert (r["slot"], r["kind"], r["series"]) == want[r["weekday"]], r
        assert r["status"] == "Planned"
    fridays = [r for r in rows if r["weekday"] == "Fri"]
    assert [r["pillar"] for r in fridays] == ["offers_events", "collective_collabs", "offers_events", "collective_collabs"]
    assert [r["goal"] for r in fridays] == ["offer", "community", "offer", "community"]
    assert all("sales" not in r for r in rows)  # derived from goal and text, never a stale slot flag
    assert all(r["derived_from"] == r["day"] - 1 for r in rows if r["kind"] == "carousel" and r["day"] > 1)
    for r in rows:  # batch sessions: Monday films Tue-Thu, Thursday films Fri-Mon, always before the day
        if r["film_by"]:
            fb = date.fromisoformat(r["film_by"])
            assert fb < date.fromisoformat(r["date"]) and fb.weekday() in (0, 3)
    assert row(sk, 9)["film_by"] == "2026-12-07"  # the spec card: Wed Dec 9 filmed Mon Dec 7


def test_skeleton_text_and_other_months(capsys):
    assert run(["month", "2026-12"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "2026-12 December (31 days)" and out[1].startswith("Day 01 - 2026-12-01 - <Title> · Tue · Carousel")
    assert len(sc.skeleton(2027, 2)["rows"]) == 28 and len(sc.skeleton(2028, 2)["rows"]) == 29
    assert sc.skeleton(2026, 12) == sc.skeleton(2026, 12)  # deterministic


def test_skeleton_passes_the_mix_and_cadence():
    v, _, mix = sc.check_plan(_loaded(sc.skeleton(2026, 12)), {})
    assert not {x["rule"] for x in v} & {"mix", "cadence", "1-sales-per-week", "9-batch"}
    assert mix["2026-12"]["posts"] > 20


def _loaded(plan: dict) -> dict:
    return {**plan, "rows": [{**r, "_d": date.fromisoformat(r["date"])} for r in plan["rows"]]}


@pytest.mark.parametrize("argv", [["month", "2026-13"], ["month", "December"], [], ["nope"]])
def test_usage_errors(argv, capsys):
    assert run(argv) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_folder_names_are_drive_safe():
    assert sc.day_folder(3, date(2026, 12, 3), "Sauna / plunge: why?") == "Day 03 - 2026-12-03 - Sauna plunge why"


# ---------------------------------------------------------------------------
# shoot card (R175-R178, R183, R184, R190)
# ---------------------------------------------------------------------------
def test_card_matches_the_spec_example_structure(tmp_path, capsys):
    assert run(["card", write(tmp_path, SPEC_EXAMPLE, "row.json")]) == 0
    text = capsys.readouterr().out
    lines = text.rstrip("\n").splitlines()
    assert lines[0].startswith('DAY 09 · Wed Dec 9 · "Your first plunge"')
    assert "FILM BY: Mon Dec 7 (batch shoot: plunge room)" in lines[0]
    heads = ["WHERE TO PUT FILES", "WHAT TO FILM", "READ THIS OUT LOUD", "MUSIC:"]
    pos = [next(i for i, ln in enumerate(lines) if ln.startswith(h)) for h in heads]
    assert pos == sorted(pos)
    assert "Drive > NUMA Reels > 2026-12 December > Day 09 - 2026-12-09 - Your first plunge" in text
    # filing rules at the top: where, voiceover naming and re-record, music, file names, changes
    filing = "\n".join(lines[pos[0]:pos[1]])
    for needle in ["photos/", "clips/", '"voiceover 09"', "re-record", "Music optional", "Any file names",
                   "Sheet edits optional"]:
        assert needle in filing, needle
    assert lines[pos[1]] == "WHAT TO FILM  (vertical, 4K 30 fps, hold 5 s, no zoom)"  # phone settings
    shots = [ln for ln in lines if ln.lstrip().startswith("[ ]")]
    assert [s.split(".")[0].strip() for s in shots] == ["[ ] 1", "[ ] 2", "[ ] 3", "[ ] 4", "[ ] 5"]
    assert shots[0].strip() == "[ ] 1. Close-up: a hand touching the water surface, slow (line 1)"
    assert "Medium:" in shots[1] and "Wide:" in shots[3]
    assert "consent list only; line 3" in shots[2] and "consent" not in shots[0]
    assert shots[4].strip() == "[ ] 5. Photo, overhead: the plunge from above (line 4; AI motion)"
    assert sum("AI motion" in s for s in shots) == 1
    assert "steam over the sauna stones" not in text  # library shots are not Katie's to film
    assert "Also snap: a candle by the plunge" in text
    read = lines[pos[2]]
    for tip in ["closet or carpeted room", "phone 12 in away", "one take", "1 s silence each end"]:
        assert tip in read, tip
    assert lines[pos[2] + 1] == '  "Three minutes. That\'s all it takes.'
    assert '$49. Send this to your plunge buddy."' in text
    assert "MUSIC: none needed (Claude makes it)." in text and "LENGTH: 45 s (5 shots + library)." in text
    assert lines[-1] == "IF YOU CAN'T: skip it. Claude will find another way."
    assert lines[-1].lower().startswith("if you can't: skip it.")


def test_card_reads_in_under_a_minute(tmp_path, capsys):
    """About as long as the spec p.36 example (~165 words): at most 180 words for a 5-shot card."""
    import re
    spec = {k: v for k, v in SPEC_EXAMPLE.items() if k != "photos"}  # the spec card has no extra stills
    assert run(["card", write(tmp_path, spec, "row.json")]) == 0
    text = capsys.readouterr().out
    words = re.findall(r"[A-Za-z][A-Za-z']*", text)
    assert len(words) <= 180, len(words)
    assert len(text.splitlines()) <= 25


def test_card_shot_numbers_match_the_script(tmp_path, capsys):
    s = copy.deepcopy(SPEC_EXAMPLE)
    s["shots"][1]["source"] = "library"  # shot 2 comes from the library
    assert run(["card", write(tmp_path, s, "row.json")]) == 0
    shots = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("[ ]")]
    assert [x.split(".")[0] for x in shots] == ["[ ] 1", "[ ] 3", "[ ] 4", "[ ] 5"]
    assert "(line 3)" in shots[1] or "line 3)" in shots[1]


def test_card_no_filming_needed_first_line(tmp_path, capsys):
    s = copy.deepcopy(SPEC_EXAMPLE)
    for x in s["shots"]:
        x["source"] = "library"
        x["people"] = False
    s.update(voiceover_by="generated", needs_consent=False, film_by=None, batch_room=None)
    assert run(["card", write(tmp_path, s, "row.json")]) == 0
    lines = capsys.readouterr().out.rstrip("\n").splitlines()
    assert lines[0].startswith("NO FILMING NEEDED")
    assert not any(ln.startswith(("WHAT TO FILM", "READ THIS OUT LOUD")) for ln in lines)
    assert "FILM BY" not in lines[2]
    text = "\n".join(lines)
    assert "photos/" in text and "Any file names" in text  # where-to-put-files stays
    assert "voiceover" not in text and "re-record" not in text and "Music optional" not in text  # nothing to record
    assert lines[-1].startswith("IF YOU CAN'T: skip it.")


@pytest.mark.parametrize("kind", ["stories", "carousel"])
def test_card_for_non_reel_days(tmp_path, capsys, kind):
    r = {"day": 12, "date": "2026-12-12", "title": "Class energy", "kind": kind, "post": kind.title()}
    assert run(["card", write(tmp_path, r, "row.json")]) == 0
    lines = capsys.readouterr().out.rstrip("\n").splitlines()
    assert lines[0].startswith("NO FILMING NEEDED") and lines[-1].startswith("IF YOU CAN'T: skip it.")


def test_card_voice_reader_and_capture_moment(tmp_path, capsys):
    s = copy.deepcopy(SPEC_EXAMPLE)
    s["voiceover_by"] = "Fallon Gleason"
    s["shots"][0]["during"] = "Numa Nights"
    s["music"] = {"mood": "warm, slow", "bpm": [70, 80], "source": "library", "track": "calm_72_ember.mp3"}
    out = tmp_path / "cards" / "SHOOT CARD.txt"
    assert run(["card", write(tmp_path, s, "row.json"), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "READ THIS OUT LOUD (Fallon Gleason reads this)" in text
    assert "(during Numa Nights; line 1)" in text
    assert 'Music Library "calm_72_ember.mp3"' in text


def test_card_rejects_bad_rows_cleanly(tmp_path, capsys):
    s = copy.deepcopy(SPEC_EXAMPLE)
    del s["shots"][0]["framing"]
    assert run(["card", write(tmp_path, s, "row.json")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "framing" in err and "Traceback" not in err
    assert run(["card", str(tmp_path / "missing.json")]) == 1


# ---------------------------------------------------------------------------
# script.json checker (R179, R180, R187, R191)
# ---------------------------------------------------------------------------
def script_errors(s: dict) -> tuple[list[str], list[str]]:
    return sc.script_problems(s, sc.load_templates(), where="t")


def test_schema_validates_the_documented_example(nc):
    assert nc.schema_errors("script.schema.json", SPEC_EXAMPLE) == []
    assert script_errors(SPEC_EXAMPLE) == ([], [])


def test_script_cli(tmp_path, capsys):
    assert run(["script", write(tmp_path, SPEC_EXAMPLE, "script.json"), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["ok"] is True and rep["errors"] == [] and rep["words"] == 37
    bad = copy.deepcopy(SPEC_EXAMPLE)
    bad["lines"][1] = "Cold plunge cures anxiety."
    assert run(["script", write(tmp_path, bad, "bad.json")]) == 1
    assert 'ERROR: banned claim' in capsys.readouterr().err


def mutate(**kw):
    s = copy.deepcopy(SPEC_EXAMPLE)
    s.update(kw)
    return s


def with_shots(n_new: int, n_library: int = 0) -> dict:
    shots = [{"n": i + 1, "line": 1 + i % 4, "what": f"shot {i + 1}", "framing": "wide", "seconds": 5,
              "people": False, "ai_motion": i == 0} for i in range(n_new + n_library)]
    for x in shots[n_new:]:
        x["source"] = "library"
    return mutate(shots=shots, needs_consent=False)


@pytest.mark.parametrize("case, needle", [
    (lambda: mutate(lines=SPEC_EXAMPLE["lines"] + ["word " * 60]), "words"),
    (lambda: mutate(length_s=20), "words"),  # 38 words > 2.3 x (20 - 7.5)
    (lambda: with_shots(9), "9 new shots"),
    (lambda: mutate(shots=[{**x, "ai_motion": False} for x in SPEC_EXAMPLE["shots"]]), "0 AI motion"),
    (lambda: mutate(shots=[{**x, "ai_motion": x["n"] in (1, 5)} for x in SPEC_EXAMPLE["shots"]]), "2 AI motion"),
    (lambda: mutate(needs_consent=False), "needs_consent"),
    (lambda: mutate(shots=[{**x, "line": 9} if x["n"] == 2 else x for x in SPEC_EXAMPLE["shots"]]), "tied to line 9"),
    (lambda: mutate(shots=[{**x, "n": x["n"] + 1} for x in SPEC_EXAMPLE["shots"]]), "numbered"),
    (lambda: mutate(shots=[{k: v for k, v in x.items() if k != "seconds"} for x in SPEC_EXAMPLE["shots"]]), "seconds"),
    (lambda: mutate(shots=[{k: v for k, v in x.items() if k != "line"} for x in SPEC_EXAMPLE["shots"]]), "line"),
    (lambda: mutate(film_by="2026-12-09"), "film_by"),
    (lambda: mutate(film_by=None), "film_by"),
    (lambda: mutate(template="tiktok_dance"), "unknown template"),
    (lambda: mutate(series="ask_the_dpt", pillar="education", goal="education"), "Ask the DPT"),
    (lambda: mutate(hook_text="Cold plunge burns fat."), "banned claim"),
    (lambda: mutate(caption={"text": "Recover with us.", "hashtags": ["#MobileAL", "#detox"]}), "banned claim"),
    (lambda: mutate(cta="Studies show it heals."), "banned claim"),
    (lambda: mutate(goal="sales"), "goal"),
    (lambda: mutate(day=7), "does not match date"),
    (lambda: mutate(series="ask_the_dpt", pillar="education", goal="education", cta="Save this.",
                    lines=["Sauna or infrared?", "Here is what we know.", "Book your first month, $49."]), "Ask the DPT"),
])
def test_script_rules_fail(case, needle):
    errs, _ = script_errors(case())
    assert errs and any(needle in e for e in errs), errs


def test_script_rules_pass_at_the_limits():
    assert script_errors(with_shots(8, 6))[0] == []  # 8 new + library shots is fine
    limit = int(2.3 * (45 - 7.5))  # 86 words
    rest = SPEC_EXAMPLE["lines"][1:]
    base = sum(len(x.split()) for x in rest) + 2
    s = mutate(lines=["Three minutes. " + "calm " * (limit - base)] + rest)
    assert script_errors(s)[0] == []
    over = mutate(lines=["Three minutes. " + "calm " * (limit - base + 1)] + rest)
    assert any("words" in e for e in script_errors(over)[0])
    assert script_errors(mutate(lines=over["lines"], outro_s=6))[0] == []  # a 6 s outro leaves room for more words


def test_script_warnings():
    _, warns = script_errors(mutate(share_line=None, safety_line=False))
    assert any("share line" in w for w in warns) and any("safety_line" in w for w in warns)


# ---------------------------------------------------------------------------
# month check: planning rules (R159, R164-R168)
# ---------------------------------------------------------------------------
def test_december_plan_passes(tmp_path, capsys):
    code, vs = violations(tmp_path, capsys, december())
    assert code == 0 and vs == []
    assert run(["check", write(tmp_path, december())]) == 0
    assert capsys.readouterr().out.startswith("OK: 31 rows pass")


def test_rule1_topic_repeat(tmp_path, capsys):
    p = december()
    row(p, 9)["topic"] = row(p, 2)["topic"]
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rules(vs) == {"1-topic-repeat"} and vs[0]["days"] == [2, 9]
    p = december()
    row(p, 16)["topic"] = row(p, 2)["topic"]  # 14 days apart is allowed
    assert violations(tmp_path, capsys, p)[0] == 0


def test_rule1_one_sales_reel_a_week(tmp_path, capsys):
    p = december()
    row(p, 9)["sales"] = True  # the week of Dec 7 already has the Numa Nights teaser
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and "1-sales-per-week" in rules(vs)


@pytest.mark.parametrize("day, change, rule", [
    (7, {"length_s": 30}, "2-length"),           # Ask the DPT runs 45-60
    (13, {"length_s": 40}, "2-length"),          # atmosphere 15-30
    (9, {"length_s": 200}, "2-length"),          # over the 180 s hard max (schema caps it too)
    (9, {"repost": True}, "3-original"),
])
def test_rules_2_and_3(tmp_path, capsys, day, change, rule):
    p = december()
    row(p, day).update(change)
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rule in rules(vs)


def test_rule4_collab_and_meet_the_collective(tmp_path, capsys):
    p = december()
    row(p, 11)["collab"] = None
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rules(vs) == {"4-collab"}
    p = december()
    row(p, 25)["series"] = None
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and {"4-meet-the-collective", "series"} <= rules(vs)


def test_rule6_signature(tmp_path, capsys):
    p = december()
    row(p, 16).update(template="member_story", signature=False)
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rules(vs) == {"6-signature"}


def test_rule7_event_windows(tmp_path, capsys):
    p = december()
    row(p, 10).update(event_role=None, event=None)  # no teaser
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and "7-event-window" in rules(vs)
    p = december()
    p["events"] = [{"name": "Numa Nights", "date": "2026-12-11"}]  # teaser Dec 10 is 1 day before; recap Dec 13 is 2 after
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any("teaser" in v["message"] for v in vs) and not any("recap" in v["message"] for v in vs)
    p = december()
    p["events"].append({"name": "Clinical Conversations", "date": "2026-12-20"})
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and len([v for v in vs if v["rule"] == "7-event-window"]) == 2


def test_rule8_closures_from_file_csv_and_plan(tmp_path, capsys):
    jf = tmp_path / "closures.json"
    jf.write_text(json.dumps({"closures": [{"date": "2026-12-04", "name": "staff day"}]}), encoding="utf-8")
    code, vs = violations(tmp_path, capsys, december(), "--closures", str(jf))
    assert code == 1 and rules(vs) == {"8-closure"} and "staff day" in vs[0]["message"]
    cf = tmp_path / "closures.csv"
    cf.write_text("Date,Name\n2026-12-25,Christmas\n", encoding="utf-8")
    p = december()
    row(p, 25)["cta"] = "Come in and see us."
    code, vs = violations(tmp_path, capsys, p, "--closures", str(cf))
    assert code == 1 and rules(vs) == {"8-closure"}
    p = december()
    p["closures"] = ["2026-12-12", "2026-12-25"]  # Stories day and a non-inviting collab reel: fine
    assert violations(tmp_path, capsys, p)[0] == 0
    p["closures"] = ["2026-12-10"]  # the teaser invites people in
    assert rules(violations(tmp_path, capsys, p)[1]) == {"8-closure"}


def test_rule9_batch_sessions(tmp_path, capsys):
    p = december()
    row(p, 9)["film_by"] = "2026-12-08"  # Mon, Tue and Thu of one week
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rules(vs) == {"9-batch"}
    p = december()
    row(p, 9)["film_by"] = "2026-12-09"
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and "9-batch" in rules(vs)


def test_cadence(tmp_path, capsys):
    p = december()
    for d in (7, 8):  # Mon + Tue of the week of Dec 7 become Stories: 3 feed posts
        row(p, d).update(kind="stories", series=None)
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any(v["rule"] == "cadence" and "3 feed posts" in v["message"] for v in vs)
    p = december()
    row(p, 17).update(kind="reel", trial_reel=False)  # no Trial Reel that week, and 6 feed posts
    code, vs = violations(tmp_path, capsys, p)
    msgs = [v["message"] for v in vs if v["rule"] == "cadence"]
    assert code == 1 and any("0 Trial Reels" in m for m in msgs) and any("6 feed posts" in m for m in msgs)
    p = december()
    p["rows"] = [r for r in p["rows"] if r["day"] != 19]
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any("nothing planned" in v["message"] for v in vs)


def test_series_rotation_and_ask_the_dpt(tmp_path, capsys):
    p = december()
    for r in p["rows"]:
        if r.get("series") == "regulate":
            r["series"] = None
            r.pop("length_class", None)
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any(v["rule"] == "series" and "regulate" in v["message"] for v in vs)
    p = december()
    row(p, 14)["sales"] = True
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any("Ask the DPT" in v["message"] for v in vs)


def test_mix_tolerance(tmp_path, capsys):
    p = december()
    for r in p["rows"]:
        if r["pillar"] == "local_seasonal":
            r["pillar"] = "education"
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and {v["rule"] for v in vs} == {"mix"}
    p["mix_tolerance"] = 0.5
    assert violations(tmp_path, capsys, p)[0] == 0
    p = december()
    p["mix"] = {"education": 0.6, "community": 0.1, "local_seasonal": 0.1, "collective_collabs": 0.1, "offers_events": 0.1}
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any("target 60%" in v["message"] for v in vs)
    p["mix"] = {"education": 1.0}
    assert check(tmp_path, p) == 1  # an invalid mix is an input error


def test_card_rules_inside_the_month_check(tmp_path, capsys):
    p = december()
    row(p, 9)["shots"][1]["people"] = True
    row(p, 9)["needs_consent"] = False
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and rules(vs) == {"card"} and vs[0]["days"] == [9]


def test_check_text_output_and_bad_input(tmp_path, capsys):
    p = december()
    row(p, 9)["topic"] = row(p, 2)["topic"]
    assert run(["check", write(tmp_path, p)]) == 1
    err = capsys.readouterr().err
    assert "ERROR: rule 1-topic-repeat: Day 09 (2026-12-09)" in err
    for bad in ({"rows": [{"day": 2, "date": "2026-12-01", "kind": "reel"}]},
                {"rows": [{"day": 1, "date": "2026-12-01", "kind": "tiktok"}]},
                {"rows": [{"day": 1, "kind": "reel"}]},
                {"rows": "nope"}):
        assert check(tmp_path, bad) == 1
        assert "Traceback" not in capsys.readouterr().err
    assert run(["check", write(tmp_path, december()), "--closures", str(tmp_path / "none.json")]) == 1


def test_partial_month_skips_monthly_rules(tmp_path, capsys):
    p = december()
    p["rows"] = [r for r in p["rows"] if r["day"] <= 20]
    p["events"] = []
    for d in (10, 13):
        row(p, d).update(event=None, event_role=None)
    capsys.readouterr()
    assert check(tmp_path, p) == 0
    rep = json.loads(capsys.readouterr().out)
    assert any("no full calendar month" in w for w in rep["warnings"]) and rep["mix"] == {}


# ---------------------------------------------------------------------------
# Sheet rows (R156) and the digest hand-off (R181, R240)
# ---------------------------------------------------------------------------
def test_sheet_json_columns_exact(tmp_path, capsys):
    assert run(["sheet", write(tmp_path, december())]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 31
    assert sc.SHEET_COLUMNS == ["Day", "Date", "Title", "Goal", "Template", "Hook (first 2 seconds)", "Voiceover script",
                                "Shot list", "Music mood + BPM", "Call to action", "Status", "Folder link", "Reel link"]
    assert all(list(r) == sc.SHEET_COLUMNS for r in rows)
    r9 = rows[8]
    assert r9["Day"] == 9 and r9["Date"] == "2026-12-09" and r9["Status"] == "Planned"
    assert r9["Music mood + BPM"] == "calm, warm piano, 90-100 BPM" and r9["Template"] == "member_story"
    assert r9["Voiceover script"].count("\n") == 3
    assert r9["Shot list"].splitlines()[0] == "1. [plunge room] Close-up: a hand touching the water surface, slow, 5 s, morning (line 1)"
    assert "consent list only" in r9["Shot list"] and "AI motion shot" in r9["Shot list"]
    assert "the room empty" not in r9["Shot list"]  # library shots are not on the shoot list
    assert rows[0]["Shot list"] == "No filming needed" and rows[4]["Shot list"] == "No filming needed"
    assert set(sc.STATUSES) == {"Planned", "Shot", "Ready to build", "Ready to post", "Posted"}


def test_sheet_csv_and_status_validation(tmp_path, capsys):
    out = tmp_path / "sheet.csv"
    assert run(["sheet", write(tmp_path, december()), "--csv", "--out", str(out)]) == 0
    reader = csv.DictReader(io.StringIO(out.read_text(encoding="utf-8")))
    assert reader.fieldnames == sc.SHEET_COLUMNS and len(list(reader)) == 31
    p = december()
    row(p, 3)["status"] = "Done"
    assert run(["sheet", write(tmp_path, p)]) == 1
    assert "status must be one of" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_digest_data_reads_the_export(tmp_path, capsys, fmt):
    out = tmp_path / f"rows.{fmt}"
    argv = ["sheet", write(tmp_path, december()), "--out", str(out)] + (["--csv"] if fmt == "csv" else [])
    assert run(argv) == 0
    rows = dd.load_rows(str(out))
    assert len(rows) == 31 and rows[8]["hook"] == row(december(), 9)["hook_text"] and rows[8]["music"].endswith("BPM")
    data = dd.assemble(dd.mx.empty_store(), rows, None, {}, date(2026, 12, 6))
    week = data["this_week"]["rows"]
    assert [r["date"] for r in week][0] == "2026-12-07" and len(week) == 7
    assert [r["no_filming"] for r in week] == [False, True, False, False, False, True, False]
    sl = data["shoot_list"]
    assert [g["room"] for g in sl["rooms"]] == sc.ROOMS  # every shot lands in a named room, in the digest's order
    assert sl["shot_count"] == 15 and len(sl["voiceovers"]) == 5
    assert sl["rooms"][0]["shots"][0]["time_of_day"] == "morning"


def test_rooms_match_the_digest():
    assert sc.ROOMS == dd.ROOMS


# ---------------------------------------------------------------------------
# sales are derived, never a stale flag (rule 1)
# ---------------------------------------------------------------------------
def test_sales_from_goal_even_with_a_stale_false_flag(tmp_path, capsys):
    p = december()
    row(p, 2).update(goal="offer", sales=False, cta="Book your first month")  # Fri Dec 4 is the week's offer
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and "1-sales-per-week" in rules(vs)


def test_sales_from_cta_text_only(tmp_path, capsys):
    p = december()
    row(p, 2).update(cta="Book your first month", template="offer_promo")  # goal stays community
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and "1-sales-per-week" in rules(vs)
    p = december()
    row(p, 2)["lines"] = row(p, 2)["lines"][:3] + ["Try a month with Discover NUMA, $49."]
    assert "1-sales-per-week" in rules(violations(tmp_path, capsys, p)[1])


def test_sales_flag_forces_and_collab_friday_is_not_sales(tmp_path, capsys):
    p = december()
    row(p, 2)["sales"] = True
    assert "1-sales-per-week" in rules(violations(tmp_path, capsys, p)[1])
    p = december()
    assert not sc.is_sales(row(p, 11)) and not sc.is_sales(row(p, 25))  # collab Fridays
    assert sc.is_sales(row(p, 4)) and sc.is_sales(row(p, 18))  # offer Fridays
    assert violations(tmp_path, capsys, p)[0] == 0


def test_offer_hidden_in_an_ask_the_dpt_reel(tmp_path, capsys):
    p = december()
    row(p, 14)["lines"] = row(p, 14)["lines"][:3] + ["Discover NUMA is $49 for your first month."]
    code, vs = violations(tmp_path, capsys, p)
    assert code == 1 and any("Ask the DPT" in v["message"] for v in vs)


def test_month_piped_into_closed_reader_exits_quietly():
    # `shoot_card.py month 2026-12 | head`: the reader goes away before all lines are written
    import subprocess
    import sys
    proc = subprocess.Popen([sys.executable, sc.__file__, "month", "2026-12"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdout.close()          # closed before the first write: every write hits a broken pipe
    err = proc.stderr.read()
    proc.stderr.close()
    assert proc.wait(timeout=60) == 0
    assert b"BrokenPipe" not in err and b"ERROR" not in err and b"Traceback" not in err
