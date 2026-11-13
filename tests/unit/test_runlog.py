"""runlog.py: run log, cron evaluation across daylight-saving changes, the watchdog and setup verification (R340, R341, R343)."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import numa_common
import runlog

CHI = ZoneInfo("America/Chicago")
UTC = timezone.utc


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(runlog.main, argv)
    return e.value.code


def out_json(capsys, argv):
    capsys.readouterr()
    assert run(argv) == 0
    return json.loads(capsys.readouterr().out)


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def rec(task, start, minutes=12, outcome="ok", note="", rid=None):
    return {"id": rid or f"{task}-{start:%Y%m%dT%H%M}", "task": task, "started_at": runlog.utc_iso(start),
            "finished_at": runlog.utc_iso(start + timedelta(minutes=minutes)) if outcome else None,
            "outcome": outcome, "note": note}


def write_log(state, runs, created="2026-10-01T00:00:00Z", reported=()):
    state.mkdir(parents=True, exist_ok=True)
    (state / "runlog.json").write_text(json.dumps({"schema_version": 1, "created_at": created, "runs": runs,
                                                   "reported": list(reported)}))


@pytest.fixture
def state(tmp_path, nc, monkeypatch):
    monkeypatch.delenv("NUMA_STATE", raising=False)
    return tmp_path / "_Plan"


# ---------------------------------------------------------------------------
# cron evaluator
# ---------------------------------------------------------------------------
def test_cron_fields():
    c = runlog.Cron("*/15 9-17/4 1,15 jan-mar mon-fri")
    assert c.minutes == {0, 15, 30, 45} and c.hours == {9, 13, 17}
    assert c.doms == {1, 15} and c.months == {1, 2, 3} and c.dows == {1, 2, 3, 4, 5}
    assert runlog.Cron("0 0 * * 7").dows == {0}  # 7 is Sunday too
    assert runlog.Cron("0 10 12 2,5,8,11 *").months == {2, 5, 8, 11}


@pytest.mark.parametrize("bad", ["0 5 * *", "60 5 * * *", "0 24 * * *", "0 5 0 * *", "0 5 * 13 *",
                                 "0 5 * * 8", "*/0 5 * * *", "x 5 * * *", "0 9-5 * * *"])
def test_cron_rejects_bad_lines(bad):
    with pytest.raises(numa_common.UserError):
        runlog.Cron(bad)


def test_cron_day_of_month_or_weekday():
    c = runlog.Cron("0 12 13 * 5")  # the 13th OR any Friday (cron's rule when both are restricted)
    days = {f.day for f in c.fires(utc(2026, 11, 1, 0), utc(2026, 12, 1, 0), CHI)}
    assert days == {6, 13, 20, 27}
    only_dom = runlog.Cron("0 12 13 * *")
    assert [f.day for f in only_dom.fires(utc(2026, 11, 1, 0), utc(2026, 12, 1, 0), CHI)] == [13]
    star_step = runlog.Cron("0 12 */10 * 5")  # a field starting with '*' is unrestricted: every Friday
    assert {f.day for f in star_step.fires(utc(2026, 11, 1, 0), utc(2026, 12, 1, 0), CHI)} == {6, 13, 20, 27}


def test_cron_dst_fall_back_week():
    """Central time ends daylight saving on Sun 2026-11-01: 5 am is 10:00 UTC before, 11:00 UTC after."""
    fires = runlog.Cron("0 5 * * *").fires(utc(2026, 10, 30, 0), utc(2026, 11, 4, 0), CHI)
    got = [(f.date().isoformat(), f.astimezone(UTC).hour, f.hour) for f in fires]
    assert got == [("2026-10-30", 10, 5), ("2026-10-31", 10, 5), ("2026-11-01", 11, 5),
                   ("2026-11-02", 11, 5), ("2026-11-03", 11, 5)]
    once = runlog.Cron("30 1 * * *").fires(utc(2026, 11, 1, 0), utc(2026, 11, 2, 0), CHI)
    assert len(once) == 1 and once[0].astimezone(UTC) == utc(2026, 11, 1, 6, 30)  # 1:30 CDT, the first one


def test_cron_dst_spring_forward():
    """2027-03-14: 2:30 am does not exist in Central time; cron runs it right after the change (3:30 CDT)."""
    fires = runlog.Cron("30 2 * * *").fires(utc(2027, 3, 13, 0), utc(2027, 3, 16, 0), CHI)
    assert [f.astimezone(UTC) for f in fires] == [utc(2027, 3, 13, 8, 30), utc(2027, 3, 14, 8, 30),
                                                  utc(2027, 3, 15, 7, 30)]
    six = runlog.Cron("0 18 * * 0").fires(utc(2027, 3, 2, 0), utc(2027, 3, 22, 0), CHI)
    assert [f.astimezone(UTC).hour for f in six] == [0, 23, 23]  # Sun 6 pm: CST -6 then CDT -5


# ---------------------------------------------------------------------------
# a synthetic week across the fall-back change
# ---------------------------------------------------------------------------
LOCAL_TIMES = {"night_check": (20, 0), "build_today": (5, 0), "dashboard_refresh": (22, 0)}


def week_runs(skip=()):
    """Every scheduled run from Wed Oct 28 to Wed Nov 4 2026 (Central), started 1-3 minutes late."""
    runs = []
    for i in range(9):
        day = datetime(2026, 10, 27, tzinfo=CHI).date() + timedelta(days=i)
        for task, (h, m) in LOCAL_TIMES.items():
            start = datetime(day.year, day.month, day.day, h, m + 2, tzinfo=CHI).astimezone(UTC)
            if (task, day.isoformat()) not in skip:
                runs.append(rec(task, start))
        if day.isoweekday() == 5:
            runs.append(rec("trend_check", datetime(day.year, day.month, day.day, 19, 1, tzinfo=CHI).astimezone(UTC)))
        if day.isoweekday() == 7:
            runs.append(rec("digest", datetime(day.year, day.month, day.day, 18, 3, tzinfo=CHI).astimezone(UTC)))
    return runs


def test_synthetic_dst_week_is_healthy(state, capsys):
    write_log(state, week_runs())
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-04T12:00:00-06:00", "--json"])
    assert res["healthy"], res["problems"]
    assert res["tasks"]["build_today"]["expected"] == 7 and res["tasks"]["build_today"]["ok"] == 7
    assert res["tasks"]["digest"]["expected"] == 1 and res["tasks"]["trend_check"]["expected"] == 1
    assert res["tasks"]["plan_month"]["expected"] == 0  # the 24th is outside the window


def test_naive_utc_offset_mistake_is_caught(state, capsys):
    """A run logged at 5 am Central with last week's offset (-05:00) after the change lands an hour early, so
    it belongs to the previous day's slot and the day itself is missed."""
    runs = [r for r in week_runs() if not (r["task"] == "build_today" and r["started_at"].startswith("2026-11-02"))]
    runs.append(rec("build_today", datetime(2026, 11, 2, 5, 2, tzinfo=timezone(timedelta(hours=-5))).astimezone(UTC),
                    rid="wrong-offset"))
    write_log(state, runs)
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-04T12:00:00-06:00", "--json"])
    missed = [p for p in res["problems"] if p["kind"] == "missed"]
    assert [(p["task"], p["date"]) for p in missed] == [("build_today", "2026-11-02")]


