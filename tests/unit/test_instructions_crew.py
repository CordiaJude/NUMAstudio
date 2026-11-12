"""Instruction-layer checks for the crew agents and core skills (T8b).

Covers agents/{critic,motion,editor,copywriter}.md and
skills/{numa-reel-editor,numa-caption,numa-brand-check}/SKILL.md:

* frontmatter (agents: name, description, model equal to the config tier,
  explicit tools; skills: name, description);
* every script and flag these files call exists (argparse, or the CONTRACTS
  section 9 signature for scripts still being built);
* every brand.json / config/studio.json key path resolves (plan.json field
  names that share a top-level name are checked against the plan schema);
* required content: the edit grammar numbers, the Year One example, every
  Critic hard gate, rubric category and weight, the Higgsfield workflow and the
  7-prompt library, the failure-ladder rows, the copy rules;
* the R119 lint (no question to Katie, no confirm step) on these files.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_instructions_director import (
    CORE_TOOLS,
    PENDING_FLAGS,
    PENDING_SCRIPTS,
    argparse_flags,
    body,
    code_segments,
    contracts_flags,
    frontmatter,
    lint_hits,
    resolve,
    script_calls,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
EXAMPLE_V2 = REPO / "skills" / "numa-reel-editor" / "assets" / "example-plan-year-one-v2.json"

AGENTS = {a: REPO / "agents" / f"{a}.md" for a in ("critic", "motion", "editor", "copywriter")}
SKILLS = {s: REPO / "skills" / s / "SKILL.md" for s in ("numa-reel-editor", "numa-caption", "numa-brand-check")}
OWNED = {**AGENTS, **SKILLS}


@pytest.fixture(scope="module")
def brand():
    return json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plan_schema():
    return json.loads((REPO / "schemas" / "plan.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def texts():
    return {k: p.read_text(encoding="utf-8") for k, p in OWNED.items()}


def norm(s: str) -> str:
    """Lowercase, unify x/× and dashes, collapse spaces: for matching spec text."""
    s = s.replace("×", "x").replace("–", "-").replace("—", "-").replace("→", "->").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def section(text: str, start: str, end: str | None = None) -> str:
    i = text.find(start)
    assert i >= 0, f"missing section {start!r}"
    j = text.find(end, i + len(start)) if end else -1
    return text[i: j if j > 0 else len(text)]


def table_rows(text: str, first_cell: str) -> dict[str, list[str]]:
    rows = {}
    for line in text.splitlines():
        m = re.match(rf"\|\s*({first_cell})\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return rows


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("agent", list(AGENTS))
def test_agent_frontmatter(agent, config):
    fm = frontmatter(AGENTS[agent])
    assert fm.get("name") == agent
    assert len(fm.get("description", "")) > 60
    assert fm.get("model") == config["models"]["agents"][agent], f"{agent}: model must be the config tier alias"
    tools = [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]
    assert tools and len(tools) == len(set(tools)), f"{agent}: explicit tool list without duplicates"
    for t in tools:
        assert t in CORE_TOOLS or re.fullmatch(r"mcp__[A-Za-z0-9_-]+__(\*|[A-Za-z0-9_-]+)", t), f"{agent}: {t!r}"


def test_agent_tiers_match_spec(config):
    tiers, agents = config["models"]["tiers"], config["models"]["agents"]
    assert agents["critic"] == tiers["top"]  # top, fresh context (spec p.38)
    assert agents["motion"] == tiers["mid"] and agents["editor"] == tiers["mid"]
    assert agents["copywriter"] == tiers["small"]


def test_tool_lists_fit_the_job():
    tools = {a: frontmatter(p)["tools"] for a, p in AGENTS.items()}
    assert "mcp__Higgsfield__*" in tools["motion"]  # server wildcard (DECISIONS D17)
    for a in ("critic", "editor", "copywriter"):
        assert "mcp__" not in tools[a], f"{a}: local scripts only"
    assert "Write" not in tools["critic"] and "Edit" not in tools["critic"], "the Critic judges, it does not edit"


def test_connector_agent_reports_missing_tools(texts):
    assert "If the Higgsfield connector tools are not visible, report it in the hand-back" in texts["motion"]


@pytest.mark.parametrize("skill", list(SKILLS))
def test_skill_frontmatter(skill):
    fm = frontmatter(SKILLS[skill])
    assert fm.get("name") == skill
    assert len(fm.get("description", "")) > 80


def test_no_model_ids(texts):
    for name, text in texts.items():
        assert not re.search(r"claude-(opus|sonnet|haiku)-\d", text), name


# ---------------------------------------------------------------------------
# scripts, flags, keys, JSON examples
# ---------------------------------------------------------------------------
def test_referenced_scripts_and_flags_exist(texts):
    problems, seen = [], set()
    for name, text in texts.items():
        for script, flags in script_calls(text):
            if script in ("numa_common.py",):
                continue
            seen.add(script)
            path = SCRIPTS / script
            if path.exists():
                known = argparse_flags(path)
            elif script in PENDING_SCRIPTS:
                known = contracts_flags(script)
            else:
                problems.append(f"{name}: {script} does not exist")
                continue
            for flag in flags:
                if flag not in known and (script, flag) not in PENDING_FLAGS:
                    problems.append(f"{name}: {script} has no {flag}")
    assert not problems, "\n".join(problems)
    assert {"baseline_plan.py", "validate_plan.py", "engine.py", "finish.py", "check_output.py", "qa_frames.py",
            "formats.py", "claims_scan.py", "critic_score.py", "ledger.py", "sources.py", "prefs.py",
            "prep_media.py"} <= seen


def test_subcommands_exist(texts):
    """ledger/critic_score/sources/prefs subcommands named in code exist."""
    subs = {"ledger.py": {"add", "check", "report", "price", "sheet"}, "critic_score.py": {"score", "round", "best"},
            "sources.py": {"add", "show", "check", "licenses"}, "prefs.py": {"add", "list", "limits", "export"}}
    for name, text in texts.items():
        for seg in code_segments(text):
            for script, allowed in subs.items():
                for m in re.finditer(rf"{re.escape(script)}\"?\s+([a-z_-]+)", seg):
                    assert m.group(1) in allowed, f"{name}: {script} {m.group(1)}"


def test_scripts_called_through_plugin_root(texts):
    for name, text in texts.items():
        if not re.search(r"python3\s+\S*\.py", text):
            continue
        assert "${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts" in text, name
        for seg in code_segments(text):
            if re.search(r"python3\s+\S*\.py", seg):
                assert '"$S/' in seg, f"{name}: call scripts via $S: {seg!r}"


def schema_resolve(schema: dict, dotted: str) -> bool:
    defs = schema.get("$defs", {})
    node = schema
    for part in dotted.split("."):
        for _ in range(4):
            if "$ref" in node:
                node = defs[node["$ref"].rsplit("/", 1)[-1]]
            elif node.get("type") == "array" and "items" in node:
                node = node["items"]
            else:
                break
        props = node.get("properties", {})
        if part not in props:
            return False
        node = props[part]
    return True


def test_key_paths_resolve(texts, brand, config, plan_schema):
    problems = []
    for name, text in texts.items():
        for seg in set(re.findall(r"`([a-z_]+(?:\.[a-z_0-9]+)+)`", text)):
            top = seg.split(".")[0]
            if top in brand:
                ok = resolve(brand, seg)
            elif top in config:
                ok = resolve(config, seg)
            else:
                continue
            if not ok and not schema_resolve(plan_schema, seg):
                problems.append(f"{name}: `{seg}` does not resolve in brand.json, config or the plan schema")
    assert not problems, "\n".join(problems)


def test_json_examples_parse(texts):
    for name, text in texts.items():
        for block in re.findall(r"```json\n(.*?)```", text, re.S):
            json.loads(block)


def test_critic_sheet_example_scores():
    import critic_score

    block = re.search(r"```json\n(.*?)```", AGENTS["critic"].read_text(encoding="utf-8"), re.S).group(1)
    sheet = json.loads(block)
    scores, gates = critic_score.parse_sheet(sheet)
    assert gates == [] and set(scores) == {c["id"] for c in critic_score.rubric()}


# ---------------------------------------------------------------------------
# numa-reel-editor SKILL: brand pointers, edit grammar, workflow, example
# ---------------------------------------------------------------------------
def test_skill_brand_pointers(texts):
    t = section(texts["numa-reel-editor"], "## 1. Brand pointers", "## 2.")
    for key in ["business.name", "offerings.offers", "offerings.not_offered", "voice.description", "assets.wordmark",
                "assets.endcard_background", "palette.value", "fonts.value", "endcard.tagline", "claims.banned",
                "consent.list", "consent.ai_processing_covered", "posting.music_rule", "posting.ai_label_rule"]:
        assert f"`{key}`" in t, key


GRAMMAR_NEEDLES = {
    "4.1": ["One story beat per spoken line", "illustrates the words",
            "before -> struggle -> turn -> payoff -> gratitude -> logo",
            "problem -> modality -> feeling -> call to action",
            "arrival -> energy -> faces -> community -> logo"],
    "4.2": ["strongest image", "never the logo", "frame 1", "0.2 s", "full opacity in frame zero", "1.5 s"],
    "4.3": ["within 1 frame at 30 fps", "2-beat cuts", "4-beat holds", "4 beats", "`peak: true`",
            "best 5-8 shots, 2 beats each", "3.5-5 s", "6-8 s"],
    "4.4": ["Exactly one", "`wipe`", "`flash`", "before and after"],
    "4.5": ["16% zoomed", "0.22 s", "0.28 s", "160 px", "every third cut", "0.5 s crossfade", "0.35 s",
            "left to right over 1 s", "The very first shot", "at least 3 transition types"],
    "4.6": ["Alternate zoom in and zoom out", "[1.02, 1.14]", "[1.15, 1.03]", "0.95-1.5", "black bars",
            "mirrored edges", "Smart framing", "`focus`", "`faces`", "`orig_faces`"],
    "4.7": ["55% saturation", "cool shift", "lifted blacks", "warm shift", "S-curve", "darkened edges",
            "bloom", "grain", "0.3-0.45"],
    "4.8": ["22 px over 0.28 s", "92 px", "#F7D6A0", "1-2 key words", "2 rows", "top 12%", "bottom 10%", "Off faces"],
    "4.9": ["ducks under the voice", "-15 LUFS", "48 kHz", "`nat`", "clip_audio", "`--clean-voice`"],
    "4.10": ["ripple", "white", "gold italic", "3.5-5 s"],
}


@pytest.mark.parametrize("sub", list(GRAMMAR_NEEDLES))
def test_edit_grammar(sub, texts):
    t = texts["numa-reel-editor"]
    start = t.find(f"### {sub} ")
    assert start > 0, f"missing Step {sub}"
    nxt = re.search(r"\n##+ ", t[start + 5:])
    sec = t[start: start + 5 + (nxt.start() if nxt else len(t))]
    for needle in GRAMMAR_NEEDLES[sub]:
        assert needle in sec, f"Step {sub}: missing {needle!r}"


def test_transition_table_complete(texts):
    rows = table_rows(texts["numa-reel-editor"], r"`(?:punch|whip|leakfade|flash|wipe|cut|fade)`")
    assert {"`punch`", "`whip`", "`leakfade`", "`flash`", "`wipe`", "`cut`", "`fade`"} <= set(rows)


def test_research_rules(texts):
    t = section(texts["numa-reel-editor"], "## 2. Research rules", "## 3.")
    for needle in ["Send this to", "45-60 s", "15-30 s", "15-60 s", "180 s", "2.3 words a second", "100 spoken words",
                   "10-14 shots", "works muted", "captions carry every spoken word", "payoff is visible",
                   "trending and popular songs are never used", "Higgsfield instrumental", "Sound Collection",
                   "license that names social media", "sources.txt", "interpretation 8"]:
        assert needle in t, needle


def test_claims_rules(texts):
    t = section(texts["numa-reel-editor"], "## 3. Claims rules", "## Step 4")
    for needle in ['"May help"', "make it worse", "Visuals count", "bodies, skin or bloodwork", "Testimonials",
                   "never repost or pin", "Ask the DPT is education only", "guides", "facilitators",
                   "claims.safety_line.text", "breath-holding", "Paid or comped creators", '"#ad"',
                   "I get free sessions", "claims.dosing_line.blocked", "ai.label_required"]:
        assert needle in t, needle
    rows = table_rows(t, r"Cold plunge|Sauna|Red light|Breathwork")
    assert set(rows) == {"Cold plunge", "Sauna", "Red light", "Breathwork"}
    assert "FDA-cleared" in rows["Red light"][1] and "inflammation" in rows["Cold plunge"][1].lower()


def test_higgsfield_step5(texts):
    t = section(texts["numa-reel-editor"], "## Step 5", "## Step 6")
    items = re.findall(r"^(\d+)\. ", t, re.M)
    assert [int(i) for i in items[:12]] == list(range(1, 13)), "ranked uses 1-12"
    for needle in ["get_cost", "Outpaint", "9:16", "2K", "standard 720p", "pro", "start + end frames", "Element",
                   "consent list only", "Seedance 2.5 for people-free spaces only", "Virality predictor",
                   "describe the motion, not the room", "keep clause", "change one thing per retry",
                   "Safe moves", "Risky", "scene, Element, camera, action timing, lighting, audio", "600", "140",
                   "160", "120", "170", "55%", "150", "never buy credits", "Never use Reframe",
                   "consent.ai_processing_covered", "agents/motion.md"]:
        assert needle in t, needle


def test_build_loop_order(texts):
    t = section(texts["numa-reel-editor"], "## Step 6", "## 8.")
    order = ['prefs.py" list', 'prep_media.py"', 'baseline_plan.py"', "Improve it by judgment", 'validate_plan.py"',
             'engine.py" "$JOB/work/plan.json" preview', "LOOK at `work/preview.jpg`", "Fix and repeat",
             'engine.py" "$JOB/work/plan.json"\n', 'finish.py"', 'check_output.py"', 'qa_frames.py"',
             "LOOK at `out/qa_strip.jpg`", 'formats.py"']
    idx = [t.find(s) for s in order]
    assert all(i >= 0 for i in idx), [s for s, i in zip(order, idx) if i < 0]
    assert idx == sorted(idx), "build loop out of order"
    for needle in ["`blur: [[", "F12", "hook_variants", "Trial Reel", "virality predictor", "--prefs", "0 ERRORs",
                   "`prepared_path`", "`people: true` + `consent: true`"]:
        assert needle in t, needle


def test_year_one_worked_example(texts):
    plan = json.loads(EXAMPLE_V2.read_text(encoding="utf-8"))
    t = section(texts["numa-reel-editor"], "## 8. Worked example")
    assert "assets/example-plan-year-one-v2.json" in t
    for needle in ["Hook text", "`before`", "`wipe`", "recap montage", "`endcard`", "transformation"]:
        assert needle in t, needle
    assert plan["hook"]["text"] in t and f'{plan["hook"]["t1"]:g}' in t
    assert plan["signature"]["type"] == "wipe" and f'{plan["signature"]["t"]:g}' in t
    assert plan["endcard"]["subtitle"] in t and f'{plan["endcard"]["t"]:g}' in t
    turn = next(s for s in plan["shots"] if s["look"] == "warm")
    assert f'{turn["t0"]:g}' in t and turn["tr"] == "leakfade"
    montage = [s for s in plan["shots"] if s["t0"] >= 30.28 and s["look"] == "warm"]
    assert f"{len(montage)} shots" in t
    assert f'{plan["duration"] - plan["endcard"]["t"]:.2f} s' in t


# ---------------------------------------------------------------------------
# critic.md
# ---------------------------------------------------------------------------
def test_critic_inputs_and_isolation(texts):
    t = texts["critic"]
    for needle in ["qa_strip.jpg", "critic_frames", "12 critic frames", "report.json", "transcript", "plan.json",
                   "SHOOT CARD", "consent_list.json", "never read `work/decisions.md`", "fresh context"]:
        assert needle in t, needle


def test_critic_hard_gates(texts, config):
    t = norm(texts["critic"])
    for gate in config["critic"]["hard_gates"]:
        assert norm(gate).rstrip(".") in t, f"hard gate missing: {gate}"
    rows = table_rows(texts["critic"], r"G\d")
    assert list(rows) == [f"G{i}" for i in range(1, 8)]
    checks = {"G1": "claims_scan", "G2": "consent_list.json", "G3": "sources.py check", "G4": "check_output",
              "G5": "offerings.offers", "G6": "ai_generated", "G7": "rule 30"}
    for g, needle in checks.items():
        assert needle in " ".join(rows[g]), f"{g}: check must use {needle}"
    assert "48 kHz only" in texts["critic"]


def test_critic_rubric(texts, config):
    t = texts["critic"]
    rows = table_rows(t, r"[A-Z][^|]*\(`[a-z_]+`\)")
    assert len(rows) == len(config["critic"]["rubric"])
    by_id = {re.search(r"`([a-z_]+)`", k).group(1): (k, v) for k, v in rows.items()}
    for cat in config["critic"]["rubric"]:
        key, cells = by_id[cat["id"]]
        assert key.startswith(cat["label"]), cat["label"]
        assert cells[0] == str(cat["weight"]), f"{cat['id']}: weight"
        assert norm(cat["five_looks_like"]) == norm(cells[1]), f"{cat['id']}: 'a 5 looks like' anchor"
    assert sum(int(v[0]) for v in rows.values()) == 100


def test_critic_pass_rule_and_output(texts, config):
    t = texts["critic"]
    p = config["critic"]["pass"]
    assert f"total {p['min_total']} or more" in t and f"no category below {p['min_category_score']}" in t
    assert f"Hook at least {p['min_hook_score']}" in t
    for needle in ['critic_score.py" score', "second opinion", "never changes a score", "score table",
                   "Numbered fixes", "exact plan.json field or shot", "Fixes the Editor can't act on are not allowed",
                   "Shot 3: replace with P7", "3 rounds"]:
        assert needle in t, needle


# ---------------------------------------------------------------------------
# motion.md
# ---------------------------------------------------------------------------
PROMPTS = {
    "Cold plunge, nobody in it": ("Kling 3.0", ["one slow push-in of about ten percent", "gentle ripples",
                                                "keep vertical lines straight"]),
    "Sauna glow": ("Kling 3.0", ["soft steam drifts up", "NUMA sign unchanged and frontal", "no people added"]),
    "Real room move": ("Kling 3.0, start + end frame", ["first image as the first frame", "one smooth dolly forward",
                                                         "no geometry warp"]),
    "Member or guide": ("Kling 3.0, person as Element", ["@Person sits on the sauna bench", "0-2 s a slow breath out",
                                                          "hands still"]),
    "Exterior and sign": ("Kling 3.0", ["Dauphin St", "golden hour", "lettering exactly as photographed"]),
    "Before -> after": ("Kling 3.0, start + end frame", ["Start: the old building", "Camera holds still",
                                                          "angle and street identical"]),
    "Empty walkthrough": ("Seedance 2.5 (no faces in frame)", ["slow steady dolly from the entrance toward the sauna door",
                                                                "no cuts", "vertical lines straight"]),
}


def test_prompt_library_has_all_seven(texts):
    lib = section(texts["motion"], "## 5. Prompt library", "## 6.")
    rows = table_rows(lib, "|".join(re.escape(k) for k in PROMPTS))
    assert set(rows) == set(PROMPTS), "all 7 spec prompts"
    for shot, (model, needles) in PROMPTS.items():
        assert rows[shot][0] == model, shot
        for n in needles:
            assert n in rows[shot][1], f"{shot}: {n!r}"


def test_motion_workflow(texts, config):
    t = texts["motion"]
    for p in config["higgsfield"]["prices"]:
        if not p.get("avoid"):
            assert f"`{p['id']}`" in t, p["id"]
    for needle in ["balance", 'ledger.py" report', 'ledger.py" check', 'ledger.py" add', "`get_cost: true`",
                   "`use_unlim: false`", "standard 720p", "re-render only the keeper at pro",
                   "Kling 3.0 (Element, consent list only)", "Seedance 2.5 only for people-free spaces",
                   "start + end frame", "Never Reframe", "Reframe (245 credits", "never buy",
                   "by day 15, at most 55% spent", "at most 150 credits", "600", "140", "160", "120", "170",
                   "Outpaint", '"9:16"', "Upscale to 2K", "LOOK at all three frames", "Drop", "only the hero photos",
                   "`consent.ai_processing_covered`", "`consent.voice_clone`", "Music bed", "Voice", "instrumental",
                   'sources.py" add', "higgsfield_paid", "virality predictor", "Trial Reel", "Scout",
                   "Claude in Chrome", "work/motion.json", "describe the motion, not the room".lower()]:
        assert needle.lower() in t.lower(), needle
    ranked = section(t, "## 3. What to use", "## 4.")
    assert [r for r in table_rows(ranked, r"\d+")] == [str(i) for i in range(1, 13)], "ranked uses 1-12"
    rules = section(t, "## 4. Prompt rules", "## 5.")
    for needle in ["one camera move per clip, with a size", "keep clause", "720p", "change one thing per retry",
                   "Safe moves", "Risky", "scene, Element (for a person), camera, action timing, lighting, audio",
                   "locks"]:
        assert needle.lower() in rules.lower(), needle


LADDER = {
    "motion": {"F7": ["warps", "Re-roll once", "Switch model", "engine motion"],
               "F8": ["`ledger.py check` exits 1", "1 strongest clip", "Engine motion only", "Never buy credits"],
               "F4": ["Landscape", "Outpaint to 9:16", "pan-across", "Blurred-fill"],
               "F5": ["Low-resolution", "Upscale to 2K", "montage", "Drop it"],
               "F1": ["No voiceover", "consent.voice_clone", "preset voice", "music-only"],
               "F2": ["No music", "exact length and tempo", "Music Library", "pad"],
               "F15": ["connector down", "15 minutes", "without motion clips", "Monday digest"]},
    "editor": {"F14": ["Render or encode crash", "--workers 1", "--draft", "one hour"],
               "F6": ["Shaky or dark", "prep_media.py", "upscale", "still"],
               "F12": ["Consent List", "blur", "different shot", "Drop the shot"],
               "F4": ["Landscape", "pan", "crop", "Blurred fill"]},
}


@pytest.mark.parametrize("agent", list(LADDER))
def test_failure_ladder_rows(agent, texts):
    rows = table_rows(texts[agent], r"F\d+")
    for fid, needles in LADDER[agent].items():
        assert fid in rows, f"{agent}: failure row {fid} missing"
        cells = rows[fid]
        assert len(cells) == 4 and all(cells), f"{agent} {fid}: what went wrong + 3 moves"
        joined = " ".join(cells).lower()
        for n in needles:
            assert n.lower() in joined, f"{agent} {fid}: {n!r}"
    assert "fallback F<n>.<move>" in texts[agent]


def test_motion_frame_snippet_runs(tmp_path):
    """The inspection snippet in motion.md extracts 3 frames from a clip."""
    import numa_common as nc

    snippet = re.search(r"python3 - \"\$S\" .*?<<'EOF'\n(.*?)EOF", AGENTS["motion"].read_text(encoding="utf-8"), re.S)
    assert snippet
    clip = tmp_path / "P2_kling_draft1.mp4"
    nc.ffmpeg("-f", "lavfi", "-i", "testsrc=size=180x320:rate=30:duration=2", "-pix_fmt", "yuv420p", str(clip))
    subprocess.run([sys.executable, "-", str(SCRIPTS), str(clip)], input=snippet.group(1), text=True, check=True,
                   capture_output=True)
    assert sorted(p.name for p in tmp_path.glob("*_f*.jpg")) == [f"P2_kling_draft1_f{i}.jpg" for i in (1, 2, 3)]


# ---------------------------------------------------------------------------
# editor.md
# ---------------------------------------------------------------------------
def test_editor_steps(texts):
    t = texts["editor"]
    order = ['baseline_plan.py"', 'validate_plan.py"', 'engine.py" "$JOB/work/plan.json" preview', "LOOK at `work/preview.jpg`",
             'engine.py" "$JOB/work/plan.json"\n', 'finish.py"', 'check_output.py"', 'qa_frames.py"',
             "LOOK at `out/qa_strip.jpg`", "## 4. Critic fix rounds", 'formats.py"']
    idx = [t.find(s) for s in order]
    assert all(i >= 0 for i in idx), [s for s, i in zip(order, idx) if i < 0]
    assert idx == sorted(idx)
    for needle in ["only agent that renders", "One render at a time", "0 ERRORs", "Apply exactly what each numbered fix names",
                   "not actionable", "`ai_generated: true`", "`ai.label_required: true`", "`orig_faces`", "`blur`",
                   "--clean-voice", "never with Higgsfield Reframe", "PREFS"]:
        assert needle in t, needle


# ---------------------------------------------------------------------------
# copywriter + numa-caption
# ---------------------------------------------------------------------------
def test_caption_skill(texts, brand):
    t = texts["numa-caption"]
    for needle in ["3 options", "**Recommended**", "plain searchable phrase", "cold plunge in Mobile, AL",
                   "3-5", "`captions.hashtags`", "`captions.hashtags.never`", 'claims_scan.py" -', "--hashtags",
                   "Story text", "Email paragraph", "40-70 words", "share line", "#ad", "I get free sessions",
                   "AI label: ON", "`ai.label_required`", "`claims.safety_line.text`", "never invent one",
                   "no booking pitch", "R236"]:
        assert needle in t, needle
    for tag in brand["captions"]["hashtags"]["base"]:
        assert tag in t, tag


def test_caption_worked_example_is_clean(texts):
    import claims_scan  # noqa: F401  (the script must import cleanly)

    ex = section(texts["numa-caption"], "## Worked example")
    lines = [ln[2:] for ln in ex.splitlines() if ln.startswith("> ")]
    tags = lines[-1]
    r = subprocess.run([sys.executable, str(SCRIPTS / "claims_scan.py"), "-", "--hashtags", tags],
                       input="\n".join(lines[:-1]), text=True, capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines[0].lower().startswith("cold plunge in mobile, al")
    assert 3 <= len(tags.split()) <= 5


def test_copywriter_agent(texts):
    t = texts["copywriter"]
    for needle in ["numa-caption", "3 caption options", "recommended", "plain searchable phrase", "3-5 hashtags",
                   'claims_scan.py" -', "--hashtags", "Story line", "email paragraph", "#ad", "AI label: ON"]:
        assert needle in t, needle


# ---------------------------------------------------------------------------
# numa-brand-check
# ---------------------------------------------------------------------------
def test_brand_check_rows(texts):
    t = texts["numa-brand-check"]
    rows = table_rows(t, r"\d")
    assert list(rows) == [str(i) for i in range(1, 8)]
    needles = {"1": ['check_output.py"', "48 kHz only", "interpretation 12"], "2": ['claims_scan.py"', "--hashtags"],
               "3": ['validate_plan.py"', "rule 28", "consent_list.json"], "4": ['sources.py" check'],
               "5": ["ai.label_required", "rule 30"], "6": ["business.name", "offerings.offers"],
               "7": ["qa_strip.jpg", "#F7D6A0", "top 12%", "wordmark"]}
    for n, ns in needles.items():
        for needle in ns:
            assert needle in " ".join(rows[n]), f"row {n}: {needle!r}"
    assert "44.1" in t and "fails" in t  # v1 accepted 44.1 kHz; v2 does not


# ---------------------------------------------------------------------------
# R119 lint on the owned files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(OWNED))
def test_r119_lint(name, texts):
    hits = lint_hits(texts[name])
    assert not hits, f"{name} asks Katie or adds a confirm step:\n" + "\n".join(hits)


def test_bodies_never_ask(texts):
    for name, text in texts.items():
        b = body(OWNED[name])
        assert not re.search(r"\boffer to\b", b, re.I), f"{name}: no offers to the user mid-run"
