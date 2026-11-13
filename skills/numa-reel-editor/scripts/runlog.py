#!/usr/bin/env python3
"""Run log and watchdog for the scheduled tasks (R340, R341, R343).

Usage:
    runlog.py start  TASK [--state DIR] [--now ISO] [--json]
    runlog.py finish [RUN_ID] [--task TASK] --outcome ok|failed|partial [--note TEXT]
                     [--state DIR] [--now ISO] [--json]
    runlog.py check  [--state DIR] [--now ISO] [--days N] [--post-by HH:MM]
                     [--since ISO [--tasks a,b]] [--mark-reported] [--json]
    runlog.py summary --week [--state DIR] [--now ISO] [--json]
    runlog.py merge  FILE [--state DIR] [--json]

Every scheduled command (and /make-reel, /chrome-queue) records its start and
finish in `STATE/runlog.json`, which is synced to Drive `_Plan/` so the next
cloud run (a fresh machine) sees it. `STATE` is `--state DIR`, else
$NUMA_STATE, else `~/NUMA Studio/_Plan`.

    {"schema_version": 1,
     "created_at": "2026-11-01T02:00:05Z",
     "runs": [{"id": "build_today-20261113T110002Z-3f9a", "task": "build_today",
               "started_at": "2026-11-13T11:00:02Z", "finished_at": "2026-11-13T11:14:40Z",
               "outcome": "ok", "note": ""}],
     "reported": ["missed:build_today:2026-11-10T05:00:00-06:00"]}

`start` prints the run id. `finish` closes that run (or, with `--task`, the
newest open run of the task when the id was lost); a run that hit an error
still finishes, with `--outcome failed`.

`check` is the watchdog. It reads the schedule from config/studio.json
(`schedule.timezone`, the 5-field cron of every task in `schedule.tasks` and of
the non-desktop tasks in `schedule.extra_tasks`) and settings from
`schedule.runlog` (defaults below), evaluates each cron in the schedule's
timezone with zoneinfo (so daylight-saving changes are handled), and reports
over the last `--days` (7):

* missed  - a scheduled time (after the log's `created_at`, so a new install
            is not flagged) with no run started in its slot (from 15 minutes
            before it up to the next scheduled time), once `grace_minutes`
            have passed;
* failed  - the slot's runs all ended `failed` (a later ok re-run clears it);
* stuck   - a run still open after `stuck_after_minutes`;
* partial - listed under `notes`, not a problem.

Each problem has an `action`: `late_build` (build_today, when a build started
now still finishes `late_build_minutes` before the posting window ends,
`post_by` or `--post-by`, the same day), `reschedule` (build_today otherwise),
`rerun` (other tasks within `rerun_within_hours` of the slot) or `skip` (the
next run catches up). `new` is false for problems an earlier
`check --mark-reported` already returned, so Jude gets each line once.

`check --since ISO` is the setup verification (R343): for every task (or
`--tasks`), did a run start after ISO and finish ok? `healthy` is false
until every one did.

`summary --week` gives the digest's run-health numbers and one plain line.
`merge FILE` folds another copy of the log (the Drive copy) into the local one
(union by run id; a finished record wins over an open one), so two machines
that ran at the same time lose nothing. Writes are atomic and serialized with
a lock file next to the log. Exit 0 on success (problems are data, not
errors), 1 on bad input, 2 on usage errors.
"""
from __future__ import annotations

import bisect
import contextlib
import hashlib
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

RUNLOG_SCHEMA_VERSION = 1
LOG_NAME = "runlog.json"
OUTCOMES = ("ok", "failed", "partial")
MAX_REPORTED = 500
TASK_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

DEFAULTS: dict[str, Any] = {
    "window_days": 7,
    "grace_minutes": 60,
    "early_minutes": 15,
    "stuck_after_minutes": {"default": 120, "build_today": 180, "plan_month": 240},
    "post_by": "18:00",
    "late_build_minutes": 60,
    "rerun_within_hours": {"plan_month": 144, "night_check": 8, "digest": 18, "trend_check": 48,
                           "dashboard_refresh": 0},
}


# ---------------------------------------------------------------------------
# State folder, lock, load/save
# ---------------------------------------------------------------------------
def state_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    env = os.environ.get("NUMA_STATE")
    if env:
        return Path(env).expanduser()
    return Path.home() / "NUMA Studio" / "_Plan"


