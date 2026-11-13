#!/usr/bin/env python3
"""Adaptive strategy engine: learns from NUMA's own engagement what to post, when and how (DECISIONS D23).

Usage:
    strategy.py plan    --month YYYY-MM [--metrics FILE] [--state FILE] [--playbook DIR] [--events FILE]
                        [--closures FILE] [--seed N] [--today YYYY-MM-DD] [--out FILE] [--json]
    strategy.py learn   --metrics FILE --state FILE [--playbook DIR] [--today YYYY-MM-DD] [--text FILE] [--json]
    strategy.py brief   --plan PLAN_JSON --metrics FILE [--state FILE] [--playbook DIR] [--week YYYY-MM-DD]
                        [--today YYYY-MM-DD] [--out FILE] [--md FILE] [--notes TXT] [--json]
    strategy.py explain SLOT --plan PLAN_JSON [--json]
    strategy.py diagnose --metrics FILE [--post ID] [--state FILE] [--playbook DIR] [--today YYYY-MM-DD] [--json]
    strategy.py score   --metrics FILE [--state FILE] [--playbook DIR] [--today YYYY-MM-DD] [--json]
    strategy.py import-research FILE... --state FILE [--playbook DIR] [--kind KIND] [--today YYYY-MM-DD] [--json]
    strategy.py validate [--playbook DIR] [--state FILE] [--json]
    strategy.py export  [--playbook DIR] [--state FILE] --out FILE

FILE paths: --metrics is metrics.py's store (metrics.json); --state is the learned
overlay (STATE/strategy.json, created on first learn/import); --playbook defaults
to skills/numa-scriptwriter/playbook (patterns, diagnosis, calendar, policies;
schemas/playbook.schema.json). The bundled playbook is never written: statuses
NUMA's data sets, imported research and the changelog live in the state file.

How it learns
* Judging windows (policies.judging, per post type, R7): a post is ignored before
  ignore_before_hours and before its first pull at or after provisional_hours; a
  pull at/after provisional_hours counts at provisional_weight (PROVISIONAL); a
  pull at/after final_hours (or the store's last pull, 7d, when final_hours is
  later) counts in full and replaces the provisional entry (FINAL). A post is
  never counted twice. Metric exceptions (e.g. saves final at 7 d) leave that
  metric out of a provisional score. Any Story pull is final (24 h insights).
* Score per post: each metric is compared with NUMA's own rolling median (90 days,
  same post type; pooled when fewer than 3) as z = ln(x / median) winsorised at
  +/- ln 4 (skip rate: (median - skip) / 0.10). Goal weights (policies.scoring):
  reach = views, sends/1k, skip, retention; saves = saves/1k, sends/1k, views;
  conversion = profile visits, follows, link clicks per 1k reach (reach weights
  when none are tracked). Missing metrics drop out; weights re-normalise. A second,
  pooled score (views, sends, saves vs the median of all feed posts) compares
  post types with each other.
* Model: two additive Bayesian models fitted by backfitting with Normal priors
  (Normal-Normal per level, known noise): A on the pooled score with dimensions
  post_type and post_type x weekday; B on the per-type score with weekday,
  hour_band, pillar, series, hook, structure and offer_week. Each observation
  weighs judging weight x 0.5^(age days / 90). A research prior counts as
  prior_strength posts (measured 3, observed 2, opinion 1), so NUMA's own data
  outweighs research after a few posts.
* Cold start and data-led share: lambda = min(1, judged posts / 30) (spec p.34
  rule 10: re-tune after 30 reels). The month starts from the default week
  (shoot_card.py month, spec p.34); a slot's type, weekday and hour move only when
  lambda x (Thompson draw difference) beats a stickiness margin (0.1). Hook and
  structure patterns are Thompson-sampled from the start (Trial Reels test hooks).
* Allocation: one Thompson draw per week (numpy default_rng(seed); default seed
  YYYYMM, so the same inputs give the same plan). An explicit exploration budget
  (policies.learning.exploration_budget, 25% of pattern slots, Trial Reels first)
  draws from testing/candidate patterns with inflated variance; the other slots
  exploit proven/testing ones. Retired patterns are never planned. No pattern
  takes more than max_pattern_share_week of a week's slots.
* Rules win: every candidate month is checked with shoot_card.py's planning rules
  (topic repeat, one sales post a week, closures, collab, Meet the Collective,
  signature reel, series, events teaser/recap, cadence, mix). On a violation the
  bandit's influence is halved (lambda/2, /4, 0) until the plan passes; the
  explanation says so. An `image` row is checked as a feed post like a carousel.

Outputs
* plan: MONTH_JSON (shoot_card.py shape) whose rows also carry post_type,
  post_time (Central HH:MM), hour_band, pattern_ids, strategy_arm and strategy
  (mode, why). pattern_ids and strategy_arm flow into metrics.py tags
  (docs/CONTRACTS.md section 9, strategy.py).
* learn: updates STATE status overrides (promote / retire / demote / start
  testing), a dated changelog in plain sentences, and the "Do more of / Do less
  of" lines for the digest and dashboard.
* brief: the Strategist's machine-readable week brief (schemas/strategy_brief.schema.json).

Exit codes: 0 ok; 1 input error (ERROR line) or a plan that breaks a planning
rule even with the bandit switched off; 2 usage.
"""
from __future__ import annotations

import calendar
import copy
import math
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims_scan  # noqa: E402
import metrics as mstore  # noqa: E402
import numa_common as nc  # noqa: E402
import shoot_card as sc  # noqa: E402

PLAYBOOK_DIR = nc.PLUGIN_ROOT / "skills" / "numa-scriptwriter" / "playbook"
PLAYBOOK_FILES = ("patterns", "diagnosis", "calendar", "policies")
SCHEMA = "playbook.schema.json"
BRIEF_SCHEMA = "strategy_brief.schema.json"
POST_TYPES = ("reel", "trial_reel", "carousel", "image", "story")
FEED_TYPES = ("reel", "carousel", "image")
VIDEO_TYPES = ("reel", "trial_reel", "story")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PULL_HOURS = {"22h": 22, "48h": 48, "72h": 72, "7d": 168, "14d": 336, "30d": 720}
EVIDENCE_ORDER = {"opinion": 0, "observed": 1, "measured": 2, "numa": 3}
STRUCTURE_KINDS = ("structure", "carousel", "photo")
KIND_FOR_ROW = {"reel": "reel", "trial_reel": "trial_reel", "carousel": "carousel", "image": "image", "stories": "story"}
ROW_KIND_FOR_TYPE = {"reel": "reel", "trial_reel": "trial_reel", "carousel": "carousel", "image": "image", "story": "stories"}
COMPONENT_METRICS = {
    "views": ("views", "reach"), "sends": ("shares", "sends_per_1k_reach"), "saves": ("saves", "saves_per_1k_reach"),
    "skip": ("skip_rate", "skip_rate_vs_median"), "retention": ("retention", "avg_watch_time_s"),
    "profile_visits": ("profile_visits",), "follows": ("follows",), "link_clicks": ("link_clicks",),
}
ROLE_ORDER = ["ask_the_dpt_reel", "carousel", "community_reel", "offer_event_collab_reel", "regulate_reel"]
ARM_KEYS = ("type", "pillar", "series", "day", "band", "hook", "structure", "offer_week", "goal", "mode", "plan")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def parse_day(text: str | None, what: str) -> date:
    if text is None:
        return date.today()
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise nc.UsageError(f"{what} must be YYYY-MM-DD, got {text!r}") from None


def norm_text(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def kebab(s: str, max_len: int = 60) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    t = re.sub(r"-{2,}", "-", t)[:max_len].strip("-")
    return t


def week_of_month(d: date) -> str:
    return f"w{(d.day - 1) // 7 + 1}"


def format_arm(arm: dict) -> str:
    """The strategy_arm tag: 'type=reel;pillar=education;...' with the keys in ARM_KEYS order."""
    return ";".join(f"{k}={'' if arm.get(k) is None else arm.get(k)}" for k in ARM_KEYS)


def parse_arm(text: Any) -> dict:
    out: dict[str, Any] = {}
    if not isinstance(text, str):
        return out
    for part in text.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip() or None
    return out


# ---------------------------------------------------------------------------
# playbook and state
# ---------------------------------------------------------------------------
def empty_state() -> dict:
    return {"schema_version": 1, "kind": "state", "patterns": [], "diagnosis": [], "status_overrides": {},
            "rules": [], "priors": [], "imports": [], "changelog": []}


def check_doc(doc: Any, where: str) -> None:
    errs = nc.schema_errors(SCHEMA, doc)
    if errs:
        raise nc.UserError(f"{where} does not match schemas/{SCHEMA}: {errs[0]}"
                           + (f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""))


def load_state(path: str | None) -> dict:
    if not path:
        return empty_state()
    p = Path(path).expanduser()
    if not p.exists():
        return empty_state()
    data = nc.read_json(p, "strategy state")
    check_doc(data, f"strategy state {p}")
    if data.get("kind") != "state":
        raise nc.UserError(f"strategy state {p}: kind must be 'state', got {data.get('kind')!r}")
    st = empty_state()
    st.update(data)
    return st


def load_playbook(directory: str | None = None, state: dict | None = None) -> dict:
    """The effective playbook: the bundled files with the state overlay applied."""
    d = Path(directory).expanduser() if directory else PLAYBOOK_DIR
    if not d.is_dir():
        raise nc.UserError(f"playbook folder not found: {d}")
    parts: dict[str, Any] = {}
    for name in PLAYBOOK_FILES:
        p = d / f"{name}.json"
        if not p.exists():
            raise nc.UserError(f"playbook file missing: {p}")
        doc = nc.read_json(p, f"playbook {name}")
        check_doc(doc, f"playbook {p.name}")
        if name not in doc:
            raise nc.UserError(f"playbook {p.name}: no '{name}' section")
        parts[name] = doc[name]
    st = state or empty_state()
    patterns: dict[str, dict] = {}
    for p in parts["patterns"]:
        if p["id"] in patterns:
            raise nc.UserError(f"playbook patterns: duplicate id {p['id']!r}")
        patterns[p["id"]] = copy.deepcopy(p)
    for p in st.get("patterns", []):
        patterns[p["id"]] = copy.deepcopy(p)
    for pid, ov in (st.get("status_overrides") or {}).items():
        if pid in patterns:
            patterns[pid]["status"] = ov["status"]
    diagnosis = {r["id"]: r for r in parts["diagnosis"]}
    for r in st.get("diagnosis", []):
        diagnosis[r["id"]] = r
    policies = copy.deepcopy(parts["policies"])
    for pt, win in (st.get("judging") or {}).items():
        policies["judging"][pt] = copy.deepcopy(win)
    return {"dir": str(d), "patterns": patterns, "diagnosis": list(diagnosis.values()),
            "calendar": parts["calendar"], "policies": policies, "state": st}


def merged_doc(pb: dict) -> dict:
    st = pb["state"]
    doc = {"schema_version": 1, "kind": "merged", "patterns": [pb["patterns"][k] for k in sorted(pb["patterns"])],
           "diagnosis": pb["diagnosis"], "calendar": pb["calendar"], "policies": pb["policies"],
           "rules": st.get("rules", []), "changelog": st.get("changelog", [])}
    if st.get("insights"):
        doc["insights"] = st["insights"]
    return doc


def pattern_text_hits(p: dict) -> list:
    hits = []
    for i, t in enumerate(p.get("examples", [])):
        hits += claims_scan.scan_text(t, where=f"pattern {p['id']} example {i + 1}")
    hits += claims_scan.scan_text(p.get("template", ""), where=f"pattern {p['id']} template")
    return hits


def playbook_problems(pb: dict) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    ids = set(pb["patterns"])
    for pid in sorted(ids):
        p = pb["patterns"][pid]
        for h in pattern_text_hits(p):
            (errs if h.severity == "fail" else warns).append(h.line())
        for t in p.get("try_instead", []):
            if t not in ids:
                errs.append(f"pattern {pid}: try_instead {t!r} is not a pattern id")
    for r in pb["diagnosis"]:
        for t in r.get("try_patterns", []):
            if t not in ids:
                errs.append(f"diagnosis {r['id']}: try_patterns {t!r} is not a pattern id")
    cal = pb["calendar"]
    for m in cal["monthly"] + cal["seasonal"] + cal["holidays"]:
        for t in m.get("hooks", []):
            if t not in ids:
                errs.append(f"calendar {m['id']}: hook {t!r} is not a pattern id")
        for i, t in enumerate(m.get("examples", [])):
            for h in claims_scan.scan_text(t, where=f"calendar {m['id']} example {i + 1}"):
                (errs if h.severity == "fail" else warns).append(h.line())
    for pt, win in pb["policies"]["judging"].items():
        if not win["ignore_before_hours"] <= win["provisional_hours"] <= win["final_hours"]:
            errs.append(f"policies.judging.{pt}: needs ignore_before_hours <= provisional_hours <= final_hours")
        if pt == "story" and win["final_hours"] >= 24:
            errs.append("policies.judging.story: Story windows must be under 24 h (insights last 24 h)")
    return errs, warns


# ---------------------------------------------------------------------------
# posts from the metrics store
# ---------------------------------------------------------------------------
def load_store(path: str | None) -> dict:
    """metrics.json, read tolerantly (pattern_ids / strategy_arm / boosted tags may be present)."""
    if not path:
        return {"reels": {}}
    p = Path(path).expanduser()
    if not p.exists():
        raise nc.UserError(f"metrics store not found: {p}")
    data = nc.read_json(p, "metrics store")
    if not isinstance(data, dict) or not isinstance(data.get("reels"), dict):
        raise nc.UserError(f"metrics store {p}: expected an object with 'reels'")
    return data


def hour_band_of(hour: int, bands: dict) -> str:
    for name, b in bands.items():
        if b["hours"][0] <= hour <= b["hours"][1]:
            return name
    return min(bands, key=lambda n: min(abs(hour - bands[n]["hours"][0]), abs(hour - bands[n]["hours"][1])))


def rates(m: dict, length: Any, ptype: str) -> dict:
    """Per-reach rates of one pull (R6: rates, not counts); missing ones absent."""
    v = {k: float(x) for k, x in m.items() if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)}
    out: dict[str, float] = {}
    reach = v.get("reach")
    if reach is not None:
        out["reach"] = reach
    if reach and reach > 0:
        for src, dst in (("shares", "sends"), ("saves", "saves"), ("follows", "follows"),
                         ("profile_visits", "profile_visits"), ("link_clicks", "link_clicks")):
            if src in v:
                out[dst] = v[src] / reach
        if "views" in v:
            out["views_per_reach"] = v["views"] / reach
    if v.get("link_clicks") is not None and v.get("profile_visits"):
        out["link_taps_per_visit"] = v["link_clicks"] / v["profile_visits"]
    if ptype in VIDEO_TYPES and "avg_watch_time_ms" in v and isinstance(length, (int, float)) and length > 0:
        out["watch_through"] = v["avg_watch_time_ms"] / 1000.0 / float(length)
    for k in ("views", "likes", "comments", "shares", "saves", "skip_rate", "avg_watch_time_ms", "profile_visits", "follows", "link_clicks"):
        if k in v:
            out[f"raw_{k}"] = v[k]
    if "skip_rate" in v and ptype in VIDEO_TYPES:
        out["raw_skip_rate"] = v["skip_rate"] / 100.0 if v["skip_rate"] > 1.0 else v["skip_rate"]
    return out


def configured_pull_hours() -> list[int]:
    hours = nc.config_value("instagram.insight_pulls_hours", [48, 72, 168]) or [48, 72, 168]
    return sorted(int(h) for h in hours)


def judge_state(post_type: str, pulls: dict, age_h: float | None, win: dict) -> tuple[str, str | None, float]:
    """(status, pull label, weight): pending | provisional | final (policies.judging, R7)."""
    labels = sorted((lb for lb in pulls if lb in PULL_HOURS), key=lambda x: PULL_HOURS[x])
    if not labels:
        return "pending", None, 0.0
    if age_h is not None and age_h < float(win["ignore_before_hours"]):
        return "pending", None, 0.0
    if post_type == "story":       # Story insights live 24 h: whatever was captured is final
        return "final", labels[-1], 1.0
    final_at = min(float(win["final_hours"]), float(max(configured_pull_hours())))
    finals = [lb for lb in labels if PULL_HOURS[lb] >= final_at]
    if finals:
        return "final", finals[0], 1.0
    provs = [lb for lb in labels if PULL_HOURS[lb] >= float(win["provisional_hours"])]
    if provs:
        return "provisional", provs[-1], float(win["provisional_weight"])
    return "pending", None, 0.0


