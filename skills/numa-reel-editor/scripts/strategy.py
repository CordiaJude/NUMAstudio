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
PULL_HOURS = {"48h": 48, "72h": 72, "7d": 168}
LAST_PULL_HOURS = 168
EVIDENCE_ORDER = {"opinion": 0, "observed": 1, "measured": 2, "numa": 3}
DIMS_A = ("post_type", "type_weekday")
DIMS_B = ("weekday", "hour_band", "pillar", "series", "hook", "structure", "offer_week")
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


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def pct(mean: float) -> str:
    """A score difference as a plain percentage vs NUMA's median."""
    v = math.exp(mean) - 1.0
    return f"{abs(v) * 100:.0f}% {'better' if v >= 0 else 'worse'}"


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
    """metrics.json, read tolerantly (pattern_ids / strategy_arm tags may be present)."""
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
    best = min(bands, key=lambda n: min(abs(hour - bands[n]["hours"][0]), abs(hour - bands[n]["hours"][1])))
    return best


def derived(m: dict, length: Any, ptype: str) -> dict:
    """Raw and computed metric values of one pull (missing ones absent)."""
    out: dict[str, float] = {}
    for k, v in m.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = float(v)
    reach = out.get("reach")
    for src, dst in (("shares", "sends_per_1k_reach"), ("saves", "saves_per_1k_reach"),
                     ("profile_visits", "profile_visits_per_1k"), ("follows", "follows_per_1k"),
                     ("link_clicks", "link_clicks_per_1k")):
        if src in out and reach and reach > 0:
            out[dst] = out[src] / reach * 1000.0
    if ptype in VIDEO_TYPES:
        if "avg_watch_time_ms" in out:
            out["avg_watch_time_s"] = out["avg_watch_time_ms"] / 1000.0
            if isinstance(length, (int, float)) and length > 0:
                out["retention"] = out["avg_watch_time_s"] / float(length)
        if "skip_rate" in out:
            out["skip_rate"] = out["skip_rate"] / 100.0 if out["skip_rate"] > 1.0 else out["skip_rate"]
    else:
        for k in ("avg_watch_time_ms", "avg_watch_time_s", "retention", "skip_rate"):
            out.pop(k, None)
    if "views" not in out and "reach" in out:
        out["views_or_reach"] = out["reach"]
    elif "views" in out:
        out["views_or_reach"] = out["views"]
    return out


def judge_state(post_type: str, pulls: dict, age_h: float | None, win: dict) -> tuple[str, str | None, float]:
    """(status, pull label, weight): status pending | provisional | final."""
    labels = [lb for lb in pulls if lb in PULL_HOURS] or list(pulls)
    if not labels:
        return "pending", None, 0.0
    if post_type == "story":
        lb = sorted(labels, key=lambda x: PULL_HOURS.get(x, 0))[-1]
        return "final", lb, 1.0
    if age_h is not None and age_h < win["ignore_before_hours"]:
        return "pending", None, 0.0
    final_at = min(float(win["final_hours"]), LAST_PULL_HOURS)
    ordered = sorted(labels, key=lambda x: PULL_HOURS.get(x, 0))
    finals = [lb for lb in ordered if PULL_HOURS.get(lb, 0) >= final_at]
    if finals:
        return "final", finals[0], 1.0
    provs = [lb for lb in ordered if PULL_HOURS.get(lb, 0) >= float(win["provisional_hours"])]
    if provs:
        return "provisional", provs[-1], float(win["provisional_weight"])
    return "pending", None, 0.0


def collect_posts(store: dict, pb: dict, today: date) -> list[dict]:
    pol = pb["policies"]
    bands = pol["hour_bands"]["bands"]
    now = datetime.combine(today, datetime.max.time()).replace(microsecond=0)
    half_life = float(pol["learning"]["half_life_days"])
    hooks_by_type: dict[str, str] = {}
    for p in pb["patterns"].values():
        if p["kind"] == "hook":
            for ht in p.get("hook_types", []):
                hooks_by_type.setdefault(ht, p["id"])
    posts = []
    for pid in sorted(store["reels"]):
        raw = store["reels"][pid]
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags") or {}
        ptype = mstore.post_type_of(raw)
        win = pol["judging"].get(ptype) or pol["judging"].get("reel")
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
        sales = arm.get("goal") == "conversion" or tags.get("pillar") == "offers_events" and arm.get("goal") != "reach"
        goal = arm.get("goal") if arm.get("goal") in ("reach", "saves", "conversion") else None
        if goal is None:
            goal = "conversion" if tags.get("pillar") == "offers_events" else pol["post_types"].get(ptype, {}).get("default_goal", "reach")
            if ptype == "story":
                goal = "reach"
        post = {
            "id": pid, "post_type": ptype, "tags": tags, "title": tags.get("title") or tags.get("slug") or pid,
            "posted": posted, "status": status, "pull": label, "judge_weight": jw,
            "weekday": WEEKDAYS[posted.weekday()] if posted else None,
            "hour_band": hour_band_of(posted.hour, bands) if posted else None,
            "pillar": tags.get("pillar") or arm.get("pillar"), "series": tags.get("series") or arm.get("series"),
            "hook": hook, "structure": structure, "pattern_ids": pids, "goal": goal, "sales": bool(sales),
            "offer_week": week_of_month(posted.date()) if posted and sales else None,
            "mode": arm.get("mode"), "length": tags.get("length"),
            "decay": 0.5 ** (max(0.0, age_h / 24.0) / half_life) if age_h is not None else 1.0,
            "values": derived(pulls[label]["metrics"], tags.get("length"), ptype) if label else {},
            "all_pulls": {k: derived(v["metrics"], tags.get("length"), ptype) for k, v in pulls.items()},
        }
        posts.append(post)
    return posts


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
COMPONENT_VALUE = {
    "views": "views_or_reach", "sends": "sends_per_1k_reach", "saves": "saves_per_1k_reach", "skip": "skip_rate",
    "retention": "retention", "profile_visits": "profile_visits_per_1k", "follows": "follows_per_1k",
    "link_clicks": "link_clicks_per_1k",
}