@contextlib.contextmanager
def locked(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Exclusive lock on `<path>.lock` (fcntl on macOS/Linux, msvcrt on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    fh = open(lock_path, "a+")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise nc.UserError(f"{path.name} is locked by another run for over {int(timeout)} s; "
                                       f"if no run is active, delete {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def _empty() -> dict:
    return {"schema_version": RUNLOG_SCHEMA_VERSION, "created_at": None, "runs": [], "reported": []}


def load_log(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return _empty()
    data = nc.read_json(path, "run log")
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        raise nc.UserError(f"{path} is not a run log (expected {{\"runs\": [...]}}); move it aside and run again")
    data.setdefault("schema_version", RUNLOG_SCHEMA_VERSION)
    data.setdefault("created_at", None)
    data.setdefault("reported", [])
    for r in data["runs"]:
        if not isinstance(r, dict) or not r.get("id") or not r.get("task") or not r.get("started_at"):
            raise nc.UserError(f"{path}: every run needs id, task and started_at")
    return data


def save_log(path: Path, data: dict) -> None:
    if not data.get("created_at") and data["runs"]:
        data["created_at"] = min(r["started_at"] for r in data["runs"])
    data["runs"].sort(key=lambda r: (r["started_at"], r["id"]))
    data["reported"] = data.get("reported", [])[-MAX_REPORTED:]
    nc.write_json(path, data)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise nc.UserError(f"unknown timezone {name!r} in config schedule.timezone "
                           "(pip install tzdata if this system has no zone database)") from None


def parse_when(text: str, tz: ZoneInfo, what: str = "time") -> datetime:
    """ISO 8601 date-time; 'Z' accepted; a naive value is read in `tz` (the schedule's timezone)."""
    s = str(text).strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(s), datetime.min.time())
        except ValueError:
            raise nc.UserError(f"{what} {text!r} is not an ISO 8601 date-time "
                               "(e.g. 2026-11-13T05:00:00-06:00)") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_iso(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).replace(microsecond=0).isoformat()


def now_arg(text: str | None, tz: ZoneInfo) -> datetime:
    return parse_when(text, tz, "--now") if text else datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 5-field cron evaluator (minute hour day-of-month month day-of-week)
# ---------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DAYS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}


def _field(text: str, lo: int, hi: int, names: dict[str, int] | None, what: str) -> tuple[set[int], bool]:
    """Values of one cron field and whether it was restricted (not '*')."""
    out: set[int] = set()
    restricted = not text.strip().startswith("*")  # cron's rule: a field starting with '*' is unrestricted
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.isdigit() or int(s) < 1:
                raise nc.UserError(f"cron {what} step {s!r} is not a positive number")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        else:
            a_s, dash, b_s = part.partition("-")
            a = _value(a_s, names, what)
            b = _value(b_s, names, what) if dash else (hi if step > 1 else a)
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise nc.UserError(f"cron {what} {text!r} is outside {lo}-{hi}")
        out.update(range(a, b + 1, step))
    return out, restricted


def _value(s: str, names: dict[str, int] | None, what: str) -> int:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    if names and s[:3] in names:
        return names[s[:3]]
    raise nc.UserError(f"cron {what} value {s!r} is not a number")


class Cron:
    """A standard 5-field cron line. Day-of-month and day-of-week follow cron's rule:
    when both are restricted, a day matches either one."""

    def __init__(self, line: str):
        parts = str(line).split()
        if len(parts) != 5:
            raise nc.UserError(f"cron {line!r} must have 5 fields (minute hour day month weekday)")
        self.line = " ".join(parts)
        self.minutes, _ = _field(parts[0], 0, 59, None, "minute")
        self.hours, _ = _field(parts[1], 0, 23, None, "hour")
        self.doms, self.dom_r = _field(parts[2], 1, 31, None, "day-of-month")
        self.months, _ = _field(parts[3], 1, 12, _MONTHS, "month")
        dows, self.dow_r = _field(parts[4], 0, 7, _DAYS, "day-of-week")
        self.dows = {d % 7 for d in dows}  # 7 = Sunday

    def day_matches(self, d: date) -> bool:
        if d.month not in self.months:
            return False
        dom_ok = d.day in self.doms
        dow_ok = (d.isoweekday() % 7) in self.dows
        if self.dom_r and self.dow_r:
            return dom_ok or dow_ok
        if self.dom_r:
            return dom_ok
        if self.dow_r:
            return dow_ok
        return True

    def fires(self, start: datetime, end: datetime, tz: ZoneInfo) -> list[datetime]:
        """Every fire time in [start, end), as aware datetimes in `tz`.

        Wall-clock times are mapped through zoneinfo: a time skipped by the
        spring-forward change fires just after it (02:30 -> 03:30 CDT); a time
        repeated by the fall-back change fires once (the first occurrence).
        """
        out: list[datetime] = []
        d = start.astimezone(tz).date() - timedelta(days=1)
        last = end.astimezone(tz).date() + timedelta(days=1)
        seen: set[datetime] = set()
        while d <= last:
            if self.day_matches(d):
                for h in sorted(self.hours):
                    for m in sorted(self.minutes):
                        local = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)  # fold=0
                        real = local.astimezone(timezone.utc)
                        if real in seen:
                            continue
                        seen.add(real)
                        if start <= real < end:
                            out.append(real.astimezone(tz))
            d += timedelta(days=1)
        out.sort()
        return out


# ---------------------------------------------------------------------------
# Schedule from config
# ---------------------------------------------------------------------------
def settings(cfg: dict) -> dict:
    user = nc.dig(cfg, "schedule.runlog") or {}
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in user.items():
        if k.startswith("_"):
            continue
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def scheduled_tasks(cfg: dict, include_desktop: bool = False) -> list[dict]:
    """Tasks with a cron: `schedule.tasks` plus `schedule.extra_tasks` (desktop-only ones on request)."""
    tasks = []
    for t in (nc.dig(cfg, "schedule.tasks") or []) + (nc.dig(cfg, "schedule.extra_tasks") or []):
        if not isinstance(t, dict) or not t.get("id") or not t.get("cron"):
            raise nc.UserError("config schedule: every task needs an id and a cron line")
        if t.get("where") == "desktop" and not include_desktop:
            continue
        tasks.append({**t, "_cron": Cron(t["cron"])})
    return tasks


def _post_by(text: str, what: str) -> tuple[int, int]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(text).strip())
    if not m:
        raise nc.UserError(f"{what} {text!r} must be HH:MM (24-hour, Central)")
    return int(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def _run_times(r: dict, tz: ZoneInfo) -> tuple[datetime, datetime | None]:
    start = parse_when(r["started_at"], tz, f"run {r['id']} started_at")
    end = parse_when(r["finished_at"], tz, f"run {r['id']} finished_at") if r.get("finished_at") else None
    return start, end


def _stuck_after(task: str, st: dict) -> float:
    s = st["stuck_after_minutes"]
    return float(s.get(task, s.get("default", 120))) if isinstance(s, dict) else float(s)


def analyze(log: dict, cfg: dict, now: datetime, days: int | None = None, post_by: str | None = None) -> dict:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    st = settings(cfg)
    days = int(days if days is not None else st["window_days"])
    if days < 1:
        raise nc.UserError("--days must be at least 1")
    pb_h, pb_m = _post_by(post_by or st["post_by"], "--post-by" if post_by else "schedule.runlog.post_by")
    grace = timedelta(minutes=float(st["grace_minutes"]))
    early = timedelta(minutes=float(st["early_minutes"]))
    win_start = now - timedelta(days=days)
    log_start = parse_when(log["created_at"], tz, "created_at") - early if log.get("created_at") else None
    now_local = now.astimezone(tz)

    runs = []
    for r in log["runs"]:
        start, end = _run_times(r, tz)
        runs.append((r, start, end))

    problems: list[dict] = []
    notes: list[dict] = []
    stats: dict[str, dict] = {}

    def run_state(r: dict, start: datetime) -> str:
        if r.get("outcome") in OUTCOMES:
            return r["outcome"]
        if (now - start) > timedelta(minutes=_stuck_after(r["task"], st)):
            return "stuck"
        return "running"

    def action_for(task: str, slot: datetime) -> str:
        if task == "build_today":
            slot_day = slot.astimezone(tz).date()
            if slot_day == now_local.date():
                deadline = datetime(slot_day.year, slot_day.month, slot_day.day, pb_h, pb_m, tzinfo=tz)
                if now + timedelta(minutes=float(st["late_build_minutes"])) <= deadline:
                    return "late_build"
            return "reschedule"
        hours = float((st["rerun_within_hours"] or {}).get(task, 0))
        return "rerun" if now < slot + timedelta(hours=hours) else "skip"

    scheduled = scheduled_tasks(cfg)
    covered_ids: set[str] = set()
    for t in scheduled:
        task = t["id"]
        fires = t["_cron"].fires(win_start - timedelta(days=40), now + timedelta(days=1), tz)
        utc_fires = [f.astimezone(timezone.utc) for f in fires]
        slots: dict[int, list[tuple[dict, datetime]]] = {}
        for r, start, _end in runs:
            if r["task"] != task:
                continue
            i = bisect.bisect_right(utc_fires, start + early) - 1
            if i >= 0:
                slots.setdefault(i, []).append((r, start))
        s = stats.setdefault(task, {"expected": 0, "ok": 0, "partial": 0, "failed": 0, "missed": 0,
                                    "stuck": 0, "running": 0, "name": t.get("name", task)})
        for i, fire in enumerate(utc_fires):
            if fire < win_start or fire > now or (log_start is None or fire < log_start):
                continue  # outside the window, or before the log existed (a new install is not a miss)
            got = slots.get(i, [])
            if not got and now < fire + grace:
                continue  # not due yet
            s["expected"] += 1
            slot_txt = local_iso(fire, tz)
            if not got:
                s["missed"] += 1
                problems.append({"kind": "missed", "task": task, "slot": slot_txt,
                                 "date": fire.astimezone(tz).date().isoformat(),
                                 "action": action_for(task, fire)})
                continue
            covered_ids.update(r["id"] for r, _ in got)
            states = [(run_state(r, start), r, start) for r, start in got]
            kinds = [k for k, _, _ in states]
            if "ok" in kinds:
                s["ok"] += 1
            elif "partial" in kinds:
                s["partial"] += 1
                r = next(r for k, r, _ in states if k == "partial")
                notes.append({"kind": "partial", "task": task, "slot": slot_txt, "run_id": r["id"],
                              "note": r.get("note", "")})
            elif "running" in kinds:
                s["running"] += 1
            else:
                kind = "stuck" if "stuck" in kinds else "failed"
                s[kind] += 1
                k, r, start = next(x for x in reversed(states) if x[0] == kind)
                p = {"kind": kind, "task": task, "slot": slot_txt,
                     "date": fire.astimezone(tz).date().isoformat(), "run_id": r["id"],
                     "started_at": local_iso(start, tz), "action": action_for(task, fire)}
                if kind == "failed":
                    p["note"] = r.get("note", "")
                else:
                    p["minutes"] = int((now - start).total_seconds() // 60)
                problems.append(p)

    # Runs outside the schedule (make_reel, a desktop chrome_queue, a task not in config): failures and stuck runs.
    for r, start, _end in runs:
        if r["id"] in covered_ids or start < win_start or start > now:
            continue
        if any(t["id"] == r["task"] for t in scheduled):
            continue
        k = run_state(r, start)
        if k in ("failed", "stuck"):
            p = {"kind": k, "task": r["task"], "slot": None, "date": start.astimezone(tz).date().isoformat(),
                 "run_id": r["id"], "started_at": local_iso(start, tz), "action": "skip"}
            if k == "failed":
                p["note"] = r.get("note", "")
            else:
                p["minutes"] = int((now - start).total_seconds() // 60)
            problems.append(p)
        elif k == "partial":
            notes.append({"kind": "partial", "task": r["task"], "slot": None, "run_id": r["id"],
                          "note": r.get("note", "")})

    for p in problems:
        p["key"] = f"{p['kind']}:{p['task']}:{p['slot'] or p['run_id']}"
        p["new"] = p["key"] not in set(log.get("reported", []))
    problems.sort(key=lambda p: (p["slot"] or p["started_at"], p["task"]))
    return {"now": local_iso(now, tz), "timezone": str(tz.key), "window_days": days,
            "healthy": not problems, "problems": problems, "notes": notes, "tasks": stats}


def verify(log: dict, cfg: dict, since: datetime, tasks: list[str] | None, now: datetime) -> dict:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    wanted = tasks or [t["id"] for t in scheduled_tasks(cfg, include_desktop=True)]
    out = {}
    for task in wanted:
        runs = [r for r in log["runs"] if r["task"] == task and since <= _run_times(r, tz)[0] <= now]
        if not runs:
            out[task] = {"status": "not run", "run_id": None}
            continue
        best = next((r for r in runs if r.get("outcome") == "ok"), None) or runs[-1]
        out[task] = {"status": best.get("outcome") or "running", "run_id": best["id"], "note": best.get("note", "")}
    return {"since": local_iso(since, tz), "healthy": all(v["status"] == "ok" for v in out.values()),
            "verify": out}


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------
_LABEL = {"missed": "MISSED", "failed": "FAILED", "stuck": "STUCK"}


def _fmt_slot(iso: str | None) -> str:
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%a %b ") + str(dt.day) + dt.strftime(" %H:%M")


def problem_line(p: dict) -> str:
    when = _fmt_slot(p.get("slot") or p.get("started_at"))
    extra = ""
    if p["kind"] == "failed" and p.get("note"):
        extra = f" ({p['note']})"
    if p["kind"] == "stuck":
        extra = f" (open {p['minutes']} min)"
    return f"{_LABEL[p['kind']]}: {p['task']} {when}{extra} -> {p['action']}"


def health_line(res: dict) -> str:
    stats = res["tasks"]
    expected = sum(s["expected"] for s in stats.values())
    ok = sum(s["ok"] + s["partial"] for s in stats.values())
    if not expected:
        return f"Run health, last {res['window_days']} days: no scheduled runs were due."
    names = {task: s.get("name", task) for task, s in stats.items()}
    bad = [f"{names.get(p['task'], p['task'])} {p['kind']} {_fmt_slot(p.get('slot') or p.get('started_at'))}"
           for p in res["problems"]]
    if len(bad) > 6:
        bad = bad[:6] + [f"and {len(bad) - 6} more"]
    tail = f"; not ok: {'; '.join(bad)}." if bad else "."
    return f"Run health, last {res['window_days']} days: {ok} of {expected} scheduled runs finished{tail}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _new_id(task: str, now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = hashlib.sha1(f"{task}|{now.isoformat()}|{os.getpid()}|{time.perf_counter_ns()}".encode()).hexdigest()[:4]
    return f"{task}-{stamp}-{salt}"


def cmd_start(args, cfg) -> int:
    if not TASK_RE.match(args.task):
        raise nc.UsageError(f"task {args.task!r} must be a snake_case id such as build_today")
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / LOG_NAME
    with locked(path):
        log = load_log(path)
        rid = _new_id(args.task, now)
        while any(r["id"] == rid for r in log["runs"]):
            rid = _new_id(args.task, now)
        log["runs"].append({"id": rid, "task": args.task, "started_at": utc_iso(now), "finished_at": None,
                            "outcome": None, "note": ""})
        save_log(path, log)
    if args.json:
        nc.print_json({"run_id": rid, "task": args.task, "started_at": local_iso(now, tz), "log": str(path)})
    else:
        print(rid)
    return 0


def cmd_finish(args, cfg) -> int:
    if not args.run_id and not args.task:
        raise nc.UsageError("give the RUN_ID that start printed, or --task TASK for its newest open run")
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / LOG_NAME
    with locked(path):
        log = load_log(path)
        if args.run_id:
            run = next((r for r in log["runs"] if r["id"] == args.run_id), None)
            if run is None:
                raise nc.UserError(f"no run {args.run_id} in {path} (sync runlog.json from Drive first, "
                                   "or finish with --task TASK)")
        else:
            open_runs = [r for r in log["runs"] if r["task"] == args.task and not r.get("finished_at")]
            if not open_runs:
                raise nc.UserError(f"no open {args.task} run in {path}")
            run = max(open_runs, key=lambda r: r["started_at"])
        run["finished_at"] = utc_iso(now)
        run["outcome"] = args.outcome
        run["note"] = " ".join((args.note or "").split())[:300]
        save_log(path, log)
    if args.json:
        nc.print_json({"run_id": run["id"], "task": run["task"], "outcome": run["outcome"],
                       "finished_at": local_iso(now, tz)})
    else:
        print(f"{run['id']}: {run['outcome']}")
    return 0


def cmd_check(args, cfg) -> int:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / LOG_NAME
    if args.since:
        tasks = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
        res = verify(load_log(path), cfg, parse_when(args.since, tz, "--since"), tasks, now)
        if args.json:
            nc.print_json(res)
        else:
            for task, v in res["verify"].items():
                print(f"{'OK' if v['status'] == 'ok' else 'NOT OK'}: {task} ({v['status']})")
            print("all tasks recorded ok" if res["healthy"] else "some tasks have no ok run since " + res["since"])
        return 0
    if args.tasks:
        raise nc.UsageError("--tasks goes with --since")
    with locked(path):
        log = load_log(path)
        res = analyze(log, cfg, now, args.days, args.post_by)
        if args.mark_reported and res["problems"]:
            known = log.setdefault("reported", [])
            known.extend(p["key"] for p in res["problems"] if p["new"])
            save_log(path, log)
    if args.json:
        nc.print_json(res)
    else:
        for p in res["problems"]:
            print(problem_line(p) + ("" if p["new"] else " (reported before)"))
        for n in res["notes"]:
            print(f"PARTIAL: {n['task']} {_fmt_slot(n['slot'])} {n['note']}".rstrip())
        print(health_line(res))
    return 0


def cmd_summary(args, cfg) -> int:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    now = now_arg(args.now, tz)
    res = analyze(load_log(state_dir(args.state) / LOG_NAME), cfg, now, 7)
    line = health_line(res)
    if args.json:
        nc.print_json({"now": res["now"], "line": line, "tasks": res["tasks"], "problems": res["problems"],
                       "notes": res["notes"], "healthy": res["healthy"]})
    else:
        print(line)
        for task, s in res["tasks"].items():
            print(f"- {s['name']}: {s['ok'] + s['partial']} of {s['expected']} ok"
                  + "".join(f", {s[k]} {k}" for k in ("missed", "failed", "stuck") if s[k]))
    return 0


def merge_logs(mine: dict, other: dict) -> dict:
    by_id = {r["id"]: r for r in mine["runs"]}
    for r in other.get("runs", []):
        if not isinstance(r, dict) or not r.get("id") or not r.get("task") or not r.get("started_at"):
            continue
        cur = by_id.get(r["id"])
        if cur is None or (not cur.get("finished_at") and r.get("finished_at")):
            by_id[r["id"]] = dict(r)
    mine["runs"] = list(by_id.values())
    seen = list(mine.get("reported", []))
    seen += [k for k in other.get("reported", []) if k not in seen]
    mine["reported"] = seen
    stamps = [x for x in (mine.get("created_at"), other.get("created_at")) if x]
    mine["created_at"] = min(stamps) if stamps else None
    return mine


def cmd_merge(args, cfg) -> int:
    other_path = Path(args.file).expanduser()
    if not other_path.exists():
        raise nc.UserError(f"no file {other_path} to merge (a first run has no Drive copy yet: skip the merge)")
    other = load_log(other_path)
    path = state_dir(args.state) / LOG_NAME
    with locked(path):
        log = load_log(path)
        before = len(log["runs"])
        merge_logs(log, other)
        save_log(path, log)
    msg = {"log": str(path), "runs": len(log["runs"]), "added": len(log["runs"]) - before}
    if args.json:
        nc.print_json(msg)
    else:
        print(f"merged {other_path.name}: {msg['added']} new run(s), {msg['runs']} in total")
    return 0


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="runlog.py", description="Run log and watchdog for the scheduled tasks.")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=nc.ArgParser)

    def common(p, now=True):
        p.add_argument("--state", help="STATE folder holding runlog.json (default $NUMA_STATE or ~/NUMA Studio/_Plan)")
        if now:
            p.add_argument("--now", help="ISO time to use instead of the clock (tests, replays)")
        p.add_argument("--json", action="store_true", help="print one JSON report")

    s = sub.add_parser("start", help="record a run's start and print its id")
    s.add_argument("task", help="task id, e.g. build_today (config schedule.tasks id) or make_reel")
    common(s)
    f = sub.add_parser("finish", help="record a run's end and outcome")
    f.add_argument("run_id", nargs="?", help="the id start printed")
    f.add_argument("--task", help="finish the newest open run of this task (when the id was lost)")
    f.add_argument("--outcome", required=True, choices=OUTCOMES)
    f.add_argument("--note", help="one short line: what failed or was left out")
    common(f)
    c = sub.add_parser("check", help="missed, failed and stuck runs over the last days (the watchdog)")
    c.add_argument("--days", type=int, help="window in days (default schedule.runlog.window_days, 7)")
    c.add_argument("--post-by", help="HH:MM Central the day's post must go out by (default schedule.runlog.post_by)")
    c.add_argument("--since", help="setup verification: did every task finish ok after this ISO time?")
    c.add_argument("--tasks", help="with --since: comma-separated task ids (default every scheduled task)")
    c.add_argument("--mark-reported", action="store_true", help="remember these problems so later checks mark them new=false")
    common(c)
    m = sub.add_parser("summary", help="run health for the digest")
    m.add_argument("--week", action="store_true", required=True, help="the last 7 days")
    common(m)
    g = sub.add_parser("merge", help="fold another copy of runlog.json (the Drive copy) into the local log")
    g.add_argument("file")
    common(g, now=False)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = nc.load_config()
    return {"start": cmd_start, "finish": cmd_finish, "check": cmd_check, "summary": cmd_summary,
            "merge": cmd_merge}[args.cmd](args, cfg)


if __name__ == "__main__":
    nc.run_cli(main)
