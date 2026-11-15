"""Adaptive strategy engine and playbook (R344-R350, DECISIONS D23).

The synthetic history below is generated, not real data: a small simulated Numa
account whose carousels (especially on Tuesdays) and one hook truly outperform.
The playbook has no "contrast-visual" id since the R1 catalogue replaced the
placeholder seeds; the winning hook here is `steam-pour` (R1's sensory heat/steam
visual, #2 of R1's "10 to test first"). The engine plans each week, the simulated
posts get metrics, and the next plan learns from them.
"""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
PLAYBOOK = REPO / "skills" / "numa-scriptwriter" / "playbook"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "strategy"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claims_scan  # noqa: E402
import numa_common as nc  # noqa: E402
import shoot_card  # noqa: E402
import strategy as S  # noqa: E402

STRATEGY = SCRIPTS / "strategy.py"
WIN_HOOK = "steam-pour"


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(STRATEGY), *map(str, args)], capture_output=True, text=True, cwd=cwd)


def fits_for(store, state=None, today=date(2026, 11, 13)):
    pb = S.load_playbook(None, state or S.empty_state())
    posts = S.collect_posts(store, pb, today)
    S.score_posts(posts, pb)
    return pb, posts, S.fit_models(posts, pb)


def empty_store():
    return {"schema_version": 1, "reels": {}, "account": {"daily": {}, "totals": {}}}


# --------------------------------------------------------------------------- synthetic world
def truth(row, rng):
    pt = row["post_type"]
    views = 800 * math.exp(rng.normal(0, 0.35))
    send = 4.0 * math.exp(rng.normal(0, 0.4))
    save = 3.0 * math.exp(rng.normal(0, 0.4))
    skip = 0.65 + rng.normal(0, 0.04)
    awt = 12.0 * math.exp(rng.normal(0, 0.15))
    if pt == "carousel":
        save *= 1.6
        views *= 1.15
        if row["weekday"] == "Tue":
            views *= 1.3
            save *= 1.6
            send *= 1.3
    if WIN_HOOK in row.get("pattern_ids", []) and pt in ("reel", "trial_reel"):
        views *= 1.4
        send *= 1.8
        skip -= 0.12
        awt *= 1.2
    reach = views * 0.8
    m = {"views": round(views), "reach": round(reach), "shares": round(send * reach / 1000, 2),
         "saves": round(save * reach / 1000, 2), "likes": round(reach * 0.04)}
    if pt in ("reel", "trial_reel"):
        m["skip_rate"] = round(skip * 100, 1)
        m["avg_watch_time_ms"] = round(awt * 1000)
    return m


def simulate(weeks=16, seed=3, start=date(2026, 3, 2)):
    """Plan week by week, post, collect metrics, learn. Returns the curve and the final store/state."""
    rng = np.random.default_rng(seed)
    store = empty_store()
    state = S.empty_state()
    truths = {}
    curve = []
    for k in range(weeks):
        mon = start + timedelta(weeks=k)
        today = mon - timedelta(days=1)
        end = datetime.combine(today, datetime.max.time())
        for pid, (posted, m7) in truths.items():
            age = (end - posted).total_seconds() / 3600
            pulls = {}
            if age >= 72:
                pulls["72h"] = {"metrics": {key: (v * 0.65 if key in ("views", "reach", "shares", "saves", "likes") else v)
                                            for key, v in m7.items()}}
            if age >= 168:
                pulls["7d"] = {"metrics": m7}
            store["reels"][pid]["pulls"] = pulls
        pb, posts, fits = fits_for(store, state, today)
        state, _ = S.learn(pb, fits, today)
        pb, posts, fits = fits_for(store, state, today)
        rows = []
        for month in sorted({(mon + timedelta(days=i)).strftime("%Y-%m") for i in range(7)}):
            plan, violations = S.month_plan(pb, fits, month, None, [], None, posts, S.recent_diagnoses(posts, pb))
            assert not violations, violations
            rows += [r for r in plan["rows"] if mon.isoformat() <= r["date"] <= (mon + timedelta(days=6)).isoformat()]
        feed = [r for r in rows if r["post_type"] in ("reel", "carousel", "image")]
        pattern_rows = [r for r in rows if r.get("pattern_ids")]
        video = [r for r in pattern_rows if r["post_type"] in ("reel", "trial_reel")]
        curve.append({
            "week": k + 1, "data_led": fits["lambda"],
            "carousel_share": sum(r["post_type"] == "carousel" for r in feed) / len(feed),
            "tuesday_carousel": all(r["post_type"] == "carousel" for r in feed if r["weekday"] == "Tue"),
            "hook_share": sum(WIN_HOOK in r["pattern_ids"] for r in video) / max(1, len(video)),
            "explore_share": sum(r["strategy"]["mode"] == "explore" for r in pattern_rows) / max(1, len(pattern_rows)),
            "hook_status": pb["patterns"][WIN_HOOK]["status"],
        })
        for r in rows:
            if r["post_type"] == "story":
                continue
            pid = f"p{r['date']}"
            hh, mi = r["post_time"].split(":")
            posted = datetime.fromisoformat(r["date"]).replace(hour=int(hh), minute=int(mi))
            truths[pid] = (posted, truth(r, rng))
            store["reels"][pid] = {"tags": {"post_type": r["post_type"], "pillar": r.get("pillar"), "series": r.get("series"),
                                            "posting_time": f"{r['date']}T{r['post_time']}:00", "length": 50,
                                            "pattern_ids": r["pattern_ids"], "strategy_arm": r["strategy_arm"]},
                                   "pulls": {}}
    return curve, store, state


@pytest.fixture(scope="module")
def sim():
    return simulate()


# --------------------------------------------------------------------------- schema and claims (R344)
def test_schemas_are_valid_draft_2020_12():
    for name in ("playbook", "strategy_brief"):
        schema = json.loads((REPO / "schemas" / f"{name}.schema.json").read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", ["patterns", "diagnosis", "calendar", "policies"])
def test_playbook_files_validate(name):
    doc = json.loads((PLAYBOOK / f"{name}.json").read_text())
    assert doc["kind"] == name and name in doc
    assert nc.schema_errors("playbook.schema.json", doc) == []


EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⏰-⏿]")