def excluded_components(post: dict, win: dict) -> set[str]:
    """Components whose metric exception makes them not final yet at this pull."""
    if post["status"] != "provisional":
        return set()
    hours = PULL_HOURS.get(post["pull"] or "", 0)
    out = set()
    for metric, ex in (win.get("exceptions") or {}).items():
        if hours < min(float(ex["final_hours"]), LAST_PULL_HOURS) or hours < float(ex["provisional_hours"]):
            for comp, names in COMPONENT_METRICS.items():
                if metric in names:
                    out.add(comp)
    return out


def baseline_pool(post: dict, judged: list[dict], window_days: int, min_posts: int, same_type: bool) -> list[dict]:
    if post["posted"] is not None:
        lo = post["posted"] - timedelta(days=window_days)
        pool = [q for q in judged if q["posted"] is None or lo <= q["posted"] <= post["posted"]]
    else:
        pool = list(judged)
    if same_type:
        same = [q for q in pool if q["post_type"] == post["post_type"]]
        if len(same) >= min_posts:
            return same
        if post["post_type"] == "trial_reel":
            trials = [q for q in judged if q["post_type"] == "trial_reel"]
            if len(trials) >= min_posts:
                return trials
    feedish = [q for q in pool if q["post_type"] in FEED_TYPES] if post["post_type"] in FEED_TYPES else pool
    if len(feedish) >= min_posts:
        return feedish
    return pool if len(pool) >= min_posts else list(judged)


def median_of(pool: list[dict], key: str, pull: str | None) -> float | None:
    vals = []
    for q in pool:
        v = (q["all_pulls"].get(pull) or {}).get(key) if pull else None
        if v is None:
            v = q["values"].get(key)
        if v is not None:
            vals.append(v)
    return statistics.median(vals) if vals else None


def component_z(comp: str, value: float, med: float, cap: float, skip_unit: float) -> float:
    if comp == "skip":
        z = (med - value) / skip_unit
    else:
        eps = max(1e-6, 0.05 * abs(med))
        z = math.log((value + eps) / (med + eps))
    return max(-cap, min(cap, z))


def weighted_score(post: dict, pool: list[dict], weights: dict, sc_pol: dict, skip: set[str]) -> tuple[float | None, dict]:
    parts: dict[str, float] = {}
    total_w = 0.0
    acc = 0.0
    for comp, w in weights.items():
        if w <= 0 or comp in skip:
            continue
        key = COMPONENT_VALUE[comp]
        v = post["values"].get(key)
        if v is None:
            continue
        med = median_of(pool, key, post["pull"])
        if med is None:
            continue
        z = component_z(comp, v, med, float(sc_pol["winsor_log_cap"]), float(sc_pol["skip_unit"]))
        parts[comp] = round(z, 4)
        acc += w * z
        total_w += w
    if total_w == 0:
        return None, parts
    return acc / total_w, parts


def score_posts(posts: list[dict], pb: dict) -> list[dict]:
    """Adds score (goal, per-type baseline) and pooled_score to every judged post."""
    pol = pb["policies"]
    sc_pol = pol["scoring"]
    judged = [p for p in posts if p["status"] in ("provisional", "final")]
    wd, mn = int(sc_pol["baseline"]["window_days"]), int(sc_pol["baseline"]["min_posts"])
    for p in posts:
        p["score"] = p["pooled_score"] = None
        p["components"] = {}
        if p not in judged:
            continue
        win = pol["judging"].get(p["post_type"]) or pol["judging"]["reel"]
        skip = excluded_components(p, win)
        pool = baseline_pool(p, judged, wd, mn, same_type=True)
        if len(pool) < 2:
            p["score_note"] = "no baseline yet (fewer than 2 judged posts)"
            continue
        weights = dict(sc_pol["goal_weights"][p["goal"]])
        s, parts = weighted_score(p, pool, weights, sc_pol, skip)
        if s is None and p["goal"] == "conversion":
            s, parts = weighted_score(p, pool, dict(sc_pol["goal_weights"]["reach"]), sc_pol, skip)
            p["score_note"] = "no conversion metrics tracked; scored on reach"
        p["score"] = round(s, 4) if s is not None else None
        p["components"] = parts
        if s is None:
            p["score_note"] = "no metric to score"
            nc.warn(f"post {p['id']}: no metric to score; left out of learning")
        if p["post_type"] in FEED_TYPES:
            ppool = [q for q in baseline_pool(p, judged, wd, mn, same_type=False) if q["post_type"] in FEED_TYPES]
            if len(ppool) >= 2:
                ps, _ = weighted_score(p, ppool, dict(sc_pol["pooled_weights"]), sc_pol, skip)
                p["pooled_score"] = round(ps, 4) if ps is not None else None
    return posts


# ---------------------------------------------------------------------------
# Bayesian additive model
# ---------------------------------------------------------------------------
class Additive:
    """y = sum over dims of beta[dim][level] + noise, fitted by backfitting with Normal priors."""

    def __init__(self, dims: tuple[str, ...], prior, sigma2: float):
        self.dims = dims
        self.prior = prior            # (dim, level) -> (mean, strength)
        self.sigma2 = sigma2
        self.post: dict[str, dict[str, tuple[float, float, float]]] = {d: {} for d in dims}

    def fit(self, obs: list[tuple[dict, float, float]]) -> "Additive":
        levels: dict[str, set] = {d: set() for d in self.dims}
        for lv, _, _ in obs:
            for d in self.dims:
                if lv.get(d) is not None:
                    levels[d].add(lv[d])
        beta = {d: {v: self.prior(d, v)[0] for v in sorted(levels[d])} for d in self.dims}
        wsum = {d: {v: 0.0 for v in levels[d]} for d in self.dims}
        for _ in range(25):
            for d in self.dims:
                acc = {v: 0.0 for v in levels[d]}
                ws = {v: 0.0 for v in levels[d]}
                for lv, y, w in obs:
                    v = lv.get(d)
                    if v is None:
                        continue
                    r = y - sum(beta[o][lv[o]] for o in self.dims if o != d and lv.get(o) is not None)
                    acc[v] += w * r
                    ws[v] += w
                for v in sorted(levels[d]):
                    m0, n0 = self.prior(d, v)
                    beta[d][v] = (n0 * m0 + acc[v]) / (n0 + ws[v]) if (n0 + ws[v]) > 0 else m0
                wsum[d] = ws
        tw = sum(w for _, _, w in obs)
        if tw >= 8:
            resid = sum(w * (y - sum(beta[d][lv[d]] for d in self.dims if lv.get(d) is not None)) ** 2 for lv, y, w in obs)
            k = 5.0
            self.sigma2 = max(0.04, (k * self.sigma2 + resid) / (k + tw))
        for d in self.dims:
            for v in levels[d]:
                m0, n0 = self.prior(d, v)
                self.post[d][v] = (beta[d][v], self.sigma2 / max(1e-9, n0 + wsum[d][v]), wsum[d][v])
        return self

    def get(self, dim: str, level: Any) -> tuple[float, float, float]:
        if level in self.post.get(dim, {}):
            return self.post[dim][level]
        m0, n0 = self.prior(dim, level)
        return m0, self.sigma2 / max(1e-9, n0), 0.0