def holiday_dates(pb: dict, year: int) -> set[date]:
    """Holiday weeks excluded from decisions (R6 section 8): policy windows plus the Mon-Sun week of each calendar holiday."""
    out: set[date] = set()
    for w in pb["policies"]["learning"]["holiday_windows"]:
        fm, fd = (int(x) for x in w["from"].split("-"))
        tm, td = (int(x) for x in w["to"].split("-"))
        start = date(year, fm, fd)
        end = date(year if (tm, td) >= (fm, fd) else year + 1, tm, td)
        out |= {start + timedelta(days=i) for i in range((end - start).days + 1)}
        prev_start = date(year - 1, fm, fd)
        prev_end = date(year - 1 if (tm, td) >= (fm, fd) else year, tm, td)
        out |= {prev_start + timedelta(days=i) for i in range((prev_end - prev_start).days + 1)}
    for m in pb["calendar"]["holidays"]:
        if not m.get("possible_closure"):
            continue
        for mon in range(1, 13):
            for d in moment_days(m, year, mon):
                wk = d - timedelta(days=d.weekday())
                out |= {wk + timedelta(days=i) for i in range(7)}
    return out


def collect_posts(store: dict, pb: dict, today: date) -> list[dict]:
    pol = pb["policies"]
    bands = pol["hour_bands"]["bands"]
    now = datetime.combine(today, datetime.max.time()).replace(microsecond=0)
    hooks_by_type: dict[str, str] = {}
    for p in pb["patterns"].values():
        if p["kind"] == "hook":
            for ht in p.get("hook_types", []):
                hooks_by_type.setdefault(ht, p["id"])
    holidays: dict[int, set[date]] = {}
    posts = []
    for pid in sorted(store["reels"]):
        raw = store["reels"][pid]
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags") or {}
        ptype = mstore.post_type_of(raw)
        collab = tags.get("collab") is True
        win = (pol.get("judging_cohorts") or {}).get("collab") if collab else None
        win = win or pol["judging"].get(ptype) or pol["judging"]["reel"]
        posted = None
        if tags.get("posting_time"):
            try:
                posted = mstore.to_central(mstore.parse_time(tags["posting_time"], f"{pid} posting_time"))
            except nc.UserError:
                nc.warn(f"post {pid}: posting_time {tags['posting_time']!r} is not a date-time; timing arms skipped")
        age_h = (now - posted).total_seconds() / 3600.0 if posted else None
        pulls = {k: v for k, v in (raw.get("pulls") or {}).items() if isinstance(v, dict) and isinstance(v.get("metrics"), dict)}
        status, label, jw = judge_state(ptype, pulls, age_h, win)
        arm = parse_arm(tags.get("strategy_arm"))
        pids = [x for x in (tags.get("pattern_ids") or []) if isinstance(x, str)]
        hook = next((x for x in pids if pb["patterns"].get(x, {}).get("kind") == "hook"), None)
        if hook is None and arm.get("hook"):
            hook = arm["hook"]
        if hook is None and tags.get("hook_type"):
            hook = hooks_by_type.get(str(tags["hook_type"]), f"hook_type:{tags['hook_type']}")
        structure = next((x for x in pids if pb["patterns"].get(x, {}).get("kind") in STRUCTURE_KINDS), None)
        if structure is None and arm.get("structure"):
            structure = arm["structure"]
        others = [x for x in pids if pb["patterns"].get(x, {}).get("kind") in ("cta", "offer", "growth")]
        sales = arm.get("goal") == "conversion" or (tags.get("pillar") == "offers_events" and arm.get("goal") != "reach")
        flags = []
        if posted is not None:
            hol = holidays.setdefault(posted.year, holiday_dates(pb, posted.year))
            if posted.date() in hol:
                flags.append("holiday")
        if tags.get("boosted") is True:
            flags.append("boosted")
        if collab:
            flags.append("collab")
        post = {
            "id": pid, "post_type": ptype, "tags": tags, "title": tags.get("title") or tags.get("slug") or pid,
            "posted": posted, "age_h": age_h, "status": status, "pull": label, "judge_weight": jw, "window": win,
            "weekday": WEEKDAYS[posted.weekday()] if posted else None,
            "hour_band": hour_band_of(posted.hour, bands) if posted else None,
            "pillar": tags.get("pillar") or arm.get("pillar"), "series": tags.get("series") or arm.get("series"),
            "hook": hook, "structure": structure, "others": others, "pattern_ids": pids, "sales": bool(sales),
            "offer_week": week_of_month(posted.date()) if posted and sales else None,
            "mode": arm.get("mode"), "length": tags.get("length"), "flags": flags, "collab": collab,
            "january": bool(posted and posted.month == 1),
            "pulls": {k: rates(v["metrics"], tags.get("length"), ptype) for k, v in pulls.items()},
        }
        post["values"] = post["pulls"].get(label, {}) if label else {}
        posts.append(post)
    posts.sort(key=lambda p: (p["posted"] or datetime.min, p["id"]))
    return posts


# ---------------------------------------------------------------------------
# scoring (R6): per-reach rates, log2 index vs the trailing same-format median, composite S, win = S > 0
# ---------------------------------------------------------------------------
COMPONENTS = ("reach", "sends", "saves", "follows", "watch_through", "views_per_reach", "profile_visits",
              "link_clicks", "link_taps_per_visit")
EXCEPTION_COMPONENT = {
    "saves": "saves", "shares": "sends", "skip_rate": "watch_through", "avg_watch_time_s": "watch_through",
    "retention": "watch_through", "views": "reach", "reach": "reach", "follows": "follows",
    "profile_visits": "profile_visits", "link_clicks": "link_clicks",
}


def component_value(post: dict, comp: str) -> float | None:
    """A component's rate at the pull that judges it: a metric exception (R7) has its own window."""
    label = post["pull"]
    if not label:
        return None
    hours = PULL_HOURS[label]
    ex = None
    for metric, w in (post["window"].get("exceptions") or {}).items():
        if EXCEPTION_COMPONENT.get(metric) == comp:
            ex = w
    if ex is None:
        return post["pulls"][label].get(comp)
    if hours < float(ex["provisional_hours"]):
        return None                                   # not readable yet (e.g. saves before 7 d)
    upto = min(float(ex["final_hours"]), float(hours))
    for lb in sorted(post["pulls"], key=lambda x: -PULL_HOURS.get(x, 0)):
        if PULL_HOURS.get(lb, 0) <= upto and comp in post["pulls"][lb]:
            return post["pulls"][lb][comp]
    return None


def baseline(post: dict, judged: list[dict], pol: dict, pooled: bool) -> list[dict]:
    """The trailing last-N same-format (or pooled feed) posts, each at least min_age_days old (R6 section 2)."""
    b = pol["scoring"]["baseline"]
    n, min_age, min_posts = int(b["window_posts"]), float(b["min_age_days"]) * 24.0, int(b["min_posts"])
    earlier = [q for q in judged if q is not post and q["posted"] is not None and post["posted"] is not None
               and q["posted"] < post["posted"]]
    if pooled:
        cohort = [q for q in earlier if q["post_type"] in FEED_TYPES and not q["collab"]]
    elif post["collab"]:
        cohort = [q for q in earlier if q["collab"]]
        if len(cohort) < min_posts:
            cohort = [q for q in earlier if q["post_type"] == post["post_type"]]
    else:
        cohort = [q for q in earlier if q["post_type"] == post["post_type"] and not q["collab"]]
    aged = [q for q in cohort if q["age_h"] is not None and q["age_h"] >= min_age]
    for pool in (aged, cohort):
        if len(pool) >= min_posts:
            return pool[-n:]
    return []


def log2_index(value: float, med: float, clip: float) -> float:
    if med <= 0 and value <= 0:
        return 0.0
    eps = max(1e-9, 0.01 * med)
    return max(-clip, min(clip, math.log2((value + eps) / (med + eps))))


def weighted(post: dict, pool: list[dict], weights: dict, clip: float, substitute: str | None) -> tuple[float | None, dict]:
    parts: dict[str, float] = {}
    acc = tw = 0.0
    for comp, w in weights.items():
        if w <= 0:
            continue
        c = comp
        if comp == "watch_through" and post["post_type"] not in VIDEO_TYPES and substitute:
            c = substitute                            # carousels/images: views per reach in place of watch-through
        v = component_value(post, c)
        vals = [x for x in (component_value(q, c) for q in pool) if x is not None]
        if v is None or not vals:
            continue
        s = log2_index(v, statistics.median(vals), clip)
        parts[c] = round(s, 4)
        acc += w * s
        tw += w
    return (acc / tw if tw else None), parts


def score_posts(posts: list[dict], pb: dict) -> list[dict]:
    """Composite S per post (same-format baseline), a pooled S (feed baseline, for formats) and the goal scores."""
    pol = pb["policies"]
    scp = pol["scoring"]
    clip = float(scp["index_clip_log2"])
    sub = scp.get("static_watch_substitute")
    judged = [p for p in posts if p["status"] in ("provisional", "final")]
    for p in posts:
        p.update({"score": None, "pooled_score": None, "win": None, "pooled_win": None, "components": {}, "goal_scores": {}})
        if p not in judged:
            continue
        pool = baseline(p, judged, pol, pooled=False)
        if not pool:
            p["score_note"] = "baseline still building (fewer than 3 earlier posts of this format)"
            continue
        s, parts = weighted(p, pool, scp["composite"], clip, sub)
        if s is None:
            p["score_note"] = "no metric to score"
            nc.warn(f"post {p['id']}: no metric to score; left out of learning")
            continue
        p["score"], p["components"] = round(s, 4), parts
        p["win"] = s > float(scp["win_above"])
        for goal, w in scp["goals"].items():
            g, _ = weighted(p, pool, w, clip, sub)
            if g is not None:
                p["goal_scores"][goal] = round(g, 4)
        if p["post_type"] in FEED_TYPES and not p["collab"]:
            ppool = baseline(p, judged, pol, pooled=True)
            if ppool:
                pw = {k: v for k, v in scp["composite"].items() if k != "watch_through"}
                ps, _ = weighted(p, ppool, pw, clip, sub)
                if ps is not None:
                    p["pooled_score"] = round(ps, 4)
                    p["pooled_win"] = ps > float(scp["win_above"])
    return posts


# ---------------------------------------------------------------------------
# learning (R6): discounted Beta-Bernoulli arms, one factored variable each
# ---------------------------------------------------------------------------
STATIC_SUFFIX = "@static"


def hook_key(pid: str, post_type: str) -> str:
    """Hooks are learned separately on video posts and on carousels/images (a cover slide is not a first second)."""
    return pid if post_type in VIDEO_TYPES else f"{pid}{STATIC_SUFFIX}"


def status_key(pb: dict, pid: str) -> str:
    p = pb["patterns"][pid]
    if p["kind"] == "hook" and not set(p["formats"]) & set(VIDEO_TYPES):
        return f"{pid}{STATIC_SUFFIX}"
    return pid


def owner_signals(pb: dict) -> dict[str, str]:
    """Owner results (REVIEW.md; STATE owner_priors from setup) outrank research priors."""
    out = {pid: p["owner_signal"] for pid, p in pb["patterns"].items() if p.get("owner_signal")}
    for op in pb["state"].get("owner_priors", []):
        out[op["target"]] = op["signal"]
    return out


def arm_prior(pb: dict, var: str, level: str) -> tuple[float, float]:
    """Beta prior (alpha, beta) for an arm: owners' data > measured > observed > opinion; never below Beta(1,1)."""
    pr = pb["policies"]["learning"]["prior"]
    owners = owner_signals(pb)
    base = level.split("@")[0]
    sig = owners.get(base) if var in ("hook", "structure", "pattern") else owners.get(f"{var}:{level}")
    if sig:
        t = float(pr["numa"]["tries"])
        rate = float(pr["numa"].get(sig, 0.75 if sig == "worked" else 0.25))
        return 1.0 + t * rate, 1.0 + t * (1 - rate)
    if var in ("hook", "structure", "pattern") and base in pb["patterns"]:
        lvl = pb["patterns"][base]["evidence"]["level"]
        cfg = pr.get(lvl if lvl != "numa" else "measured", pr["opinion"])
        t, rate = float(cfg["tries"]), float(cfg.get("win_rate", 0.5))
        return 1.0 + t * rate, 1.0 + t * (1 - rate)
    tilt = float((pb["policies"].get("prior_means") or {}).get(var, {}).get(level, 0.0))
    t = float(pr["opinion"]["tries"])
    return 1.0 + t * (0.5 + tilt), 1.0 + t * (0.5 - tilt)


def post_arms(p: dict) -> list[tuple[str, str, str]]:
    """(variable, level, outcome key) for every factored arm a post updates."""
    out: list[tuple[str, str, str]] = []
    trial = p["post_type"] == "trial_reel"
    pre = ""       # a Trial Reel is one try for its arms, judged against the trial-only baseline (R6 sections 5, 7)
    if p["post_type"] in FEED_TYPES and p["pooled_win"] is not None:
        out.append(("format", p["post_type"], "pooled"))
        if p["weekday"]:
            out.append(("format_day", f"{p['post_type']}|{p['weekday']}", "pooled"))
    if p["hook"]:
        out.append(("hook", pre + hook_key(p["hook"], p["post_type"]), "win"))
    if p["structure"]:
        out.append(("structure", pre + p["structure"], "win"))
    for x in p["others"]:
        out.append(("pattern", pre + x, "win"))
    if not trial:
        for var, lv in (("pillar", p["pillar"]), ("series", p["series"]), ("weekday", p["weekday"]),
                        ("band", p["hour_band"]), ("offer_week", p["offer_week"])):
            if lv:
                out.append((var, lv, "win"))
    return out


def fit_models(posts: list[dict], pb: dict) -> dict:
    """Discounted Beta posteriors per arm (gamma per new judged post) plus undiscounted decision records."""
    lp = pb["policies"]["learning"]
    gamma = float(lp["discount"])
    excluded = set(lp["exclude_from_decisions"])
    ev: dict[tuple[str, str], list[float]] = {}
    records: dict[tuple[str, str], list[dict]] = {}
    cohort: dict[str, list[dict]] = {}
    judged = [p for p in posts if p["status"] in ("provisional", "final") and p["score"] is not None]
    for p in judged:
        for k in ev:
            ev[k][0] *= gamma
            ev[k][1] *= gamma
        p["excluded"] = sorted(set(p["flags"]) & excluded)
        if p["collab"]:
            cohort.setdefault("collab", []).append(p)
        if p["excluded"]:
            continue
        w = p["judge_weight"]
        for var, lv, kind in post_arms(p):
            won = p["pooled_win"] if kind == "pooled" else p["win"]
            s = p["pooled_score"] if kind == "pooled" else p["score"]
            if won is None:
                continue
            e = ev.setdefault((var, lv), [0.0, 0.0])
            e[0 if won else 1] += w
            records.setdefault((var, lv), []).append({"post": p["id"], "date": p["posted"].date().isoformat() if p["posted"] else None,
                                                      "S": s, "win": bool(won), "final": p["status"] == "final",
                                                      "january": p["january"]})
    n = len(judged)
    prior_decay = gamma ** n          # R6: all counts, the priors' pseudo-counts too, decay by gamma per new post (floor Beta(1,1))
    arms: dict[tuple[str, str], dict] = {}
    for key in set(ev) | set(records):
        arms[key] = make_arm(pb, key, prior_decay, ev.get(key, [0.0, 0.0]), records.get(key, []))
    return {"arms": arms, "cohorts": cohort, "lambda": min(1.0, n / float(lp["data_led_after_posts"])), "judged": n,
            "prior_decay": prior_decay,
            "final": sum(p["status"] == "final" for p in judged), "provisional": sum(p["status"] == "provisional" for p in judged)}


def make_arm(pb: dict, key: tuple[str, str], prior_decay: float, ev: list[float], records: list[dict]) -> dict:
    a0, b0 = arm_prior(pb, *key)
    a = 1.0 + (a0 - 1.0) * prior_decay + ev[0]
    b = 1.0 + (b0 - 1.0) * prior_decay + ev[1]
    return {"alpha": a, "beta": b, "records": records, "mean": a / (a + b)}


def arm(fits: dict, pb: dict, var: str, level: str) -> dict:
    """An arm's posterior (its decayed prior when Numa has no data on it yet)."""
    if (var, level) in fits["arms"]:
        return fits["arms"][(var, level)]
    return make_arm(pb, (var, level), fits.get("prior_decay", 1.0), [0.0, 0.0], [])


def decision_stats(records: list[dict], january: bool = True) -> dict:
    rec = [r for r in records if r["final"] and (january or not r["january"])]
    s = [r["S"] for r in rec]
    return {"tries": len(rec), "wins": sum(r["win"] for r in rec),
            "median_index": round(2 ** statistics.median(s), 4) if s else None, "records": rec}


def analyse(store_path: str | None, pb: dict, today: date) -> tuple[list[dict], dict]:
    posts = collect_posts(load_store(store_path), pb, today)
    score_posts(posts, pb)
    return posts, fit_models(posts, pb)

# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------
def easter(year: int) -> date:
    """Gregorian Easter Sunday (Anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = (h + ll - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def nth_weekday(year: int, month: int, n: int, wd: int) -> date:
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(wd - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - wd) % 7)


def moment_days(m: dict, year: int, month: int) -> list[date]:
    w = m["when"]
    days = calendar.monthrange(year, month)[1]
    all_days = [date(year, month, i) for i in range(1, days + 1)]
    out: list[date] = []
    if "rule" in w:
        rule = w["rule"]
        if rule.startswith("fixed "):
            mm, dd = (int(x) for x in rule.split()[1].split("-"))
            centers = [date(year, mm, dd)] if mm == month else []
        elif rule.startswith("nth-weekday "):
            _, mon, n, wd = rule.split()
            centers = [nth_weekday(year, int(mon), int(n), [x.lower() for x in WEEKDAYS].index(wd))] if int(mon) == month else []
        else:  # mardi-gras
            centers = [easter(y) - timedelta(days=47) for y in (year - 1, year, year + 1)]
        lo, hi = (w.get("offset_days") or [0, 0])
        for c in centers:
            out += [c + timedelta(days=k) for k in range(lo, hi + 1)]
        return sorted({d for d in out if d.year == year and d.month == month})
    if "from" in w and "to" in w:
        fm, fd = (int(x) for x in w["from"].split("-"))
        tm, td = (int(x) for x in w["to"].split("-"))
        for d in all_days:
            key = (d.month, d.day)
            out.append(d) if (fm, fd) <= key <= (tm, td) else None
        return out
    if "months" in w and month not in w["months"]:
        return []
    if "days" in w:
        return [d for d in all_days if d.day in w["days"]]
    return all_days


def month_moments(pb: dict, year: int, month: int) -> list[dict]:
    cal = pb["calendar"]
    out = []
    for group in ("monthly", "seasonal", "holidays"):
        for m in cal[group]:
            ds = moment_days(m, year, month)
            if ds:
                out.append({"id": m["id"], "name": m["name"], "group": group, "from": ds[0].isoformat(), "to": ds[-1].isoformat(),
                            "dates": [d.isoformat() for d in ds], "what": m["what"], "pillar": m.get("pillar"),
                            "offer": bool(m.get("offer")), "possible_closure": bool(m.get("possible_closure")),
                            "hooks": m.get("hooks", []), "evidence": m["evidence"]["level"]})
    return out


# ---------------------------------------------------------------------------
# month plan
# ---------------------------------------------------------------------------
class Draws:
    """Thompson draws from the arms' Beta posteriors, one per arm per week, drawn in a fixed order (determinism)."""

    def __init__(self, fits: dict, pb: dict, rng):
        self.fits, self.pb, self.rng = fits, pb, rng
        self.cache: dict[tuple[str, str], float] = {}

    def beta(self, var: str, level: str) -> float:
        key = (var, level)
        if key not in self.cache:
            a = arm(self.fits, self.pb, var, level)
            self.cache[key] = float(self.rng.beta(a["alpha"], a["beta"]))
        return self.cache[key]

    def informed(self, var: str, level: str) -> float:
        """A draw for an arm NUMA has data on; the prior mean for one it hasn't (no churn from pure prior noise)."""
        a = arm(self.fits, self.pb, var, level)
        return self.beta(var, level) if a["records"] else a["mean"]

    def prime(self) -> None:
        for t in FEED_TYPES:
            self.beta("format", t)
            for wd in WEEKDAYS:
                self.beta("format_day", f"{t}|{wd}")
        for w in ("w1", "w2", "w3", "w4", "w5"):
            self.beta("offer_week", w)


def default_type(row: dict) -> str:
    return KIND_FOR_ROW[row["kind"]]


def make_row(day: date, role: str, month: int) -> dict:
    slot = next(s for s in sc.DEFAULT_WEEK if s["slot"] == role)
    slot = dict(slot)
    films = slot.pop("films")
    row: dict[str, Any] = {"day": day.day, "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
                           "folder": sc.day_folder(day.day, day, None), "title": None, "status": "Planned"}
    row.update(slot)
    if row["kind"] == "trial_reel":
        row["trial_reel"] = True
    if films:
        fb, session = sc.batch_session(day)
        row["film_by"], row["batch_session"] = fb.isoformat(), session
    else:
        row["film_by"], row["batch_session"] = None, None
    return row


def set_type(row: dict, ptype: str) -> None:
    """Change a feed row's post type (rows keep their role's pillar and goal)."""
    d = date.fromisoformat(row["date"])
    row["kind"] = ROW_KIND_FOR_TYPE[ptype]
    if ptype == "reel":
        row.pop("derived_from", None)
        row["template"] = row.get("template") or "modality_explainer"
        row["post"] = "Reel"
        fb, session = sc.batch_session(d)
        row["film_by"], row["batch_session"] = fb.isoformat(), session
    else:
        row["film_by"], row["batch_session"] = None, None
        row["series"] = None if row.get("series") in sc.SERIES else row.get("series")
        row.pop("template", None)
        row.pop("length_class", None)
        row["post"] = "Carousel" if ptype == "carousel" else "Single photo"
        if ptype == "image":
            row.pop("derived_from", None)


def compat_plan(plan: dict) -> dict:
    """The plan as shoot_card.py check reads it: an image post counts as a carousel-like feed post."""
    rows = []
    for r in plan["rows"]:
        r2 = {k: v for k, v in r.items() if k not in ("strategy",)}
        if r2["kind"] == "image":
            r2["kind"] = "carousel"
        r2["_d"] = date.fromisoformat(r2["date"])
        rows.append(r2)
    rows.sort(key=lambda r: (r["_d"], sc.KINDS.index(r["kind"])))
    return {**plan, "rows": rows}


def closure_items(items: list, where: str) -> dict[date, str]:
    """Closure dates from a list of 'YYYY-MM-DD', {date, name} or {start, end, closed, what} (brand.json closures.known)."""
    out: dict[date, str] = {}
    for it in items:
        if isinstance(it, dict) and ("start" in it or "end" in it):
            if it.get("closed") is False:
                continue                      # open with shorter hours: not a closure
            a = sc.parse_date(it.get("start") or it.get("end"), where)
            b = sc.parse_date(it.get("end") or it.get("start"), where)
            for i in range((b - a).days + 1):
                out[a + timedelta(days=i)] = str(it.get("what") or it.get("name") or "closed")
        elif isinstance(it, dict):
            out[sc.parse_date(it.get("date"), where)] = str(it.get("name") or it.get("what") or "closed")
        else:
            out[sc.parse_date(it, where)] = "closed"
    return out


def closure_dates(path: str | None) -> dict[date, str]:
    """brand.json closures.known plus a closures file (JSON list / {"closures": [...]} or CSV with a Date column)."""
    known = nc.brand_value("closures.known")
    out = closure_items(known if isinstance(known, list) else [], "brand.json closures.known")
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise nc.UserError(f"closures file not found: {p}")
        if p.suffix.lower() == ".csv":
            import csv
            import io
            reader = csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig")))
            key = next((k for k in (reader.fieldnames or []) if k and k.strip().lower() == "date"), None)
            if key is None:
                raise nc.UserError(f"closures file {p}: needs a Date column")
            out.update(closure_items([r[key] for r in reader if (r.get(key) or "").strip()], f"closures file {p}"))
        else:
            data = nc.read_json(p, "closures file")
            data = data.get("closures") if isinstance(data, dict) else data
            if not isinstance(data, list):
                raise nc.UserError(f"closures file {p}: expected a list of dates or {{\"closures\": [...]}}")
            out.update(closure_items(data, f"closures file {p}"))
    return out


def read_events(path: str | None) -> list[dict]:
    if not path:
        return []
    data = nc.read_json(Path(path).expanduser(), "events file")
    data = data.get("events") if isinstance(data, dict) else data
    if not isinstance(data, list):
        raise nc.UserError("events file: expected a list of {name, date} or {\"events\": [...]}")
    out = []
    for i, ev in enumerate(data):
        if not isinstance(ev, dict) or not ev.get("name") or not ev.get("date"):
            raise nc.UserError(f"events file item {i + 1}: needs 'name' and 'date'")
        out.append({"name": str(ev["name"]), "date": sc.parse_date(ev["date"], f"event {ev['name']}").isoformat()})
    return out


