#!/usr/bin/env python3
"""Queue of the steps that need Claude in Chrome (R342).

Usage:
    chrome_queue.py add    --kind KIND --payload JSON --deadline ISO --fallback TEXT [--not-before ISO]
                           [--state DIR] [--now ISO] [--json]
    chrome_queue.py list   [--status pending|in_progress|done|expired|conflict|all] [--state DIR] [--json]
    chrome_queue.py next   [--claim RUN_ID] [--lease-minutes N] [--kinds a,b] [--state DIR] [--now ISO] [--json]
    chrome_queue.py done   ID --claim RUN_ID --result TEXT [--state DIR] [--now ISO] [--json]
    chrome_queue.py fail   ID --claim RUN_ID --reason TEXT [--state DIR] [--now ISO] [--json]
    chrome_queue.py expire --run RUN_ID [--margin-minutes N] [--state DIR] [--now ISO] [--json]
    chrome_queue.py merge  FILE [--state DIR] [--json]

Claude in Chrome exists only while Katie's Mac is awake with the desktop app
open, so a run that needs it queues the step instead of waiting:

    KIND                  what Chrome does                                  fallback (never publishes, D26)
    scout_research        signed-in research on NUMA's own channels         the web-search result stands
    competitor_log        competitors' last 12 posts on Instagram           the web-search log stands
    trial_reel            post an APPROVED reel as a Trial Reel             stays staged; the approver is told
    collab_invite         post an APPROVED reel with the collaborator       stays staged; the approver is told
    ai_label              post an APPROVED reel with the AI label on        stays staged; the approver is told
    higgsfield_unlimited  unlimited-window Kling drafts on higgsfield.ai    that build drafts through the connector

Posting kinds are queued only after a person approved the post (DECISIONS
D26), and no fallback ever publishes.

The queue lives in `STATE/chrome_queue.json` (`--state DIR`, else $NUMA_STATE,
else `~/NUMA Studio/_Plan`), synced to Drive `_Plan/`:

    {"schema_version": 1,
     "items": [{"id": "trial_reel-3be1c09a42", "kind": "trial_reel",
                "payload": {"job": "Day 10 - 2026-12-10 - Cold snap calm"},
                "not_before": "2026-12-10T15:45:00-06:00", "deadline": "2026-12-10T17:00:00-06:00",
                "fallback": "Stays staged; the approver is told to post it from the app",
                "status": "pending", "added_at": "2026-12-10T11:05:00Z", "attempts": 0, "last_error": null,
                "claimed_by": null, "claimed_at": null, "lease_until": null,
                "done_at": null, "result": null, "expired_at": null, "expired_by": null, "conflict": null}]}

* `add` prints the item id. An identical item (same kind and payload) that is
  pending, in progress or done is not added twice: its id is printed and, for
  a pending one, the earlier deadline is kept (refused when that would put
  `not_before` at or after the deadline). A naive time is read in config
  `schedule.timezone` (Central). `--not-before` holds an item back (a posting
  step waits for its posting window).
* `next` (read only) shows the pending item with the earliest deadline that is
  ready (`not_before` passed) and not past its deadline; `--kinds` limits the
  kinds. `next --claim RUN_ID` also claims it under the lock: status
  `in_progress`, `claimed_by`, and a lease (`--lease-minutes`, default
  config `schedule.chrome_queue.lease_minutes` or 45). Two drainers never get
  the same item; a lease that runs out returns the item to `pending`.
* `done ID --claim RUN_ID` and `fail ID --claim RUN_ID` need that claim. `fail`
  records the attempt and returns the item to `pending`. `done` on an item that
  expired meanwhile marks it `conflict` (the fallback already ran) and exits 1,
  so the clash is reported, never silently won.
* `expire --run RUN_ID` (the one designated runner: the 8 pm night check)
  expires every pending item, and every claim whose lease ran out, whose
  deadline is at least `--margin-minutes` (default
  `schedule.chrome_queue.expire_margin_minutes` or 60) in the past, and prints
  them with their fallbacks; it also lists the `conflict` items.
* `merge FILE` folds the Drive copy in: union by id; done or expired beats
  pending and in_progress; done on one side and expired on the other becomes
  `conflict`; of two live claims the earlier one wins.

Writes are atomic and serialized with a lock file next to the queue. Exit 0 on
success, 1 on bad input (payload not a JSON object, a time not ISO 8601,
unknown id, a missing claim, a conflict), 2 on usage errors (an unknown --kind
among them).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
from runlog import local_iso, locked, now_arg, parse_when, state_dir, utc_iso, zone  # noqa: E402

QUEUE_SCHEMA_VERSION = 1
QUEUE_NAME = "chrome_queue.json"
KINDS = ("scout_research", "competitor_log", "trial_reel", "collab_invite", "ai_label", "higgsfield_unlimited")
POSTING_KINDS = ("trial_reel", "collab_invite", "ai_label")
STATUSES = ("pending", "in_progress", "done", "expired", "conflict")
DEFAULT_LEASE_MIN = 45
DEFAULT_MARGIN_MIN = 60
FIELDS = ("id", "kind", "payload", "not_before", "deadline", "fallback", "status", "added_at", "attempts",
          "last_error", "claimed_by", "claimed_at", "lease_until", "done_at", "result", "expired_at",
          "expired_by", "conflict")


def _cfg_minutes(key: str, default: int) -> float:
    v = nc.dig(nc.load_config(), f"schedule.chrome_queue.{key}")
    return float(v) if isinstance(v, (int, float)) and v > 0 else float(default)


def _tz():
    return zone(nc.dig(nc.load_config(), "schedule.timezone") or "America/Chicago")


def load_queue(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {"schema_version": QUEUE_SCHEMA_VERSION, "items": []}
    data = nc.read_json(path, "Chrome queue")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise nc.UserError(f"{path} is not a Chrome queue (expected {{\"items\": [...]}}); move it aside and run again")
    for it in data["items"]:
        if not isinstance(it, dict) or not it.get("id") or it.get("kind") not in KINDS \
                or it.get("status") not in STATUSES or not it.get("deadline"):
            raise nc.UserError(f"{path}: every item needs id, a known kind, status and deadline")
        for k in FIELDS:
            it.setdefault(k, 0 if k == "attempts" else None)
    data.setdefault("schema_version", QUEUE_SCHEMA_VERSION)
    return data


def save_queue(path: Path, data: dict) -> None:
    nc.write_json(path, data)


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def item_key(kind: str, payload: dict) -> str:
    return hashlib.sha1(f"{kind}|{canonical(payload)}".encode("utf-8")).hexdigest()[:10]


def _t(value: str | None, tz, what: str) -> datetime | None:
    return parse_when(value, tz, what) if value else None


def _public(it: dict | None) -> dict | None:
    return {k: it.get(k) for k in FIELDS} if it else None


def _find(data: dict, item_id: str, path: Path) -> dict:
    it = next((i for i in data["items"] if i["id"] == item_id), None)
    if it is None:
        raise nc.UserError(f"no item {item_id} in {path} (chrome_queue.py list --status all shows the ids)")
    return it


def _release(it: dict) -> None:
    it.update(status="pending", claimed_by=None, claimed_at=None, lease_until=None)


def _lapse_leases(data: dict, now: datetime, tz) -> int:
    """Claims whose lease ran out go back to pending (the drainer died or the Mac slept)."""
    n = 0
    for it in data["items"]:
        if it["status"] == "in_progress" and (_t(it["lease_until"], tz, "lease_until") or now) <= now:
            it["attempts"] = int(it.get("attempts") or 0) + 1
            it["last_error"] = f"{utc_iso(now)} lease of {it['claimed_by']} ran out"
            _release(it)
            n += 1
    return n


def _claimed(it: dict, run: str) -> None:
    if it["status"] == "expired":
        return
    if it["status"] != "in_progress" or it["claimed_by"] != run:
        raise nc.UserError(f"{it['id']} is not claimed by {run} (status {it['status']}"
                           + (f", claimed by {it['claimed_by']}" if it["claimed_by"] else "")
                           + "); claim it with next --claim first")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_add(args) -> int:
    tz = _tz()
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        raise nc.UserError(f"--payload is not valid JSON ({e.msg} at column {e.colno})") from None
    if not isinstance(payload, dict) or not payload:
        raise nc.UserError("--payload must be a non-empty JSON object, e.g. '{\"job\": \"Day 10 - ...\"}'")
    fallback = " ".join((args.fallback or "").split())
    if not fallback:
        raise nc.UserError("--fallback must say what happens when the deadline passes")
    deadline = parse_when(args.deadline, tz, "--deadline")
    not_before = parse_when(args.not_before, tz, "--not-before") if args.not_before else None
    if not_before and not_before >= deadline:
        raise nc.UserError("--not-before must be earlier than --deadline")
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / QUEUE_NAME
    with locked(path):
        data = load_queue(path)
        same = [i for i in data["items"] if i["kind"] == args.kind and canonical(i["payload"]) == canonical(payload)]
        live = next((i for i in same if i["status"] in ("pending", "in_progress", "done")), None)
        if live is not None:
            if live["status"] == "pending" and deadline < _t(live["deadline"], tz, "deadline"):
                nb = _t(live["not_before"], tz, "not_before")
                if nb and nb >= deadline:
                    raise nc.UserError(f"{live['id']} is already queued with not_before {live['not_before']}; "
                                       f"the earlier deadline {local_iso(deadline, tz)} would come before it")
                live["deadline"] = local_iso(deadline, tz)
                save_queue(path, data)
            it, added = live, False
        else:
            n = len(same)
            it = {k: None for k in FIELDS}
            it.update(id=f"{args.kind}-{item_key(args.kind, payload)}" + (f"-{n + 1}" if n else ""),
                      kind=args.kind, payload=payload, deadline=local_iso(deadline, tz), fallback=fallback,
                      not_before=local_iso(not_before, tz) if not_before else None, status="pending",
                      added_at=utc_iso(now), attempts=0)
            data["items"].append(it)
            save_queue(path, data)
            added = True
    if args.json:
        nc.print_json({"added": added, "item": _public(it)})
    else:
        print(it["id"] if added else f"{it['id']} (already queued, {it['status']})")
        if deadline <= now:
            nc.warn(f"deadline {local_iso(deadline, tz)} has already passed: the next expire runs its fallback")
    return 0


def cmd_list(args) -> int:
    data = load_queue(state_dir(args.state) / QUEUE_NAME)
    items = data["items"] if args.status == "all" else [i for i in data["items"] if i["status"] == args.status]
    items = sorted(items, key=lambda i: (STATUSES.index(i["status"]), i["deadline"], i["added_at"] or ""))
    if args.json:
        nc.print_json({"items": [_public(i) for i in items]})
    else:
        if not items:
            print("no items" if args.status == "all" else f"no {args.status} items")
        for i in items:
            print(f"{i['id']}  {i['status']}  deadline {i['deadline']}  {canonical(i['payload'])}")
    return 0


def cmd_next(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    kinds = set(_kinds(args.kinds)) if args.kinds else set(KINDS)
    lease = float(args.lease_minutes) if args.lease_minutes else _cfg_minutes("lease_minutes", DEFAULT_LEASE_MIN)
    if lease <= 0:
        raise nc.UsageError("--lease-minutes must be positive")
    path = state_dir(args.state) / QUEUE_NAME

    def pick(data):
        live = [i for i in data["items"] if i["status"] == "pending" and i["kind"] in kinds
                and _t(i["deadline"], tz, "deadline") > now]
        ready = [i for i in live if not i["not_before"] or _t(i["not_before"], tz, "not_before") <= now]
        ready.sort(key=lambda i: (_t(i["deadline"], tz, "deadline"), i["added_at"] or ""))
        return (ready[0] if ready else None), len(ready), len(live) - len(ready)

    if args.claim:
        with locked(path):
            data = load_queue(path)
            lapsed = _lapse_leases(data, now, tz)
            it, ready, waiting = pick(data)
            if it:
                it.update(status="in_progress", claimed_by=args.claim, claimed_at=utc_iso(now),
                          lease_until=utc_iso(now + timedelta(minutes=lease)))
            if it or lapsed:
                save_queue(path, data)
    else:
        data = load_queue(path)
        it, ready, waiting = pick(data)
    if args.json:
        nc.print_json({"item": _public(it), "pending": ready, "waiting": waiting, "claimed": bool(args.claim and it)})
    else:
        print(json.dumps(_public(it), ensure_ascii=False) if it else "none")
    return 0


def cmd_done(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    result = " ".join((args.result or "").split())
    if not result:
        raise nc.UserError("--result must say what Chrome did (a permalink, a file, 'posted with AI label')")
    path = state_dir(args.state) / QUEUE_NAME
    with locked(path):
        data = load_queue(path)
        it = _find(data, args.id, path)
        _claimed(it, args.claim)
        if it["status"] == "expired":
            it.update(status="conflict", conflict={"done_by": args.claim, "done_at": utc_iso(now),
                                                   "result": result[:500], "expired_at": it["expired_at"],
                                                   "expired_by": it["expired_by"]})
            save_queue(path, data)
            raise nc.UserError(f"conflict: {it['id']} expired at {it['expired_at']} and its fallback ran, but "
                               f"Chrome also did it ({result[:80]}); recorded as conflict for Jude to check")
        it.update(status="done", done_at=utc_iso(now), result=result[:500], lease_until=None)
        save_queue(path, data)
    if args.json:
        nc.print_json({"item": _public(it)})
    else:
        print(f"{it['id']}: done")
    return 0


def cmd_fail(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    reason = " ".join((args.reason or "").split())
    if not reason:
        raise nc.UserError("--reason must say why the Chrome attempt failed")
    path = state_dir(args.state) / QUEUE_NAME
    with locked(path):
        data = load_queue(path)
        it = _find(data, args.id, path)
        _claimed(it, args.claim)
        if it["status"] == "expired":
            raise nc.UserError(f"{it['id']} already expired; its fallback ran")
        it["attempts"] = int(it.get("attempts") or 0) + 1
        it["last_error"] = f"{utc_iso(now)} {reason[:300]}"
        _release(it)
        save_queue(path, data)
    if args.json:
        nc.print_json({"item": _public(it)})
    else:
        print(f"{it['id']}: attempt {it['attempts']} failed; pending again until {it['deadline']}")
    return 0


def cmd_expire(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    margin = float(args.margin_minutes) if args.margin_minutes is not None \
        else _cfg_minutes("expire_margin_minutes", DEFAULT_MARGIN_MIN)
    if margin < 0:
        raise nc.UsageError("--margin-minutes cannot be negative")
    path = state_dir(args.state) / QUEUE_NAME
    expired = []
    with locked(path):
        data = load_queue(path)
        _lapse_leases(data, now, tz)
        for it in data["items"]:
            if it["status"] == "pending" and _t(it["deadline"], tz, "deadline") + timedelta(minutes=margin) <= now:
                it.update(status="expired", expired_at=utc_iso(now), expired_by=args.run)
                expired.append(it)
        save_queue(path, data)
        conflicts = [i for i in data["items"] if i["status"] == "conflict"]
    if args.json:
        nc.print_json({"expired": [_public(i) for i in expired], "conflicts": [_public(i) for i in conflicts]})
    else:
        if not expired:
            print("nothing expired")
        for i in expired:
            print(f"EXPIRED: {i['id']} (deadline {i['deadline']}) -> fallback: {i['fallback']}")
        for i in conflicts:
            print(f"CONFLICT: {i['id']} expired and was also done by Chrome: {i['conflict']}")
    return 0


def merge_queues(mine: dict, other: dict, tz) -> int:
    by_id = {i["id"]: i for i in mine["items"]}
    added = 0
    for it in other.get("items", []):
        if not isinstance(it, dict) or it.get("kind") not in KINDS or it.get("status") not in STATUSES \
                or not it.get("id") or not it.get("deadline"):
            continue
        it = {**{k: (0 if k == "attempts" else None) for k in FIELDS}, **it}
        cur = by_id.get(it["id"])
        if cur is None:
            by_id[it["id"]] = dict(it)
            added += 1
            continue
        a, b = cur["status"], it["status"]
        attempts = max(int(cur.get("attempts") or 0), int(it.get("attempts") or 0))
        if {a, b} == {"done", "expired"}:
            done, exp = (cur, it) if a == "done" else (it, cur)
            merged = dict(exp)
            merged.update(status="conflict", conflict={"done_by": done["claimed_by"], "done_at": done["done_at"],
                                                       "result": done["result"], "expired_at": exp["expired_at"],
                                                       "expired_by": exp["expired_by"]})
            by_id[it["id"]] = merged
        elif "conflict" in (a, b):
            by_id[it["id"]] = dict(cur if a == "conflict" else it)
        elif b in ("done", "expired") and a not in ("done", "expired"):
            by_id[it["id"]] = dict(it)
        elif a == b == "in_progress" and cur["claimed_by"] != it["claimed_by"]:
            first = min((cur, it), key=lambda x: (x["claimed_at"] or "", x["claimed_by"] or ""))
            by_id[it["id"]] = dict(first)
        elif a == "pending" and b == "in_progress":
            by_id[it["id"]] = dict(it)
        by_id[it["id"]]["attempts"] = attempts
    mine["items"] = sorted(by_id.values(), key=lambda i: (i.get("added_at") or "", i["id"]))
    return added


def cmd_merge(args) -> int:
    tz = _tz()
    other_path = Path(args.file).expanduser()
    if not other_path.exists():
        raise nc.UserError(f"no file {other_path} to merge; merge only after a successful download (when Drive "
                           "confirms there is no chrome_queue.json yet, skip the merge)")
    other = load_queue(other_path)
    path = state_dir(args.state) / QUEUE_NAME
    with locked(path):
        data = load_queue(path)
        added = merge_queues(data, other, tz)
        save_queue(path, data)
    conflicts = sum(1 for i in data["items"] if i["status"] == "conflict")
    if args.json:
        nc.print_json({"queue": str(path), "items": len(data["items"]), "added": added, "conflicts": conflicts})
    else:
        print(f"merged {other_path.name}: {added} new item(s), {len(data['items'])} in total"
              + (f", {conflicts} conflict(s)" if conflicts else ""))
    return 0


def _kinds(text: str) -> list[str]:
    out = [k.strip() for k in re.split(r"[,\s]+", text) if k.strip()]
    bad = [k for k in out if k not in KINDS]
    if bad:
        raise nc.UsageError(f"unknown kind(s) {', '.join(bad)}; one of {', '.join(KINDS)}")
    return out


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="chrome_queue.py", description="Queue of the steps that need Claude in Chrome.")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=nc.ArgParser)

    def common(p, now=True):
        p.add_argument("--state", help="STATE folder holding chrome_queue.json (default $NUMA_STATE or ~/NUMA Studio/_Plan)")
        if now:
            p.add_argument("--now", help="ISO time to use instead of the clock (tests, replays)")
        p.add_argument("--json", action="store_true", help="print one JSON report")

    a = sub.add_parser("add", help="queue a Chrome step with a deadline and a fallback")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--payload", required=True, help="JSON object: what the step needs (job, month, file, ...)")
    a.add_argument("--deadline", required=True, help="ISO time after which the fallback runs instead")
    a.add_argument("--fallback", required=True, help="what happens when the deadline passes (never a publish)")
    a.add_argument("--not-before", help="ISO time before which the step must not run (e.g. the posting window)")
    common(a)
    li = sub.add_parser("list", help="queued items")
    li.add_argument("--status", default="pending", choices=STATUSES + ("all",))
    common(li, now=False)
    n = sub.add_parser("next", help="the ready item with the earliest deadline; --claim takes it")
    n.add_argument("--claim", metavar="RUN_ID", help="claim the item for this run (lease, under the lock)")
    n.add_argument("--lease-minutes", type=float, help="claim lease (default config or 45)")
    n.add_argument("--kinds", help="comma-separated kinds this drainer may take")
    common(n)
    d = sub.add_parser("done", help="mark a claimed item done")
    d.add_argument("id")
    d.add_argument("--claim", required=True, metavar="RUN_ID", help="the run that claimed it")
    d.add_argument("--result", required=True, help="what Chrome did")
    common(d)
    f = sub.add_parser("fail", help="record a failed attempt on a claimed item (it goes back to pending)")
    f.add_argument("id")
    f.add_argument("--claim", required=True, metavar="RUN_ID", help="the run that claimed it")
    f.add_argument("--reason", required=True)
    common(f)
    e = sub.add_parser("expire", help="expire items past deadline + margin and print their fallbacks")
    e.add_argument("--run", required=True, metavar="RUN_ID", help="the designated runner's run id (recorded)")
    e.add_argument("--margin-minutes", type=float, help="wait this long past a deadline (default config or 60)")
    common(e)
    m = sub.add_parser("merge", help="fold another copy of chrome_queue.json (the Drive copy) into the local queue")
    m.add_argument("file")
    common(m, now=False)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"add": cmd_add, "list": cmd_list, "next": cmd_next, "done": cmd_done, "fail": cmd_fail,
            "expire": cmd_expire, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    nc.run_cli(main)
