"""Release and cross-file consistency checks (R1-R2, R304, R309, R314, R319-R326).

Run before every release (README "Release checklist"): versions agree, every script is documented
in docs/CONTRACTS.md section 9 and the other way round, README names every command, agent and skill,
no secrets or media outside the bundled assets, nothing reads the git-ignored spec/ folder at run
time, and every .py file parses with the Python 3.10 grammar.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess

import pytest

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
MEDIA = re.compile(r"\.(jpe?g|png|gif|heic|heif|webp|tiff?|mp4|mov|m4v|avi|mkv|mp3|wav|m4a|aac|flac|ogg)$", re.I)
SECRET = re.compile(
    r"(AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"
    r"|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}|xox[abpr]-[A-Za-z0-9-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|AIza[0-9A-Za-z_-]{35}|EAA[A-Za-z0-9]{40,}|ya29\.[0-9A-Za-z_-]{20,}|hf_[A-Za-z0-9]{30,}"
    r"|(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9/+_-]{24,}['\"])",
    re.I,
)
BINARY = {".png", ".jpg", ".jpeg", ".ttf", ".otf", ".onnx", ".pdf", ".heic", ".mp4", ".mp3", ".wav", ".pyc"}


@pytest.fixture(scope="module")
def files(repo_root):
    """Tracked files plus untracked files that are not git-ignored (what the next commit would ship)."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=repo_root,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return sorted({f for f in out.stdout.splitlines() if f and (repo_root / f).is_file()})


@pytest.fixture(scope="module")
def manifest(repo_root):
    return json.loads((repo_root / ".claude-plugin" / "plugin.json").read_text())


# ---------------------------------------------------------------- versions

def test_versions_match(repo_root, manifest):
    market = json.loads((repo_root / ".claude-plugin" / "marketplace.json").read_text())
    version = manifest["version"]
    assert SEMVER.match(version)
    assert [p["version"] for p in market["plugins"]] == [version]
    changelog = (repo_root / "CHANGELOG.md").read_text()
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})", changelog, re.M)
    assert released and released[0][0] == version, "the newest CHANGELOG release must be the manifest version"
    assert f"[{version}]: https://github.com/CordiaJude/numa-studio/" in changelog, "CHANGELOG link for the release"


def test_changelog_records_golden_test(repo_root, manifest):
    """R314: every release re-runs the M2 golden test and records it."""
    changelog = (repo_root / "CHANGELOG.md").read_text()
    start = changelog.index(f"## [{manifest['version']}]")
    nxt = changelog.find("\n## [", start + 5)
    section = changelog[start:nxt if nxt > 0 else None]
    assert re.search(r"golden", section, re.I), "release section must record the M2 golden test result"


def test_readme_release_checklist_r314(repo_root):
    readme = (repo_root / "README.md").read_text()
    assert "Release checklist" in readme
    assert "golden_year_one.py" in readme and "does not ship" in readme


# ---------------------------------------------------------------- scripts <-> contracts

def _cli_scripts(repo_root):
    """Pipeline scripts: files in scripts/ with a __main__ entry point (helper modules have none)."""
    d = repo_root / "skills" / "numa-reel-editor" / "scripts"
    return sorted(p.name for p in d.glob("*.py") if '__name__ == "__main__"' in p.read_text()
                  or "__name__ == '__main__'" in p.read_text())


def _contract_scripts(repo_root):
    text = (repo_root / "docs" / "CONTRACTS.md").read_text()
    sec = text[text.index("## 9. Script command lines"):]
    return sorted(set(re.findall(r"^### ([a-z_]+\.py)\b", sec, re.M)))


def test_every_script_has_a_contract_entry(repo_root):
    missing = sorted(set(_cli_scripts(repo_root)) - set(_contract_scripts(repo_root)))
    assert not missing, f"scripts without a docs/CONTRACTS.md section 9 entry: {missing}"


def test_every_contract_entry_has_a_script(repo_root):
    scripts = set(_cli_scripts(repo_root))
    missing = sorted(set(_contract_scripts(repo_root)) - scripts)
    assert not missing, f"CONTRACTS.md section 9 documents scripts that do not exist: {missing}"


def test_helper_modules_are_not_scripts(repo_root):
    d = repo_root / "skills" / "numa-reel-editor" / "scripts"
    helpers = sorted(p.name for p in d.glob("*.py"))
    helpers = [h for h in helpers if h not in _cli_scripts(repo_root)]
    assert "numa_common.py" in helpers
    for h in helpers:  # imported by a script, so they ship with a reason
        stem = h[:-3]
        assert any(re.search(rf"^\s*(import {stem}\b|from {stem} import)", p.read_text(), re.M)
                   for p in d.glob("*.py") if p.name != h), f"{h} is neither a script nor imported"


# ---------------------------------------------------------------- README coverage (R322)

