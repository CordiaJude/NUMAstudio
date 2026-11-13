#!/usr/bin/env python3
"""Run log and watchdog for the scheduled tasks (R340, R341, R343).

Usage:
    runlog.py start  TASK [--late] [--state DIR] [--now ISO] [--json]
    runlog.py finish [RUN_ID] [--task TASK] --outcome ok|failed|partial [--note TEXT] [--rescheduled]
                     [--state DIR] [--now ISO] [--json]
    runlog.py check  [--days N] [--late-build-by HH:MM] [--mark-reported RUN_ID]
                     [--since ISO [--tasks a,b]] [--state DIR] [--now ISO] [--json]
    runlog.py summary --week [--state DIR] [--now ISO] [--json]
    runlog.py merge-dir DIR [--state DIR] [--json]

Every scheduled command (and /make-reel, /chrome-queue) records its start and
finish. `STATE` is `--state DIR`, else $NUMA_STATE, else `~/NUMA Studio/_Plan`.

Storage (one writer per file, so Drive's last-writer-wins never loses a run):
* `STATE/runlog/<run_id>.json` - one run's record, written only by that run
  (start, then finish). The commands upload it to Drive `_Plan/runlog/`.
* `STATE/runlog/reported-<run_id>.json` - the problem keys the watchdog run
  `<run_id>` reported (`check --mark-reported RUN_ID`).
* `STATE/runlog.json` - the local merged view, rebuilt from the folder:
    {"schema_version": 1, "created_at": "2026-11-01T02:00:05Z",
     "runs": [{"id": "build_today-20261113T110002Z-3f9a", "task": "build_today",
               "started_at": "2026-11-13T11:00:02Z", "finished_at": "2026-11-13T11:14:40Z",
               "outcome": "ok", "note": "", "late": false, "rescheduled": false, "supersedes": []}],
     "reported": ["missed:build_today:2026-11-10T05:00:00-06:00"]}
  Before a run starts, the commands download Drive `_Plan/runlog/` into a
  folder and run `merge-dir` on it (union by run id; a finished record wins
  over an open one; reported keys are unioned).

`start` prints the run id. `--late` marks a late build started by the
watchdog. An earlier open run of the same task is listed in the new run's
`supersedes` (a desktop run cut off by sleep, a cloud run that died): it is
reported as `interrupted`, not stuck. `finish` closes the run (or, with
`--task`, the newest open run of the task when the id was lost); a run that hit
an error still finishes, with `--outcome failed`. `--rescheduled` records that
the run itself already moved the day (build-today's failure path), so the
watchdog does not reschedule it again.

`check` is the watchdog. It reads the schedule from config/studio.json
(`schedule.timezone`, the 5-field cron of every task in `schedule.tasks` and of
the non-desktop tasks in `schedule.extra_tasks`) and settings from
`schedule.runlog` (defaults below), evaluates each cron in the schedule's
timezone with zoneinfo (so daylight-saving changes are handled), and reports
over the last `--days` (7):

* missed  - a scheduled time (after the log's `created_at`, so a new install
            is not flagged) with no run started in its slot (from
            `early_minutes` before it up to the next scheduled time), once
            `grace_minutes` have passed;
* failed  - the slot's runs all ended `failed` (a later ok re-run clears it);
* stuck   - a run still open after `stuck_after_minutes`;
* partial / interrupted - listed under `notes`, not problems.

Each problem has an `action`:
* `late_build` - build_today only: the slot was missed outright (no run at
  all, `runs` 0) and it is still before `late_build_by` (Central) today. A late
  build makes the day's files for a person to approve (DECISIONS D26:
  nothing posts without approval); it never posts by itself. A slot that
  already has a run (late or not, finished or still running) never gets one.
* `reschedule` - build_today otherwise.
* `skip` - nothing to do: the run already rescheduled its day (`rescheduled`),
  or the next run catches up.
* `rerun` - other tasks within `rerun_within_hours` of the slot.
`new` is false for problems that a `check --mark-reported` already returned,
so Jude gets each line once.

`check --since ISO` is the setup verification (R343): for every task (or
`--tasks`), did a run start after ISO and finish? `ok` passes; `partial`
counts as ran, with a warning; `failed`, `running` or `not run` fail it.

`summary --week` gives the digest's run-health numbers and one plain line.
Writes are atomic and serialized with a lock file next to the log. Exit 0 on
success (problems are data, not errors), 1 on bad input, 2 on usage errors.
"""
from __future__ import annotations

