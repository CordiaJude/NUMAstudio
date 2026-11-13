"""Adaptive strategy engine and playbook (R344-R350, DECISIONS D23).

The synthetic history below is generated, not real data: a small simulated NUMA
account whose carousels (especially on Tuesdays) and "contrast-visual" hooks on
video truly outperform. The engine plans each week, the simulated posts get
metrics, and the next plan learns from them.
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
    if "contrast-visual" in row.get("pattern_ids", []) and pt in ("reel", "trial_reel"):
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


def simulate(weeks=12, seed=5, start=date(2026, 1, 5)):
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
            "contrast_share": sum("contrast-visual" in r["pattern_ids"] for r in video) / max(1, len(video)),
            "explore_share": sum(r["strategy"]["mode"] == "explore" for r in pattern_rows) / max(1, len(pattern_rows)),
            "contrast_status": pb["patterns"]["contrast-visual"]["status"],
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


def test_playbook_content_is_honest():
    pats = json.loads((PLAYBOOK / "patterns.json").read_text())["patterns"]
    kinds = {p["kind"] for p in pats}
    assert kinds == {"hook", "structure", "carousel", "photo", "offer", "cta", "growth"}
    assert not [p["id"] for p in pats if p["status"] == "proven"], "no seed may be proven before NUMA has data"
    assert not [p["id"] for p in pats if p["evidence"]["level"] == "numa"]
    ids = {p["id"] for p in pats}
    assert len(ids) == len(pats)
    for p in pats:
        assert p["evidence"]["sources"] and p["when_not"] and set(p["try_instead"]) <= ids, p["id"]
    templates = {t["id"] for g in ("templates", "presets")
                 for t in json.loads((REPO / "skills" / "numa-scriptwriter" / "templates.json").read_text())[g]}
    for p in pats:
        assert set(p.get("templates", [])) <= templates, p["id"]
    diag = json.loads((PLAYBOOK / "diagnosis.json").read_text())["diagnosis"]
    assert len(diag) >= 15
    pol = json.loads((PLAYBOOK / "policies.json").read_text())["policies"]
    assert set(pol["judging"]) == {"reel", "trial_reel", "carousel", "image", "story"}
    assert pol["judging"]["reel"]["provisional_hours"] == 72 and pol["judging"]["reel"]["final_hours"] == 168
    assert pol["judging"]["story"]["final_hours"] < 24
    assert all(w["origin"] == "seed" and w["evidence"]["level"] == "opinion" for w in pol["judging"].values())


def test_every_playbook_example_passes_claims_scan():
    pats = json.loads((PLAYBOOK / "patterns.json").read_text())["patterns"]
    texts = [(p["id"], t) for p in pats for t in p["examples"] + [p["template"]]]
    cal = json.loads((PLAYBOOK / "calendar.json").read_text())["calendar"]
    texts += [(m["id"], t) for g in ("monthly", "seasonal", "holidays") for m in cal[g] for t in m.get("examples", [])]
    assert len(texts) > 100
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
    cp = S.compat_plan(plan)
    v, _, _ = shoot_card.check_plan(cp, {})
    assert v == []
    sk = shoot_card.skeleton(*shoot_card.parse_month(month))
    for row, base in zip(plan["rows"], sk["rows"]):
        assert row["date"] == base["date"]
        if row.get("event_role") or row.get("signature") or "content mix" in " ".join(row["strategy"]["why"]):
            continue
        assert row["kind"] == base["kind"], row["date"]       # default week types and days at cold start
    assert {r["post_time"] for r in plan["rows"]} == {"16:30"}  # late afternoon prior (spec p.34)
    retired = {pid for pid, p in pb["patterns"].items() if p["status"] == "retired"}
    for r in plan["rows"]:
        arm = S.parse_arm(r["strategy_arm"])
        assert list(arm) == list(S.ARM_KEYS) and arm["type"] == r["post_type"] and arm["plan"] == month
        assert set(r["pattern_ids"]) <= set(pb["patterns"]) and not set(r["pattern_ids"]) & retired
        if r["kind"] != "stories":
            assert r["pattern_ids"], r["date"]
    trials = [r for r in plan["rows"] if r["kind"] == "trial_reel"]
    assert trials and all(r["strategy"]["mode"] == "explore" for r in trials)   # Trial Reels explore first
    st = plan["strategy"]
    assert 0.2 <= st["explore_slots"] / st["pattern_slots"] <= 0.3


def test_plan_cli_writes_month_json(tmp_path):
    out = tmp_path / "plan.json"
    r = run("plan", "--month", "2026-12", "--today", "2026-11-13", "--out", out)
    assert r.returncode == 0, r.stderr
    plan = json.loads(out.read_text())
    assert plan["month"] == "2026-12" and len(plan["rows"]) == 31
    assert plan["strategy"]["data_led_share"] == 0 and plan["strategy"]["violations"] == []
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
        r = run("plan", "--month", "2026-04", "--metrics", m, "--state", st, "--today", "2026-03-29", "--seed", 11, "--out", out)
        assert r.returncode == 0, r.stderr
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    out = tmp_path / "p2.json"
    run("plan", "--month", "2026-04", "--metrics", m, "--state", st, "--today", "2026-03-29", "--seed", 12, "--out", out)
    a = [r["pattern_ids"] for r in json.loads(outs[0])["rows"]]
    b = [r["pattern_ids"] for r in json.loads(out.read_text())["rows"]]
    assert a != b   # the seed drives the Thompson draws


# --------------------------------------------------------------------------- learning (R346, R348)
def test_learning_curve_shifts_to_the_true_winners(sim):
    curve, _, _ = sim
    early, late = curve[:3], curve[6:]
    mean = lambda rows, k: sum(r[k] for r in rows) / len(rows)  # noqa: E731
    assert mean(early, "carousel_share") == pytest.approx(0.2)
    assert mean(late, "carousel_share") >= 0.33
    assert all(r["tuesday_carousel"] for r in curve)             # the Tuesday carousel is never given up
    assert mean(early, "contrast_share") <= 0.15
    assert mean(late, "contrast_share") >= 0.35
    assert all(r["contrast_share"] < 1 for r in curve)            # never all-in on one hook
    assert all(r["explore_share"] >= 0.15 for r in curve)         # exploration kept every week
    assert curve[7]["contrast_status"] == "proven"                # promoted within 8 weeks
    assert curve[0]["data_led"] == 0 and curve[-1]["data_led"] == 1


def test_learn_cli_changelog_and_insights(sim, tmp_path):
    _, store, _ = sim
    m, st, txt = tmp_path / "metrics.json", tmp_path / "strategy.json", tmp_path / "changes.txt"
    m.write_text(json.dumps(store))
    r = run("learn", "--metrics", m, "--state", st, "--today", "2026-03-29", "--text", txt, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    assert state["status_overrides"]["contrast-visual"]["status"] == "proven"
    promote = [c for c in rep["changes"] if c["target"] == "contrast-visual"]
    assert promote and promote[0]["action"] == "promote" and "beat NUMA's median" in promote[0]["why"]
    assert any("Carousel" in x for x in rep["insights"]["do_more"])
    text = txt.read_text()
    assert text.startswith("Strategy update 2026-03-29") and "Do more of:" in text and "Do less of:" in text
    # a second learn on the same data changes nothing and adds no duplicate changelog lines
    n = len(state["changelog"])
    r = run("learn", "--metrics", m, "--state", st, "--today", "2026-03-29", "--json")
    assert json.loads(r.stdout)["changes"] == [] and len(json.loads(st.read_text())["changelog"]) == n


def test_retire_and_retired_never_planned():
    store = empty_store()
    rng = np.random.default_rng(3)
    for i in range(16):
        d = date(2026, 9, 1) + timedelta(days=i * 2)
        bad = i % 2 == 0
        m = {"views": int(900 * math.exp(rng.normal(0, 0.1))), "reach": 700, "shares": 1 if bad else 6, "saves": 2,
             "skip_rate": 80 if bad else 62, "avg_watch_time_ms": 7000 if bad else 13000}
        if bad:
            m["views"] = int(m["views"] * 0.5)
        store["reels"][f"r{i}"] = {"tags": {"post_type": "reel", "posting_time": f"{d.isoformat()}T16:30:00", "length": 50,
                                            "pattern_ids": ["myth-buster" if bad else "question-hook"]},
                                   "pulls": {"7d": {"metrics": m}}}
    pb, posts, fits = fits_for(store, today=date(2026, 11, 1))
    state, changes = S.learn(pb, fits, date(2026, 11, 1))
    assert state["status_overrides"]["myth-buster"]["status"] == "retired"
    assert any(c["action"] == "retire" and "won't be planned again" in c["why"] for c in changes)
    pb2 = S.load_playbook(None, state)
    posts2 = S.collect_posts(store, pb2, date(2026, 11, 1))
    S.score_posts(posts2, pb2)
    fits2 = S.fit_models(posts2, pb2)
    plan, v = S.month_plan(pb2, fits2, "2026-12", 1, [], None, posts2, [])
    assert v == [] and not any("myth-buster" in r["pattern_ids"] for r in plan["rows"])


# --------------------------------------------------------------------------- rules win (R347)
def test_planning_rules_with_events_and_closures(sim, tmp_path):
    _, store, state = sim
    m, st = tmp_path / "metrics.json", tmp_path / "strategy.json"
    m.write_text(json.dumps(store))
    st.write_text(json.dumps(state))
    ev = tmp_path / "events.json"
    ev.write_text(json.dumps([{"name": "Numa Nights", "date": "2026-04-17"}, {"name": "Clinical Conversations", "date": "2026-04-25"}]))
    cl = tmp_path / "closures.json"
    cl.write_text(json.dumps([{"date": "2026-04-03", "name": "Good Friday"}, "2026-04-10"]))
    out = tmp_path / "plan.json"
    r = run("plan", "--month", "2026-04", "--metrics", m, "--state", st, "--today", "2026-03-29",
            "--events", ev, "--closures", cl, "--out", out)
    assert r.returncode == 0, r.stderr
    plan = json.loads(out.read_text())
    closures = shoot_card.closure_dates({"closures": plan["closures"]}, None)
    v, _, _ = shoot_card.check_plan(S.compat_plan(plan), closures)
    assert v == []
    rows = plan["rows"]
    teasers = [r for r in rows if r.get("event_role") == "teaser"]
    recaps = [r for r in rows if r.get("event_role") == "recap"]
    assert {r["event"] for r in teasers} == {r["event"] for r in recaps} == {"Numa Nights", "Clinical Conversations"}
    for r in rows:
        if r["date"] in ("2026-04-03", "2026-04-10"):
            assert not shoot_card.is_invite({**r, "_d": date.fromisoformat(r["date"])}), r
    weeks = {}
    for r in rows:
        if r["kind"] != "stories" and shoot_card.is_sales(r):
            weeks.setdefault(shoot_card.monday_of(date.fromisoformat(r["date"])), []).append(r["date"])
    assert all(len(v) == 1 for v in weeks.values()), weeks
    reels = [r for r in rows if r["kind"] == "reel"]
    assert any(r.get("collab") and r.get("series") != "meet_the_collective" for r in reels)
    assert any(r.get("series") == "meet_the_collective" for r in reels)
    assert any(r.get("signature") for r in reels)
    for wk in {shoot_card.monday_of(date.fromisoformat(r["date"])) for r in rows}:
        feed = [r for r in rows if shoot_card.monday_of(date.fromisoformat(r["date"])) == wk and r["kind"] in ("reel", "carousel", "image")]
        assert sum(r["kind"] != "reel" for r in feed) <= 2     # feed_mix bounds hold however strong the data


def test_rules_cut_the_bandit_when_it_breaks_a_rule(monkeypatch):
    pb, posts, fits = fits_for(empty_store())
    fits = dict(fits, **{"lambda": 1.0})
    calls = []
    real = shoot_card.check_plan

    def strict(plan, closures):
        lam_rows = plan["rows"]
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


# --------------------------------------------------------------------------- judging windows
def _reel(posted, pulls, **tags):
    return {"tags": {"post_type": "reel", "posting_time": posted, "length": 50, **tags},
            "pulls": {k: {"metrics": v} for k, v in pulls.items()}}


def _m(scale=1.0, saves=4):
    return {"views": int(1000 * scale), "reach": int(800 * scale), "shares": 4 * scale, "saves": saves * scale,
            "skip_rate": 64, "avg_watch_time_ms": 12000}


def test_judging_windows_pending_provisional_final():
    store = empty_store()
    store["reels"]["young"] = _reel("2026-11-12T16:30:00", {"48h": _m()})            # ~31 h old: ignored
    store["reels"]["early"] = _reel("2026-11-09T16:30:00", {"48h": _m(), "72h": _m()})   # provisional
    store["reels"]["done"] = _reel("2026-11-01T16:30:00", {"48h": _m(), "72h": _m(), "7d": _m(1.4)})  # final
    store["reels"]["other"] = _reel("2026-10-20T16:30:00", {"7d": _m(0.8)})
    store["reels"]["story"] = {"tags": {"post_type": "story", "posting_time": "2026-11-12T09:00:00"},
                               "pulls": {"48h": {"metrics": {"reach": 300, "views": 340}}}}
    pb, posts, fits = fits_for(store, today=date(2026, 11, 13))
    by = {p["id"]: p for p in posts}
    assert by["young"]["status"] == "pending" and by["young"]["score"] is None
    assert by["early"]["status"] == "provisional" and by["early"]["pull"] == "72h" and by["early"]["judge_weight"] == 0.5
    assert by["done"]["status"] == "final" and by["done"]["pull"] == "7d" and by["done"]["judge_weight"] == 1.0
    assert by["story"]["status"] == "final"
    assert fits["judged"] == 4 and fits["provisional"] == 1 and fits["final"] == 3   # each post once
    assert by["done"]["score"] > 0     # its 7d numbers replaced the provisional 72h read


def test_metric_exception_drops_saves_from_a_provisional_score():
    store = empty_store()
    store["reels"]["a"] = _reel("2026-10-01T16:30:00", {"7d": _m()})
    store["reels"]["b"] = _reel("2026-10-05T16:30:00", {"7d": _m()})
    store["reels"]["c"] = _reel("2026-11-09T16:30:00", {"72h": _m(saves=40)})
    state = S.empty_state()
    win = copy.deepcopy(json.loads((PLAYBOOK / "policies.json").read_text())["policies"]["judging"]["reel"])
    win["exceptions"] = {"saves": {"ignore_before_hours": 72, "provisional_hours": 168, "provisional_weight": 1,
                                   "final_hours": 168, "evidence": {"level": "opinion", "sources": ["test"]}}}
    state["judging"] = {"reel": win}
    for st, has_saves in ((S.empty_state(), True), (state, False)):
        pb, posts, _ = fits_for(store, st, today=date(2026, 11, 13))
        c = next(p for p in posts if p["id"] == "c")
        c["goal"] = "saves"
        S.score_posts(posts, pb)
        assert ("saves" in c["components"]) is has_saves


def test_brief_lists_provisional_posts_and_validates(sim, tmp_path):
    _, store, state = sim
    m, st = tmp_path / "metrics.json", tmp_path / "strategy.json"
    m.write_text(json.dumps(store))
    st.write_text(json.dumps(state))
    plan = tmp_path / "plan.json"
    assert run("plan", "--month", "2026-03", "--metrics", m, "--state", st, "--today", "2026-03-29", "--out", plan).returncode == 0
    notes = tmp_path / "notes.txt"
    notes.write_text("Contrast hooks lead; keep the Tuesday carousel.\n")
    out, md = tmp_path / "brief.json", tmp_path / "brief.md"
    r = run("brief", "--plan", plan, "--metrics", m, "--state", st, "--today", "2026-03-29", "--week", "2026-03-23",
            "--out", out, "--md", md, "--notes", notes)
    assert r.returncode == 0, r.stderr
    b = json.loads(out.read_text())
    assert nc.schema_errors("strategy_brief.schema.json", b) == []
    assert b["week_of"] == "2026-03-23" and len(b["slots"]) == 7
    assert b["provisional"] and all(p["weight"] == 0.5 for p in b["provisional"])
    assert b["data"]["provisional_posts"] == len(b["provisional"])
    assert b["strategist_notes"].startswith("Contrast hooks lead")
    assert any(u["id"] == "contrast-visual" for u in b["use_patterns"])
    text = md.read_text()
    for head in ("## This week", "## Still provisional", "## Do more of", "## Why", "## Strategist notes"):
        assert head in text
    notes.write_text("Plunging cures stress.")
    r = run("brief", "--plan", plan, "--metrics", m, "--state", st, "--today", "2026-03-29", "--notes", notes)
    assert r.returncode == 1 and "banned claim" in r.stderr


def test_diagnose_matches_the_table():
    store = empty_store()
    for i in range(6):
        d = date(2026, 10, 1) + timedelta(days=3 * i)
        store["reels"][f"ok{i}"] = _reel(f"{d.isoformat()}T16:30:00", {"7d": _m()}, series="regulate")
    store["reels"]["weak"] = _reel("2026-10-25T16:30:00", {"7d": {**_m(0.6), "skip_rate": 78, "shares": 0.5}}, series="regulate")
    pb, posts, fits = fits_for(store, today=date(2026, 11, 13))
    diag = S.recent_diagnoses(posts, pb)
    assert diag and diag[0]["post"] == "weak"
    ids = {r["id"] for r in diag[0]["rows"]}
    assert {"skip-above-median", "sends-low"} <= ids
    planner_bonus = S.Planner(pb, fits, 2026, 12, 1, [], {}, posts, diag).diagnosis_bonus()
    assert planner_bonus[("regulate", "contrast-visual")] > 0


# --------------------------------------------------------------------------- import-research (R349)
def test_import_research_fixtures(tmp_path):
    st = tmp_path / "strategy.json"
    files = [FIXTURES / "R1 Hooks.md", FIXTURES / "R3 Script structures.md", FIXTURES / "R2 Formats and mix.md"]
    r = run("import-research", *files, "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert set(rep["added"]) == {"steam-reveal", "cold-plunge-pov", "three-beat-explainer"}
    assert "contrast-visual" in rep["merged"]
    assert any("detox-hook" in x for x in rep["rejected"])
    assert any("Feels off" in x for x in rep["rejected"])
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    by = {p["id"]: p for p in state["patterns"]}
    steam = by["steam-reveal"]
    assert steam["kind"] == "hook" and steam["status"] == "candidate" and steam["origin"] == "research"
    assert steam["evidence"]["level"] == "observed" and "https://example.org/steam-study" in steam["evidence"]["sources"]
    assert steam["try_instead"] == ["contrast-visual", "seasonal-weather"]
    assert set(steam["formats"]) == {"reel", "trial_reel", "story"}
    assert by["three-beat-explainer"]["kind"] == "structure" and by["three-beat-explainer"]["length_s"] == [45, 60]
    cv = by["contrast-visual"]
    assert cv["status"] == "testing" and cv["evidence"]["level"] == "observed"    # merge never upgrades or changes status
    assert "https://example.org/hooks-2026" in cv["evidence"]["sources"]
    for p in state["patterns"]:
        for ex in p["examples"]:
            assert not claims_scan.has_fail(claims_scan.scan_text(ex))
    assert {d["metric"] for d in state["diagnosis"]} == {"skip_rate", "saves_per_1k_reach", "profile_visits"}
    assert {p["level"]: p["value"] for p in state["priors"]} == {"reel": 0.65, "carousel": 0.3}
    assert state["rules"][0]["topic"] == "cadence" and state["rules"][0]["evidence"]["level"] == "measured"
    # importing again adds nothing new
    r = run("import-research", files[0], "--state", st, "--today", "2026-11-14", "--json")
    assert json.loads(r.stdout)["added"] == []
    assert len(json.loads(st.read_text())["patterns"]) == len(state["patterns"])
    assert run("validate", "--state", st).returncode == 0


def test_import_never_overwrites_numa_results(tmp_path):
    st = tmp_path / "strategy.json"
    state = S.empty_state()
    state["status_overrides"]["contrast-visual"] = {"status": "retired", "since": "2026-10-01", "why": "lost on NUMA's data",
                                                    "n": 9, "mean": -0.3, "prob_better": 0.05}
    st.write_text(json.dumps(state))
    assert run("import-research", FIXTURES / "R1 Hooks.md", "--state", st, "--today", "2026-11-13").returncode == 0
    after = json.loads(st.read_text())
    assert after["status_overrides"]["contrast-visual"]["status"] == "retired"
    pb = S.load_playbook(None, after)
    assert pb["patterns"]["contrast-visual"]["status"] == "retired"


def test_import_r7_judging_windows(tmp_path):
    st = tmp_path / "strategy.json"
    r = run("import-research", FIXTURES / "R7 Judging windows.md", "--state", st, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert any("story" in x and "under 24 h" in x for x in rep["rejected"])
    state = json.loads(st.read_text())
    assert nc.schema_errors("playbook.schema.json", state) == []
    j = state["judging"]
    assert set(j) == {"reel", "trial_reel", "carousel", "image"}
    assert j["reel"]["ignore_before_hours"] == 24 and j["reel"]["provisional_hours"] == 48
    assert j["reel"]["provisional_weight"] == 0.4 and j["reel"]["final_hours"] == 168          # "7 d" = 168 h
    assert j["reel"]["evidence"]["level"] == "measured" and j["reel"]["evidence"]["sources"] == ["https://example.org/accumulation"]
    assert j["reel"]["origin"] == "research" and "compare 48 h" in j["reel"]["how_to_verify"]
    assert j["reel"]["exceptions"]["saves"]["final_hours"] == 168
    assert j["carousel"]["exceptions"]["shares"]["provisional_hours"] == 168
    pb = S.load_playbook(None, state)
    assert pb["policies"]["judging"]["reel"]["provisional_hours"] == 48
    assert pb["policies"]["judging"]["story"]["final_hours"] < 24    # the seed Story window stays
    store = empty_store()
    store["reels"]["x"] = _reel("2026-11-10T16:30:00", {"48h": _m()})    # 48 h pull now counts as provisional
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
    may = {m["id"]: m for m in S.month_moments(pb, 2026, 5)}
    assert may["memorial-day"]["dates"] == ["2026-05-25"]


def test_strategy_arm_round_trip():
    arm = {"type": "carousel", "pillar": "education", "series": None, "day": "Tue", "band": "late_afternoon",
           "hook": "contrast-visual", "structure": "carousel-comparison", "offer_week": None, "goal": "saves",
           "mode": "exploit", "plan": "2026-12"}
    text = S.format_arm(arm)
    assert text.startswith("type=carousel;pillar=education;series=;day=Tue")
    assert S.parse_arm(text) == arm


def test_score_cli_and_missing_metrics(tmp_path):
    store = empty_store()
    store["reels"]["a"] = _reel("2026-10-01T16:30:00", {"7d": {"views": 900, "reach": 700}})
    store["reels"]["b"] = _reel("2026-10-03T16:30:00", {"7d": {"views": 1200, "reach": 900, "shares": 3}})
    store["reels"]["c"] = {"tags": {"post_type": "image", "posting_time": "not a date"}, "pulls": {"7d": {"metrics": {"reach": 400}}}}
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(store))
    r = run("score", "--metrics", m, "--today", "2026-11-13", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert {p["id"] for p in rep["posts"]} == {"a", "b", "c"}
    assert "WARN:" in r.stderr and "Traceback" not in r.stderr


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
    for pid in re.findall(r"`([a-z]+(?:-[a-z0-9]+)+)`", text):
        if pid in ("needs-katie",):
            continue
        assert pid in S.load_playbook()["patterns"] or pid in {d["id"] for d in S.load_playbook()["diagnosis"]}, pid
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
    for must in ("tools not visible", "Jude", "never computes", "provisional", "strategy_brief.json"):
        assert must.lower() in text.lower(), must