def test_missed_failed_stuck_and_partial(state, capsys):
    runs = week_runs(skip={("build_today", "2026-11-02"), ("night_check", "2026-11-03")})
    for r in runs:
        if r["task"] == "dashboard_refresh" and r["started_at"].startswith("2026-11-01"):  # Oct 31, 10 pm CDT
            r.update(outcome="failed", note="Composio unreachable")
        if r["task"] == "build_today" and r["started_at"].startswith("2026-11-03"):
            r.update(outcome="partial", note="posted without Trial Reel")
    late = datetime(2026, 11, 4, 5, 1, tzinfo=CHI).astimezone(UTC)
    runs = [r for r in runs if not (r["task"] == "build_today" and r["started_at"].startswith("2026-11-04"))]
    runs.append(rec("build_today", late, outcome=None, rid="hung"))
    write_log(state, runs)
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-04T12:00:00-06:00", "--json"])
    kinds = {(p["kind"], p["task"], p["date"]): p for p in res["problems"]}
    assert set(kinds) == {("missed", "build_today", "2026-11-02"), ("missed", "night_check", "2026-11-03"),
                          ("failed", "dashboard_refresh", "2026-10-31"), ("stuck", "build_today", "2026-11-04")}
    assert kinds[("failed", "dashboard_refresh", "2026-10-31")]["note"] == "Composio unreachable"
    assert kinds[("missed", "build_today", "2026-11-02")]["action"] == "reschedule"
    assert kinds[("stuck", "build_today", "2026-11-04")]["action"] == "late_build"  # noon: a build still posts today
    assert kinds[("stuck", "build_today", "2026-11-04")]["minutes"] == 419
    assert kinds[("failed", "dashboard_refresh", "2026-10-31")]["action"] == "skip"
    assert [n["task"] for n in res["notes"]] == ["build_today"]
    assert res["tasks"]["build_today"]["partial"] == 1 and not res["healthy"]


