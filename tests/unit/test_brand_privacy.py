"""Privacy guard: the public repo names no one but the co-founders (DECISIONS D25).

Real names of staff, providers, partners and members live only in the private STATE/people.json
(Drive _Plan/people.json). This test greps every tracked file for those names. It needs the names,
which are never in the repo, so it reads them from:

    NUMA_PRIVATE_NAMES   names separated by commas or "|", or
    NUMA_PEOPLE_FILE     path to the private people.json (schemas/people.schema.json)

and skips when neither is set. Full names are checked everywhere; single names (first or last) are
checked everywhere except third-party research reports (docs/research/R*.md cite outside authors).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ALLOWED = {"Scott", "Katie", "Moore", "Scott Moore", "Katie Moore"}
# Name parts too common to grep alone (still checked as part of the full name).
TOO_COMMON = {"Dr.", "Dr", "Kate", "Grace", "Davis", "Mobile"}


def _names() -> list[str]:
    raw = os.environ.get("NUMA_PRIVATE_NAMES", "").strip()
    if raw:
        return [n.strip() for n in re.split(r"[,|]", raw) if n.strip()]
    path = os.environ.get("NUMA_PEOPLE_FILE", "").strip()
    if path and Path(path).expanduser().is_file():
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return [p["name"] for p in data.get("people", []) if p.get("kind") != "founder" and p.get("name")]
    return []


def _tokens(names: list[str]) -> tuple[set[str], set[str]]:
    full, single = set(), set()
    for n in names:
        n = re.sub(r"^Dr\.?\s+", "", n.strip())
        if n in ALLOWED:
            continue
        parts = n.split()
        if len(parts) > 1:
            full.add(n)
        for part in parts:
            if part not in ALLOWED and part not in TOO_COMMON and len(part) > 2:
                single.add(part)
    return full, single


def test_no_private_names_in_tracked_files(repo_root):
    names = _names()
    if not names:
        pytest.skip("set NUMA_PRIVATE_NAMES or NUMA_PEOPLE_FILE (the private people.json) to run the privacy guard")
    full, single = _tokens(names)
    files = subprocess.run(["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for rel in files:
        if rel.startswith("spec/") or rel.endswith((".png", ".jpg", ".jpeg", ".woff2", ".ttf", ".mp3", ".mp4", ".otf")):
            continue
        try:
            text = (repo_root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        third_party = re.match(r"docs/research/R\d", rel) is not None
        for tok in sorted(full) + ([] if third_party else sorted(single)):
            for m in re.finditer(r"(?<![\w@])" + re.escape(tok) + r"(?![\w])", text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{rel}:{line}: {tok}")
    assert hits == [], "private names in the public repo:\n" + "\n".join(hits)


def test_tokens_skip_the_cofounders_and_common_parts():
    full, single = _tokens(["Scott Moore", "Jane Placeholder", "Dr. Ann Example", "Kate", "Sam"])
    assert full == {"Jane Placeholder", "Ann Example"}
    assert single == {"Jane", "Placeholder", "Ann", "Example", "Sam"}