class Planner:
    def __init__(self, pb: dict, fits: dict, year: int, month: int, seed: int, events: list[dict],
                 closures: dict[date, str], posts: list[dict], diagnoses: list[dict]):
        self.pb, self.fits, self.year, self.month, self.seed = pb, fits, year, month, seed
        self.events, self.closures, self.posts, self.diagnoses = events, closures, posts, diagnoses
        self.pol = pb["policies"]
        self.lp = self.pol["learning"]
        self.moments = month_moments(pb, year, month)

    # -- structure (types, days, hours, offers, events) -------------------
    def build(self, lam: float) -> dict:
        import numpy as np
        rng = np.random.default_rng(self.seed)
        stick = float(self.lp["stickiness"])
        days_in = calendar.monthrange(self.year, self.month)[1]
        all_days = [date(self.year, self.month, i) for i in range(1, days_in + 1)]
        weeks: dict[date, list[date]] = {}
        for d in all_days:
            weeks.setdefault(sc.monday_of(d), []).append(d)
        rows: list[dict] = []
        week_draws: dict[date, Draws] = {}
        for wk in sorted(weeks):
            dr = Draws(self.fits, self.pb, rng)
            dr.prime()
            week_draws[wk] = dr
            for d in weeks[wk]:     # weekdays follow the default week (spec p.34); time is a blocked rotation (R6)
                r = make_row(d, sc.DEFAULT_WEEK[d.weekday()]["slot"], self.month)
                r["strategy"] = {"why": [], "week": wk.isoformat()}
                rows.append(r)
        by_date = {r["date"]: r for r in rows}
        for r in rows:
            if r["slot"] == "carousel":
                prev = date.fromisoformat(r["date"]) - timedelta(days=1)
                pr = by_date.get(prev.isoformat())
                r["derived_from"] = prev.day if pr and pr["kind"] == "reel" else None
        self.place_events(rows)
        self.assign_sales(rows, week_draws, lam, stick)
        self.assign_monthly(rows)
        self.assign_types(rows, week_draws, lam, stick)
        self.balance_pillars(rows, lam)
        self.assign_hours(rows, week_draws, lam)
        for r in rows:
            r["post_type"] = KIND_FOR_ROW[r["kind"]]
        plan = {"schema_version": 1, "month": f"{self.year:04d}-{self.month:02d}",
                "month_folder": sc.month_folder(all_days[0]), "days": days_in,
                "mix": nc.brand_value("positioning.content_mix", {}), "mix_tolerance": sc.DEFAULT_MIX_TOLERANCE,
                "events": [{"name": e["name"], "date": e["date"]} for e in self.events],
                "closures": [{"date": d.isoformat(), "name": n} for d, n in sorted(self.closures.items())],
                "rows": rows}
        plan["_draws"] = week_draws
        return plan

    def place_events(self, rows: list[dict]) -> None:
        cal = self.pb["calendar"]["events"]
        by_date = {r["date"]: r for r in rows}
        for ev in self.events:
            ed = date.fromisoformat(ev["date"])
            for role, (lo, hi), sign in (("teaser", cal["teaser_days_before"], -1), ("recap", cal["recap_days_after"], 1)):
                window = [ed + timedelta(days=sign * k) for k in range(lo, hi + 1)]
                if sign < 0:
                    window = sorted(window, reverse=True)  # prefer closer to the event... 2 days before first
                cands = [by_date[d.isoformat()] for d in window if d.isoformat() in by_date]
                cands = [r for r in cands if not r.get("event_role")]
                if role == "teaser":
                    cands = [r for r in cands if date.fromisoformat(r["date"]) not in self.closures]
                feed = [r for r in cands if r["kind"] in ("reel", "carousel") and r["slot"] != "offer_event_collab_reel"]
                pick = (feed or [r for r in cands if r["kind"] in ("reel", "carousel")] or cands or [None])[0]
                if pick is None:
                    continue
                d = date.fromisoformat(pick["date"])
                pick.update({"kind": "reel", "pillar": "offers_events", "event": ev["name"], "event_role": role,
                             "series": None, "template": "event_teaser" if role == "teaser" else "event_recap",
                             "goal": "offer" if role == "teaser" else "community", "post": f"Event {role}: {ev['name']}",
                             "slot_notes": f"{ev['name']} {role} (spec p.34 rule 7)"})
                pick.pop("derived_from", None)
                pick.pop("length_class", None)
                if role == "teaser":
                    pick["invites"] = True
                fb, session = sc.batch_session(d)
                pick["film_by"], pick["batch_session"] = fb.isoformat(), session
                pick["strategy"]["why"].append(f"Rule: {ev['name']} {role} {'2-3 days before' if role == 'teaser' else 'within 2 days after'} the event")

    def assign_sales(self, rows: list[dict], week_draws: dict, lam: float, stick: float) -> None:
        sales_rows = [r for r in rows if r["slot"] == "offer_event_collab_reel" and not r.get("event_role")]
        teaser_weeks = {sc.monday_of(date.fromisoformat(r["date"])) for r in rows if r.get("event_role") == "teaser"}
        lo, hi = self.pol["offers"]["offers_per_month"]
        offer_windows = {d for m in self.moments if m["offer"] for d in m["dates"]}
        ranked = []
        for r in sales_rows:
            d = date.fromisoformat(r["date"])
            wk = sc.monday_of(d)
            if wk in teaser_weeks or d in self.closures:
                continue
            dr = week_draws[wk]
            default_offer = (d.day - 1) // 7 % 2 == 0
            s = lam * dr.informed("offer_week", week_of_month(d)) + (stick if default_offer else 0.0) + (0.03 if r["date"] in offer_windows else 0.0)
            ranked.append((s, d, r))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        k = max(0, min(hi, max(lo, round(len(sales_rows) / 2)), len(sales_rows) - 2, len(ranked)))
        offers = {id(r) for _, _, r in ranked[:k]}
        collab_done = mtc_done = False
        for r in sales_rows:
            d = date.fromisoformat(r["date"])
            if id(r) in offers:
                r.update({"pillar": "offers_events", "goal": "offer", "template": "offer_promo", "sales": True, "series": None,
                          "slot_notes": "The week's one sales moment", "post": "Offer reel"})
                win = [m["name"] for m in self.moments if m["offer"] and r["date"] in m["dates"]]
                r["strategy"]["why"].append(f"Offer placed in {week_of_month(d)} of the month"
                                            + (f" ({', '.join(win)})" if win else "")
                                            + f"; offer-week win-rate draw {week_draws[sc.monday_of(d)].informed('offer_week', week_of_month(d)):.2f}")
                continue
            r.update({"pillar": "collective_collabs", "goal": "community", "template": "class_spotlight", "sales": False,
                      "post": "Collab reel"})
            if not collab_done:
                r.update({"collab": True, "series": None, "slot_notes": "Collab: 'Sweat there, recover here'"})
                collab_done = True
                r["strategy"]["why"].append("Rule: at least one collab reel a month (spec p.34 rule 4)")
            elif not mtc_done:
                r.update({"collab": True, "series": "meet_the_collective", "slot_notes": "Meet the Collective feature"})
                mtc_done = True
                r["strategy"]["why"].append("Rule: one Meet the Collective feature a month (spec p.34 rule 4)")
            else:
                r.update({"collab": True, "series": None, "slot_notes": "Collab or partner feature"})
            if d in self.closures or sc.monday_of(d) in teaser_weeks:
                r["strategy"]["why"].append("No offer this week: " + ("closure day" if d in self.closures else "the event teaser is the week's sales post"))

    def assign_monthly(self, rows: list[dict]) -> None:
        reels = [r for r in rows if r["kind"] == "reel" and not r.get("event_role")]
        if not any(r.get("series") == "meet_the_collective" for r in rows) or not any(r.get("collab") and r.get("series") != "meet_the_collective" for r in rows):
            spare = [r for r in reels if r["slot"] == "community_reel"]
            spare = spare[1:] if len(spare) > 1 else spare
            if not any(r.get("collab") and r.get("series") != "meet_the_collective" for r in rows) and spare:
                r = spare.pop(0)
                r.update({"collab": True, "series": None, "pillar": "collective_collabs", "goal": "community",
                          "template": "class_spotlight", "slot_notes": "Collab: 'Sweat there, recover here'"})
                r["strategy"]["why"].append("Rule: at least one collab reel a month (spec p.34 rule 4)")
            if not any(r.get("series") == "meet_the_collective" for r in rows) and spare:
                r = spare.pop(0)
                r.update({"collab": True, "series": "meet_the_collective", "pillar": "collective_collabs", "goal": "community",
                          "template": "class_spotlight", "slot_notes": "Meet the Collective feature"})
                r["strategy"]["why"].append("Rule: one Meet the Collective feature a month (spec p.34 rule 4)")
        community = [r for r in rows if r["kind"] == "reel" and r["slot"] == "community_reel" and r.get("series") == "first_plunge"]
        if len(community) >= 2:
            r = community[len(community) // 2]
            r.update({"signature": True, "template": "transformation", "series": None, "slot_notes": "Signature transformation or reveal"})
            r["strategy"]["why"].append("Rule: one signature transformation or reveal reel a month (spec p.34 rule 6)")
        for series, role in (("ask_the_dpt", "ask_the_dpt_reel"), ("first_plunge", "community_reel"), ("regulate", "regulate_reel")):
            mine = [r for r in rows if r["kind"] == "reel" and r.get("series") == series]
            if mine:
                mine[0]["_protect"] = f"keeps the {series} series in rotation"

    def balance_pillars(self, rows: list[dict], lam: float) -> None:
        """Rule: the month's content mix stays within tolerance of brand.json content_mix (shoot_card.py check)."""
        target = {k: float(v) for k, v in (nc.brand_value("positioning.content_mix", {}) or {}).items()}
        if set(target) != set(sc.PILLARS):
            return
        tol = sc.DEFAULT_MIX_TOLERANCE - 0.01
        dest_fields = {
            "community": {"goal": "community", "template": "member_story", "slot_notes": "Community moment (content mix)"},
            "local_seasonal": {"goal": "awareness", "template": "seasonal_holiday", "slot_notes": "Local or seasonal moment (content mix)"},
            "collective_collabs": {"goal": "community", "template": "class_spotlight", "slot_notes": "Collective feature (content mix)"},
        }
        for _ in range(40):
            counted = [r for r in rows if r["kind"] in ("reel", "trial_reel", "carousel", "image") and not r.get("derived_from")]
            if not counted:
                return
            n = len(counted)
            share = {p: sum(r.get("pillar") == p for r in counted) / n for p in sc.PILLARS}
            over = [p for p in sc.PILLARS if share[p] > target[p] + tol]
            under = [p for p in dest_fields if share[p] < target[p] + tol - 1.0 / n]
            if not over or not under:
                return
            src = max(over, key=lambda p: share[p] - target[p])
            pillar_mean = {p: arm(self.fits, self.pb, "pillar", p)["mean"] - 0.5 for p in under}
            dst = max(under, key=lambda p: (target[p] - share[p]) + lam * pillar_mean[p])
            seen: dict[str, int] = {}
            extras = []
            for r in counted:
                key = r.get("series") or r["slot"]
                seen[key] = seen.get(key, 0) + 1
                if (r.get("pillar") == src and seen[key] > 1 and not (r.get("event_role") or r.get("sales") or r.get("collab")
                                                                       or r.get("signature") or r.get("_protect"))):
                    extras.append(r)
            if not extras:
                return
            r = extras[-1]
            r.update({"pillar": dst, "series": None, **({k: v for k, v in dest_fields[dst].items() if k != "template" or r["kind"] in ("reel", "trial_reel")})})
            r["strategy"]["why"].append(f"Rule: content mix ({src} was {share[src]:.0%} of the month, target {target[src]:.0%}); "
                                        f"this slot became {dst}")

    def type_score(self, dr: Draws, row: dict, t: str, lam: float, stick: float) -> float:
        wd = row["weekday"]
        return lam * (dr.informed("format", t) + dr.informed("format_day", f"{t}|{wd}")) + (stick if t == default_type(row) else 0.0)

    def assign_types(self, rows: list[dict], week_draws: dict, lam: float, stick: float) -> None:
        """Format by goal (R6 test order 3): Thompson draws on the format arms (pooled wins vs the feed median)."""
        mix = self.pol["feed_mix"]
        for wk, dr in sorted(week_draws.items()):
            feed = [r for r in rows if r["strategy"]["week"] == wk.isoformat() and r["kind"] in ("reel", "carousel", "image")]
            if lam <= 0 or not feed:
                continue
            n = len(feed)
            max_nonreel = int(math.floor(n * (1 - float(mix["reel"]["min"])) + 1e-9))
            max_car = int(math.floor(n * float(mix["carousel"]["max"]) + 1e-9))
            max_img = int(math.floor(n * float(mix["image"]["max"]) + 1e-9))
            min_car = 1 if n >= 4 else 0
            current = {id(r): default_type(r) for r in feed}
            free = [r for r in feed if not (r.get("event_role") or r.get("collab") or r.get("signature") or r.get("_protect"))]
            moves = []
            for r in free:
                cur = current[id(r)]
                base = self.type_score(dr, r, cur, lam, stick)
                for t in FEED_TYPES:
                    if t != cur:
                        gain = self.type_score(dr, r, t, lam, stick) - base
                        if gain > 0:
                            moves.append((gain, r["date"], t, r))
            moves.sort(key=lambda x: (-x[0], x[1], x[2]))
            changed: set[int] = set()
            for gain, _, t, r in moves:
                if id(r) in changed:
                    continue
                trial = dict(current)
                trial[id(r)] = t
                vals = list(trial.values())
                if (sum(v != "reel" for v in vals) > max_nonreel or vals.count("carousel") > max_car
                        or vals.count("image") > max_img or vals.count("carousel") < min_car):
                    continue
                current = trial
                changed.add(id(r))
                old = default_type(r)
                set_type(r, t)
                fa = arm(self.fits, self.pb, "format", t)
                r["strategy"]["why"].append(
                    f"Type {old} -> {t}: {t}s beat the feed median in {fa['mean']:.0%} of NUMA's posts (posterior), "
                    f"{r['weekday']} draw gain {gain + stick:+.2f} > stickiness {stick:.2f} (data-led share {lam:.0%})")

    def time_plan(self) -> tuple[str, list[str], str]:
        """Blocked time-slot rotation outside the bandit (R6 section 6): (best band, rotation, reason)."""
        ts = self.lp["time_slots"]
        bands = self.pol["hour_bands"]["bands"]
        default = self.pol["hour_bands"]["default"]
        rot = [b for b in ts["rotation"] if b in bands] or [default]
        stats = {b: decision_stats(arm(self.fits, self.pb, "band", b)["records"]) for b in bands}
        best, why = default, f"{default.replace('_', ' ')} is the default (spec p.34) until a slot wins"
        d = stats[default]
        for b in rot:
            s = stats[b]
            if b == default or s["tries"] < ts["min_posts_each"] or d["tries"] < ts["min_posts_each"] or not d["median_index"]:
                continue
            ratio = s["median_index"] / d["median_index"]
            if ratio >= float(ts["min_ratio"]) and (best == default or s["median_index"] > stats[best]["median_index"]):
                best = b
                why = (f"{b.replace('_', ' ')} beat {default.replace('_', ' ')} by {ratio:.2f}x over {s['tries']} and "
                       f"{d['tries']} posts (needs {ts['min_ratio']}x over {ts['min_posts_each']} each)")
        return best, rot, why

    def assign_hours(self, rows: list[dict], week_draws: dict, lam: float) -> None:
        bands = self.pol["hour_bands"]["bands"]
        default = self.pol["hour_bands"]["default"]
        best, rot, why = self.time_plan()
        weeks = sorted({r["strategy"]["week"] for r in rows})
        for r in rows:
            w = weeks.index(r["strategy"]["week"])
            if r["kind"] == "stories":
                band, note = default, "the Stories default"
            elif best == default:
                band = rot[w % len(rot)]
                note = f"blocked rotation week {w + 1} ({' / '.join(x.replace('_', ' ') for x in rot)}); {why}"
            else:
                band = best if (w % 4 != 3 or len(rot) < 2) else next(b for b in rot if b != best)
                note = why + ("" if band == best else "; one week in four keeps rotating to watch the others")
            r["hour_band"] = band
            r["post_time"] = bands[band]["post_at"]
            r["strategy"]["why"].append(f"Hour: {band.replace('_', ' ')} ({bands[band]['post_at']} Central): {note}")

    # -- patterns ----------------------------------------------------------
    def pattern_slots(self, plan: dict) -> None:
        import numpy as np
        rng = np.random.default_rng(self.seed + 7919)
        rows = plan["rows"]
        feed = [r for r in rows if r["kind"] in ("reel", "carousel", "image")]
        n_explore = int(round(float(self.lp["explore_share"]) * len(feed)))
        protected = [r for r in feed if not (r.get("sales") or r.get("event_role") or r.get("signature") or r.get("collab"))]
        current = self.current_test_variable()
        r_note = f"testing {current} first (R6 test order: {', '.join(self.lp['test_order'])})"
        tested: dict[int, str] = {}
        for j in (list(rng.permutation(len(protected)))[:n_explore] if protected else []):
            tested[id(protected[int(j)])] = current
        plan["_test_note"] = r_note
        for r in rows:
            if r["kind"] == "trial_reel":
                tested[id(r)] = "hook"        # Trial Reels test hooks, on top of the explore share (trial-only pool)
        cap = float(self.lp["max_pattern_share_month"])
        hook_rows = [r for r in rows if r["kind"] in ("reel", "trial_reel", "carousel", "image")]
        limit = max(1, int(math.floor(cap * len(hook_rows) + 1e-9)))
        week_rows: dict[str, int] = {}
        for r in hook_rows:
            week_rows[r["strategy"]["week"]] = week_rows.get(r["strategy"]["week"], 0) + 1
        used: dict[str, int] = {}
        week_used: dict[tuple[str, str], int] = {}
        diag = self.diagnosis_bonus()
        draws = plan["_draws"]
        for r in rows:
            var = tested.get(id(r))
            rule = bool(r.get("event_role") or r.get("signature") or r.get("sales") or r["kind"] == "stories")
            mode = "explore" if var else ("rule" if rule else "exploit")
            r["strategy"]["mode"] = mode
            if var:
                r["strategy"]["tests"] = var
            wk = r["strategy"]["week"]
            dr = draws[date.fromisoformat(wk)]
            ptype = KIND_FOR_ROW[r["kind"]]
            goal = self.row_goal(r)
            r["strategy"]["goal"] = goal
            chosen: list[str] = []
            if ptype != "story":
                wk_limit = max(1, int(math.ceil(cap * week_rows.get(wk, 1) - 1e-9)))   # the 40% cap, spread over the weeks
                hook = self.pick(r, dr, "hook", ptype, goal, var == "hook", diag, used, limit, week_used, wk_limit)
                if hook:
                    used[hook] = used.get(hook, 0) + 1
                    week_used[(wk, hook)] = week_used.get((wk, hook), 0) + 1
                    chosen.append(hook)
                st = self.pick_structure(r, dr, ptype, goal, var == "structure", diag)
                if st:
                    chosen.append(st)
                    tmpl = self.pb["patterns"][st].get("templates") or []
                    if r["kind"] in ("reel", "trial_reel") and tmpl and not (r.get("event_role") or r.get("signature") or r.get("sales")):
                        r["template"] = tmpl[0]
                extra = self.pick(r, dr, "offer" if r.get("sales") else "cta", ptype, goal, var == "cta", diag, {}, 99, {}, 99)
                if extra:
                    chosen.append(extra)
            r["pattern_ids"] = chosen
            r["strategy"]["hook"] = next((x for x in chosen if self.pb["patterns"][x]["kind"] == "hook"), None)
            r["strategy"]["structure"] = next((x for x in chosen if self.pb["patterns"][x]["kind"] in STRUCTURE_KINDS), None)
            d = date.fromisoformat(r["date"])
            arm_tag = {"type": ptype, "pillar": r.get("pillar"), "series": r.get("series"), "day": r["weekday"],
                       "band": r.get("hour_band"), "hook": r["strategy"]["hook"], "structure": r["strategy"]["structure"],
                       "offer_week": week_of_month(d) if r.get("sales") or r.get("event_role") == "teaser" else None,
                       "goal": goal, "mode": mode, "plan": plan["month"]}
            r["strategy_arm"] = format_arm(arm_tag)
            moms = [m["id"] for m in self.moments if r["date"] in m["dates"] and m["group"] != "monthly"]
            if moms:
                r["moments"] = moms

    def current_test_variable(self) -> str:
        """The first variable in R6's test order that is not settled yet (a proven arm, or every arm in its pool tried enough)."""
        need = float(self.lp["promote"]["min_tries"])
        kinds = {"hook": ("hook",), "structure": STRUCTURE_KINDS, "cta": ("cta",)}
        for var in self.lp["test_order"]:
            if var not in kinds:
                continue                       # format: the weekly allocation; time: the blocked rotation
            pats = [p for p in self.pb["patterns"].values() if p["kind"] in kinds[var] and p["status"] != "retired"]
            if any(p["status"] == "proven" for p in pats):
                continue
            testing = [p for p in pats if p["status"] == "testing"]
            if any(self.pstat(p["id"], "reel" if var != "structure" or p["kind"] == "structure" else p["formats"][0])["tries"] < need
                   for p in testing):
                return var
        return next((v for v in self.lp["test_order"] if v in kinds), "hook")

    def row_goal(self, r: dict) -> str:
        if r.get("sales") or r.get("event_role") == "teaser" or r.get("goal") == "offer":
            return "conversion"
        if r["kind"] == "carousel":
            return "saves"
        return "reach"

    def diagnosis_bonus(self) -> dict[tuple[str, str], float]:
        """(series or post type, pattern id) -> bonus for the documented fix of a recent underperformer."""
        out: dict[tuple[str, str], float] = {}
        for dg in self.diagnoses:
            key = dg.get("series") or dg["post_type"]
            for row in dg["rows"]:
                for pid in row.get("try_patterns", []):
                    out[(key, pid)] = 0.08
        return out

    def pattern_arm(self, pid: str, ptype: str) -> tuple[str, str]:
        kind = self.pb["patterns"][pid]["kind"]
        pre = ""
        if kind == "hook":
            return "hook", pre + hook_key(pid, ptype)
        if kind in STRUCTURE_KINDS:
            return "structure", pre + pid
        return "pattern", pre + pid

    def pstat(self, pid: str, ptype: str) -> dict:
        a = arm(self.fits, self.pb, *self.pattern_arm(pid, ptype))
        return {**a, **decision_stats(a["records"])}

    def candidates(self, kinds: tuple[str, ...], ptype: str, r: dict) -> list[dict]:
        fmt = {ptype, "reel"} if ptype == "trial_reel" else {ptype}
        pats = [p for p in self.pb["patterns"].values() if p["kind"] in kinds and p["status"] != "retired"
                and fmt & set(p["formats"])]
        fit = [p for p in pats if not p.get("pillars") or r.get("pillar") in p["pillars"]]
        return sorted(fit or pats, key=lambda p: p["id"])

    def fit_bonus(self, p: dict, r: dict, goal: str, diag: dict) -> float:
        b = 0.0
        if p.get("series") and r.get("series") in p["series"]:
            b += 0.08
        if goal not in p["goals"]:
            b -= 0.04
        for m in self.moments:
            if r["date"] in m["dates"] and p["id"] in m.get("hooks", []):
                b += 0.04
        if r.get("event_role") == "teaser" and p["id"] in self.pb["calendar"]["events"].get("teaser_hooks", []):
            b += 0.3
        b += diag.get((r.get("series") or KIND_FOR_ROW[r["kind"]], p["id"]), 0.0)
        if not self.pstat(p["id"], KIND_FOR_ROW[r["kind"]])["records"] and p.get("priority"):
            b += 0.05 * max(0, 6 - int(p["priority"])) / 5.0   # test-first rank while NUMA has no data on it
        return b

    def choose(self, r: dict, dr: Draws, pats: list[dict], ptype: str, goal: str, explore: bool, diag: dict,
               penalty: dict[str, float]) -> tuple[str, str] | None:
        """Exploit: the best posterior mean among proven arms (else tried, else all). Explore: Thompson over 3-5 arms."""
        if not pats:
            return None
        if explore:
            pool = [p for p in pats if p["status"] != "proven"] or pats
            lo, hi = self.lp["arms_per_variable"]
            need = float(self.lp["promote"]["min_tries"])

            def rank(p: dict) -> tuple:
                done = self.pstat(p["id"], ptype)["tries"] >= need
                return (p["status"] != "testing", done, p.get("priority", 99), p["id"])
            # R6: 3-5 arms at a time, in test-first order; an arm with enough tries makes room for the next
            pool = sorted(pool, key=rank)[:max(int(lo), int(hi))]
            scored = []
            for p in pool:
                st = self.pstat(p["id"], ptype)
                s = dr.beta(*self.pattern_arm(p["id"], ptype)) + self.fit_bonus(p, r, goal, diag) - penalty.get(p["id"], 0.0)
                s += 0.1 / (1 + st["tries"] + len(st["records"]))   # explore what NUMA has least data on
                scored.append((s, p["id"]))
            mode = f"explore: Thompson draw over {len(pool)} arms"
        else:
            proven = [p for p in pats if p["status"] == "proven"]
            tried = [p for p in pats if self.pstat(p["id"], ptype)["records"]]
            pool = proven or (tried if len(tried) >= 2 else pats)
            scored = [(self.pstat(p["id"], ptype)["mean"] + self.fit_bonus(p, r, goal, diag) - penalty.get(p["id"], 0.0), p["id"])
                      for p in pool]
            mode = "exploit: best posterior " + ("among proven patterns" if proven else "so far")
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1], mode

    def describe(self, pid: str, ptype: str) -> str:
        st = self.pstat(pid, ptype)
        mi = f", median {st['median_index']:.2f}x" if st["median_index"] else ""
        return (f"{pid} ({self.pb['patterns'][pid]['status']}, {st['tries']} final tries, {st['wins']} wins{mi}; "
                f"P(beats median) {st['mean']:.0%})")

    def pick(self, r: dict, dr: Draws, kind: str, ptype: str, goal: str, explore: bool, diag: dict,
             used: dict, limit: int, week_used: dict, week_limit: int) -> str | None:
        wk = r["strategy"]["week"]
        pats = [p for p in self.candidates((kind,), ptype, r)
                if used.get(p["id"], 0) < limit and week_used.get((wk, p["id"]), 0) < week_limit]
        penalty: dict[str, float] = {}     # hook fatigue is handled by the monthly cap (R6: 40% per pattern)
        got = self.choose(r, dr, pats, ptype, goal, explore, diag, penalty)
        if not got:
            return None
        best, how = got
        r["strategy"]["why"].append(f"{kind.capitalize()}: {self.describe(best, ptype)}; {how}")
        return best

    def pick_structure(self, r: dict, dr: Draws, ptype: str, goal: str, explore: bool, diag: dict) -> str | None:
        fixed = None
        if r.get("event_role") == "teaser":
            fixed = self.pb["calendar"]["events"].get("teaser_structure")
        elif r.get("event_role") == "recap":
            fixed = self.pb["calendar"]["events"].get("recap_structure")
        elif r.get("signature"):
            fixed = self.pb["calendar"]["events"].get("signature_structure")
        elif r.get("sales"):
            fixed = (self.pb["calendar"]["events"].get("offer_structures") or {}).get(ptype)
        if fixed and fixed in self.pb["patterns"] and self.pb["patterns"][fixed]["status"] != "retired":
            r["strategy"]["why"].append(f"Structure: {fixed} (rule: {r.get('event_role') or ('signature' if r.get('signature') else 'sales')} slot)")
            return fixed
        kinds = {"reel": ("structure",), "trial_reel": ("structure",), "carousel": ("carousel",), "image": ("photo",)}[ptype]
        reserved = set((self.pb["calendar"]["events"].get("offer_structures") or {}).values()) | {
            self.pb["calendar"]["events"].get(k) for k in ("teaser_structure", "recap_structure", "signature_structure")}
        pats = [p for p in self.candidates(kinds, ptype, r) if p["id"] not in reserved]
        if r.get("series"):
            ser = [p for p in pats if r["series"] in (p.get("series") or [])]
            pats = ser or [p for p in pats if not p.get("series")] or pats
        got = self.choose(r, dr, pats, ptype, goal, explore, diag, {})
        if not got:
            return None
        best, how = got
        r["strategy"]["why"].append(f"Structure: {self.describe(best, ptype)}; {how}")
        return best


