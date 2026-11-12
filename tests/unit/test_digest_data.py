"""digest_data.py: Monday digest numbers from metrics, ledger and plan rows (R240, R181, R239)."""
from __future__ import annotations

import json

import pytest

import digest_data as dd
import ledger as lg
import numa_common


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(dd.main, argv)
    return e.value.code


def store():
    def reel(title, when, views, shares, awt):
        return {"tags": {"title": title, "length": 30, "posting_time": when, "series": "first_plunge"},
                "pulls": {"72h": {"pulled_at": None, "metrics": {"views": views, "reach": views // 2, "shares": shares,
                                                                "saves": 2, "avg_watch_time_ms": awt, "skip_rate": 50}}}}
    return {"schema_version": 1, "account": {"daily": {}, "totals": {}}, "reels": {
        "old": reel("Older reel", "2026-11-03T17:00:00-06:00", 400, 1, 6000),
        "a": reel("Your first plunge", "2026-11-10T17:00:00-06:00", 2400, 30, 15000),
        "b": reel("Sauna vs infrared", "2026-11-12T23:30:00-06:00", 900, 4, 9000),
        "late": reel("Sunday late post", "2026-11-15T23:30:00-06:00", 100, 0, 3000),  # still Sunday in Central
    }}


ROWS = [
    {"Day": "15", "Date": "2026-11-16", "Title": "Ask the DPT", "Goal": "education", "Status": "Planned",
     "Voiceover script": "Sauna or infrared?",
     "Shot list": "1. Close-up: sauna door opening, morning\n2. Wide: the plunge room empty\n3. Room: front of house | Katie at the desk"},
    {"Day": "16", "Date": "2026-11-17", "Title": "Carousel", "Goal": "education", "Status": "Planned", "Shot list": "No filming needed"},
    {"Day": "17", "Date": "2026-11-18", "Title": "First plunge", "Status": "Planned", "Voiceover script": "Three minutes.",
     "Shots": [{"shot": "Hand on the water", "room": "plunge room", "time_of_day": "morning", "minutes": 2},
               {"shot": "The sign out front", "time_of_day": "evening"}]},
    {"Day": "18", "Date": "2026-11-19", "Title": "Already shot", "Status": "Shot", "Shot list": "sauna glow"},
    {"Day": "13", "Date": "2026-11-14", "Title": "Posted, no insights", "Status": "Posted"},
    {"Day": "", "Date": "", "Title": ""},
]


def test_assemble(nc, tmp_path):
    led = tmp_path / "ledger.json"
    lg.main(["add", "--ledger", str(led), "--job", "kling_pro_5s", "--reel", "a", "--date", "2026-11-09"])
    rows_f = tmp_path / "rows.json"
    rows_f.write_text(json.dumps(ROWS))
    d = dd.assemble(store(), dd.load_rows(str(rows_f)), str(led), {"changes": ["Shorter hooks on education reels"]},
                    dd.date(2026, 11, 15))
    lw = d["last_week"]
    assert (lw["start"], lw["end"]) == ("2026-11-09", "2026-11-15")
    assert [r["reel"] for r in lw["reels"]] == ["a", "b", "late"]
    a = lw["reels"][0]
    assert a["views"] == 2400 and a["avg_watch_time_s"] == 15.0 and a["sends"] == 30
    assert lw["best"]["reel"] == "a" and any("retention" in s for s in lw["best"]["signals"])
    assert lw["posted_without_insights"][0]["title"] == "Posted, no insights"
    assert [r["date"] for r in d["this_week"]["rows"]] == ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]
    assert d["this_week"]["rows"][1]["no_filming"] is True
    sl = d["shoot_list"]
    assert [g["room"] for g in sl["rooms"]] == ["plunge room", "sauna", "front of house", "outside"]
    plunge = sl["rooms"][0]
    assert [s["shot"] for s in plunge["shots"]] == ["Hand on the water", "Wide: the plunge room empty"]  # morning first
    assert plunge["minutes"] == 2 + 1 + 3
    assert len(sl["voiceovers"]) == 2 and sl["shot_count"] == 5  # "Already shot" row excluded
    assert sl["total_minutes"] == pytest.approx(6 + 4 + 4 + 4 + 2 * 2)
    assert d["budget"]["used"] == 8.75 and d["budget"]["month"] == "2026-11"
    assert "heads_ups" in d["needs_director"] and "changes" not in d["needs_director"]


