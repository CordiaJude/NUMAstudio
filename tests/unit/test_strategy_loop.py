"""The learning loop end to end and its guard rails (T18 review): tags through metrics.py, judging by real pull age,
missing data, decision hysteresis, per-arm decay, the trial-only pool, format, offer-week, cadence, Story-frame and
off-day learning, and import deltas."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import metrics as mstore  # noqa: E402
import numa_common as nc  # noqa: E402
import strategy as S  # noqa: E402


def cli(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)


def fits_for(store, state=None, today=date(2026, 11, 13)):
    pb = S.load_playbook(None, state or S.empty_state())
    posts = S.collect_posts(store, pb, today)
    S.score_posts(posts, pb)
    return pb, posts, S.fit_models(posts, pb)


def post(day: date, mult=1.0, pids=(), pt="reel", pulls=("7d",), **tags):
    rc = 1000 * mult
    m = {"reach": rc, "views": rc, "shares": 5 * mult * mult, "saves": 5 * mult * mult}
    if pt in ("reel", "trial_reel"):
        m["avg_watch_time_ms"] = 9000 * mult
    return {"tags": {"post_type": pt, "posting_time": f"{day.isoformat()}T16:30:00", "length": 30, "pattern_ids": list(pids), **tags},
            "pulls": {p: {"metrics": dict(m)} for p in pulls}}


# --------------------------------------------------------------------------- tags flow end to end
def test_tags_flow_from_metrics_into_the_learning(tmp_path):
    store = tmp_path / "metrics.json"
    start = date(2026, 9, 21)                                  # clear of the Labor Day holiday week
    for i in range(12):
        d = start + timedelta(days=2 * i)
        good = i % 2 == 0
        hook = "steam-pour" if good else "timer-challenge"
        tags = {"post_type": "reel", "posting_time": f"{d.isoformat()}T16:30:00", "length": 30, "pattern_ids": [hook],
                "strategy_arm": f"type=reel;pillar=education;series=;day=;band=;hook={hook};structure=;offer_week=;goal=reach;mode=explore;plan=2026-09",
                "boosted": False}
        assert cli("metrics.py", "tag", "--store", store, "--reel", f"r{i}", "--tags", json.dumps(tags)).returncode == 0
        for pull, hrs in (("72h", 72), ("7d", 168)):
            mult = 2.0 if good else 0.6
            data = {"reach": 1000 * mult, "views": 1100 * mult, "shares": 6 * mult * mult, "saves": 4 * mult,
                    "avg_watch_time_ms": int(9000 * mult)}
            pulled = (datetime.fromisoformat(f"{d.isoformat()}T16:30:00") + timedelta(hours=hrs)).isoformat()
            r = cli("metrics.py", "ingest", "--store", store, "--reel", f"r{i}", "--pull", pull, "--data", json.dumps(data),
                    "--pulled-at", pulled)
            assert r.returncode == 0, r.stderr
    raw = json.loads(store.read_text())["reels"]["r0"]["tags"]
    assert raw["pattern_ids"] == ["steam-pour"] and raw["strategy_arm"].startswith("type=reel") and raw["boosted"] is False
    r = cli("strategy.py", "score", "--metrics", store, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    st = tmp_path / "strategy.json"
    r = cli("strategy.py", "learn", "--metrics", store, "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    pb, posts, fits = fits_for(json.loads(store.read_text()))
    win = S.decision_stats(fits["arms"][("hook", "steam-pour")]["records"])
    lose = S.decision_stats(fits["arms"][("hook", "timer-challenge")]["records"])
    assert win["tries"] >= 4 and win["wins"] == win["tries"] and lose["wins"] == 0
    assert fits["arms"][("hook", "steam-pour")]["mean"] > 0.6 > fits["arms"][("hook", "timer-challenge")]["mean"]


def test_metrics_store_accepts_strategy_tags_and_story_pulls(tmp_path):
    store = tmp_path / "m.json"
    bad = cli("metrics.py", "tag", "--store", store, "--reel", "a", "--tags", json.dumps({"pattern_ids": ["Not An Id"]}))
    assert bad.returncode == 1 and "pattern_ids" in bad.stderr
    tags = {"post_type": "story", "posting_time": "2026-11-12T08:00:00-06:00", "story_frames": 2}
    assert cli("metrics.py", "tag", "--store", store, "--reel", "s", "--tags", json.dumps(tags)).returncode == 0
    tags = {"post_type": "reel", "posting_time": "2026-11-01T08:00:00-06:00"}
    assert cli("metrics.py", "tag", "--store", store, "--reel", "r", "--tags", json.dumps(tags)).returncode == 0
    data = json.loads(store.read_text())
    due = {d["reel"]: d for d in mstore.due(data, datetime(2026, 11, 13, 13, 30, tzinfo=timezone.utc))}   # story 23.5 h old
    assert due["s"]["pulls"] == ["12h", "22h"] and due["s"]["pull_now"] == "22h"
    assert "12h" not in due["r"]["pulls"] and "22h" not in due["r"]["pulls"] and due["r"]["pull_now"] == "7d"
    assert "s" not in {d["reel"] for d in mstore.due(data, datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc))}   # past 24 h
    assert nc.config_value("instagram.insight_pulls_hours") == [12, 22, 48, 72, 168, 336, 720]


# --------------------------------------------------------------------------- judging and missing data
def test_pull_age_story_windows_and_missing_data():
    store = {"reels": {f"b{i}": post(date(2026, 10, 1) + timedelta(days=i)) for i in range(4)}}
    late = post(date(2026, 11, 1), pulls=("72h",))
    late["pulls"]["72h"]["pulled_at"] = "2026-11-09T16:30:00"           # labelled 72h, really taken at 8 days: final
    store["reels"]["late"] = late
    store["reels"]["s12"] = post(date(2026, 11, 12), pt="story", pulls=("12h",))
    store["reels"]["s22"] = post(date(2026, 11, 12), pt="story", pulls=("12h", "22h"))
    store["reels"]["zero"] = post(date(2026, 10, 20), mult=0.0)
    store["reels"]["thin"] = {"tags": {"post_type": "reel", "posting_time": "2026-10-21T16:30:00", "length": 30},
                              "pulls": {"7d": {"metrics": {"reach": 900}}}}
    store["reels"]["boost"] = post(date(2026, 10, 5, ), mult=9.0, boosted=True)
    pb, posts, fits = fits_for(store)
    by = {p["id"]: p for p in posts}
    assert by["late"]["status"] == "final" and by["late"]["pull_hours"]["72h"] == pytest.approx(192)
    assert by["s12"]["status"] == "provisional" and by["s12"]["judge_weight"] == 0.7    # R7: Story early read at 12 h
    assert by["s22"]["status"] == "final" and by["s22"]["pull"] == "22h"
    assert by["zero"]["score"] is None and by["thin"]["score"] is None                   # missing data, never a loss
    assert all(by["boost"] not in S.baseline(p, posts, pb["policies"], pooled=False) for p in posts if p["posted"])


# --------------------------------------------------------------------------- decisions: hysteresis, re-entry, trial pool
def _series(results, hook="timer-challenge", start=date(2026, 2, 2)):
    st, d = {"reels": {}}, start
    for i in range(6):
        st["reels"][f"f{i}"] = post(d)
        d += timedelta(days=1)
    for i, mult in enumerate(results):
        st["reels"][f"h{i:02d}"] = post(d, mult, [hook])
        d += timedelta(days=1)
        st["reels"][f"g{i:02d}"] = post(d)
        d += timedelta(days=1)
    return st, d


def _learn(store, state, today):
    pb, posts, fits = fits_for(store, state, today)
    return S.learn(pb, fits, today)


def test_reentered_pattern_starts_clean_and_status_changes_need_fresh_evidence():
    store, end = _series([0.5] * 8)
    state, _ = _learn(store, S.empty_state(), end + timedelta(days=10))
    assert state["status_overrides"]["timer-challenge"]["status"] == "retired"
    state, ch = _learn(store, state, end + timedelta(days=105))
    assert [c["action"] for c in ch if c["target"] == "timer-challenge"] == ["reenter"]
    for k in range(3):                                        # no new tries: it stays in testing
        state, ch = _learn(store, state, end + timedelta(days=106 + k))
        assert state["status_overrides"]["timer-challenge"]["status"] == "testing"
        assert not [c for c in ch if c["target"] == "timer-challenge"]


def test_no_flapping_between_promote_and_demote():
    store, end = _series([2.0] * 6)
    promoted_on = end + timedelta(days=10)
    state, _ = _learn(store, S.empty_state(), promoted_on)
    assert state["status_overrides"]["timer-challenge"]["status"] == "proven"           # fast track: 6 of the first 6
    more, end2 = _series([2.0] * 6 + [1.0] * 6 + [0.85] * 8)      # the losses come after the promotion
    assert end2 > promoted_on + timedelta(days=16)
    state, ch = _learn(more, state, end2 + timedelta(days=10))
    assert state["status_overrides"]["timer-challenge"]["status"] == "testing"          # last 8 lost: demoted
    for k in range(4):                                        # same data, later days: no re-promotion, no re-demotion
        state, ch = _learn(more, state, end2 + timedelta(days=11 + k))
        assert not [c for c in ch if c["target"] == "timer-challenge"]
    st = S.decision_stats(state and _fits_arm(more, state, end2), since=state["status_overrides"]["timer-challenge"]["counts_from"])
    assert st["tries"] == 0                                    # a new promotion needs tries after the demotion


def _fits_arm(store, state, end):
    _, _, fits = fits_for(store, state, end + timedelta(days=10))
    return fits["arms"][("hook", "timer-challenge")]["records"]


def test_fast_track_only_for_the_first_tries():
    lp = S.load_playbook()["policies"]["learning"]
    recs = [{"post": f"p{i}", "date": f"2026-03-{i + 1:02d}", "S": 0.6, "win": True, "final": True, "january": False} for i in range(6)]
    recs += [{"post": f"q{i}", "date": f"2026-04-{i + 1:02d}", "S": -0.1, "win": False, "final": True, "january": False} for i in range(6)]
    pat = dict(S.load_playbook()["patterns"]["timer-challenge"], status="testing")
    new, why, st = S.decide(pat, {"records": recs}, lp)
    assert new is None and st["tries"] == 12                   # 6 of 12 with a median under 1.25x: keep testing


def test_trial_reels_decide_in_their_own_pool_and_inform_the_main_arm():
    store = {"reels": {f"b{i}": post(date(2026, 10, 1) + timedelta(days=i), pt="trial_reel") for i in range(4)}}
    for i in range(6):
        store["reels"][f"t{i}"] = post(date(2026, 10, 14) + timedelta(days=i), 2.0, ["steam-pour"], pt="trial_reel")
    pb, posts, fits = fits_for(store)
    trial = fits["arms"][("hook", "trial:steam-pour")]
    main = fits["arms"][("hook", "steam-pour")]
    assert len(trial["records"]) >= 5 and main["records"] == []
    prior = S.arm(fits, pb, "hook", "steam-pour@static")      # an untouched arm for comparison
    assert main["mean"] > prior["mean"]


def test_each_arm_decays_only_on_its_own_updates():
    store = {"reels": {f"b{i}": post(date(2026, 6, 1) + timedelta(days=i)) for i in range(4)}}
    store["reels"]["early"] = post(date(2026, 6, 10), 2.0, ["steam-pour"])
    for i in range(30):                                      # many later posts with another hook
        store["reels"][f"x{i}"] = post(date(2026, 6, 11) + timedelta(days=i), 1.0, ["timer-challenge"])
    pb, posts, fits = fits_for(store)
    a = fits["arms"][("hook", "steam-pour")]
    a0, b0 = S.arm_prior(pb, "hook", "steam-pour")
    assert a["alpha"] == pytest.approx(1 + (a0 - 1) * 0.97 + 1.0)      # one update: decayed once, not 30 times


# --------------------------------------------------------------------------- format, offers, cadence, frames, off day
def test_format_tests_and_evidence_widens_the_image_share():
    pb, posts, fits = fits_for({"reels": {}})
    plan, v = S.month_plan(pb, fits, "2027-02", None, [], None, posts, [])
    assert v == []
    tests = [r for r in plan["rows"] if r["strategy"].get("tests") == "format"]
    assert tests and all(r["kind"] == "image" for r in tests) and all(r["strategy"]["mode"] == "explore" for r in tests)
    planner = S.Planner(pb, fits, 2027, 3, 1, [], {}, posts, [])
    assert planner.format_bounds(5)["image"] == 1
    store = {"reels": {}}
    for i in range(14):                                       # images beat the feed median again and again
        d = date(2026, 9, 21) + timedelta(days=i)              # clear of the Labor Day week
        store["reels"][f"r{i}"] = post(d)
        store["reels"][f"i{i}"] = post(d, 2.0, pt="image")
    pb2, posts2, fits2 = fits_for(store)
    assert fits2["arms"][("format", "image")]["mean"] > fits2["arms"][("format", "reel")]["mean"]
    b = S.Planner(pb2, fits2, 2026, 12, 1, [], {}, posts2, []).format_bounds(5)
    assert b["widened"] and b["image"] == 2 and b["nonreel"] == 3


def test_offer_week_test_and_untried_weeks_are_drawn():
    pb, posts, fits = fits_for({"reels": {}})
    plan, v = S.month_plan(pb, fits, "2027-04", None, [], None, posts, [])     # five Fridays
    offers = [r for r in plan["rows"] if r.get("sales")]
    assert v == [] and any(r["strategy"].get("offer_explore") for r in offers)
    assert any("Offer-week test" in w for r in offers for w in r["strategy"]["why"])


def test_blocked_rotations_for_cadence_story_frames_and_off_day():
    pb, posts, fits = fits_for({"reels": {}})
    planner = S.Planner(pb, fits, 2027, 1, 1, [], {}, posts, [])
    blocks = [date(2027, 1, 4) + timedelta(weeks=4 * k) for k in range(3)]
    cad = [planner.rotation("cadence", w)[0] for w in blocks]
    frames = [planner.rotation("story_frames", w)[0] for w in blocks]
    off = [planner.rotation("off_day", w)[0] for w in blocks]
    assert sorted(set(cad)) == ["4", "5"] and set(frames) == {"1", "2", "3"} and set(off) == {"Sat", "Sun"}
    for month in ("2027-01", "2027-02", "2027-03"):
        plan, v = S.month_plan(pb, fits, month, None, [], None, posts, [])
        assert v == []
        for wk in {r["strategy"]["week"] for r in plan["rows"]}:
            rows = [r for r in plan["rows"] if r["strategy"]["week"] == wk]
            if len(rows) == 7:
                feed = sum(r["kind"] in ("reel", "carousel", "image") for r in rows)
                assert feed == rows[0]["strategy"]["feed_per_week"] in (4, 5)
        stories = [r for r in plan["rows"] if r["kind"] == "stories"]
        assert all(r["story_frames"] in (1, 2, 3) for r in stories)


def test_cadence_winner_after_enough_weeks():
    pb, posts, _ = fits_for({"reels": {}})
    weeks = []
    for k in range(20):                                       # 4-post weeks reach more than 5-post weeks
        feed = 4 if k % 2 else 5
        weeks.append({"week": (date(2026, 1, 5) + timedelta(weeks=k)).isoformat(), "feed": feed, "judged": feed,
                      "reach": 6000.0 if feed == 4 else 2500.0, "follows": 0.0, "final": True, "excluded": False})
    fits = {"arms": {}, "weeks": weeks, "lambda": 1.0}
    level, why = S.Planner(pb, fits, 2026, 7, 1, [], {}, posts, []).rotation("cadence", date(2026, 7, 6))
    assert "4 beat 5" in why


# --------------------------------------------------------------------------- import keeps bundled fixes
def test_import_stores_deltas_so_bundled_fixes_still_apply(tmp_path):
    st = tmp_path / "strategy.json"
    fixture = Path(__file__).resolve().parent / "fixtures" / "strategy" / "R1 Hooks.md"
    assert cli("strategy.py", "import-research", fixture, "--state", st, "--today", "2026-11-13").returncode == 0
    state = json.loads(st.read_text())
    assert "temp-split" in state["pattern_deltas"] and all(p["id"] != "temp-split" for p in state["patterns"])
    pbdir = tmp_path / "pb"
    pbdir.mkdir()
    for f in (REPO / "skills" / "numa-scriptwriter" / "playbook").glob("*.json"):
        (pbdir / f.name).write_text(f.read_text())
    doc = json.loads((pbdir / "patterns.json").read_text())
    for p in doc["patterns"]:
        if p["id"] == "temp-split":
            p["template"] = "A later plugin fix to this template."
    (pbdir / "patterns.json").write_text(json.dumps(doc))
    merged = S.load_playbook(str(pbdir), state)["patterns"]["temp-split"]
    assert merged["template"] == "A later plugin fix to this template."
    assert "https://example.org/hooks-2026" in merged["evidence"]["sources"]


def test_playbook_names_only_the_co_founders():
    pb = S.load_playbook(None, None)
    assert S.playbook_name_problems(pb) == []
    allowed = S.founder_names()
    assert {"Scott", "Katie"} <= allowed
    assert S.name_hits("Meet Katie, our co-founder.", "x", allowed) == []
    for text in ("Breathe with Robin for 30 seconds.", "Meet Robin, one of our guides.", "Robin's breathwork for guys"):
        assert S.name_hits(text, "x", allowed), text
    assert S.name_hits("Breathe with [guide name] for 30 seconds.", "x", allowed) == []
    bad = json.loads(json.dumps(pb["patterns"]["breathe-along"]))
    bad["examples"] = ["Breathe with Robin for 30 seconds."]
    pb["patterns"]["breathe-along"] = bad
    errs, _ = S.playbook_problems(pb)
    assert any("Robin" in e for e in errs)


def test_half_day_closure_posts_early_and_invites_nobody_after():
    half = S.partial_closures(None)
    assert half[date(2026, 12, 31)] == {"name": "New Year's Eve", "open_until": "12:00"}
    pb, posts, fits = fits_for({"reels": {}})
    plan, v = S.month_plan(pb, fits, "2026-12", None, [], None, posts, [])
    assert v == [] and plan["partial_closures"] == [{"date": "2026-12-31", "name": "New Year's Eve", "open_until": "12:00"}]
    nye = [r for r in plan["rows"] if r["date"] == "2026-12-31"]
    assert nye and all(not (r.get("sales") or r.get("invites")) for r in nye)
    assert all(r["post_time"] < "12:00" for r in nye if r.get("post_time"))
    assert date(2026, 12, 31) not in S.closure_dates(None)          # a half day is not a full closure
    lines = S.guardrails(date(2026, 12, 28), date(2027, 1, 3), plan)
    assert any("Half day" in x and "12:00" in x for x in lines)
