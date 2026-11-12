"""prefs.py: feedback memory, de-duplication and numeric limits honoured by validate_plan (R276-R278)."""
from __future__ import annotations

import json

import pytest

import numa_common
import prefs
import validate_plan


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(prefs.main, argv)
    return e.value.code


@pytest.mark.parametrize("note,key,value", [
    ("fewer whips", "max_whips", 1),
    ("Too many whip transitions!", "max_whips", 1),
    ("no whips please", "max_whips", 0),
    ("bigger captions", "caption_px", 104),
    ("more people", "min_people_shots", 2),
    ("shorter hooks", "max_hook_words", 6),
    ("softer light leaks", "max_leak_strength", 0.35),
    ("fewer flashes", "max_flashes", 1),
    ("it feels too choppy", "min_shot_seconds", 1.0),
    ("shorter captions", "max_caption_chars", 50),
])
def test_rule_mapping(nc, note, key, value):
    r = prefs.match_rule(note)
    assert r is not None and r.key == key and r.value(1) == value


def test_dedup_and_tightening(nc, tmp_path, capsys):
    f = tmp_path / "preferences.json"
    assert run(["add", "--file", str(f), "fewer whips", "--date", "2026-12-01"]) == 0
    assert run(["add", "--file", str(f), "Fewer whips, please.", "--date", "2026-12-03"]) == 0
    assert run(["add", "--file", str(f), "too many whips", "--date", "2026-12-05"]) == 0
    assert run(["add", "--file", str(f), "Use the teal more in the end card", "--date", "2026-12-05"]) == 0
    data = json.loads(f.read_text())
    assert len(data["notes"]) == 2
    whips = data["notes"][0]
    assert whips["times"] == 3 and whips["first_date"] == "2026-12-01" and whips["last_date"] == "2026-12-05"
    assert data["notes"][1]["rule"] is None
    assert data["limits"] == {"max_whips": 0}  # 1, then tightened one step, bounded at 0
    assert "Already noted" in capsys.readouterr().out


def test_limits_feed_validator(nc, tmp_path, plan_factory, capsys):
    f = tmp_path / "preferences.json"
    plan = plan_factory()
    plan["shots"][1]["tr"] = "whip"
    assert not [i for i in validate_plan.validate(plan, None, {}, None) if i.rule == 38]
    run(["add", "--file", str(f), "no whips", "--date", "2026-12-01"])
    # the preferences file itself is a valid --prefs file
    issues = validate_plan.validate(plan, None, validate_plan.load_prefs(f), None)
    assert any(i.rule == 38 and "max_whips" in i.message for i in issues)
    out = tmp_path / "limits.json"
    capsys.readouterr()
    assert run(["export", "--file", str(f), "--out", str(out)]) == 0
    assert validate_plan.load_prefs(out) == {"max_whips": 0}
    capsys.readouterr()
    assert run(["limits", "--file", str(f), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"max_whips": 0}


def test_contradictions_later_wins(nc, tmp_path):
    f = tmp_path / "p.json"
    run(["add", "--file", str(f), "bigger captions", "--date", "2026-12-01"])
    run(["add", "--file", str(f), "smaller captions", "--date", "2026-12-02"])
    run(["add", "--file", str(f), "too slow", "--date", "2026-12-03"])        # max_shot_seconds 3.0
    for d in ("2026-12-04", "2026-12-05", "2026-12-06", "2026-12-07", "2026-12-08"):
        run(["add", "--file", str(f), "slower cuts", "--date", d])            # min_shot_seconds up to 2.0
    limits = json.loads(f.read_text())["limits"]
    assert limits["caption_px"] == 84
    assert limits["min_shot_seconds"] == 2.0 and limits["max_shot_seconds"] == 3.0
    run(["add", "--file", str(f), "snappier", "--date", "2026-12-09"])       # max 3.0 -> 2.5
    run(["add", "--file", str(f), "more cuts", "--date", "2026-12-10"])      # -> 2.0
    run(["add", "--file", str(f), "faster pace", "--date", "2026-12-11"])    # -> 1.5 < min 2.0: older min dropped
    limits = json.loads(f.read_text())["limits"]
    assert limits["max_shot_seconds"] == 1.5 and "min_shot_seconds" not in limits


def test_errors(nc, tmp_path, capsys):
    f = tmp_path / "p.json"
    assert run(["add", "--file", str(f), "   "]) == 1
    assert run(["list", "--file", str(f)]) == 1
    f.write_text("[]")
    assert run(["list", "--file", str(f)]) == 1
    assert run(["add", "--file", str(f), "x", "--date", "Dec 1"]) == 2
    assert run([]) == 2