def test_readme_names_every_command_agent_skill_script(repo_root):
    readme = (repo_root / "README.md").read_text()
    for p in sorted((repo_root / "commands").glob("*.md")):
        assert f"/{p.stem}" in readme, f"README does not mention /{p.stem}"
    for p in sorted((repo_root / "agents").glob("*.md")):
        assert f"`{p.stem}`" in readme, f"README does not mention the {p.stem} agent"
    for p in sorted((repo_root / "skills").glob("*/SKILL.md")):
        assert p.parent.name in readme, f"README does not mention the {p.parent.name} skill"
    for name in _cli_scripts(repo_root):
        assert name in readme, f"README does not list {name}"


def test_readme_sections_r322(repo_root):
    readme = (repo_root / "README.md").read_text()
    for needle in ("/plugin marketplace add CordiaJude/numa-studio", "/plugin install numa-studio@numa-studio",
                   "## Daily use", "## Commands", "Scheduled tasks", "pip install -r requirements.txt",
                   "tests/run_tests.py", "NUMA_TEST_PACK", "pytest tests/unit", "## Privacy and licensing"):
        assert needle in readme, needle


def test_readme_documents_every_env_var(repo_root, files):
    used = set()
    for f in files:
        if f.endswith((".py", ".md")) and not f.startswith("spec/"):
            used |= set(re.findall(r"\bNUMA_[A-Z][A-Z_]+\b", (repo_root / f).read_text(errors="ignore")))
    used -= {"NUMA_PLUGIN"}  # the /NUMA_PLUGIN/ placeholder prefix in the example plan, not a variable
    readme = (repo_root / "README.md").read_text()
    missing = sorted(v for v in used if v not in readme)
    assert not missing, f"environment variables not in the README: {missing}"


def test_readme_links_resolve(repo_root):
    readme = (repo_root / "README.md").read_text()
    for target in re.findall(r"\]\(([^)#]+)\)", readme):
        if target.startswith(("http://", "https://")):
            continue
        assert (repo_root / target).exists(), f"README links to a missing file: {target}"


# ---------------------------------------------------------------- hygiene (R323, R324)

def test_no_secrets(repo_root, files):
    hits = []
    for f in files:
        p = repo_root / f
        if p.suffix.lower() in BINARY:
            continue
        for m in SECRET.finditer(p.read_text(errors="ignore")):
            hits.append(f"{f}: {m.group(0)[:12]}...")
    assert not hits, f"possible secrets: {hits}"


def test_no_media_outside_assets(repo_root, files):
    stray = [f for f in files if MEDIA.search(f) and not f.startswith("skills/numa-reel-editor/assets/")]
    assert not stray, f"media files outside skills/numa-reel-editor/assets/: {stray}"


def test_spec_folder_is_ignored_and_unshipped(repo_root, files):
    assert "spec/" in (repo_root / ".gitignore").read_text().split()
    assert not [f for f in files if f.startswith("spec/")]


def test_no_runtime_reference_to_spec_folder(repo_root, files):
    """Nothing the plugin runs (scripts, commands, agents, skills, data) may read the git-ignored spec/
    folder: it is not there on an installed plugin. Citations of the brief (spec/SPEC.pdf) in prose are fine."""
    runtime = [f for f in files if f.startswith(("skills/", "commands/", "agents/", "config/", "brand/", "schemas/"))
               or f in ("tests/run_tests.py", "tests/golden_year_one.py")]
    bad = []
    for f in runtime:
        text = (repo_root / f).read_text(errors="ignore")
        if f.endswith(".py"):
            pattern = r"""['"/]spec/|\bspec/(kit|test-pack|SPEC)"""
        else:
            pattern = r"\bspec/(?!SPEC\.(pdf|txt)\b)"
        for m in re.finditer(pattern, text):
            line = text.count("\n", 0, m.start()) + 1
            bad.append(f"{f}:{line}")
    assert not bad, f"run-time references to spec/: {bad}"


def test_no_kit_paths_in_scripts(repo_root, files):
    pattern = re.compile(r"(NUMA_Studio_Developer_Kit|test-pack|Year_One_hand_built_reference)")
    for f in files:
        if f.startswith("skills/") and f.endswith(".py"):
            assert not pattern.search((repo_root / f).read_text()), f"{f} names a developer-kit path"


# ---------------------------------------------------------------- Python 3.10 (R326)

def test_every_py_parses_as_python_310(repo_root, files):
    bad = []
    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            ast.parse((repo_root / f).read_text(encoding="utf-8"), filename=f, feature_version=(3, 10))
        except SyntaxError as e:
            bad.append(f"{f}:{e.lineno}: {e.msg}")
    assert not bad, f"not valid Python 3.10 syntax: {bad}"


def test_ci_runs_the_suites_r309(repo_root):
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ("push", "pull_request", '"3.10"', '"3.12"', "pytest tests/unit", "tests/run_tests.py",
                   "feature_version=(3, 10)", "huggingface", "ffmpeg"):
        assert needle in ci, needle
    try:
        import yaml
    except ImportError:
        return
    doc = yaml.safe_load(ci)
    assert {"parse", "unit", "end-to-end"} <= set(doc["jobs"])