import bisect
import contextlib
import hashlib
import json
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
RUN_DIR = "runlog"
OUTCOMES = ("ok", "failed", "partial")
MAX_REPORTED = 2000
TASK_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*-\d{8}T\d{6}Z-[0-9a-f]{4}$")

DEFAULTS: dict[str, Any] = {
    "window_days": 7,
    "grace_minutes": 60,
    "early_minutes": 120,
    "stuck_after_minutes": {"default": 120, "build_today": 180, "plan_month": 240},
    "late_build_by": "15:00",
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


def _valid_run(r: Any) -> bool:
    return isinstance(r, dict) and bool(r.get("id")) and bool(r.get("task")) and bool(r.get("started_at"))


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
        if not _valid_run(r):
            raise nc.UserError(f"{path}: every run needs id, task and started_at")
    return data


def save_log(path: Path, data: dict) -> None:
    if data["runs"]:
        first = min(r["started_at"] for r in data["runs"])
        if not data.get("created_at") or first < data["created_at"]:
            data["created_at"] = first
    data["runs"].sort(key=lambda r: (r["started_at"], r["id"]))
    data["reported"] = data.get("reported", [])[-MAX_REPORTED:]
    nc.write_json(path, data)


def write_run_file(state: Path, run: dict) -> Path:
    """This run's own record: the only file of the run log that this run ever writes."""
    return nc.write_json(state / RUN_DIR / f"{run['id']}.json", run)


def merge_run(log: dict, r: dict) -> bool:
    """Fold one run record into the log; a finished record wins over an open one. True when it changed."""
    for i, cur in enumerate(log["runs"]):
        if cur["id"] == r["id"]:
            if not cur.get("finished_at") and r.get("finished_at"):
                log["runs"][i] = dict(r)
                return True
            if cur.get("finished_at") and r.get("finished_at") and r["finished_at"] > cur["finished_at"]:
                log["runs"][i] = dict(r)
                return True
            return False
    log["runs"].append(dict(r))
    return True


def merge_reported(log: dict, keys: list) -> None:
    seen = set(log["reported"])
    log["reported"].extend(k for k in keys if isinstance(k, str) and k not in seen and not seen.add(k))


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


def _hhmm(text: str, what: str) -> tuple[int, int]:
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


def analyze(log: dict, cfg: dict, now: datetime, days: int | None = None, late_build_by: str | None = None) -> dict:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    st = settings(cfg)
    days = int(days if days is not None else st["window_days"])
    if days < 1:
        raise nc.UserError("--days must be at least 1")
    lb_h, lb_m = _hhmm(late_build_by or st["late_build_by"],
                       "--late-build-by" if late_build_by else "schedule.runlog.late_build_by")
    grace = timedelta(minutes=float(st["grace_minutes"]))
    early = timedelta(minutes=float(st["early_minutes"]))
    win_start = now - timedelta(days=days)
    now_local = now.astimezone(tz)

    runs = []
    for r in log["runs"]:
        start, end = _run_times(r, tz)
        runs.append((r, start, end))
    superseded = {i for r, _, _ in runs for i in (r.get("supersedes") or [])}
    if log.get("created_at"):
        log_start = parse_when(log["created_at"], tz, "created_at") - early
    else:
        log_start = min((s for _, s, _ in runs), default=None)
        log_start = log_start - early if log_start else None

    problems: list[dict] = []
    notes: list[dict] = []
    stats: dict[str, dict] = {}

    def run_state(r: dict, start: datetime) -> str:
        if r.get("outcome") in OUTCOMES:
            return r["outcome"]
        if r["id"] in superseded:
            return "interrupted"
        if (now - start) > timedelta(minutes=_stuck_after(r["task"], st)):
            return "stuck"
        return "running"

    def action_for(task: str, slot: datetime, kind: str, got: list) -> str:
        if any(r.get("rescheduled") for r, _ in got):
            return "skip"  # the run already moved its day
        if task == "build_today":
            slot_day = slot.astimezone(tz).date()
            cutoff = datetime(slot_day.year, slot_day.month, slot_day.day, lb_h, lb_m, tzinfo=tz)
            if kind == "missed" and not got and slot_day == now_local.date() and now < cutoff:
                return "late_build"
            return "reschedule"
        hours = float((st["rerun_within_hours"] or {}).get(task, 0))
        return "rerun" if now < slot + timedelta(hours=hours) else "skip"

    def note(kind: str, r: dict, slot_txt: str | None) -> None:
        notes.append({"kind": kind, "task": r["task"], "slot": slot_txt, "run_id": r["id"],
                      "note": r.get("note", "") if kind == "partial" else "interrupted (a later run started)"})

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
                                    "stuck": 0, "running": 0, "late": 0, "name": t.get("name", task)})
        for i, fire in enumerate(utc_fires):
            if fire < win_start or fire > now or (log_start is None or fire < log_start):
                continue  # outside the window, or before the log existed (a new install is not a miss)
            got = slots.get(i, [])
            if not got and now < fire + grace:
                continue  # not due yet
            s["expected"] += 1
            slot_txt = local_iso(fire, tz)
            day = fire.astimezone(tz).date().isoformat()
            if not got:
                s["missed"] += 1
                problems.append({"kind": "missed", "task": task, "slot": slot_txt, "date": day, "runs": 0,
                                 "late_runs": 0, "action": action_for(task, fire, "missed", got)})
                continue
            covered_ids.update(r["id"] for r, _ in got)
            if any(r.get("late") for r, _ in got):
                s["late"] += 1
            states = [(run_state(r, start), r, start) for r, start in got]
            kinds = [k for k, _, _ in states]
            if "ok" in kinds:
                s["ok"] += 1
            elif "partial" in kinds or "interrupted" in kinds:
                s["partial"] += 1
                k, r, _ = next(x for x in states if x[0] in ("partial", "interrupted"))
                note(k, r, slot_txt)
            elif "running" in kinds:
                s["running"] += 1
            else:
                kind = "stuck" if "stuck" in kinds else "failed"
                s[kind] += 1
                k, r, start = next(x for x in reversed(states) if x[0] == kind)
                p = {"kind": kind, "task": task, "slot": slot_txt, "date": day, "run_id": r["id"],
                     "runs": len(got), "late_runs": sum(1 for x, _ in got if x.get("late")),
                     "started_at": local_iso(start, tz), "action": action_for(task, fire, kind, got)}
                if kind == "failed":
                    p["note"] = r.get("note", "")
                else:
                    p["minutes"] = int((now - start).total_seconds() // 60)
                if any(x.get("rescheduled") for x, _ in got):
                    p["rescheduled"] = True
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
                 "run_id": r["id"], "runs": 1, "late_runs": 0, "started_at": local_iso(start, tz),
                 "action": "skip"}
            if k == "failed":
                p["note"] = r.get("note", "")
            else:
                p["minutes"] = int((now - start).total_seconds() // 60)
            problems.append(p)
        elif k in ("partial", "interrupted"):
            note(k, r, None)

    reported = set(log.get("reported", []))
    for p in problems:
        p["key"] = f"{p['kind']}:{p['task']}:{p['slot'] or p['run_id']}"
        p["new"] = p["key"] not in reported
    problems.sort(key=lambda p: (p["slot"] or p["started_at"], p["task"]))
    return {"now": local_iso(now, tz), "timezone": str(tz.key), "window_days": days,
            "healthy": not problems, "problems": problems, "notes": notes, "tasks": stats}


def verify(log: dict, cfg: dict, since: datetime, tasks: list[str] | None, now: datetime) -> dict:
    tz = zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")
    wanted = tasks or [t["id"] for t in scheduled_tasks(cfg, include_desktop=True)]
    rank = {"ok": 3, "partial": 2, "failed": 1}
    out = {}
    for task in wanted:
        runs = [r for r in log["runs"] if r["task"] == task and since <= _run_times(r, tz)[0] <= now]
        if not runs:
            out[task] = {"status": "not run", "ran": False, "run_id": None, "note": ""}
            continue
        best = max(runs, key=lambda r: (rank.get(r.get("outcome") or "", 0), r["started_at"]))
        status = best.get("outcome") or "running"
        out[task] = {"status": status, "ran": status in ("ok", "partial"), "run_id": best["id"],
                     "note": best.get("note", "")}
    return {"since": local_iso(since, tz), "healthy": all(v["ran"] for v in out.values()),
            "warnings": [t for t, v in out.items() if v["status"] == "partial"], "verify": out}


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


def _tz(cfg: dict) -> ZoneInfo:
    return zone(nc.dig(cfg, "schedule.timezone") or "America/Chicago")


def cmd_start(args, cfg) -> int:
    if not TASK_RE.match(args.task):
        raise nc.UsageError(f"task {args.task!r} must be a snake_case id such as build_today")
    tz = _tz(cfg)
    now = now_arg(args.now, tz)
    state = state_dir(args.state)
    path = state / LOG_NAME
    with locked(path):
        log = load_log(path)
        rid = _new_id(args.task, now)
        while any(r["id"] == rid for r in log["runs"]):
            rid = _new_id(args.task, now)
        earlier = sorted(r["id"] for r in log["runs"] if r["task"] == args.task and not r.get("finished_at")
                         and r["started_at"] <= utc_iso(now))
        run = {"id": rid, "task": args.task, "started_at": utc_iso(now), "finished_at": None, "outcome": None,
               "note": "", "late": bool(args.late), "rescheduled": False, "supersedes": earlier}
        log["runs"].append(run)
        write_run_file(state, run)
        save_log(path, log)
    if args.json:
        nc.print_json({"run_id": rid, "task": args.task, "started_at": local_iso(now, tz), "late": run["late"],
                       "supersedes": earlier, "file": str(state / RUN_DIR / f"{rid}.json")})
    else:
        print(rid)
    return 0


def cmd_finish(args, cfg) -> int:
    if not args.run_id and not args.task:
        raise nc.UsageError("give the RUN_ID that start printed, or --task TASK for its newest open run")
    tz = _tz(cfg)
    now = now_arg(args.now, tz)
    state = state_dir(args.state)
    path = state / LOG_NAME
    with locked(path):
        log = load_log(path)
        if args.run_id:
            run = next((r for r in log["runs"] if r["id"] == args.run_id), None)
            if run is None:
                raise nc.UserError(f"no run {args.run_id} in {path} (merge the Drive copy first, "
                                   "or finish with --task TASK)")
        else:
            open_runs = [r for r in log["runs"] if r["task"] == args.task and not r.get("finished_at")]
            if not open_runs:
                raise nc.UserError(f"no open {args.task} run in {path}")
            run = max(open_runs, key=lambda r: r["started_at"])
        run["finished_at"] = utc_iso(now)
        run["outcome"] = args.outcome
        run["note"] = " ".join((args.note or "").split())[:300]
        run["rescheduled"] = bool(args.rescheduled) or bool(run.get("rescheduled"))
        write_run_file(state, run)
        save_log(path, log)
    if args.json:
        nc.print_json({"run_id": run["id"], "task": run["task"], "outcome": run["outcome"],
                       "rescheduled": run["rescheduled"], "finished_at": local_iso(now, tz),
                       "file": str(state / RUN_DIR / f"{run['id']}.json")})
    else:
        print(f"{run['id']}: {run['outcome']}")
    return 0


def cmd_check(args, cfg) -> int:
    tz = _tz(cfg)
    now = now_arg(args.now, tz)
    state = state_dir(args.state)
    path = state / LOG_NAME
    if args.since:
        if args.mark_reported:
            raise nc.UsageError("--mark-reported does not go with --since")
        tasks = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
        res = verify(load_log(path), cfg, parse_when(args.since, tz, "--since"), tasks, now)
        if args.json:
            nc.print_json(res)
        else:
            for task, v in res["verify"].items():
                label = "OK" if v["status"] == "ok" else ("WARN" if v["status"] == "partial" else "NOT OK")
                print(f"{label}: {task} ({v['status']}{': ' + v['note'] if v['note'] else ''})")
            print("all tasks ran" + (" (check the WARN lines)" if res["warnings"] else "") if res["healthy"]
                  else "some tasks did not finish since " + res["since"])
        return 0
    if args.tasks:
        raise nc.UsageError("--tasks goes with --since")
    if args.mark_reported and not ID_RE.match(args.mark_reported):
        raise nc.UsageError("--mark-reported takes this run's id (the one runlog.py start printed)")
    with locked(path):
        log = load_log(path)
        res = analyze(log, cfg, now, args.days, args.late_build_by)
        if args.mark_reported:
            keys = [p["key"] for p in res["problems"] if p["new"]]
            mark = state / RUN_DIR / f"reported-{args.mark_reported}.json"
            old = nc.read_json(mark, "reported file").get("reported", []) if mark.exists() else []
            nc.write_json(mark, {"run_id": args.mark_reported, "reported": old + [k for k in keys if k not in old]})
            merge_reported(log, keys)
            save_log(path, log)
            res["reported_file"] = str(mark)
    if args.json:
        nc.print_json(res)
    else:
        for p in res["problems"]:
            print(problem_line(p) + ("" if p["new"] else " (reported before)"))
        for n in res["notes"]:
            print(f"{n['kind'].upper()}: {n['task']} {_fmt_slot(n['slot'])} {n['note']}".rstrip())
        print(health_line(res))
    return 0


def cmd_summary(args, cfg) -> int:
    tz = _tz(cfg)
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
                  + "".join(f", {s[k]} {k}" for k in ("missed", "failed", "stuck", "late") if s[k]))
    return 0