def month_plan(pb: dict, fits: dict, month_text: str, seed: int | None, events: list[dict], closures_file: str | None,
               posts: list[dict], diagnoses: list[dict]) -> tuple[dict, list[dict]]:
    year, month = sc.parse_month(month_text)
    seed = int(seed) if seed is not None else year * 100 + month
    closures = closure_dates(closures_file)
    planner = Planner(pb, fits, year, month, seed, events, closures, posts, diagnoses)
    lam = fits["lambda"]
    tried = []
    plan = None
    violations: list[dict] = []
    for factor in (1.0, 0.5, 0.25, 0.0):
        lam_eff = lam * factor
        if tried and lam_eff == tried[-1]:
            continue
        tried.append(lam_eff)
        plan = planner.build(lam_eff)
        cp = compat_plan(plan)
        violations, warns, _ = sc.check_plan(cp, closures)
        if not violations:
            break
    assert plan is not None
    planner.pattern_slots(plan)
    plan.pop("_draws", None)
    test_note = plan.pop("_test_note", "")
    for r in plan["rows"]:
        r.pop("_protect", None)
    overridden = len(tried) > 1
    plan["strategy"] = {
        "seed": seed, "data_led_share": round(lam, 4), "data_led_share_used": round(tried[-1], 4),
        "judged_posts": fits["judged"], "final_posts": fits["final"], "provisional_posts": fits["provisional"],
        "rules_overrode_bandit": overridden,
        "formula": "data-led share = min(1, judged posts / policies.learning.data_led_after_posts); a feed slot changes "
                   "format when share x (Beta win-rate draw difference) > stickiness; patterns are Thompson-sampled from day one",
        "explore_share": planner.lp["explore_share"],
        "time_slot": planner.time_plan()[2],
        "explore_variable": test_note,
        "explore_slots": sum(r.get("strategy", {}).get("mode") == "explore" for r in plan["rows"]),
        "pattern_slots": sum(bool(r.get("pattern_ids")) for r in plan["rows"]),
        "moments": planner.moments,
        "playbook": pb["dir"],
    }
    if overridden:
        for r in plan["rows"]:
            r["strategy"]["why"].append(f"Planning rules won: the bandit's share was cut from {lam:.0%} to {tried[-1]:.0%} "
                                        f"so the month passes shoot_card.py check")
    return plan, violations


# ---------------------------------------------------------------------------
# diagnosis
# ---------------------------------------------------------------------------
DIAG_VALUE = {
    "views": lambda v: v.get("raw_views"), "reach": lambda v: v.get("reach"), "likes": lambda v: v.get("raw_likes"),
    "comments": lambda v: v.get("raw_comments"), "saves": lambda v: v.get("raw_saves"), "shares": lambda v: v.get("raw_shares"),
    "avg_watch_time_s": lambda v: v["raw_avg_watch_time_ms"] / 1000.0 if "raw_avg_watch_time_ms" in v else None,
    "skip_rate": lambda v: v.get("raw_skip_rate"), "retention": lambda v: v.get("watch_through"),
    "sends_per_1k_reach": lambda v: v["sends"] * 1000.0 if "sends" in v else None,
    "saves_per_1k_reach": lambda v: v["saves"] * 1000.0 if "saves" in v else None,
    "profile_visits": lambda v: v.get("profile_visits"), "follows": lambda v: v.get("follows"),
    "link_clicks": lambda v: v.get("link_clicks"),
}


def diagnose_post(p: dict, pb: dict, judged: list[dict]) -> list[dict]:
    """Diagnosis rows whose conditions all hold, against NUMA's same-format trailing median (R3 table)."""
    pool = baseline(p, judged, pb["policies"], pooled=False) or [q for q in judged if q["post_type"] == p["post_type"] and q is not p]

    def value(q: dict, m: str) -> float | None:
        if m == "length":
            return float(q["length"]) if isinstance(q.get("length"), (int, float)) else None
        if m == "score":
            return q.get("score")
        if m == "skip_rate_vs_median":
            own = q["values"].get("raw_skip_rate")
            meds = [x["values"].get("raw_skip_rate") for x in pool if x["values"].get("raw_skip_rate") is not None]
            return own - statistics.median(meds) if own is not None and meds else None
        f = DIAG_VALUE.get(m)
        return f(q["values"]) if f else None

    out = []
    for row in pb["diagnosis"]:
        if p["post_type"] not in row["post_types"] or (row.get("sales_only") and not p["sales"]):
            continue
        ok = True
        for c in row["when"]:
            v = value(p, c["metric"])
            if v is None:
                ok = False
                break
            if c["ref"] == "value":
                ref = c["x"]
            else:
                vals = [x for x in (value(q, c["metric"]) for q in pool) if x is not None]
                if not vals:
                    ok = False
                    break
                med = statistics.median(vals)
                ref = med * c["x"] if c["ref"] == "median_ratio" else med + c["x"]
            if not ((v < ref) if c["op"] == "<" else (v > ref)):
                ok = False
                break
        if ok:
            out.append({"id": row["id"], "symptom": row["symptom"], "cause": row["cause"], "fix": row["fix"],
                        "try_patterns": row.get("try_patterns", []), "evidence": row["evidence"]["level"]})
    return out


def recent_diagnoses(posts: list[dict], pb: dict) -> list[dict]:
    """The latest judged post per series (or post type) whose S is below log2(underperform_index), with its diagnosis rows."""
    thr = math.log2(float(pb["policies"]["learning"]["underperform_index"]))
    judged = [p for p in posts if p["status"] in ("provisional", "final")]
    latest: dict[str, dict] = {}
    for p in judged:
        latest[p["series"] or p["post_type"]] = p
    out = []
    for key in sorted(latest):
        p = latest[key]
        if p["score"] is not None and p["score"] < thr:
            rows = diagnose_post(p, pb, judged)
            if rows:
                out.append({"post": p["id"], "title": p["title"], "post_type": p["post_type"], "series": p["series"],
                            "score": p["score"], "index": round(2 ** p["score"], 3), "rows": rows})
    return out


# ---------------------------------------------------------------------------
# learn (R6 section 5 decision rules)
# ---------------------------------------------------------------------------
VAR_LABEL = {"format": "{v} posts", "format_day": "{a}s on {b}s", "weekday": "posting on {v}s", "band": "posting in the {v}",
             "pillar": "{v} content", "series": "the {v} series", "offer_week": "offers in week {v} of the month"}


def level_text(var: str, level: str) -> str:
    if var == "format_day":
        a, b = level.split("|")
        return VAR_LABEL[var].format(a=a.replace("_", " "), b=b)
    v = level.lstrip("w") if var == "offer_week" else level.replace("_", " ")
    return VAR_LABEL[var].format(v=v)


def insights(fits: dict, pb: dict) -> tuple[list[str], list[str]]:
    """'Do more of / Do less of' lines: arms with enough final tries and a clear win rate and median index."""
    ins = pb["policies"]["learning"].get("insight") or {"min_tries": 4, "min_win_rate": 0.65, "max_win_rate": 0.35}
    up = float(pb["policies"]["learning"]["promote"]["min_median_index"])
    down = float(pb["policies"]["learning"]["retire"]["max_median_index"])
    more, less = [], []
    for (var, level), a in sorted(fits["arms"].items()):
        st = decision_stats(a["records"])
        if st["tries"] < ins["min_tries"] or not st["median_index"]:
            continue
        rate = st["wins"] / st["tries"]
        if var in VAR_LABEL:
            label = level_text(var, level).capitalize()
            base = "the feed median" if var in ("format", "format_day") else "NUMA's median"
        else:
            pid = level.split(":")[-1].split("@")[0]
            if pid not in pb["patterns"]:
                continue
            label = pb["patterns"][pid]["name"] + (" (Trial Reels)" if level.startswith("trial:") else "") + \
                (" on carousels and images" if level.endswith(STATIC_SUFFIX) else "") + f" ({pid})"
            base = "NUMA's median"
        line = f"{label}: beat {base} in {st['wins']} of {st['tries']} posts, median {st['median_index']:.2f}x."
        if rate >= ins["min_win_rate"] and st["median_index"] >= up:
            more.append(line)
        elif rate <= ins["max_win_rate"] and st["median_index"] <= down:
            less.append(line)
    collab = [p for p in fits["cohorts"].get("collab", []) if p["score"] is not None and p["status"] == "final"]
    if len(collab) >= ins["min_tries"]:
        wins = sum(bool(p["win"]) for p in collab)
        line = f"Collab posts (their own cohort): beat the collab median in {wins} of {len(collab)}."
        (more if wins / len(collab) >= ins["min_win_rate"] else less if wins / len(collab) <= ins["max_win_rate"] else []).append(line)
    return more, less


def months_after(d: date, months: float) -> date:
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])) + timedelta(days=int(round((months % 1) * 30)))


def decide(p: dict, a: dict, lp: dict) -> tuple[str | None, str | None, dict]:
    """(new status, reason, stats) for one pattern's main-pool arm, per R6 section 5."""
    cur = p["status"]
    st = decision_stats(a["records"])
    no_jan = decision_stats(a["records"], january=False)
    pro, fast, ret, dem = lp["promote"], lp["fast_track"], lp["retire"], lp["demote"]
    name = p["name"]

    def promotes(s: dict) -> str | None:
        if s["tries"] >= pro["min_tries"] and s["wins"] >= pro["min_wins"] and (s["median_index"] or 0) >= pro["min_median_index"]:
            return (f"{name} beat NUMA's median in {s['wins']} of {s['tries']} posts with a median of {s['median_index']:.2f}x "
                    f"(promote at {pro['min_wins']:g} of {pro['min_tries']:g} and {pro['min_median_index']}x); promoted to the exploit slots.")
        first = s["records"][:int(fast["first"])]
        if len(first) >= fast["first"]:
            w = sum(r["win"] for r in first)
            mi = 2 ** statistics.median(r["S"] for r in first)
            if w >= fast["min_wins"] and mi >= fast["min_median_index"]:
                return (f"{name} won {w} of its first {len(first)} posts with a median of {mi:.2f}x (fast track); "
                        f"promoted, re-checked at 10 tries.")
        return None

    if cur in ("candidate", "testing"):
        why = promotes(no_jan)
        if why:
            return "proven", why, st
        if promotes(st):
            return None, (f"{name} would be promoted, but some wins are from January; it must win again in "
                          f"February-March first (R6: January wins are provisional)."), st
    if cur in ("candidate", "testing", "proven") and st["median_index"] is not None and st["median_index"] <= ret["max_median_index"]:
        for rule in ret["rules"]:
            if st["tries"] >= rule["min_tries"] and st["wins"] <= rule["max_wins"]:
                return "retired", (f"{name} beat NUMA's median in only {st['wins']} of {st['tries']} posts, median "
                                   f"{st['median_index']:.2f}x; retired for {lp['retired_months']:g} months."), st
    if cur == "proven" and st["tries"] >= dem["last"]:
        last = st["records"][-int(dem["last"]):]
        w = sum(r["win"] for r in last)
        mi = 2 ** statistics.median(r["S"] for r in last)
        if w <= dem["max_wins"] or mi < dem["min_median_index"]:
            return "testing", (f"{name} won {w} of its last {len(last)} posts (median {mi:.2f}x); back to testing "
                               f"(fatigue check)."), st
    if cur == "candidate" and a["records"]:
        return "testing", f"{name} was used for the first time; now testing.", st
    return None, None, st


def learn(pb: dict, fits: dict, today: date) -> tuple[dict, list[dict]]:
    st = copy.deepcopy(pb["state"])
    lp = pb["policies"]["learning"]
    changes: list[dict] = []
    for pid in sorted(pb["patterns"]):
        p = pb["patterns"][pid]
        ov = st["status_overrides"].get(pid) or {}
        if p["status"] == "retired" and ov.get("status") == "retired" and not ov.get("reentered"):
            since = date.fromisoformat(ov["since"])
            if today >= months_after(since, float(lp["retired_months"])):
                why = f"{p['name']} was retired on {ov['since']}; after {lp['retired_months']:g} months it re-enters testing once."
                st["status_overrides"][pid] = {"status": "testing", "since": today.isoformat(), "why": why, "reentered": True}
                changes.append({"date": today.isoformat(), "action": "reenter", "target": pid, "from": "retired", "to": "testing", "why": why})
            continue
        key = status_key(pb, pid)
        var = "hook" if p["kind"] == "hook" else ("structure" if p["kind"] in STRUCTURE_KINDS else "pattern")
        a = fits["arms"].get((var, key))
        if not a:
            continue
        new, why, s = decide(p, a, lp)
        if why and not new:
            if not any(c.get("target") == pid and c["action"] == "hold" and c["why"] == why for c in st.get("changelog", [])[-50:]):
                changes.append({"date": today.isoformat(), "action": "hold", "target": pid, "from": p["status"], "to": p["status"], "why": why})
            continue
        if new and new != p["status"]:
            entry = {"status": new, "since": today.isoformat(), "why": why, "tries": s["tries"], "wins": s["wins"]}
            if s["median_index"] is not None:
                entry["median_index"] = s["median_index"]
            if ov.get("reentered"):
                entry["reentered"] = True
            st["status_overrides"][pid] = entry
            action = {"proven": "promote", "retired": "retire", "testing": "demote" if p["status"] == "proven" else "start_testing"}[new]
            ch = {"date": today.isoformat(), "action": action, "target": pid, "from": p["status"], "to": new, "why": why,
                  "tries": s["tries"], "wins": s["wins"]}
            if s["median_index"] is not None:
                ch["median_index"] = s["median_index"]
            changes.append(ch)
    more, less = insights(fits, pb)
    st["insights"] = {"date": today.isoformat(), "judged_posts": fits["judged"], "data_led_share": round(fits["lambda"], 4),
                      "do_more": more, "do_less": less}
    st["changelog"] = list(st.get("changelog", [])) + changes
    st["updated"] = today.isoformat()
    return st, changes


