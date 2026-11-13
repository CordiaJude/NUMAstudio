#!/usr/bin/env python3
"""The Critic's pass rule, computed exactly (spec p.40-41, R211).

Usage:
    critic_score.py score  SCORES_JSON [--gate-failed TEXT ...] [--json]
    critic_score.py round  --rounds FILE --version ID SCORES_JSON [--gate-failed TEXT ...] [--json]
    critic_score.py best   --rounds FILE [--json]

SCORES_JSON (a file, or inline JSON) is the Critic's sheet: every rubric
category of config `critic.rubric` scored as a whole number 1-5 (4 or 4.0), either flat or
under "scores", with optional failed hard gates:

    {"scores": {"hook": 4, "retention_pacing": 4, "story_clarity": 4, "shareability": 4,
                "beat_sync_transitions": 4, "captions": 5, "brand_look": 4, "audio_mix": 4},
     "hard_gates_failed": []}

total = sum(weight x score / 5) (weights sum to 100). PASS when total >= 80,
no category below 3 and hook >= 4 (config `critic.pass`), and no hard gate
failed; any failed hard gate is a FAIL whatever the score. The total is never
rounded before the comparison (79.95 fails).

`round` records one Critic round for a reel in a rounds file (max
`critic.max_rounds` = 3) and prints the decision:
    ship         this version passed;
    revise       failed, rounds left: apply the Critic's fixes and render again;
    ship_best    failed on the last round: ship the best-scoring version so far
                 that failed no hard gate (highest total, then lowest-category
                 score, then hook, then the later round);
    hold         failed on the last round and every version failed a hard gate:
                 nothing may ship; follow the escalation rule.
`best` prints the best shippable version recorded so far.

Exit codes: score 0 = PASS, 1 = FAIL or bad input; round 0 when recorded
(1 on bad input or when the rounds are used up); best 0, or 1 when no version
can ship.
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

ROUNDS_SCHEMA_VERSION = 1


def rubric() -> list[dict]:
    r = [c for c in nc.config_value("critic.rubric", []) or [] if isinstance(c, dict) and c.get("id")]
    if not r:
        raise nc.UserError("config/studio.json has no critic.rubric")
    return r


def pass_rule() -> dict:
    p = nc.config_value("critic.pass", {}) or {}
    return {"min_total": p.get("min_total", 80), "min_category_score": p.get("min_category_score", 3),
            "min_hook_score": p.get("min_hook_score", 4)}


def max_rounds() -> int:
    return int(nc.config_value("critic.max_rounds", 3) or 3)


def parse_sheet(data: Any, rub: list[dict] | None = None) -> tuple[dict[str, int], list[str]]:
    """Validated (scores, failed gates). Every category present, integers 1-5, no unknown categories."""
    rub = rub or rubric()
    if not isinstance(data, dict):
        raise nc.UserError("scores: expected a JSON object")
    gates = data.get("hard_gates_failed", [])
    scores = data.get("scores", data if "scores" not in data else None)
    if not isinstance(scores, dict):
        raise nc.UserError("scores: 'scores' must be an object of category: 1-5")
    scores = {k: v for k, v in scores.items() if k not in ("hard_gates_failed", "notes") and not k.startswith("_")}
    if not isinstance(gates, list) or not all(isinstance(g, str) and g.strip() for g in gates):
        raise nc.UserError("scores: 'hard_gates_failed' must be a list of gate descriptions")
    ids = [c["id"] for c in rub]
    errors = []
    missing = [i for i in ids if i not in scores]
    if missing:
        errors.append(f"missing categories: {', '.join(missing)}")
    unknown = sorted(k for k in scores if k not in ids)
    if unknown:
        errors.append(f"unknown categories: {', '.join(unknown)} (known: {', '.join(ids)})")
    for k in ids:
        v = scores.get(k)
        whole = isinstance(v, int) or (isinstance(v, float) and v.is_integer())  # 4.0 is fine, 4.5 is not
        if k in scores and (isinstance(v, bool) or not whole or not 1 <= v <= 5):
            errors.append(f"{k}: score must be an integer 1-5, got {v!r}")
    if errors:
        raise nc.UserError("scores: " + "; ".join(errors))
    return {k: int(scores[k]) for k in ids}, [g.strip() for g in gates]


def evaluate(scores: dict[str, int], gates_failed: list[str] | None = None, rub: list[dict] | None = None,
             rule: dict | None = None) -> dict:
    rub = rub or rubric()
    rule = rule or pass_rule()
    total = sum((Fraction(str(c["weight"])) * scores[c["id"]] / 5 for c in rub), Fraction(0))
    reasons = []
    if total < Fraction(str(rule["min_total"])):
        reasons.append(f"total {float(total):g} < {rule['min_total']}")
    low = [f"{c['id']} {scores[c['id']]}" for c in rub if scores[c["id"]] < rule["min_category_score"]]
    if low:
        reasons.append(f"categories below {rule['min_category_score']}: {', '.join(low)}")
    hook = scores.get("hook")
    if hook is not None and hook < rule["min_hook_score"]:
        reasons.append(f"hook {hook} < {rule['min_hook_score']}")
    for g in gates_failed or []:
        reasons.append(f"hard gate failed: {g}")
    return {"total": round(float(total), 2), "total_exact": str(total), "passed": not reasons, "reasons": reasons,
            "scores": scores, "hard_gates_failed": list(gates_failed or []),
            "min_category": min(scores.values()), "hook": hook}


def best_version(rounds: list[dict]) -> dict | None:
    ok = [r for r in rounds if not r.get("hard_gates_failed")]
    if not ok:
        return None
    return max(ok, key=lambda r: (Fraction(r["total_exact"]), r["min_category"], r.get("hook") or 0, r["round"]))


def load_rounds(path: Path, create: bool) -> dict:
    if not path.exists() and create:
        return {"schema_version": ROUNDS_SCHEMA_VERSION, "max_rounds": max_rounds(), "rounds": []}
    data = nc.read_json(path, "rounds file")
    if not isinstance(data, dict) or not isinstance(data.get("rounds"), list):
        raise nc.UserError(f"rounds file {path}: expected an object with a 'rounds' list")
    for i, r in enumerate(data["rounds"]):
        if not isinstance(r, dict) or not {"round", "version", "total_exact", "passed", "min_category"} <= set(r):
            raise nc.UserError(f"rounds file {path}: rounds[{i}] is incomplete")
    return data


def load_sheet(arg: str) -> Any:
    v = arg.strip()
    if v.startswith("{"):
        try:
            return json.loads(v)
        except json.JSONDecodeError as e:
            raise nc.UserError(f"scores: invalid JSON: {e.msg}") from None
    return nc.read_json(Path(arg).expanduser(), "scores file")


def describe(res: dict) -> str:
    verdict = "PASS" if res["passed"] else "FAIL"
    tail = "" if res["passed"] else ": " + "; ".join(res["reasons"])
    return f"{verdict} {res['total']:g}/100{tail}"


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="critic_score.py", description="Weighted Critic score and pass rule (spec p.40-41).")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    s = sub.add_parser("score", help="score one sheet; exit 1 on FAIL")
    s.add_argument("scores", metavar="SCORES_JSON")
    s.add_argument("--gate-failed", action="append", default=[], metavar="TEXT", help="a failed hard gate (repeatable)")
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("round", help="record a round and decide: ship, revise, ship_best or hold")
    r.add_argument("--rounds", required=True, metavar="FILE")
    r.add_argument("--version", required=True, metavar="ID", help="the render scored (e.g. a file name)")
    r.add_argument("scores", metavar="SCORES_JSON")
    r.add_argument("--gate-failed", action="append", default=[], metavar="TEXT")
    r.add_argument("--json", action="store_true")
    b = sub.add_parser("best", help="the best shippable version so far")
    b.add_argument("--rounds", required=True, metavar="FILE")
    b.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: score, round or best")

    if args.cmd == "score":
        scores, gates = parse_sheet(load_sheet(args.scores))
        res = evaluate(scores, gates + [g for g in args.gate_failed if g.strip()])
        if args.json:
            nc.print_json(res)
        else:
            print(describe(res))
        return 0 if res["passed"] else 1

    path = Path(args.rounds).expanduser().resolve()
    if args.cmd == "round":
        data = load_rounds(path, create=True)
        limit = int(data.get("max_rounds") or max_rounds())
        if any(r["passed"] for r in data["rounds"]):
            raise nc.UserError(f"{path}: a version already passed (round {next(r['round'] for r in data['rounds'] if r['passed'])}); ship it")
        if len(data["rounds"]) >= limit:
            raise nc.UserError(f"{path}: all {limit} rounds are used; run `best` and ship that version")
        scores, gates = parse_sheet(load_sheet(args.scores))
        res = evaluate(scores, gates + [g for g in args.gate_failed if g.strip()])
        entry = {"round": len(data["rounds"]) + 1, "version": args.version, **res}
        data["rounds"].append(entry)
        if res["passed"]:
            decision, ship = "ship", entry
        elif entry["round"] < limit:
            decision, ship = "revise", None
        else:
            ship = best_version(data["rounds"])
            decision = "ship_best" if ship else "hold"
        data["decision"] = decision
        data["ship_version"] = ship["version"] if ship else None
        nc.write_json(path, data)
        out = {"round": entry["round"], "max_rounds": limit, "result": res, "decision": decision,
               "ship_version": data["ship_version"], "ship_round": ship["round"] if ship else None}
        if args.json:
            nc.print_json(out)
        else:
            print(f"Round {entry['round']}/{limit} ({args.version}): {describe(res)}")
            msg = {"ship": f"Decision: ship {args.version}",
                   "revise": "Decision: revise (apply the Critic's numbered fixes and render again)",
                   "ship_best": f"Decision: ship the best version, {out['ship_version']} (round {out['ship_round']})",
                   "hold": "Decision: hold; every version failed a hard gate, nothing may ship"}[decision]
            print(msg)
        return 0
    if args.cmd == "best":
        data = load_rounds(path, create=False)
        best = best_version(data["rounds"])
        if args.json:
            nc.print_json(best)
        elif best:
            print(f"Best: {best['version']} (round {best['round']}), {best['total']:g}/100, "
                  f"{'passed' if best['passed'] else 'did not pass'}")
        if best is None:
            nc.error_line(f"{path}: no version can ship (none recorded, or every one failed a hard gate)")
            return 1
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