STATIC_SUFFIX = "@static"


def hook_key(pid: str, post_type: str) -> str:
    """Hooks are learned separately on video posts and on carousels/images (a cover slide is not a first second)."""
    return pid if post_type in VIDEO_TYPES else f"{pid}{STATIC_SUFFIX}"


def status_key(pb: dict, pid: str) -> str:
    """The posterior that decides a pattern's status: video for hooks used on video, else the static one."""
    p = pb["patterns"][pid]
    if p["kind"] == "hook" and not set(p["formats"]) & set(VIDEO_TYPES):
        return f"{pid}{STATIC_SUFFIX}"
    return pid


def pattern_prior(pb: dict, pid: str) -> tuple[float, float]:
    lp = pb["policies"]["learning"]
    pid = pid.split("@")[0]
    p = pb["patterns"].get(pid)
    if p is None:
        return 0.0, float(lp["prior_strength"]["opinion"])
    lvl = p["evidence"]["level"]
    strength = float(lp["prior_strength"].get(lvl, lp["prior_strength"]["opinion"])) if lvl != "numa" else float(lp["prior_strength"]["measured"])
    return float(lp.get("evidence_prior_mean", {}).get(lvl, 0.0)), strength


def make_prior(pb: dict):
    pol = pb["policies"]
    lp = pol["learning"]
    strength = lp["prior_strength"]
    pe = pol.get("prior_evidence", {})
    imported: dict[str, float] = {}
    for pr in pb["state"].get("priors", []):
        if pr["dimension"] == "feed_share":
            seed = float(pol["feed_mix"][pr["level"]]["prior"]) if pr["level"] in pol["feed_mix"] else 0.0
            tilt = 0.1 * math.log((pr["value"] + 0.05) / (seed + 0.05))
            imported[pr["level"]] = max(-0.1, min(0.1, tilt))

    def prior(dim: str, level: Any) -> tuple[float, float]:
        if dim in ("hook", "structure"):
            return pattern_prior(pb, str(level))
        if dim == "type_weekday":
            return 0.0, float(strength["interaction"])
        means = pol["prior_means"].get(dim, {})
        lvl = (pe.get(dim) or {}).get("level", "opinion")
        n0 = float(strength.get(lvl, strength["opinion"]))
        m = float(means.get(str(level), 0.0))
        if dim == "post_type":
            m += imported.get(str(level), 0.0)
        return m, n0
    return prior


