"""Release and cross-file consistency checks (R1-R2, R304, R309, R314, R319-R326).

Run before every release (README "Release checklist"): versions agree, every script is documented
in docs/CONTRACTS.md section 9 and the other way round, README names every command, agent and skill,
no secrets or media outside the bundled assets, nothing reads the git-ignored spec/ folder at run
time, and every .py file parses with the Python 3.10 grammar.

The Python 3.10 parse uses ast's `feature_version=(3, 10)`, which is best-effort: newer interpreters
do not reject every post-3.10 construct (a backslash inside an f-string expression slipped past it).
So when a real `python3.10` is on PATH the same files are also parsed with it (one subprocess);
without one that check is skipped. CI's parse job (a real 3.10) and the 3.10 unit-test job are
authoritative.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys

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


PARSE_WITH_THIS_INTERPRETER = """
import ast, sys
bad = []
for f in sys.stdin.read().splitlines():
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read(), filename=f)
    except SyntaxError as e:
        bad.append(f"{f}:{e.lineno}: {e.msg}")
print("\\n".join(bad))
sys.exit(1 if bad else 0)
"""


def test_every_py_parses_with_a_real_python_310(repo_root, files):
    """feature_version misses some 3.12-only syntax; a real 3.10 interpreter does not."""
    exe = shutil.which("python3.10")
    if sys.version_info[:2] == (3, 10):
        exe = sys.executable
    if not exe:
        pytest.skip("no python3.10 on PATH (CI's parse job runs a real 3.10)")
    py = [f for f in files if f.endswith(".py")]
    r = subprocess.run([exe, "-I", "-c", PARSE_WITH_THIS_INTERPRETER], input="\n".join(py), cwd=repo_root,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"not valid Python 3.10 syntax (real 3.10):\n{r.stdout}{r.stderr}"


def test_ci_runs_the_suites_r309(repo_root):
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ("push", "pull_request", '"3.10"', '"3.12"', "pytest tests/unit", "tests/run_tests.py",
                   "huggingface", "ffmpeg", "brew install ffmpeg", "macos-latest"):
        assert needle in ci, needle
    try:
        import yaml
    except ImportError:
        return
    doc = yaml.safe_load(ci)
    jobs = doc["jobs"]
    assert {"parse", "unit", "unit-macos", "end-to-end"} <= set(jobs)
    # R326: the parse job runs a real Python 3.10, not ast feature_version on a newer interpreter
    setup = [s for s in jobs["parse"]["steps"] if str(s.get("uses", "")).startswith("actions/setup-python")]
    assert [s["with"]["python-version"] for s in setup] == ["3.10"]
    assert "ast.parse" in json.dumps(jobs["parse"]["steps"])
    # R298: macOS (the primary platform) runs the unit tests on 3.12
    mac = jobs["unit-macos"]
    assert mac["runs-on"] == "macos-latest"
    assert any(s.get("with", {}).get("python-version") == "3.12" for s in mac["steps"])
    assert any("pytest tests/unit" in str(s.get("run", "")) for s in mac["steps"])


# ---------------------------------------------------------------- run-time brand data (DECISIONS D18)

D18_FILES = ["commands/make-reel.md", "commands/build-today.md", "commands/plan-month.md",
             "commands/night-check.md", "commands/digest.md", "commands/dashboard-refresh.md",
             "commands/trend-check.md", "commands/post-reel.md", "agents/librarian.md"]


@pytest.mark.parametrize("name", D18_FILES)
def test_run_files_point_numa_brand_at_state_copy_d18(repo_root, name):
    text = (repo_root / name).read_text()
    line = 'if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi'
    assert text.count(line) == 1, f"{name}: the D18 NUMA_BRAND line, once, in the setup section"
    assert text.index(line) < text.index("python3 "), f"{name}: NUMA_BRAND is set before the first script call"


# ---------------------------------------------------------------- docs/examples (R251)

def test_metrics_example_is_a_valid_store(repo_root, nc):
    """docs/examples/metrics.example.json is metrics.py output: `validate` accepts it and `compute` is stable."""
    ex = repo_root / "docs" / "examples" / "metrics.example.json"
    store = json.loads(ex.read_text())
    assert store["schema_version"] == 1 and store["reels"] and store["account"]["daily"]
    script = repo_root / "skills" / "numa-reel-editor" / "scripts" / "metrics.py"
    r = subprocess.run([sys.executable, str(script), "validate", "--store", str(ex)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    readme = (repo_root / "docs" / "examples" / "README.md").read_text()
    assert "metrics.example.json" in readme
    assert "docs/examples/" in (repo_root / "README.md").read_text()
