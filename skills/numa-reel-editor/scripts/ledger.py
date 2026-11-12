#!/usr/bin/env python3
"""Higgsfield credit ledger: record every job, enforce the monthly budget (spec p.3, p.43, p.48).

Usage:
    ledger.py add    --ledger PATH --credits N --job TEXT [--category CAT] [--reel SLUG] [--model TEXT]
                     [--outcome kept|failed-refunded|unwanted | --refunded] [--date YYYY-MM-DD] [--force]
    ledger.py check  --ledger PATH [--category CAT --credits N | --job PRICE_ID] [--reel SLUG]
                     [--date YYYY-MM-DD] [--json]
    ledger.py report --ledger PATH [--month YYYY-MM] [--date YYYY-MM-DD] [--balance N] [--json]
    ledger.py sheet  --ledger PATH [--month YYYY-MM]
    ledger.py price  [PRICE_ID] [--json]

`record` is an alias of `add`, `can-spend` an alias of `check`; `--today` an alias of `--date`.

Storage. PATH is either a JSON file (all months in one file) or a folder, in
which case each month lives in its own file `PATH/ledger_YYYY-MM.json`. Each
entry: {n, date, month, category, job, price_id, model, credits, charged, reel,
outcome}. `charged` is what the month really paid: failed-and-refunded jobs are
recorded with charged 0; kept and unwanted jobs are charged in full.

Rules (config/studio.json `budget`, `higgsfield`), checked by `check` against
the proposed spend plus what is already charged this month:

* category split: charged(CAT) + N <= budget.split[CAT].credits
  (600 Kling / 140 Seedance / 160 photo prep / 120 music / 10 voice / 170 reserve);
* monthly total: charged(month) + N <= budget.monthly_credits (1,200);
* per reel: charged(reel, month) + N <= budget.max_credits_per_reel (150), when --reel is given;
* pacing: charged(month) + N <= monthly_credits * f(d), where d is the day of
  the month (1..D, D = days in the month) and, with p = pacing.max_fraction_spent
  (0.55), b = pacing.by_day (15), r = max_credits_per_reel / monthly_credits:

      f(d) = max(p * (d / b) ** 0.6, r)         for d <= b
      f(d) = p + (1 - p) * (d - b) / (D - b)    for d >  b

  The spec fixes only day 15 (55%), so the first half is a concave curve that
  lets the month start faster than a straight line (about 28% by day 5, 43%
  by day 10) and never below one reel's cap (12.5%, so day 1 can make a reel);
  after day 15 a straight line to 100% on the last day.

Credits don't roll over (budget.rollover false): every figure is per calendar
month, so a new month starts from zero. Deterministic: the date comes from
--date (default: today's local date).

`add` runs the same rules on the job being recorded: a job that breaks one is
not recorded (one `ERROR:` per rule, exit 1) unless --force is given (the
credits were already spent), when it is recorded with a `WARN:` per rule.
Refunded failures cost nothing and are always recorded.

Exit codes: check 0 = allowed, 1 = blocked (one `ERROR: blocked: <reason>` line
per broken rule); other commands 0, 1 on bad input, 2 on usage errors.
"""
from __future__ import annotations

import calendar
import csv
import io
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

OUTCOMES = ("kept", "failed-refunded", "unwanted")
LEDGER_SCHEMA_VERSION = 1
# Price id prefix -> budget category (config budget.split keys).
PRICE_CATEGORY = (
    ("kling_", "kling_motion"),
    ("seedance_", "seedance_people_free"),
    ("outpaint", "photo_prep"),
    ("upscale", "photo_prep"),
    ("music", "music"),
    ("voice", "voice"),
)
PACING_EXPONENT = 0.6  # concave start of the month (see module doc)
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def budget() -> dict:
    b = nc.config_value("budget")
    if not isinstance(b, dict) or not isinstance(b.get("split"), dict):
        raise nc.UserError("config/studio.json has no budget.split section")
    return b


def split_credits() -> dict[str, float]:
    return {k: float(v["credits"] if isinstance(v, dict) else v) for k, v in budget()["split"].items()
            if not k.startswith("_")}


def prices() -> list[dict]:
    return [p for p in nc.config_value("higgsfield.prices", []) or [] if isinstance(p, dict) and p.get("id")]


