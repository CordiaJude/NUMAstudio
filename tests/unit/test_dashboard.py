"""dashboard.py: self-contained HTML dashboard from a fixture metrics.json (R249, R250)."""
from __future__ import annotations

import json
import re

import pytest

import dashboard as db
import numa_common


def fixture_store():
    reels = {}
    series = ["ask_the_dpt", "first_plunge", "regulate"]
    for i in range(6):
        views = 1000 + 300 * i
        reels[f"r{i}"] = {
            "tags": {"title": f"Reel {i} <b>", "length": [45, 22, 58][i % 3], "series": series[i % 3],
                     "hook_type": ["question", "contrast"][i % 2],
                     "posting_time": f"2026-11-{2 + i:02d}T17:30:00-06:00", "permalink": f"https://instagram.com/reel/{i}/",
                     "trial_reel": i == 0, "collab": False},
            "pulls": {"7d": {"pulled_at": None, "metrics": {"views": views, "reach": views // 2, "shares": 5 + i,
                                                           "saves": 3, "avg_watch_time_ms": 15000, "skip_rate": 40 + i}}},
        }
    return {"schema_version": 1, "reels": reels,
            "account": {"daily": {"2026-11-01": {"reach": 300}, "2026-11-02": {"reach": 420}}, "totals": {}}}


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(db.main, argv)
    return e.value.code


def test_builds_all_views(nc, tmp_path):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(fixture_store()))
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"week_of": "2026-11-09", "do_more": ["Question hooks"], "do_less": ["Whips in Regulate"]}))
    comp = tmp_path / "comp.json"
    comp.write_text(json.dumps({"month": "2026-11", "accounts": [{"name": "Beyond The Plunge", "handle": "@beyondtheplunge",
        "posts": [{"date": f"2026-11-{k + 1:02d}", "format": "reel", "hook": "Cold myths", "views": 100 + k, "likes": 5}
                  for k in range(14)]}]}))
    out = tmp_path / "dash" / "index.html"
    assert run([str(m), str(out), "--notes", str(notes), "--competitors", str(comp), "--today", "2026-11-12"]) == 0
    html = out.read_text()
    for heading in ("Leaderboard", "By series", "By length", "By hook type", "Posting-time heatmap", "90-day trend",
                    "Competitor tracker", "Do more of / Do less of"):
        assert heading in html
    assert "Question hooks" in html and "Whips in Regulate" in html
    assert "Reel 0 &lt;b&gt;" in html and "<b>" not in html.replace("<body>", "")  # escaped
    assert "Ask the DPT" in html  # series id -> brand.json name
    assert "Mission Fitness" in html  # every brand.json competitor listed, even unlogged
    assert html.count("<caption") >= 6
    assert "prefers-color-scheme:dark" in html and 'name="viewport"' in html
    # no network assets
    assert not re.search(r"""(src|href)=["']https?://(?!instagram\.com)""", html)
    assert "<script" not in html and "@import" not in html
    # leaderboard order: highest views first
    assert html.index("Reel 5 &lt;b&gt;") < html.index("Reel 0 &lt;b&gt;")
    # heatmap: posted 17:30 Central -> 5p column holds values
    assert "5p: median" in html


def test_deterministic(nc, tmp_path):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(fixture_store()))
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    assert run([str(m), str(a)]) == 0 and run([str(m), str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    assert "Data through November 7, 2026" in a.read_text()  # latest post date, not the clock


def test_empty_states(nc, tmp_path):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps({"schema_version": 1, "reels": {}, "account": {"daily": {}, "totals": {}}}))
    out = tmp_path / "e.html"
    assert run([str(m), str(out)]) == 0
    html = out.read_text()
    assert "No reels yet" in html and "No posting times yet" in html and "Nothing logged yet" in html
    assert "No data yet" in html


def test_bad_inputs(nc, tmp_path):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps({"schema_version": 1, "reels": {"x": {"pulls": {"48h": {"metrics": {"plays": 3}}}}}}))
    assert run([str(m), str(tmp_path / "o.html")]) == 1
    m.write_text(json.dumps(fixture_store()))
    bad = tmp_path / "n.json"
    bad.write_text(json.dumps({"do_more": "everything"}))
    assert run([str(m), str(tmp_path / "o.html"), "--notes", str(bad)]) == 1
    assert run([str(m), str(tmp_path / "o.html"), "--today", "12/11/2026"]) == 2
    assert run([]) == 2
