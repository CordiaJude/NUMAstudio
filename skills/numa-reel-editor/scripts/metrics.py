#!/usr/bin/env python3
"""Instagram metrics store for the performance loop (spec p.47, DECISIONS D7: metrics.json).

Usage:
    metrics.py ingest   --store FILE --reel ID --pull 48h|72h|7d --data INSIGHTS_JSON [--tags TAGS_JSON]
                        [--pulled-at ISO]
    metrics.py account  --store FILE --data USER_INSIGHTS_JSON [--date YYYY-MM-DD]
    metrics.py tag      --store FILE --reel ID --tags TAGS_JSON
    metrics.py due      --store FILE [--now ISO] [--json]
    metrics.py compute  --store FILE [--json]
    metrics.py validate --store FILE

`--post ID` is the same as `--reel ID` (every post type is stored the same way).

`--data` is the raw response of Composio's INSTAGRAM_GET_IG_MEDIA_INSIGHTS /
INSTAGRAM_GET_USER_INSIGHTS (the Composio envelope {"data": ..., "successful":
...} is unwrapped) in the Graph API insights shape: `data[].name` with
`values[].value` (and `end_time` for daily account values) or `total_value.value`.
A flat object {"views": 120, "reach": 95, ...} is accepted too. `--tags` is a
JSON file (or inline JSON object) of Numa's tags.

Rules:
* Per-reel metrics are config `instagram.metrics` (views, reach, likes, comments,
  saves, shares, reposts, total_interactions, avg_watch_time_ms, skip_rate);
  Graph names are mapped (saved -> saves, ig_reels_avg_watch_time ->
  avg_watch_time_ms, reels_skip_rate -> skip_rate). Retired metrics (config
  `instagram.never_request`: plays, impressions, and the old play counters) are
  rejected with exit 1: never request them.
* Tags (config `instagram.tags`): length (s), series, pillar, hook_type,
  transitions (list), music_source, posting_time (ISO 8601; naive times are
  Central), trial_reel (bool), collab (bool); plus title, slug, media_id,
  permalink, thumbnail, and post_type (R337): reel, carousel, image, story or
  trial_reel (POST_TYPES). A post without post_type is a reel (a trial_reel
  when its trial_reel tag is true); trial_reel true with a post_type other than
  trial_reel or reel is an error, and post_type trial_reel sets trial_reel true.
* Posts of every type share the store (the `reels` key holds every post). Only
  video posts (reel, trial_reel, story) have watch time and skip rate: a
  carousel's or image's avg_watch_time_ms, total_watch_time_ms or skip_rate is
  dropped at ingest with a WARN and rejected by `validate`.
* Pulls are stored per reel at 48h / 72h / 7d (config `instagram.insight_pulls_hours`);
  re-ingesting a pull replaces it. Account-level insights are kept forever
  (Meta keeps them only 90 days).
* `compute` (config `instagram.computed`) writes per pull and per post (from the
  latest pull: 7d, else 72h, else 48h): retention = avg watch time (s) / length (s);
  sends_per_1k_reach = shares / reach * 1000; saves_per_1k_reach; and
  skip_rate_vs_median = skip rate - median skip rate of Numa's reels (reel and
  trial_reel posts only). Metrics a post type does not have (watch time,
  retention and skip rate of a carousel or image) are null, never an error;
  each post's `computed` carries its `post_type`.
* `due` lists the posts whose next pull is due at --now (posting_time + 48 h,
  72 h, 168 h and not yet pulled). Stories are left out: Instagram keeps a
  Story's insights only while it is live (24 h), so they are pulled the same day.

Store shape (metrics.json):
    {"schema_version": 1,
     "reels": {"<id>": {"tags": {...},
                        "pulls": {"48h": {"pulled_at": ISO|null, "metrics": {...}, "computed": {...}}},
                        "computed": {..., "post_type": "reel", "from_pull": "7d"}}},
     "account": {"daily": {"YYYY-MM-DD": {"reach": 812, ...}},   (dated by period start = end_time - 1 day)
                 "totals": {"YYYY-MM-DD": {"accounts_engaged": 120, ...}}}}
"""
from __future__ import annotations

import json
import math
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