def test_playbook_is_seeded_from_the_research_with_numa_facts():
    pats = json.loads((PLAYBOOK / "patterns.json").read_text())["patterns"]
    by = {p["id"]: p for p in pats}
    count = lambda k: sum(p["kind"] == k for p in pats)  # noqa: E731
    assert (count("hook"), count("structure"), count("carousel"), count("photo")) == (32, 16, 12, 9)   # R1, R3, R4
    assert by["clinical-conversations-question"]["status"] == "retired" and "trend-audio-sync" not in by   # REVIEW.md
    assert by["beat-sync-original-sound"]["aliases"] == ["trend-audio-sync"]
    assert "trending" in by["beat-sync-original-sound"]["template"].lower() and "never" in by["beat-sync-original-sound"]["template"].lower()
    assert "photo" in by["member-experience-voice"]["template"] and "never a standalone text card" in by["member-experience-voice"]["template"]
    assert not [p["id"] for p in pats if p["status"] == "proven"], "no seed may be proven before Numa has data"
    ids = set(by)
    for p in pats:
        assert p["evidence"]["sources"] and p["when_not"] and set(p["try_instead"]) <= ids, p["id"]
        if p["status"] == "retired":
            continue
        text = json.dumps({k: p[k] for k in ("name", "template", "examples", "visual", "beats", "when_not") if k in p}, ensure_ascii=False)
        assert not EMOJI.search(text), p["id"]
        assert not re.search(r"\bNUMA\b|14-person|\brobes?\b|\btea\b|\blockers?\b|Clinical Conversations", text), p["id"]
        for temp in re.findall(r"(\d+)°", text):
            assert 44 <= int(temp) <= 52 or 175 <= int(temp) <= 190 or int(temp) >= 85, (p["id"], temp)   # plunge, sauna or weather
    worked = {p["id"] for p in pats if p.get("owner_signal") == "worked"}
    assert {"plunge-entry", "reaction-face", "collab-local-face", "struct-event-recap"} <= worked
    assert by["number-cover"]["owner_signal"] == "flopped"
    assert [p["id"] for p in sorted((p for p in pats if p["kind"] == "hook"), key=lambda p: p["priority"])][:3] == \
        ["plunge-entry", "steam-pour", "reaction-face"]                                              # R1 "test first" order
    templates = {t["id"] for g in ("templates", "presets")
                 for t in json.loads((REPO / "skills" / "numa-scriptwriter" / "templates.json").read_text())[g]}
    for p in pats:
        assert set(p.get("templates", [])) <= templates, p["id"]
    diag = json.loads((PLAYBOOK / "diagnosis.json").read_text())["diagnosis"]
    assert len(diag) == 17 and all("R3_Script_structures" in d["evidence"]["sources"][0] for d in diag)


def test_policies_adopt_r6_and_r7():
    pol = json.loads((PLAYBOOK / "policies.json").read_text())["policies"]
    sc_ = pol["scoring"]
    assert sc_["composite"] == {"sends": 0.3, "follows": 0.2, "watch_through": 0.2, "saves": 0.15, "reach": 0.15}
    assert sc_["baseline"] == {"window_posts": 20, "min_age_days": 7, "min_posts": 3} and sc_["index_clip_log2"] == 2
    lp = pol["learning"]
    assert lp["discount"] == 0.97 and lp["explore_share"] == 0.3 and lp["max_pattern_share_month"] == 0.4
    assert lp["promote"] == {"min_tries": 8, "min_wins": 6, "min_median_index": 1.25}
    assert lp["fast_track"] == {"first": 6, "min_wins": 5, "min_median_index": 1.4}
    assert lp["retire"]["rules"] == [{"min_tries": 6, "max_wins": 1}, {"min_tries": 8, "max_wins": 2}]
    assert lp["demote"] == {"last": 8, "max_wins": 3, "min_median_index": 1.0}
    assert set(lp["exclude_from_decisions"]) == {"holiday", "boosted", "collab"} and lp["retired_months"] == 3
    assert "heuristic (R6)" in lp["evidence"]["notes"] and "heuristic (R6)" in sc_["evidence"]["notes"]
    j = pol["judging"]
    assert (j["reel"]["provisional_hours"], j["reel"]["provisional_weight"], j["reel"]["final_hours"]) == (72, 0.6, 168)
    assert j["reel"]["exceptions"]["saves"]["final_hours"] == 336 and j["reel"]["exceptions"]["shares"]["final_hours"] == 336
    assert j["reel"]["exceptions"]["skip_rate"]["final_hours"] == 72 and j["reel"]["long_tail_audit_hours"] == 720
    assert j["story"]["final_hours"] < 24 and pol["judging_cohorts"]["collab"]["provisional_weight"] == 0.4


def test_every_playbook_example_passes_claims_scan():
    pats = json.loads((PLAYBOOK / "patterns.json").read_text())["patterns"]
    texts = [(p["id"], t) for p in pats for t in p["examples"] + [p["template"]]]
    cal = json.loads((PLAYBOOK / "calendar.json").read_text())["calendar"]
    texts += [(m["id"], t) for g in ("monthly", "seasonal", "holidays") for m in cal[g] for t in m.get("examples", [])]
    assert len(texts) > 200
    for where, text in texts:
        hits = claims_scan.scan_text(text, where=where)
        assert not hits, f"{where}: {[h.line() for h in hits]}"