def price(price_id: str) -> dict:
    for p in prices():
        if p["id"] == price_id:
            return p
    known = ", ".join(p["id"] for p in prices())
    raise nc.UserError(f"unknown price id {price_id!r}; known: {known}")


def category_for_price(price_id: str) -> str | None:
    for prefix, cat in PRICE_CATEGORY:
        if price_id.startswith(prefix):
            return cat
    return None


def kling_reel_cost() -> dict:
    """Current Kling-based cost of one reel (R228): typical-max hero clips x (standard draft + pro keeper)."""
    hf = nc.config_value("higgsfield", {}) or {}
    defaults = hf.get("defaults", {}) or {}
    draft_id = (defaults.get("motion_draft") or {}).get("price_id", "kling_std_5s")
    final_id = (defaults.get("motion") or {}).get("price_id", "kling_pro_5s")
    typical = (hf.get("clips_per_reel") or {}).get("typical") or [2, 3]
    clips = int(max(typical)) if isinstance(typical, list) and typical else int(typical)
    per_clip = float(price(draft_id)["credits"]) + float(price(final_id)["credits"])
    return {"clips": clips, "draft": draft_id, "final": final_id, "per_clip": per_clip,
            "per_reel": round(clips * per_clip, 2)}


# ---------------------------------------------------------------------------
# Dates and pacing
# ---------------------------------------------------------------------------
def parse_date(text: str | None) -> date:
    if text is None:
        return date.today()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise nc.UsageError(f"date must be YYYY-MM-DD, got {text!r}") from None


def parse_month(text: str) -> str:
    if not MONTH_RE.match(text or ""):
        raise nc.UsageError(f"month must be YYYY-MM, got {text!r}")
    return text


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def pacing_fraction(d: date) -> float:
    """Highest fraction of the month's credits that may be spent by the end of day d (see module doc)."""
    b = budget()
    pacing = b.get("pacing", {}) or {}
    p = float(pacing.get("max_fraction_spent", 0.55))
    by = int(pacing.get("by_day", 15))
    monthly = float(b.get("monthly_credits", 1200))
    floor = min(1.0, float(b.get("max_credits_per_reel", 150)) / monthly) if monthly else 0.0
    days = calendar.monthrange(d.year, d.month)[1]
    if d.day <= by:
        return max(p * (d.day / by) ** PACING_EXPONENT, floor)
    return min(1.0, p + (1.0 - p) * (d.day - by) / max(1, days - by))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
