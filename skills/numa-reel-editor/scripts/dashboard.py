#!/usr/bin/env python3
"""Build Numa's performance dashboard: one self-contained HTML file (spec p.47, DECISIONS D7).

Usage:
    dashboard.py METRICS_JSON OUT_HTML [--notes NOTES_JSON] [--competitors FILE] [--today YYYY-MM-DD]
                 [--title TEXT]

Reads the metrics store written by metrics.py and writes OUT_HTML with:
a leaderboard of every post (reels, trial reels, carousels, photos, stories;
each row names its type); results by post type (R337: carousels and photos have
no watch time, so their retention shows a dash), series, length and hook type; a posting-time
heatmap (day x hour, Central time); a 90-day trend line (views per post, plus
account reach per day when account insights are stored); the monthly
competitor tracker; and the Director's "Do more of / Do less of" box.

No network assets: inline CSS and SVG only, light and dark themes, works from
phone width up, every table has a caption. Output is deterministic: the
"data through" date is --today, else the latest date found in the data.

NOTES_JSON (written by the Director each week):
    {"week_of": "2026-12-07", "do_more": ["..."], "do_less": ["..."]}

Competitor log (written monthly by the Scout; the accounts are brand.json
positioning.competitors, last 12 posts each):
    {"month": "2026-12", "accounts": [{"name": "Beyond The Plunge", "handle": "@beyondtheplunge",
      "posts": [{"date": "2026-12-01", "url": "...", "format": "reel", "hook": "...",
                 "views": 1200, "likes": 40, "comments": 3}]}]}
"""
from __future__ import annotations

import html
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics as mx  # noqa: E402
import numa_common as nc  # noqa: E402

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TREND_DAYS = 90
LEADERBOARD_TOP = 20
TYPE_LABELS = {"reel": "Reel", "trial_reel": "Trial reel", "carousel": "Carousel", "image": "Photo", "story": "Story"}


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def fmt_num(x: Any, digits: int = 0) -> str:
    if not isinstance(x, (int, float)):
        return "–"
    if digits == 0:
        return f"{round(x):,}"
    return f"{x:,.{digits}f}"


def fmt_pct(x: Any) -> str:
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "–"


def med(values: list) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    return statistics.median(vals) if vals else None


def hour_label(h: int) -> str:
    return f"{(h % 12) or 12}{'a' if h < 12 else 'p'}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def reel_rows(store: dict) -> list[dict]:
    mx.compute(store)
    rows = []
    for rid in sorted(store["reels"]):
        reel = store["reels"][rid]
        label = mx.latest_pull(reel)
        if not label:
            continue
        tags = reel.get("tags") or {}
        m = reel["pulls"][label]["metrics"]
        c = reel.get("computed") or {}
        posted = None
        if tags.get("posting_time"):
            posted = mx.to_central(mx.parse_time(tags["posting_time"], f"reels.{rid}.tags.posting_time"))
        rows.append({
            "id": rid, "title": tags.get("title") or tags.get("slug") or rid, "permalink": tags.get("permalink"),
            "type": mx.post_type_of(reel),
            "series": tags.get("series"), "pillar": tags.get("pillar"), "hook_type": tags.get("hook_type"),
            "length": tags.get("length"), "posted": posted, "pull": label,
            "trial_reel": tags.get("trial_reel"), "collab": tags.get("collab"),
            "views": m.get("views"), "reach": m.get("reach"), "shares": m.get("shares"), "saves": m.get("saves"),
            "retention": c.get("retention"), "sends_1k": c.get("sends_per_1k_reach"),
            "saves_1k": c.get("saves_per_1k_reach"), "skip_vs": c.get("skip_rate_vs_median"),
            "skip": m.get("skip_rate"), "awt_s": c.get("avg_watch_time_s"),
        })
    return rows


def length_bucket(length: Any) -> str | None:
    if not isinstance(length, (int, float)):
        return None
    if length < 15:
        return "Under 15 s"
    if length <= 30:
        return "15–30 s"
    if length <= 45:
        return "31–45 s"
    if length <= 60:
        return "46–60 s"
    return "Over 60 s"


