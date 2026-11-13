"""Instruction-layer checks for the 30-day content system (T9).

Covers commands/{plan-month,night-check,build-today,digest,trend-check,dashboard-refresh}.md,
agents/scriptwriter.md, skills/numa-scriptwriter/SKILL.md + templates.json and docs/SCHEDULED_TASKS.md:

* frontmatter: commands run on the Director's tier, the scriptwriter on its tier
  (config/studio.json `models.agents`), explicit minimal tools;
* every script they call exists and every flag they pass is defined by that script's argparse;
* every brand.json / config key path they cite resolves;
* required sections and rows per requirement (R154-R195, R238-R242, R252, R261-R264);
* the template library data (R192, R193) and the fields the planner needs (R194);
* the scheduled-task doc agrees with config `schedule` (R261, R262);
* the R119 lint (no question to Katie, no confirm step) on every owned file.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"

COMMANDS = ["plan-month", "night-check", "build-today", "digest", "trend-check", "dashboard-refresh"]
OWNED = {c: REPO / "commands" / f"{c}.md" for c in COMMANDS}
OWNED["scriptwriter"] = REPO / "agents" / "scriptwriter.md"
OWNED["skill"] = REPO / "skills" / "numa-scriptwriter" / "SKILL.md"
SCHEDULED = REPO / "docs" / "SCHEDULED_TASKS.md"
TEMPLATES = REPO / "skills" / "numa-scriptwriter" / "templates.json"
CORE_TOOLS = {"Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Task"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: no frontmatter"
    end = text.find("\n---", 4)
    assert end > 0, f"{path.name}: frontmatter not closed"
    data = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        assert sep, f"{path.name}: bad frontmatter line {line!r}"
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def code_segments(text: str) -> list[str]:
    out, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append(line)
        else:
            out.extend(re.findall(r"`([^`\n]+)`", line))
    return out


def script_calls(text: str) -> list[tuple[str, str | None, list[str]]]:
    """(script, subcommand or None, flags) for every `<name>.py` in code."""
    calls = []
    for seg in code_segments(text):
        parts = re.split(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b", seg)
        for i in range(1, len(parts), 2):
            tail = parts[i + 1] if i + 1 < len(parts) else ""
            sub = re.match(r'"?\s+([a-z][a-z-]+)\b', tail)
            flags = re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", tail)
            calls.append((parts[i], sub.group(1) if sub else None, flags))
    return calls


def prose_calls(text: str) -> list[tuple[str, list[str]]]:
    """(script, flags) for prose sentences that name one script and backtick a flag ("Pass `--x` to a.py")."""
    calls, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for sentence in re.split(r"(?<=[.;])\s+", line):
            scripts = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b", sentence))
            flags = re.findall(r"`[^`]*?(?<![\w-])(--[a-z][a-z0-9-]*)[^`]*`", sentence)
            if len(scripts) == 1 and flags:
                calls.append((scripts.pop(), flags))
    return calls


# Flags a later task adds (DECISIONS D14: T12 adds baseline_plan.py --template). The integration task empties this.
PENDING_FLAGS = {("baseline_plan.py", "--template"): "T12 adds --template (DECISIONS D14)"}


def argparse_flags(script: Path) -> set[str]:
    return set(re.findall(r"""["'](--[a-z][a-z0-9-]*)["']""", script.read_text(encoding="utf-8")))


def subcommands(script: Path) -> set[str]:
    return set(re.findall(r"""add_parser\(\s*["']([a-z][a-z-]*)["']""", script.read_text(encoding="utf-8")))


def resolve(data, dotted: str) -> bool:
    node = data
    for part in dotted.split("."):
        while isinstance(node, dict) and part not in node and isinstance(node.get("value"), dict):
            node = node["value"]
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text[text.find("\n---", 4) + 4:]


@pytest.fixture(scope="module")
def brand():
    return json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def texts():
    return {k: p.read_text(encoding="utf-8") for k, p in OWNED.items()}


@pytest.fixture(scope="module")
def templates():
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cmd", COMMANDS)
def test_command_frontmatter(cmd, config):
    fm = frontmatter(OWNED[cmd])
    assert fm.get("description") and fm.get("argument-hint")
    assert fm.get("model") == config["models"]["agents"]["director"], f"{cmd} runs as the Director (top tier)"


def test_scriptwriter_agent_frontmatter(config):
    fm = frontmatter(OWNED["scriptwriter"])
    assert fm["name"] == "scriptwriter" and fm["description"]
    assert fm["model"] == config["models"]["agents"]["scriptwriter"] == config["models"]["tiers"]["mid"]
    tools = [t.strip() for t in fm["tools"].split(",")]
    assert tools and len(tools) == len(set(tools)) and set(tools) <= CORE_TOOLS
    assert "Bash" in tools and "WebSearch" not in tools  # writes and runs checks; research is the scout's job


def test_skill_frontmatter():
    fm = frontmatter(OWNED["skill"])
    assert fm["name"] == "numa-scriptwriter"
    d = fm["description"].lower()
    assert "/plan-month" in d and "help me plan a reel for numa nights" in d and "claims" in d  # R186


# ---------------------------------------------------------------------------
# scripts, flags, key paths
# ---------------------------------------------------------------------------
def test_scripts_and_flags_exist(texts):
    seen = set()
    for name, text in texts.items():
        for script, sub, flags in script_calls(text):
            path = SCRIPTS / script
            assert path.exists(), f"{name}: calls missing script {script}"
            subs = subcommands(path)
            if subs and sub and not sub.startswith("-"):
                assert sub in subs, f"{name}: {script} has no subcommand {sub!r}"
            known = argparse_flags(path)
            for f in flags:
                assert f in known or (script, f) in PENDING_FLAGS, f"{name}: {script} has no flag {f}"
            seen.add(script)
        for script, flags in prose_calls(text):
            path = SCRIPTS / script
            assert path.exists(), f"{name}: names missing script {script}"
            for f in flags:
                assert f in argparse_flags(path) or (script, f) in PENDING_FLAGS, f"{name}: {script} has no flag {f} (prose)"
    assert {"shoot_card.py", "digest_data.py", "metrics.py", "dashboard.py", "ledger.py", "prefs.py",
            "library.py", "claims_scan.py", "formats.py"} <= seen


def test_prose_flag_detection():
    assert prose_calls("Pass `--template` from the row to baseline_plan.py.") == [("baseline_plan.py", ["--template"])]
    assert prose_calls("Run `baseline_plan.py --nope X` today.") == [("baseline_plan.py", ["--nope"])]
    assert prose_calls("No flags for engine.py here.") == []


def test_pending_flags_are_referenced(texts):
    used = {(s, f) for t in texts.values() for s, _, fl in script_calls(t) for f in fl}
    used |= {(s, f) for t in texts.values() for s, fl in prose_calls(t) for f in fl}
    for key in PENDING_FLAGS:
        assert key in used or key[1] in argparse_flags(SCRIPTS / key[0]), f"stale PENDING_FLAGS entry {key}"


def test_shoot_card_subcommands_used(texts):
    calls = [(s, sub) for t in texts.values() for s, sub, _ in script_calls(t) if s == "shoot_card.py"]
    assert {sub for _, sub in calls} >= {"month", "card", "check", "script", "sheet"}


KEY_RE = re.compile(r"(brand\.json|config(?:/studio\.json)?)\s+`([a-z_][a-z0-9_.]*)`")


def test_key_paths_resolve(texts, brand, config):
    n = 0
    for name, text in texts.items():
        for src, key in KEY_RE.findall(text):
            data = brand if src == "brand.json" else config
            assert resolve(data, key), f"{name}: {src} key {key!r} does not resolve"
            n += 1
    assert n >= 30
    for key in ["drive.plan_sheet", "drive.digests", "drive.music_library", "drive.music_naming", "drive.day_folder",
                "drive.month_folder", "drive.shoot_card", "drive.metrics_sheet", "closures.location", "closures.known",
                "positioning.collab_partners", "positioning.series", "positioning.content_mix", "team.collective",
                "offerings.offers", "offerings.events", "posting.digest_destination", "posting.music_rule",
                "consent.voice_clone", "escalation.contact", "business.cta_link"]:
        assert resolve(brand, key), key
    for key in ["schedule.tasks", "schedule.timezone", "instagram.graph_api_version", "instagram.never_request",
                "instagram.metrics", "instagram.judge_at_hours", "instagram.tools.media_insights",
                "instagram.tools.user_insights", "budget.split", "budget.pacing", "budget.max_credits_per_reel",
                "render.words_per_second", "render.outro_music_only_s", "render.length_s"]:
        assert resolve(config, key), key


# ---------------------------------------------------------------------------
# required content per requirement
# ---------------------------------------------------------------------------
def test_plan_month(texts):
    t = texts["plan-month"]
    for needle in [
        "Nobody approves the plan", "Never ask Katie",                             # R154
        "Offers and prices", "Class schedule and events", "Closures and holidays",  # R155
        "Last month's results", "Season and Mobile local moments", "Credit budget", "scout", "WebSearch",
        "Mardi Gras", "hurricane", "New Year",
        "Day, Date, Title, Goal, Template, Hook (first 2 seconds), Voiceover script, Shot list, "
        "Music mood + BPM, Call to action, Status, Folder link, Reel link",          # R156
        "Planned", "Ready to build", "Ready to post", "Posted",
        "photos/", "clips/", "Finished/", "SHOOT CARD", "script.json",              # R157
        "4-5 feed posts", "1-2 Trial Reels", "never a week dark",                    # R160
        "30/25/15/15/15", "30 or more", "posting hours", "re-tune",                 # R161, R170, R252
        "| Mon | Ask the DPT reel, 45-60 s |", "| Sun | Regulate reel or Stories |",  # R162
        "late afternoon Central", "72 h",                                           # R163
        "No topic repeats within 14 days", "at most one sales-focused reel a week",  # R164
        "growth reels 45-60 s", "never a repost",                                   # R165
        "one Meet the Collective feature a month",                                  # R166
        "trend-check swaps in weather hooks",                                       # R167
        "signature transformation", "teaser 2-3 days before", "recap within 2 days",  # R168
        "one or two short sessions",                                                # R169
        "Mission Fitness first", "Sweat there, recover here",                        # R172
        "filmed once", "library_tags",                                              # R182
        "read back to back", "named by day number",                                 # R183
        "capture moment", "`during`",                                               # R184
        "failure table on the night check, never a reminder",                       # R185
        "all in one pass", "scriptwriter",                                          # R186
        "prefs.py\" add",                                                           # R252 edit rules
        "digest_notes.json",                                                        # changes listed in the digest
        "credits_planned", "budget.split",                                          # credit split per day
    ]:
        assert needle in t, needle
    order = ["## 1. Gather inputs", "## 2. Re-weight", "## 3. The skeleton", "## 4. Scripts and cards",
             "## 5. Batch the shoot", "## 6. Credits per day", "## 7. Check until clean", "## 8. Write Drive"]
    pos = [t.find(h) for h in order]
    assert -1 not in pos and pos == sorted(pos)


def test_night_check(texts):
    t = texts["night-check"]
    for needle in ["8 pm", "librarian", "scout", "Claude in Chrome", "web search", "library.py\" query",
                   "scriptwriter", "swap", "heads-up", "never a question", "Ready to build",
                   "voiceover NN", "never a reminder", "F16", "F1", "shoot_card.py\" check",
                   "Nothing for you to do", "digest_notes.json"]:
        assert needle in t, needle


def test_build_today(texts):
    t = texts["build-today"]
    for needle in ["5 am", "commands/make-reel.md", "Folder link", "plan_row.json", "Ready to post", "Posted",
                   "--template", "carousel", "stories", "formats.py", "Trial Reel", "notification", "F13", "F15",
                   "never ask Katie anything"]:
        assert needle in t, needle


def test_digest(texts):
    t = texts["digest"]
    for needle in ["6 pm", "never asks a question", "two minutes", 'digest_data.py" --metrics', "--plan-rows",
                   "--ledger", "--notes", "_Plan/Digests/", "Google Doc", "notification", "email",
                   "thumbnail", "why you think it worked", "by room", "total time estimate", "credits used and left",
                   "Claude usage", "Days swapped", "Scout found", "skipped"]:
        assert needle in t, needle
    rows = re.findall(r"^\| (\d) \| ([^|]+)\|", t, re.M)
    assert [r[0] for r in rows] == list("123456")                                           # R239: six sections
    assert [r[1].strip() for r in rows] == ["Last week", "What changed", "This week", "This week's shoot list",
                                            "Budget", "Heads-ups"]


def test_trend_check(texts):
    t = texts["trend-check"]
    for needle in ["7 pm", "Fridays", "scout", "web search", "formats, hooks, editing styles and topics, never songs",
                   "Sound Collection", "three ideas", "example_link", "why_it_fits", "how_with_numa",
                   "motion transfer", "Trial Reel", "may slot", "7-day forecast", "cold snap", "Heat wave", "Storm",
                   "Sauna season in Mobile", "competitor log"]:
        assert needle.lower() in t.lower(), needle


def test_dashboard_refresh(texts):
    t = texts["dashboard-refresh"]
    for needle in ['metrics.py" due', 'metrics.py" ingest', 'metrics.py" compute', 'metrics.py" account',
                   'metrics.py" tag', 'dashboard.py"', "graph_api_version", "instagram.graph_api_version",
                   "Never request plays or impressions", "INSTAGRAM_GET_IG_MEDIA_INSIGHTS",
                   "INSTAGRAM_GET_USER_INSIGHTS", "republish", "same dashboard artifact", "NUMA Reel Metrics",
                   "Do more of / Do less of", "Meta error 190", "10 pm"]:
        assert needle in t, needle


def test_scriptwriter_skill(texts):
    t = texts["skill"]
    for needle in [
        "first 2 seconds", "2.3 x (`length_s` - `outro_s`)", "65-70 words", "6-8 s",          # R187
        "one short sentence per story beat",
        "numbered, each tied to a line", "framing", "exactly one `ai_motion`",                # R188
        "Photos", "Audio direction", "mood and tempo",
        "On-screen text and CTA", "numa-caption", "hashtags",                                  # R189
        "at most 8 new shots", "consent list only",                                            # R178
        "NO FILMING NEEDED", "IF YOU CAN'T: skip it.", "WHERE TO PUT FILES",                    # R175-R177
        "Claims policy, every line", 'shoot_card.py" script',                                  # R191
        "Missing material", "rewrite only the lines",
        "Month pass", "One-off", "help me plan a reel for Numa Nights",                          # R186
        "growth reels 45-60 s", "never over 3 minutes",                                         # R165
        "templates.json", "Ask the DPT", "guides or facilitators", "No questions to Katie",
    ]:
        assert needle in t, needle
    for tip in ["closet or carpeted bedroom", "12 inches", "normal talking voice", "one take", "1 second of silence"]:
        assert tip in t, tip                                                                    # R190
    assert "words_per_second" in t and "outro_music_only_s" in t


def test_scriptwriter_agent(texts):
    t = texts["scriptwriter"]
    for needle in ["numa-scriptwriter/SKILL.md", "Month pass", "Rewrite", "One-off", 'shoot_card.py" script',
                   'shoot_card.py" card', "never contact Katie", "models.agents.scriptwriter"]:
        assert needle in t, needle


def test_skill_example_passes_the_checker(texts, tmp_path):
    import shoot_card as sc

    m = re.search(r"## Worked example.*?```json\n(.*?)```", texts["skill"], re.S)
    s = json.loads(m.group(1))
    errs, _ = sc.script_problems(s, sc.load_templates(), where="SKILL example")
    assert errs == []


# ---------------------------------------------------------------------------
# template library (R192, R193, R194 data shape)
# ---------------------------------------------------------------------------
TEMPLATE_IDS = ["transformation", "class_spotlight", "member_story", "modality_explainer", "offer_promo",
                "event_recap", "event_teaser", "behind_the_scenes", "founder_message", "myth_vs_fact",
                "seasonal_holiday"]
PRESET_NAMES = ["Numa Nights recap", "Class spotlight", "Member story", "Offer promo: Discover NUMA",
                "Education: 3 things, with kinetic type", "Holiday hours"]
FIELDS = ["id", "name", "kind", "what", "example_hook", "arc", "beat_count", "typical_length_s", "default_length_s",
          "length_class", "signature_moment", "turn", "pacing", "look", "transitions", "hook_style", "goal",
          "pillars", "series", "needs", "kinetic_type", "text_cards", "cta_style"]


def test_template_library(templates, brand, config):
    plan_schema = json.loads((REPO / "schemas" / "plan.schema.json").read_text(encoding="utf-8"))
    shot = plan_schema["$defs"]["shot"]["properties"]
    sig_types = set(plan_schema["properties"]["signature"]["properties"]["type"]["enum"])
    trs, looks = set(shot["tr"]["enum"]), set(shot["look"]["enum"])
    series = {s["id"] for s in brand["positioning"]["series"]["value"]}
    pillars = set(brand["positioning"]["content_mix"]["value"])
    assert [t["id"] for t in templates["templates"]] == TEMPLATE_IDS
    assert [p["name"] for p in templates["presets"]] == PRESET_NAMES
    ids = [t["id"] for t in templates["templates"] + templates["presets"]]
    assert len(ids) == len(set(ids))
    lr = config["render"]["length_s"]
    for t in templates["templates"] + templates["presets"]:
        for f in FIELDS:
            assert f in t, f"{t['id']}: missing {f}"
        assert t["kind"] == ("template" if t in templates["templates"] else "preset")
        assert t["beat_count"] == len(t["arc"]) >= 4 and t["arc"][0]["beat"] == "hook" and t["arc"][-1]["beat"] == "outro"
        lo, hi = t["typical_length_s"]
        assert lr["main_reel"][0] <= lo <= t["default_length_s"] <= hi <= lr["main_reel"][1]
        want = "growth" if lo >= lr["growth"][0] else ("atmosphere" if hi <= lr["atmosphere"][1] else None)
        assert t["length_class"] == want, t["id"]
        assert t["signature_moment"]["type"] in sig_types and 0 < t["signature_moment"]["at"] < 1
        assert t["turn"] is None or 0 < t["turn"]["at"] < 1
        assert set(t["transitions"]) <= trs and t["look"]["default"] in looks
        assert t["look"]["before_turn"] in looks | {None}
        assert t["pacing"]["beats_per_shot"][0] >= 1 and t["pacing"]["beats_per_shot"][1] <= config["render"]["max_shot_beats"]
        assert config["render"]["outro_music_only_s"]["min"] <= t["pacing"]["outro_s"] <= config["render"]["outro_music_only_s"]["max"]
        assert t["goal"] in {"awareness", "offer", "community", "education"}
        assert set(t["series"]) <= series and set(t["pillars"]) <= pillars
        for s in t["series"]:  # a template that serves a series fits that series' length
            rng = next(x["length_s"] for x in brand["positioning"]["series"]["value"] if x["id"] == s)
            assert rng is None or (rng[0] <= t["default_length_s"] <= rng[1]), (t["id"], s)
        assert t["kinetic_type"] == bool(t["text_cards"])
    for p in templates["presets"]:
        assert p["base"] in TEMPLATE_IDS
    by_id = {t["id"]: t for t in templates["templates"] + templates["presets"]}
    assert by_id["transformation"]["signature_moment"]["type"] == "wipe" and by_id["transformation"]["look"]["before_turn"] == "before"
    assert by_id["education_three_things"]["kinetic_type"] and by_id["holiday_hours"]["kinetic_type"]
    assert by_id["numa_nights_recap"]["event"] == "Numa Nights"
    assert all(k in templates["_fields"] for k in FIELDS if k not in ("id", "name", "what"))


def test_template_copy_passes_claims():
    import claims_scan as cs

    data = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    for t in data["templates"] + data["presets"]:
        hits = [h for h in cs.scan_text(json.dumps(t, ensure_ascii=False), where=t["id"]) if h.severity == "fail"]
        assert not hits, [h.line() for h in hits]


# ---------------------------------------------------------------------------
# scheduled tasks (R261-R264)
# ---------------------------------------------------------------------------
def test_scheduled_tasks_doc_matches_config(config):
    t = SCHEDULED.read_text(encoding="utf-8")
    tasks = config["schedule"]["tasks"]
    assert len(tasks) == 6 and config["schedule"]["timezone"] == "America/Chicago"
    for task in tasks:
        cmd = task["command"].lstrip("/")
        assert (REPO / "commands" / f"{cmd}.md").exists(), f"no command file for {task['command']}"
        assert f"| {task['name']} | {task['when']} | `CRON_TZ=America/Chicago {task['cron']}` | `{task['command']}` |" in t, task["id"]
        assert re.search(rf"```\nRun {re.escape(task['command'])}\b", t), f"no paste-ready prompt for {task['command']}"
    for needle in ["Keep computer awake", "Run on startup", "Claude in Chrome", "Always allow", "Run now",
                   "Notifications on", "permissions.allow", "Composio", "Higgsfield", "Google Drive", "Gmail"]:
        assert needle in t, needle


def test_command_times_match_config(config, texts):
    words = {"plan_month": "24th", "night_check": "8 pm", "build_today": "5 am", "dashboard_refresh": "10 pm",
             "trend_check": "7 pm", "digest": "6 pm"}
    for task in config["schedule"]["tasks"]:
        cmd = task["command"].lstrip("/")
        assert f"`{task['id']}` scheduled task" in texts[cmd], cmd
        assert words[task["id"]] in texts[cmd], cmd


# ---------------------------------------------------------------------------
# R119: no question to Katie, no confirm step
# ---------------------------------------------------------------------------
def _director_lint():
    spec = importlib.util.spec_from_file_location("_t8_lint", Path(__file__).with_name("test_instructions_director.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.lint_hits


@pytest.mark.parametrize("name", sorted(OWNED))
def test_r119_lint(name, texts):
    hits = _director_lint()(texts[name])
    assert not hits, f"{name}:\n" + "\n".join(hits)


def test_no_confirm_or_approval_steps(texts):
    for name, t in texts.items():
        low = t.lower()
        assert "approve the plan?" not in low and "confirm before" not in low and "reply with" not in low, name
    assert "Nobody approves the plan" in texts["plan-month"]


# ---------------------------------------------------------------------------
# scheduling reliability: bootstrap, run log, watchdog, Chrome queue (R339-R343)
# ---------------------------------------------------------------------------
CHROME_QUEUE_CMD = REPO / "commands" / "chrome-queue.md"
MAKE_REEL = REPO / "commands" / "make-reel.md"
TASK_IDS = {"plan-month": "plan_month", "night-check": "night_check", "build-today": "build_today",
            "dashboard-refresh": "dashboard_refresh", "trend-check": "trend_check", "digest": "digest"}


def _prompts(text: str) -> dict[str, str]:
    """'**N. Name**' heading -> the fenced prompt under it."""
    return {m.group(1): m.group(2) for m in re.finditer(r"\*\*\d\. ([^*]+)\*\*[^\n]*\n```\n(.*?)\n```", text, re.S)}


@pytest.mark.parametrize("cmd", COMMANDS)
def test_every_scheduled_command_logs_and_bootstraps(cmd, texts, config):
    t = texts[cmd]
    task = TASK_IDS[cmd]
    assert task in {x["id"] for x in config["schedule"]["tasks"]}
    sec = t[t.find("## Run start and end"):]
    assert sec and t.find("## Run start and end") < t.find("## 1.")              # first thing the run does
    assert f'runlog.py" start {task} --state "$STATE"' in sec                   # R340
    assert 'ensure_env.py" --json' in sec                                       # R339
    assert 'runlog.py" merge "$STATE/runlog.drive.json"' in sec and 'chrome_queue.py" merge' in sec
    assert 'runlog.py" finish <RUN_ID> --outcome' in sec and f"--task {task}" in sec
    assert "always, also when the run fails" in sec                             # finish on failure too
    assert "escalation channel in `STATE/brand.json`" in sec and "D19" in sec    # env failure: Jude only
    assert "finished in the run log" in t[t.find("## Done means"):]


def test_build_today_bootstrap_flags(texts):
    t = texts["build-today"]
    assert 'ensure_env.py" --json --with-model' in t and "`--with-chromium`" in t and "component carousel" in t
    assert "make-reel skips its own" in t


def test_make_reel_bootstrap_when_run_by_hand():
    t = MAKE_REEL.read_text(encoding="utf-8")
    assert 'runlog.py" start make_reel --state "$STATE"' in t and 'ensure_env.py" --json --with-model' in t
    assert "always, also on failure" in t and 'runlog.py" finish' in t
    assert "from /build-today, skip this paragraph" in t
    assert 'chrome_queue.py" add --kind higgsfield_unlimited' in t


@pytest.mark.parametrize("cmd", ["night-check", "dashboard-refresh"])
def test_watchdog_r341(cmd, texts):
    t = texts[cmd]
    assert "## 6. Watchdog (R341)" in t
    assert 'runlog.py" check --state "$STATE" --json --mark-reported' in t
    assert 'chrome_queue.py" expire' in t
    assert '"new": true' in t and "Jude one line" in t and "Katie gets nothing" in t
    full = texts["night-check"]
    for action in ("`late_build`", "`reschedule`", "`rerun`", "`skip`"):
        assert action in full
    assert "commands/build-today.md" in full and "Reschedule" in full and "before the posting window ends" in full


def test_night_check_final_message_stays_katies(texts):
    t = texts["night-check"]
    sec = t[t.find("## 6. Watchdog"):t.find("## Done means")]
    assert "before the run's final message" in sec and "never goes in this run's final message" in sec


def test_digest_shows_run_health(texts):
    t = texts["digest"]
    assert 'runlog.py" summary --week --state "$STATE" --json' in t
    assert 'chrome_queue.py" list --status expired' in t
    heads = re.search(r"^\| 6 \| Heads-ups \|(.*)$", t, re.M).group(1)
    assert "run health" in heads and "nothing for you to do" in heads
    assert "Jude-only footer" in t and "never into Katie's text" in t


@pytest.mark.parametrize("cmd", ["plan-month", "night-check", "trend-check", "build-today"])
def test_chrome_steps_check_then_drain_or_queue(cmd, texts):
    t = texts[cmd]
    assert "**Claude in Chrome (R342).**" in t and "`mcp__claude-in-chrome__*`" in t
    assert "drain the queue first (commands/chrome-queue.md sections 2 and 4)" in t
    if cmd != "build-today":
        assert 'chrome_queue.py" add --kind' in t and "--deadline" in t and "--fallback" in t


def test_queued_payloads_are_json(texts):
    for name, text in {**texts, "make-reel": MAKE_REEL.read_text(encoding="utf-8")}.items():
        for payload in re.findall(r"--payload '([^']*)'", text):
            assert isinstance(json.loads(payload), dict), (name, payload)


def test_competitor_log_queue_and_fallback(texts):
    t = texts["trend-check"]
    assert "--kind competitor_log" in t and "web-search competitor log" in t


def test_plan_month_avoids_unlabelled_ai_people(texts):
    t = texts["plan-month"]
    sec = t[t.find("**AI-animated people (R342).**"):t.find("## 7. Check until clean")]
    for needle in ["cannot be guaranteed", "no AI-label field", "Claude in Chrome", "people-free",
                   "`STATE/setup.json` `verified`", "posting.ai_label_rule"]:
        assert needle in sec, needle


# ---------------------------------------------------------------------------
# commands/chrome-queue.md (the desktop-only drain task)
# ---------------------------------------------------------------------------
def test_chrome_queue_command(config):
    import chrome_queue

    fm = frontmatter(CHROME_QUEUE_CMD)
    assert fm.get("description") and fm.get("argument-hint")
    assert fm.get("model") == config["models"]["agents"]["director"]
    t = CHROME_QUEUE_CMD.read_text(encoding="utf-8")
    order = ["## 1. Run start", "## 2. Expired items first", "## 3. Is Chrome here?", "## 4. Drain the queue",
             "## 5. Late build", "## 6. Run end"]
    pos = [t.find(h) for h in order]
    assert -1 not in pos and pos == sorted(pos)
    for needle in ['runlog.py" start chrome_queue', 'ensure_env.py" --json', 'chrome_queue.py" merge',
                   'chrome_queue.py" expire', 'chrome_queue.py" next', 'chrome_queue.py" done <id> --result',
                   'chrome_queue.py" fail <id> --reason', 'runlog.py" check --state "$STATE" --json',
                   "`late_build`", "`runs` below 2", 'runlog.py" finish <RUN_ID> --outcome',
                   "always, also on failure", "desktop scheduled task", "only while the Mac is awake",
                   "`mcp__claude-in-chrome__*`", "deadline order", "heads_ups", "not_before"]:
        assert needle in t, needle
    rows = re.findall(r"^\| `([a-z_]+)` \|(?:[^|\n]+\|){3}$", t, re.M)        # kind | payload | Chrome | fallback
    assert sorted(rows) == sorted(chrome_queue.KINDS)                              # every kind, with a fallback
    assert "--mark-reported" not in t.replace("do not pass `--mark-reported`", "")


def test_chrome_queue_command_scripts_lint_and_keys(brand, config):
    t = CHROME_QUEUE_CMD.read_text(encoding="utf-8")
    for script, sub, flags in script_calls(t):
        path = SCRIPTS / script
        assert path.exists(), script
        if sub and subcommands(path):
            assert sub in subcommands(path), (script, sub)
        for f in flags:
            assert f in argparse_flags(path), (script, f)
    for src, key in KEY_RE.findall(t):
        assert resolve(brand if src == "brand.json" else config, key), key
    assert resolve(config, "higgsfield.defaults.motion_draft")
    assert not _director_lint()(t)


# ---------------------------------------------------------------------------
# docs/SCHEDULED_TASKS.md: self-contained prompts, the seventh and the desktop task (R343)
# ---------------------------------------------------------------------------
def test_scheduled_prompts_are_self_contained(config):
    t = SCHEDULED.read_text(encoding="utf-8")
    prompts = _prompts(t)
    names = [x["name"] for x in config["schedule"]["tasks"]] + ["Quarterly research re-check", "Chrome queue"]
    assert list(prompts) == names
    for task in config["schedule"]["tasks"]:
        p = prompts[task["name"]]
        cmd = task["command"].lstrip("/")
        assert p.startswith(f"Run {task['command']} ")
        assert "NUMA Studio plugin (numa-studio)" in p and f"commands/{cmd}.md" in p
        assert f"If {task['command']} does not expand into instructions" in p
        assert f"runlog.py start {task['id']}" in p and "runlog.py finish" in p and "also when something fails" in p
        assert "ensure_env.py" in p
    q = prompts["Quarterly research re-check"]
    assert "runlog.py start quarterly_research" in q and "runlog.py finish" in q and "Jude" in q
    c = prompts["Chrome queue"]
    assert "commands/chrome-queue.md" in c and "runlog.py start chrome_queue" in c
    for p in prompts.values():
        assert "?" not in p, "a scheduled prompt never asks anything"


def test_scheduled_doc_seventh_and_desktop_tasks(config):
    t = SCHEDULED.read_text(encoding="utf-8")
    assert "## The eight tasks" in t and "## Cloud or desktop: where a task runs" in t
    assert ("| 7 | Quarterly research re-check | The 12th of Feb, May, Aug and Nov, 10 am | "
            "`CRON_TZ=America/Chicago 0 10 12 2,5,8,11 *` |") in t
    assert "| 8 | Chrome queue | Hourly at :47, while the Mac is awake | `CRON_TZ=America/Chicago 47 * * * *` | " \
           "`/chrome-queue` | **Desktop** |" in t
    for needle in ["fresh machine every time", "Only while the Mac is awake", "local/desktop scheduled task",
                   "not in the cloud", "runlog.py check --since", "`OK:`", "Watchdog (R341)", "ensure_env.py"]:
        assert needle in t, needle
    for extra in config["schedule"].get("extra_tasks", []):   # once config carries tasks 7 and 8
        assert f"| {extra['name']} | {extra['when']} | `CRON_TZ=America/Chicago {extra['cron']}` |" in t, extra["id"]
        if extra.get("where") == "desktop":
            assert extra["command"] == "/chrome-queue"
