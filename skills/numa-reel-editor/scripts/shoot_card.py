#!/usr/bin/env python3
"""Month skeleton, shoot cards, plan checks and Sheet export for the 30-day system (spec p.31-37).

Usage:
    shoot_card.py month  YYYY-MM [--json]
    shoot_card.py card   ROW_JSON [--out FILE]
    shoot_card.py check  MONTH_JSON [--closures FILE] [--json]
    shoot_card.py script SCRIPT_JSON [--json]
    shoot_card.py sheet  MONTH_JSON [--csv] [--out FILE]

month   The deterministic skeleton of a calendar month: one row per day with
        the day number, date, weekday, the Drive month folder
        ("2026-12 December") and day folder ("Day 01 - 2026-12-01 - <Title>"),
        and the default-week slot (spec p.34): Mon Ask the DPT reel; Tue
        carousel (from Monday's topic); Wed community reel; Thu Trial Reel +
        Stories; Fri offer, event or collab reel (the week's one sales moment;
        offer weeks and collab weeks alternate); Sat Stories; Sun Regulate
        reel. Each filmed day gets a suggested batch session: Monday films
        Tue-Thu, Thursday films Fri-Mon (two short sessions a week). The
        output has the MONTH_JSON shape that `check` and `sheet` read.

card    The phone-readable shoot card for one plan row (a script.json, or a
        carousel/Stories row) in the spec p.36 format: "No filming needed" as
        the first line when the day needs nothing from Katie, the header
        (DAY · date · title · FILM BY), the filing rules (where, voiceover,
        music, file names, phone settings, changes), numbered checkbox shots
        tied to script lines with framing and duration, "consent list only"
        on people shots, the AI motion shot, the script to read with the
        recording tips, music, length, and the last line "IF YOU CAN'T: skip
        it. ..." Written to --out (UTF-8) or stdout.

check   The planning rules on a month plan (spec p.33-35), where they are
        mechanical; exit 1 on any violation:
          rule 1   no topic repeats within 14 days; at most one sales reel a week
          rule 2   lengths: growth 45-60 s, atmosphere 15-30 s, reels 15-60 s, never over 180 s
          rule 3   originality: no reposts
          rule 4   at least one collab reel and one Meet the Collective a month
          rule 6   one signature transformation/reveal reel a month
          rule 7   every event: teaser 2-3 days before, recap within 2 days after
          rule 8   nothing that invites people in on a closure day
          rule 9   filming grouped into at most 2 batch sessions a week, each before its day
          cadence  4-5 feed posts and 1-2 Trial Reels a week, never a week dark
          series   all five series every month; Ask the DPT never sells
          mix      content mix within +/- mix_tolerance (default 0.10) of the target
          card     every reel row with a script passes the `script` checks
        Rules 5 (the Friday weather swap) and 10 (re-tuning after 30 reels)
        are the Director's judgment and are not checked here. Month-level
        rules (4, 6, series, mix) apply to calendar months the plan fully
        covers.

script  The card rules and timing for one script.json (spec p.35-36): the
        schema (schemas/script.schema.json); words <= 2.3 x (length_s -
        outro_s) (config render.words_per_second, outro default
        render.outro_music_only_s.default); at most 8 new shots; exactly one
        ai_motion shot; every shot tied to an existing line with framing and
        seconds; shots numbered 1..N; people shots => needs_consent; the
        template id exists in skills/numa-scriptwriter/templates.json; Ask the
        DPT never sells; and claims_scan over every text (title, hook, lines,
        shots, photos, on-screen text, CTA, share line, caption, hashtags).
        Exit 1 on any ERROR; WARN lines never change the exit code.

sheet   The plan as "NUMA 30-Day Reel Plan" Sheet rows with exactly the spec
        p.33 columns, in order: Day, Date, Title, Goal, Template, Hook (first 2
        seconds), Voiceover script, Shot list, Music mood + BPM, Call to
        action, Status, Folder link, Reel link. JSON (a list of row objects) by
        default, CSV with --csv; stdout or --out. The Shot list holds only the
        shots Katie films, one per line as "N. [room] Framing: what, S s, time
        (line L)", or "No filming needed"; digest_data.py reads this export.

MONTH_JSON: {"month": "2026-12", "rows": [row, ...], "events": [{"name", "date"}],
"closures": ["YYYY-MM-DD" | {"date", "name"}], "mix": {pillar: share},
"mix_tolerance": 0.10} or a bare list of rows. A row has at least day, date and
kind (reel, trial_reel, carousel, stories); reel rows carry the script.json
fields once scripted. Defaults: topic = title; sales = goal is offer, or an
offer or booking ask ("book", "$49", a brand.json offer name such as Discover
NUMA) in the CTA, hook, lines or on-screen text (`sales: true` forces it; false
never hides it); invites = sales, an event teaser, or a booking-style CTA; mix = brand.json
positioning.content_mix. --closures FILE: JSON (list of dates or
{"date", "name"} objects, or {"closures": [...]}) or CSV with a Date column;
merged with MONTH_JSON closures and brand.json closures.known.
"""
from __future__ import annotations

import calendar
import csv
import io
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims_scan  # noqa: E402
import numa_common as nc  # noqa: E402

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_SHORT = [m[:3] for m in MONTHS]
ROOMS = ["plunge room", "sauna", "class studio", "front of house", "outside"]
SERIES = ["ask_the_dpt", "first_plunge", "too_hot_for_a_diy_plunge", "regulate", "meet_the_collective"]
PILLARS = ["education", "community", "local_seasonal", "collective_collabs", "offers_events"]
KINDS = ["reel", "trial_reel", "carousel", "stories"]
REEL_KINDS = {"reel", "trial_reel"}
FEED_KINDS = {"reel", "carousel"}
TOPIC_KINDS = {"reel", "trial_reel", "carousel"}
SHEET_COLUMNS = ["Day", "Date", "Title", "Goal", "Template", "Hook (first 2 seconds)", "Voiceover script",
                 "Shot list", "Music mood + BPM", "Call to action", "Status", "Folder link", "Reel link"]
