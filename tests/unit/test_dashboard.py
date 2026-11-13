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
    for heading in ("Leaderboard", "By post type", "By series", "By length", "By hook type", "Posting-time heatmap", "90-day trend",
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
    assert "No posts yet" in html and "No posting times yet" in html and "Nothing logged yet" in html
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


def test_heatmap_and_text_contrast(nc):
    """Every heat cell's text and the muted ink reach WCAG AA 4.5:1 in both themes."""
    for heat, card in ((db.HEAT_LIGHT, db.CARD_LIGHT), (db.HEAT_DARK, db.CARD_DARK)):
        for i in range(18, 101):
            a = i / 100
            ink = (0, 0, 0) if db.heat_ink(a, heat, card) == "#000" else (255, 255, 255)
            assert db.contrast(db.blend(heat, a, card), ink) >= 4.5, (heat, a)
    hexrgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))  # noqa: E731
    css = db.css()
    light_muted = re.search(r"--muted:(#[0-9a-f]{6})", css).group(1)
    dark_muted = re.findall(r"--muted:(#[0-9a-f]{6})", css)[1]
    assert db.contrast(hexrgb(light_muted), hexrgb("#faf6ee")) >= 4.5
    assert db.contrast(hexrgb(dark_muted), hexrgb("#211f1c")) >= 4.5


def test_leaderboard_cards_and_cap(nc, tmp_path):
    store = fixture_store()
    base = store["reels"]["r0"]
    for i in range(6, 26):
        store["reels"][f"r{i}"] = json.loads(json.dumps(base))
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(store))
    out = tmp_path / "o.html"
    assert run([str(m), str(out)]) == 0
    html = out.read_text()
    assert 'class="cards"' in html and 'data-label="Views"' in html and "table.cards td::before" in html
    assert "Show the other 6 posts" in html
    assert 'class="sr"' not in html and "Darker is better" not in html


def test_dark_heat_ink_rule_wins(nc):
    """Same specificity: the dark-theme heat ink rules must come after the base (light) rule."""
    css = db.css()
    base = css.index(".heat td.v{color:var(--ink-l)}")
    dark = [i for i in (css.find(':root:not([data-theme="light"]) .heat td.v{color:var(--ink-d)}'), css.find(':root[data-theme="dark"] .heat td.v'))]
    assert all(i > base for i in dark) and css.count("--ink-l)") == 1


def test_results_by_post_type(nc, tmp_path):
    """R337: a post-type table and the type on every leaderboard row; no watch time for carousels or photos."""
    store = fixture_store()
    store["reels"]["c1"] = {"tags": {"title": "Five rituals", "post_type": "carousel",
                                     "posting_time": "2026-11-03T12:00:00-06:00"},
                            "pulls": {"48h": {"pulled_at": None, "metrics": {"views": 9000, "reach": 4000, "shares": 40,
                                                                            "saves": 120}}}}
    store["reels"]["c1"]["tags"].update({"series": "regulate", "length": 10})   # a length tag on a carousel is ignored
    store["reels"]["i1"] = {"tags": {"title": "Cold plunge photo", "post_type": "image"},
                            "pulls": {"7d": {"pulled_at": None, "metrics": {"views": 700, "reach": 500, "saves": 9}}}}
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(store))
    out = tmp_path / "o.html"
    assert run([str(m), str(out), "--today", "2026-11-12"]) == 0
    html = out.read_text()
    sec = html[html.index('id="bt-h"'):html.index("</section>", html.index('id="bt-h"'))]
    for label in ("Reel", "Carousel", "Photo", "Story", "Trial reel"):
        assert f'<th scope="row" class="name">{label}</th>' in sec, label
    assert sec.index(">Reel<") < sec.index(">Carousel<") < sec.index(">Photo<") < sec.index(">Story<")
    row = sec[sec.index(">Carousel<"):sec.index("</tr>", sec.index(">Carousel<"))]
    assert "n/a" in row and "9,000" in row and "30.0" in row          # saves per 1k reach
    story = sec[sec.index(">Story<"):sec.index("</tr>", sec.index(">Story<"))]
    assert 'data-label="Posts">0<' in story                          # a type with no posts yet
    lb = html[html.index('id="lb-h"'):html.index("</section>", html.index('id="lb-h"'))]
    assert 'data-label="Type" class="l">Carousel<' in lb and 'data-label="Type" class="l">Photo<' in lb
    assert lb.index("Five rituals") < lb.index("Reel 5")             # most views first, any type
    bl = html[html.index('id="bl-h"'):html.index("</section>", html.index('id="bl-h"'))]
    assert "Under 15 s" not in bl and 'scope="col">Reels<' in bl and "Reels and trial reels only" in bl
    bs = html[html.index('id="bs-h"'):html.index("</section>", html.index('id="bs-h"'))]
    assert 'scope="col">Posts<' in bs and 'scope="col">Reels<' not in bs
    reg = bs[bs.index(">Regulate<"):bs.index("</tr>", bs.index(">Regulate<"))]
    assert 'data-label="Posts">3<' in reg                              # 2 reels + the carousel
    assert 'data-label="Type" class="l">Trial reel<' in lb and "(Trial)" not in lb  # v2.0 trial_reel tag -> type


def test_post_type_empty_state(nc, tmp_path):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps({"schema_version": 1, "reels": {}, "account": {"daily": {}, "totals": {}}}))
    out = tmp_path / "e.html"
    assert run([str(m), str(out)]) == 0
    html = out.read_text()
    assert "By post type" in html and "each post is tagged with its type" in html