def test_validate_and_export_cli(tmp_path):
    r = run("validate", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["ok"] and rep["errors"] == [] and rep["warnings"] == []
    out = tmp_path / "merged.json"
    r = run("export", "--out", out)
    assert r.returncode == 0, r.stderr
    merged = json.loads(out.read_text())
    assert merged["kind"] == "merged" and nc.schema_errors("playbook.schema.json", merged) == []


def test_validate_rejects_a_banned_example(tmp_path):
    bad = tmp_path / "pb"
    bad.mkdir()
    for f in PLAYBOOK.glob("*.json"):
        (bad / f.name).write_text(f.read_text())
    doc = json.loads((bad / "patterns.json").read_text())
    doc["patterns"][0]["examples"].append("The sauna detoxes your body.")
    (bad / "patterns.json").write_text(json.dumps(doc))
    r = run("validate", "--playbook", bad)
    assert r.returncode == 1 and "detox" in r.stderr and "Traceback" not in r.stderr


# --------------------------------------------------------------------------- cold start (R346)
@pytest.mark.parametrize("month", ["2026-12", "2027-02", "2027-03", "2027-08"])
def test_cold_start_plan_is_the_default_week_and_valid(month):
    pb, posts, fits = fits_for(empty_store())
    assert fits["lambda"] == 0 and fits["judged"] == 0
    plan, violations = S.month_plan(pb, fits, month, None, [], None, posts, [])
    assert violations == []
    closures = S.closure_dates(None)
    v, _, _ = shoot_card.check_plan(S.compat_plan(plan), closures)
    assert v == []
    sk = shoot_card.skeleton(*shoot_card.parse_month(month))
    for row, base in zip(plan["rows"], sk["rows"]):
        assert row["date"] == base["date"]
        if row.get("event_role") or row.get("signature") or "content mix" in " ".join(row["strategy"]["why"]) \
                or row["strategy"].get("tests") == "format" or row["strategy"].get("feed_per_week", 5) < 5:
            continue
        assert row["kind"] == base["kind"], row["date"]       # default week types and days at cold start
    first_week = [r for r in plan["rows"] if r["strategy"]["week"] == plan["rows"][0]["strategy"]["week"]]
    assert {r["post_time"] for r in first_week} == {"16:30"}                 # late afternoon first (spec p.34)
    assert {r["post_time"] for r in plan["rows"]} <= {"16:30", "07:00", "12:00"}   # then the blocked rotation (R6)
    retired = {pid for pid, p in pb["patterns"].items() if p["status"] == "retired"}
    for r in plan["rows"]:
        arm = S.parse_arm(r["strategy_arm"])
        assert list(arm) == list(S.ARM_KEYS) and arm["type"] == r["post_type"] and arm["plan"] == month
        assert set(r["pattern_ids"]) <= set(pb["patterns"]) and not set(r["pattern_ids"]) & retired
        if r["kind"] != "stories":
            assert r["pattern_ids"], r["date"]
        if r.get("series") == "ask_the_dpt":
            assert not any(pb["patterns"][x]["kind"] == "offer" for x in r["pattern_ids"])
    trials = [r for r in plan["rows"] if r["kind"] == "trial_reel"]
    assert trials and all(r["strategy"]["mode"] == "explore" for r in trials)   # Trial Reels explore, on top
    feed = [r for r in plan["rows"] if r["kind"] in ("reel", "carousel", "image")]
    explore_feed = [r for r in feed if r["strategy"]["mode"] == "explore"]
    assert len(explore_feed) == round(0.3 * len(feed))                       # R6: about 70/30
    assert plan["strategy"]["explore_variable"].startswith("testing hook first")


def test_plan_cli_writes_month_json(tmp_path):
    out = tmp_path / "plan.json"
    r = run("plan", "--month", "2026-12", "--today", "2026-11-13", "--out", out)
    assert r.returncode == 0, r.stderr
    plan = json.loads(out.read_text())
    assert plan["month"] == "2026-12" and len(plan["rows"]) == 31
    assert plan["strategy"]["data_led_share"] == 0 and plan["strategy"]["violations"] == []
    closed = {c["date"] for c in plan["closures"]}
    assert {"2026-12-24", "2026-12-25"} <= closed and "2026-12-31" not in closed   # brand.json ranges; open-until days aren't closures
    r = run("explain", "8", "--plan", out, "--json")
    assert r.returncode == 0, r.stderr
    ex = json.loads(r.stdout)
    assert ex["date"] == "2026-12-08" and ex["why"] and any(w.startswith("Hour:") for w in ex["why"])
    r = run("explain", "2026-12-03", "--plan", out)
    assert r.returncode == 0 and "Patterns:" in r.stdout


# --------------------------------------------------------------------------- determinism
def test_plan_is_deterministic_with_a_seed(sim, tmp_path):
    _, store, state = sim
    m, st = tmp_path / "metrics.json", tmp_path / "strategy.json"
    m.write_text(json.dumps(store))
    st.write_text(json.dumps(state))
    outs = []
    for i in range(2):
        out = tmp_path / f"p{i}.json"
        r = run("plan", "--month", "2026-07", "--metrics", m, "--state", st, "--today", "2026-06-21", "--seed", 11, "--out", out)
        assert r.returncode == 0, r.stderr
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    out = tmp_path / "p2.json"
    run("plan", "--month", "2026-07", "--metrics", m, "--state", st, "--today", "2026-06-21", "--seed", 12, "--out", out)
    a = [r["pattern_ids"] for r in json.loads(outs[0])["rows"]]
    b = [r["pattern_ids"] for r in json.loads(out.read_text())["rows"]]
    assert a != b   # the seed drives the Thompson draws


# --------------------------------------------------------------------------- learning (R346, R348)
def test_learning_curve_shifts_to_the_true_winners(sim):
    curve, _, _ = sim
    early, late = curve[:4], curve[8:]
    mean = lambda rows, k: sum(r[k] for r in rows) / len(rows)  # noqa: E731
    assert mean(late, "carousel_share") >= mean(early, "carousel_share") + 0.08   # carousels grow past R2's soft share
    assert all(r["tuesday_carousel"] for r in curve)             # the Tuesday carousel is never given up
    assert mean(early, "hook_share") <= 0.25                    # R1's test-first hook #2, one arm of five
    assert mean(late, "hook_share") >= max(0.3, mean(early, "hook_share") + 0.15)
    assert mean(late, "hook_share") <= 0.6                         # the 40% cap (per month and week) keeps variety
    assert all(r["explore_share"] >= 0.15 for r in curve)        # exploration kept every week
    assert curve[-1]["hook_status"] == "proven"                  # promoted by R6's rule (>= 6 of 8, median >= 1.25x)
    assert curve[0]["data_led"] == 0 and curve[-1]["data_led"] == 1


def test_hook_cap_holds_in_every_month(sim, tmp_path):
    _, store, state = sim
    pb, posts, fits = fits_for(store, state, date(2026, 6, 21))
    for month in ("2026-07", "2026-08"):
        plan, v = S.month_plan(pb, fits, month, None, [], None, posts, [])
        assert v == []
        for video in (True, False):                                # video and static hooks are separate arms, capped apart
            rows = [r for r in plan["rows"] if (r["post_type"] in ("reel", "trial_reel")) == video]
            hooks = [x for r in rows for x in r.get("pattern_ids", []) if pb["patterns"][x]["kind"] == "hook"]
            assert not hooks or max(hooks.count(h) for h in set(hooks)) <= max(1, int(0.4 * len(hooks)))


def test_learn_cli_changelog_and_insights(sim, tmp_path):
    _, store, _ = sim
    m, st, txt = tmp_path / "metrics.json", tmp_path / "strategy.json", tmp_path / "changes.txt"
    m.write_text(json.dumps(store))
    r = run("learn", "--metrics", m, "--state", st, "--today", "2026-06-21", "--text", txt, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    ov = state["status_overrides"][WIN_HOOK]
    assert ov["status"] == "proven" and ov["tries"] >= 8 and ov["wins"] >= 6 and ov["median_index"] >= 1.25
    promote = [c for c in rep["changes"] if c["target"] == WIN_HOOK]
    assert promote and promote[0]["action"] == "promote" and "beat Numa's median in" in promote[0]["why"]
    assert any(WIN_HOOK in x for x in rep["insights"]["do_more"])
    text = txt.read_text()
    assert text.startswith("Strategy update 2026-06-21") and "Do more of:" in text and "Do less of:" in text
    n = len(state["changelog"])
    r = run("learn", "--metrics", m, "--state", st, "--today", "2026-06-21", "--json")
    assert json.loads(r.stdout)["changes"] == [] and len(json.loads(st.read_text())["changelog"]) == n


def _decision_store(hook_wins: dict[str, bool], start=date(2026, 3, 2), n=16, step=2, **extra_tags):
    """Alternating posts of two hooks: a loser and a neutral one; metrics make the loser lose clearly."""
    store = empty_store()
    rng = np.random.default_rng(3)
    for i in range(n):
        d = start + timedelta(days=i * step)
        hook = list(hook_wins)[i % len(hook_wins)]
        good = hook_wins[hook]
        m = {"views": int(900 * math.exp(rng.normal(0, 0.05))), "reach": 700, "shares": 6 if good else 1, "saves": 4 if good else 1,
             "skip_rate": 62 if good else 80, "avg_watch_time_ms": 13000 if good else 6000}
        if not good:
            m["reach"], m["views"] = 350, 450
        store["reels"][f"r{i:02d}"] = {"tags": {"post_type": "reel", "posting_time": f"{d.isoformat()}T16:30:00", "length": 50,
                                                "pattern_ids": [hook], **extra_tags},
                                       "pulls": {"7d": {"metrics": m}}}
    return store


def test_retire_reentry_and_never_planned():
    store = _decision_store({"myth-not-required": False, "steam-pour": True})
    today = date(2026, 5, 1)
    pb, posts, fits = fits_for(store, today=today)
    state, changes = S.learn(pb, fits, today)
    ov = state["status_overrides"]["myth-not-required"]
    assert ov["status"] == "retired" and ov["wins"] <= 2 and ov["median_index"] <= 0.8
    assert any(c["action"] == "retire" and "retired for 3 months" in c["why"] for c in changes)
    pb2 = S.load_playbook(None, state)
    posts2 = S.collect_posts(store, pb2, today)
    S.score_posts(posts2, pb2)
    plan, v = S.month_plan(pb2, S.fit_models(posts2, pb2), "2026-06", 1, [], None, posts2, [])
    assert v == [] and not any("myth-not-required" in r["pattern_ids"] for r in plan["rows"])
    later = date(2026, 8, 2)                                       # 3 months on: re-enters testing once
    pb3 = S.load_playbook(None, state)
    posts3 = S.collect_posts(store, pb3, later)
    S.score_posts(posts3, pb3)
    state3, changes3 = S.learn(pb3, S.fit_models(posts3, pb3), later)
    assert state3["status_overrides"]["myth-not-required"] == {**state3["status_overrides"]["myth-not-required"], "status": "testing", "reentered": True}
    assert any(c["action"] == "reenter" for c in changes3)


def test_holiday_collab_and_boosted_posts_stay_out_of_decisions():
    for tags in ({"collab": True}, {"boosted": True}):
        store = _decision_store({"myth-not-required": False, "steam-pour": True}, **tags)
        pb, posts, fits = fits_for(store, today=date(2026, 5, 1))
        assert all(set(p["excluded"]) for p in posts if p["score"] is not None)
        state, _ = S.learn(pb, fits, date(2026, 5, 1))
        assert "myth-not-required" not in state["status_overrides"]
    store = _decision_store({"myth-not-required": False, "steam-pour": True}, start=date(2025, 12, 20), n=8)
    pb, posts, fits = fits_for(store, today=date(2026, 2, 1))
    assert all("holiday" in p["flags"] for p in posts)                       # Dec 20 - Jan 5 (R6 section 8)


def test_january_wins_wait_for_february_march():
    store = _decision_store({"steam-pour": True, "myth-not-required": False}, start=date(2027, 1, 6), n=28, step=1)
    pb, posts, fits = fits_for(store, today=date(2027, 3, 1))
    a = fits["arms"][("hook", "steam-pour")]
    st = S.decision_stats(a["records"])
    assert st["wins"] >= 8 and sum(r["january"] for r in st["records"]) >= 7   # MLK week is held out as a holiday week
    state, changes = S.learn(pb, fits, date(2027, 3, 1))
    assert state["status_overrides"].get("steam-pour", {}).get("status") != "proven"
    assert any(c["action"] == "hold" and "January" in c["why"] for c in changes)


# --------------------------------------------------------------------------- rules win (R347)
def test_planning_rules_with_events_and_closures(sim, tmp_path):
    _, store, state = sim
    m, st = tmp_path / "metrics.json", tmp_path / "strategy.json"
    m.write_text(json.dumps(store))
    st.write_text(json.dumps(state))
    ev = tmp_path / "events.json"
    ev.write_text(json.dumps([{"name": "Numa Nights", "date": "2026-07-17"}]))
    cl = tmp_path / "closures.json"
    cl.write_text(json.dumps([{"date": "2026-07-10", "name": "staff day"}, {"start": "2026-07-22", "end": "2026-07-23", "closed": True, "what": "storm"}]))
    out = tmp_path / "plan.json"
    r = run("plan", "--month", "2026-07", "--metrics", m, "--state", st, "--today", "2026-06-21",
            "--events", ev, "--closures", cl, "--out", out)
    assert r.returncode == 0, r.stderr
    plan = json.loads(out.read_text())
    closures = S.closure_dates(str(cl))
    assert {date(2026, 7, 10), date(2026, 7, 22), date(2026, 7, 23)} <= set(closures)
    v, _, _ = shoot_card.check_plan(S.compat_plan(plan), closures)
    assert v == []
    rows = plan["rows"]
    assert [r["event_role"] for r in rows if r.get("event")] == ["teaser", "recap"]
    for r in rows:
        if date.fromisoformat(r["date"]) in closures:
            assert not shoot_card.is_invite({**r, "_d": date.fromisoformat(r["date"])}), r
    weeks = {}
    for r in rows:
        if r["kind"] != "stories" and shoot_card.is_sales(r):
            weeks.setdefault(shoot_card.monday_of(date.fromisoformat(r["date"])), []).append(r["date"])
    assert all(len(x) == 1 for x in weeks.values()), weeks
    reels = [r for r in rows if r["kind"] == "reel"]
    assert any(r.get("collab") and r.get("series") != "meet_the_collective" for r in reels)
    assert any(r.get("series") == "meet_the_collective" for r in reels)
    assert any(r.get("signature") for r in reels)
    for wk in {r["strategy"]["week"] for r in rows}:
        feed = [r for r in rows if r["strategy"]["week"] == wk and r["kind"] in ("reel", "carousel", "image")]
        assert sum(r["kind"] != "reel" for r in feed) <= int(len(feed) * 0.6)   # soft bounds widen with evidence, never past reels >= 40%
        assert sum(r["kind"] == "image" for r in feed) <= int(len(feed) * 0.4)


def test_rules_cut_the_bandit_when_it_breaks_a_rule(monkeypatch):
    pb, posts, fits = fits_for(empty_store())
    fits = dict(fits, **{"lambda": 1.0})
    calls = []
    real = shoot_card.check_plan

    def strict(plan, closures):
        calls.append(len(calls))
        v, w, mix = real(plan, closures)
        if len(calls) == 1:   # pretend the data-led plan broke a rule
            v = v + [{"rule": "1-sales-per-week", "days": [], "message": "synthetic"}]
        return v, w, mix
    monkeypatch.setattr(S.sc, "check_plan", strict)
    plan, v = S.month_plan(pb, fits, "2026-12", 3, [], None, posts, [])
    assert v == [] and plan["strategy"]["rules_overrode_bandit"]
    assert plan["strategy"]["data_led_share_used"] == 0.5
    assert any("Planning rules won" in w for r in plan["rows"] for w in r["strategy"]["why"])


# --------------------------------------------------------------------------- scoring and judging windows (R345)
def _reel(posted, pulls, **tags):
    return {"tags": {"post_type": "reel", "posting_time": posted, "length": 50, **tags},
            "pulls": {k: {"metrics": v} for k, v in pulls.items()}}


def _m(scale=1.0, saves=4):
    return {"views": int(1000 * scale), "reach": int(800 * scale), "shares": 4 * scale, "saves": saves * scale,
            "skip_rate": 64, "avg_watch_time_ms": 12000}


def test_judging_windows_pending_provisional_final():
    store = empty_store()
    for i in range(4):
        store["reels"][f"base{i}"] = _reel(f"2026-10-0{i + 1}T16:30:00", {"7d": _m()})
    store["reels"]["young"] = _reel("2026-11-12T16:30:00", {"48h": _m()})                 # ~31 h: ignored (reel: 48 h)
    store["reels"]["early"] = _reel("2026-11-09T16:30:00", {"48h": _m(), "72h": _m()})     # provisional at 0.6
    store["reels"]["done"] = _reel("2026-11-01T16:30:00", {"48h": _m(), "72h": _m(), "7d": _m(1.4)})  # final
    store["reels"]["trial"] = {"tags": {"post_type": "trial_reel", "posting_time": "2026-11-09T16:30:00"},
                               "pulls": {"72h": {"metrics": _m()}}}                          # trial: final at 72 h
    store["reels"]["story"] = {"tags": {"post_type": "story", "posting_time": "2026-11-12T09:00:00"},
                               "pulls": {"22h": {"metrics": {"reach": 300, "views": 340}}}}
    store["reels"]["collab"] = _reel("2026-11-09T16:30:00", {"72h": _m()}, collab=True)   # cohort: ignore before... prov at 168
    pb, posts, fits = fits_for(store, today=date(2026, 11, 13))
    by = {p["id"]: p for p in posts}
    assert by["young"]["status"] == "pending" and by["young"]["score"] is None
    assert by["early"]["status"] == "provisional" and by["early"]["pull"] == "72h" and by["early"]["judge_weight"] == 0.6
    assert by["done"]["status"] == "final" and by["done"]["pull"] == "7d" and by["done"]["judge_weight"] == 1.0
    assert by["trial"]["status"] == "final" and by["story"]["status"] == "final"
    assert by["collab"]["status"] == "pending"                       # collab cohort: provisional only from 168 h, weight 0.4
    assert fits["provisional"] == 1 and by["done"]["score"] > 0       # each post counted once, at its latest window
    win = by["done"]["records"] if "records" in by["done"] else None
    assert win is None


def test_scores_are_log2_indexes_against_the_trailing_median():
    store = empty_store()
    for i in range(5):
        store["reels"][f"b{i}"] = _reel(f"2026-09-0{i + 1}T16:30:00", {"7d": _m()})
    store["reels"]["x"] = _reel("2026-10-20T16:30:00", {"7d": {**_m(), "shares": 32, "saves": 4}})   # sends 8x the median
    pb, posts, _ = fits_for(store, today=date(2026, 11, 13))
    x = next(p for p in posts if p["id"] == "x")
    assert x["components"]["sends"] == 2.0                           # log2(8) = 3, clipped at +2
    assert x["components"]["saves"] == 0.0 and x["win"] is True
    assert set(x["goal_scores"]) >= {"reach", "sends", "saves"}


def test_metric_exceptions_read_each_metric_at_its_own_window():
    store = empty_store()
    for i in range(4):
        store["reels"][f"b{i}"] = _reel(f"2026-09-0{i + 1}T16:30:00", {"7d": _m()})
    store["reels"]["c"] = _reel("2026-11-09T16:30:00", {"72h": _m(saves=40)})             # provisional
    store["reels"]["d"] = _reel("2026-10-20T16:30:00", {"72h": {**_m(), "avg_watch_time_ms": 30000},
                                                        "7d": {**_m(), "avg_watch_time_ms": 12000}})
    pb, posts, _ = fits_for(store, today=date(2026, 11, 13))
    c = next(p for p in posts if p["id"] == "c")
    assert "saves" not in c["components"] and "sends" not in c["components"]   # R7: saves/shares read from 7 d on
    d = next(p for p in posts if p["id"] == "d")
    assert d["components"]["watch_through"] > 0                       # R7: watch time final at 72 h, read from the 72 h pull


def test_owner_priors_outrank_research_priors():
    pb = S.load_playbook()
    owner = S.arm_prior(pb, "hook", "plunge-entry")
    research = S.arm_prior(pb, "hook", "steam-pour")
    flop = S.arm_prior(pb, "hook", "number-cover")
    mean = lambda ab: ab[0] / sum(ab)  # noqa: E731
    assert mean(owner) > mean(research) > mean(flop) and sum(owner) > sum(research)
    state = S.empty_state()
    state["owner_priors"] = [{"target": "steam-pour", "signal": "flopped", "why": "setup answers"}]
    assert mean(S.arm_prior(S.load_playbook(None, state), "hook", "steam-pour")) < 0.5


def test_brief_lists_provisional_posts_and_validates(sim, tmp_path):
    _, store, state = sim
    m, st = tmp_path / "metrics.json", tmp_path / "strategy.json"
    m.write_text(json.dumps(store))
    st.write_text(json.dumps(state))
    plan = tmp_path / "plan.json"
    assert run("plan", "--month", "2026-06", "--metrics", m, "--state", st, "--today", "2026-06-21", "--out", plan).returncode == 0
    notes = tmp_path / "notes.txt"
    notes.write_text("Steam hooks lead; keep the Tuesday carousel.\n")
    out, md = tmp_path / "brief.json", tmp_path / "brief.md"
    r = run("brief", "--plan", plan, "--metrics", m, "--state", st, "--today", "2026-06-21", "--week", "2026-06-22",
            "--out", out, "--md", md, "--notes", notes)
    assert r.returncode == 0, r.stderr
    b = json.loads(out.read_text())
    assert nc.schema_errors("strategy_brief.schema.json", b) == []
    assert b["week_of"] == "2026-06-22" and len(b["slots"]) == 7
    assert b["provisional"] and all(0 < p["weight"] < 1 for p in b["provisional"])
    assert b["data"]["provisional_posts"] == len(b["provisional"])
    assert b["strategist_notes"].startswith("Steam hooks lead")
    assert any(u["id"] == WIN_HOOK for u in b["use_patterns"])
    g = " ".join(b["guardrails"])
    assert "Discover Numa" in g and "never invent" in g and "Saturday mornings" in g
    assert any("Offer week of the month: learning is slow" in x and "v2.2" in x for x in b["reasoning"])
    text = md.read_text()
    for head in ("## This week", "## Still provisional", "## Do more of", "## Why", "## Strategist notes", "## Guardrails"):
        assert head in text
    notes.write_text("Plunging cures stress.")
    r = run("brief", "--plan", plan, "--metrics", m, "--state", st, "--today", "2026-06-21", "--notes", notes)
    assert r.returncode == 1 and "banned claim" in r.stderr


def test_diagnose_matches_the_table():
    store = empty_store()
    for i in range(6):
        d = date(2026, 9, 1) + timedelta(days=3 * i)
        store["reels"][f"ok{i}"] = _reel(f"{d.isoformat()}T16:30:00", {"7d": _m()}, series="regulate")
    store["reels"]["weak"] = _reel("2026-10-25T16:30:00", {"7d": {**_m(0.6), "skip_rate": 78, "shares": 0.5,
                                                                   "avg_watch_time_ms": 8000}}, series="regulate")
    pb, posts, fits = fits_for(store, today=date(2026, 11, 13))
    diag = S.recent_diagnoses(posts, pb)
    assert diag and diag[0]["post"] == "weak"
    ids = {r["id"] for r in diag[0]["rows"]}
    assert {"skip-above-median", "sends-low"} <= ids
    bonus = S.Planner(pb, fits, 2026, 12, 1, [], {}, posts, diag).diagnosis_bonus()
    assert bonus[("regulate", "plunge-entry")] > 0


# --------------------------------------------------------------------------- import-research (R349)
def test_import_research_fixtures(tmp_path):
    st = tmp_path / "strategy.json"
    files = [FIXTURES / "R1 Hooks.md", FIXTURES / "R3 Script structures.md", FIXTURES / "R2 Formats and mix.md"]
    r = run("import-research", *files, "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert set(rep["added"]) == {"steam-reveal", "cold-plunge-feet", "three-beat-explainer"}
    assert "temp-split" in rep["merged"]
    assert any("detox-hook" in x for x in rep["rejected"])
    assert any("Feels off" in x for x in rep["rejected"])
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    by = {p["id"]: p for p in state["patterns"]}
    steam = by["steam-reveal"]
    assert steam["kind"] == "hook" and steam["status"] == "candidate" and steam["origin"] == "research"
    assert steam["evidence"]["level"] == "observed" and "https://example.org/steam-study" in steam["evidence"]["sources"]
    assert steam["try_instead"] == ["temp-split", "seasonal-weather"]
    assert set(steam["formats"]) == {"reel", "trial_reel", "story"}
    assert by["three-beat-explainer"]["kind"] == "structure" and by["three-beat-explainer"]["length_s"] == [45, 60]
    assert "temp-split" not in by                                 # a bundled pattern is never copied into STATE
    delta = state["pattern_deltas"]["temp-split"]
    assert "https://example.org/hooks-2026" in delta["sources"] and set(delta) <= {"sources", "examples", "notes"}
    merged_ts = S.load_playbook(None, state)["patterns"]["temp-split"]
    seed = S.load_playbook()["patterns"]["temp-split"]
    assert merged_ts["status"] == seed["status"] and merged_ts["evidence"]["level"] == seed["evidence"]["level"]   # never upgraded
    assert "https://example.org/hooks-2026" in merged_ts["evidence"]["sources"]
    for p in state["patterns"]:
        for ex in p["examples"]:
            assert not claims_scan.has_fail(claims_scan.scan_text(ex))
    assert {d["metric"] for d in state["diagnosis"]} == {"skip_rate", "saves_per_1k_reach"}   # the third symptom is already a seed row
    assert any(m.startswith("diagnosis:") for m in rep["merged"])
    assert {p["level"]: p["value"] for p in state["priors"]} == {"reel": 0.65, "carousel": 0.3}
    assert state["rules"][0]["topic"] == "cadence" and state["rules"][0]["evidence"]["level"] == "measured"
    r = run("import-research", files[0], "--state", st, "--today", "2026-11-14", "--json")
    rep2 = json.loads(r.stdout)
    assert rep2["added"] == [] and rep2["skipped"] == ["R1 Hooks.md"]          # same text: skipped, idempotent
    again = json.loads(st.read_text())
    assert again["patterns"] == state["patterns"] and len(again["changelog"]) == len(state["changelog"])
    assert len(again["imports"]) == len(state["imports"])
    assert run("validate", "--state", st).returncode == 0


def test_import_real_research_reports(tmp_path):
    """The committed deep-research results parse: R1 (32 hooks), R3 (16 structures + 17-row table), R4 (12 + 9)."""
    st = tmp_path / "strategy.json"
    files = [REPO / "docs" / "research" / f for f in ("R1_Hooks.md", "R3_Script_structures.md", "R4_Carousels_photos_offers.md")]
    r = run("import-research", *files, "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    # the seed already holds them (built from these files), so they merge instead of duplicating
    assert rep["added"] == []                                   # renamed and dropped ids map to their seed entries (aliases)
    assert {"beat-sync-original-sound", "carousel-meet-the-guide", "clinical-conversations-question"} <= set(rep["merged"])
    assert len([m for m in rep["merged"] if not m.startswith("diagnosis:")]) == 32 + 16 + 12 + 9
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    assert run("validate", "--state", st).returncode == 0


def test_import_never_overwrites_numa_results(tmp_path):
    st = tmp_path / "strategy.json"
    state = S.empty_state()
    state["status_overrides"]["temp-split"] = {"status": "retired", "since": "2026-10-01", "why": "lost on Numa's data",
                                               "tries": 8, "wins": 1, "median_index": 0.7}
    st.write_text(json.dumps(state))
    assert run("import-research", FIXTURES / "R1 Hooks.md", "--state", st, "--today", "2026-11-13").returncode == 0
    after = json.loads(st.read_text())
    assert after["status_overrides"]["temp-split"]["status"] == "retired"
    assert S.load_playbook(None, after)["patterns"]["temp-split"]["status"] == "retired"


def test_import_r7_judging_windows_real_report(tmp_path):
    st = tmp_path / "strategy.json"
    r = run("import-research", REPO / "docs" / "research" / "R7_Judging_windows.md", "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert any("(story)" in x and "under 24 h" in x for x in rep["rejected"])     # the 168 h story follows row
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    j = state["judging"]
    assert set(j) == {"reel", "trial_reel", "carousel", "image", "story"}
    assert (j["reel"]["ignore_before_hours"], j["reel"]["provisional_hours"], j["reel"]["provisional_weight"], j["reel"]["final_hours"]) == (48, 72, 0.6, 168)
    assert j["reel"]["long_tail_audit_hours"] == 720
    assert (j["trial_reel"]["provisional_hours"], j["trial_reel"]["final_hours"]) == (24, 72)
    assert j["carousel"]["provisional_weight"] == 0.75 and j["image"]["provisional_weight"] == 0.8
    assert j["story"]["final_hours"] == 20 and j["story"]["ignore_before_hours"] == 6
    for pt in ("reel", "carousel", "image"):
        assert j[pt]["exceptions"]["saves"]["final_hours"] == 336 and j[pt]["exceptions"]["shares"]["final_hours"] == 336
    assert j["reel"]["exceptions"]["skip_rate"]["final_hours"] == 72 and j["reel"]["exceptions"]["avg_watch_time_s"]["final_hours"] == 72
    assert j["carousel"]["exceptions"]["follows"]["final_hours"] == 168
    assert state["judging_cohorts"]["collab"]["provisional_weight"] == 0.4
    assert j["reel"]["evidence"]["level"] == "measured" and any("developers.facebook.com" in s for s in j["reel"]["evidence"]["sources"])
    pb = S.load_playbook(None, state)
    assert pb["policies"]["judging"]["reel"]["final_hours"] == 168


def test_import_r7_sample_table(tmp_path):
    st = tmp_path / "strategy.json"
    r = run("import-research", FIXTURES / "R7 Judging windows.md", "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert any("story" in x and "under 24 h" in x for x in rep["rejected"])
    j = json.loads(st.read_text())["judging"]
    assert j["reel"]["provisional_hours"] == 48 and j["reel"]["provisional_weight"] == 0.4 and j["reel"]["final_hours"] == 168
    assert j["reel"]["exceptions"]["saves"]["final_hours"] == 168 and j["carousel"]["exceptions"]["shares"]["provisional_hours"] == 168
    pb = S.load_playbook(None, json.loads(st.read_text()))
    store = empty_store()
    store["reels"]["x"] = _reel("2026-11-10T16:30:00", {"48h": _m()})      # 48 h pull now counts as provisional
    posts = S.collect_posts(store, pb, date(2026, 11, 13))
    assert posts[0]["status"] == "provisional" and posts[0]["judge_weight"] == 0.4


# --------------------------------------------------------------------------- calendar and helpers
def test_calendar_dates():
    assert S.easter(2027) == date(2027, 3, 28)
    pb = S.load_playbook()
    feb27 = {m["id"]: m for m in S.month_moments(pb, 2027, 2)}
    assert "2027-02-09" in feb27["mardi-gras"]["dates"]                    # Fat Tuesday 2027
    nov = {m["id"]: m for m in S.month_moments(pb, 2026, 11)}
    assert nov["thanksgiving"]["dates"] == ["2026-11-26"] and nov["hurricane-season"]["to"] == "2026-11-30"
    jan = {m["id"]: m for m in S.month_moments(pb, 2027, 1)}
    assert jan["new-year-reset"]["offer"] and jan["month-start-payday"]["dates"][0] == "2027-01-01"


def test_strategy_arm_round_trip():
    arm = {"type": "carousel", "pillar": "education", "series": None, "day": "Tue", "band": "late_afternoon",
           "hook": "temp-split", "structure": "carousel-what-to-bring", "offer_week": None, "goal": "saves",
           "mode": "exploit", "plan": "2026-12"}
    text = S.format_arm(arm)
    assert text.startswith("type=carousel;pillar=education;series=;day=Tue")
    assert S.parse_arm(text) == arm


def test_score_cli_and_missing_metrics(tmp_path):
    store = empty_store()
    for i in range(4):
        store["reels"][f"a{i}"] = _reel(f"2026-10-0{i + 1}T16:30:00", {"7d": {"views": 900 + i, "reach": 700}})
    store["reels"]["c"] = {"tags": {"post_type": "image", "posting_time": "not a date"}, "pulls": {"7d": {"metrics": {"reach": 400}}}}
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(store))
    r = run("score", "--metrics", m, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert {p["id"] for p in rep["posts"]} == {"a0", "a1", "a2", "a3", "c"}
    assert "WARN:" in r.stderr and "Traceback" not in r.stderr
    assert run("score", "--metrics", m, "--today", "2026-11-13").returncode == 0


# --------------------------------------------------------------------------- CLI errors
@pytest.mark.parametrize("args,code,text", [
    ([], 2, "choose a command"),
    (["plan", "--month", "2026-13"], 2, "YYYY-MM"),
    (["plan", "--month", "2026-12", "--metrics", "nope.json"], 1, "metrics store not found"),
    (["explain", "40", "--plan", "nope.json"], 1, "not found"),
    (["learn", "--metrics", "nope.json"], 2, "--state"),
])
def test_cli_errors(args, code, text, tmp_path):
    r = run(*args, cwd=tmp_path)
    assert r.returncode == code, r.stderr
    assert text in r.stderr and "Traceback" not in r.stderr


def test_bad_state_is_a_clean_error(tmp_path):
    st = tmp_path / "strategy.json"
    st.write_text(json.dumps({"schema_version": 1, "kind": "state", "status_overrides": {"x": {"status": "great"}}}))
    r = run("plan", "--month", "2026-12", "--state", st)
    assert r.returncode == 1 and "ERROR:" in r.stderr and "Traceback" not in r.stderr


# --------------------------------------------------------------------------- instructions (R350)
def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def _strategy_flags():
    ap = S.build_parser()
    sub = next(a for a in ap._actions if a.__class__.__name__ == "_SubParsersAction")
    return {name: {o for a in p._actions for o in a.option_strings} for name, p in sub.choices.items()}


@pytest.mark.parametrize("path", [REPO / "agents" / "strategist.md", REPO / "skills" / "numa-scriptwriter" / "ADAPTIVE.md"])
def test_instruction_files_reference_real_commands(path):
    text = path.read_text(encoding="utf-8")
    flags = _strategy_flags()
    calls = re.findall(r'strategy\.py"?\s+([a-z-]+)([^\n`]*)', text)
    assert calls
    for cmd, rest in calls:
        assert cmd in flags, cmd
        for flag in re.findall(r"(--[a-z-]+)", rest):
            assert flag in flags[cmd], f"{cmd} {flag}"
    pb = S.load_playbook()
    known = set(pb["patterns"]) | {d["id"] for d in pb["diagnosis"]}
    for pid in re.findall(r"`([a-z]+(?:-[a-z0-9]+)+)`", text):
        assert pid in known, pid
    assert not re.search(r"\bask (katie|her)\b|\bconfirm with\b|\bwait for (katie|approval)\b", text, re.I)
    for line in re.findall(r'"([^"]{8,})"', text):
        assert not claims_scan.has_fail(claims_scan.scan_text(line)), line


def test_strategist_agent_frontmatter():
    fm = frontmatter(REPO / "agents" / "strategist.md")
    config = json.loads((REPO / "config" / "studio.json").read_text())
    assert fm["name"] == "strategist" and len(fm["description"]) > 60
    assert fm["model"] == config["models"]["agents"]["strategist"] == config["models"]["tiers"]["mid"]
    assert [t.strip() for t in fm["tools"].split(",")] == ["Bash", "Read", "Write"]
    text = (REPO / "agents" / "strategist.md").read_text()
    for must in ("tools not visible", "Jude", "never computes", "provisional", "strategy_brief.json", "never invent",
                 "Saturday morning"):
        assert must.lower() in text.lower(), must