class Ledger:
    """Entries for one PATH (file holding all months, or a folder of ledger_YYYY-MM.json files)."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.folder_mode = self.path.is_dir() or (not self.path.exists() and self.path.suffix.lower() != ".json")

    def file_for(self, month: str) -> Path:
        return self.path / f"ledger_{month}.json" if self.folder_mode else self.path

    def _read(self, p: Path) -> dict:
        if not p.exists():
            return {"schema_version": LEDGER_SCHEMA_VERSION, "entries": []}
        data = nc.read_json(p, "ledger")
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise nc.UserError(f"ledger {p}: expected an object with an 'entries' list")
        for i, e in enumerate(data["entries"]):
            problem = entry_problem(e)
            if problem:
                raise nc.UserError(f"ledger {p}: entries[{i}]: {problem}")
        return data

    def entries(self, month: str) -> list[dict]:
        return [e for e in self._read(self.file_for(month))["entries"] if e["month"] == month]

    def append(self, entry: dict) -> dict:
        p = self.file_for(entry["month"])
        data = self._read(p)
        entry["n"] = 1 + max([int(e.get("n", 0)) for e in data["entries"]] or [0])
        data["entries"].append(entry)
        data["schema_version"] = LEDGER_SCHEMA_VERSION
        nc.write_json(p, data)
        return entry


def entry_problem(e: Any) -> str | None:
    if not isinstance(e, dict):
        return "not an object"
    for k in ("date", "month", "category", "job", "credits", "charged", "outcome"):
        if k not in e:
            return f"missing '{k}'"
    if e["outcome"] not in OUTCOMES:
        return f"outcome {e['outcome']!r} is not one of {', '.join(OUTCOMES)}"
    for k in ("credits", "charged"):
        if not isinstance(e[k], (int, float)) or isinstance(e[k], bool) or e[k] < 0 or not math.isfinite(e[k]):
            return f"'{k}' must be a number >= 0"
    if not MONTH_RE.match(str(e["month"])) or not str(e["date"]).startswith(e["month"]):
        return f"date {e['date']!r} does not match month {e['month']!r}"
    return None


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def r2(x: float) -> float:
    return round(float(x) + 0.0, 2)


def summary(entries: list[dict], month: str) -> dict:
    split = split_credits()
    b = budget()
    monthly = float(b.get("monthly_credits", 1200))
    used_cat = {k: 0.0 for k in split}
    for e in entries:
        used_cat[e["category"]] = used_cat.get(e["category"], 0.0) + float(e["charged"])
    used = sum(float(e["charged"]) for e in entries)
    cats = {k: {"budget": split.get(k, 0.0), "used": r2(v), "left": r2(split.get(k, 0.0) - v)}
            for k, v in used_cat.items()}
    reels: dict[str, float] = {}
    for e in entries:
        if e.get("reel"):
            reels[e["reel"]] = reels.get(e["reel"], 0.0) + float(e["charged"])
    return {
        "month": month,
        "monthly_credits": monthly,
        "used": r2(used),
        "left": r2(monthly - used),
        "categories": cats,
        "reels": {k: r2(v) for k, v in sorted(reels.items())},
        "jobs": len(entries),
        "refunded_jobs": sum(1 for e in entries if e["outcome"] == "failed-refunded"),
        "unwanted_credits": r2(sum(float(e["charged"]) for e in entries if e["outcome"] == "unwanted")),
    }


def evaluate(entries: list[dict], d: date, category: str | None, credits: float, reel: str | None) -> dict:
    """Would spending `credits` (in `category`, for `reel`) on day d break a rule? Returns the decision."""
    month = month_of(d)
    s = summary(entries, month)
    b = budget()
    monthly = s["monthly_credits"]
    per_reel = float(b.get("max_credits_per_reel", nc.config_value("higgsfield.max_credits_per_reel", 150)))
    frac = pacing_fraction(d)
    pace_cap = r2(monthly * frac)
    reasons: list[str] = []
    if category is not None:
        cat = s["categories"][category]
        if cat["used"] + credits > cat["budget"] + 1e-9:
            reasons.append(f"category {category}: {cat['used']:g} used + {credits:g} > {cat['budget']:g} split")
    if s["used"] + credits > monthly + 1e-9:
        reasons.append(f"month {month}: {s['used']:g} used + {credits:g} > {monthly:g} credits")
    reel_used = s["reels"].get(reel, 0.0) if reel else 0.0
    if reel and reel_used + credits > per_reel + 1e-9:
        reasons.append(f"reel {reel}: {reel_used:g} used + {credits:g} > {per_reel:g} per-reel cap")
    if s["used"] + credits > pace_cap + 1e-9:
        reasons.append(f"pacing: day {d.day}: {s['used']:g} used + {credits:g} > {pace_cap:g} "
                       f"({frac * 100:.1f}% of {monthly:g}); slow down until later in the month")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "date": d.isoformat(),
        "month": month,
        "category": category,
        "credits": r2(credits),
        "reel": reel,
        "reel_used": r2(reel_used),
        "reel_cap": per_reel,
        "pacing_fraction": round(frac, 4),
        "pacing_cap": pace_cap,
        "used": s["used"],
        "left": s["left"],
        "category_left": s["categories"][category]["left"] if category else None,
    }


def report(entries: list[dict], month: str, d: date | None, balance: float | None) -> dict:
    s = summary(entries, month)
    cost = kling_reel_cost()
    left = s["left"] if balance is None else float(balance)
    kling_left = s["categories"].get("kling_motion", {}).get("left", 0.0)
    s["balance"] = r2(left)
    s["balance_source"] = "ledger" if balance is None else "given"
    s["kling_reel_cost"] = cost
    s["reels_covered"] = int(max(0.0, left) // cost["per_reel"]) if cost["per_reel"] else 0
    s["reels_covered_by_kling_split"] = int(max(0.0, kling_left) // cost["per_reel"]) if cost["per_reel"] else 0
    if d is not None and month_of(d) == month:
        frac = pacing_fraction(d)
        cap = r2(s["monthly_credits"] * frac)
        s["pacing"] = {"date": d.isoformat(), "fraction": round(frac, 4), "cap": cap,
                       "on_track": s["used"] <= cap + 1e-9}
    return s


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _common(p) -> None:
    p.add_argument("--ledger", required=True, metavar="PATH", help="ledger JSON file, or a folder of monthly files")


def _date_arg(p) -> None:
    p.add_argument("--date", "--today", dest="date", metavar="YYYY-MM-DD", help="the day (default: today)")


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="ledger.py", description="Higgsfield credit ledger and budget rules (spec p.43).")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    a = sub.add_parser("add", aliases=["record"], help="record one Higgsfield job")
    _common(a)
    a.add_argument("--job", required=True, help="price id from config (e.g. kling_pro_5s) or a description")
    a.add_argument("--credits", type=float, help="credits the job cost (default: the price id's credits)")
    a.add_argument("--category", help="budget category (default: derived from the price id)")
    a.add_argument("--reel", help="reel slug")
    a.add_argument("--model", help="model or tool (default: from the price id)")
    a.add_argument("--outcome", choices=OUTCOMES, help="kept (default), failed-refunded or unwanted")
    a.add_argument("--refunded", action="store_true", help="same as --outcome failed-refunded")
    a.add_argument("--force", action="store_true", help="record even when it breaks a budget rule (already spent)")
    _date_arg(a)
    c = sub.add_parser("check", aliases=["can-spend"], help="may this spend happen? exit 1 when blocked")
    _common(c)
    c.add_argument("--category")
    c.add_argument("--credits", type=float)
    c.add_argument("--job", help="price id: fills --credits and --category from config")
    c.add_argument("--reel")
    _date_arg(c)
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("report", help="used/left per category and reels the balance covers")
    _common(r)
    r.add_argument("--month", help="YYYY-MM (default: the month of --date)")
    _date_arg(r)
    r.add_argument("--balance", type=float, help="actual Higgsfield balance (e.g. from the connector) instead of the ledger's")
    r.add_argument("--json", action="store_true")
    s = sub.add_parser("sheet", help="CSV rows for the plan Sheet mirror")
    _common(s)
    s.add_argument("--month", help="YYYY-MM (default: this month)")
    pr = sub.add_parser("price", help="look up a job's credits in config")
    pr.add_argument("price_id", nargs="?", metavar="PRICE_ID")
    pr.add_argument("--json", action="store_true")
    return ap


def resolve_job(job: str | None, category: str | None, credits: float | None) -> tuple[str | None, float | None, dict | None]:
    known = {p["id"]: p for p in prices()}
    p = known.get(job or "")
    if p is not None:
        if p.get("avoid"):
            raise nc.UserError(f"{p['id']}: {p.get('note') or 'never use this job'}")
        category = category or category_for_price(p["id"])
        credits = float(p["credits"]) if credits is None else credits
    return category, credits, p


def check_category(category: str | None) -> None:
    split = split_credits()
    if category is not None and category not in split:
        raise nc.UsageError(f"unknown category {category!r}; one of: {', '.join(split)}")


def check_credits(credits: float | None) -> None:
    if credits is not None and (not math.isfinite(credits) or credits < 0):
        raise nc.UsageError(f"--credits must be a number >= 0, got {credits:g}")


def print_report(rep: dict) -> None:
    print(f"Higgsfield credits {rep['month']}: {rep['used']:g} used, {rep['left']:g} left of {rep['monthly_credits']:g}")
    for k, c in rep["categories"].items():
        print(f"  {k:<22} {c['used']:>7g} used  {c['left']:>7g} left of {c['budget']:g}")
    cost = rep["kling_reel_cost"]
    print(f"Balance {rep['balance']:g} covers {rep['reels_covered']} reels at {cost['per_reel']:g} credits/reel "
          f"({cost['clips']} Kling clips x {cost['per_clip']:g}: {cost['draft']} draft + {cost['final']} keeper)")
    if "pacing" in rep:
        pc = rep["pacing"]
        state = "on track" if pc["on_track"] else "AHEAD of pace: slow down"
        print(f"Pacing {pc['date']}: cap {pc['cap']:g} ({pc['fraction'] * 100:.1f}%), {state}")


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: add, check, report, sheet or price")
    cmd = {"record": "add", "can-spend": "check"}.get(args.cmd, args.cmd)

    if cmd == "price":
        items = [price(args.price_id)] if args.price_id else prices()
        if args.json:
            nc.print_json(items[0] if args.price_id else items)
        else:
            for p in items:
                flag = "  (avoid)" if p.get("avoid") else ""
                print(f"{p['id']:<20} {float(p['credits']):>7g} credits  {p.get('model') or p.get('tool')}: {p['job']}{flag}")
        return 0

    led = Ledger(args.ledger)
    if cmd == "add":
        if args.refunded and args.outcome and args.outcome != "failed-refunded":
            raise nc.UsageError("--refunded contradicts --outcome")
        category, credits, p = resolve_job(args.job, args.category, args.credits)
        if credits is None:
            raise nc.UsageError("--credits is required when --job is not a known price id")
        if category is None:
            raise nc.UsageError("--category is required when --job is not a known price id")
        check_category(category)
        check_credits(credits)
        d = parse_date(args.date)
        outcome = "failed-refunded" if args.refunded else (args.outcome or "kept")
        entry = {
            "date": d.isoformat(), "month": month_of(d), "category": category, "job": args.job,
            "price_id": p["id"] if p else None, "model": args.model or (p.get("model") or p.get("tool") if p else None),
            "credits": r2(credits), "charged": 0.0 if outcome == "failed-refunded" else r2(credits),
            "reel": args.reel, "outcome": outcome,
        }
        if entry["charged"] > 0:
            res = evaluate(led.entries(entry["month"]), d, category, entry["charged"], args.reel)
            for reason in res["reasons"]:
                (nc.warn if args.force else nc.error_line)(f"over budget: {reason}")
            if res["reasons"] and not args.force:
                nc.error_line("not recorded: re-run with --force if the credits were already spent")
                return 1
        led.append(entry)
        s = summary(led.entries(entry["month"]), entry["month"])
        print(f"Recorded #{entry['n']} {entry['job']} {credits:g} credits ({outcome}) in {category}; "
              f"{s['used']:g} used, {s['left']:g} left this month")
        return 0

    if cmd == "check":
        category, credits, _ = resolve_job(args.job, args.category, args.credits)
        if (category is None) != (credits is None):
            raise nc.UsageError("check needs both --category and --credits (or a price id in --job)")
        check_category(category)
        check_credits(credits)
        d = parse_date(args.date)
        res = evaluate(led.entries(month_of(d)), d, category, credits or 0.0, args.reel)
        if args.json:
            nc.print_json(res)
        else:
            what = f"{res['credits']:g} credits in {category}" if category else "current spending"
            if res["allowed"]:
                print(f"OK: {what} allowed on {res['date']} ({res['used']:g} used, pacing cap {res['pacing_cap']:g})")
            else:
                print(f"BLOCKED: {what} on {res['date']}")
        for reason in res["reasons"]:
            nc.error_line(f"blocked: {reason}")
        return 0 if res["allowed"] else 1

    if cmd == "report":
        d = parse_date(args.date)
        month = parse_month(args.month) if args.month else month_of(d)
        if args.balance is not None:
            check_credits(args.balance)
        rep = report(led.entries(month), month, d, args.balance)
        if args.json:
            nc.print_json(rep)
        else:
            print_report(rep)
        return 0

    if cmd == "sheet":
        month = parse_month(args.month) if args.month else month_of(date.today())
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["#", "Date", "Category", "Job", "Model", "Credits", "Charged", "Reel", "Outcome", "Month used"])
        running = 0.0
        for e in led.entries(month):
            running += float(e["charged"])
            w.writerow([e.get("n", ""), e["date"], e["category"], e["job"], e.get("model") or "",
                        f"{float(e['credits']):g}", f"{float(e['charged']):g}", e.get("reel") or "",
                        e["outcome"], f"{r2(running):g}"])
        sys.stdout.write(buf.getvalue())
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