STORE_SCHEMA_VERSION = 1
PULL_LABELS = {48: "48h", 72: "72h", 168: "7d"}
PULL_ORDER = ["48h", "72h", "7d"]
CENTRAL = "America/Chicago"

# Graph API metric names -> store names.
NAME_MAP = {
    "saved": "saves",
    "ig_reels_avg_watch_time": "avg_watch_time_ms",
    "avg_watch_time": "avg_watch_time_ms",
    "reels_skip_rate": "skip_rate",
    "ig_reels_skip_rate": "skip_rate",
    "ig_reels_video_view_total_time": "total_watch_time_ms",
}
EXTRA_REEL_METRICS = {"total_watch_time_ms", "follows", "profile_visits", "profile_activity"}
# Counters that went away together with plays/impressions.
RETIRED_EXTRA = {"ig_reels_aggregated_all_plays_count", "clips_replays_count", "video_views"}
TAG_TEXT = ("series", "pillar", "hook_type", "music_source", "title", "slug", "media_id", "permalink", "thumbnail")
TAG_BOOL = ("trial_reel", "collab")
# Post types (R337). Video posts have watch time and skip rate; carousels and single images do not.
POST_TYPES = ("reel", "carousel", "image", "story", "trial_reel")
VIDEO_TYPES = ("reel", "trial_reel", "story")
REEL_TYPES = ("reel", "trial_reel")           # the skip-rate median is over these
VIDEO_ONLY_METRICS = ("avg_watch_time_ms", "total_watch_time_ms", "skip_rate")


def cfg_metrics() -> list[str]:
    return list(nc.config_value("instagram.metrics", []) or [])


def never_request() -> set[str]:
    return set(nc.config_value("instagram.never_request", ["plays", "impressions"]) or []) | RETIRED_EXTRA


def pull_labels() -> list[str]:
    hours = nc.config_value("instagram.insight_pulls_hours", [48, 72, 168]) or [48, 72, 168]
    return [PULL_LABELS.get(int(h), f"{int(h)}h") for h in hours]


def pull_hours() -> dict[str, int]:
    hours = nc.config_value("instagram.insight_pulls_hours", [48, 72, 168]) or [48, 72, 168]
    return {PULL_LABELS.get(int(h), f"{int(h)}h"): int(h) for h in hours}


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def central_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(CENTRAL)
    except Exception:  # noqa: BLE001 - no tz database: fall back to the US Central rules below
        return None


def _us_central_offset(utc: datetime) -> timedelta:
    """US Central offset for a UTC instant (DST: 2nd Sunday of March 08:00 UTC to 1st Sunday of Nov 07:00 UTC)."""
    y = utc.year
    march = datetime(y, 3, 8, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7, hours=8)
    nov = datetime(y, 11, 1, tzinfo=timezone.utc)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7, hours=7)
    return timedelta(hours=-5) if start <= utc < end else timedelta(hours=-6)


def to_central(dt: datetime) -> datetime:
    """The same instant as a naive Central wall-clock time."""
    tz = central_tz()
    if tz is not None:
        return dt.astimezone(tz).replace(tzinfo=None)
    utc = dt.astimezone(timezone.utc)
    return (utc + _us_central_offset(utc)).replace(tzinfo=None)


def parse_time(text: Any, what: str) -> datetime:
    """ISO 8601 date-time -> aware datetime; a naive time is Central wall-clock time."""
    if not isinstance(text, str) or not text.strip():
        raise nc.UserError(f"{what}: expected an ISO 8601 date-time, got {text!r}")
    s = text.strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)  # Graph's +0000
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise nc.UserError(f"{what}: not an ISO 8601 date-time: {text!r}") from None
    if dt.tzinfo is None:
        tz = central_tz()
        if tz is not None:
            dt = dt.replace(tzinfo=tz)
        else:
            guess = dt.replace(tzinfo=timezone.utc) + timedelta(hours=6)
            dt = dt.replace(tzinfo=timezone(_us_central_offset(guess)))
    return dt


# ---------------------------------------------------------------------------
# Parsing Composio / Graph responses
# ---------------------------------------------------------------------------
def load_json_arg(value: str, what: str) -> Any:
    """A path to a JSON file, or inline JSON (starts with { or [)."""
    v = value.strip()
    if v.startswith("{") or v.startswith("["):
        try:
            return json.loads(v)
        except json.JSONDecodeError as e:
            raise nc.UserError(f"{what}: invalid JSON: {e.msg}") from None
    return nc.read_json(Path(value).expanduser(), what)