def changelog_text(changes: list[dict], st: dict, fits: dict) -> str:
    lines = [f"Strategy update {st['updated']} ({fits['judged']} posts judged: {fits['final']} final, "
             f"{fits['provisional']} provisional; data-led share {fits['lambda']:.0%})"]
    lines.append("What changed:" if changes else "What changed: nothing yet (no pattern has enough posts to move).")
    lines += [f"- {c['why']}" for c in changes]
    lines.append("Do more of:")
    lines += [f"- {x}" for x in st["insights"]["do_more"]] or ["- (nothing clear yet)"]
    lines.append("Do less of:")
    lines += [f"- {x}" for x in st["insights"]["do_less"]] or ["- (nothing clear yet)"]
    return "\n".join(lines) + "\n"


def write_state(path: str, st: dict) -> None:
    check_doc(st, "strategy state (about to be written)")
    nc.write_json(Path(path).expanduser(), st)


# ---------------------------------------------------------------------------
# import-research
# ---------------------------------------------------------------------------
FIELD_ALIASES = [
    (r"^id\s*,\s*name$", "id_name"), (r"^id$", "id"), (r"^(pattern\s+)?name$|^tactic$|^structure$|^template name$", "name"),
    (r"^format|^applies to", "formats"), (r"example|share/save line", "examples"),
    (r"^template|fill[- ]in|^how to do it", "template"), (r"^visual", "visual"), (r"^best use|^goal|^use for", "goal"),
    (r"^effort|^impact", "expected"),
    (r"^evidence", "evidence"), (r"^sources?$|^links?$", "sources"), (r"^expected effect|^expected impact", "expected"),
    (r"^when not|^avoid", "when_not"), (r"try instead|if it underperforms|what to do if|^fix", "try_instead"),
    (r"beat|outline|slide-by-slide|^slides", "beats"), (r"^length", "length"), (r"^confidence", "confidence"),
    (r"^rule$", "rule"), (r"how to (test|verify|measure)|^measure", "how_to_test"), (r"failure", "failure"),
    (r"^composition", "visual"), (r"^how for", "template"), (r"^when to use", "when_use"),
]
METRIC_ALIASES = [
    (r"skip", "skip_rate"), (r"average watch|watch time|avg watch", "avg_watch_time_s"), (r"retention", "retention"),
    (r"send|share", "sends_per_1k_reach"), (r"save", "saves_per_1k_reach"), (r"profile visit", "profile_visits"),
    (r"follow", "follows"), (r"link|click", "link_clicks"), (r"comment", "comments"), (r"like", "likes"),
    (r"view|play", "views"), (r"reach", "reach"),
]
EXCEPTION_METRICS = [
    (r"save", "saves"), (r"send|share", "shares"), (r"skip", "skip_rate"), (r"watch", "avg_watch_time_s"),
    (r"retention", "retention"), (r"profile", "profile_visits"), (r"follow", "follows"), (r"link|click", "link_clicks"),
    (r"view|play", "views"), (r"reach", "reach"), (r"comment", "comments"), (r"like", "likes"),
]
URL = re.compile(r"https?://[^\s)\]>,;]+")


def field_key(label: str) -> str | None:
    t = norm_text(label.replace("*", "")).replace(" s ", "s ")
    raw = label.strip().strip("*").strip().lower()
    for pat, key in FIELD_ALIASES:
        if re.search(pat, raw) or re.search(pat, t):
            return key
    return None