def fit_models(posts: list[dict], pb: dict) -> dict:
    lp = pb["policies"]["learning"]
    s2 = float(lp["noise_sd"]) ** 2
    prior = make_prior(pb)
    obs_a, obs_b = [], []
    for p in posts:
        w = p["judge_weight"] * p["decay"]
        if w <= 0:
            continue
        if p["pooled_score"] is not None and p["post_type"] in FEED_TYPES:
            lv = {"post_type": p["post_type"], "type_weekday": f"{p['post_type']}|{p['weekday']}" if p["weekday"] else None}
            obs_a.append((lv, p["pooled_score"], w))
        if p["score"] is not None:
            lv = {"weekday": p["weekday"], "hour_band": p["hour_band"], "pillar": p["pillar"],
                  "series": p["series"], "hook": hook_key(p["hook"], p["post_type"]) if p["hook"] else None,
                  "structure": p["structure"], "offer_week": p["offer_week"]}
            obs_b.append((lv, p["score"], w))
    a = Additive(DIMS_A, prior, s2).fit(obs_a)
    b = Additive(DIMS_B, prior, s2).fit(obs_b)
    # every tagged pattern of any kind: a simple Normal posterior on the per-type score
    pats: dict[str, dict] = {}
    for pid in pb["patterns"]:
        m0, n0 = pattern_prior(pb, pid)
        keys = [pid, f"{pid}{STATIC_SUFFIX}"] if pb["patterns"][pid]["kind"] == "hook" else [pid]
        for key in keys:
            pats[key] = {"acc": 0.0, "w": 0.0, "n": 0, "m0": m0, "n0": n0, "kind": pb["patterns"][pid]["kind"]}
    for p in posts:
        if p["score"] is None:
            continue
        w = p["judge_weight"] * p["decay"]
        ids = set(p["pattern_ids"]) | {x for x in (p["hook"], p["structure"]) if x}
        for pid in ids:
            key = hook_key(pid, p["post_type"]) if pb["patterns"].get(pid, {}).get("kind") == "hook" else pid
            if key in pats:
                pats[key]["acc"] += w * p["score"]
                pats[key]["w"] += w
                pats[key]["n"] += 1
    pattern_post = {}
    for pid, s in pats.items():
        kind = s["kind"]
        if kind == "hook" and pid in b.post["hook"]:
            mean, var, weff = b.post["hook"][pid]
        elif kind in STRUCTURE_KINDS and pid in b.post["structure"]:
            mean, var, weff = b.post["structure"][pid]
        else:
            mean = (s["n0"] * s["m0"] + s["acc"]) / (s["n0"] + s["w"])
            var, weff = b.sigma2 / (s["n0"] + s["w"]), s["w"]
        sd = math.sqrt(var)
        pattern_post[pid] = {"mean": mean, "var": var, "n": s["n"], "weight": weff, "prob_better": phi(mean / sd) if sd > 0 else 0.5}
    judged = [p for p in posts if p["status"] in ("provisional", "final") and p["score"] is not None]
    n = len(judged)
    lam = min(1.0, n / float(lp["data_led_after_posts"]))
    return {"A": a, "B": b, "patterns": pattern_post, "lambda": lam, "judged": n,
            "final": sum(p["status"] == "final" for p in judged), "provisional": sum(p["status"] == "provisional" for p in judged)}


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
    """Thompson draws for one week: one value per (model, dim, level), drawn in a fixed order."""

    def __init__(self, fits: dict, pb: dict, rng):
        self.fits, self.pb, self.rng = fits, pb, rng
        self.temper = float(pb["policies"]["learning"]["exploit_variance_scale"])
        self.cache: dict[tuple, float] = {}

    def a(self, dim: str, level: str) -> float:
        return self._draw("A", dim, level, self.temper)

    def b(self, dim: str, level: str) -> float:
        return self._draw("B", dim, level, self.temper)

    def _draw(self, model: str, dim: str, level: str, inflate: float) -> float:
        key = (model, dim, level, inflate)
        if key not in self.cache:
            mean, var, _ = self.fits[model].get(dim, level)
            self.cache[key] = float(self.rng.normal(mean, math.sqrt(var * inflate)))
        return self.cache[key]

    def pattern(self, pid: str, inflate: float = 1.0) -> float:
        key = ("P", pid, inflate)
        if key not in self.cache:
            st = self.fits["patterns"].get(pid) or {"mean": 0.0, "var": 0.25}
            self.cache[key] = float(self.rng.normal(st["mean"], math.sqrt(st["var"] * inflate)))
        return self.cache[key]

    def prime(self) -> None:
        """Draw every level used by the planner up front, in sorted order (determinism)."""
        bands = self.pb["policies"]["hour_bands"]["bands"]
        for t in FEED_TYPES:
            self.a("post_type", t)
            for wd in WEEKDAYS:
                self.a("type_weekday", f"{t}|{wd}")
        for wd in WEEKDAYS:
            self.b("weekday", wd)
        for bnd in sorted(bands):
            self.b("hour_band", bnd)
        for w in ("w1", "w2", "w3", "w4", "w5"):
            self.b("offer_week", w)


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
            ds = weeks[wk]
            roles = {d: sc.DEFAULT_WEEK[d.weekday()]["slot"] for d in ds}
            why: dict[date, list[str]] = {d: [] for d in ds}
            if len(ds) == 7 and lam > 0:
                roles, notes = self.assign_days(ds, dr, lam, stick)
                for d, n in notes.items():
                    why[d].append(n)
            for d in ds:
                r = make_row(d, roles[d], self.month)
                r["strategy"] = {"why": why[d], "week": wk.isoformat()}
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

    def assign_days(self, ds: list[date], dr: Draws, lam: float, stick: float) -> tuple[dict, dict]:
        default = {d: sc.DEFAULT_WEEK[d.weekday()]["slot"] for d in ds}
        feed_n = int(self.pol["cadence"]["feed_per_week"]["value"])
        score = {d: lam * dr.b("weekday", WEEKDAYS[d.weekday()]) + (stick if default[d] in ROLE_ORDER else 0.0) for d in ds}
        feed = sorted(sorted(ds, key=lambda d: (-score[d], d))[:feed_n])
        rest = [d for d in ds if d not in feed]
        tscore = {d: lam * dr.b("weekday", WEEKDAYS[d.weekday()]) + (stick if default[d] == "trial_reel" else 0.0) for d in rest}
        trial = sorted(rest, key=lambda d: (-tscore[d], d))[0]
        roles = {d: ROLE_ORDER[i] for i, d in enumerate(feed)}
        roles[trial] = "trial_reel"
        for d in rest:
            if d != trial:
                roles[d] = "stories"
        notes = {}
        for d in ds:
            if roles[d] != default[d]:
                notes[d] = (f"{WEEKDAYS[d.weekday()]} moved from {default[d].replace('_', ' ')} to {roles[d].replace('_', ' ')}: "
                            f"NUMA's {WEEKDAYS[d.weekday()]} posts draw {score[d] - (stick if default[d] in ROLE_ORDER else 0):+.2f} "
                            f"(data-led share {lam:.0%})")
        return roles, notes

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
            s = lam * dr.b("offer_week", week_of_month(d)) + (stick if default_offer else 0.0) + (0.03 if r["date"] in offer_windows else 0.0)
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
                                            + f"; offer-week draw {week_draws[sc.monday_of(d)].b('offer_week', week_of_month(d)):+.2f}")
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
            pillar_mean = {p: self.fits["B"].get("pillar", p)[0] for p in under}
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
        return lam * (dr.a("post_type", t) + dr.a("type_weekday", f"{t}|{wd}")) + (stick if t == default_type(row) else 0.0)

    def assign_types(self, rows: list[dict], week_draws: dict, lam: float, stick: float) -> None:
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
                nonreel = sum(v != "reel" for v in vals)
                if nonreel > max_nonreel or vals.count("carousel") > max_car or vals.count("image") > max_img or vals.count("carousel") < min_car:
                    continue
                current = trial
                changed.add(id(r))
                old = default_type(r)
                set_type(r, t)
                r["strategy"]["why"].append(
                    f"Type {old} -> {t}: NUMA's {t} posts on {r['weekday']}s draw {gain + stick:+.2f} "
                    f"above a {old} here (pooled score vs the feed median; data-led share {lam:.0%}, needs > {stick:.2f})")

    def assign_hours(self, rows: list[dict], week_draws: dict, lam: float) -> None:
        bands = self.pol["hour_bands"]["bands"]
        default = self.pol["hour_bands"]["default"]
        means = self.pol["prior_means"].get("hour_band", {})
        for r in rows:
            dr = week_draws[date.fromisoformat(r["strategy"]["week"])]
            if r["kind"] == "stories" or lam <= 0:
                band = default
                r["strategy"]["why"].append(f"Hour: {band.replace('_', ' ')} ({bands[band]['post_at']} Central), the default"
                                            + (" for Stories" if r["kind"] == "stories" else " until NUMA's own data leads"))
            else:
                sc_b = {b: float(means.get(b, 0.0)) + lam * (dr.b("hour_band", b) - float(means.get(b, 0.0))) for b in sorted(bands)}
                band = max(sorted(sc_b), key=lambda b: (sc_b[b], b == default))
                r["strategy"]["why"].append(f"Hour: {band.replace('_', ' ')} ({bands[band]['post_at']} Central) scored {sc_b[band]:+.2f} "
                                            f"vs {sc_b.get(default, 0):+.2f} for {default.replace('_', ' ')} (data-led share {lam:.0%})")
            r["hour_band"] = band
            r["post_time"] = bands[band]["post_at"]

    # -- patterns ----------------------------------------------------------
    def pattern_slots(self, plan: dict) -> None:
        import numpy as np
        rng = np.random.default_rng(self.seed + 7919)
        rows = plan["rows"]
        budget = float(self.lp["exploration_budget"])
        infl = float(self.lp["explore_variance_inflation"])
        cap = float(self.lp["max_pattern_share_week"])
        hooky = [r for r in rows if r["kind"] in ("reel", "trial_reel", "carousel", "image")]
        n_explore = int(round(budget * len(hooky)))
        explore: list[dict] = [r for r in hooky if r["kind"] == "trial_reel"][:n_explore]
        others = [r for r in hooky if r not in explore and not (r.get("sales") or r.get("event_role") or r.get("signature") or r.get("collab"))]
        order = list(rng.permutation(len(others))) if others else []
        for i in order:
            if len(explore) >= n_explore:
                break
            explore.append(others[int(i)])
        explore_ids = {id(r) for r in explore}
        diag_bonus = self.diagnosis_bonus()
        used_week: dict[str, dict[str, int]] = {}
        week_n: dict[str, int] = {}
        for r in hooky:
            week_n[r["strategy"]["week"]] = week_n.get(r["strategy"]["week"], 0) + 1
        draws = plan["_draws"]
        for r in rows:
            mode = "explore" if id(r) in explore_ids else ("rule" if (r.get("event_role") or r.get("signature") or r.get("sales")
                                                                      or r["kind"] == "stories") else "exploit")
            r["strategy"]["mode"] = mode
            wk = r["strategy"]["week"]
            dr = draws[date.fromisoformat(wk)]
            ptype = KIND_FOR_ROW[r["kind"]]
            goal = self.row_goal(r)
            r["strategy"]["goal"] = goal
            chosen: list[str] = []
            if ptype != "story":
                limit = max(1, int(math.floor(cap * week_n.get(wk, 1) + 1e-9)))
                hook = self.pick(r, dr, "hook", ptype, goal, mode, infl, diag_bonus, used_week.setdefault(wk, {}), limit)
                if hook:
                    used_week[wk][hook] = used_week[wk].get(hook, 0) + 1
                    chosen.append(hook)
                st = self.pick_structure(r, dr, ptype, goal, mode, infl, diag_bonus)
                if st:
                    chosen.append(st)
                    tmpl = self.pb["patterns"][st].get("templates") or []
                    if r["kind"] in ("reel", "trial_reel") and tmpl and not (r.get("event_role") or r.get("signature") or r.get("sales")):
                        r["template"] = tmpl[0]
                kind = "offer" if r.get("sales") else "cta"
                extra = self.pick(r, dr, kind, ptype, goal, mode, infl, diag_bonus, {}, 99)
                if extra:
                    chosen.append(extra)
            r["pattern_ids"] = chosen
            r["strategy"]["hook"] = next((x for x in chosen if self.pb["patterns"][x]["kind"] == "hook"), None)
            r["strategy"]["structure"] = next((x for x in chosen if self.pb["patterns"][x]["kind"] in STRUCTURE_KINDS), None)
            d = date.fromisoformat(r["date"])
            arm = {"type": ptype, "pillar": r.get("pillar"), "series": r.get("series"), "day": r["weekday"],
                   "band": r.get("hour_band"), "hook": r["strategy"]["hook"], "structure": r["strategy"]["structure"],
                   "offer_week": week_of_month(d) if r.get("sales") or r.get("event_role") == "teaser" else None,
                   "goal": goal, "mode": mode, "plan": plan["month"]}
            r["strategy_arm"] = format_arm(arm)
            moms = [m["id"] for m in self.moments if r["date"] in m["dates"] and (m["group"] != "monthly")]
            if moms:
                r["moments"] = moms

    def pkey(self, pid: str, ptype: str) -> str:
        return hook_key(pid, ptype) if self.pb["patterns"][pid]["kind"] == "hook" else pid

    def pstat(self, pid: str, ptype: str) -> dict:
        return self.fits["patterns"].get(self.pkey(pid, ptype)) or {}

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
                    out[(key, pid)] = 0.15
        return out

    def eligible(self, kind_set: tuple[str, ...], ptype: str, mode: str) -> list[dict]:
        fmt = {ptype, "reel"} if ptype == "trial_reel" else {ptype}
        pats = [p for p in self.pb["patterns"].values() if p["kind"] in kind_set and p["status"] != "retired"
                and fmt & set(p["formats"])]
        want = ("testing", "candidate") if mode == "explore" else ("proven", "testing")
        pick = [p for p in pats if p["status"] in want]
        if mode != "explore":
            # exploit what NUMA has data on; untried patterns wait for exploration slots (cold start: all untried)
            tried = [p for p in pick if p["status"] == "proven" or self.pstat(p["id"], ptype).get("n", 0) > 0]
            if len(tried) >= 2:
                pick = tried
        return sorted(pick or pats, key=lambda p: p["id"])

    def fit_bonus(self, p: dict, r: dict, goal: str, diag: dict) -> float:
        b = 0.0
        if p.get("pillars") and r.get("pillar") not in p["pillars"]:
            b -= 0.25
        if p.get("series") and r.get("series") in p["series"]:
            b += 0.15
        if goal not in p["goals"]:
            b -= 0.05
        for m in self.moments:
            if r["date"] in m["dates"] and p["id"] in m.get("hooks", []):
                b += 0.05
        if r.get("event_role") == "teaser" and p["id"] in self.pb["calendar"]["events"].get("teaser_hooks", []):
            b += 0.3
        b += diag.get((r.get("series") or KIND_FOR_ROW[r["kind"]], p["id"]), 0.0)
        if self.pstat(p["id"], KIND_FOR_ROW[r["kind"]]).get("n", 0) == 0 and p.get("priority"):
            b += 0.2 * max(0, 6 - int(p["priority"])) / 5.0   # test-first rank while a pattern has no NUMA data
        return b

    def pick(self, r: dict, dr: Draws, kind: str, ptype: str, goal: str, mode: str, infl: float, diag: dict,
             used: dict, limit: int) -> str | None:
        pats = self.eligible((kind,), ptype, mode)
        if not pats:
            return None
        inflate = infl if mode == "explore" else float(self.lp["exploit_variance_scale"])
        scored = []
        for p in pats:
            if used.get(p["id"], 0) >= limit:
                continue
            s = dr.pattern(self.pkey(p["id"], ptype), inflate) + self.fit_bonus(p, r, goal, diag)
            if mode == "explore":
                n = self.pstat(p["id"], ptype).get("n", 0)
                s += 0.3 / (1 + n)   # explore slots try what NUMA has least data on first
            scored.append((s, p["id"]))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], x[1]))
        best = scored[0][1]
        st = self.pstat(best, ptype)
        r["strategy"]["why"].append(
            f"{kind.capitalize()}: {best} ({self.pb['patterns'][best]['status']}, {st.get('n', 0)} NUMA posts, "
            f"{pct(st.get('mean', 0.0))} than median so far; {mode})")
        return best

    def pick_structure(self, r: dict, dr: Draws, ptype: str, goal: str, mode: str, infl: float, diag: dict) -> str | None:
        fixed = None
        if r.get("event_role") == "teaser":
            fixed = self.pb["calendar"]["events"].get("teaser_structure")
        elif r.get("event_role") == "recap":
            fixed = self.pb["calendar"]["events"].get("recap_structure")
        elif r.get("signature"):
            fixed = "struct-transformation"
        elif r.get("sales"):
            fixed = {"reel": "struct-offer-promo", "carousel": "carousel-first-visit", "image": "struct-offer-promo"}.get(ptype)
        if fixed and fixed in self.pb["patterns"] and self.pb["patterns"][fixed]["status"] != "retired":
            r["strategy"]["why"].append(f"Structure: {fixed} (rule: {r.get('event_role') or ('signature' if r.get('signature') else 'sales')} slot)")
            return fixed
        kinds = {"reel": ("structure",), "trial_reel": ("structure",), "carousel": ("carousel",), "image": ("photo",)}[ptype]
        pats = [p for p in self.eligible(kinds, ptype, mode) if p["id"] != "struct-transformation"
                and not (p["id"].startswith("struct-event") or p["id"] == "struct-offer-promo")]
        if r.get("series"):
            ser = [p for p in pats if r["series"] in (p.get("series") or [])]
            pats = ser or [p for p in pats if not p.get("series")] or pats
        if r.get("pillar"):
            pil = [p for p in pats if not p.get("pillars") or r["pillar"] in p["pillars"]]
            pats = pil or pats
        if not pats:
            return None
        inflate = infl if mode == "explore" else float(self.lp["exploit_variance_scale"])
        scored = sorted(((dr.pattern(p["id"], inflate) + self.fit_bonus(p, r, goal, diag), p["id"]) for p in pats),
                        key=lambda x: (-x[0], x[1]))
        best = scored[0][1]
        st = self.pstat(best, ptype)
        r["strategy"]["why"].append(f"Structure: {best} ({self.pb['patterns'][best]['status']}, {st.get('n', 0)} NUMA posts; {mode})")
        return best


