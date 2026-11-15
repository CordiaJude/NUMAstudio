"""v2.1 wiring across commands, agents, skills, config and docs (T16).

Covers: the approval re-check (DECISIONS D26), Story capture timing (the 12-22 h window, simulated
against metrics.py `due`), the strategy steps (R344-R350), the post types (R336), the people rules
(D25) and the owners' wording rules (no "NUMA" in user-facing text, no emojis, no cloned voices, no
lawyer gate, Clinical Conversations never promoted).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CMD = REPO / "commands"
AGENTS = REPO / "agents"
SKILLS = REPO / "skills"
SCHEDULED = REPO / "docs" / "SCHEDULED_TASKS.md"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


def _all_tasks(config) -> dict:
    return {t["id"]: t for t in config["schedule"]["tasks"] + config["schedule"].get("extra_tasks", [])}


# ---------------------------------------------------------------------------
# Story capture timing
# ---------------------------------------------------------------------------
def _daily_minutes(cron: str) -> int:
    minute, hour, dom, month, dow = cron.split()
    assert dom == month == dow == "*" and minute.isdigit() and hour.isdigit(), f"not a daily cron: {cron}"
    return int(hour) * 60 + int(minute)


def test_story_pull_runs_leave_no_gap_longer_than_the_window(config):
    sp = config["schedule"]["story_pulls"]
    lo, hi = sp["window_hours"]
    assert (lo, hi) == (12, 22) and sp["insights_expire_hours"] == 24
    tasks = _all_tasks(config)
    assert set(sp["pull_runs"]) == {"build_today", "story_pulls", "night_check", "dashboard_refresh"}
    times = sorted(_daily_minutes(tasks[t]["cron"]) for t in sp["pull_runs"])
    gaps = [(b - a) for a, b in zip(times, times[1:])] + [times[0] + 1440 - times[-1]]
    assert max(gaps) < (hi - lo) * 60, gaps
    assert max(gaps) / 60 == pytest.approx(sp["max_gap_hours"], abs=0.01)
    assert tasks["story_pulls"]["where"] == "cloud" and tasks["story_pulls"]["command"] == "/dashboard-refresh stories"
    # without the midday task the 5 am -> 8 pm gap (15 h) would lose Stories
    without = sorted(_daily_minutes(tasks[t]["cron"]) for t in sp["pull_runs"] if t != "story_pulls")
    gaps2 = [(b - a) for a, b in zip(without, without[1:])] + [without[0] + 1440 - without[-1]]
    assert max(gaps2) > (hi - lo) * 60


def test_every_story_is_pulled_before_24h_whatever_its_posting_time(config, nc):
    """Simulate metrics.py `due` at the four pull runs for a Story posted at every 10 minutes of a day."""
    import metrics

    tasks = _all_tasks(config)
    runs = sorted(_daily_minutes(tasks[t]["cron"]) for t in config["schedule"]["story_pulls"]["pull_runs"])
    central = timezone(timedelta(hours=-6))
    day0 = datetime(2026, 12, 7, tzinfo=central)
    for posted_min in range(0, 1440, 10):
        posted = day0 + timedelta(minutes=posted_min)
        store = {"schema_version": 1, "account": {"daily": {}, "totals": {}},
                 "reels": {"s1": {"tags": {"post_type": "story", "posting_time": posted.isoformat()}, "pulls": {}}}}
        pulled = []
        for day in range(0, 3):
            for m in runs:
                now = day0 + timedelta(days=day, minutes=m)
                if now <= posted:
                    continue
                for item in metrics.due(store, now):
                    age = (now - posted).total_seconds() / 3600
                    pulled.append((item["pull_now"], age))
                    store["reels"]["s1"]["pulls"][item["pull_now"]] = {"pulled_at": now.isoformat(), "metrics": {}}
        assert pulled, f"Story posted at {posted:%H:%M} was never pulled"
        assert all(12 <= age < 24 for _, age in pulled), (posted, pulled)
        assert any(age <= 22 for _, age in pulled), (posted, pulled)


def test_story_pulls_wired_into_the_runs():
    bt, nc_, dr = read("commands/build-today.md"), read("commands/night-check.md"), read("commands/dashboard-refresh.md")
    assert "**Story pulls first (Story capture timing).**" in bt and "`post_type` is `story` only" in bt
    assert "## 7. Story pulls and the approval re-check" in nc_ and "`post_type` is `story` only" in nc_
    assert "**`stories` (the 12:40 pm Story task" in dr and "runlog.py start story_pulls" in dr
    assert "argument-hint" in dr and "stories" in dr.split("---")[1]
    s = SCHEDULED.read_text(encoding="utf-8")
    sec = s[s.find("**Story capture timing.**"):s.find("**Mac settings.**")]
    for needle in ["between 12 h and 22 h", "never after 24 h", "**10 hours** wide", "7 h 40 min",
                   "05:00, 12:40, 20:00 and 22:00", "5:30 pm", "`skip`"]:
        assert needle in sec, needle


# ---------------------------------------------------------------------------
# Approval re-check (DECISIONS D26)
# ---------------------------------------------------------------------------
def test_post_reel_section_13_approval_recheck():
    t = read("commands/post-reel.md")
    sec = t[t.find("## 13. Approval re-check"):]
    assert sec, "post-reel section 13"
    for needle in ["`approvals`", "Download Drive `_Plan/staged/`", "a failed download is never \"absent\"",
                   "`Approved` or `Approved - <name or initials>`", "planned time or at the next slot",
                   "**One notice per run, never one per post.**", "the owners and the social media lead, by role",
                   "`STATE/approval_notices.json`", "A statement, never a question", "`approval_notify`"]:
        assert needle in sec, needle
    assert "No fallback anywhere in this command may publish" in t
    assert "`STATE/staged/<SLUG>.json`" in t and "_Plan/staged/" in t
    assert "approved a plan, not this post" in t                         # approval before staging does not count
    assert "--not-before <posting time - 75 min> --deadline <posting time>" in t   # T17 M4
    assert "do **not** publish and do **not** expire it" in t
    when = t[t.find("## 3. When to post"):t.find("## 4. Publish")]
    for needle in ["**Approved before the planned time:**", "**Approved after the planned time", "**next slot**",
                   "`approval.min_lead_minutes`", "`approval.latest_post_time`", "**Not approved:** nothing is scheduled"]:
        assert needle in when, needle


@pytest.mark.parametrize("rel", ["commands/night-check.md", "commands/dashboard-refresh.md", "commands/chrome-queue.md"])
def test_scheduled_runs_recheck_staged_rows(rel):
    t = read(rel)
    assert "commands/post-reel.md section 13 (`approvals`)" in t, rel
    assert re.search(r"never posts? an unapproved row", t, re.I), rel


def test_approval_config_and_recheck_tasks(config):
    ap = config["approval"]
    tasks = _all_tasks(config)
    assert set(ap["recheck_in"]) <= set(tasks) and set(ap["recheck_in"]) == {
        "night_check", "dashboard_refresh", "story_pulls", "chrome_queue"}
    assert ap["staged_status"] == "Ready to post" and ap["approved_status"][0] == "Approved"
    assert ap["notify_until_approver_named"] == ["the owners", "the social media lead"]
    assert re.fullmatch(r"\d\d:\d\d", ap["latest_post_time"])


@pytest.mark.parametrize("rel", ["commands/build-today.md", "commands/make-reel.md"])
def test_build_and_make_reel_never_post_unapproved(rel):
    t = read(rel)
    assert "never posts an unapproved row" in t or "never post an unapproved row" in t, rel
    assert "Ready to post" in t and "DECISIONS D26" in t


def test_digest_lists_staged_posts_first():
    t = read("commands/digest.md")
    assert "| top | Staged for approval |" in t and "--learned" in t and "--brief" in t
    assert "| 2a | What we learned |" in t and "`STATE/strategy_changes.txt`" in t and "`do_more`" in t


def test_numa_setup_asks_for_the_approval_channel_once():
    t = read("commands/numa-setup.md")
    assert "### Who hears about posts staged for approval: ask once (DECISIONS D26)" in t
    assert "`approval_notify`" in t and "only in `STATE`" in t and "Approved and Posted" in t


# ---------------------------------------------------------------------------
# Strategy steps (R344-R350)
# ---------------------------------------------------------------------------
def test_plan_month_runs_the_strategist_before_scripting():
    t = read("commands/plan-month.md")
    s2, s4 = t.find("## 2. The Strategist plans the month"), t.find("## 4. Scripts and cards")
    assert 0 < s2 < s4
    assert t.find('strategy.py" plan --month YYYY-MM') < s4
    assert "STATE/plans/strategy_YYYY-MM.json" in t and "skills/numa-scriptwriter/ADAPTIVE.md" in t
    assert 'cp "$STATE/plans/strategy_YYYY-MM.json" "$STATE/plans/plan_YYYY-MM.json"' in t


def test_build_today_reads_the_brief_slot_and_tags():
    t = read("commands/build-today.md")
    assert "**Today's brief slot (R350).**" in t and "`STATE/strategy_brief.json` `slots[]`" in t
    assert "`pattern_ids`, `strategy_arm`, `boosted` and `story_frames`" in t
    assert 'metrics.py" tag --store "$STATE/metrics.json" --post <media_id> --tags' in t


def test_dashboard_refresh_pulls_due_and_runs_the_strategist():
    t = read("commands/dashboard-refresh.md")
    assert 'metrics.py" due --store' in t and "`12h` and `22h`" in t and "`48h`, `72h`, `7d`, `14d` and `30d`" in t
    assert "metrics.py ingest --store STORE --post ID --pull LABEL --data INSIGHTS_JSON --pulled-at ISO" in t
    assert t.find("--pulled-at") < t.find("## 5. The Strategist's refresh")
    assert "**strategist** (agents/strategist.md) with job `refresh`" in t


def test_scriptwriter_skill_and_agent_link_adaptive():
    sk = read("skills/numa-scriptwriter/SKILL.md")
    assert "[ADAPTIVE.md](ADAPTIVE.md)" in sk and "## Post types" in sk
    assert "ADAPTIVE.md" in read("agents/scriptwriter.md")


# ---------------------------------------------------------------------------
# Post types (R336)
# ---------------------------------------------------------------------------
def test_post_types_config_matches_scripts(config, nc):
    import metrics
    import shoot_card

    types = config["post_types"]["types"]
    assert {t["id"] for t in types} == {"reel", "trial_reel", "component_carousel", "photo_carousel", "reel_carousel",
                                        "single_photo", "story"}
    assert {t["row_kind"] for t in types} == set(shoot_card.KINDS)
    assert {t["metrics_post_type"] for t in types} == set(metrics.POST_TYPES)
    assert {t["carousel_source"] for t in types if "carousel_source" in t} == set(shoot_card.CAROUSEL_SOURCES)
    assert "post_type" in config["instagram"]["tags"]


def test_post_types_in_build_plan_and_templates():
    bt = read("commands/build-today.md")
    for needle in ["| reel, trial_reel |", "`carousel_source` component", "`carousel_source` photos",
                   "`carousel_source` reel", "| image (a single-photo feed post", "| stories |",
                   'photo_post.py" carousel', 'photo_post.py" single', "**designer**", "`--with-chromium`"]:
        assert needle in bt, needle
    pm = read("commands/plan-month.md")
    for needle in ["`carousel` + `carousel_source: component`", "`carousel` + `carousel_source: photos`",
                   "`image` | Single photo post", "`stories` | Story set"]:
        assert needle in pm, needle
    tpl = json.loads(read("skills/numa-scriptwriter/templates.json"))
    assert {t["id"] for t in tpl["post_types"]} == {"component_carousel", "photo_carousel", "reel_carousel",
                                                    "single_photo", "story_set"}


def test_post_type_copy_passes_claims(nc):
    import claims_scan as cs

    for t in json.loads(read("skills/numa-scriptwriter/templates.json"))["post_types"]:
        hits = [h for h in cs.scan_text(json.dumps(t, ensure_ascii=False), where=t["id"]) if h.severity == "fail"]
        assert not hits, [h.line() for h in hits]


def test_post_reel_rerenders_canvas_carousels_before_posting():
    t = read("commands/post-reel.md")
    sec = t[t.find("**0. Component carousel: re-render the canvas"):t.find("**1. The slides.**")]
    assert "DECISIONS D21" in sec and 'design_render.py" canvas' in sec and "--with-chromium" in sec
    assert "fallback carousel.3" in sec and "`SLUG_carousel_NN.jpg`" in sec


# ---------------------------------------------------------------------------
# People rules (D25)
# ---------------------------------------------------------------------------
def test_librarian_people_rules():
    t = read("agents/librarian.md")
    sec = t[t.find("## 5. People rules"):t.find("## 6. End of run")]
    for needle in ["`do_not_feature`", "`one_existing_post_only`", "A child", "`consent.never_film`",
                   "not even blurred", "never copy a name"]:
        assert needle in sec, needle


@pytest.mark.parametrize("rel", ["commands/post-reel.md", "agents/designer.md", "agents/critic.md", "agents/scout.md"])
def test_photo_flows_honour_people_json(rel):
    t = read(rel)
    assert "people.json" in t and "one_existing_post_only" in t, rel


# ---------------------------------------------------------------------------
# Owners' wording rules (T19 leftovers, D25)
# ---------------------------------------------------------------------------
INSTRUCTION_FILES = sorted(p.relative_to(REPO).as_posix() for p in
                           list(CMD.glob("*.md")) + list(AGENTS.glob("*.md")) + list(SKILLS.glob("*/SKILL.md")))
# Allowed: the plugin's name, Drive folder and Sheet names, env vars, and the rule that names the banned spelling.
ALLOWED_CAPS = re.compile(r'NUMA(?= Studio| Reels| 30-Day| Reel Metrics|_)|"NUMA"|never NUMA|Never: NUMA|any "NUMA"|never "NUMA"')
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2705\u274C]")


@pytest.mark.parametrize("rel", INSTRUCTION_FILES)
def test_no_user_facing_numa_or_emoji(rel):
    if rel == "commands/brand-setup.md":
        pytest.skip("the questionnaire quotes the owners' original questions verbatim (docs/QUESTIONS_FOR_KATIE.md)")
    text = ALLOWED_CAPS.sub("", read(rel))
    assert not re.findall(r"\bNUMA\b", text), rel
    assert not EMOJI.search(read(rel)), rel


@pytest.mark.parametrize("rel", INSTRUCTION_FILES)
def test_no_clone_voice_lawyer_gate_or_cancelled_event(rel):
    if rel == "commands/brand-setup.md":
        pytest.skip("the questionnaire quotes the owners' original questions verbatim")
    for line in read(rel).splitlines():
        low = line.lower()
        if "clone" in low:
            assert re.search(r"never|no cloned|non-cloned|not cloned|clone_allowed|stay false|never a clone", low), (rel, line)
        if "lawyer" in low or "legal review" in low or "legal-review" in low:
            assert re.search(r"dropped|no lawyer|not a lawyer|skip|waived|replaces", low), (rel, line)
        if "clinical conversations" in low:
            assert "cancel" in low, (rel, line)
        assert "finnish sauna" not in low and "14-person" not in low, (rel, line)


@pytest.mark.parametrize("rel", ["commands/make-reel.md", "agents/motion.md", "skills/numa-reel-editor/SKILL.md",
                                 "commands/night-check.md"])
def test_voice_fallback_matches_d25(rel):
    t = read(rel)
    assert "voice.generic_ai_allowed" in t and "on-screen text" in t, rel
    assert "consent.voice_clone` is true" not in t and "cloned voice, **only** when" not in t, rel


def test_critic_g5_spells_numa():
    t = read("agents/critic.md")
    g5 = next(line for line in t.splitlines() if line.startswith("| G5 |"))
    assert "Discover Numa $49" in g5 and 'always "Numa" on screen' in g5 and "Discover NUMA" not in g5
    rs = read("skills/numa-reel-editor/SKILL.md")
    assert "Discover NUMA" not in rs and "Discover Numa" in rs


def test_readme_names_the_v21_parts():
    t = read("README.md")
    for needle in ["`designer`", "numa-carousel", "design_render.py", "tools/gen_carousel_components.py",
                   "NUMA_DC_RUNTIME", "NUMA_BRAND_FONTS", "NUMA_BRAND_LOGO", "photo_post.py", "`strategist`",
                   "strategy.py", "/chrome-queue", "NUMA_STATE", "NUMA_CACHE", "ensure_env.py", "runlog.py",
                   "chrome_queue.py", "Version 2.1.0"]:
        assert needle in t, needle
    assert "legal-review gate" not in t


def test_ci_installs_chromium():
    ci = read(".github/workflows/ci.yml")
    assert ci.count("python -m playwright install --with-deps chromium") >= 2
