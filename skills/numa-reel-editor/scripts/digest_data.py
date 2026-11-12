#!/usr/bin/env python3
"""Numbers for the Monday digest, assembled deterministically (spec p.45-46, p.37, R240).

Usage:
    digest_data.py --metrics METRICS_JSON --plan-rows ROWS [--ledger PATH] [--notes NOTES_JSON]
                   [--today YYYY-MM-DD] [--out JSON] [--text TXT] [--json]

Inputs:
* METRICS_JSON: the metrics store (metrics.py).
* ROWS: the "NUMA 30-Day Reel Plan" Sheet exported as JSON (a list of row
  objects, or {"rows": [...]}) or CSV with a header row. Column names are
  matched loosely (case and punctuation ignored): Day, Date, Title, Goal,
  Template, Hook, Voiceover script, Shot list (or Shots), Music, Call to action,
  Status, Folder link, Reel link, and optionally Posting time, Room, Film by.
  Shots may be a list of {"shot", "room", "time_of_day", "minutes"} objects or
  text, one shot per line; a line's room comes from a "room:" prefix, a
  "[room]" tag, or the room named in it (plunge room, sauna, class studio,
  front of house, outside).
* PATH: the credit ledger (ledger.py). Optional; without it the budget
  section is left for the Director.
* NOTES_JSON: optional {"changes": [...], "heads_ups": [...]} written by the
  Director (what changed because of last week; swaps, Scout finds, skips).

Weeks: the digest goes out Sunday evening. "This week" starts on the next
Monday (today, when --today is a Monday); "last week" is the seven days
before it. Dates are Central time.

Outputs: one JSON document (--out or --json) with sections last_week,
changes, this_week, shoot_list, budget, heads_ups, and `needs_director` (the
sections only the Director can write: why the best reel worked, and any
section without data); plus a plain-text phone-readable draft (--text, or on
stdout without --json). Shoot-time estimate: `minutes` per shot when given,
else 1 minute per shot, plus 3 minutes to set up each room, plus 2 minutes per
voiceover (read back to back in one sitting).
"""
from __future__ import annotations

import csv
import io
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger as lg  # noqa: E402
import metrics as mx  # noqa: E402
import numa_common as nc  # noqa: E402

ROOMS = ["plunge room", "sauna", "class studio", "front of house", "outside"]
ROOM_WORDS = [
    ("plunge room", r"\b(cold )?plunge( room)?\b|\bice bath\b"),
    ("sauna", r"\bsauna\b|\binfrared\b"),
    ("class studio", r"\b(class )?studio\b|\bclass\b|\bmat\b|\byoga\b|\bbreathwork room\b"),
    ("front of house", r"\bfront (of house|desk|door)\b|\blobby\b|\breception\b|\bentrance\b|\bcheck[- ]in\b"),
    ("outside", r"\boutside\b|\bexterior\b|\boutdoors?\b|\bstreet\b|\bsign(age)?\b|\bparking\b|\bsidewalk\b"),
]
TIMES = ["morning", "midday", "afternoon", "evening", "night"]
MIN_PER_SHOT, MIN_PER_ROOM, MIN_PER_VOICEOVER = 1.0, 3.0, 2.0
NO_FILMING = re.compile(r"no filming needed", re.I)
DONE_STATUS = {"shot", "ready to build", "ready to post", "posted"}


def norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).strip().lower()).strip("_")


ALIASES = {
    "shot_list": "shots", "shotlist": "shots", "shots": "shots",
    "voiceover_script": "script", "voiceover": "script", "script": "script",
    "hook_first_2_seconds": "hook", "hook": "hook", "music_mood_bpm": "music", "music": "music",
    "call_to_action": "cta", "cta": "cta", "folder_link": "folder", "folder": "folder", "reel_link": "reel_link",
    "posting_time": "posting_time", "post_time": "posting_time", "film_by": "film_by", "slug": "slug",
}


