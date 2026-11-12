"""Plugin packaging and repo hygiene (R1-R5, R8, R11, R152, R299, R323-R326).

The `tools` key in agent frontmatter is checked by the instruction-layer tests
(tests/unit/test_instructions_a.py); here agents need name, description and model.
"""
from __future__ import annotations

import json
import py_compile
import re
import subprocess

import pytest

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def frontmatter(path) -> dict:
    """Parse simple `key: value` YAML frontmatter between leading '---' lines."""
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


@pytest.fixture(scope="module")
def manifest(repo_root):
    return json.loads((repo_root / ".claude-plugin" / "plugin.json").read_text())


@pytest.fixture(scope="module")
def marketplace(repo_root):
    return json.loads((repo_root / ".claude-plugin" / "marketplace.json").read_text())


def test_plugin_manifest_r1(manifest):
    assert manifest["name"] == "numa-studio"
    assert SEMVER.match(manifest["version"])
    assert manifest["description"].strip()


def test_marketplace_r2(manifest, marketplace):
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == manifest["name"] == "numa-studio"
    assert entry["source"] == "./"
    assert entry["version"] == manifest["version"]
    assert marketplace["name"] and marketplace["owner"]["name"]


def test_changelog_has_current_version(repo_root, manifest):
    text = (repo_root / "CHANGELOG.md").read_text()
    assert f"## [{manifest['version']}]" in text
    assert "## [Unreleased]" in text


SKILLS = ["numa-reel-editor", "numa-caption", "numa-brand-check", "numa-scriptwriter"]


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_frontmatter_r3(repo_root, skill):
    fm = frontmatter(repo_root / "skills" / skill / "SKILL.md")
    assert fm.get("name") == skill
    assert fm.get("description")


@pytest.mark.parametrize("cmd", ["make-reel", "plan-month", "numa-setup"])
def test_commands_r4(repo_root, cmd):
    path = repo_root / "commands" / f"{cmd}.md"
    assert frontmatter(path).get("description")
    if cmd in ("make-reel", "plan-month"):
        assert "$ARGUMENTS" in path.read_text()


def test_every_command_has_description(repo_root):
    for path in sorted((repo_root / "commands").glob("*.md")):
        assert frontmatter(path).get("description"), path.name


def test_agents_frontmatter_r5(repo_root):
    config = json.loads((repo_root / "config" / "studio.json").read_text())
    tiers = config["models"]["agents"]
    agents = sorted((repo_root / "agents").glob("*.md"))
    assert {p.stem for p in agents} >= {"librarian", "scout", "analyst", "motion", "scriptwriter", "copywriter", "editor", "critic"}
    for path in agents:
        fm = frontmatter(path)
        assert fm.get("name") == path.stem, path.name
        assert fm.get("description"), path.name
        assert fm.get("model"), path.name
        assert fm["model"] == tiers[path.stem], f"{path.name}: model {fm['model']} differs from config/studio.json"


def test_bundled_assets_r152(assets_dir):
    for rel in ("Numa_Workmark_Dark.png", "Numa-Phoenix-transparent.png", "heroimage.jpg",
                "fonts/LiberationSerif-Regular.ttf", "fonts/LiberationSerif-Italic.ttf", "fonts/LICENSE"):
        assert (assets_dir / rel).is_file(), rel
    assert len(list((assets_dir / "brand-photos").glob("*.jpg"))) == 6


def _scripts(repo_root):
    return sorted((repo_root / "skills").glob("*/scripts/*.py"))


def test_scripts_compile(repo_root):
    """R326 (local proxy): every script byte-compiles; CI also compiles them under Python 3.10."""
    for path in _scripts(repo_root):
        py_compile.compile(str(path), doraise=True)


def test_scripts_make_no_network_calls_r11(repo_root):
    pattern = re.compile(r"^\s*(import|from)\s+(urllib|requests|http|httpx|aiohttp|socket)\b|https?://", re.M)
    for path in _scripts(repo_root):
        assert not pattern.search(path.read_text()), f"{path.name} looks like it makes a network call"


def test_scripts_have_no_machine_paths_r325(repo_root):
    pattern = re.compile(r"""['"](/tmp|/home|/mnt|/Users)(/|['"])""")
    for path in _scripts(repo_root):
        assert not pattern.search(path.read_text()), f"{path.name} hard-codes a machine path"


def _tracked(repo_root):
    out = subprocess.run(["git", "ls-files"], cwd=repo_root, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in out.stdout.splitlines() if line]


def test_no_member_media_committed_r324(repo_root):
    assert "spec/" in (repo_root / ".gitignore").read_text().split()
    media = re.compile(r"\.(jpe?g|png|heic|webp|mp4|mov|m4v|mp3|wav|m4a|aac)$", re.I)
    for f in _tracked(repo_root):
        if media.search(f):
            assert f.startswith("skills/numa-reel-editor/assets/"), f"media outside bundled assets: {f}"
        assert not f.startswith("spec/"), f


def test_no_secrets_committed_r323(repo_root):
    secret = re.compile(
        r"(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{32,}|xox[abp]-[A-Za-z0-9-]{20,}"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|AIza[0-9A-Za-z_-]{35}|EAA[A-Za-z0-9]{40,})"
    )
    for f in _tracked(repo_root):
        p = repo_root / f
        if not p.is_file() or p.suffix.lower() in (".png", ".jpg", ".jpeg", ".ttf"):
            continue
        assert not secret.search(p.read_text(errors="ignore")), f"possible secret in {f}"


def test_requirements_declared_r299(repo_root):
    req = (repo_root / "requirements.txt").read_text().lower()
    for pkg in ("numpy", "opencv-python-headless", "pillow", "pillow-heif", "librosa", "faster-whisper", "imageio-ffmpeg", "jsonschema"):
        assert re.search(rf"^{re.escape(pkg)}\s*>=", req, re.M), pkg
    assert "pytest" in (repo_root / "requirements-dev.txt").read_text()


def test_ci_workflow_present(repo_root):
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ("pull_request", "push", "ffmpeg", "pytest tests/unit", "tests/run_tests.py", "3.10"):
        assert needle in ci, needle