def api_error(obj: Any) -> str | None:
    """The error text of a Composio envelope or a Graph error body ({"error": {"message": ...}}), if any."""
    if not isinstance(obj, dict):
        return None
    for node in (obj, obj.get("data"), (obj.get("data") or {}).get("data") if isinstance(obj.get("data"), dict) else None):
        if isinstance(node, dict) and node.get("error"):
            err = node["error"]
            if isinstance(err, dict):
                msg = err.get("message") or err.get("error_user_msg") or json.dumps(err, sort_keys=True)
                code = err.get("code")
                return f"{msg} (code {code})" if code is not None else str(msg)
            return str(err)
    return None


def check_composio(obj: Any, where: str) -> None:
    """A failed Composio call (successful: false) or a Graph error body: report the API's error text."""
    err = api_error(obj)
    failed = isinstance(obj, dict) and obj.get("successful") is False
    if failed or (err and insight_items(obj) is None):
        raise nc.UserError(f"{where}: the Instagram insights call failed: {err or 'no error message'}")


def insight_items(obj: Any) -> list[dict] | None:
    """The Graph `data` list of {name, values|total_value} inside a Composio response, else None."""
    if isinstance(obj, list) and obj and all(isinstance(x, dict) and "name" in x for x in obj):
        return obj
    if isinstance(obj, dict):
        for key in ("data", "response_data", "result", "insights"):
            if key in obj:
                found = insight_items(obj[key])
                if found is not None:
                    return found
    return None


