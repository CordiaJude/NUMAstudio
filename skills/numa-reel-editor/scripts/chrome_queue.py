#!/usr/bin/env python3
"""Queue of the steps that need Claude in Chrome (R342).

Usage:
    chrome_queue.py add  --kind KIND --payload JSON --deadline ISO --fallback TEXT [--state DIR] [--now ISO] [--json]
    chrome_queue.py list [--status pending|done|expired|all] [--state DIR] [--json]
    chrome_queue.py next [--state DIR] [--now ISO] [--json]
    chrome_queue.py done ID --result TEXT [--state DIR] [--now ISO] [--json]
    chrome_queue.py fail ID --reason TEXT [--state DIR] [--now ISO] [--json]
    chrome_queue.py expire [--state DIR] [--now ISO] [--json]
    chrome_queue.py merge FILE [--state DIR] [--json]

Claude in Chrome exists only while Katie's Mac is awake with the desktop app
open, so a cloud run that needs it queues the step instead of waiting:

    KIND                  what Chrome does                               typical deadline / fallback
    scout_research        signed-in research on NUMA's own channels      before the plan or build uses it / web search stands
    competitor_log        competitors' last 12 posts on Instagram        end of the month / the web-search log stands
    trial_reel            post a reel as a Trial Reel on instagram.com   posting time / post as a normal reel
    collab_invite         add the collaborator on instagram.com          posting time / post without the invite
    ai_label              post with Instagram's AI label switched on     posting time / not posted, Jude gets one line
    higgsfield_unlimited  unlimited-window Kling drafts on higgsfield.ai that reel's build / connector drafts

The queue lives in `STATE/chrome_queue.json` (`--state DIR`, else $NUMA_STATE,
else `~/NUMA Studio/_Plan`), synced to Drive `_Plan/` like the run log:

    {"schema_version": 1,
     "items": [{"id": "trial_reel-3be1c09a42", "kind": "trial_reel",
                "payload": {"job": "Day 10 - 2026-12-10 - Cold snap calm"},
                "deadline": "2026-12-10T17:00:00-06:00", "fallback": "Post as a normal reel and note it",
                "status": "pending", "added_at": "2026-12-10T11:05:00Z", "attempts": 0,
                "last_error": null, "done_at": null, "result": null, "expired_at": null}]}

* `add` prints the item id. An identical item (same kind and payload) that is
  still pending or already done is not added twice: its id is printed and,
  for a pending one, the earlier of the two deadlines is kept. A naive
  deadline is read in config `schedule.timezone` (Central).
* `next` prints the pending item with the earliest deadline that has not
  passed (`{"item": null}` when there is none).
* `done ID --result` marks it done; `fail ID --reason` records a failed
  attempt and leaves it pending for the next Chrome run.
* `expire` marks every pending item whose deadline has passed as expired and
  prints them, each with its fallback, so the caller runs the fallbacks now.
* `merge FILE` folds another copy of the queue (the Drive copy) into the local
  one: union by id; done or expired wins over pending.

Writes are atomic and serialized with a lock file next to the queue. Exit 0 on
success, 1 on bad input (payload not a JSON object, deadline not ISO 8601,
unknown id), 2 on usage errors (an unknown --kind among them).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
from runlog import local_iso, locked, now_arg, parse_when, state_dir, utc_iso, zone  # noqa: E402

QUEUE_SCHEMA_VERSION = 1
QUEUE_NAME = "chrome_queue.json"
KINDS = ("scout_research", "competitor_log", "trial_reel", "collab_invite", "ai_label", "higgsfield_unlimited")
STATUSES = ("pending", "done", "expired")


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
    data.setdefault("schema_version", QUEUE_SCHEMA_VERSION)
    return data


def save_queue(path: Path, data: dict) -> None:
    nc.write_json(path, data)


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def item_key(kind: str, payload: dict) -> str:
    return hashlib.sha1(f"{kind}|{canonical(payload)}".encode("utf-8")).hexdigest()[:10]


def _deadline(it: dict, tz) -> datetime:
    return parse_when(it["deadline"], tz, f"item {it['id']} deadline")


def _public(it: dict) -> dict:
    return {k: it.get(k) for k in ("id", "kind", "payload", "deadline", "fallback", "status", "added_at",
                                   "attempts", "last_error", "done_at", "result", "expired_at")}


def _find(data: dict, item_id: str, path: Path) -> dict:
    it = next((i for i in data["items"] if i["id"] == item_id), None)
    if it is None:
        raise nc.UserError(f"no item {item_id} in {path} (chrome_queue.py list shows the ids)")
    return it


def cmd_add(args) -> int:
    tz = _tz()
    if args.kind not in KINDS:
        raise nc.UserError(f"unknown kind {args.kind!r}; one of {', '.join(KINDS)}")
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        raise nc.UserError(f"--payload is not valid JSON ({e.msg} at column {e.colno})") from None
    if not isinstance(payload, dict) or not payload:
        raise nc.UserError("--payload must be a non-empty JSON object, e.g. '{\"job\": \"Day 10 - ...\"}'")
    fallback = " ".join((args.fallback or "").split())
    if not fallback:
        raise nc.UserError("--fallback must say what runs when the deadline passes")
    deadline = parse_when(args.deadline, tz, "--deadline")
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / QUEUE_NAME
    key = item_key(args.kind, payload)
    with locked(path):
        data = load_queue(path)
        same = [i for i in data["items"] if i["kind"] == args.kind and canonical(i["payload"]) == canonical(payload)]
        live = next((i for i in same if i["status"] in ("pending", "done")), None)
        if live is not None:
            if live["status"] == "pending" and deadline < _deadline(live, tz):
                live["deadline"] = local_iso(deadline, tz)
                save_queue(path, data)
            it, added = live, False
        else:
            n = len(same)
            it = {"id": f"{args.kind}-{key}" + (f"-{n + 1}" if n else ""), "kind": args.kind, "payload": payload,
                  "deadline": local_iso(deadline, tz), "fallback": fallback, "status": "pending",
                  "added_at": utc_iso(now), "attempts": 0, "last_error": None, "done_at": None, "result": None,
                  "expired_at": None}
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
    path = state_dir(args.state) / QUEUE_NAME
    data = load_queue(path)
    items = data["items"] if args.status == "all" else [i for i in data["items"] if i["status"] == args.status]
    items = sorted(items, key=lambda i: (i["status"] != "pending", i["deadline"], i["added_at"] or ""))
    if args.json:
        nc.print_json({"items": [_public(i) for i in items]})
    else:
        if not items:
            print(f"no {args.status if args.status != 'all' else ''} items".replace("  ", " "))
        for i in items:
            print(f"{i['id']}  {i['status']}  deadline {i['deadline']}  {canonical(i['payload'])}")
    return 0


def cmd_next(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    data = load_queue(state_dir(args.state) / QUEUE_NAME)
    live = [i for i in data["items"] if i["status"] == "pending" and _deadline(i, tz) > now]
    live.sort(key=lambda i: (_deadline(i, tz), i["added_at"] or ""))
    it = live[0] if live else None
    if args.json:
        nc.print_json({"item": _public(it) if it else None, "pending": len(live)})
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
        if it["status"] == "expired":
            raise nc.UserError(f"{it['id']} already expired and its fallback ran at {it['expired_at']}; "
                               "record the late result in the decisions log instead")
        it.update(status="done", done_at=utc_iso(now), result=result[:500])
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
        if it["status"] != "pending":
            raise nc.UserError(f"{it['id']} is {it['status']}, not pending")
        it["attempts"] = int(it.get("attempts") or 0) + 1
        it["last_error"] = f"{utc_iso(now)} {reason[:300]}"
        save_queue(path, data)
    if args.json:
        nc.print_json({"item": _public(it)})
    else:
        print(f"{it['id']}: attempt {it['attempts']} failed; still pending until {it['deadline']}")
    return 0


def cmd_expire(args) -> int:
    tz = _tz()
    now = now_arg(args.now, tz)
    path = state_dir(args.state) / QUEUE_NAME
    expired = []
    with locked(path):
        data = load_queue(path)
        for it in data["items"]:
            if it["status"] == "pending" and _deadline(it, tz) <= now:
                it.update(status="expired", expired_at=utc_iso(now))
                expired.append(it)
        if expired:
            save_queue(path, data)
    if args.json:
        nc.print_json({"expired": [_public(i) for i in expired]})
    else:
        if not expired:
            print("nothing expired")
        for i in expired:
            print(f"EXPIRED: {i['id']} (deadline {i['deadline']}) -> fallback: {i['fallback']}")
    return 0


def merge_queues(mine: dict, other: dict) -> int:
    rank = {"pending": 0, "expired": 1, "done": 2}
    by_id = {i["id"]: i for i in mine["items"]}
    added = 0
    for it in other.get("items", []):
        if not isinstance(it, dict) or it.get("kind") not in KINDS or it.get("status") not in STATUSES:
            continue
        cur = by_id.get(it["id"])
        if cur is None:
            by_id[it["id"]] = dict(it)
            added += 1
        elif rank[it["status"]] > rank[cur["status"]]:
            by_id[it["id"]] = dict(it)
        elif it["status"] == cur["status"] == "pending":
            cur["attempts"] = max(int(cur.get("attempts") or 0), int(it.get("attempts") or 0))
    mine["items"] = sorted(by_id.values(), key=lambda i: (i.get("added_at") or "", i["id"]))
    return added


def cmd_merge(args) -> int:
    other_path = Path(args.file).expanduser()
    if not other_path.exists():
        raise nc.UserError(f"no file {other_path} to merge (a first run has no Drive copy yet: skip the merge)")
    other = load_queue(other_path)
    path = state_dir(args.state) / QUEUE_NAME
    with locked(path):
        data = load_queue(path)
        added = merge_queues(data, other)
        save_queue(path, data)
    if args.json:
        nc.print_json({"queue": str(path), "items": len(data["items"]), "added": added})
    else:
        print(f"merged {other_path.name}: {added} new item(s), {len(data['items'])} in total")
    return 0


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
    a.add_argument("--fallback", required=True, help="what happens when the deadline passes")
    common(a)
    li = sub.add_parser("list", help="queued items")
    li.add_argument("--status", default="pending", choices=STATUSES + ("all",))
    common(li, now=False)
    n = sub.add_parser("next", help="the pending item with the earliest deadline")
    common(n)
    d = sub.add_parser("done", help="mark an item done")
    d.add_argument("id")
    d.add_argument("--result", required=True, help="what Chrome did")
    common(d)
    f = sub.add_parser("fail", help="record a failed attempt (the item stays pending)")
    f.add_argument("id")
    f.add_argument("--reason", required=True)
    common(f)
    e = sub.add_parser("expire", help="expire items past their deadline and print their fallbacks")
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