STATUSES = ["Planned", "Shot", "Ready to build", "Ready to post", "Posted"]
MAX_NEW_SHOTS = 8
TOPIC_GAP_DAYS = 14
TEASER_WINDOW = (2, 3)      # days before the event
RECAP_WINDOW = (1, 2)       # days after the event
FEED_PER_WEEK = (4, 5)
TRIAL_PER_WEEK = (1, 2)
MAX_SESSIONS_PER_WEEK = 2
DEFAULT_MIX_TOLERANCE = 0.10
TEMPLATES_PATH = nc.PLUGIN_ROOT / "skills" / "numa-scriptwriter" / "templates.json"
INVITE_CTA = re.compile(
    r"\b(book|booking|come in|come by|join us|see you|sign up|try (?:a|your first) (?:month|session|class)|"
    r"discover numa|first month|drop[- ]in|reserve|rsvp|tickets?|visit us|walk in)\b", re.I)
SALES_TEXT = re.compile(
    r"\b(book|booking|first month|try a month|discover numa|drop[- ]in|membership|sign up|tickets?)\b|\$\s?\d+",
    re.I)
SAFETY_TOPIC = re.compile(r"\b(plunge|cold|ice|sauna|heat|hot)\b", re.I)

# Default week (spec p.34). Fri alternates offer weeks and collab weeks (one sales moment a week).
DEFAULT_WEEK: list[dict[str, Any]] = [
    {"slot": "ask_the_dpt_reel", "kind": "reel", "post": "Ask the DPT reel, 45-60 s", "series": "ask_the_dpt",
     "pillar": "education", "goal": "education", "length_class": "growth", "template": "modality_explainer",
     "slot_notes": "Education; no booking pitch in it", "films": True},
    {"slot": "carousel", "kind": "carousel", "post": "Carousel", "series": None, "pillar": "education",
     "goal": "education", "slot_notes": "Saveable explainer or protocol from Monday's topic", "films": False},
    {"slot": "community_reel", "kind": "reel", "post": "Community reel (First Plunge or member moment)",
     "series": "first_plunge", "pillar": "community", "goal": "community", "template": "member_story",
     "slot_notes": "Built for sends", "films": True},
    {"slot": "trial_reel", "kind": "trial_reel", "post": "Trial Reel + Stories", "series": "too_hot_for_a_diy_plunge",
     "pillar": "local_seasonal", "goal": "awareness", "template": "seasonal_holiday",
     "slot_notes": "Tests a new hook on non-followers", "films": True},
    {"slot": "offer_event_collab_reel", "kind": "reel", "post": "Offer, event or collab reel", "series": None,
     "pillar": "offers_events", "goal": "offer", "template": "offer_promo",
     "slot_notes": "The week's one sales moment", "films": True},
    {"slot": "stories", "kind": "stories", "post": "Stories", "series": None, "pillar": None, "goal": None,
     "slot_notes": "Behind the scenes, class energy", "films": False},
    {"slot": "regulate_reel", "kind": "reel", "post": "Regulate reel or Stories", "series": "regulate",
     "pillar": "education", "goal": "education", "length_class": "growth", "template": "modality_explainer",
     "slot_notes": "Calm, reflective", "films": True},
]
COLLAB_FRIDAY = {"pillar": "collective_collabs", "goal": "community", "template": "class_spotlight",
                 "slot_notes": "Collab week: 'Sweat there, recover here' or Meet the Collective"}

FILING_RULES = [
    "Photos -> photos/   Videos -> clips/   Voice memo -> name it \"voiceover {nn}\"",
    "Only in this day's folder. File names don't matter; Claude sorts by content.",
    "Re-record: replace the voiceover file. Reading the week's scripts back to back is fine: one file per day.",
    "Music: optional. Drop a track here, or Claude picks from Music Library by the mood below.",
    "Changes: optional. Edit this day's Sheet row; nothing waits on it.",
]
PHONE_SETTINGS = "phone vertical, 4K at 30 fps, hold each shot 5 seconds, don't zoom"
RECORDING_TIPS = ("quiet room with soft surfaces like a closet or carpeted bedroom, phone 12 inches away, "
                  "normal voice, one take, 1 second of silence at the start and end")