def test_a_rerun_in_the_same_slot_clears_a_failure(state, capsys):
    first = utc(2026, 11, 3, 11, 1)
    write_log(state, [rec("build_today", first, outcome="failed", note="render crash"),
                      rec("build_today", first + timedelta(hours=1), rid="retry")], created="2026-11-03T10:00:00Z")
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-03T08:00:00-06:00", "--json"])
    assert res["healthy"] and res["tasks"]["build_today"] == {**res["tasks"]["build_today"], "ok": 1, "failed": 0}


def test_late_build_window_and_post_by(state, capsys):
    write_log(state, [], created="2026-11-12T00:00:00Z")
    args = ["check", "--state", str(state), "--json"]

    def action(now, *extra):
        res = out_json(capsys, args + ["--now", now, *extra])
        return next(p["action"] for p in res["problems"] if p["task"] == "build_today" and p["date"] == now[:10])

    assert action("2026-11-13T09:00:00-06:00") == "late_build"
    assert action("2026-11-13T16:59:00-06:00") == "late_build"  # 60 min build before 18:00
    assert action("2026-11-13T17:30:00-06:00") == "reschedule"
    assert action("2026-11-13T17:30:00-06:00", "--post-by", "19:00") == "late_build"
    assert action("2026-11-13T20:00:00-06:00") == "reschedule"  # the 8 pm night check: too late today
    assert run(args + ["--now", "2026-11-13T09:00:00", "--post-by", "25:00"]) == 1


def test_rerun_window_for_other_tasks(state, capsys):
    write_log(state, [], created="2026-11-20T00:00:00Z")
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-25T08:00:00-06:00", "--json"])
    plan = next(p for p in res["problems"] if p["task"] == "plan_month")
    assert plan["slot"] == "2026-11-24T21:00:00-06:00" and plan["action"] == "rerun"
    night = [p for p in res["problems"] if p["task"] == "night_check"]
    assert {p["date"]: p["action"] for p in night}["2026-11-24"] == "skip"  # past tomorrow's 5 am build


def test_new_install_is_not_missed(state, capsys):
    write_log(state, [rec("build_today", utc(2026, 11, 13, 11, 0))], created=None)
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T07:00:00-06:00", "--json"])
    assert res["healthy"] and res["tasks"]["build_today"]["expected"] == 1
    assert json.loads((state / "runlog.json").read_text())["created_at"] is None  # check alone writes nothing
    assert run(["start", "night_check", "--state", str(state), "--now", "2026-11-13T20:00:00-06:00"]) == 0
    assert json.loads((state / "runlog.json").read_text())["created_at"] == "2026-11-13T11:00:00Z"


def test_grace_period(state, capsys):
    write_log(state, [], created="2026-11-13T00:00:00Z")
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T05:30:00-06:00", "--json"])
    assert not [p for p in res["problems"] if p["task"] == "build_today"]  # 30 min late is not missed yet
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T06:01:00-06:00", "--json"])
    assert [p["kind"] for p in res["problems"] if p["task"] == "build_today"] == ["missed"]


def test_mark_reported_sends_each_problem_once(state, capsys):
    write_log(state, [], created="2026-11-12T00:00:00Z")
    args = ["check", "--state", str(state), "--now", "2026-11-13T20:00:00-06:00", "--json", "--mark-reported"]
    first = out_json(capsys, args)
    assert first["problems"] and all(p["new"] for p in first["problems"])
    again = out_json(capsys, args)
    assert again["problems"] and not any(p["new"] for p in again["problems"])
    later = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T23:30:00-06:00", "--json"])
    assert [p["task"] for p in later["problems"] if p["new"]] == ["night_check", "dashboard_refresh"]


