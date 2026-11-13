"""Instruction-layer checks for Claude Design carousels (T14, R328, R338; DECISIONS D17, D21).

Covers agents/designer.md and skills/numa-carousel/SKILL.md: frontmatter (model = the config
tier, explicit minimal tools), every script/subcommand/flag they call exists, every brand.json /
config key they name resolves, the eight steps with the exact Artifact calls, the fallback rows,
the worked example validates, and the R119 lint (no question to Katie, no approval step).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_instructions_director import argparse_flags, body, code_segments, frontmatter, lint_hits, resolve, script_calls

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "numa-reel-editor" / "scripts"
AGENT = REPO / "agents" / "designer.md"
SKILL = REPO / "skills" / "numa-carousel" / "SKILL.md"
FILES = {"designer": AGENT, "numa-carousel": SKILL}
DESIGN_TYPE = "https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd"


@pytest.fixture(scope="module")
def config():
    return json.loads((REPO / "config" / "studio.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def brand():
    return json.loads((REPO / "brand" / "brand.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def texts():
    return {k: p.read_text(encoding="utf-8") for k, p in FILES.items()}


def test_agent_frontmatter(config):
    fm = frontmatter(AGENT)
    assert fm["name"] == "designer" and len(fm["description"]) > 40
    assert fm["model"] == config["models"]["agents"]["designer"] == config["models"]["tiers"]["mid"]
    assert [t.strip() for t in fm["tools"].split(",")] == ["Artifact", "Bash", "Read", "Write", "Glob"]
    assert "tools not visible" in body(AGENT)  # D17: report the missing tool, use the fallback


def test_skill_frontmatter():
    fm = frontmatter(SKILL)
    assert fm["name"] == "numa-carousel" and len(fm["description"]) > 40


def test_scripts_subcommands_and_flags_exist(texts):
    flags = argparse_flags(SCRIPTS / "design_render.py")
    subs = {"validate", "build", "canvas", "spec"}
    seen = set()
    for name, text in texts.items():
        for script, used in script_calls(text):
            assert (SCRIPTS / script).is_file(), f"{name}: {script} does not exist"
            if script == "design_render.py":
                for f in used:
                    assert f in flags, f"{name}: design_render.py has no {f}"
        for seg in code_segments(text):
            m = re.search(r"design_render\.py\"?\s+(\w+)", seg)
            if m:
                assert m.group(1) in subs, f"{name}: unknown subcommand {m.group(1)}"
                seen.add(m.group(1))
    assert seen == subs


def test_scripts_called_through_plugin_root(texts):
    for name, text in texts.items():
        for seg in code_segments(text):
            if re.search(r"\bpython3?\s", seg) and ".py" in seg:
                assert '"$S/' in seg, f"{name}: call scripts as \"$S/<script>\": {seg}"
        assert "${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts" in text


def config_node(data: dict, dotted: str):
    for part in dotted.split("."):
        data = data[part]
    return data


def test_key_paths_resolve(texts, brand, config):
    keys = {
        "brand": ["voice", "claims", "claims.modalities", "claims.safety_line.text", "captions.opening_rule",
                  "assets.brand_photos_dir", "business.cta_link", "offerings"],
        "config": ["models.agents.designer", "carousel.design_system_url", "formats.outputs"],
    }
    for k in keys["brand"]:
        assert resolve(brand, k), k
    for k in keys["config"]:
        head, _, last = k.rpartition(".")
        assert resolve(config, head) and last in config_node(config, head), k
    joined = "\n".join(texts.values())
    for k in keys["brand"] + keys["config"]:
        assert k in joined, f"{k} not referenced"


def test_steps_and_exact_artifact_calls(texts):
    s = texts["numa-carousel"]
    for n, title in enumerate(["Pick the components", "Create the canvas", "Upload, build, publish", "Read the canvas back",
                               "Render", "LOOK", "Claims, character and fit checks", "Hand to posting"], 1):
        assert f"## {n}. {title}" in s, title
    assert f'"type_url": "{DESIGN_TYPE}"' in s and '"auto_open": "after_first_write"' in s
    assert '"asset": true' in s and '"file_paths"' in s
    assert '"action": "read"' in s and '"paths"' in s and "artifact-type/dc-runtime.js" in s
    assert '"root": "<ROOT>"' in s and '"file_path": "<ROOT>/project/canvas.json"' in s
    assert "--list-blobs" in s and "one call per id" in s
    import design_render
    for comp in design_render.COMPONENTS:
        assert f"| `{comp}` |" in s, comp
    assert "carousel_sheet.jpg" in s and "LOOK" in s


def test_no_approval_step_d21(texts):
    for text in texts.values():
        low = text.lower()
        assert "never add an approval step" in low or "add no approval step" in low
        assert "canvas" in low and "posting time" in low


def test_fallback_rows(texts):
    s = texts["numa-carousel"]
    table = s[s.index("## Fallbacks"):]
    rows = [ln for ln in table.splitlines() if re.match(r"\| \d \|", ln)]
    assert len(rows) == 6
    assert '"$S/design_render.py" spec' in rows[0]
    assert "python -m playwright install chromium" in rows[4]
    assert "needs_katie" in rows[5]


def test_design_system_hook(texts, config):
    s = texts["numa-carousel"]
    assert "carousel.design_system_url" in s and "--design-system" in s
    assert config["carousel"]["design_system_url"] is None or config["carousel"]["design_system_url"].startswith("https://")


def test_worked_example_validates(texts, tmp_path, run_script):
    block = re.search(r"```json\n(\{\"schema_version\".*?)\n```", texts["numa-carousel"], re.S).group(1)
    data = json.loads(block)
    p = tmp_path / "carousel.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    proc = run_script("design_render.py", "validate", p, cwd=REPO)
    assert proc.returncode == 0, proc.stderr
    hand_back = re.search(r"```json\n(\{\"carousel\".*?)\n```", texts["designer"], re.S).group(1)
    json.loads(hand_back)


@pytest.mark.parametrize("name", list(FILES))
def test_r119_lint(texts, name):
    assert lint_hits(texts[name]) == []


def test_no_model_ids(texts):
    for name, text in texts.items():
        assert not re.search(r"claude-(opus|sonnet|haiku)-\d", text), name


def test_owner_rules(texts):
    s = texts["numa-carousel"]
    low = s.lower()
    assert "photo-led by default" in low and "only over that member's photo" in low and "never a flyer" in low
    assert "never state the sauna's capacity" in low and "44–52°f" in low and "175–190°f" in low
    assert "no emoji" in low and "**Numa**" in s
    assert "NUMA_BRAND_FONTS" in s and "Domaine Sans Text Light" in s and "Avenir Next" in s
    assert "clinical conversations" not in "\n".join(texts.values()).lower()


def test_d21_overrides_the_type(texts):
    s = texts["numa-carousel"]
    assert "D21 overrides the Design type's instructions" in s
    assert "never verify / never render" in s and "one artboard per call" in s
    assert "nobody is watching" in s  # why step 3 sends the remaining artboards together