LAST_LINE = "IF YOU CAN'T: skip it. Claude will find another way."


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def parse_month(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(text).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise nc.UsageError(f"month must be YYYY-MM, got {text!r}")
    return int(m.group(1)), int(m.group(2))


def parse_date(value: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise nc.UserError(f"{what}: date must be YYYY-MM-DD, got {value!r}") from None


def month_folder(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d} {MONTHS[d.month - 1]}"


def safe_title(title: str) -> str:
    """A title that works as the end of a Drive folder name."""
    t = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", str(title))
    t = " ".join(t.split()).strip(" .")
    return t[:60].rstrip(" .")


def day_folder(day: int, d: date, title: str | None) -> str:
    return f"Day {day:02d} - {d.isoformat()} - {safe_title(title) if title else '<Title>'}"


def short_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {MONTHS_SHORT[d.month - 1]} {d.day}"


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def word_count(text: str) -> int:
    return sum(1 for tok in str(text).split() if re.search(r"[A-Za-z0-9]", tok))


def norm_topic(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def truthy(v: Any) -> bool:
    return bool(v) and v not in ("no", "false", "0")


def load_templates() -> dict[str, dict]:
    data = nc.read_json(TEMPLATES_PATH, "template library")
    out = {}
    for group in ("templates", "presets"):
        for t in data.get(group, []):
            out[t["id"]] = t
    return out


def config_wps() -> float:
    return float(nc.config_value("render.words_per_second", 2.3))


def config_outro() -> float:
    outro = nc.config_value("render.outro_music_only_s", {}) or {}
    return float(outro.get("default", 7.5)) if isinstance(outro, dict) else float(outro)


def length_ranges() -> dict[str, list[float]]:
    lr = nc.config_value("render.length_s", {}) or {}
    return {"main_reel": lr.get("main_reel", [15, 60]), "growth": lr.get("growth", [45, 60]),
            "atmosphere": lr.get("atmosphere", [15, 30]), "hard_max": lr.get("hard_max", 180)}


def series_lengths() -> dict[str, list[float]]:
    out = {}
    for s in nc.brand_value("positioning.series", []) or []:
        if isinstance(s, dict) and s.get("id") and isinstance(s.get("length_s"), list):
            out[s["id"]] = s["length_s"]
    return out


# ---------------------------------------------------------------------------
# month skeleton
# ---------------------------------------------------------------------------
def batch_session(d: date) -> tuple[date, str]:
    """Monday films Tue-Thu; Thursday films Fri-Mon (Monday's reel in the Thursday before)."""
    wd = d.weekday()
    if wd in (1, 2, 3):
        return monday_of(d), "Mon"
    if wd in (4, 5, 6):
        return monday_of(d) + timedelta(days=3), "Thu"
    return d - timedelta(days=4), "Thu"


def skeleton(year: int, month: int) -> dict:
    days = calendar.monthrange(year, month)[1]
    rows = []
    for day in range(1, days + 1):
        d = date(year, month, day)
        slot = dict(DEFAULT_WEEK[d.weekday()])
        if slot["slot"] == "offer_event_collab_reel" and (d.day - 1) // 7 % 2 == 1:
            slot.update(COLLAB_FRIDAY)
        films = slot.pop("films")
        row: dict[str, Any] = {
            "day": day, "date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
            "folder": day_folder(day, d, None), "title": None, "status": "Planned",
        }
        row.update(slot)
        if row["kind"] == "trial_reel":
            row["trial_reel"] = True
        if row["slot"] == "carousel":
            prev = d - timedelta(days=1)
            row["derived_from"] = prev.day if prev.month == month else None
        if films:
            fb, session = batch_session(d)
            row["film_by"], row["batch_session"] = fb.isoformat(), session
        else:
            row["film_by"], row["batch_session"] = None, None
        rows.append(row)
    first = date(year, month, 1)
    return {"schema_version": 1, "month": f"{year:04d}-{month:02d}", "month_folder": month_folder(first),
            "days": days, "mix": nc.brand_value("positioning.content_mix", {}),
            "mix_tolerance": DEFAULT_MIX_TOLERANCE, "events": [], "closures": [], "rows": rows}


def cmd_month(args) -> int:
    year, month = parse_month(args.month)
    sk = skeleton(year, month)
    if args.json:
        nc.print_json(sk)
        return 0
    print(f"{sk['month_folder']} ({sk['days']} days)")
    for r in sk["rows"]:
        film = f" · film by {short_date(date.fromisoformat(r['film_by']))}" if r["film_by"] else ""
        print(f"{r['folder']} · {r['weekday']} · {r['post']}" + (f" ({r['pillar']})" if r.get("pillar") else "") + film)
    return 0


# ---------------------------------------------------------------------------
# plan loading
# ---------------------------------------------------------------------------
def load_plan(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    data = nc.read_json(p, "month plan")
    if isinstance(data, list):
        data = {"rows": data}
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise nc.UserError(f"month plan {p}: expected {{\"rows\": [...]}} or a list of rows")
    rows = []
    for i, r in enumerate(data["rows"]):
        where = f"month plan row {i + 1}"
        if not isinstance(r, dict):
            raise nc.UserError(f"{where}: expected an object")
        for key in ("day", "date", "kind"):
            if r.get(key) in (None, ""):
                raise nc.UserError(f"{where}: missing '{key}'")
        if r["kind"] not in KINDS:
            raise nc.UserError(f"{where}: kind must be one of {', '.join(KINDS)}, got {r['kind']!r}")
        d = parse_date(r["date"], where)
        if not isinstance(r["day"], int) or isinstance(r["day"], bool) or r["day"] != d.day:
            raise nc.UserError(f"{where}: day {r['day']!r} does not match date {d.isoformat()}")
        rows.append({**r, "_d": d})
    rows.sort(key=lambda r: (r["_d"], KINDS.index(r["kind"])))
    for key in ("events", "closures"):
        if not isinstance(data.get(key, []), list):
            raise nc.UserError(f"month plan: '{key}' must be a list")
    return {**data, "rows": rows}


def closure_dates(plan: dict, closures_file: str | None) -> dict[date, str]:
    items: list[Any] = list(plan.get("closures", []))
    known = nc.brand_value("closures.known")
    if isinstance(known, list):
        items += known
    if closures_file:
        p = Path(closures_file).expanduser().resolve()
        if not p.exists():
            raise nc.UserError(f"closures file not found: {p}")
        if p.suffix.lower() == ".csv":
            reader = csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig")))
            key = next((k for k in (reader.fieldnames or []) if k and k.strip().lower() == "date"), None)
            if key is None:
                raise nc.UserError(f"closures file {p}: needs a Date column")
            name_key = next((k for k in (reader.fieldnames or []) if k and k.strip().lower() in ("name", "reason")), None)
            items += [{"date": row[key], "name": row.get(name_key) if name_key else None}
                      for row in reader if (row.get(key) or "").strip()]
        else:
            data = nc.read_json(p, "closures file")
            data = data.get("closures") if isinstance(data, dict) else data
            if not isinstance(data, list):
                raise nc.UserError(f"closures file {p}: expected a list of dates or {{\"closures\": [...]}}")
            items += data
    out: dict[date, str] = {}
    for it in items:
        if isinstance(it, dict):
            out[parse_date(it.get("date"), "closure")] = str(it.get("name") or "closed")
        else:
            out[parse_date(it, "closure")] = "closed"
    return out


def row_topic(r: dict) -> str | None:
    t = r.get("topic") or r.get("title")
    if not t:
        return None
    return norm_topic(t) + (f" #{r['event_role']}" if r.get("event_role") else "")


def offer_words() -> re.Pattern:
    names = [str(o.get("name")) for o in (nc.brand_value("offerings.offers", []) or [])
             if isinstance(o, dict) and o.get("name")]
    alt = "|".join(re.escape(n) for n in names)
    return re.compile(SALES_TEXT.pattern + (rf"|\b(?:{alt})\b" if alt else ""), re.I)


def row_texts(r: dict) -> str:
    parts = [r.get("cta"), r.get("hook_text"), *(r.get("lines") or []), *(r.get("on_screen") or [])]
    return " ".join(str(x) for x in parts if isinstance(x, str))


def is_sales(r: dict) -> bool:
    """A sales-focused post: goal offer, or an offer/booking ask in its CTA, hook, lines or on-screen text.

    `sales: true` forces it on; a `false` never hides a goal or text that sells.
    """
    if r.get("sales") is True or r.get("goal") == "offer":
        return True
    return bool(offer_words().search(row_texts(r)))


def is_invite(r: dict) -> bool:
    if "invites" in r:
        return bool(r["invites"])
    if is_sales(r) or r.get("event_role") == "teaser":
        return True
    return bool(INVITE_CTA.search(str(r.get("cta") or "")))


def is_collab(r: dict) -> bool:
    return truthy(r.get("collab")) and r.get("series") != "meet_the_collective"


def new_shots(r: dict) -> list[dict]:
    return [s for s in r.get("shots") or [] if isinstance(s, dict) and s.get("source", "new") == "new"]


def needs_filming(r: dict) -> bool:
    return r.get("kind") in REEL_KINDS and bool(new_shots(r))


def needs_reading(r: dict) -> bool:
    by = str(r.get("voiceover_by") or "Katie").strip().lower()
    return r.get("kind", "reel") in REEL_KINDS and bool(r.get("lines")) and by not in ("generated", "none")


def label(r: dict) -> str:
    return f"Day {r['day']:02d} ({r['_d'].isoformat()})"


# ---------------------------------------------------------------------------
# script.json checks
# ---------------------------------------------------------------------------
def script_problems(s: dict, templates: dict | None = None, where: str = "script") -> tuple[list[str], list[str]]:
    """(errors, warnings) for one script.json / reel row."""
    errs, warns = [], []
    clean = {k: v for k, v in s.items() if not k.startswith("_")}
    for e in nc.schema_errors("script.schema.json", clean):
        errs.append(f"{where}: {e}")
    if errs:
        return errs, warns
    lines, shots = s["lines"], s["shots"]
    wps, outro = config_wps(), float(s.get("outro_s", config_outro()))
    limit = wps * (float(s["length_s"]) - outro)
    words = sum(word_count(x) for x in lines)
    if words > limit:
        errs.append(f"{where}: script is {words} words; {s['length_s']:g} s with a {outro:g} s outro allows "
                    f"{int(limit)} ({wps:g} words/s x {s['length_s'] - outro:g} s)")
    elif words < 0.35 * limit and str(s.get("voiceover_by", "")).lower() != "none":
        warns.append(f"{where}: script is {words} words, under a third of the {int(limit)} the length allows")
    fresh = [x for x in shots if x.get("source", "new") == "new"]
    if len(fresh) > MAX_NEW_SHOTS:
        errs.append(f"{where}: {len(fresh)} new shots; at most {MAX_NEW_SHOTS} (reuse library shots for the rest)")
    ai = [x["n"] for x in shots if x["ai_motion"]]
    if len(ai) != 1:
        errs.append(f"{where}: {len(ai)} AI motion shots ({', '.join(map(str, ai)) or 'none'}); mark exactly one")
    if [x["n"] for x in shots] != list(range(1, len(shots) + 1)):
        errs.append(f"{where}: shots must be numbered 1..{len(shots)} in order")
    for x in shots:
        if not 1 <= x["line"] <= len(lines):
            errs.append(f"{where}: shot {x['n']} is tied to line {x['line']}, but the script has {len(lines)} lines")
    people = [x["n"] for x in shots if x["people"]]
    if people and not s["needs_consent"]:
        errs.append(f"{where}: shots {', '.join(map(str, people))} show people; set needs_consent (consent list only)")
    if s["needs_consent"] and not people:
        warns.append(f"{where}: needs_consent is set but no shot has people")
    if fresh and not s.get("film_by"):
        errs.append(f"{where}: {len(fresh)} shots to film but no film_by date")
    if s.get("film_by") and s["film_by"] >= s["date"]:
        errs.append(f"{where}: film_by {s['film_by']} must be before the reel's date {s['date']}")
    if fresh and not s.get("batch_room"):
        warns.append(f"{where}: no batch_room; the digest cannot group these shots by room")
    if templates is not None and s["template"] not in templates:
        errs.append(f"{where}: unknown template {s['template']!r} (skills/numa-scriptwriter/templates.json)")
    if s.get("series") == "ask_the_dpt" and (is_sales(s) or INVITE_CTA.search(row_texts(s))):
        errs.append(f"{where}: Ask the DPT is education only; no booking pitch or offer in the same reel")
    hook_words = set(norm_topic(s["hook_text"]).split())
    if hook_words and not hook_words & set(norm_topic(lines[0]).split()):
        warns.append(f"{where}: line 1 should speak the hook ({s['hook_text']!r})")
    if not s.get("share_line"):
        warns.append(f"{where}: no share line (a reason to send it)")
    texts = [s["title"], s["hook_text"], *lines, *(x["what"] for x in shots), *s.get("photos", []),
             *s.get("on_screen", []), s["cta"], s.get("share_line") or ""]
    if not s["safety_line"] and SAFETY_TOPIC.search(" ".join(texts)):
        warns.append(f"{where}: cold or heat reel without safety_line (brand.json claims.safety_line)")
    surfaces = [("title", s["title"]), ("hook", s["hook_text"])]
    surfaces += [(f"line {i}", t) for i, t in enumerate(lines, 1)]
    surfaces += [(f"shot {x['n']}", x["what"]) for x in shots]
    surfaces += [("photos", t) for t in s.get("photos", [])] + [("on-screen text", t) for t in s.get("on_screen", [])]
    surfaces += [("cta", s["cta"]), ("share line", s.get("share_line") or "")]
    cap = s.get("caption") or {}
    surfaces += [("caption", cap.get("text") or ""), ("hashtags", " ".join(cap.get("hashtags") or []))]
    for name, text in surfaces:
        if not text:
            continue
        for h in claims_scan.scan_text(text, where=f"{where} {name}"):
            (errs if h.severity == "fail" else warns).append(h.line())
    return errs, warns


def cmd_script(args) -> int:
    p = Path(args.script).expanduser().resolve()
    s = nc.read_json(p, "script.json")
    if not isinstance(s, dict):
        raise nc.UserError(f"script.json {p}: expected an object")
    errs, warns = script_problems(s, load_templates(), where=p.name)
    if args.json:
        nc.print_json({"ok": not errs, "errors": errs, "warnings": warns,
                       "words": sum(word_count(x) for x in s.get("lines") or [] if isinstance(x, str))})
    else:
        for w in warns:
            nc.warn(w)
        for e in errs:
            nc.error_line(e)
        if not errs:
            print(f"OK: {p.name} passes the card rules" + (f" ({len(warns)} warnings)" if warns else ""))
    return 1 if errs else 0


# ---------------------------------------------------------------------------
# month checks
# ---------------------------------------------------------------------------
def full_months(rows: list[dict]) -> list[tuple[int, int]]:
    have: dict[tuple[int, int], set[int]] = {}
    for r in rows:
        have.setdefault((r["_d"].year, r["_d"].month), set()).add(r["_d"].day)
    return [ym for ym, days in sorted(have.items()) if len(days) == calendar.monthrange(*ym)[1]]


def check_plan(plan: dict, closures: dict[date, str]) -> tuple[list[dict], list[str], dict]:
    rows = plan["rows"]
    V: list[dict] = []
    W: list[str] = []

    def bad(rule: str, msg: str, days: list[int] | None = None) -> None:
        V.append({"rule": rule, "days": days or [], "message": msg})

    if not rows:
        bad("plan", "the plan has no rows")
        return V, W, {}
    by_date: dict[date, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["_d"], []).append(r)
    first, last = rows[0]["_d"], rows[-1]["_d"]
    span = (last - first).days + 1
    missing = [first + timedelta(days=i) for i in range(span) if first + timedelta(days=i) not in by_date]
    if missing:
        bad("cadence", "days with nothing planned (something posts every day): "
            + ", ".join(d.isoformat() for d in missing), [d.day for d in missing])

    # rule 1: topics and sales
    topical = [r for r in rows if r["kind"] in TOPIC_KINDS and not r.get("derived_from")]
    for i, a in enumerate(topical):
        ta = row_topic(a)
        if not ta:
            if a["kind"] in REEL_KINDS:
                W.append(f"{label(a)}: no title or topic yet")
            continue
        for b in topical[i + 1:]:
            gap = (b["_d"] - a["_d"]).days
            if gap >= TOPIC_GAP_DAYS:
                break
            if row_topic(b) == ta:
                bad("1-topic-repeat", f"{label(b)}: topic {ta!r} repeats {label(a)} after {gap} days "
                    f"(needs {TOPIC_GAP_DAYS})", [a["day"], b["day"]])
    weeks: dict[date, list[dict]] = {}
    for r in rows:
        weeks.setdefault(monday_of(r["_d"]), []).append(r)
    for wk, wrows in sorted(weeks.items()):
        sales = [r for r in wrows if r["kind"] in TOPIC_KINDS and is_sales(r)]
        if len(sales) > 1:
            bad("1-sales-per-week", f"week of {wk.isoformat()}: {len(sales)} sales-focused posts "
                f"({', '.join(label(r) for r in sales)}); at most one a week", [r["day"] for r in sales])

    # rule 2 + 3: lengths and originality
    lr, sl = length_ranges(), series_lengths()
    for r in rows:
        if truthy(r.get("repost")):
            bad("3-original", f"{label(r)}: reposts are never planned; other people's content only as a collab post",
                [r["day"]])
        if r["kind"] not in REEL_KINDS or r.get("length_s") is None:
            continue
        n = r["length_s"]
        if not isinstance(n, (int, float)) or isinstance(n, bool):
            bad("2-length", f"{label(r)}: length_s must be a number", [r["day"]])
            continue
        rng, why = lr["main_reel"], "a reel"
        if r.get("length_class") in ("growth", "atmosphere"):
            rng, why = lr[r["length_class"]], f"a {r['length_class']} reel"
        elif r.get("series") in sl:
            rng, why = sl[r["series"]], f"the {r['series']} series"
        if n > lr["hard_max"]:
            bad("2-length", f"{label(r)}: {n:g} s is over the {lr['hard_max']} s hard maximum", [r["day"]])
        elif not rng[0] <= n <= rng[1]:
            bad("2-length", f"{label(r)}: {n:g} s; {why} runs {rng[0]}-{rng[1]} s", [r["day"]])

    # rule 7: events
    for ev in plan.get("events", []):
        if not isinstance(ev, dict) or not ev.get("name") or not ev.get("date"):
            raise nc.UserError("month plan: each event needs 'name' and 'date'")
        ed, name = parse_date(ev["date"], f"event {ev['name']}"), str(ev["name"])
        for role, (lo, hi), sign in (("teaser", TEASER_WINDOW, -1), ("recap", RECAP_WINDOW, 1)):
            window = sorted(ed + timedelta(days=sign * k) for k in range(lo, hi + 1))
            if window[0] < first or window[-1] > last:
                if not any(first <= d <= last for d in window):
                    W.append(f"event {name} {ed.isoformat()}: the {role} window is outside this plan")
                    continue
            hits = [r for r in rows if r.get("event_role") == role and norm_topic(r.get("event") or "") == norm_topic(name)]
            inside = [r for r in hits if window[0] <= r["_d"] <= window[-1]]
            if not inside:
                when = f"{window[0].isoformat()}..{window[-1].isoformat()}"
                found = f" (found {', '.join(label(r) for r in hits)})" if hits else ""
                bad("7-event-window", f"event {name} on {ed.isoformat()}: needs a {role} between {when}{found}",
                    [r["day"] for r in hits])

    # rule 8: closures
    for d, why in sorted(closures.items()):
        for r in by_date.get(d, []):
            if r["kind"] != "stories" and is_invite(r):
                bad("8-closure", f"{label(r)}: invites people in on a closure day ({why})", [r["day"]])
            elif r["kind"] == "stories" and truthy(r.get("invites")):
                bad("8-closure", f"{label(r)}: Stories invite people in on a closure day ({why})", [r["day"]])

    # rule 9: batch sessions
    sessions: dict[date, set[date]] = {}
    for r in rows:
        fb = r.get("film_by")
        if not fb:
            if needs_filming(r):
                bad("9-batch", f"{label(r)}: shots to film but no film_by date", [r["day"]])
            continue
        fbd = parse_date(fb, f"{label(r)} film_by")
        if fbd >= r["_d"]:
            bad("9-batch", f"{label(r)}: film_by {fbd.isoformat()} is not before the reel's day", [r["day"]])
        sessions.setdefault(monday_of(fbd), set()).add(fbd)
    for wk, ds in sorted(sessions.items()):
        if len(ds) > MAX_SESSIONS_PER_WEEK:
            bad("9-batch", f"week of {wk.isoformat()}: {len(ds)} filming sessions "
                f"({', '.join(d.isoformat() for d in sorted(ds))}); group them into at most {MAX_SESSIONS_PER_WEEK}")

    # cadence
    carousels = feed_total = 0
    for wk, wrows in sorted(weeks.items()):
        feed = [r for r in wrows if r["kind"] in FEED_KINDS]
        trials = [r for r in wrows if r["kind"] == "trial_reel" or (r["kind"] == "reel" and truthy(r.get("trial_reel")))]
        feed_total += len(feed)
        carousels += sum(r["kind"] == "carousel" for r in feed)
        ndays = len({r["_d"] for r in wrows})
        if ndays == 7:
            if not FEED_PER_WEEK[0] <= len(feed) <= FEED_PER_WEEK[1]:
                bad("cadence", f"week of {wk.isoformat()}: {len(feed)} feed posts; plan "
                    f"{FEED_PER_WEEK[0]}-{FEED_PER_WEEK[1]} a week")
            if not TRIAL_PER_WEEK[0] <= len(trials) <= TRIAL_PER_WEEK[1]:
                bad("cadence", f"week of {wk.isoformat()}: {len(trials)} Trial Reels; plan "
                    f"{TRIAL_PER_WEEK[0]}-{TRIAL_PER_WEEK[1]} a week")
        else:
            if ndays >= 3 and not feed:
                bad("cadence", f"week of {wk.isoformat()}: no feed post (never a week dark)")
            if len(feed) > FEED_PER_WEEK[1] or len(trials) > TRIAL_PER_WEEK[1]:
                bad("cadence", f"week of {wk.isoformat()}: {len(feed)} feed posts and {len(trials)} Trial Reels; "
                    f"at most {FEED_PER_WEEK[1]} and {TRIAL_PER_WEEK[1]}")
    if feed_total and not 0.15 <= carousels / feed_total <= 0.45:
        W.append(f"carousels are {carousels} of {feed_total} feed posts; about a third is the target")

    # month-level: collabs, Meet the Collective, signature, series rotation, mix
    mix_report: dict = {}
    months = full_months(rows)
    if not months:
        W.append("the plan covers no full calendar month; the monthly rules (collab, signature, series, mix) were skipped")
    target = plan.get("mix") or nc.brand_value("positioning.content_mix", {}) or {}
    tol = float(plan.get("mix_tolerance", DEFAULT_MIX_TOLERANCE))
    if months and (set(target) != set(PILLARS) or abs(sum(target.values()) - 1.0) > 0.01):
        raise nc.UserError(f"content mix must give a share for each of {', '.join(PILLARS)} summing to 1.0")
    for (y, m) in months:
        mrows = [r for r in rows if (r["_d"].year, r["_d"].month) == (y, m)]
        tag = f"{y:04d}-{m:02d}"
        reels = [r for r in mrows if r["kind"] in REEL_KINDS]
        if not any(is_collab(r) for r in reels):
            bad("4-collab", f"{tag}: no collab reel ('Sweat there, recover here'); plan at least one a month")
        if not any(r.get("series") == "meet_the_collective" for r in reels):
            bad("4-meet-the-collective", f"{tag}: no Meet the Collective feature; plan one a month")
        if not any(truthy(r.get("signature")) or r.get("template") == "transformation" for r in reels):
            bad("6-signature", f"{tag}: no signature transformation or reveal reel; plan one a month")
        missing_series = [s for s in SERIES if not any(r.get("series") == s for r in reels)]
        if missing_series:
            bad("series", f"{tag}: series not in rotation this month: {', '.join(missing_series)}")
        counted = [r for r in mrows if r["kind"] in TOPIC_KINDS and not r.get("derived_from")]
        pill = [r.get("pillar") for r in counted]
        if any(p not in PILLARS for p in pill):
            unknown = sorted({str(p) for p in pill if p not in PILLARS})
            bad("mix", f"{tag}: rows without a known pillar ({', '.join(unknown)})",
                [r["day"] for r in counted if r.get("pillar") not in PILLARS])
            continue
        shares = {p: round(pill.count(p) / len(pill), 4) if pill else 0.0 for p in PILLARS}
        mix_report[tag] = {"posts": len(pill), "shares": shares, "target": target, "tolerance": tol}
        for p in PILLARS:
            if abs(shares[p] - float(target[p])) > tol + 1e-9:
                bad("mix", f"{tag}: {p} is {shares[p]:.0%} of {len(pill)} planned posts; target "
                    f"{float(target[p]):.0%} +/- {tol:.0%}")

    # per-row card rules
    templates = load_templates()
    for r in rows:
        if r["kind"] in REEL_KINDS and r.get("lines"):
            row = {k: v for k, v in r.items() if k != "_d"}
            errs, warns = script_problems(row, templates, where=label(r))
            for e in errs:
                bad("card", e, [r["day"]])
            W.extend(warns)
        elif r["kind"] in REEL_KINDS and r.get("series") == "ask_the_dpt" and is_sales(r):
            bad("series", f"{label(r)}: Ask the DPT is education only; no booking pitch in the same reel", [r["day"]])
    return V, W, mix_report


def cmd_check(args) -> int:
    plan = load_plan(args.plan)
    closures = closure_dates(plan, args.closures)
    V, W, mix = check_plan(plan, closures)
    if args.json:
        nc.print_json({"ok": not V, "violations": V, "warnings": W, "mix": mix,
                       "closures": sorted(d.isoformat() for d in closures)})
    else:
        for w in W:
            nc.warn(w)
        for v in V:
            nc.error_line(f"rule {v['rule']}: {v['message']}")
        if not V:
            print(f"OK: {len(plan['rows'])} rows pass the planning rules" + (f" ({len(W)} warnings)" if W else ""))
    return 1 if V else 0


# ---------------------------------------------------------------------------
# shoot card
# ---------------------------------------------------------------------------
def music_text(music: dict | None) -> str:
    if not music:
        return "MUSIC: none needed (Claude picks it)."
    bpm = music.get("bpm") or []
    tempo = f", {bpm[0]}-{bpm[1]} BPM" if len(bpm) == 2 else ""
    mood = f"{music.get('mood', '')}{tempo}".strip(", ")
    src = music.get("source")
    if src == "generate":
        return f"MUSIC: none needed (Claude makes it: {mood})."
    if src == "library":
        track = f" \"{music['track']}\"" if music.get("track") else " by mood"
        return f"MUSIC: none needed (Claude picks from Music Library{track}: {mood})."
    if src == "natural":
        return "MUSIC: none needed (the clips' own sound)."
    return f"MUSIC: optional. Drop a {mood} track named \"music\" here, or Claude picks one."


def shot_text(s: dict) -> str:
    framing = {"wide": "Wide", "medium": "Medium", "close": "Close-up", "overhead": "Overhead"}[s["framing"]]
    if s.get("kind", "video") == "photo":
        body = f"Photo, {framing.lower()}: {s['what']}"
    else:
        body = f"{framing}: {s['what']}, {s['seconds']:g} s"
    if s.get("time_of_day"):
        body += f", {s['time_of_day']}"
    tags = []
    if s.get("during"):
        tags.append(f"during {s['during']}")
    if s["people"]:
        tags.append("consent list only")
    tags.append(f"line {s['line']}")
    if s["ai_motion"]:
        tags.append("AI motion shot")
    return f"{body}   ({') ('.join(tags)})"


def render_card(r: dict) -> str:
    for key in ("day", "date", "title"):
        if r.get(key) in (None, ""):
            raise nc.UserError(f"plan row: missing '{key}'")
    d = parse_date(r["date"], "plan row")
    kind = r.get("kind", "reel")
    if kind not in KINDS:
        raise nc.UserError(f"plan row: kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if kind in REEL_KINDS:
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        errs = nc.schema_errors("script.schema.json", clean)
        if errs:
            raise nc.UserError(f"plan row Day {r['day']}: {errs[0]}" + (f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""))
    folder = day_folder(int(r["day"]), d, r["title"])
    fresh = new_shots(r) if kind in REEL_KINDS else []
    reading = needs_reading(r)
    nothing = not fresh and not reading
    L: list[str] = []
    if nothing:
        what = {"carousel": "Claude builds this carousel from this week's reel and the library.",
                "stories": "Claude cuts today's Stories from this week's material."}.get(
            kind, "Claude builds this reel from the media library and brand photos.")
        L += [f"NO FILMING NEEDED. {what}", ""]
    film_by = ""
    if r.get("film_by") and not nothing:
        fb = parse_date(r["film_by"], "film_by")
        room = f": {r['batch_room']}" if r.get("batch_room") else ""
        film_by = f"    FILM BY: {short_date(fb)} (batch shoot{room})"
    L.append(f"DAY {int(r['day']):02d} · {short_date(d)} · \"{r['title']}\"{film_by}")
    L.append("")
    root = nc.brand_value("drive.root", "NUMA Reels")
    L.append("WHERE TO PUT FILES")
    L.append(f"  Drive > {root} > {month_folder(d)} > {folder}")
    L += [f"  {x}".replace("{nn}", f"{int(r['day']):02d}") for x in FILING_RULES]
    L.append("")
    if fresh:
        L.append(f"WHAT TO FILM  ({PHONE_SETTINGS})")
        for i, s in enumerate(fresh, 1):
            L.append(f"  [ ] {i}. {shot_text({**s, 'n': i})}")
        if r.get("photos"):
            L.append(f"  Also snap if it's easy: {'; '.join(r['photos'])}")
        L.append("")
    if reading:
        who = str(r.get("voiceover_by") or "Katie")
        reader = "" if who.lower() == "katie" else f" ({who} reads this)"
        L.append(f"READ THIS OUT LOUD{reader}  ({RECORDING_TIPS})")
        n_lines = len(r["lines"])
        for i, line in enumerate(r["lines"]):
            opening = '"' if i == 0 else " "
            closing = '"' if i == n_lines - 1 else ""
            L.append(f"  {opening}{line}{closing}")
        L.append("")
    if kind in REEL_KINDS:
        reused = len([s for s in r.get("shots") or [] if s.get("source") == "library"])
        parts = f"these {len(fresh)} shots" if fresh else "library and brand photos"
        if fresh and reused:
            parts += " + reused library shots"
        L.append(f"{music_text(r.get('music'))}    LENGTH: {r['length_s']:g} seconds ({parts}).")
    else:
        L.append(f"POST: {r.get('post') or kind.title()}. Nothing to record.")
    L.append(LAST_LINE)
    return "\n".join(L) + "\n"


def cmd_card(args) -> int:
    p = Path(args.row).expanduser().resolve()
    row = nc.read_json(p, "plan row")
    if not isinstance(row, dict):
        raise nc.UserError(f"plan row {p}: expected an object")
    text = render_card(row)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        nc.info(f"shoot card -> {out}")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# Sheet export
# ---------------------------------------------------------------------------
def shot_list_text(r: dict) -> str:
    fresh = new_shots(r) if r["kind"] in REEL_KINDS else []
    if not fresh:
        return "No filming needed"
    out = []
    for i, s in enumerate(fresh, 1):
        room = s.get("room") or r.get("batch_room")
        framing = {"wide": "Wide", "medium": "Medium", "close": "Close-up", "overhead": "Overhead"}.get(s.get("framing"), "")
        what = f"Photo, {framing.lower()}: {s.get('what')}" if s.get("kind") == "photo" else \
            f"{framing}: {s.get('what')}, {s.get('seconds', 5):g} s"
        if s.get("time_of_day"):
            what += f", {s['time_of_day']}"
        extra = [f"during {s['during']}"] if s.get("during") else []
        if s.get("people"):
            extra.append("consent list only")
        extra.append(f"line {s.get('line')}")
        if s.get("ai_motion"):
            extra.append("AI motion shot")
        out.append(f"{i}. " + (f"[{room}] " if room else "") + what + f" ({'; '.join(extra)})")
    return "\n".join(out)


def sheet_rows(plan: dict) -> list[dict]:
    out = []
    for r in plan["rows"]:
        music = r.get("music") or {}
        bpm = music.get("bpm") or []
        mtext = ", ".join(x for x in [music.get("mood") or "", f"{bpm[0]}-{bpm[1]} BPM" if len(bpm) == 2 else ""] if x)
        status = r.get("status") or "Planned"
        if status not in STATUSES:
            raise nc.UserError(f"{label(r)}: status must be one of {', '.join(STATUSES)}, got {status!r}")
        title = r.get("title") or (r.get("post") or r["kind"].replace("_", " ").title())
        script = "\n".join(r.get("lines") or []) if r["kind"] in REEL_KINDS else ""
        out.append({
            "Day": r["day"], "Date": r["_d"].isoformat(), "Title": title, "Goal": r.get("goal") or "",
            "Template": r.get("template") or "", "Hook (first 2 seconds)": r.get("hook_text") or "",
            "Voiceover script": script, "Shot list": shot_list_text(r), "Music mood + BPM": mtext,
            "Call to action": r.get("cta") or "", "Status": status,
            "Folder link": r.get("folder_link") or "", "Reel link": r.get("reel_link") or "",
        })
    return out


def cmd_sheet(args) -> int:
    plan = load_plan(args.plan)
    rows = sheet_rows(plan)
    if args.csv:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=SHEET_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        text = buf.getvalue()
    else:
        text = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        nc.info(f"{len(rows)} Sheet rows -> {out}")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="shoot_card.py", description="Month skeleton, shoot cards, plan checks and Sheet rows.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    m = sub.add_parser("month", help="the month skeleton: days, folders, default-week slots")
    m.add_argument("month", metavar="YYYY-MM")
    m.add_argument("--json", action="store_true")
    c = sub.add_parser("card", help="the shoot card text for one plan row / script.json")
    c.add_argument("row", metavar="ROW_JSON")
    c.add_argument("--out", metavar="FILE")
    k = sub.add_parser("check", help="planning rules on a month plan; exit 1 on violations")
    k.add_argument("plan", metavar="MONTH_JSON")
    k.add_argument("--closures", metavar="FILE", help="closure dates (JSON or CSV with a Date column)")
    k.add_argument("--json", action="store_true")
    s = sub.add_parser("script", help="card rules and timing for one script.json; exit 1 on errors")
    s.add_argument("script", metavar="SCRIPT_JSON")
    s.add_argument("--json", action="store_true")
    h = sub.add_parser("sheet", help="the plan as Sheet rows (spec p.33 columns)")
    h.add_argument("plan", metavar="MONTH_JSON")
    h.add_argument("--csv", action="store_true", help="CSV instead of JSON")
    h.add_argument("--out", metavar="FILE")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: month, card, check, script or sheet")
    return {"month": cmd_month, "card": cmd_card, "check": cmd_check, "script": cmd_script,
            "sheet": cmd_sheet}[args.cmd](args)


if __name__ == "__main__":
    nc.run_cli(main)