LENGTH_ORDER = ["Under 15 s", "15–30 s", "31–45 s", "46–60 s", "Over 60 s"]


def series_names() -> dict[str, str]:
    out = {}
    for s in nc.brand_value("positioning.series", []) or []:
        if isinstance(s, dict) and s.get("id"):
            out[s["id"]] = s.get("name") or s["id"]
    return out


def group(rows: list[dict], key, order: list[str] | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = key(r)
        if k:
            groups.setdefault(k, []).append(r)
    names = order and [n for n in order if n in groups] or sorted(groups)
    return [{"name": n, "count": len(groups[n]), "views": med([r["views"] for r in groups[n]]),
             "reach": med([r["reach"] for r in groups[n]]),
             "retention": med([r["retention"] for r in groups[n]]),
             "sends_1k": med([r["sends_1k"] for r in groups[n]]),
             "saves_1k": med([r["saves_1k"] for r in groups[n]])} for n in names]


def data_through(rows: list[dict], store: dict, comp: dict | None) -> date | None:
    dates = [r["posted"].date() for r in rows if r["posted"]]
    dates += [date.fromisoformat(d) for d in (store.get("account", {}) or {}).get("daily", {})]
    for acct in (comp or {}).get("accounts", []) or []:
        for p in acct.get("posts", []) or []:
            try:
                dates.append(date.fromisoformat(str(p.get("date"))[:10]))
            except ValueError:
                pass
    return max(dates) if dates else None


def load_notes(path: str | None) -> dict | None:
    if not path:
        return None
    data = nc.read_json(Path(path).expanduser(), "notes file")
    if not isinstance(data, dict):
        raise nc.UserError(f"notes file {path}: expected an object with do_more and do_less lists")
    for k in ("do_more", "do_less"):
        v = data.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise nc.UserError(f"notes file {path}: '{k}' must be a list of sentences")
    return data


def load_competitors(path: str | None) -> dict | None:
    if not path:
        return None
    data = nc.read_json(Path(path).expanduser(), "competitor log")
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise nc.UserError(f"competitor log {path}: expected {{\"month\": ..., \"accounts\": [...]}}")
    for i, a in enumerate(data["accounts"]):
        if not isinstance(a, dict) or not (a.get("name") or a.get("handle")):
            raise nc.UserError(f"competitor log {path}: accounts[{i}] needs a name or handle")
        if not isinstance(a.get("posts", []), list):
            raise nc.UserError(f"competitor log {path}: accounts[{i}].posts must be a list")
        for j, p in enumerate(a.get("posts", [])):
            if not isinstance(p, dict):
                raise nc.UserError(f"competitor log {path}: accounts[{i}].posts[{j}] is not an object")
            for k in ("views", "likes", "comments"):
                v = p.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                    raise nc.UserError(f"competitor log {path}: accounts[{i}].posts[{j}].{k} must be a number >= 0")
    return data


# ---------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------
HEAT_LIGHT, CARD_LIGHT = (63, 111, 114), (255, 255, 255)
HEAT_DARK, CARD_DARK = (127, 179, 181), (33, 31, 28)

CSS = """
:root{color-scheme:light;--bg:#faf6ee;--card:#ffffff;--ink:#22201c;--ink2:#5b554c;--muted:#6b6459;
--line:#e6dfd2;--accent:#3f6f72;--accent-soft:#d8e6e6;--ember:#a8502d;--good:#2f6b3f;--bad:#a8502d;--heat:@HEAT_LIGHT@}
.heat td.v{color:var(--ink-l)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#171614;--card:#211f1c;
--ink:#f1ece3;--ink2:#c9c1b4;--muted:#9a9184;--line:#36322c;--accent:#7fb3b5;--accent-soft:#2b3b3c;--ember:#e08a63;
--good:#8cc79a;--bad:#e08a63;--heat:@HEAT_DARK@}
:root:not([data-theme="light"]) .heat td.v{color:var(--ink-d)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#171614;--card:#211f1c;--ink:#f1ece3;--ink2:#c9c1b4;--muted:#9a9184;
--line:#36322c;--accent:#7fb3b5;--accent-soft:#2b3b3c;--ember:#e08a63;--good:#8cc79a;--bad:#e08a63;--heat:@HEAT_DARK@}
:root[data-theme="dark"] .heat td.v{color:var(--ink-d)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
header h1{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:28px;margin:0 0 2px}
header p{margin:0;color:var(--ink2)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:16px;min-width:0}
h2{font-size:17px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 12px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr))}
.grid>section{margin-top:0}
.tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tile .k{color:var(--ink2);font-size:13px}.tile .v{font-size:26px;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;position:relative}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:14px}
caption{text-align:left;color:var(--ink2);font-size:13px;padding:0 0 8px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child,th.l,td.l{text-align:left}
th.name,td.name{white-space:normal;min-width:150px;max-width:300px;overflow-wrap:anywhere}
.name .meta{display:block;color:var(--ink2);font-size:12px;font-weight:400}
thead th{color:var(--ink2);font-weight:600;font-size:13px}
a{color:var(--accent)}
.bar{display:inline-block;height:8px;border-radius:0 4px 4px 0;background:var(--accent);vertical-align:middle;margin-right:6px}
.pos{color:var(--bad)}.neg{color:var(--good)}
.empty{color:var(--muted);font-style:italic;margin:4px 0}
.dm{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))}
.dm h3{font-size:15px;margin:0 0 6px}.dm ul{margin:0;padding-left:20px}.dm li{margin:4px 0}
.dm .more h3{color:var(--accent)}.dm .less h3{color:var(--ember)}
.heat td{padding:0;border:1px solid var(--card);min-width:30px;height:30px;text-align:center;font-size:11px}
.heat th{font-weight:500;font-size:12px;padding:4px}
.heat td span{display:block;line-height:30px}
.legend{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:12px;margin-top:8px}
.legend i{display:inline-block;width:18px;height:12px;border-radius:2px}
svg{display:block;width:100%;height:auto}
svg.narrow{display:none}
@media (max-width:600px){svg.wide{display:none}svg.narrow{display:block}
table.cards thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
table.cards,table.cards tbody{display:block}
table.cards tr{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px 12px;padding:10px 0;
border-bottom:1px solid var(--line)}
table.cards th.name{grid-column:1/-1;border:0;padding:0;max-width:none}
table.cards td{border:0;padding:0;text-align:left;white-space:normal}
table.cards td::before{content:attr(data-label);display:block;color:var(--ink2);font-size:12px}}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
svg text{fill:var(--ink2);font-size:11px}
svg .grid line{stroke:var(--line)}
svg .series{stroke:var(--accent);fill:none;stroke-width:2}
svg .dot{fill:var(--accent);stroke:var(--card);stroke-width:2}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
footer{color:var(--muted);font-size:12px;margin-top:20px}
"""


def _lum(rgb: tuple[float, float, float]) -> float:
    c = [x / 255 for x in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: tuple, b: tuple) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def blend(rgb: tuple, alpha: float, under: tuple) -> tuple[float, float, float]:
    return tuple(alpha * c + (1 - alpha) * u for c, u in zip(rgb, under))


def heat_ink(alpha: float, heat: tuple, card: tuple) -> str:
    """Black or white, whichever reads better on this heat cell (>= 4.58:1 for any background)."""
    bg = blend(heat, alpha, card)
    return "#000" if contrast(bg, (0, 0, 0)) >= contrast(bg, (255, 255, 255)) else "#fff"


def css() -> str:
    return CSS.replace("@HEAT_LIGHT@", ",".join(map(str, HEAT_LIGHT))).replace("@HEAT_DARK@", ",".join(map(str, HEAT_DARK)))


def empty(text: str) -> str:
    return f'<p class="empty">{esc(text)}</p>'


def table(caption: str, head: list[str], rows: list[list[str]], first_is_name: bool = True,
          left: tuple[int, ...] = ()) -> str:
    """An accessible table; `left` = indexes of text columns aligned left (numbers align right).
    Under 600 px wide each row becomes a card: the name on top, then the cells labelled from the header."""
    def lcls(i: int) -> str:
        return ' class="l"' if i in left else ""
    th = "".join(f'<th scope="col"{lcls(i)}>{esc(h)}</th>' for i, h in enumerate(head))
    body = []
    for r in rows:
        cells = [f'<th scope="row" class="name">{r[0]}</th>' if first_is_name else f"<td>{r[0]}</td>"]
        cells += [f'<td data-label="{esc(head[i])}"{lcls(i)}>{c}</td>'
                  for i, c in enumerate(r[1:], 1)]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<p class="sub" aria-hidden="true">{esc(caption)}</p>'
            f'<div class="scroll"><table class="cards"><caption class="vh">{esc(caption)}</caption><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def tiles(rows: list[dict]) -> str:
    items = [("Posts tracked", fmt_num(len(rows))), ("Median views", fmt_num(med([r["views"] for r in rows]))),
             ("Median retention", fmt_pct(med([r["retention"] for r in rows]))),
             ("Median sends / 1,000 reach", fmt_num(med([r["sends_1k"] for r in rows]), 1)),
             ("Median saves / 1,000 reach", fmt_num(med([r["saves_1k"] for r in rows]), 1))]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in items) + "</div>"