def month_plan(pb: dict, fits: dict, month_text: str, seed: int | None, events: list[dict], closures_file: str | None,
               posts: list[dict], diagnoses: list[dict]) -> tuple[dict, list[dict]]:
    year, month = sc.parse_month(month_text)
    seed = int(seed) if seed is not None else year * 100 + month
    base = {"closures": [], "rows": []}
    closures = sc.closure_dates(base, closures_file)
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
    for r in plan["rows"]:
        r.pop("_protect", None)
    overridden = len(tried) > 1
    plan["strategy"] = {
        "seed": seed, "data_led_share": round(lam, 4), "data_led_share_used": round(tried[-1], 4),
        "judged_posts": fits["judged"], "final_posts": fits["final"], "provisional_posts": fits["provisional"],
        "rules_overrode_bandit": overridden,
        "formula": "data-led share = min(1, judged posts / policies.learning.data_led_after_posts); "
                   "a slot moves when share x (Thompson draw difference) > stickiness",
        "exploration_budget": planner.lp["exploration_budget"],
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
def diagnose_post(p: dict, pb: dict, judged: list[dict]) -> list[dict]:
    pol = pb["policies"]["scoring"]
    pool = baseline_pool(p, judged, int(pol["baseline"]["window_days"]), int(pol["baseline"]["min_posts"]), same_type=True)
    vals = dict(p["values"])
    if isinstance(p.get("length"), (int, float)):
        vals["length"] = float(p["length"])
    if p["score"] is not None:
        vals["score"] = p["score"]
    if "skip_rate" in vals:
        med = median_of([q for q in pool if q["post_type"] in ("reel", "trial_reel")], "skip_rate", p["pull"])
        if med is not None:
            vals["skip_rate_vs_median"] = vals["skip_rate"] - med
    key_of = {"sends_per_1k_reach": "sends_per_1k_reach", "saves_per_1k_reach": "saves_per_1k_reach", "views": "views_or_reach"}
    out = []
    for row in pb["diagnosis"]:
        if p["post_type"] not in row["post_types"]:
            continue
        if row.get("sales_only") and not p["sales"]:
            continue
        ok = True
        for c in row["when"]:
            m = c["metric"]
            v = vals.get(key_of.get(m, m), vals.get(m))
            if v is None:
                ok = False
                break
            if c["ref"] == "value":
                ref = c["x"]
            else:
                med = median_of(pool, key_of.get(m, m), p["pull"])
                if med is None:
                    ok = False
                    break
                ref = med * c["x"] if c["ref"] == "median_ratio" else med + c["x"]
            if not ((v < ref) if c["op"] == "<" else (v > ref)):
                ok = False
                break
        if ok:
            out.append({"id": row["id"], "symptom": row["symptom"], "cause": row["cause"], "fix": row["fix"],
                        "try_patterns": row.get("try_patterns", []), "evidence": row["evidence"]["level"]})
    return out


def recent_diagnoses(posts: list[dict], pb: dict) -> list[dict]:
    """The latest judged post per series (or post type) that underperformed, with its matching diagnosis rows."""
    thr = float(pb["policies"]["learning"]["underperform_score"])
    judged = [p for p in posts if p["status"] in ("provisional", "final")]
    latest: dict[str, dict] = {}
    for p in sorted(judged, key=lambda q: (q["posted"] or datetime.min, q["id"])):
        latest[p["series"] or p["post_type"]] = p
    out = []
    for key in sorted(latest):
        p = latest[key]
        if p["score"] is not None and p["score"] < thr:
            rows = diagnose_post(p, pb, judged)
            if rows:
                out.append({"post": p["id"], "title": p["title"], "post_type": p["post_type"], "series": p["series"],
                            "score": p["score"], "rows": rows})
    return out


# ---------------------------------------------------------------------------
# learn
# ---------------------------------------------------------------------------
DIM_LABEL = {"post_type": "{v} posts", "type_weekday": "{a}s on {b}s", "weekday": "posting on {v}s",
             "hour_band": "posting in the {v}", "pillar": "{v} content", "series": "the {v} series",
             "offer_week": "offers in week {v} of the month", "hook": "the {v} hook", "structure": "the {v} structure"}


def level_text(dim: str, level: str) -> str:
    if dim == "type_weekday":
        a, b = level.split("|")
        return DIM_LABEL[dim].format(a=a.replace("_", " "), b=b)
    v = level.replace("_", " ")
    if dim == "offer_week":
        v = level.lstrip("w")
    return DIM_LABEL[dim].format(v=v)


def insights(fits: dict, pb: dict) -> tuple[list[str], list[str]]:
    th = pb["policies"]["learning"]["insight"]
    more, less = [], []
    for model, dims in (("A", DIMS_A), ("B", DIMS_B)):
        for dim in dims:
            if dim in ("hook", "structure"):
                continue
            for level, (mean, var, w) in sorted(fits[model].post[dim].items()):
                if w < th["min_n"] or level is None:
                    continue
                sd = math.sqrt(var)
                pb_ = phi(mean / sd) if sd > 0 else 0.5
                base = "the feed median" if model == "A" else "NUMA's median"
                if mean >= th["min_effect"] and pb_ >= th["min_prob"]:
                    more.append(f"{level_text(dim, level).capitalize()}: about {pct(mean)} than {base} over {w:.0f} weighted posts.")
                elif mean <= -th["min_effect"] and 1 - pb_ >= th["min_prob"]:
                    less.append(f"{level_text(dim, level).capitalize()}: about {pct(mean)} than {base} over {w:.0f} weighted posts.")
    for pid, st in sorted(fits["patterns"].items()):
        if st["n"] < th["min_n"]:
            continue
        name = pb["patterns"][pid.split("@")[0]]["name"] + (" on carousels and images" if pid.endswith(STATIC_SUFFIX) else "")
        if st["mean"] >= th["min_effect"] and st["prob_better"] >= th["min_prob"]:
            more.append(f"{name} ({pid}): about {pct(st['mean'])} than NUMA's median over {st['n']} posts.")
        elif st["mean"] <= -th["min_effect"] and 1 - st["prob_better"] >= th["min_prob"]:
            less.append(f"{name} ({pid}): about {pct(st['mean'])} than NUMA's median over {st['n']} posts.")
    return more, less


def learn(pb: dict, fits: dict, today: date) -> tuple[dict, list[dict]]:
    st = copy.deepcopy(pb["state"])
    lp = pb["policies"]["learning"]
    pro, ret, dem = lp["promote"], lp["retire"], lp["demote"]
    changes: list[dict] = []
    for pid in sorted(pb["patterns"]):
        p = pb["patterns"][pid]
        s = fits["patterns"].get(status_key(pb, pid))
        if not s or s["n"] == 0:
            continue
        cur, new, why = p["status"], None, None
        n, mean, prob = s["n"], s["mean"], s["prob_better"]
        if cur in ("candidate", "testing") and n >= pro["min_n"] and mean >= pro["min_effect"] and prob >= pro["min_prob"]:
            new, why = "proven", (f"{p['name']} beat NUMA's median by about {pct(mean).split()[0]} over {n} posts "
                                  f"({prob:.0%} likely better); promoted, the plan now uses it in exploit slots.")
        elif cur in ("candidate", "testing", "proven") and n >= ret["min_n"] and mean <= -ret["min_effect"] and 1 - prob >= ret["min_prob"]:
            new, why = "retired", (f"{p['name']} trailed NUMA's median by about {pct(mean).split()[0]} over {n} posts "
                                   f"({1 - prob:.0%} likely worse); retired, it won't be planned again.")
        elif cur == "proven" and n >= dem["min_n"] and prob < dem["min_prob"]:
            new, why = "testing", (f"{p['name']} no longer beats NUMA's median ({prob:.0%} likely better over {n} posts); "
                                   f"back to testing.")
        elif cur == "candidate":
            new, why = "testing", f"{p['name']} was used for the first time ({n} post{'s' if n != 1 else ''}); now testing."
        if new and new != cur:
            st["status_overrides"][pid] = {"status": new, "since": today.isoformat(), "why": why, "n": n,
                                           "mean": round(mean, 4), "prob_better": round(prob, 4)}
            action = {"proven": "promote", "retired": "retire", "testing": "demote" if cur == "proven" else "start_testing"}[new]
            changes.append({"date": today.isoformat(), "action": action, "target": pid, "from": cur, "to": new, "why": why,
                            "n": n, "mean": round(mean, 4), "prob_better": round(prob, 4)})
    more, less = insights(fits, pb)
    st["insights"] = {"date": today.isoformat(), "judged_posts": fits["judged"], "data_led_share": round(fits["lambda"], 4),
                      "do_more": more, "do_less": less}
    st["changelog"] = list(st.get("changelog", [])) + changes
    st["updated"] = today.isoformat()
    return st, changes


def changelog_text(changes: list[dict], st: dict, fits: dict) -> str:
    lines = [f"Strategy update {st['updated']} ({fits['judged']} posts judged: {fits['final']} final, "
             f"{fits['provisional']} provisional; data-led share {fits['lambda']:.0%})"]
    lines.append("What changed:" if changes else "What changed: nothing yet (not enough posts to move any pattern).")
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
    (r"^evidence", "evidence"), (r"^sources?$|^links?$", "sources"), (r"^expected effect|^expected impact", "expected"),
    (r"^when not|^avoid", "when_not"), (r"try instead|if it underperforms|what to do if|^fix", "try_instead"),
    (r"beat|outline|slide-by-slide|slides", "beats"), (r"^length", "length"), (r"^confidence", "confidence"),
    (r"^rule$", "rule"), (r"how to (test|verify|measure)", "how_to_test"), (r"failure", "failure"),
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


def parse_blocks(text: str) -> list[dict]:
    """Heading- or numbered-item-delimited blocks of 'Field: value' lines."""
    blocks: list[dict] = []
    cur: dict | None = None
    section = ""
    last_key = None
    for ln in text.splitlines():
        if ln.strip().startswith("|"):
            continue
        h = re.match(r"^\s*#{1,6}\s+(.*)$", ln)
        item = re.match(r"^\s*(\d+)[.)]\s+\*\*(.+?)\*\*\s*(.*)$", ln)
        if h or item:
            if cur:
                blocks.append(cur)
            title = (h.group(1) if h else item.group(2)).strip().strip("*").strip()
            if h and not re.search(r"[:`]|\b[a-z0-9]+-[a-z0-9]+\b", title) and len(title.split()) > 6:
                section = title
            cur = {"_title": title, "_section": section, "_fields": {}}
            if h:
                section = section if len(title.split()) <= 6 and re.search(r"[a-z]+-[a-z]+", title) else title
            last_key = None
            continue
        if cur is None:
            continue
        m = re.match(r"^\s*[-*•]?\s*\*{0,2}([A-Za-z][\w /(),&'-]{0,48}?)\*{0,2}\s*[:—–]\s*\*{0,2}\s*(.*)$", ln)
        key = field_key(m.group(1)) if m else None
        if m and key:
            val = m.group(2).strip()
            cur["_fields"].setdefault(key, [])
            if val:
                cur["_fields"][key].append(val)
            last_key = key
            continue
        sub = re.match(r"^\s{2,}[-*•]\s+(.*)$|^\s*[-*•]\s+[\"“'](.*)$", ln)
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
    level = next((lv for lv in ("measured", "observed", "opinion") if lv in t), "measured" if "official" in t else "opinion")
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


def kind_for(fname: str, block: dict, forced: str | None) -> str | None:
    if forced:
        return forced
    ctx = f"{block['_section']} {block['_title']}".lower()
    up = Path(fname).name.upper()
    if "carousel" in ctx:
        return "carousel"
    if "photo" in ctx or "single" in ctx or "image" in ctx:
        return "photo"
    if "offer" in ctx and "R4" in up:
        return "offer"
    m = re.match(r"^R(\d)\b", up.replace("_", " ").replace("-", " "))
    n = m.group(1) if m else None
    return {"1": "hook", "3": "structure", "4": "carousel", "5": "growth"}.get(n or "", None)


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
        self.names = {norm_text(p["name"]): pid for pid, p in pb["patterns"].items()}
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
        if not ({"template", "examples"} & set(f)) and "id_name" not in f:
            return
        kind = kind_for(fname, b, self.forced)
        if kind is None:
            self.reject(f"{fname} '{b['_title'][:40]}'", "can't tell the pattern kind (name the file R1..R5 or pass --kind)")
            return
        pid, name = None, None
        if "id_name" in f:
            parts = [x.strip().strip("`*") for x in f["id_name"][0].split(",", 1)]
            pid, name = parts[0], parts[1] if len(parts) > 1 else parts[0]
        pid = pid or (f.get("id") or [None])[0]
        name = name or (f.get("name") or [None])[0] or re.sub(r"^\s*[\d.)]+\s*", "", b["_title"]).strip("`* ")
        name = re.sub(r"^(id\s*[:=]\s*)", "", name or "", flags=re.I).strip() or "Imported pattern"
        title_id = re.search(r"`?\b([a-z0-9]+(?:-[a-z0-9]+)+)\b`?", b["_title"])
        pid = kebab((pid or "").strip("`") or (title_id.group(1) if title_id else "") or name)
        if not pid:
            self.reject(f"{fname} '{b['_title'][:40]}'", "no id or name")
            return
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
        existing = pid if pid in self.ids else self.names.get(norm_text(name))
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
                               "goals": parse_goals(" ".join(f.get("goal", []) + f.get("expected", []))),
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
        self.names[norm_text(name)] = pid
        self.report["added"].append(pid)
        self.log("import", pid, f"New candidate {kind} pattern '{name}' from {fname} ({ev['level']} evidence); "
                 f"it will be tried in exploration slots.")

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
        s = fits["patterns"].get(status_key(pb, pid)) or {"n": 0, "mean": 0.0, "prob_better": 0.5}
        if p["status"] == "retired":
            avoid.append({"id": pid, "kind": p["kind"], "reason": (pb["state"]["status_overrides"].get(pid) or {}).get("why", "Retired.")})
        elif p["status"] == "proven":
            use.append({"id": pid, "kind": p["kind"], "status": "proven",
                        "reason": f"About {pct(s['mean'])} than NUMA's median over {s['n']} posts."})
    planned = sorted({pid for s in slots for pid in s["pattern_ids"]})
    for pid in planned:
        if all(u["id"] != pid for u in use):
            p = pb["patterns"][pid]
            s = fits["patterns"].get(status_key(pb, pid)) or {"n": 0}
            use.append({"id": pid, "kind": p["kind"], "status": p["status"],
                        "reason": f"Planned this week ({p['status']}, {s.get('n', 0)} NUMA posts so far)."})
    experiments = []
    for s in slots:
        if s["mode"] == "explore":
            experiments.append({"date": s["date"], "post_type": s["post_type"], "testing": s["pattern_ids"],
                                "compare_with": "other Trial Reels" if s["post_type"] == "trial_reel" else f"NUMA's {s['post_type']} median",
                                "metric": "skip_rate, sends_per_1k_reach" if s["post_type"] in ("reel", "trial_reel") else "saves_per_1k_reach"})
    prov = [{"id": p["id"], "title": p["title"], "post_type": p["post_type"], "pull": p["pull"], "weight": p["judge_weight"],
             "final_after_hours": (pb["policies"]["judging"].get(p["post_type"]) or {}).get("final_hours")}
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
        reasoning.append(f"{d['title']} underperformed ({pct(d['score'])} than median): {d['rows'][0]['fix']}")
    target = nc.brand_value("positioning.content_mix", {}) or {}
    suggested = {}
    for pil, share in target.items():
        mean, _, w = fits["B"].get("pillar", pil)
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
             "rules_note": "Planning rules (claims, consent, budget, events, closures, one sales post a week) override this brief."}
    return brief


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
