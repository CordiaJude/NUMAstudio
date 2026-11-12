"""Instruction-layer checks for the Director's run (T8a).

Covers commands/make-reel.md and agents/{librarian,scout,analyst}.md:

* frontmatter: name/description/model/tools, model equal to the tier alias in
  config/studio.json `models.agents` (R125, R204);
* every script these files call exists and every flag they pass is one the
  script's argparse defines (or the CONTRACTS section 9 signature, for scripts
  still being built in parallel);
* every brand.json / config key path they cite resolves;
* required rows and steps (R10-R14, R18, R30-R33, R41, R91-R125, R250, R277, R283);
* the R119 lint over every run-time instruction file: no question to Katie and
  no confirm or approval step (setup questionnaire excepted).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
CONTRACTS = REPO / "docs" / "CONTRACTS.md"

OWNED = {
    "make-reel": REPO / "commands" / "make-reel.md",
    "librarian": REPO / "agents" / "librarian.md",
    "scout": REPO / "agents" / "scout.md",
    "analyst": REPO / "agents" / "analyst.md",
}

# Scripts being built in parallel: until they exist, their flags are checked
# against the docs/CONTRACTS.md section 9 signature instead of argparse.
PENDING_SCRIPTS = {"formats.py"}
# Flags a later task adds to an existing script (DECISIONS D14: T12 adds
# baseline_plan.py --template). The integration task empties this.
PENDING_FLAGS = {("baseline_plan.py", "--template"): "T12 adds --template (DECISIONS D14)"}

# Core Claude Code tools an agent may list; anything else must be an MCP tool.
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
        if not line.strip() or line.startswith((" ", "\t", "#", "-")):
            continue
        key, sep, value = line.partition(":")
        assert sep, f"{path.name}: bad frontmatter line {line!r}"
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text[text.find("\n---", 4) + 4:]


def code_segments(text: str) -> list[str]:
    """Every fenced-code line and every inline code span."""
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
    """(script, flags) for every script named in code: the flags that follow it on the same segment."""
    calls = []
    for seg in code_segments(text):
        parts = re.split(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b", seg)
        for i in range(1, len(parts), 2):
            flags = re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", parts[i + 1] if i + 1 < len(parts) else "")
            calls.append((parts[i], flags))
    return calls


def argparse_flags(script: Path) -> set[str]:
    return set(re.findall(r"""["'](--[a-z][a-z0-9-]*)["']""", script.read_text(encoding="utf-8")))


def contracts_flags(script: str) -> set[str]:
    text = CONTRACTS.read_text(encoding="utf-8")
    m = re.search(rf"### {re.escape(script)}.*?```(.*?)```", text, re.S)
    assert m, f"{script}: no signature in docs/CONTRACTS.md section 9"
    return set(re.findall(r"(--[a-z][a-z0-9-]*)", m.group(1)))


def resolve(data, dotted: str) -> bool:
    node = data
    for part in dotted.split("."):
        while isinstance(node, dict) and part not in node and isinstance(node.get("value"), dict):
            node = node["value"]
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@pytest.fixture(scope="module")
def brand():
    return json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def texts():
    return {k: p.read_text(encoding="utf-8") for k, p in OWNED.items()}


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
def test_make_reel_frontmatter(config):
    fm = frontmatter(OWNED["make-reel"])
    assert fm.get("description")
    assert fm.get("argument-hint")
    assert fm.get("model") == config["models"]["agents"]["director"], "the Director runs on the top tier (R111)"


@pytest.mark.parametrize("agent", ["librarian", "scout", "analyst"])
def test_agent_frontmatter(agent, config):
    fm = frontmatter(OWNED[agent])
    assert fm.get("name") == agent
    assert len(fm.get("description", "")) > 40
    assert fm.get("model") == config["models"]["agents"][agent], f"{agent}: model must be the config tier alias"
    tools = [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]
    assert tools, f"{agent}: tools must be an explicit list"
    assert len(tools) == len(set(tools)), f"{agent}: duplicate tools"
    for t in tools:
        assert t in CORE_TOOLS or re.fullmatch(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+", t), f"{agent}: unknown tool {t!r}"
    assert "*" not in fm.get("tools", "")


def test_agent_tiers_match_spec(config):
    tiers = config["models"]["tiers"]
    agents = config["models"]["agents"]
    assert agents["librarian"] == tiers["small"]  # small, fast (spec p.38)
    assert agents["scout"] in (tiers["small"], tiers["mid"])  # small or mid (R125)
    assert agents["analyst"] in (tiers["small"], tiers["mid"])  # small or mid
    assert agents["director"] == tiers["top"]


def test_tool_lists_fit_the_job():
    tools = {a: frontmatter(OWNED[a])["tools"] for a in ("librarian", "scout", "analyst")}
    assert "Google_Drive" in tools["librarian"]  # ingest through the Drive connector (R13, R14)
    assert "claude-in-chrome" in tools["scout"] and "WebSearch" in tools["scout"]  # Chrome + cloud fallback (R124)
    assert "mcp__" not in tools["analyst"]  # local scripts only


def test_no_model_ids_in_instructions(texts):
    for name, text in texts.items():
        assert not re.search(r"claude-(opus|sonnet|haiku)-\d", text), f"{name}: model ids belong in config/studio.json (R204)"


# ---------------------------------------------------------------------------
# referenced scripts, flags and keys
# ---------------------------------------------------------------------------
def test_referenced_scripts_and_flags_exist(texts):
    problems, seen = [], set()
    for name, text in texts.items():
        for script, flags in script_calls(text):
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
    assert {"analyze.py", "fix_transcript.py", "vision.py", "prep_media.py", "baseline_plan.py",
            "validate_plan.py", "engine.py", "finish.py", "check_output.py", "qa_frames.py",
            "critic_score.py", "formats.py", "claims_scan.py", "ledger.py", "library.py",
            "prefs.py", "sources.py"} <= seen


def test_scripts_called_through_plugin_root(texts):
    for name, text in texts.items():
        assert "${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts" in text, name
        for seg in code_segments(text):
            if re.search(r"python3\s+\S*\.py", seg):
                assert '"$S/' in seg, f"{name}: call scripts by absolute path via $S: {seg!r}"


def test_key_paths_resolve(texts, brand, config):
    problems = []
    for name, text in texts.items():
        for seg in set(re.findall(r"`([a-z_]+(?:\.[a-z_0-9]+)+)`", text)):
            top = seg.split(".")[0]
            if top in brand and top not in config:
                ok = resolve(brand, seg)
            elif top in config and top not in brand:
                ok = resolve(config, seg)
            else:
                continue
            if not ok:
                problems.append(f"{name}: `{seg}` does not resolve")
    assert not problems, "\n".join(problems)


def test_json_examples_parse(texts, tmp_path):
    import dashboard

    for name, text in texts.items():
        for block in re.findall(r"```json\n(.*?)```", text, re.S):
            json.loads(block)
    comp = re.search(r"## Competitor log.*?```json\n(.*?)```", texts["scout"], re.S)
    assert comp, "scout.md: competitor log example missing"
    f = tmp_path / "competitors_2026-12.json"
    f.write_text(comp.group(1), encoding="utf-8")
    data = dashboard.load_competitors(str(f))
    assert data["accounts"][0]["handle"]


# ---------------------------------------------------------------------------
# make-reel.md required content
# ---------------------------------------------------------------------------
FAILURE_ROWS = {
    "F1": ["No voiceover", "consent.voice_clone", "preset voice", "Music-only reel"],
    "F2": ["No music", "Higgsfield instrumental", "Music Library", "pad"],
    "F3": ["Too few photos or clips", "Scout", "library.py query", "brand photos", "later day"],
    "F4": ["Landscape photo", "outpaint", "pan-across", "Blurred-fill"],
    "F5": ["Low-resolution or blurry", "upscale to 2K", "montage", "Drop it"],
    "F6": ["Shaky or dark clip", "prep_media.py", "upscale/denoise", "motion clip from a still"],
    "F7": ["warps a face", "Re-roll once", "Switch model", "engine motion"],
    "F8": ["Credits running low", "strongest days", "Engine motion only", "Never buy credits"],
    "F9": ["Transcript mishears", "fix_transcript.py", "transcript_fixes", "Captions from the script"],
    "F10": ["Critic fails 3 rounds", "best-scoring", "10-15 s", "later day"],
    "F11": ["Health or results claim", "experience language", "Remove the line", "Never ship it"],
    "F12": ["not on the Consent List", "blur", "different shot", "Drop the shot"],
    "F13": ["Closure or holiday", "evergreen", "Story instead", "Skip the day"],
    "F14": ["Render or encode crash", "saved files", "--draft", "one hour", "reschedule"],
    "F15": ["connector down", "15 minutes", "local copy", "queue uploads", "Monday digest"],
    "F16": ["Topic-only mode", "scriptwriter", "consent.voice_clone", "Music Library", "B-roll"],
    "F17": ["Chrome or the desktop app unavailable", "web search", "Media library", "brand photos"],
}


def failure_table(text: str) -> dict[str, str]:
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(F\d+)\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_failure_table_complete(texts):
    rows = failure_table(texts["make-reel"])
    assert list(rows) == list(FAILURE_ROWS), "failure rows must be F1..F17 in order"
    for fid, needles in FAILURE_ROWS.items():
        cells = [c.strip() for c in rows[fid].split("|")]
        assert len(cells) == 4 and all(cells), f"{fid}: needs what went wrong + 3 moves"
        for needle in needles:
            assert needle.lower() in rows[fid].lower(), f"{fid}: missing {needle!r}"


def test_fallback_logging_rule(texts):
    t = texts["make-reel"]
    assert "fallback F<n>.<move>" in t  # R110: log which fallback was used
    assert re.search(r"\| F3\.2\b", t), "Decisions log example shows a fallback entry"


STAGES = [
    ("1. Ingest", ["librarian", "Google Drive connector", "HEIC"]),
    ("2. Analyze", ['analyze.py" "$JOB/raw" "$JOB/work" --script', 'fix_transcript.py" "$JOB/work/analysis.json" --script']),
    ("3. Vision", ['vision.py"', 'prep_media.py"']),
    ("4. Material check", ["shoot card", "scout", "Claude in Chrome", "web search", "library.py\" query", "brand photos", "sources.py\" add"]),
    ("5. Story and shot plan", ["baseline_plan.py", "--template", "--before", "--after", "--turn", "--script", "--hook", "edit grammar"]),
    ("6. Motion", ["motion agent", "ledger.py\" check", "ai.label_required"]),
    ("7. Validate", ['validate_plan.py"', "0 ERRORs"]),
    ("8. Preview", ["preview", "LOOK", "repeat"]),
    ("9. Render and finish", ['engine.py" "$JOB/work/plan.json"', 'finish.py"', 'check_output.py"', 'qa_frames.py"']),
    ("10. Critic loop", ["max 3 rounds", "fresh context", 'critic_score.py" round', "ship_best", "hold", "numa-brand-check"]),
    ("11. All outputs", ['formats.py" "$JOB/work/plan.json" "$JOB/out/SLUG_reel.mp4"', "reach", "Story", "carousel", "cover", ".srt", "hook variants"]),
    ("12. Caption", ["3 captions", "You pick one", 'claims_scan.py"', "--hashtags"]),
    ("13. Deliver", ["Send the reel file in this chat", "Chat delivery is primary", "Finished/", "upload_queue.json", "Ready to post", "post-reel", "delivery note", "media library"]),
]


def test_stage_flow_in_order(texts):
    t = texts["make-reel"]
    starts = [t.find(f"**{head}") for head, _ in STAGES]
    assert all(i > 0 for i in starts), [h for (h, _), i in zip(STAGES, starts) if i < 0]
    assert starts == sorted(starts), "stages out of order"
    ends = starts[1:] + [t.find("## 4. Failure")]
    for (head, needles), i, j in zip(STAGES, starts, ends):
        section = t[i:j]
        for needle in needles:
            assert needle in section, f"stage {head!r}: missing {needle!r}"


def test_folder_resolution_order_r13(texts):
    t = texts["make-reel"]
    order = ["`$ARGUMENTS` names a folder", "is `newest`", "is a date", "today's row in the plan Sheet",
             "Else the newest dated day folder", "attached in this chat"]
    idx = [t.find(s) for s in order]
    assert all(i > 0 for i in idx) and idx == sorted(idx), idx


def test_inputs_prefs_and_steering(texts):
    t = texts["make-reel"]
    for needle in ["$ARGUMENTS", "SHOOT CARD", "note.txt", "never a required step", 'prefs.py" list',
                   'prefs.py" add', "PREFS", "Closure check"]:
        assert needle in t, needle
    # every call that takes --prefs gets it (R277)
    for script in ("baseline_plan.py", "validate_plan.py"):
        for seg in code_segments(t):
            if f'{script}"' in seg:
                assert "PREFS" in seg, f"{script} call without PREFS: {seg!r}"


def test_decision_authority_and_escalation(texts, brand):
    t = texts["make-reel"]
    for needle in ["Never ask Katie anything", "No step waits", "Never stop", "Fixed limits are rules",
                   "Tell, don't ask", "Decision authority", "Meta error 190", "card payment fails",
                   "legal_review_done", "`escalation.contact`", "work continues"]:
        assert needle.lower() in t.lower(), needle
    assert len(brand["escalation"]["for"]) == 3


def test_parallel_crews_and_resumability(texts):
    t = texts["make-reel"]
    for needle in ["in parallel with the librarian", "**analyst**", "**copywriter**", "one Editor per run",
                   "never start two renders at once", "Resumability", "newer than every input", "re-run one stage"]:
        assert needle.lower() in t.lower(), needle


def test_decisions_log_and_note_templates(texts):
    t = texts["make-reel"]
    assert "HH:MM | stage | decision | why | fallback" in t
    note = re.search(r"## 6\. Delivery note.*?```(.*?)```(.*?)\n## ", t, re.S)
    assert note, "delivery note template missing"
    tmpl = note.group(1)
    for needle in ["Story:", "Captions (", "\n1. ", "\n2. ", "\n3. ", "Made:", "Decided (", "Status:"]:
        assert needle in tmpl, needle
    assert "?" not in tmpl, "the note never asks"
    assert max(len(line) for line in tmpl.splitlines()) <= 72, "phone-readable lines"


def test_no_credit_path_and_closures(texts):
    t = texts["make-reel"]
    assert "renders without motion clips" in t  # R33
    assert "evergreen" in t and "Story instead" in t and "Skip the day" in t  # R107


# ---------------------------------------------------------------------------
# agents required content
# ---------------------------------------------------------------------------
def test_librarian_steps(texts):
    t = texts["librarian"]
    for needle in ["`JOB/raw/`", "keeping Drive subfolders", "HEIC", "SHOOT CARD", "work/script.txt",
                   "inventory.json", '"missing"', "Match by content", 'analyze.py" "$JOB/raw" "$JOB/work" --no-transcribe',
                   'library.py" add', "never contact Katie"]:
        assert needle in t, needle
    assert t.find("## 1. Download") < t.find("## 3. Check against the shoot card") < t.find("## 4. Report")


def test_scout_search_order_and_rules(texts):
    t = texts["scout"]
    order = ["NUMA's own channels", "NUMA's own accounts", "Free stock", "Royalty-free music", "Facts for the script"]
    idx = [t.find(s) for s in order]
    assert all(i > 0 for i in idx) and idx == sorted(idx), idx
    for needle in ["Never take other businesses' or creators'", "Consent List", "license page", "sources.py\" add",
                   "raw/scout/", "cloud web search", "Never wait for the desktop app", "the Director decides",
                   "positioning.competitors", "competitors_YYYY-MM.json", "dashboard.py --competitors",
                   "last 12 posts", "never an estimate"]:
        assert needle in t, needle


def test_analyst_steps(texts):
    t = texts["analyst"]
    for needle in ['analyze.py"', 'fix_transcript.py"', 'vision.py"', 'prep_media.py"', "contact_photos.jpg",
                   "work/ratings.json", "best_window", '"ranked"', "uncovered_lines", "`business.name`",
                   "`team.collective`", "script is the truth", "consent_list.json"]:
        assert needle in t, needle


# ---------------------------------------------------------------------------
# R119 lint: no question to Katie, no confirm/approval step
# ---------------------------------------------------------------------------
LINT_PATTERNS = [
    r"\bask(?:s|ing)?\s+(?:katie|her|the user|the owner)\b",
    r"\bask(?:s|ing)?\b[^.?!]{0,40}\bkatie\b",
    r"\bkatie\b[^.!?]*\?",
    r"\bcheck(?:s|ing)? with (?:katie|her)\b",
    r"\bconfirm(?:s|ing)? with\b",
    r"\bconfirm(?:ation)? step\b",
    r"\bwhich (?:one )?do you prefer\b",
    r"\bwould you like\b",
    r"\bdo you want\b",
    r"\bwant me to\b",
    r"\bshall i\b",
    r"\bshould i\b",
    r"\blet me know\b",
    r"\bwait(?:s|ing)? (?:for|on) (?:katie|her|the user|approval|confirmation|a reply|an answer)\b",
    r"\b(?:get|ask for|request|needs?|await)s? (?:katie'?s? |her )?(?:approval|sign-?off|go-?ahead|confirmation)\b",
    r"\bbefore (?:posting|rendering|spending|continuing),? (?:ask|confirm|check with)\b",
]
LINT_RE = re.compile("|".join(LINT_PATTERNS), re.I)
NEGATION = re.compile(r"\b(?:never|no|not|don't|do not|nothing|none|without|isn't|is not|zero)\b", re.I)

# Setup questionnaire: the only place questions belong (R119; docs/QUESTIONS_FOR_KATIE.md is not scanned).
LINT_EXEMPT = {"commands/numa-setup.md", "commands/brand-setup.md"}
# Files owned by other tasks that still fail the lint; the integration task (T11) empties this list.
LINT_XFAIL: set[str] = set()


def runtime_instruction_files() -> list[str]:
    files = sorted(REPO.glob("commands/*.md")) + sorted(REPO.glob("agents/*.md")) + sorted(REPO.glob("skills/*/SKILL.md"))
    return [p.relative_to(REPO).as_posix() for p in files if p.relative_to(REPO).as_posix() not in LINT_EXEMPT]


# Names that contain a trigger word but are not questions (brand.json positioning.series).
LINT_ALLOW = re.compile(r"\bask the dpt\b", re.I)


def lint_hits(text: str) -> list[str]:
    text = LINT_ALLOW.sub("", text)
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for sentence in re.split(r"(?<=[.;!?])\s+|\s+-\s+", line):
            for m in LINT_RE.finditer(sentence):
                if NEGATION.search(sentence[: m.start()]):
                    continue
                hits.append(f"line {n}: {m.group(0)!r} in {sentence.strip()[:120]!r}")
    return hits


@pytest.mark.parametrize("rel", [
    pytest.param(r, marks=pytest.mark.xfail(reason="pending T8b/T9/T10 rewrite", strict=False))
    if r in LINT_XFAIL else r
    for r in runtime_instruction_files()
])
def test_r119_no_questions_or_confirm_steps(rel):
    hits = lint_hits((REPO / rel).read_text(encoding="utf-8"))
    assert not hits, f"{rel} asks Katie or adds a confirm step (R119):\n" + "\n".join(hits)


@pytest.mark.parametrize("bad", [
    "Ask Katie which photo she likes.",
    "Confirm with Katie before posting.",
    "Which do you prefer, A or B?",
    "Wait for her approval, then render.",
    "Get Katie's approval on the caption.",
    "Let me know if you want changes.",
    "Want me to post it now?",
    "List the folders and ask which one Katie will use.",
    "Katie, is this caption OK?",
])
def test_r119_lint_catches(bad):
    assert lint_hits(bad), bad


@pytest.mark.parametrize("good", [
    "Never ask Katie anything.",
    "There is no confirm step anywhere in this pipeline.",
    "No step waits for approval or a reply.",
    "Nothing waits on her approval.",
    "Katie is informed, never asked.",
    "Series: Ask the DPT (Katie, education only).",
])
def test_r119_lint_allows_negated_rules(good):
    assert not lint_hits(good), good


def test_r119_exemptions_are_setup_only():
    assert all("setup" in f for f in LINT_EXEMPT)
    for rel in LINT_XFAIL:
        assert (REPO / rel).exists(), f"stale xfail entry {rel}"
        assert rel not in {p.relative_to(REPO).as_posix() for p in OWNED.values()}, "owned files may not be xfailed"