def do_more_less(notes: dict | None) -> str:
    head = '<section aria-labelledby="dm-h"><h2 id="dm-h">Do more of / Do less of</h2>'
    if not notes or not (notes.get("do_more") or notes.get("do_less")):
        return head + empty("The Director writes this box each week once there is data to learn from.") + "</section>"
    sub = f'<p class="sub">Week of {esc(notes["week_of"])}</p>' if notes.get("week_of") else ""

    def lst(items: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>" if items else empty("Nothing this week.")
    return (head + sub + f'<div class="dm"><div class="more"><h3>Do more of</h3>{lst(notes.get("do_more", []))}</div>'
            f'<div class="less"><h3>Do less of</h3>{lst(notes.get("do_less", []))}</div></div></section>')


def leaderboard(rows: list[dict], names: dict[str, str]) -> str:
    head = ('<section aria-labelledby="lb-h"><h2 id="lb-h">Leaderboard</h2>'
            '<p class="sub">Every post by views, from its latest pull (7 d, else 72 h, else 48 h). '
            'Carousels and photos have no watch time or skip rate.</p>')
    if not rows:
        return head + empty("No posts yet: the dashboard fills in after the first 48-hour insights pull.") + "</section>"
    ranked = sorted(rows, key=lambda r: (-(r["views"] or 0), r["id"]))
    body = []
    for i, r in enumerate(ranked, 1):
        title = esc(r["title"])
        if r["permalink"]:
            title = f'<a href="{esc(r["permalink"])}">{title}</a>'
        flags = " · ".join(x for x, on in (("Trial", r["trial_reel"] and r["type"] != "trial_reel"),
                                            ("Collab", r["collab"])) if on)
        if flags:
            title += f' <span class="sub">({esc(flags)})</span>'
        sv = r["skip_vs"]
        skip = "–" if not isinstance(sv, (int, float)) else (
            f'<span class="{"pos" if sv > 0 else "neg"}">{sv:+.1f}</span>' if sv else "0.0")
        meta = [r["posted"].strftime("%b %-d") if r["posted"] else None, names.get(r["series"], r["series"]),
                f"{fmt_num(r['length'])} s" if isinstance(r["length"], (int, float)) else None, f"{r['pull']} pull"]
        name = f'{i}. {title}<span class="meta">{esc(" · ".join(m for m in meta if m))}</span>'
        body.append([name, esc(TYPE_LABELS[r["type"]]), fmt_num(r["views"]), fmt_num(r["reach"]),
                     fmt_pct(r["retention"]), fmt_num(r["sends_1k"], 1), fmt_num(r["saves_1k"], 1), skip])
    cols = ["Post", "Type", "Views", "Reach", "Retention", "Sends/1k", "Saves/1k", "Skip vs median"]
    out = head + table(f"Top {min(len(body), LEADERBOARD_TOP)} posts by views; skip rate is in points against Numa's "
                       "reel median (lower is better).", cols, body[:LEADERBOARD_TOP], left=(1,))
    if len(body) > LEADERBOARD_TOP:
        out += (f"<details><summary>Show the other {len(body) - LEADERBOARD_TOP} posts</summary>"
                + table("The rest of the posts by views.", cols, body[LEADERBOARD_TOP:], left=(1,)) + "</details>")
    return out + "</section>"


def breakdown(title: str, hid: str, groups: list[dict], what: str, unit: str = "posts") -> str:
    """Median results per group; `unit` names what is counted ("posts": every type, "reels": reels and trial reels)."""
    head = f'<section aria-labelledby="{hid}"><h2 id="{hid}">{esc(title)}</h2>'
    if not groups:
        return head + empty(f"No tagged {unit} yet: tag each {unit[:-1]}'s {what} when it posts.") + "</section>"
    top = max([g["views"] or 0 for g in groups] or [0]) or 1
    rows = []
    for g in groups:
        w = 0 if not g["views"] else max(2, round(60 * g["views"] / top))
        rows.append([esc(g["name"]), fmt_num(g["count"]),
                     f'<span class="bar" style="width:{w}px" aria-hidden="true"></span>{fmt_num(g["views"])}',
                     fmt_pct(g["retention"]), fmt_num(g["sends_1k"], 1)])
    note = " Retention counts video posts only." if unit == "posts" else " Reels and trial reels only."
    return head + table(f"Median results by {what}.{note}", [what.capitalize(), unit.capitalize(), "Median views",
                                                            "Retention", "Sends/1k"], rows) + "</section>"


def by_post_type(rows: list[dict]) -> str:
    """Median results per post type (R337), in metrics.POST_TYPES order; every type is listed."""
    head = ('<section aria-labelledby="bt-h"><h2 id="bt-h">By post type</h2>'
            '<p class="sub">Retention is for video posts only: carousels and photos have no watch time.</p>')
    if not rows:
        return head + empty("No posts yet: each post is tagged with its type (reel, carousel, photo, story, "
                            "trial reel) when it posts.") + "</section>"
    groups = {g["name"]: g for g in group(rows, lambda r: r["type"], list(mx.POST_TYPES))}
    top = max([g["views"] or 0 for g in groups.values()] or [0]) or 1
    body = []
    for t in mx.POST_TYPES:
        g = groups.get(t)
        if not g:
            body.append([esc(TYPE_LABELS[t]), "0", "–", "–", "–", "–", "–"])
            continue
        w = 0 if not g["views"] else max(2, round(60 * g["views"] / top))
        ret = fmt_pct(g["retention"]) if t in mx.VIDEO_TYPES else '<span class="sub">n/a</span>'
        body.append([esc(TYPE_LABELS[t]), fmt_num(g["count"]),
                     f'<span class="bar" style="width:{w}px" aria-hidden="true"></span>{fmt_num(g["views"])}',
                     fmt_num(g["reach"]), ret, fmt_num(g["sends_1k"], 1), fmt_num(g["saves_1k"], 1)])
    return head + table("Median results by post type; a type with no posts yet shows 0.",
                        ["Post type", "Posts", "Median views", "Median reach", "Retention", "Sends/1k", "Saves/1k"],
                        body) + "</section>"


def heatmap(rows: list[dict]) -> str:
    head = ('<section aria-labelledby="hm-h"><h2 id="hm-h">Posting-time heatmap</h2>'
            '<p class="sub">Median views by day and hour posted (Central time). Stronger colour means more views.</p>')
    cells: dict[tuple[int, int], list] = {}
    for r in rows:
        if r["posted"] and isinstance(r["views"], (int, float)):
            cells.setdefault((r["posted"].weekday(), r["posted"].hour), []).append(r["views"])
    if not cells:
        return head + empty("No posting times yet: tag each post's posting_time when it posts.") + "</section>"
    hours = sorted(set(range(6, 23)) | {h for _, h in cells})
    vals = {k: med(v) for k, v in cells.items()}
    top = max(vals.values()) or 1
    th = "".join(f'<th scope="col">{hour_label(h)}</th>' for h in hours)
    body = []
    for d in range(7):
        tds = []
        for h in hours:
            v = vals.get((d, h))
            label = f"{DAYS[d]} {hour_label(h)}: " + (f"median {fmt_num(v)} views, {len(cells[(d, h)])} posts" if v is not None
                                                     else "no posts")
            if v is None:
                tds.append(f'<td title="{esc(label)}"><span class="vh">{esc(label)}</span></td>')
            else:
                a = round(0.18 + 0.82 * v / top, 2)
                ink_l, ink_d = heat_ink(a, HEAT_LIGHT, CARD_LIGHT), heat_ink(a, HEAT_DARK, CARD_DARK)
                tds.append(f'<td class="v" title="{esc(label)}" style="background:rgba(var(--heat),{a:.2f});'
                           f'--ink-l:{ink_l};--ink-d:{ink_d}"><span aria-hidden="true">{esc(fmt_compact(v))}</span>'
                           f'<span class="vh">{esc(label)}</span></td>')
        body.append(f'<tr><th scope="row">{DAYS[d]}</th>{"".join(tds)}</tr>')
    legend = ('<div class="legend" aria-hidden="true"><span>Fewer views</span>'
              '<i style="background:rgba(var(--heat),.18)"></i><i style="background:rgba(var(--heat),.5)"></i>'
              '<i style="background:rgba(var(--heat),.75)"></i><i style="background:rgba(var(--heat),1)"></i>'
              '<span>More views</span></div>')
    return (head + '<div class="scroll"><table class="heat"><caption class="vh">Median views per posting slot; empty cells had no '
            f'posts.</caption><thead><tr><th scope="col">Day</th>{th}</tr></thead><tbody>{"".join(body)}</tbody>'
            f"</table></div>{legend}</section>")


def fmt_compact(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    return f"{round(v)}"


def line_chart(points: list[tuple[date, float, str]], start: date, end: date, label: str) -> str:
    """The chart twice: a wide drawing for desktop and a narrow one for phones (CSS shows one), so text stays legible."""
    return _line_svg(points, start, end, label, 960, "wide") + _line_svg(points, start, end, label, 420, "narrow")


def _line_svg(points: list[tuple[date, float, str]], start: date, end: date, label: str, width: int, cls: str) -> str:
    """One-series SVG line chart over [start, end] with a recessive grid and per-point hover titles."""
    W, H, L, R, T, B = width, 240, 44, 12, 12, 26
    top = max(v for _, v, _ in points) or 1
    step = 10 ** max(0, len(str(int(top))) - 1)
    ymax = max(step, -(-top // step) * step)
    span = max(1, (end - start).days)

    def x(d: date) -> float:
        return L + (W - L - R) * (d - start).days / span

    def y(v: float) -> float:
        return T + (H - T - B) * (1 - v / ymax)
    grid = []
    for i in range(5):
        v = ymax * i / 4
        grid.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                    f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{esc(fmt_compact(v))}</text>')
    ticks = []
    d = date(start.year, start.month, 1)
    while d <= end:
        if d >= start:
            ticks.append(f'<text x="{x(d):.1f}" y="{H - 8}" text-anchor="middle">{d.strftime("%b %-d")}</text>')
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    pts = sorted(points)
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(p[0]):.1f},{y(p[1]):.1f}" for i, p in enumerate(pts))
    r = 4 if len(pts) <= 40 else 2.5  # dense daily series: smaller markers, still one hover target per point
    dots = "".join(f'<circle class="dot" cx="{x(p[0]):.1f}" cy="{y(p[1]):.1f}" r="{r}"><title>{esc(p[2])}</title></circle>'
                   for p in pts)
    return (f'<svg class="{cls}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(label)}"><g class="grid">{"".join(grid)}</g>'
            f'{"".join(ticks)}<path class="series" d="{path}"/>{dots}</svg>')


def trend(rows: list[dict], store: dict, today: date | None) -> str:
    head = ('<section aria-labelledby="tr-h"><h2 id="tr-h">90-day trend</h2>')
    if today is None:
        return head + empty("No data yet: the trend line starts with the first post.") + "</section>"
    start = today - timedelta(days=TREND_DAYS - 1)
    out = [head, f'<p class="sub">{start.strftime("%b %-d, %Y")} – {today.strftime("%b %-d, %Y")}</p>']
    pts = [(r["posted"].date(), float(r["views"]), f'{r["title"]}: {fmt_num(r["views"])} views')
           for r in rows if r["posted"] and isinstance(r["views"], (int, float)) and start <= r["posted"].date() <= today]
    if pts:
        out.append("<h3 class=\"sub\">Views per post, by posting date</h3>")
        out.append(line_chart(pts, start, today, "Views per post over the last 90 days"))
        out.append("<details><summary>Show as a table</summary>" + table(
            "Views per post in the last 90 days.", ["Posted", "Post", "Views"],
            [[esc(p[0].isoformat()), esc(p[2].rsplit(":", 1)[0]), fmt_num(p[1])] for p in sorted(pts)]) + "</details>")
    else:
        out.append(empty("No posts in the last 90 days."))
    daily = (store.get("account", {}) or {}).get("daily", {}) or {}
    apts = [(date.fromisoformat(d), float(v["reach"]), f"{d}: {fmt_num(v['reach'])} accounts reached")
            for d, v in sorted(daily.items()) if isinstance(v.get("reach"), (int, float))
            and start <= date.fromisoformat(d) <= today]
    if apts:
        out.append("<h3 class=\"sub\">Account reach per day</h3>")
        out.append(line_chart(apts, start, today, "Account reach per day over the last 90 days"))
    return "".join(out) + "</section>"


def competitors(comp: dict | None) -> str:
    head = ('<section aria-labelledby="cp-h"><h2 id="cp-h">Competitor tracker</h2>')
    listed = [c for c in nc.brand_value("positioning.competitors", []) or [] if isinstance(c, dict)]
    n_posts = int(nc.config_value("instagram.competitors_tracked_posts", 12) or 12)
    logged = {}
    for a in (comp or {}).get("accounts", []) or []:
        logged[(a.get("handle") or a.get("name") or "").lower()] = a
        logged[(a.get("name") or "").lower()] = a
    names = [(c.get("name"), c.get("handle")) for c in listed]
    for a in (comp or {}).get("accounts", []) or []:
        if not any((a.get("handle") or "").lower() == (h or "").lower() or (a.get("name") or "").lower() == (n or "").lower()
                   for n, h in names):
            names.append((a.get("name"), a.get("handle")))
    if not names:
        return head + empty("No competitors listed in brand.json.") + "</section>"
    sub = (f'<p class="sub">Last {n_posts} posts per account, logged by the Scout for {esc(comp.get("month"))}.</p>'
           if comp and comp.get("month") else f'<p class="sub">Last {n_posts} posts per account, logged monthly by the Scout.</p>')
    if not any((a.get("posts") or []) for a in (comp or {}).get("accounts", []) or []):
        who = ", ".join(f"{n or h}" + (f" ({h})" if n and h else "") for n, h in names)
        return head + sub + empty(f"Nothing logged yet. The Scout logs the last {n_posts} posts of each account "
                                  f"every month: {who}.") + "</section>"
    rows = []
    for name, handle in names:
        a = logged.get((handle or "").lower()) or logged.get((name or "").lower())
        who = esc(name or handle) + (f' <span class="sub">{esc(handle)}</span>' if handle and name else "")
        posts = (a or {}).get("posts", []) or []
        if not posts:
            rows.append([who, "0", "–", "–", "–", "–", "Not logged yet"])
            continue
        posts = sorted(posts, key=lambda p: str(p.get("date", "")), reverse=True)[:n_posts]
        formats: dict[str, int] = {}
        for p in posts:
            formats[str(p.get("format") or "post")] = formats.get(str(p.get("format") or "post"), 0) + 1
        top_fmt = sorted(formats.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        best = max(posts, key=lambda p: ((p.get("views") or 0), (p.get("likes") or 0)))
        hook = esc(best.get("hook") or "–")
        if best.get("url"):
            hook = f'<a href="{esc(best["url"])}">{hook}</a>'
        rows.append([who, fmt_num(len(posts)), fmt_num(med([p.get("views") for p in posts])),
                     fmt_num(med([p.get("likes") for p in posts])), esc(top_fmt),
                     esc(str(posts[0].get("date", "–"))[:10]), hook])
    return head + sub + table("Competitors' recent posts: medians, most used format, latest post and best post's hook.",
                              ["Account", "Posts", "Median views", "Median likes", "Top format", "Latest",
                               "Best post"], rows, left=(4, 6)) + "</section>"


def build(store: dict, notes: dict | None, comp: dict | None, today: date | None, title: str) -> str:
    rows = reel_rows(store)
    through = today or data_through(rows, store, comp)
    names = series_names()
    sub = f"Data through {through.strftime('%B %-d, %Y')} · Central time" if through else "No data yet"
    body = [
        f"<header><h1>{esc(title)}</h1><p>{esc(sub)}</p></header>",
        tiles(rows),
        do_more_less(notes),
        leaderboard(rows, names),
        by_post_type(rows),
        '<div class="grid" style="margin-top:16px">',
        breakdown("By series", "bs-h", group(rows, lambda r: names.get(r["series"], r["series"])), "series"),
        breakdown("By length", "bl-h", group([r for r in rows if r["type"] in mx.REEL_TYPES],
                                             lambda r: length_bucket(r["length"]), LENGTH_ORDER), "length", "reels"),
        breakdown("By hook type", "bh-h", group(rows, lambda r: r["hook_type"]), "hook type"),
        "</div>",
        heatmap(rows),
        trend(rows, store, through),
        competitors(comp),
        "<footer>Built by NUMA Studio dashboard.py from metrics.json (Instagram insights via Composio). "
        "Retention = average watch time ÷ reel length; sends = shares.</footer>",
    ]
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{css()}</style></head><body><main>"
            + "\n".join(body) + "</main></body></html>\n")


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="dashboard.py", description="Build the self-contained HTML performance dashboard.")
    ap.add_argument("metrics", metavar="METRICS_JSON")
    ap.add_argument("out", metavar="OUT_HTML")
    ap.add_argument("--notes", metavar="NOTES_JSON", help="the Director's Do more / Do less notes")
    ap.add_argument("--competitors", metavar="FILE", help="the Scout's monthly competitor log")
    ap.add_argument("--today", metavar="YYYY-MM-DD", help="end of the 90-day window (default: latest date in the data)")
    ap.add_argument("--title", default="Numa Reel Dashboard")
    args = ap.parse_args(argv)
    today = None
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            raise nc.UsageError(f"--today must be YYYY-MM-DD, got {args.today!r}") from None
    store = mx.load_store(Path(args.metrics).expanduser().resolve())
    doc = build(store, load_notes(args.notes), load_competitors(args.competitors), today, args.title)
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.tmp")
    tmp.write_text(doc, encoding="utf-8", newline="\n")
    tmp.replace(out)
    print(f"Wrote {out} ({len(store['reels'])} posts)")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
