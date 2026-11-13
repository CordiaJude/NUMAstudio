"""Instruction-layer checks for setup and auto-posting (T10).

Covers commands/{numa-setup,brand-setup,post-reel}.md, docs/SETUP_GUIDE.md and
docs/QUESTIONS_FOR_KATIE.md: frontmatter, referenced scripts and flags, key
paths, all 51 setup questions with their brand.json keys, the Composio tool
names from spec p.47-48, the posting gates, and the R119 lint exemptions.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
CMD = {n: REPO / "commands" / f"{n}.md" for n in ("numa-setup", "brand-setup", "post-reel")}
DOCS = {"guide": REPO / "docs" / "SETUP_GUIDE.md", "questions": REPO / "docs" / "QUESTIONS_FOR_KATIE.md"}

# brand.json keys the questionnaire writes that the shipped brand.json does not carry yet
# (requested shared-file change, T10 report). The integration task empties this set.
# brand.json keys the questionnaire writes (all present in the shipped brand.json).
QUESTIONNAIRE_KEYS = {
    "positioning.differentiator", "positioning.join_reasons", "positioning.hesitations",
    "positioning.member_stories", "positioning.goals_90d", "offerings.priority_offer",
    "offerings.upcoming", "assets.logo_credit", "voice.inspiration_accounts", "voice.off_limits_topics",
    "team.voiceover", "socials.instagram_account", "business.account_owners", "positioning.paid_ads",
    "positioning.past_best_posts", "positioning.past_flops", "positioning.audience_size",
    "positioning.ask_the_dpt", "offerings.rates_considered", "posting.legal_counsel", "drive.root_link",
}
# Private keys written only to STATE/brand.json, never to the public repo copy (checked against the schema below).
STATE_ONLY_KEYS = {"escalation.channel"}

# One distinctive phrase per question (spec p.54-57), in order.
QUESTIONS = [
    "How do you write the name", "Address, the area of Mobile", "Regular hours, and every closure",
    "Every service and its price", "Discover NUMA ($49)", "Numa Nights and Clinical Conversations",
    "Who's on the team", "The founding story in your words", "What makes NUMA different",
    "Who do you see most at NUMA", "The top three reasons people join", "Any member stories you love",
    "What should these reels do in the next 90 days", "Which offer matters most right now",
    "Is anything full", "What's coming in the next 3 months", "official brand colors",
    "3 Instagram accounts whose videos you love", "Anything you dislike seeing in wellness content",
    "Words you always use", "What do you call the people who come", "Emojis in captions",
    "Music you picture under NUMA videos", "Topics that are off-limits", "consent or photo release",
    "Who on the team may appear in videos", "Are children ever at NUMA", "Will you record voiceovers yourself",
    "Who will film", "Best times for a 20-minute batch shoot", "Any rooms or moments that should never be filmed",
    "Business or Creator account", "Who owns the Google Drive", "Should reels post automatically",
    "always want to see first", "Where should every call to action point", "Are you running paid ads",
    "Where should the Monday digest go", "Your best-performing posts ever", "Anything you've tried that flopped",
    "Roughly how many followers today", "1719 Dauphin St", "Which phone number should be used everywhere",
    "Is the team list right", "Ask the DPT", "Which red light panels", "57 minutes of sauna",
    "cover appearing in social posts and AI processing", "Would NUMA partner with Mission Fitness",
    "rate for healthcare workers or students", "advertising lawyer",
]
GROUPS = ["The business", "Goals", "Brand and taste", "People and consent", "Filming",
          "Accounts and posting", "What's worked", "Confirm what the research found"]
SPEC_COMPOSIO_TOOLS = ["INSTAGRAM_POST_IG_USER_MEDIA", "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH",
                       "INSTAGRAM_GET_IG_MEDIA_INSIGHTS", "INSTAGRAM_GET_USER_INSIGHTS"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: no frontmatter"
    end = text.find("\n---", 4)
    assert end > 0
    data = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "-")):
            data[key.strip()] = value.strip().strip('"')
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


def script_calls(text: str) -> list[tuple[str, list[str]]]:
    calls = []
    for seg in code_segments(text):
        parts = re.split(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b", seg)
        for i in range(1, len(parts), 2):
            tail = parts[i + 1] if i + 1 < len(parts) else ""
            calls.append((parts[i], re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", tail)))
    return calls


def prose_script_flags(text: str) -> list[tuple[str, str]]:
    """`setup_check.py --download-model` style mentions in running text."""
    return re.findall(r"([a-z_]+\.py) (--[a-z][a-z0-9-]*)", text)


def argparse_flags(script: Path) -> set[str]:
    return set(re.findall(r"""["'](--[a-z][a-z0-9-]*)["']""", script.read_text(encoding="utf-8")))


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
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def brand():
    return json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def texts():
    return {**{k: body(p) for k, p in CMD.items()}, **{k: body(p) for k, p in DOCS.items()}}


# ---------------------------------------------------------------------------
# structure, scripts, keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(CMD))
def test_command_frontmatter(name):
    fm = frontmatter(CMD[name])
    assert len(fm.get("description", "")) > 40
    assert fm.get("argument-hint")
    assert fm.get("model") == "opus"


def test_referenced_scripts_and_flags_exist(texts):
    problems, seen = [], set()
    for name, text in texts.items():
        for script, flags in script_calls(text) + [(s, [f]) for s, f in prose_script_flags(text)]:
            path = SCRIPTS / script
            seen.add(script)
            if not path.exists():
                problems.append(f"{name}: {script} does not exist")
                continue
            known = argparse_flags(path)
            problems += [f"{name}: {script} has no {f}" for f in flags if f not in known]
    assert not problems, "\n".join(problems)
    assert {"setup_check.py", "ledger.py", "claims_scan.py", "metrics.py"} <= seen


def test_scripts_called_through_plugin_root():
    for name, path in CMD.items():
        text = body(path)
        assert "${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts" in text, name
        for seg in code_segments(text):
            if re.search(r"python3\s+\S*\.py", seg):
                assert '"$S/' in seg, f"{name}: {seg!r}"


def test_key_paths_resolve(texts, brand, config):
    problems = []
    for name, text in texts.items():
        for seg in set(re.findall(r"`([a-z_]+(?:\.[a-z_0-9]+)+)`", text)):
            top = seg.split(".")[0]
            if top in brand and top not in config:
                ok = resolve(brand, seg) or seg in STATE_ONLY_KEYS
            elif top in config and top not in brand:
                ok = resolve(config, seg)
            else:
                continue
            if not ok:
                problems.append(f"{name}: `{seg}` does not resolve")
    assert not problems, "\n".join(problems)


def test_state_only_keys_pass_the_schema(brand):
    import copy
    import numa_common as nc
    b = copy.deepcopy(brand)
    b["escalation"]["channel"] = "notification"
    assert nc.schema_errors("brand", b) == []
    assert "channel" not in brand["escalation"], "private channel must not be committed"


def test_questionnaire_keys_exist(brand):
    assert not [k for k in QUESTIONNAIRE_KEYS if not resolve(brand, k)]


def test_q24_claim_rule_template_validates(brand, tmp_path, monkeypatch):
    """The new-claims-rule template in brand-setup.md, filled in, keeps brand.json schema-valid."""
    import copy
    import numa_common as nc
    text = body(CMD["brand-setup"])
    tmpl = re.search(r"\*\*New claims rule \(Q24\)\.\*\* For each claim: `(\{.*?\})`", text).group(1)
    rule = json.loads(tmpl.replace("<snake_case>", "immune_boost").replace("<plain words>", "immune boost")
                      .replace("<python regex>", "\\\\bimmune\\\\s+boost\\\\w*"))
    assert "source" not in rule
    b = copy.deepcopy(brand)
    b["claims"]["banned"].append(rule)
    path = tmp_path / "brand.json"
    path.write_text(json.dumps(b))
    monkeypatch.setenv("NUMA_BRAND", str(path))
    nc.clear_caches()
    try:
        assert nc.schema_errors("brand", b) == []
        nc.load_brand()  # schema + every pattern compiles
        bad = copy.deepcopy(b)
        bad["claims"]["banned"][-1]["source"] = "Katie Q24"
        assert nc.schema_errors("brand", bad), "schema should reject extra rule keys"
    finally:
        nc.clear_caches()


def test_brand_setup_saves_state_copy_per_d18(texts):
    t = texts["brand-setup"]
    sec = t[t.find("## 4. Validate and save"):t.find("## 5.")]
    assert "`STATE/brand.json`" in sec and "D18" in sec and "NUMA_BRAND" in sec
    assert "Keys added by this questionnaire" not in t


def test_escalation_channel_and_quarterly_reminder(texts):
    s = texts["numa-setup"]
    assert "`escalation.channel`" in s and "STATE/brand.json` only" in s
    assert "Quarterly research re-check" in s and "0 10 12 2,5,8,11 *" in s
    assert "Quarterly research re-check" in texts["guide"]
    assert "`mcp__Google_Docs__*`" in s and "`mcp__Gmail__*`" in s and "| Google Docs |" in s


def test_error_190_line_identical(texts):
    line = re.search(r'"(NUMA Studio: Instagram disconnected \(Meta error 190\)\. Fix: [^"]+)"', texts["post-reel"]).group(1)
    assert "Composio dashboard" in line and line in texts["numa-setup"]


def test_setup_check_cli_matches_contract():
    contract = (REPO / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    sig = re.search(r"### setup_check\.py.*?```(.*?)```", contract, re.S).group(1)
    defined = set(re.findall(r"""add_argument\(\s*["'](--[a-z][a-z0-9-]*)["']""", (SCRIPTS / "setup_check.py").read_text()))
    assert set(re.findall(r"--[a-z-]+", sig)) == defined


# ---------------------------------------------------------------------------
# the 51 questions
# ---------------------------------------------------------------------------
def question_rows(text: str) -> dict[int, str]:
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\| (\d+) \| (.+)", line) or re.match(r"\*\*(\d+)\.\*\* (.+)", line)
        if m:
            rows[int(m.group(1))] = m.group(2)
    return rows


@pytest.mark.parametrize("doc", ["brand-setup", "questions"])
def test_all_51_questions_in_order_with_keys(doc, texts, brand):
    text = texts[doc]
    rows = question_rows(text)
    assert sorted(rows) == list(range(1, 52)), doc
    for n, phrase in enumerate(QUESTIONS, 1):
        assert phrase in rows[n], f"{doc} Q{n}: {phrase!r} missing"
    # every question names at least one brand.json key
    if doc == "brand-setup":
        for n, row in rows.items():
            assert re.search(r"`[a-z_]+(\.[a-z_0-9]+)*`", row), f"Q{n} has no brand.json key"
    else:
        blocks = re.split(r"\n\*\*\d+\.\*\* ", text)[1:]
        assert len(blocks) == 51 and all("_Fills:_ `" in b for b in blocks)
    positions = [text.find(g) for g in GROUPS]
    assert all(p >= 0 for p in positions) and positions == sorted(positions), doc


def test_question_texts_match_between_docs(texts):
    a, b = question_rows(texts["brand-setup"]), question_rows(texts["questions"])
    for n in range(1, 52):
        assert a[n].split(" | ")[0].strip() == b[n].rstrip(" ").rstrip(), f"Q{n} differs"


def test_brand_setup_rules(texts, brand):
    t = texts["brand-setup"]
    for needle in ["needs_katie", "`confirmed`", "Don't know", "keep the current value", "setup_check.py\" --skip-render --json",
                   "only** place", "Asked once", "posting.legal_review_done", "claims_scan.py",
                   "Brand-data edits", "dosing_line.blocked` stays true", "children never (Q27)",
                   "auto-post yes (Q34)", "see-first none (Q35)"]:
        assert needle in t, needle
    # defaults the spec fixes are the shipped values
    assert brand["consent"]["children"]["value"] == "never"
    assert brand["posting"]["auto_post"]["value"] is True
    assert brand["posting"]["see_first"]["value"] == []


# ---------------------------------------------------------------------------
# /numa-setup
# ---------------------------------------------------------------------------
def test_numa_setup_steps(texts, brand):
    t = texts["numa-setup"]
    for needle in ["setup_check.py\" --download-model", "requirements.txt", "--break-system-packages",
                   "qa_strip.jpg", "ledger.py\" report --ledger", "--balance", "get_cost",
                   "Google Drive", "Google Sheets", "Higgsfield", "Composio Instagram", "Gmail", "Claude in Chrome",
                   "`instagram.graph_api_version`", "Ask Jude this one question, once", "`drive.root`",
                   "Always allow", "Keep computer awake", "Run on startup", "Golden test",
                   "2026-11-09 Year One", "docs/SCHEDULED_TASKS.md", "Exact prompts to paste", "copied **exactly**"]:
        assert needle in t, needle
    assert (REPO / "docs" / "SCHEDULED_TASKS.md").is_file()
    cols = brand["consent"]["list"]["columns"]
    assert ", ".join(f"`{c}`" for c in cols) in t
    assert "`Date`, `Name`, `Note`" in t
    for key in ("music_library", "digests", "consent_list", "closures", "plan_dir"):
        assert f"`drive.{key}`" in t
    # the golden test comes before the schedule
    assert t.find("Golden test") < t.find("## 10. Scheduled tasks")


def test_scheduled_task_prompts_exist():
    sched = body(REPO / "docs" / "SCHEDULED_TASKS.md")
    assert "Exact prompts to paste" in sched and "So runs never stall" in sched


# ---------------------------------------------------------------------------
# /post-reel
# ---------------------------------------------------------------------------
def test_post_reel_is_the_handoff_named_by_make_reel():
    assert "`post-reel` command" in body(REPO / "commands" / "make-reel.md")


def test_post_reel_composio_tools(texts, config):
    t = texts["post-reel"]
    for tool in SPEC_COMPOSIO_TOOLS:
        assert re.search(rf"\b{tool}\b", t), tool
    assert set(SPEC_COMPOSIO_TOOLS) == set(config["instagram"]["tools"].values())
    assert "graph_api_version" in t and "COMPOSIO_PROXY_EXECUTE" in t


def test_post_reel_gates_and_flow(texts, brand):
    t = texts["post-reel"]
    for key in ("posting.auto_post.value", "posting.legal_review_done.value",
                "posting.require_approval.value", "posting.see_first.value"):
        assert f"`{key}`" in t and resolve(brand, key), key
    gates = [t.find(k) for k in ("`posting.auto_post.value`", "`posting.legal_review_done.value`",
                                 "`posting.require_approval.value`")]
    assert gates == sorted(gates)
    assert brand["posting"]["require_approval"]["value"] is False  # the switch ships off
    assert brand["posting"]["legal_review_done"]["value"] is False
    for needle in ["off by default", "escalation.contact", "`instagram.publishing_limit_per_24h`",
                   "`instagram.container_max_age_hours`", "never reuse", "`instagram.publish_wait_minutes`",
                   "sleep 180", "Composio file staging", "Drive public link", "video/mp4", "publicly fetchable",
                   "`posting.posting_time`", "5:00 pm Central", "Facebook", "Meta Business Suite",
                   "Trial Reel", "trial_params", "collaborators", "Claude in Chrome", "AI label",
                   "`ai.label_required`", "Status `Posted`", "permalink", "metrics.py\" tag",
                   "Meta error 190", "Queue the post", "Retry after 1, 5 and 15 minutes",
                   "Google Business Profile", "never ask Katie anything"]:
        assert needle in t, needle


def test_post_reel_ai_label_order(texts):
    t = texts["post-reel"]
    sec = t[t.find("## 6. The AI label"):t.find("## 7.")]
    assert sec.find("**API:**") < sec.find("**Claude in Chrome:**") < sec.find("**Neither:**")
    assert "Jude" in sec


# ---------------------------------------------------------------------------
# docs/SETUP_GUIDE.md
# ---------------------------------------------------------------------------
def test_setup_guide(texts, config):
    t = texts["guide"]
    for needle in ["Max", "Keep computer awake", "Run on startup", "CordiaJude/numa-studio", "Google Drive",
                   "Higgsfield", "Composio", "Business or Creator", "Gmail", "Claude in Chrome", "Consent List",
                   "Closures", "voice sample", "/numa-setup", "/brand-setup", "Golden test", "SCHEDULED_TASKS.md",
                   "Account fixes", "NUMA | Sauna + Cold Plunge Mobile AL", "One phone number everywhere",
                   "Google Business Profile", "AI label", "Monthly cost", "$100", "$0 (free Hobby plan)",
                   "about $150-160 a month", "blocking inputs", "lawyer", "Verify these first",
                   "Research prompts", "every quarter", "`higgsfield.prices_verified_on`"]:
        assert needle in t, needle
    for task in config["schedule"]["tasks"]:
        assert task["name"] in t and task["when"] in t, task["id"]
    verify = t[t.find("## Verify these first"):t.find("## Monthly cost")]
    assert len(re.findall(r"^\| [1-4] \|", verify, re.M)) == 4
    prompts = t[t.find("## Research prompts"):]
    assert len(re.findall(r'^\d\. "', prompts, re.M)) == 5
    assert config["higgsfield"]["prices_verified_on"]


# ---------------------------------------------------------------------------
# R119: questions only in the setup commands
# ---------------------------------------------------------------------------
def _director_lint():
    spec = importlib.util.spec_from_file_location("_director_lint", Path(__file__).with_name("test_instructions_director.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r119_exempts_only_the_two_setup_commands():
    lint = _director_lint()
    assert lint.LINT_EXEMPT == {"commands/numa-setup.md", "commands/brand-setup.md"}
    assert "commands/post-reel.md" in lint.runtime_instruction_files()


def test_post_reel_never_asks():
    lint = _director_lint()
    hits = lint.lint_hits(body(CMD["post-reel"]))
    assert not hits, "\n".join(hits)


def test_setup_questions_go_to_jude_only(texts):
    t = texts["numa-setup"]
    assert "never ask" in t.lower() or "never asked of Katie" in t
    asks = [ln for ln in t.splitlines() if re.search(r"\bask\b", ln, re.I)]
    assert all("Jude" in ln or "never" in ln.lower() or "only" in ln.lower() or "once" in ln.lower() for ln in asks), asks


# ---------------------------------------------------------------------------
# /post-reel: carousels and single photos (R333, R335)
# ---------------------------------------------------------------------------
IMAGE_POST_TOOLS = ["INSTAGRAM_POST_IG_USER_MEDIA", "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH",
                    "INSTAGRAM_CREATE_CAROUSEL_CONTAINER", "INSTAGRAM_GET_IG_USER_CONTENT_PUBLISHING_LIMIT",
                    "INSTAGRAM_GET_IG_USER_MEDIA", "INSTAGRAM_GET_IG_MEDIA", "FACEBOOK_CREATE_MULTI_PHOTO_POST",
                    "FACEBOOK_CREATE_PHOTO_POST", "FACEBOOK_LIST_MANAGED_PAGES"]


def _section12(texts) -> str:
    t = texts["post-reel"]
    start = t.find("## 12. Carousels and single photos")
    assert start > 0
    return t[start:]


def test_post_reel_describes_all_post_types():
    fm = frontmatter(CMD["post-reel"])
    assert "posts reels, carousels and photos" in fm["description"]
    assert "carousel or photo" in fm["argument-hint"]


def test_post_reel_image_tools_and_fields(texts):
    sec = _section12(texts)
    for tool in IMAGE_POST_TOOLS:
        assert re.search(rf"\*\*{tool}\*\*|\b{tool}\b", sec), tool
    for field in ("`image_url`", "`image_file`", "`is_carousel_item` true", "`alt_text`", "`media_type` CAROUSEL",
                  "`children`", "`creation_id`", "`caption`", "`photo_urls`", "`page_id`", "`graph_api_version`"):
        assert field in sec, field
    # the carousel order: children, then the CAROUSEL parent, then publish
    car = sec[sec.find("| Carousel (2-10 slides) |"):]
    car = car[:car.find("\n")]
    assert car.find("`is_carousel_item` true") < car.find("`media_type` CAROUSEL") < car.find(
        "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH")
    single = sec[sec.find("| Single photo (IMAGE) |"):]
    single = single[:single.find("\n")]
    assert "no `media_type`" in single and "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH" in single


def test_post_reel_image_gates_and_rules(texts, brand, config):
    sec = _section12(texts)
    gates = [sec.find(f"`{k}`") for k in ("posting.auto_post.value", "posting.legal_review_done.value",
                                           "posting.require_approval.value", "posting.see_first.value")]
    assert all(g >= 0 for g in gates) and gates == sorted(gates)
    for key in ("instagram.publishing_limit_per_24h", "instagram.container_max_age_hours", "instagram.graph_api_version"):
        assert f"`{key}`" in sec and resolve(config, key), key
    for needle in ["counts as **one** post", "same run", "never publish an old container", "AI label",
                   "Drive public link", "image/jpeg", "Composio file staging", "1,000 characters",
                   "Status `Posted`", "permalink", "post_type", "metrics.py\" tag", "--post <media_id>",
                   "Facebook never blocks Instagram", "Meta Business Suite", "Never publish the same carousel or photo twice",
                   "code 9007", "section 8", "never a question", "STATE/consent_list.json", "--blur-faces",
                   "photo_post.py\" carousel", "photo_post.py\" single", "LOOK at every slide",
                   "_carousel_NN.jpg", "read as a number", "Never ask Katie anything"]:
        assert needle in sec, needle
    assert "socials.facebook" in sec and resolve(brand, "socials.facebook")


def test_post_reel_reel_flow_unchanged(texts):
    """The reel sections keep their numbers and order; the new section comes last."""
    t = texts["post-reel"]
    heads = re.findall(r"^## (\d+)\. ", t, re.M)
    assert heads == [str(i) for i in range(1, 13)]
    assert "media_type` = config `instagram.media_type` (REELS)" in t


def test_post_reel_post_types_match_metrics():
    import metrics
    sec = body(CMD["post-reel"])
    assert "reel, carousel, image, story, trial_reel" in sec
    assert tuple("reel, carousel, image, story, trial_reel".split(", ")) == metrics.POST_TYPES