def cmd_merge_dir(args, cfg) -> int:
    src = Path(args.dir).expanduser()
    if not src.is_dir():
        raise nc.UserError(f"{src} is not a folder; download Drive _Plan/runlog/ into it first "
                           "(an empty folder when Drive confirmed it does not exist yet)")
    state = state_dir(args.state)
    path = state / LOG_NAME
    added = changed = skipped = 0
    with locked(path):
        log = load_log(path)
        before = {r["id"] for r in log["runs"]}
        for f in sorted(src.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                skipped += 1
                nc.warn(f"skipped {f.name}: not readable JSON (re-download it)")
                continue
            if f.name.startswith("reported-") and isinstance(data, dict):
                merge_reported(log, data.get("reported", []))
                own = state / RUN_DIR / f.name
                mine = nc.read_json(own, "reported file").get("reported", []) if own.exists() else []
                nc.write_json(own, {**data, "reported": mine + [k for k in data.get("reported", []) if k not in mine]})
            elif _valid_run(data):
                if merge_run(log, data):
                    changed += 1
                    added += data["id"] not in before
                    write_run_file(state, next(r for r in log["runs"] if r["id"] == data["id"]))
            else:
                skipped += 1
                nc.warn(f"skipped {f.name}: not a run record")
        save_log(path, log)
    msg = {"log": str(path), "runs": len(log["runs"]), "added": added, "updated": changed - added,
           "skipped": skipped}
    if args.json:
        nc.print_json(msg)
    else:
        print(f"merged {src.name}: {added} new run(s), {changed - added} updated, {len(log['runs'])} in total")
    return 0


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="runlog.py", description="Run log and watchdog for the scheduled tasks.")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=nc.ArgParser)

    def common(p, now=True):
        p.add_argument("--state", help="STATE folder (default $NUMA_STATE or ~/NUMA Studio/_Plan)")
        if now:
            p.add_argument("--now", help="ISO time to use instead of the clock (tests, replays)")
        p.add_argument("--json", action="store_true", help="print one JSON report")

    s = sub.add_parser("start", help="record a run's start and print its id")
    s.add_argument("task", help="task id, e.g. build_today (config schedule.tasks id) or make_reel")
    s.add_argument("--late", action="store_true", help="a late build the watchdog started")
    common(s)
    f = sub.add_parser("finish", help="record a run's end and outcome")
    f.add_argument("run_id", nargs="?", help="the id start printed")
    f.add_argument("--task", help="finish the newest open run of this task (when the id was lost)")
    f.add_argument("--outcome", required=True, choices=OUTCOMES)
    f.add_argument("--note", help="one short line: what failed or was left out")
    f.add_argument("--rescheduled", action="store_true", help="this run already rescheduled its day")
    common(f)
    c = sub.add_parser("check", help="missed, failed and stuck runs over the last days (the watchdog)")
    c.add_argument("--days", type=int, help="window in days (default schedule.runlog.window_days, 7)")
    c.add_argument("--late-build-by", help="HH:MM Central: latest start of a late build (default schedule.runlog.late_build_by)")
    c.add_argument("--since", help="setup verification: did every task finish after this ISO time?")
    c.add_argument("--tasks", help="with --since: comma-separated task ids (default every scheduled task)")
    c.add_argument("--mark-reported", metavar="RUN_ID",
                   help="this watchdog run's id: remember these problems so later checks mark them new=false")
    common(c)
    m = sub.add_parser("summary", help="run health for the digest")
    m.add_argument("--week", action="store_true", required=True, help="the last 7 days")
    common(m)
    g = sub.add_parser("merge-dir", help="fold a downloaded copy of Drive _Plan/runlog/ into the local log")
    g.add_argument("dir")
    common(g, now=False)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = nc.load_config()
    return {"start": cmd_start, "finish": cmd_finish, "check": cmd_check, "summary": cmd_summary,
            "merge-dir": cmd_merge_dir}[args.cmd](args, cfg)


if __name__ == "__main__":
    nc.run_cli(main)