def load_rows(path: str) -> list[dict]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise nc.UserError(f"plan rows not found: {p}")
    if p.suffix.lower() == ".csv":
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise nc.UserError(f"plan rows {p}: not UTF-8 text") from None
        raw = list(csv.DictReader(io.StringIO(text)))
    else:
        data = nc.read_json(p, "plan rows")
        raw = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
            raise nc.UserError(f"plan rows {p}: expected a list of row objects (or {{\"rows\": [...]}})")
    rows = []
    for i, r in enumerate(raw):
        row = {ALIASES.get(norm_key(k), norm_key(k)): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
        d = row.get("date")
        if not d:
            continue  # blank Sheet lines
        try:
            row["date"] = date.fromisoformat(str(d)[:10])
        except ValueError:
            raise nc.UserError(f"plan rows {p}: row {i + 1}: date must be YYYY-MM-DD, got {d!r}") from None
        rows.append(row)
    return sorted(rows, key=lambda r: (r["date"], str(r.get("day", ""))))


def room_of(text: str, explicit: Any = None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    t = text.lower()
    m = re.match(r"^\s*(?:room\s*:\s*([^|;,:]+)|\[([^\]]+)\])", t)
    if m:
        return (m.group(1) or m.group(2)).strip()
    for room, pat in ROOM_WORDS:
        if re.search(pat, t):
            return room
    return "room not named"


def time_of(text: str, explicit: Any = None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    t = text.lower()
    for name in TIMES:
        if re.search(rf"\b{name}\b", t):
            return name
    if re.search(r"\b(noon|lunch)\b", t):
        return "midday"
    return "any time"


def shots_of(row: dict) -> list[dict]:
    shots = row.get("shots")
    out = []
    items = shots if isinstance(shots, list) else [ln for ln in str(shots or "").splitlines() if ln.strip()]
    for it in items:
        if isinstance(it, dict):
            text = str(it.get("shot") or it.get("text") or it.get("what") or "").strip()
            minutes = it.get("minutes")
            room, when = room_of(text, it.get("room") or row.get("room")), time_of(text, it.get("time_of_day") or it.get("light"))
        else:
            text = re.sub(r"^\s*(\[ ?\]|[-*•]|\d+[.)])\s*", "", str(it)).strip()
            minutes = None
            room, when = room_of(text, row.get("room")), time_of(text)
        if not text:
            continue
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
            minutes = MIN_PER_SHOT
        out.append({"shot": text, "room": room, "time_of_day": when, "minutes": float(minutes),
                    "day": row.get("day"), "date": row["date"].isoformat(), "title": row.get("title")})
    return out


def room_rank(room: str) -> tuple[int, str]:
    return (ROOMS.index(room), "") if room in ROOMS else (len(ROOMS) + (room == "room not named"), room)


def time_rank(t: str) -> int:
    return TIMES.index(t) if t in TIMES else len(TIMES)


def shoot_list(rows: list[dict]) -> dict:
    shots, voiceovers = [], []
    for r in rows:
        status = str(r.get("status") or "").strip().lower()
        if status in DONE_STATUS or NO_FILMING.search(str(r.get("shots") or "")):
            continue
        shots += shots_of(r)
        if str(r.get("script") or "").strip():
            voiceovers.append({"day": r.get("day"), "date": r["date"].isoformat(), "title": r.get("title"),
                               "file_name": f"voiceover (Day {r.get('day')})" if r.get("day") else "voiceover"})
    rooms: dict[str, list[dict]] = {}
    for s in shots:
        rooms.setdefault(s["room"], []).append(s)
    groups = []
    for room in sorted(rooms, key=room_rank):
        items = sorted(rooms[room], key=lambda s: (time_rank(s["time_of_day"]), s["date"], s["shot"]))
        groups.append({"room": room, "shots": items,
                       "minutes": round(sum(s["minutes"] for s in items) + MIN_PER_ROOM, 1)})
    total = sum(g["minutes"] for g in groups) + MIN_PER_VOICEOVER * len(voiceovers)
    return {"rooms": groups, "voiceovers": voiceovers, "shot_count": len(shots),
            "total_minutes": round(total, 1)}


def central_date(tags: dict) -> date | None:
    pt = tags.get("posting_time")
    return mx.to_central(mx.parse_time(pt, "posting_time")).date() if pt else None


def last_week(store: dict, start: date, end: date, rows: list[dict]) -> dict:
    mx.compute(store)
    all_vals: dict[str, list] = {"retention": [], "sends_per_1k_reach": [], "saves_per_1k_reach": []}
    reels = []
    for rid in sorted(store["reels"]):
        reel = store["reels"][rid]
        c = reel.get("computed") or {}
        for k in all_vals:
            if isinstance(c.get(k), (int, float)):
                all_vals[k].append(c[k])
        tags = reel.get("tags") or {}
        d = central_date(tags)
        if d is None or not start <= d <= end:
            continue
        label = mx.latest_pull(reel)
        m = reel["pulls"][label]["metrics"] if label else {}
        reels.append({
            "reel": rid, "title": tags.get("title") or tags.get("slug") or rid, "posted": d.isoformat(),
            "permalink": tags.get("permalink"), "thumbnail": tags.get("thumbnail"), "pull": label,
            "views": m.get("views"), "reach": m.get("reach"), "avg_watch_time_s": c.get("avg_watch_time_s"),
            "sends": m.get("shares"), "saves": m.get("saves"), "retention": c.get("retention"),
            "sends_per_1k_reach": c.get("sends_per_1k_reach"), "saves_per_1k_reach": c.get("saves_per_1k_reach"),
            "skip_rate_vs_median": c.get("skip_rate_vs_median"),
            "tags": {k: tags.get(k) for k in ("series", "pillar", "hook_type", "length", "transitions", "music_source",
                                              "posting_time", "trial_reel", "collab") if k in tags},
        })
    reels.sort(key=lambda r: (r["posted"], r["reel"]))
    medians = {k: round(statistics.median(v), 4) if v else None for k, v in all_vals.items()}
    best = None
    with_views = [r for r in reels if isinstance(r["views"], (int, float))]
    if with_views:
        b = max(with_views, key=lambda r: (r["views"], r["sends"] or 0, r["reel"]))
        signals = []
        for k, label in (("retention", "retention"), ("sends_per_1k_reach", "sends per 1,000 reach"),
                         ("saves_per_1k_reach", "saves per 1,000 reach")):
            if isinstance(b[k], (int, float)) and medians[k] and b[k] > medians[k]:
                signals.append(f"{label} {b[k]:g} vs NUMA median {medians[k]:g}")
        if isinstance(b["skip_rate_vs_median"], (int, float)) and b["skip_rate_vs_median"] < 0:
            signals.append(f"skip rate {abs(b['skip_rate_vs_median']):g} points under NUMA's median")
        best = {"reel": b["reel"], "title": b["title"], "views": b["views"], "signals": signals, "tags": b["tags"]}
    known = {r["reel"] for r in reels} | {r["title"] for r in reels}
    pending = [{"date": r["date"].isoformat(), "title": r.get("title"), "reel_link": r.get("reel_link")}
               for r in rows if start <= r["date"] <= end and str(r.get("status") or "").lower() == "posted"
               and r.get("slug") not in known and r.get("title") not in known]
    return {"start": start.isoformat(), "end": end.isoformat(), "reels": reels, "best": best,
            "medians_all_reels": medians, "posted_without_insights": pending}


def this_week(rows: list[dict], start: date, end: date) -> list[dict]:
    out = []
    for r in rows:
        if start <= r["date"] <= end:
            out.append({"date": r["date"].isoformat(), "weekday": r["date"].strftime("%a"), "day": r.get("day"),
                        "title": r.get("title"), "goal": r.get("goal"), "template": r.get("template"),
                        "hook": r.get("hook"), "status": r.get("status"), "posting_time": r.get("posting_time"),
                        "no_filming": bool(NO_FILMING.search(str(r.get("shots") or "")))})
    return out


def budget(ledger_path: str | None, today: date) -> dict | None:
    if not ledger_path:
        return None
    month = lg.month_of(today)
    rep = lg.report(lg.Ledger(ledger_path).entries(month), month, today, None)
    return {"month": month, "used": rep["used"], "left": rep["left"], "monthly_credits": rep["monthly_credits"],
            "reels_covered": rep["reels_covered"], "per_reel_kling_cost": rep["kling_reel_cost"]["per_reel"],
            "pacing": rep.get("pacing"),
            "categories": {k: {"used": v["used"], "left": v["left"]} for k, v in rep["categories"].items()}}


def load_notes(path: str | None) -> dict:
    if not path:
        return {}
    data = nc.read_json(Path(path).expanduser(), "notes file")
    if not isinstance(data, dict):
        raise nc.UserError("notes file: expected {\"changes\": [...], \"heads_ups\": [...]}")
    for k in ("changes", "heads_ups"):
        if not isinstance(data.get(k, []), list) or not all(isinstance(x, str) for x in data.get(k, [])):
            raise nc.UserError(f"notes file: '{k}' must be a list of sentences")
    return data


def week_bounds(today: date) -> tuple[date, date, date, date]:
    start = today if today.weekday() == 0 else today + timedelta(days=7 - today.weekday())
    return start - timedelta(days=7), start - timedelta(days=1), start, start + timedelta(days=6)


def assemble(store: dict, rows: list[dict], ledger_path: str | None, notes: dict, today: date) -> dict:
    lw0, lw1, tw0, tw1 = week_bounds(today)
    week_rows = [r for r in rows if tw0 <= r["date"] <= tw1]
    data = {
        "schema_version": 1, "today": today.isoformat(),
        "last_week": last_week(store, lw0, lw1, rows),
        "changes": notes.get("changes", []),
        "this_week": {"start": tw0.isoformat(), "end": tw1.isoformat(), "rows": this_week(rows, tw0, tw1)},
        "shoot_list": shoot_list(week_rows),
        "budget": budget(ledger_path, today),
        "heads_ups": notes.get("heads_ups", []),
    }
    needs = []
    if data["last_week"]["best"]:
        needs.append("last_week.best.why")
    for key, empty in (("changes", not data["changes"]), ("heads_ups", not data["heads_ups"]),
                       ("budget", data["budget"] is None)):
        if empty:
            needs.append(key)
    data["needs_director"] = needs
    return data


def _n(x: Any, digits: int = 0) -> str:
    if not isinstance(x, (int, float)):
        return "n/a"
    return f"{x:,.{digits}f}" if digits else f"{round(x):,}"


def text_draft(d: dict) -> str:
    lw, tw = d["last_week"], d["this_week"]
    L: list[str] = [f"NUMA MONDAY DIGEST · week of {date.fromisoformat(tw['start']).strftime('%b %-d')}", ""]
    L.append(f"1. LAST WEEK ({date.fromisoformat(lw['start']).strftime('%b %-d')}–{date.fromisoformat(lw['end']).strftime('%b %-d')})")
    if lw["reels"]:
        for r in lw["reels"]:
            L.append(f"- {r['title']}: {_n(r['views'])} views, {_n(r['avg_watch_time_s'], 1)} s avg watch, {_n(r['sends'])} sends"
                     + (f" · {r['permalink']}" if r.get("permalink") else ""))
        if lw["best"]:
            sig = "; ".join(lw["best"]["signals"])
            L.append(f"Best: {lw['best']['title']} ({_n(lw['best']['views'])} views)" + (f": {sig}" if sig else ""))
    else:
        L.append("- No reels with insights from last week.")
    for p in lw["posted_without_insights"]:
        L.append(f"- {p['title']} ({p['date']}): insights not in yet")
    L.append("")
    if d["changes"]:
        L.append("2. WHAT CHANGED")
        L += [f"- {c}" for c in d["changes"]]
        L.append("")
    L.append("3. THIS WEEK")
    if tw["rows"]:
        for r in tw["rows"]:
            extra = " · no filming needed" if r["no_filming"] else ""
            when = f" · {r['posting_time']}" if r.get("posting_time") else ""
            L.append(f"- {r['weekday']} {date.fromisoformat(r['date']).strftime('%b %-d')}: {r['title'] or 'untitled'}"
                     + (f" ({r['goal']})" if r.get("goal") else "") + when + extra)
    else:
        L.append("- Nothing scheduled in the plan Sheet.")
    L.append("")
    sl = d["shoot_list"]
    L.append(f"4. SHOOT LIST · about {_n(sl['total_minutes'])} min")
    if sl["rooms"]:
        for g in sl["rooms"]:
            L.append(f"{g['room'].upper()} (~{_n(g['minutes'])} min)")
            L += [f"  [ ] {s['shot']}" + (f" · {s['time_of_day']}" if s["time_of_day"] != "any time" else "")
                  + (f" · Day {s['day']}" if s.get("day") else "") for s in g["shots"]]
    else:
        L.append("- No filming needed this week.")
    if sl["voiceovers"]:
        L.append(f"VOICEOVERS, back to back (~{_n(MIN_PER_VOICEOVER * len(sl['voiceovers']))} min): "
                 + ", ".join(f"Day {v['day']}" if v.get("day") else v["date"] for v in sl["voiceovers"]))
    L.append("")
    if d["budget"]:
        b = d["budget"]
        pace = ""
        if b.get("pacing"):
            pace = " · on pace" if b["pacing"]["on_track"] else " · ahead of pace, slowing down"
        L.append("5. BUDGET")
        L.append(f"- Higgsfield: {_n(b['used'])} credits used, {_n(b['left'])} left this month "
                 f"(about {b['reels_covered']} reels){pace}")
        L.append("")
    if d["heads_ups"]:
        L.append("6. HEADS-UPS")
        L += [f"- {h}" for h in d["heads_ups"]]
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="digest_data.py", description="Assemble the Monday digest's numbers (JSON + text draft).")
    ap.add_argument("--metrics", required=True, metavar="METRICS_JSON")
    ap.add_argument("--plan-rows", required=True, metavar="ROWS", help="plan Sheet export (.json or .csv)")
    ap.add_argument("--ledger", metavar="PATH", help="credit ledger file or folder")
    ap.add_argument("--notes", metavar="NOTES_JSON", help="the Director's changes and heads-ups")
    ap.add_argument("--today", metavar="YYYY-MM-DD", help="the digest day (default: today)")
    ap.add_argument("--out", metavar="JSON", help="write the JSON here")
    ap.add_argument("--text", metavar="TXT", help="write the plain-text draft here")
    ap.add_argument("--json", action="store_true", help="print the JSON on stdout")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        raise nc.UsageError(f"--today must be YYYY-MM-DD, got {args.today!r}") from None
    mpath = Path(args.metrics).expanduser().resolve()
    store = mx.load_store(mpath) if mpath.exists() else mx.empty_store()
    if not mpath.exists():
        nc.warn(f"metrics store not found ({mpath}); last week has no insights")
    data = assemble(store, load_rows(args.plan_rows), args.ledger, load_notes(args.notes), today)
    text = text_draft(data)
    if args.out:
        nc.write_json(Path(args.out).expanduser().resolve(), data)
    if args.text:
        t = Path(args.text).expanduser().resolve()
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8", newline="\n")
    if args.json:
        nc.print_json(data)
    elif not (args.out or args.text):
        sys.stdout.write(text)
    else:
        print(f"Wrote {', '.join(x for x in (args.out, args.text) if x)}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
