"""ledger.py: Higgsfield credit ledger and budget rules (R216, R219, R220, R228)."""
from __future__ import annotations

import json
from datetime import date

import pytest

import ledger as lg


def add(tmp, *args):
    return lg.main(["add", "--ledger", str(tmp), *map(str, args)])


def run(argv):
    with pytest.raises(SystemExit) as e:
        import numa_common
        numa_common.run_cli(lg.main, argv)
    return e.value.code


def test_split_sums_to_monthly(nc):
    split = lg.split_credits()
    assert split == {"kling_motion": 600, "seedance_people_free": 140, "photo_prep": 160, "music": 120,
                     "voice": 10, "reserve": 170}
    assert sum(split.values()) == nc.config_value("budget.monthly_credits") == 1200


def test_price_lookup(nc, capsys):
    assert lg.price("kling_pro_5s")["credits"] == 8.75
    assert lg.main(["price", "music_40s", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["credits"] == 5.82
    with pytest.raises(nc.UserError):
        lg.price("nope")


def test_pacing_formula(nc):
    assert lg.pacing_fraction(date(2026, 12, 15)) == pytest.approx(0.55)
    assert lg.pacing_fraction(date(2026, 12, 1)) == pytest.approx(150 / 1200)   # one reel's cap floor
    assert lg.pacing_fraction(date(2026, 12, 10)) == pytest.approx(0.55 * 10 / 15)
    assert lg.pacing_fraction(date(2026, 12, 31)) == pytest.approx(1.0)
    assert lg.pacing_fraction(date(2026, 12, 23)) == pytest.approx(0.55 + 0.45 * 8 / 16)


def test_day15_overspend_blocks(nc, tmp_path, capsys):
    led = tmp_path / "ledger.json"
    for i in range(11):  # 11 x 60 = 660 = exactly 55% of 1,200
        cat = "reserve" if i == 0 else "kling_motion"
        assert add(led, "--job", "batch", "--category", cat, "--credits", 60, "--date", f"2026-12-{1 + i:02d}") == 0
    capsys.readouterr()
    assert run(["check", "--ledger", str(led), "--date", "2026-12-15"]) == 0  # exactly at the cap is allowed
    # 660 used by day 15: anything more breaks the pacing rule
    code = run(["check", "--ledger", str(led), "--category", "music", "--credits", "5.82", "--date", "2026-12-15"])
    err = capsys.readouterr().err
    assert code == 1 and "pacing" in err and "ERROR: blocked" in err
    # on day 20 the cap is higher, so the same spend is fine
    assert run(["check", "--ledger", str(led), "--category", "music", "--credits", "5.82", "--date", "2026-12-20"]) == 0


def test_category_reel_and_month_caps(nc, tmp_path, capsys):
    led = tmp_path / "l.json"
    add(led, "--job", "seedance_1080p_5s", "--reel", "r1", "--date", "2026-12-20")
    ents = lg.Ledger(led).entries("2026-12")
    r = lg.evaluate(ents, date(2026, 12, 20), "seedance_people_free", 80, "r2")
    assert not r["allowed"] and any("category seedance_people_free" in x for x in r["reasons"])
    r = lg.evaluate(ents, date(2026, 12, 20), "kling_motion", 75, "r1")
    assert not r["allowed"] and any("per-reel cap" in x for x in r["reasons"])
    r = lg.evaluate(ents, date(2026, 12, 20), "kling_motion", 70, "r1")
    assert r["allowed"], r["reasons"]
    r = lg.evaluate(ents, date(2026, 12, 31), "reserve", 1200, None)
    assert any("month 2026-12" in x for x in r["reasons"])


def test_refunds_and_rollover(nc, tmp_path):
    led = tmp_path / "months"  # folder mode: one file per month
    add(led, "--job", "kling_std_5s", "--reel", "r1", "--date", "2026-11-30")
    add(led, "--job", "kling_pro_5s", "--reel", "r1", "--refunded", "--date", "2026-11-30")
    add(led, "--job", "kling_pro_5s", "--reel", "r1", "--outcome", "unwanted", "--date", "2026-11-30")
    assert sorted(p.name for p in led.iterdir()) == ["ledger_2026-11.json"]
    nov = lg.summary(lg.Ledger(led).entries("2026-11"), "2026-11")
    assert nov["used"] == 16.25 and nov["refunded_jobs"] == 1 and nov["unwanted_credits"] == 8.75
    dec = lg.summary(lg.Ledger(led).entries("2026-12"), "2026-12")
    assert dec["used"] == 0 and dec["left"] == 1200


def test_report_reels_covered(nc, tmp_path, capsys):
    led = tmp_path / "l.json"
    add(led, "--job", "music_40s", "--date", "2026-12-02")
    capsys.readouterr()
    assert lg.main(["report", "--ledger", str(led), "--date", "2026-12-02", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["kling_reel_cost"]["per_reel"] == 48.75  # 3 clips x (7.5 draft + 8.75 keeper)
    assert rep["reels_covered"] == int((1200 - 5.82) // 48.75)
    assert rep["categories"]["music"]["left"] == pytest.approx(114.18)
    assert lg.main(["report", "--ledger", str(led), "--date", "2026-12-02", "--balance", "100", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["reels_covered"] == 2


def test_sheet_csv_and_errors(nc, tmp_path, capsys):
    led = tmp_path / "l.json"
    add(led, "--job", "upscale_2k", "--reel", "r9", "--date", "2026-12-03")
    capsys.readouterr()
    lg.main(["sheet", "--ledger", str(led), "--month", "2026-12"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("#,Date,Category") and "photo_prep,upscale_2k" in lines[1]
    assert run(["add", "--ledger", str(led), "--job", "reframe_20s_1080p"]) == 1  # never use Reframe
    assert run(["add", "--ledger", str(led), "--job", "custom", "--credits", "3"]) == 2  # category needed
    assert run(["check", "--ledger", str(led), "--category", "bogus", "--credits", "1"]) == 2
    assert run([]) == 2