def parse_tables(text: str) -> list[tuple[list[str], list[list[str]], str]]:
    """Markdown or tab-separated tables: (normalised headers, rows, heading above)."""
    out = []
    lines = text.splitlines()
    i = 0
    heading = ""
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^\s*#{1,6}\s", ln):
            heading = ln.strip("# ").strip()
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1].strip()):
            hdr = [c.strip().strip("*").strip() for c in ln.strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append(([kebab(h).replace("-", "_") for h in hdr], rows, heading))
            i = j
            continue
        if "\t" in ln and i + 1 < len(lines) and "\t" in lines[i + 1] and len(ln.split("\t")) >= 3:
            hdr = [c.strip() for c in ln.split("\t")]
            rows = []
            j = i + 1
            while j < len(lines) and "\t" in lines[j]:
                rows.append([c.strip() for c in lines[j].split("\t")])
                j += 1
            out.append(([kebab(h).replace("-", "_") for h in hdr], rows, heading))
            i = j
            continue
        i += 1
    return out


ITEM_BOLD = re.compile(r"^\s*\*\*([A-Z]{1,2}\d{1,2})\s*[\u2014\u2013-]\s*(.+?)\*\*\s*$")
ITEM_NUM = re.compile(r"^\s*(\d+)[.)]\s+\*\*(.+?)\*\*\s*(.*)$")


def parse_blocks(text: str) -> list[dict]:
    """Blocks of 'Field: value' lines: each heading, '**C1 - Name**' line or '1. **Name**' item starts one.

    A block keeps the last level-1/2 heading as its section, and the rows of any table inside it (beat tables).
    """
    blocks: list[dict] = []
    cur: dict | None = None
    section = ""
    last_key = None
    in_table = False
    for ln in text.splitlines():
        if ln.strip().startswith("|"):
            if cur is not None:
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    continue
                if in_table:
                    cur.setdefault("_rows", []).append(cells)
                else:
                    cur["_header"] = [kebab(c).replace("-", "_") for c in cells]
                in_table = True
            continue
        in_table = False
        h = re.match(r"^\s*(#{1,6})\s+(.*)$", ln)
        item = ITEM_BOLD.match(ln) or ITEM_NUM.match(ln)
        if h or item:
            if cur:
                blocks.append(cur)
            if h:
                title = h.group(2).strip().strip("*").strip()
                if len(h.group(1)) <= 2:
                    section = title
            else:
                title = f"{item.group(1)} \u2014 {item.group(2)}" if item.re is ITEM_BOLD else item.group(2)
            cur = {"_title": title.strip().strip("*").strip(), "_section": section, "_fields": {}}
            last_key = None
            continue
        if cur is None:
            continue
        m = re.match(r"^\s*[-*\u2022]?\s*\*{0,2}([A-Za-z][\w /(),&'+\u2192-]{0,48}?)\*{0,2}\s*[:\u2014\u2013]\s*\*{0,2}\s*(.*)$", ln)
        key = field_key(m.group(1)) if m else None
        if m and key:
            val = m.group(2).strip()
            cur["_fields"].setdefault(key, [])
            if val:
                cur["_fields"][key].append(val)
            last_key = key
            continue
        sub = re.match(r"^\s{2,}[-*\u2022]\s+(.*)$|^\s*[-*\u2022]\s+[\"\u201c'](.*)$", ln)
        if sub and last_key:
            cur["_fields"][last_key].append((sub.group(1) or sub.group(2) or "").strip())
    if cur:
        blocks.append(cur)
    return [b for b in blocks if b["_fields"]]


def split_examples(vals: list[str]) -> list[str]:
    out = []
    for v in vals:
        quoted = re.findall(r"[\"“]([^\"”]{4,200})[\"”]", v)
        parts = quoted or [x for x in re.split(r"\s*(?:;|\s/\s|\|)\s*", v) if x]
        for x in parts:
            x = x.strip().strip("\"'“”‘’").strip()
            if len(x) >= 3 and x not in out:
                out.append(x)
    return out


def parse_evidence(text: str, fname: str, sources: list[str]) -> dict:
    t = text.lower()
    words = sorted((t.find(lv), lv) for lv in ("measured", "observed", "opinion") if lv in t)
    if words:
        level = words[0][1]
    else:
        codes = [("opinion", r"\[p\]|\bpc\b|anecdot|practitioner"), ("observed", r"\[c\]|\ban\b|moderate|case stud"),
                 ("measured", r"\[o\]|\[m\]|\bos\b|\bls\b|official|strong")]
        present = [lv for lv, pat in codes if re.search(pat, t)]
        level = present[0] if present else "opinion"   # the weakest evidence present: patterns sit on measured mechanics
    srcs = URL.findall(text) + [s for v in sources for s in (URL.findall(v) or [v.strip()]) if s.strip()]
    rest = URL.sub("", text).strip(" -:;,.")
    rest = re.sub(r"\b(measured|observed|opinion|official|high|medium|low)\b(\s+confidence)?", "", rest, flags=re.I)
    rest = re.sub(r"\(\s*\)", "", rest).strip(" ()-:;,.")
    if rest and rest.lower() not in ("measured", "observed", "opinion"):
        srcs.append(rest[:300])
    srcs = [s for i, s in enumerate(srcs) if s and s not in srcs[:i]] or [f"research import: {fname}"]
    ev: dict[str, Any] = {"level": level, "sources": srcs[:8], "notes": f"Imported from {fname}."}
    conf = re.search(r"\b(high|medium|low)\b", t)
    if conf:
        ev["confidence"] = conf.group(1)
    return ev


def parse_formats(text: str) -> list[str]:
    t = text.lower()
    out = []
    for word, pt in (("trial", "trial_reel"), ("reel", "reel"), ("carousel", "carousel"), ("photo", "image"),
                     ("image", "image"), ("single", "image"), ("stor", "story")):
        if word in t and pt not in out:
            out.append(pt)
    return out


def parse_goals(text: str) -> list[str]:
    t = text.lower()
    out = []
    for words, g in ((("save", "education", "explainer", "protocol"), "saves"),
                     (("offer", "event", "convert", "booking", "conversion", "sale", "link"), "conversion"),
                     (("reach", "community", "local", "seasonal", "collab", "awareness", "discovery", "send", "growth"), "reach")):
        if any(w in t for w in words) and g not in out:
            out.append(g)
    return out or ["reach"]


def research_number(fname: str) -> str | None:
    m = re.match(r"^R(\d)\b", Path(fname).name.upper().replace("_", " ").replace("-", " "))
    return m.group(1) if m else None


def kind_for(fname: str, block: dict, forced: str | None) -> str | None:
    if forced:
        return forced
    n = research_number(fname)
    if n in ("1", "3", "5"):
        return {"1": "hook", "3": "structure", "5": "growth"}[n]
    ctx = f"{block['_section']} {block['_title']}".lower()
    if "carousel" in ctx:
        return "carousel"
    if "photo" in ctx or "single" in ctx or "image" in ctx:
        return "photo"
    if "offer" in ctx:
        return "offer"
    return "carousel" if n == "4" else None


def metric_from_text(text: str) -> str | None:
    t = text.lower()
    for pat, m in METRIC_ALIASES:
        if re.search(pat, t):
            return m
    return None


def to_number(text: str, what: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", str(text).replace(",", ""))
    if not m:
        raise ValueError(f"{what}: no number in {text!r}")
    v = float(m.group(0))
    if re.search(r"\b(d|day|days)\b", str(text).lower()) and not re.search(r"\bh(ours?)?\b", str(text).lower()):
        v *= 24.0
    return v


class Importer:
    def __init__(self, pb: dict, today: date, forced_kind: str | None):
        self.pb, self.today, self.forced = pb, today, forced_kind
        self.st = copy.deepcopy(pb["state"])
        self.st.setdefault("judging", {})
        self.ids = set(pb["patterns"])
        self.names = {(p["kind"], norm_text(p["name"])): pid for pid, p in pb["patterns"].items()}
        self.report: dict[str, list] = {"added": [], "merged": [], "rejected": [], "rules": [], "diagnosis": [],
                                        "priors": [], "judging": []}

    def log(self, action: str, target: str, why: str) -> None:
        self.st["changelog"].append({"date": self.today.isoformat(), "action": action, "target": target, "from": None,
                                     "to": None, "why": why})

    def run_file(self, path: Path) -> None:
        if not path.exists():
            raise nc.UserError(f"research file not found: {path}")
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        fname = path.name
        before = {k: len(v) for k, v in self.report.items()}
        for headers, rows, heading in parse_tables(text):
            self.table(headers, rows, heading, fname)
        for block in parse_blocks(text):
            self.block(block, fname)
        added = len(self.report["added"]) - before["added"] + len(self.report["diagnosis"]) - before["diagnosis"] \
            + len(self.report["rules"]) - before["rules"] + len(self.report["judging"]) - before["judging"] \
            + len(self.report["priors"]) - before["priors"]
        self.st["imports"].append({"date": self.today.isoformat(), "file": fname, "added": added,
                                   "merged": len(self.report["merged"]) - before["merged"],
                                   "rejected": len(self.report["rejected"]) - before["rejected"]})

    # tables -----------------------------------------------------------
    def table(self, headers: list[str], rows: list[list[str]], heading: str, fname: str) -> None:
        hs = set(headers)
        if "post_type" in hs and "provisional_hours" in hs:
            self.judging_table(headers, rows, fname)
        elif any("symptom" in h for h in headers) and any("fix" in h for h in headers):
            self.diagnosis_table(headers, rows, fname)
        elif any(h in ("post_type", "post_types", "type", "format") for h in headers) and any("share" in h for h in headers):
            self.share_table(headers, rows, fname)
        elif "rule" in hs:
            for r in rows:
                rec = dict(zip(headers, r))
                col = lambda word: next((v for k, v in rec.items() if word in k), "")  # noqa: E731
                self.add_rule(rec.get("rule", ""), col("evidence"), col("source"), col("confidence"), col("how_to"), fname, heading)
        elif "id" in hs or "name" in hs or "tactic" in hs:
            for r in rows:
                rec = dict(zip(headers, r))
                fields: dict[str, list[str]] = {}
                for h, v in rec.items():
                    k = field_key(h.replace("_", " "))
                    if k and v:
                        fields.setdefault(k, []).append(v)
                if fields:
                    self.block({"_title": rec.get("name") or rec.get("id") or "", "_section": heading, "_fields": fields}, fname)

    def judging_table(self, headers: list[str], rows: list[list[str]], fname: str) -> None:
        has_metric = "metric" in headers
        for r in rows:
            rec = dict(zip(headers, r))
            pt_raw = norm_text(rec.get("post_type", "")).replace(" ", "_")
            pt = {"photo": "image", "single_image": "image", "stories": "story", "trial_reels": "trial_reel",
                  "reels": "reel", "carousels": "carousel", "images": "image"}.get(pt_raw, pt_raw)
            where = f"{fname} judging row {pt_raw or '?'}"
            if pt not in POST_TYPES:
                self.reject(where, f"unknown post_type {rec.get('post_type')!r}")
                continue
            try:
                win = {"ignore_before_hours": to_number(rec.get("ignore_before_hours", "0"), "ignore_before_hours"),
                       "provisional_hours": to_number(rec["provisional_hours"], "provisional_hours"),
                       "provisional_weight": to_number(rec.get("provisional_weight", "0.5"), "provisional_weight"),
                       "final_hours": to_number(rec["final_hours"], "final_hours")}
            except (KeyError, ValueError) as e:
                self.reject(where, str(e))
                continue
            if not 0 <= win["provisional_weight"] <= 1:
                self.reject(where, f"provisional_weight {win['provisional_weight']} is not between 0 and 1")
                continue
            if not win["ignore_before_hours"] <= win["provisional_hours"] <= win["final_hours"] or win["final_hours"] <= 0:
                self.reject(where, "needs ignore_before_hours <= provisional_hours <= final_hours")
                continue
            if pt == "story" and win["final_hours"] >= 24:
                self.reject(where, "Story windows must be under 24 h (Instagram keeps Story insights 24 h only)")
                continue
            ev_text = " ".join(x for x in (rec.get("evidence", ""), rec.get("confidence", "")) if x)
            win["evidence"] = parse_evidence(ev_text, fname, [rec.get("sources", "")] if rec.get("sources") else [])
            if rec.get("best_early_metric"):
                win["best_early_metric"] = rec["best_early_metric"][:200]
            hv = next((v for k, v in rec.items() if k.startswith("how_to")), "")
            if hv:
                win["how_to_verify"] = hv[:300]
            win["origin"] = "research"
            win["added"] = self.today.isoformat()
            current = self.st["judging"].get(pt) or copy.deepcopy(self.pb["policies"]["judging"].get(pt) or {})
            if current.get("origin") == "numa":
                self.reject(where, "NUMA's own judging window is never overwritten by research")
                continue
            if has_metric and rec.get("metric"):
                metric = next((m for pat, m in EXCEPTION_METRICS if re.search(pat, rec["metric"].lower())), None)
                if metric is None:
                    self.reject(where, f"unknown metric {rec['metric']!r}")
                    continue
                base = current if current else None
                if not base:
                    self.reject(where, f"no window for {pt} to attach the {metric} exception to")
                    continue
                base.setdefault("exceptions", {})[metric] = dict(win)
                self.st["judging"][pt] = base
                self.report["judging"].append(f"{pt}:{metric}")
                self.log("import", f"judging:{pt}:{metric}", f"{pt} {metric} is judged final at {win['final_hours']:g} h "
                         f"(provisional {win['provisional_hours']:g} h at weight {win['provisional_weight']:g}), from {fname}.")
            else:
                if current.get("exceptions") and current.get("origin") == "research":
                    win["exceptions"] = current["exceptions"]
                self.st["judging"][pt] = win
                self.report["judging"].append(pt)
                self.log("import", f"judging:{pt}", f"{pt} posts: ignore before {win['ignore_before_hours']:g} h, provisional at "
                         f"{win['provisional_hours']:g} h (weight {win['provisional_weight']:g}), final at {win['final_hours']:g} h, from {fname}.")

    def diagnosis_table(self, headers: list[str], rows: list[list[str]], fname: str) -> None:
        col = {k: next((h for h in headers if k in h), None) for k in ("symptom", "cause", "fix", "evidence", "source")}
        existing = {norm_text(r["symptom"]) for r in self.pb["diagnosis"]} | {norm_text(r["symptom"]) for r in self.st["diagnosis"]}
        for r in rows:
            rec = dict(zip(headers, r))
            symptom = rec.get(col["symptom"] or "", "").strip()
            cause = rec.get(col["cause"] or "", "").strip() or "Not stated in the research."
            fix = rec.get(col["fix"] or "", "").strip()
            metric = metric_from_text(symptom)
            if not symptom or not fix or metric is None:
                self.reject(f"{fname} diagnosis '{symptom[:40]}'", "no metric named in the symptom (skip rate, watch time, retention, reach, sends, saves, profile visits, follows, link clicks)")
                continue
            if norm_text(symptom) in existing:
                self.report["merged"].append(f"diagnosis:{symptom[:40]}")
                continue
            hits = [h for h in claims_scan.scan_text(fix, where=f"{fname} fix") if h.severity == "fail"]
            if hits:
                self.reject(f"{fname} diagnosis '{symptom[:40]}'", hits[0].line())
                continue
            low = bool(re.search(r"\b(low|drop|below|falls?|weak|few|under)\b", symptom.lower()))
            if metric == "skip_rate":
                cond = {"metric": metric, "op": ">" if not low else "<", "ref": "median_delta", "x": 0.05 if not low else -0.05}
            else:
                cond = {"metric": metric, "op": "<" if low else ">", "ref": "median_ratio", "x": 0.8 if low else 1.2}
            video = metric in ("skip_rate", "avg_watch_time_s", "retention")
            rid = kebab(f"r-{metric}-{symptom}")[:60].strip("-")
            n = 2
            ids = {x["id"] for x in self.pb["diagnosis"]} | {x["id"] for x in self.st["diagnosis"]}
            base = rid
            while rid in ids:
                rid = f"{base[:56]}-{n}"
                n += 1
            ev = parse_evidence(rec.get(col["evidence"] or "", "") + " " + rec.get(col["source"] or "", ""), fname, [])
            row = {"id": rid, "metric": metric, "post_types": ["reel", "trial_reel"] if video else ["reel", "trial_reel", "carousel", "image"],
                   "when": [cond], "symptom": symptom, "cause": cause, "fix": fix,
                   "try_patterns": [x for x in re.findall(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", fix) if x in self.ids],
                   "evidence": ev, "origin": "research"}
            self.st["diagnosis"].append(row)
            existing.add(norm_text(symptom))
            self.report["diagnosis"].append(rid)
            self.log("import", f"diagnosis:{rid}", f"New diagnosis row from {fname}: {symptom} -> {fix}")

    def share_table(self, headers: list[str], rows: list[list[str]], fname: str) -> None:
        tcol = next(h for h in headers if h in ("post_type", "post_types", "type", "format"))
        scol = next(h for h in headers if "share" in h)
        for r in rows:
            rec = dict(zip(headers, r))
            types = parse_formats(rec.get(tcol, ""))
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", rec.get(scol, ""))]
            if len(types) != 1 or not nums or types[0] not in FEED_TYPES:
                continue
            val = sum(nums[:2]) / min(2, len(nums)) / 100.0
            if not 0 <= val <= 1:
                continue
            ev = parse_evidence(" ".join(rec.get(h, "") for h in headers if "evidence" in h or "source" in h or "confidence" in h), fname, [])
            self.st["priors"] = [p for p in self.st["priors"] if p["level"] != types[0]]
            self.st["priors"].append({"dimension": "feed_share", "level": types[0], "value": round(val, 4), "evidence": ev,
                                      "added": self.today.isoformat()})
            self.report["priors"].append(f"feed_share:{types[0]}={val:.2f}")
            self.log("import", f"prior:feed_share:{types[0]}", f"Research suggests {types[0]}s as about {val:.0%} of feed posts "
                     f"({ev['level']}); kept as a weak prior, NUMA's own data decides.")

    def add_rule(self, text: str, evidence: str, source: str, confidence: str, how: str, fname: str, heading: str) -> None:
        text = text.strip()
        if not text:
            return
        rid = kebab(f"rule-{text}")[:60].strip("-")
        if any(r["id"] == rid for r in self.st["rules"]):
            self.report["merged"].append(rid)
            return
        t = f"{heading} {text}".lower()
        topic = next((tp for words, tp in ((("hour", "time", "day of", "weekday"), "timing"), (("per week", "cadence", "frequency", "dark week"), "cadence"),
                                             (("offer", "discount", "promo"), "offers"), (("month",), "monthly"), (("mix", "share"), "mix"),
                                             (("promote", "retire", "sample", "explore", "score", "threshold"), "learning")) if any(w in t for w in words)), "other")
        rule = {"id": rid, "topic": topic, "rule": text[:500], "evidence": parse_evidence(f"{evidence} {confidence}", fname, [source] if source else []),
                "added": self.today.isoformat()}
        if how:
            rule["how_to_test"] = how[:300]
        self.st["rules"].append(rule)
        self.report["rules"].append(rid)

    # blocks -----------------------------------------------------------
    def reject(self, where: str, why: str) -> None:
        self.report["rejected"].append(f"{where}: {why}")
        self.log("reject", where[:120], f"Not imported: {why}")

    def block(self, b: dict, fname: str) -> None:
        f = b["_fields"]
        if "rule" in f and not ("template" in f or "examples" in f):
            self.add_rule(" ".join(f["rule"]), " ".join(f.get("evidence", [])), " ".join(f.get("sources", [])),
                          " ".join(f.get("confidence", [])), " ".join(f.get("how_to_test", [])), fname, b["_section"])
            return
        rows = b.get("_rows") or []
        if not ({"template", "examples", "beats"} & set(f)) and "id_name" not in f and not rows:
            return
        kind = kind_for(fname, b, self.forced)
        if kind is None:
            self.reject(f"{fname} '{b['_title'][:40]}'", "can't tell the pattern kind (name the file R1..R5 or pass --kind)")
            return
        pid, name = self.ident(b, kind)
        if not pid:
            self.reject(f"{fname} '{b['_title'][:40]}'", "no id or name")
            return
        hdr = b.get("_header") or []
        if rows and "beat" in hdr:
            col = {h: i for i, h in enumerate(hdr)}
            said = [r[col["said"]] for r in rows if "said" in col and len(r) > col["said"]]
            f.setdefault("examples", []).extend(x for x in said if re.search(r"[\"\u201c]", x))
            f.setdefault("beats", []).extend(
                f"{r[col['beat']]} ({r[col['seconds']]} s): {r[col['shown']] if 'shown' in col and len(r) > col['shown'] else ''}".strip()
                for r in rows if len(r) > max(col.get("beat", 0), col.get("seconds", 0)))
            if not f.get("template"):
                f["template"] = [" -> ".join(r[col["beat"]] for r in rows if len(r) > col["beat"])]
        if not f.get("template") and f.get("beats"):
            f["template"] = [" -> ".join(re.split(r"\s*\u00b7\s*", " ".join(f["beats"])))]
        if f.get("failure"):
            f.setdefault("when_not", []).append("Failure signs and fix: " + " ".join(f["failure"]))
        where = f"{fname} pattern {pid}"
        examples = split_examples(f.get("examples", []))
        good, bad = [], []
        for ex in examples:
            hits = [h for h in claims_scan.scan_text(ex, where=f"{where} example") if h.severity == "fail"]
            (bad if hits else good).append((ex, hits))
        for ex, hits in bad:
            self.reject(f"{where} example \"{ex[:50]}\"", hits[0].line())
        template = " ".join(f.get("template", [])).strip() or name
        t_hits = [h for h in claims_scan.scan_text(template, where=f"{where} template") if h.severity == "fail"]
        if t_hits:
            self.reject(where, t_hits[0].line())
            return
        good_ex = [ex for ex, _ in good][:6]
        ev = parse_evidence(" ".join(f.get("evidence", [])) + " " + " ".join(f.get("confidence", [])), fname, f.get("sources", []))
        existing = pid if pid in self.ids else self.names.get((kind, norm_text(name)))
        if existing:
            self.merge(existing, good_ex, ev, fname)
            return
        if not good_ex:
            self.reject(where, "no claims-safe example left")
            return
        fmts = parse_formats(" ".join(f.get("formats", []))) or {"hook": ["reel", "trial_reel"], "structure": ["reel"], "carousel": ["carousel"],
                                                                 "photo": ["image"], "offer": ["reel", "carousel"], "cta": ["reel"], "growth": ["reel"]}[kind]
        if kind == "carousel":
            fmts = ["carousel"]
        if kind == "photo":
            fmts = ["image"] if "image" not in fmts else fmts
        try_text = " ".join(f.get("try_instead", []))
        tries = [x for x in re.findall(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", try_text) if x in self.ids and x != pid]
        when_not = " ".join(f.get("when_not", [])).strip() or "Not stated in the research; treat as untested on NUMA."
        if try_text and not tries:
            when_not += f" If it underperforms: {try_text}"
        pat: dict[str, Any] = {"id": pid, "kind": kind, "name": name[:120], "formats": fmts,
                               "goals": parse_goals(" ".join(f.get("goal", []))),
                               "template": template[:600], "examples": good_ex, "evidence": ev, "status": "candidate",
                               "when_not": when_not[:600], "try_instead": tries, "origin": "research", "added": self.today.isoformat()}
        if f.get("visual"):
            pat["visual"] = " ".join(f["visual"])[:300]
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", " ".join(f.get("length", [])))][:2]
        if len(nums) == 2 and 0 < nums[0] <= nums[1] and kind == "structure":
            pat["length_s"] = nums
        if f.get("beats") and kind in STRUCTURE_KINDS:
            pat["beats"] = [x[:200] for x in f["beats"]][:12]
        self.st["patterns"] = [p for p in self.st["patterns"] if p["id"] != pid] + [pat]
        self.ids.add(pid)
        self.names[(kind, norm_text(name))] = pid
        self.report["added"].append(pid)
        self.log("import", pid, f"New candidate {kind} pattern '{name}' from {fname} ({ev['level']} evidence); "
                 f"it will be tried in exploration slots.")

    def ident(self, b: dict, kind: str) -> tuple[str | None, str]:
        """(id, name) from 'id, name' fields, an 'id: `x` · name: Y' title, or a 'C1 - Name' title (id = kind prefix + name)."""
        f = b["_fields"]
        title = b["_title"]
        if "id_name" in f:
            parts = [x.strip().strip("`*") for x in f["id_name"][0].split(",", 1)]
            return kebab(parts[0]), parts[1] if len(parts) > 1 else parts[0]
        m = re.search(r"id:\s*`?([a-z0-9]+(?:-[a-z0-9]+)*)`?\s*[\u00b7|,;]\s*name:\s*(.+)$", title)
        if m:
            return kebab(m.group(1)), m.group(2).strip().strip("`*\"")
        if f.get("id"):
            return kebab(f["id"][0].strip("`")), (f.get("name") or [f["id"][0]])[0]
        m = re.match(r"^\s*(?:[A-Z]{1,2}\d{1,2}|\d+[.)]?)\s*[\u2014\u2013-]\s*(.+)$", title)
        name = (m.group(1) if m else re.sub(r"^\s*[\d.)]+\s*", "", title)).strip()
        quoted = re.match(r"^[\"\u201c](.+?)[\"\u201d]", name)
        name = quoted.group(1) if quoted else re.split(r":\s*[\"\u201c]", name)[0]
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip(" `*\"") or "Imported pattern"
        title_id = re.search(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", title)
        if title_id:
            return title_id.group(1), name
        prefix = {"structure": "struct-", "carousel": "carousel-", "photo": "photo-", "growth": "growth-", "offer": "offer-"}.get(kind, "")
        return kebab(prefix + name, 48), name

    def merge(self, pid: str, examples: list[str], ev: dict, fname: str) -> None:
        # Research only adds sources and safe examples: status, evidence level and NUMA's results are never changed.
        cur = copy.deepcopy(next((p for p in self.st["patterns"] if p["id"] == pid), None) or self.pb["patterns"][pid])
        srcs = cur["evidence"]["sources"] + [s for s in ev["sources"] if s not in cur["evidence"]["sources"]]
        cur["evidence"]["sources"] = srcs[:12]
        note = f"Also in {fname} ({ev['level']})."
        if note not in cur["evidence"].get("notes", ""):
            cur["evidence"]["notes"] = (cur["evidence"].get("notes", "") + " " + note).strip()[:600]
        for ex in examples:
            if ex not in cur["examples"] and len(cur["examples"]) < 6:
                cur["examples"].append(ex)
        self.st["patterns"] = [p for p in self.st["patterns"] if p["id"] != pid] + [cur]
        self.report["merged"].append(pid)
        self.log("merge", pid, f"{cur['name']} is already in the playbook; added the sources and safe examples from {fname} "
                 f"(status and NUMA results unchanged).")


# ---------------------------------------------------------------------------
# brief
# ---------------------------------------------------------------------------
def build_brief(plan: dict, pb: dict, posts: list[dict], fits: dict, week: date, today: date) -> dict:
    mon = sc.monday_of(week)
    sun = mon + timedelta(days=6)
    rows = [r for r in plan.get("rows", []) if mon.isoformat() <= r["date"] <= sun.isoformat()]
    slots = []
    for r in rows:
        st = r.get("strategy") or {}
        slots.append({"date": r["date"], "weekday": r.get("weekday"), "post_type": r.get("post_type") or KIND_FOR_ROW.get(r["kind"], r["kind"]),
                      "kind": r["kind"], "post_time": r.get("post_time"), "hour_band": r.get("hour_band"), "pillar": r.get("pillar"),
                      "series": r.get("series"), "goal": st.get("goal"), "mode": st.get("mode", "rule"),
                      "pattern_ids": r.get("pattern_ids", []), "strategy_arm": r.get("strategy_arm"),
                      "event": r.get("event"), "event_role": r.get("event_role"), "sales": bool(r.get("sales")),
                      "why": st.get("why", [])})
    counts: dict[str, int] = {}
    for s in slots:
        counts[s["post_type"]] = counts.get(s["post_type"], 0) + 1
    use, avoid = [], []
    for pid in sorted(pb["patterns"]):
        p = pb["patterns"][pid]
        var = "hook" if p["kind"] == "hook" else ("structure" if p["kind"] in STRUCTURE_KINDS else "pattern")
        a = arm(fits, pb, var, status_key(pb, pid))
        s = decision_stats(a["records"])
        if p["status"] == "retired":
            avoid.append({"id": pid, "kind": p["kind"], "reason": (pb["state"]["status_overrides"].get(pid) or {}).get("why", "Retired.")})
        elif p["status"] == "proven":
            use.append({"id": pid, "kind": p["kind"], "status": "proven",
                        "reason": f"Beat NUMA's median in {s['wins']} of {s['tries']} final posts"
                                  + (f", median {s['median_index']:.2f}x." if s["median_index"] else ".")})
    planned = sorted({pid for s in slots for pid in s["pattern_ids"]})
    for pid in planned:
        if all(u["id"] != pid for u in use):
            p = pb["patterns"][pid]
            var = "hook" if p["kind"] == "hook" else ("structure" if p["kind"] in STRUCTURE_KINDS else "pattern")
            s = decision_stats(arm(fits, pb, var, status_key(pb, pid))["records"])
            use.append({"id": pid, "kind": p["kind"], "status": p["status"],
                        "reason": f"Planned this week ({p['status']}, {s['tries']} final NUMA posts so far)."})
    experiments = []
    for s in slots:
        if s["mode"] == "explore":
            row = next(r for r in rows if r["date"] == s["date"] and r["kind"] == s["kind"])
            var = (row.get("strategy") or {}).get("tests", "hook")
            tested = [x for x in s["pattern_ids"] if pb["patterns"].get(x, {}).get("kind") in
                      {"hook": ("hook",), "structure": STRUCTURE_KINDS, "cta": ("cta", "offer")}.get(var, ("hook",))]
            experiments.append({"date": s["date"], "post_type": s["post_type"], "testing": tested or s["pattern_ids"],
                                "compare_with": "other Trial Reels (trial-only pool)" if s["post_type"] == "trial_reel"
                                else f"NUMA's last {pb['policies']['scoring']['baseline']['window_posts']} {s['post_type']}s",
                                "metric": "composite S (win = S > 0)"})
    prov = [{"id": p["id"], "title": p["title"], "post_type": p["post_type"], "pull": p["pull"], "weight": p["judge_weight"],
             "final_after_hours": p["window"]["final_hours"]}
            for p in posts if p["status"] == "provisional"]
    pending = [p["id"] for p in posts if p["status"] == "pending"]
    more, less = insights(fits, pb)
    diag = recent_diagnoses(posts, pb)
    changes = [c for c in pb["state"].get("changelog", []) if c["action"] in ("promote", "retire", "demote", "start_testing")][-10:]
    reasoning = [f"{fits['judged']} posts judged ({fits['final']} final, {fits['provisional']} provisional); "
                 f"the plan is {fits['lambda']:.0%} data-led (min(1, judged / {pb['policies']['learning']['data_led_after_posts']}))."]
    if plan.get("strategy", {}).get("rules_overrode_bandit"):
        reasoning.append("Planning rules overrode part of the bandit's choice this month (see each slot's why).")
    reasoning += [f"Do more: {x}" for x in more[:4]] + [f"Do less: {x}" for x in less[:4]]
    for d in diag:
        reasoning.append(f"{d['title']} underperformed ({d['index']:.2f}x NUMA's median): {d['rows'][0]['fix']}")
    target = nc.brand_value("positioning.content_mix", {}) or {}
    suggested = {}
    for pil, share in target.items():
        mean = arm(fits, pb, "pillar", pil)["mean"] - 0.5
        suggested[pil] = float(share) * math.exp(max(-0.5, min(0.5, mean)) * fits["lambda"])
    tot = sum(suggested.values()) or 1.0
    suggested = {k: round(max(float(target[k]) - 0.05, min(float(target[k]) + 0.05, v / tot)), 3) for k, v in suggested.items()}
    brief = {"schema_version": 1, "kind": "strategy_brief", "date": today.isoformat(), "week_of": mon.isoformat(),
             "month": plan.get("month"),
             "data": {"judged_posts": fits["judged"], "final_posts": fits["final"], "provisional_posts": fits["provisional"],
                      "pending_posts": len(pending), "data_led_share": round(fits["lambda"], 4)},
             "provisional": prov, "pending": pending,
             "mix": {"feed_posts": sum(counts.get(t, 0) for t in FEED_TYPES), "post_types": counts,
                     "trial_reels": counts.get("trial_reel", 0), "suggested_pillar_mix": suggested},
             "slots": slots, "use_patterns": use, "avoid_patterns": avoid, "experiments": experiments,
             "diagnoses": diag, "do_more": more, "do_less": less, "changes": changes, "reasoning": reasoning,
             "guardrails": guardrails(mon, sun, plan),
             "rules_note": "Planning rules (claims, consent, budget, events, closures, one sales post a week) override this brief."}
    return brief


def guardrails(mon: date, sun: date, plan: dict) -> list[str]:
    """What the brief may never propose (REVIEW.md): only brand.json offers, no invented codes, boosts or partners."""
    offers = [o.get("name") for o in (nc.brand_value("offerings.offers", []) or []) if isinstance(o, dict) and o.get("name")]
    lines = [f"Offers: only those in brand.json offerings.offers ({', '.join(offers) or 'none recorded'}); never invent an offer, "
             "discount, code, paid boost or partnership.",
             "Don't send new people to Saturday mornings (often full); point them to weekdays.",
             "Nothing that invites people in on a closure day."]
    closed = [c for c in plan.get("closures", []) if mon.isoformat() <= str(c.get("date") if isinstance(c, dict) else c) <= sun.isoformat()]
    if closed:
        lines.append("Closed this week: " + ", ".join(f"{c['date']} ({c.get('name') or 'closed'})" if isinstance(c, dict) else str(c) for c in closed))
    return lines


def brief_markdown(b: dict) -> str:
    out = [f"# Strategy brief: week of {b['week_of']}", "",
           f"{b['data']['judged_posts']} posts judged ({b['data']['final_posts']} final, {b['data']['provisional_posts']} provisional), "
           f"{b['data']['data_led_share']:.0%} data-led.", "", "## This week", "",
           "| Date | Type | Time | Pillar | Mode | Patterns |", "|---|---|---|---|---|---|"]
    for s in b["slots"]:
        out.append(f"| {s['date']} {s['weekday'] or ''} | {s['post_type']} | {s['post_time'] or ''} | {s['pillar'] or ''} | "
                   f"{s['mode']} | {', '.join(s['pattern_ids'])} |")
    out += ["", "## Use", ""] + [f"- {u['id']}: {u['reason']}" for u in b["use_patterns"]]
    out += ["", "## Avoid", ""] + ([f"- {a['id']}: {a['reason']}" for a in b["avoid_patterns"]] or ["- nothing retired yet"])
    out += ["", "## Experiments", ""] + ([f"- {e['date']} {e['post_type']}: {', '.join(e['testing'])} vs {e['compare_with']}" for e in b["experiments"]] or ["- none"])
    out += ["", "## Still provisional", ""] + ([f"- {p['title']} ({p['post_type']}, {p['pull']} pull, weight {p['weight']:g})" for p in b["provisional"]] or ["- none"])
    out += ["", "## Do more of", ""] + ([f"- {x}" for x in b["do_more"]] or ["- nothing clear yet"])
    out += ["", "## Do less of", ""] + ([f"- {x}" for x in b["do_less"]] or ["- nothing clear yet"])
    out += ["", "## Why", ""] + [f"- {x}" for x in b["reasoning"]]
    if b.get("strategist_notes"):
        out += ["", "## Strategist notes", "", b["strategist_notes"]]
    out += ["", "## Guardrails", ""] + [f"- {g}" for g in b.get("guardrails", [])]
    out += ["", b["rules_note"], ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="strategy.py", description="Adaptive strategy engine (playbook + Bayesian learning + Thompson sampling).")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)

    def common(p, metrics_required=False, state=True):
        p.add_argument("--metrics", required=metrics_required, help="metrics.py store (metrics.json)")
        if state:
            p.add_argument("--state", help="learned overlay (STATE/strategy.json)")
        p.add_argument("--playbook", help="playbook folder (default: skills/numa-scriptwriter/playbook)")
        p.add_argument("--today", help="YYYY-MM-DD (default: today)")

    p = sub.add_parser("plan", help="recommended month allocation")
    p.add_argument("--month", required=True, help="YYYY-MM")
    common(p)
    p.add_argument("--events", help="JSON list of {name, date}")
    p.add_argument("--closures", help="closures JSON or CSV (shoot_card.py format)")
    p.add_argument("--seed", type=int, help="random seed (default YYYYMM)")
    p.add_argument("--out", help="write the plan JSON here")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("learn", help="update pattern statuses, changelog and insights")
    common(p, metrics_required=True)
    p.add_argument("--text", help="also write the plain-text changelog here")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("brief", help="the Strategist's week brief")
    p.add_argument("--plan", required=True, help="strategy plan JSON (plan --out)")
    common(p, metrics_required=True)
    p.add_argument("--week", help="any date in the week (default: --today)")
    p.add_argument("--out", help="write the brief JSON here")
    p.add_argument("--md", help="write the human brief here")
    p.add_argument("--notes", help="text file: the Strategist's notes, stored as strategist_notes")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("explain", help="why a slot got its type, time and patterns")
    p.add_argument("slot", metavar="SLOT", help="day number or YYYY-MM-DD")
    p.add_argument("--plan", required=True)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("diagnose", help="diagnosis rows for underperforming posts")
    common(p, metrics_required=True)
    p.add_argument("--post", help="one post id (default: the latest underperformer per series)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("score", help="per-post scores and judging status")
    common(p, metrics_required=True)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("import-research", help="import deep-research results into the state")
    p.add_argument("files", nargs="+", metavar="FILE")
    p.add_argument("--state", required=True)
    p.add_argument("--playbook")
    p.add_argument("--kind", choices=["hook", "structure", "carousel", "photo", "offer", "cta", "growth"])
    p.add_argument("--today")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("validate", help="check the playbook (and state): schema, claims, references")
    p.add_argument("--playbook")
    p.add_argument("--state")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("export", help="write the merged playbook")
    p.add_argument("--playbook")
    p.add_argument("--state")
    p.add_argument("--out", required=True)
    return ap


def find_row(plan: dict, slot: str) -> dict:
    rows = plan.get("rows") if isinstance(plan, dict) else None
    if not isinstance(rows, list):
        raise nc.UserError("plan: expected {\"rows\": [...]} (strategy.py plan --out)")
    s = slot.strip()
    for r in rows:
        if r.get("date") == s or (s.isdigit() and r.get("day") == int(s)):
            return r
    raise nc.UserError(f"no slot {slot!r} in the plan (use a day number or YYYY-MM-DD)")


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: plan, learn, brief, explain, diagnose, score, import-research, validate or export")

    if args.cmd == "explain":
        plan = nc.read_json(Path(args.plan).expanduser(), "plan")
        r = find_row(plan, args.slot)
        st = r.get("strategy") or {}
        out = {"date": r["date"], "weekday": r.get("weekday"), "post_type": r.get("post_type"), "post_time": r.get("post_time"),
               "pillar": r.get("pillar"), "series": r.get("series"), "mode": st.get("mode"), "pattern_ids": r.get("pattern_ids", []),
               "strategy_arm": r.get("strategy_arm"), "why": st.get("why", [])}
        if args.json:
            nc.print_json(out)
        else:
            print(f"{out['date']} {out['weekday']}: {out['post_type']} at {out['post_time']} Central, {out['pillar']}"
                  + (f" / {out['series']}" if out["series"] else "") + f" ({out['mode']})")
            print("Patterns: " + (", ".join(out["pattern_ids"]) or "none"))
            for w in out["why"]:
                print(f"- {w}")
        return 0

    state_path = getattr(args, "state", None)
    state = load_state(state_path)
    pb = load_playbook(args.playbook, state)

    if args.cmd == "validate":
        errs, warns = playbook_problems(pb)
        if args.json:
            nc.print_json({"ok": not errs, "errors": errs, "warnings": warns, "patterns": len(pb["patterns"]),
                           "diagnosis": len(pb["diagnosis"])})
        else:
            for w in warns:
                nc.warn(w)
            for e in errs:
                nc.error_line(e)
            if not errs:
                print(f"OK: {len(pb['patterns'])} patterns, {len(pb['diagnosis'])} diagnosis rows, every example claims-safe")
        return 1 if errs else 0

    if args.cmd == "export":
        doc = merged_doc(pb)
        check_doc(doc, "merged playbook")
        nc.write_json(Path(args.out).expanduser(), doc)
        print(f"Wrote {args.out}: {len(doc['patterns'])} patterns")
        return 0

    today = parse_day(args.today, "--today")

    if args.cmd == "import-research":
        imp = Importer(pb, today, args.kind)
        for f in args.files:
            imp.run_file(Path(f).expanduser())
        imp.st["updated"] = today.isoformat()
        for key in ("judging", "judging_cohorts"):
            if not imp.st.get(key):
                imp.st.pop(key, None)
        write_state(args.state, imp.st)
        rep = imp.report
        if args.json:
            nc.print_json({"ok": True, **rep})
        else:
            for r in rep["rejected"]:
                nc.warn(f"rejected: {r}")
            print(f"Imported {len(args.files)} file(s): {len(rep['added'])} new patterns, {len(rep['merged'])} merged, "
                  f"{len(rep['diagnosis'])} diagnosis rows, {len(rep['rules'])} rules, {len(rep['priors'])} priors, "
                  f"{len(rep['judging'])} judging windows, {len(rep['rejected'])} rejected")
        return 0

    posts, fits = analyse(args.metrics, pb, today)

    if args.cmd == "score":
        out = [{"id": p["id"], "post_type": p["post_type"], "status": p["status"], "pull": p["pull"], "weight": p["judge_weight"],
                "goal": p["goal"], "score": p["score"], "pooled_score": p["pooled_score"], "components": p["components"],
                **({"note": p["score_note"]} if p.get("score_note") else {})} for p in posts]
        if args.json:
            nc.print_json({"posts": out, "judged": fits["judged"], "data_led_share": round(fits["lambda"], 4)})
        else:
            for o in out:
                s = f"{o['score']:+.2f}" if o["score"] is not None else "n/a"
                print(f"{o['id']} ({o['post_type']}, {o['status']}{', ' + o['pull'] if o['pull'] else ''}): score {s}")
        return 0

    if args.cmd == "diagnose":
        judged = [p for p in posts if p["status"] in ("provisional", "final")]
        if args.post:
            p = next((q for q in posts if q["id"] == args.post), None)
            if p is None:
                raise nc.UserError(f"post {args.post!r} is not in the metrics store")
            if p not in judged:
                raise nc.UserError(f"post {args.post!r} is not judged yet ({p['status']}); wait for its first judging pull")
            result = [{"post": p["id"], "title": p["title"], "post_type": p["post_type"], "series": p["series"], "score": p["score"],
                       "rows": diagnose_post(p, pb, judged)}]
        else:
            result = recent_diagnoses(posts, pb)
        if args.json:
            nc.print_json(result)
        else:
            if not result or not any(d["rows"] for d in result):
                print("No diagnosis: no recent post underperformed with a matching symptom.")
            for d in result:
                for row in d["rows"]:
                    print(f"{d['post']}: {row['symptom']} -> {row['fix']}" + (f" (try: {', '.join(row['try_patterns'])})" if row["try_patterns"] else ""))
        return 0

    if args.cmd == "learn":
        new_state, changes = learn(pb, fits, today)
        write_state(args.state, new_state)
        text = changelog_text(changes, new_state, fits)
        if args.text:
            p = Path(args.text).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        if args.json:
            nc.print_json({"ok": True, "changes": changes, "insights": new_state["insights"], "judged": fits["judged"],
                           "final": fits["final"], "provisional": fits["provisional"], "data_led_share": round(fits["lambda"], 4)})
        else:
            print(text, end="")
        return 0

    if args.cmd == "plan":
        events = read_events(args.events)
        plan, violations = month_plan(pb, fits, args.month, args.seed, events, args.closures, posts, recent_diagnoses(posts, pb))
        plan["strategy"]["violations"] = violations
        if args.out:
            nc.write_json(Path(args.out).expanduser(), plan)
        if args.json:
            nc.print_json(plan)
        else:
            s = plan["strategy"]
            print(f"{plan['month']}: {s['judged_posts']} posts judged, {s['data_led_share']:.0%} data-led"
                  f"{' (rules cut it to ' + format(s['data_led_share_used'], '.0%') + ')' if s['rules_overrode_bandit'] else ''}; "
                  f"{s['explore_slots']} of {s['pattern_slots']} pattern slots explore")
            for r in plan["rows"]:
                print(f"{r['date']} {r['weekday']} {r['post_type']:<10} {r.get('post_time', ''):>5}  {r.get('pillar') or '':<18} "
                      f"{r['strategy'].get('mode', ''):<8} {', '.join(r.get('pattern_ids', []))}")
        for v in violations:
            nc.error_line(f"rule {v['rule']}: {v['message']}")
        return 1 if violations else 0

    if args.cmd == "brief":
        plan = nc.read_json(Path(args.plan).expanduser(), "plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("rows"), list):
            raise nc.UserError("plan: expected {\"rows\": [...]} (strategy.py plan --out)")
        week = parse_day(args.week, "--week") if args.week else today
        brief = build_brief(plan, pb, posts, fits, week, today)
        if args.notes:
            notes = Path(args.notes).expanduser()
            if not notes.exists():
                raise nc.UserError(f"notes file not found: {notes}")
            text = notes.read_text(encoding="utf-8").strip()
            hits = [h for h in claims_scan.scan_text(text, where="strategist notes") if h.severity == "fail"]
            if hits:
                raise nc.UserError(hits[0].line())
            if text:
                brief["strategist_notes"] = text
        errs = nc.schema_errors(BRIEF_SCHEMA, brief)
        if errs:
            raise nc.UserError(f"brief does not match schemas/{BRIEF_SCHEMA}: {errs[0]}")
        if args.out:
            nc.write_json(Path(args.out).expanduser(), brief)
        if args.md:
            p = Path(args.md).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(brief_markdown(brief), encoding="utf-8")
        if args.json:
            nc.print_json(brief)
        else:
            print(brief_markdown(brief), end="")
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