def test_budget_numbers(nc, tmp_path):
    led = tmp_path / "ledger.json"
    lg.main(["add", "--ledger", str(led), "--job", "kling_pro_5s", "--date", "2026-11-09"])
    b = dd.budget(str(led), dd.date(2026, 11, 15))
    assert b["used"] == 8.75 and b["left"] == 1191.25 and b["reels_covered"] == 24


def test_cli_outputs_and_csv(nc, tmp_path, capsys):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(store()))
    csv_f = tmp_path / "plan.csv"
    csv_f.write_text("Day,Date,Title,Goal,Status,Shot list\n"
                     "15,2026-11-16,Ask the DPT,education,Planned,\"Sauna door, morning\nOutside sign\"\n")
    out, txt = tmp_path / "d.json", tmp_path / "d.txt"
    args = ["--metrics", str(m), "--plan-rows", str(csv_f), "--today", "2026-11-15"]
    assert run(args + ["--out", str(out), "--text", str(txt)]) == 0
    text = txt.read_text()
    assert text.startswith("NUMA MONDAY DIGEST · week of Nov 16")
    for part in ("1. LAST WEEK", "Your first plunge: 2,400 views, 15.0 s avg watch, 30 sends", "Best: Your first plunge",
                 "3. THIS WEEK", "Mon Nov 16: Ask the DPT", "4. SHOOT LIST", "SAUNA", "OUTSIDE"):
        assert part in text
    assert "5. BUDGET" not in text  # no ledger given: left for the Director
    assert json.loads(out.read_text())["needs_director"] == ["last_week.best.why", "changes", "heads_ups", "budget"]
    # deterministic
    assert run(args + ["--out", str(tmp_path / "d2.json")]) == 0
    assert (tmp_path / "d2.json").read_bytes() == out.read_bytes()
    capsys.readouterr()
    assert run(args + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["today"] == "2026-11-15"


def test_week_bounds(nc):
    assert dd.week_bounds(dd.date(2026, 11, 15))[2] == dd.date(2026, 11, 16)  # Sunday -> next Monday
    assert dd.week_bounds(dd.date(2026, 11, 16))[2] == dd.date(2026, 11, 16)  # Monday -> today
    assert dd.week_bounds(dd.date(2026, 11, 18))[2] == dd.date(2026, 11, 23)


def test_errors(nc, tmp_path):
    bad = tmp_path / "rows.json"
    bad.write_text(json.dumps([{"Date": "16/11/2026", "Title": "x"}]))
    assert run(["--metrics", str(tmp_path / "m.json"), "--plan-rows", str(bad)]) == 1
    bad.write_text(json.dumps({"rows": "nope"}))
    assert run(["--metrics", str(tmp_path / "m.json"), "--plan-rows", str(bad)]) == 1
    assert run(["--metrics", str(tmp_path / "m.json"), "--plan-rows", str(tmp_path / "none.json")]) == 1
    assert run(["--metrics", "m", "--plan-rows", "r", "--today", "soon"]) == 2
    assert run([]) == 2


def test_us_dates_and_tidy_shots(nc, tmp_path):
    csv_f = tmp_path / "plan.csv"
    csv_f.write_text("Day,Date,Title,Status,Shot list\n"
                     "15,11/16/2026,Ask the DPT,Planned,\"[class studio] Fallon on the mat, morning\nroom: sauna | wide of the benches\"\n"
                     "16,11/17/26,Carousel,Planned,No filming needed\n")
    rows = dd.load_rows(str(csv_f))
    assert [r["date"] for r in rows] == [dd.date(2026, 11, 16), dd.date(2026, 11, 17)]
    d = dd.assemble(store(), rows, None, {}, dd.date(2026, 11, 15))
    shots = {g["room"]: [s["shot"] for s in g["shots"]] for g in d["shoot_list"]["rooms"]}
    assert shots == {"sauna": ["wide of the benches"], "class studio": ["Fallon on the mat, morning"]}
    text = dd.text_draft(d)
    assert "[class studio]" not in text and "morning · morning" not in text
    assert "Fallon on the mat, morning · Day 15" in text
    best = d["last_week"]["best"]["signals"]
    assert all(not any(len(n.split(".")[-1]) > 1 for n in sig.replace("%", "").split() if n[:1].isdigit() and "." in n)
               for sig in best)


def test_bad_us_date(nc, tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("Date,Title\n13/45/2026,x\n")
    with pytest.raises(nc.UserError):
        dd.load_rows(str(f))
