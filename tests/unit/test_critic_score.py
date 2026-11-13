"""critic_score.py: weighted total and pass rule (R211), rounds and ship-the-best fallback."""
from __future__ import annotations

import json

import pytest

import critic_score as cs
import numa_common

IDS = ["hook", "retention_pacing", "story_clarity", "shareability", "beat_sync_transitions", "captions",
       "brand_look", "audio_mix"]


def sheet(default=4, **over):
    s = {k: default for k in IDS}
    s.update(over)
    return s


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(cs.main, argv)
    return e.value.code


def test_weights_sum_to_100(nc):
    assert sum(c["weight"] for c in cs.rubric()) == 100
    assert [c["id"] for c in cs.rubric()] == IDS


def test_total_and_exact_80(nc):
    assert cs.evaluate(sheet(5))["total"] == 100
    r = cs.evaluate(sheet(4))  # 4/5 of 100 = exactly 80
    assert r["total"] == 80 and r["passed"]


def test_79_9_fails_80_passes(nc):
    rub = [{"id": "hook", "weight": 20}, {"id": "a", "weight": 79.875}, {"id": "b", "weight": 0.125}]
    low = cs.evaluate({"hook": 4, "a": 4, "b": 5}, rub=rub)   # 16 + 63.9 + 0.125 = 80.025 -> pass
    assert low["passed"]
    rub2 = [{"id": "hook", "weight": 20}, {"id": "a", "weight": 79.9}, {"id": "b", "weight": 0.1}]
    r = cs.evaluate({"hook": 4, "a": 4, "b": 3}, rub=rub2)    # 16 + 63.92 + 0.06 = 79.98: no rounding up
    assert r["total_exact"] == str(cs.Fraction(3999, 50)) and not r["passed"]
    assert any("total 79.98 < 80" in x for x in r["reasons"])


def test_hook_3_fails_even_with_high_total(nc):
    r = cs.evaluate(sheet(5, hook=3))
    assert r["total"] == 92 and not r["passed"] and any("hook 3 < 4" in x for x in r["reasons"])


def test_category_of_2_fails(nc):
    r = cs.evaluate(sheet(5, captions=2))
    assert r["total"] == 94 and not r["passed"] and any("captions 2" in x for x in r["reasons"])


def test_hard_gate_overrides(nc, tmp_path, capsys):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"scores": sheet(5), "hard_gates_failed": ["Music with no recorded license source"]}))
    assert run(["score", str(f)]) == 1
    assert "hard gate failed" in capsys.readouterr().out
    assert run(["score", json.dumps(sheet(5))]) == 0
    assert run(["score", json.dumps(sheet(5)), "--gate-failed", "Black bars"]) == 1


@pytest.mark.parametrize("bad", [
    {k: 4 for k in IDS[:-1]},                 # missing a category
    sheet(4, hook=6),                         # out of range
    sheet(4, hook=0),
    sheet(4, hook=4.5),                       # not an integer
    sheet(4, hook=True),
    sheet(4, hook="4"),
    {**sheet(4), "vibes": 5},                 # unknown category
])
def test_validation(nc, bad):
    with pytest.raises(nc.UserError):
        cs.parse_sheet(bad)


def test_rounds_ship_best(nc, tmp_path, capsys):
    rf = tmp_path / "rounds.json"
    assert run(["round", "--rounds", str(rf), "--version", "v1", json.dumps(sheet(4, hook=3)), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "revise"
    assert run(["round", "--rounds", str(rf), "--version", "v2", json.dumps(sheet(5, captions=2)),
                "--gate-failed", "Frozen frame", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "revise"
    assert run(["round", "--rounds", str(rf), "--version", "v3", json.dumps(sheet(3, hook=4)), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    # v2 scored highest but failed a hard gate; v1 (84) beats v3 (64)
    assert out["decision"] == "ship_best" and out["ship_version"] == "v1" and out["ship_round"] == 1
    assert run(["round", "--rounds", str(rf), "--version", "v4", json.dumps(sheet(5))]) == 1  # max 3 rounds
    assert run(["best", "--rounds", str(rf), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "v1"


def test_rounds_pass_and_hold(nc, tmp_path, capsys):
    rf = tmp_path / "r.json"
    assert run(["round", "--rounds", str(rf), "--version", "a", json.dumps(sheet(4))]) == 0
    assert "Decision: ship a" in capsys.readouterr().out
    assert run(["round", "--rounds", str(rf), "--version", "b", json.dumps(sheet(4))]) == 1  # already passed
    rf2 = tmp_path / "r2.json"
    for v in ("a", "b", "c"):
        run(["round", "--rounds", str(rf2), "--version", v, json.dumps(sheet(5)), "--gate-failed", "Banned claim"])
    assert json.loads(rf2.read_text())["decision"] == "hold"
    assert run(["best", "--rounds", str(rf2)]) == 1


def test_integral_floats_accepted(nc):
    scores, _ = cs.parse_sheet(sheet(4.0, hook=5.0))
    assert scores["hook"] == 5 and isinstance(scores["hook"], int)
    assert cs.evaluate(scores)["total"] == 84