def _number(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise nc.UserError(f"{what}: expected a number, got {v!r}")
    if v < 0:
        raise nc.UserError(f"{what}: negative value {v!r}")
    return int(v) if float(v).is_integer() else float(v)


def store_name(name: str) -> str:
    return NAME_MAP.get(name, name)


def reject_retired(names: list[str], where: str) -> None:
    bad = sorted({n for n in names if n in never_request()})
    if bad:
        raise nc.UserError(f"{where}: retired metric(s) {', '.join(bad)}: never request plays or impressions "
                           f"(use views); remove them from the Composio call")


def parse_media_insights(obj: Any, where: str) -> tuple[dict, list[str]]:
    """Per-reel metrics {store name: number} and a list of ignored names."""
    check_composio(obj, where)
    items = insight_items(obj)
    raw: dict[str, Any] = {}
    if items is None:
        if isinstance(obj, dict) and isinstance(obj.get("data"), dict):
            obj = obj["data"]
        if not isinstance(obj, dict) or not obj:
            raise nc.UserError(f"{where}: no insights found (expected Graph 'data[].name/values' or a flat object)")
        raw = {k: v for k, v in obj.items() if not k.startswith("_")}
    else:
        for i, it in enumerate(items):
            name = str(it.get("name"))
            if isinstance(it.get("total_value"), dict) and "value" in it["total_value"]:
                raw[name] = it["total_value"]["value"]
            elif isinstance(it.get("values"), list) and it["values"]:
                raw[name] = it["values"][-1].get("value") if isinstance(it["values"][-1], dict) else None
            elif "value" in it:
                raw[name] = it["value"]
            else:
                raise nc.UserError(f"{where}: data[{i}] ({name}) has no values[].value or total_value.value")
    reject_retired(list(raw), where)
    allowed = set(cfg_metrics()) | EXTRA_REEL_METRICS
    out: dict[str, Any] = {}
    ignored: list[str] = []
    for name, value in raw.items():
        key = store_name(name)
        if key not in allowed:
            ignored.append(name)
            continue
        if isinstance(value, dict):  # breakdown values: sum the parts
            value = sum(_number(v, f"{where}: {name}.{k}") for k, v in value.items())
        out[key] = _number(value, f"{where}: {name}")
    if not out:
        raise nc.UserError(f"{where}: none of the expected metrics ({', '.join(cfg_metrics())}) found")
    return out, ignored


def parse_user_insights(obj: Any, where: str, day: str | None) -> tuple[dict, dict]:
    """Account insights -> ({date: {metric: value}} daily series, {date: {metric: value}} totals)."""
    check_composio(obj, where)
    items = insight_items(obj)
    if items is None:
        raise nc.UserError(f"{where}: no insights found (expected Graph 'data[].name' with values or total_value)")
    reject_retired([str(it.get("name")) for it in items], where)
    daily: dict[str, dict] = {}
    totals: dict[str, dict] = {}
    for i, it in enumerate(items):
        name = store_name(str(it.get("name")))
        if isinstance(it.get("total_value"), dict) and "value" in it["total_value"]:
            if day is None:
                raise nc.UsageError(f"{where}: {name} is a total_value; pass --date YYYY-MM-DD for the day it was pulled")
            totals.setdefault(day, {})[name] = _number(it["total_value"]["value"], f"{where}: {name}")
            continue
        values = it.get("values")
        if not isinstance(values, list):
            raise nc.UserError(f"{where}: data[{i}] ({name}) has no values or total_value")
        for j, v in enumerate(values):
            if not isinstance(v, dict) or "value" not in v:
                raise nc.UserError(f"{where}: data[{i}].values[{j}] has no value")
            if isinstance(v["value"], dict):
                continue  # demographic breakdowns are not kept
            when = v.get("end_time")
            # a daily value's end_time is the end of its day: the period started one day earlier
            d = (parse_time(when, f"{where}: {name} end_time") - timedelta(days=1)).date().isoformat() if when else day
            if d is None:
                raise nc.UsageError(f"{where}: {name} values have no end_time; pass --date YYYY-MM-DD")
            daily.setdefault(d, {})[name] = _number(v["value"], f"{where}: {name}")
    return daily, totals


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def clean_tags(tags: Any, where: str = "tags") -> dict:
    if not isinstance(tags, dict):
        raise nc.UserError(f"{where}: expected a JSON object")
    allowed = (set(nc.config_value("instagram.tags", []) or []) | set(TAG_TEXT) | set(TAG_BOOL)
               | {"length", "transitions", "posting_time", "post_type"})
    out: dict[str, Any] = {}
    for k, v in tags.items():
        if k.startswith("_"):
            continue
        if k not in allowed:
            raise nc.UserError(f"{where}: unknown tag '{k}' (known: {', '.join(sorted(allowed))})")
        if v is None:
            out[k] = None
        elif k == "length":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise nc.UserError(f"{where}: length must be seconds > 0, got {v!r}")
            out[k] = v
        elif k in TAG_BOOL:
            if not isinstance(v, bool):
                raise nc.UserError(f"{where}: {k} must be true or false, got {v!r}")
            out[k] = v
        elif k == "transitions":
            items = [v] if isinstance(v, str) else v
            if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
                raise nc.UserError(f"{where}: transitions must be a list of names, got {v!r}")
            out[k] = [x.strip() for x in items]
        elif k == "posting_time":
            parse_time(v, f"{where}: posting_time")
            out[k] = v.strip()
        elif k == "post_type":
            if not isinstance(v, str) or v.strip().lower() not in POST_TYPES:
                raise nc.UserError(f"{where}: post_type must be one of {', '.join(POST_TYPES)}, got {v!r}")
            out[k] = v.strip().lower()
        else:
            if not isinstance(v, str):
                raise nc.UserError(f"{where}: {k} must be text, got {v!r}")
            out[k] = v.strip()
    check_post_type(out, where)
    return out


def check_post_type(tags: dict, where: str = "tags") -> None:
    """trial_reel true only goes with a reel or trial_reel post."""
    pt = tags.get("post_type")
    if tags.get("trial_reel") is True and pt not in (None, "reel", "trial_reel"):
        raise nc.UserError(f"{where}: trial_reel is true but post_type is {pt}; a Trial Reel is post_type trial_reel")


def merge_tags(current: dict, new: dict, where: str = "tags") -> dict:
    """Tags after an update (post_type trial_reel also sets trial_reel true), checked together."""
    merged = dict(current or {})
    merged.update(new)
    if merged.get("post_type") == "trial_reel":
        merged["trial_reel"] = True
    check_post_type(merged, where)
    return merged


def post_type_of(post: dict) -> str:
    """The post's type: its post_type tag, else trial_reel when tagged so, else reel (the v2.0 stores)."""
    tags = post.get("tags") or {}
    pt = tags.get("post_type")
    if isinstance(pt, str) and pt in POST_TYPES:
        return pt
    return "trial_reel" if tags.get("trial_reel") is True else "reel"


def article(word: str) -> str:
    """'a carousel', 'an image'."""
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def drop_video_only(metrics: dict, post_type: str, where: str) -> dict:
    """A carousel's or image's metrics without watch time or skip rate (WARN for each dropped)."""
    if post_type in VIDEO_TYPES:
        return metrics
    out = {}
    for k, v in metrics.items():
        if k in VIDEO_ONLY_METRICS:
            nc.warn(f"{where}: {k} does not apply to {article(post_type)} post; ignored")
            continue
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def empty_store() -> dict:
    return {"schema_version": STORE_SCHEMA_VERSION, "reels": {}, "account": {"daily": {}, "totals": {}}}


def load_store(path: Path, create: bool = False) -> dict:
    if not path.exists() and create:
        return empty_store()
    data = nc.read_json(path, "metrics store")
    problems = store_problems(data)
    if problems:
        raise nc.UserError(f"metrics store {path}: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
    return data


def store_problems(data: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(data, dict):
        return ["not a JSON object"]
    if data.get("schema_version") != STORE_SCHEMA_VERSION:
        out.append(f"schema_version must be {STORE_SCHEMA_VERSION}")
    reels = data.get("reels")
    if not isinstance(reels, dict):
        return out + ["'reels' must be an object"]
    labels = set(pull_labels())
    banned = never_request()
    for rid, reel in reels.items():
        if not isinstance(reel, dict):
            out.append(f"reels.{rid}: not an object")
            continue
        try:
            clean_tags(reel.get("tags", {}), f"reels.{rid}.tags")
        except nc.UserError as e:
            out.append(str(e))
        ptype = post_type_of(reel)
        pulls = reel.get("pulls", {})
        if not isinstance(pulls, dict):
            out.append(f"reels.{rid}.pulls: not an object")
            continue
        for label, pull in pulls.items():
            if label not in labels:
                out.append(f"reels.{rid}.pulls.{label}: unknown pull (use {', '.join(sorted(labels))})")
            m = pull.get("metrics") if isinstance(pull, dict) else None
            if not isinstance(m, dict):
                out.append(f"reels.{rid}.pulls.{label}.metrics: missing")
                continue
            for k, v in m.items():
                if k in banned:
                    out.append(f"reels.{rid}.pulls.{label}.metrics.{k}: retired metric")
                elif k in VIDEO_ONLY_METRICS and ptype not in VIDEO_TYPES:
                    out.append(f"reels.{rid}.pulls.{label}.metrics.{k}: {article(ptype)} post has no {k}")
                elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    out.append(f"reels.{rid}.pulls.{label}.metrics.{k}: not a number >= 0")
    acct = data.get("account", {})
    if not isinstance(acct, dict):
        out.append("'account' must be an object")
    else:
        for part in ("daily", "totals"):
            series = acct.get(part, {})
            if not isinstance(series, dict):
                out.append(f"account.{part}: not an object")
                continue
            for d, vals in series.items():
                try:
                    date.fromisoformat(d)
                except ValueError:
                    out.append(f"account.{part}.{d}: not a YYYY-MM-DD date")
                if not isinstance(vals, dict):
                    out.append(f"account.{part}.{d}: not an object")
                    continue
                for k in vals:
                    if k in banned:
                        out.append(f"account.{part}.{d}.{k}: retired metric")
    return out


# ---------------------------------------------------------------------------
# Computed metrics
# ---------------------------------------------------------------------------
def _ratio(a: Any, b: Any, scale: float = 1.0) -> float | None:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > 0:
        return round(a / b * scale, 4)
    return None


def pull_computed(metrics: dict, length: Any, post_type: str = "reel") -> dict:
    """Computed metrics of one pull; watch time and retention are null for a carousel or image."""
    awt = metrics.get("avg_watch_time_ms") if post_type in VIDEO_TYPES else None
    if not isinstance(awt, (int, float)) or isinstance(awt, bool):
        awt = None
    return {
        "avg_watch_time_s": round(awt / 1000.0, 3) if isinstance(awt, (int, float)) else None,
        "retention": _ratio(awt / 1000.0 if isinstance(awt, (int, float)) else None, length),
        "sends_per_1k_reach": _ratio(metrics.get("shares"), metrics.get("reach"), 1000.0),
        "saves_per_1k_reach": _ratio(metrics.get("saves"), metrics.get("reach"), 1000.0),
    }


def latest_pull(reel: dict) -> str | None:
    pulls = reel.get("pulls", {}) or {}
    for label in reversed(PULL_ORDER):
        if label in pulls:
            return label
    return next(iter(pulls), None)


def compute(store: dict) -> dict:
    """Fill per-pull and per-reel computed metrics in place; returns {reel id: computed}."""
    skips = []
    for reel in store["reels"].values():
        label = latest_pull(reel)
        if label and post_type_of(reel) in REEL_TYPES:
            s = reel["pulls"][label]["metrics"].get("skip_rate")
            if isinstance(s, (int, float)):
                skips.append(float(s))
    median_skip = statistics.median(skips) if skips else None
    out = {}
    for rid in sorted(store["reels"]):
        reel = store["reels"][rid]
        length = (reel.get("tags") or {}).get("length")
        ptype = post_type_of(reel)
        for pull in (reel.get("pulls") or {}).values():
            pull["computed"] = pull_computed(pull["metrics"], length, ptype)
        label = latest_pull(reel)
        if not label:
            reel.pop("computed", None)
            continue
        m = reel["pulls"][label]["metrics"]
        c = dict(reel["pulls"][label]["computed"])
        s = m.get("skip_rate") if ptype in REEL_TYPES else None
        c["post_type"] = ptype
        c["skip_rate_median"] = round(median_skip, 4) if median_skip is not None else None
        c["skip_rate_vs_median"] = round(s - median_skip, 4) if isinstance(s, (int, float)) and median_skip is not None else None
        c["from_pull"] = label
        reel["computed"] = c
        out[rid] = c
    return out


def due(store: dict, now: datetime) -> list[dict]:
    hours = pull_hours()
    out = []
    for rid in sorted(store["reels"]):
        reel = store["reels"][rid]
        pt = (reel.get("tags") or {}).get("posting_time")
        if not pt or post_type_of(reel) == "story":
            continue
        posted = parse_time(pt, f"reels.{rid}.tags.posting_time")
        age_h = (now - posted).total_seconds() / 3600.0
        done = set((reel.get("pulls") or {}).keys())
        last_done = max([hours.get(label, 0) for label in done] or [0])
        ready = [label for label, h in hours.items() if age_h >= h and label not in done and h > last_done]
        if ready:
            out.append({"reel": rid, "post_type": post_type_of(reel), "pulls": ready, "pull_now": ready[-1], "hours_since_post": round(age_h, 1),
                        "posting_time": pt, "media_id": (reel.get("tags") or {}).get("media_id")})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="metrics.py", description="Instagram metrics store (metrics.json, spec p.47).")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    i = sub.add_parser("ingest", help="store one reel's insights pull")
    i.add_argument("--store", required=True)
    i.add_argument("--reel", "--post", dest="reel", required=True, help="post id (media id or slug), any post type")
    i.add_argument("--pull", required=True, choices=PULL_ORDER)
    i.add_argument("--data", required=True, help="INSTAGRAM_GET_IG_MEDIA_INSIGHTS response (file or inline JSON)")
    i.add_argument("--tags", help="Numa tags (file or inline JSON object)")
    i.add_argument("--pulled-at", help="ISO time of the pull (stored as given)")
    a = sub.add_parser("account", help="store account insights (kept beyond Meta's 90 days)")
    a.add_argument("--store", required=True)
    a.add_argument("--data", required=True, help="INSTAGRAM_GET_USER_INSIGHTS response (file or inline JSON)")
    a.add_argument("--date", help="YYYY-MM-DD for total_value metrics")
    t = sub.add_parser("tag", help="set or update a post's Numa tags")
    t.add_argument("--store", required=True)
    t.add_argument("--reel", "--post", dest="reel", required=True, help="post id (media id or slug)")
    t.add_argument("--tags", required=True)
    d = sub.add_parser("due", help="reels whose 48h/72h/7d pull is due now")
    d.add_argument("--store", required=True)
    d.add_argument("--now", help="ISO date-time (default: the current time)")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("compute", help="add retention, sends/saves per 1,000 reach, skip rate vs median")
    c.add_argument("--store", required=True)
    c.add_argument("--json", action="store_true")
    v = sub.add_parser("validate", help="check the store")
    v.add_argument("--store", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: ingest, account, tag, due, compute or validate")
    path = Path(args.store).expanduser().resolve()

    if args.cmd == "validate":
        data = nc.read_json(path, "metrics store")
        problems = store_problems(data)
        for p in problems:
            nc.error_line(p)
        if problems:
            return 1
        print(f"OK: {len(data['reels'])} reels, {len(data.get('account', {}).get('daily', {}))} account days")
        return 0

    if args.cmd == "due":
        store = load_store(path, create=True)
        now = parse_time(args.now, "--now") if args.now else datetime.now(timezone.utc)
        items = due(store, now)
        if args.json:
            nc.print_json(items)
        elif not items:
            print("No pulls due.")
        else:
            for it in items:
                print(f"{it['reel']}: pull {', '.join(it['pulls'])} ({it['hours_since_post']:g} h since posting)")
        return 0

    store = load_store(path, create=args.cmd in ("ingest", "account", "tag"))
    if args.cmd == "ingest":
        metrics, ignored = parse_media_insights(load_json_arg(args.data, "--data"), "--data")
        reel = store["reels"].setdefault(args.reel, {"tags": {}, "pulls": {}})
        if args.tags:
            reel["tags"] = merge_tags(reel["tags"], clean_tags(load_json_arg(args.tags, "--tags"), "--tags"), "--tags")
        metrics = drop_video_only(metrics, post_type_of(reel), "--data")
        if args.pulled_at:
            parse_time(args.pulled_at, "--pulled-at")
        reel["pulls"][args.pull] = {"pulled_at": args.pulled_at, "metrics": metrics}
        reel["pulls"] = {k: reel["pulls"][k] for k in PULL_ORDER if k in reel["pulls"]}
        for name in ignored:
            nc.warn(f"--data: metric '{name}' is not tracked; ignored")
        compute(store)
        nc.write_json(path, store)
        print(f"Stored {args.pull} pull for {args.reel}: " + ", ".join(f"{k}={v:g}" for k, v in metrics.items()))
        return 0
    if args.cmd == "account":
        if args.date:
            try:
                date.fromisoformat(args.date)
            except ValueError:
                raise nc.UsageError(f"--date must be YYYY-MM-DD, got {args.date!r}") from None
        daily, totals = parse_user_insights(load_json_arg(args.data, "--data"), "--data", args.date)
        acct = store.setdefault("account", {"daily": {}, "totals": {}})
        for part, series in (("daily", daily), ("totals", totals)):
            dest = acct.setdefault(part, {})
            for d, vals in series.items():
                dest.setdefault(d, {}).update(vals)
            acct[part] = {k: dest[k] for k in sorted(dest)}
        nc.write_json(path, store)
        print(f"Stored account insights: {len(daily)} daily dates, {len(totals)} total dates "
              f"({len(acct['daily'])} days kept)")
        return 0
    if args.cmd == "tag":
        reel = store["reels"].setdefault(args.reel, {"tags": {}, "pulls": {}})
        reel["tags"] = merge_tags(reel["tags"], clean_tags(load_json_arg(args.tags, "--tags"), "--tags"), "--tags")
        ptype = post_type_of(reel)
        for label, pull in reel.get("pulls", {}).items():
            pull["metrics"] = drop_video_only(pull["metrics"], ptype, f"pull {label}")
        compute(store)
        nc.write_json(path, store)
        print(f"Tagged {args.reel}: " + ", ".join(f"{k}={v}" for k, v in reel["tags"].items()))
        return 0
    if args.cmd == "compute":
        result = compute(store)
        nc.write_json(path, store)
        if args.json:
            nc.print_json(result)
        else:
            for rid, c in result.items():
                parts = [f"{k}={c[k]:g}" for k in ("retention", "sends_per_1k_reach", "saves_per_1k_reach",
                                                    "skip_rate_vs_median") if isinstance(c.get(k), (int, float))]
                print(f"{rid} ({c['post_type']}, {c['from_pull']}): " + (", ".join(parts) or "no computable metrics"))
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