def test_unscheduled_runs_report_failures(state, capsys):
    write_log(state, [rec("make_reel", utc(2026, 11, 13, 15, 0), outcome="failed", note="Drive down")],
              created="2026-11-13T15:00:00Z")
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T10:00:00-06:00", "--json"])
    p = next(p for p in res["problems"] if p["task"] == "make_reel")
    assert p["kind"] == "failed" and p["slot"] is None and p["note"] == "Drive down"


# ---------------------------------------------------------------------------
# start / finish / merge / summary / verification
# ---------------------------------------------------------------------------
def test_start_and_finish(state, capsys):
    capsys.readouterr()
    assert run(["start", "build_today", "--state", str(state), "--now", "2026-11-13T05:00:20-06:00"]) == 0
    rid = capsys.readouterr().out.strip()
    assert rid.startswith("build_today-20261113T110020Z-")
    assert run(["finish", rid, "--outcome", "failed", "--note", "render   crash", "--state", str(state),
                "--now", "2026-11-13T05:30:00-06:00"]) == 0
    log = json.loads((state / "runlog.json").read_text())
    assert log["runs"][0] == {"id": rid, "task": "build_today", "started_at": "2026-11-13T11:00:20Z",
                              "finished_at": "2026-11-13T11:30:00Z", "outcome": "failed", "note": "render crash"}
    run(["start", "digest", "--state", str(state), "--now", "2026-11-15T18:00:00"])
    capsys.readouterr()
    assert run(["finish", "--task", "digest", "--outcome", "ok", "--state", str(state), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["task"] == "digest"
    assert run(["finish", "nope-1", "--outcome", "ok", "--state", str(state)]) == 1
    assert "no run nope-1" in capsys.readouterr().err
    assert run(["finish", "--task", "digest", "--outcome", "ok", "--state", str(state)]) == 1  # none open
    assert run(["finish", "--outcome", "ok", "--state", str(state)]) == 2
    assert run(["finish", rid, "--outcome", "great", "--state", str(state)]) == 2
    assert run(["start", "Build Today", "--state", str(state)]) == 2


def test_state_from_environment(tmp_path, nc, monkeypatch, capsys):
    monkeypatch.setenv("NUMA_STATE", str(tmp_path / "s"))
    assert run(["start", "digest"]) == 0
    assert (tmp_path / "s" / "runlog.json").is_file()


def test_bad_log_and_bad_times(state, capsys):
    state.mkdir(parents=True)
    (state / "runlog.json").write_text("[1, 2]")
    assert run(["check", "--state", str(state)]) == 1
    assert "not a run log" in capsys.readouterr().err
    (state / "runlog.json").unlink()
    assert run(["start", "digest", "--state", str(state), "--now", "yesterday"]) == 1
    assert "ISO 8601" in capsys.readouterr().err


def test_merge_keeps_both_machines_runs(state, tmp_path, capsys):
    a = rec("build_today", utc(2026, 11, 13, 11, 0), outcome=None, rid="a")
    write_log(state, [a], created="2026-11-13T11:00:00Z")
    other = tmp_path / "drive.json"
    other.write_text(json.dumps({"created_at": "2026-11-10T00:00:00Z", "reported": ["missed:x:y"],
                                 "runs": [rec("build_today", utc(2026, 11, 13, 11, 0), rid="a"),
                                          rec("night_check", utc(2026, 11, 13, 2, 0), rid="b")]}))
    out = out_json(capsys, ["merge", str(other), "--state", str(state), "--json"])
    assert out["added"] == 1 and out["runs"] == 2
    log = json.loads((state / "runlog.json").read_text())
    assert {r["id"]: r["outcome"] for r in log["runs"]} == {"a": "ok", "b": "ok"}  # the finished copy wins
    assert log["created_at"] == "2026-11-10T00:00:00Z" and log["reported"] == ["missed:x:y"]
    assert run(["merge", str(tmp_path / "missing.json"), "--state", str(state)]) == 1


def test_concurrent_starts_lose_nothing(state, scripts_dir):
    procs = [subprocess.Popen([sys.executable, str(scripts_dir / "runlog.py"), "start", f"task_{i}", "--state",
                               str(state)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for i in range(8)]
    ids = [p.communicate(timeout=60)[0].strip() for p in procs]
    assert all(p.returncode == 0 for p in procs)
    log = json.loads((state / "runlog.json").read_text())
    assert sorted(r["id"] for r in log["runs"]) == sorted(ids) and len(set(ids)) == 8
    assert not list(state.glob("*.tmp"))


def test_summary_week(state, capsys):
    runs = week_runs(skip={("build_today", "2026-11-02")})
    write_log(state, runs)
    capsys.readouterr()
    assert run(["summary", "--week", "--state", str(state), "--now", "2026-11-04T12:00:00-06:00"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Run health, last 7 days: 22 of 23 scheduled runs finished; not ok: "
                           "Build today's reel and outputs missed Mon Nov 2 05:00.")
    assert "- Build today's reel and outputs: 6 of 7 ok, 1 missed" in text
    res = out_json(capsys, ["summary", "--week", "--state", str(state), "--now", "2026-11-04T12:00:00-06:00",
                            "--json"])
    assert res["line"].startswith("Run health") and not res["healthy"]
    assert run(["summary", "--state", str(state)]) == 2  # --week is the only period


def test_setup_verification_since(state, capsys):
    since = "2026-11-13T09:00:00-06:00"
    runs = [rec(t, utc(2026, 11, 13, 16, i)) for i, t in enumerate(
        ["plan_month", "night_check", "build_today", "dashboard_refresh", "trend_check"])]
    runs.append(rec("digest", utc(2026, 11, 13, 16, 30), outcome="failed", note="Docs not connected"))
    runs.append(rec("digest", utc(2026, 11, 12, 16, 30), rid="old-ok"))  # before --since: does not count
    write_log(state, runs)
    res = out_json(capsys, ["check", "--since", since, "--state", str(state), "--now", "2026-11-13T12:00:00-06:00",
                            "--json"])
    assert not res["healthy"]
    assert {k: v["status"] for k, v in res["verify"].items()} == {
        "plan_month": "ok", "night_check": "ok", "build_today": "ok", "dashboard_refresh": "ok",
        "trend_check": "ok", "digest": "failed"}
    res = out_json(capsys, ["check", "--since", since, "--tasks", "build_today,chrome_queue", "--state", str(state),
                            "--now", "2026-11-13T12:00:00-06:00", "--json"])
    assert res["verify"]["chrome_queue"]["status"] == "not run"
    assert run(["check", "--tasks", "digest", "--state", str(state)]) == 2


def test_extra_tasks_and_settings_from_config(state, tmp_path, monkeypatch, capsys, repo_root):
    cfg = json.loads((repo_root / "config" / "studio.json").read_text())
    cfg = copy.deepcopy(cfg)
    cfg["schedule"]["extra_tasks"] = [
        {"id": "quarterly_research", "name": "Quarterly research re-check", "cron": "0 10 12 2,5,8,11 *",
         "where": "cloud"},
        {"id": "chrome_queue", "name": "Chrome queue", "cron": "17 * * * *", "where": "desktop"}]
    cfg["schedule"]["runlog"] = {"_readme": "x", "post_by": "17:00", "stuck_after_minutes": {"build_today": 30}}
    path = tmp_path / "studio.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setenv("NUMA_CONFIG", str(path))
    numa_common.clear_caches()
    write_log(state, [rec("build_today", utc(2026, 11, 13, 11, 0), outcome=None, rid="hung")],
              created="2026-11-10T00:00:00Z")
    res = out_json(capsys, ["check", "--state", str(state), "--now", "2026-11-13T15:55:00-06:00", "--json"])
    assert "chrome_queue" not in res["tasks"]  # desktop-only: asleep is not missed
    assert res["tasks"]["quarterly_research"]["expected"] == 1
    hung = next(p for p in res["problems"] if p.get("run_id") == "hung")
    assert hung["kind"] == "stuck" and hung["action"] == "late_build"  # 15:55 + 60 min <= post_by 17:00; open 10 h > 30 min
    res = out_json(capsys, ["check", "--since", "2026-11-13T00:00", "--state", str(state), "--json",
                            "--now", "2026-11-13T16:10:00-06:00"])
    assert "chrome_queue" in res["verify"] and "quarterly_research" in res["verify"]
