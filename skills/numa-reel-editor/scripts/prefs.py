#!/usr/bin/env python3
"""Feedback memory: Katie's revision notes, kept so she never repeats one (spec p.30 #8).

Usage:
    prefs.py add    --file FILE "NOTE" [--date YYYY-MM-DD]
    prefs.py list   --file FILE [--json]
    prefs.py limits --file FILE [--json]
    prefs.py export --file FILE --out FILE

The preferences file is durable in Drive `_Plan/` with a local copy (the
Librarian syncs it); every run reads it. Its shape:

    {"schema_version": 1,
     "notes": [{"id": 1, "text": "fewer whips", "key": "fewer whips", "rule": "fewer_whips",
                "first_date": "2026-12-03", "last_date": "2026-12-09", "times": 2}],
     "limits": {"max_whips": 0}}

`limits` is regenerated on every write, so the file itself can be passed to
`validate_plan.py --prefs` and `baseline_plan.py --prefs` (both read a
top-level "limits" object). `limits --json` / `export` give the bare object.

De-duplication: a note is matched to an earlier one by its normalized text
(case, punctuation, filler words like "please" and "a bit" ignored) or by the
rule it maps to ("fewer whips" and "too many whip transitions" are the same
note). A repeat is not stored twice: the earlier note's `times` goes up and its
limit tightens one step, because a repeated note means the last change was not
enough. Notes no rule understands are still kept (the Director reads them).

Numeric rules (key, first value, step per repeat, bound). The validate_plan.py
rule 38 keys are honoured today by the validator/baseline; caption_px,
min_people_shots and max_hook_words are recorded for the engine/planner.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

PREFS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Rule:
    id: str
    key: str
    first: float
    step: float
    bound: float
    patterns: tuple[str, ...]

    def value(self, times: int) -> float:
        v = self.first + self.step * (max(1, times) - 1)
        v = max(v, self.bound) if self.step < 0 else min(v, self.bound)
        return int(v) if float(v).is_integer() else round(v, 3)


LESS = r"(fewer|less|not so many|too many|too much|cut( down)?( on)?( the)?|tone down( the)?)"
NONE = r"(no|no more|don'?t use( any)?|do not use( any)?|never use( any)?|stop using( the)?|without( any)?|lose the|drop the)"
# First match wins: specific rules (captions, hooks, whole-reel length) come before the general ones,
# and "none" rules (max = 0) before "fewer" rules.
RULES: tuple[Rule, ...] = (
    Rule("no_whips", "max_whips", 0, 0, 0, (rf"\b{NONE} whips?\b", r"\bwhips?\b.{0,10}\b(never|none)\b")),
    Rule("fewer_whips", "max_whips", 1, -1, 0, (LESS + r" .{0,20}\bwhip", r"\bwhips?\b.{0,20}\b(too many|less|fewer|too much)\b")),
    Rule("no_flashes", "max_flashes", 0, 0, 0, (rf"\b{NONE} (white )?flash(es)?\b",)),
    Rule("fewer_flashes", "max_flashes", 1, -1, 0, (LESS + r" .{0,20}\bflash", r"\bflash(es)?\b.{0,20}\b(too many|less|fewer)\b")),
    Rule("softer_leaks", "max_leak_strength", 0.35, -0.1, 0.1,
         (r"\b(softer|subtler|gentler|lighter|weaker)\b.{0,20}\b(light )?leaks?\b", r"\bleaks?\b.{0,20}\btoo (strong|bright)\b")),
    Rule("no_leaks", "max_leaks", 0, 0, 0, (rf"\b{NONE} (light )?leaks?\b",)),
    Rule("fewer_leaks", "max_leaks", 1, -1, 0, (LESS + r" .{0,20}\b(light )?leaks?\b",)),
    Rule("shorter_captions", "max_caption_chars", 50, -10, 25,
         (r"\bshorter (captions?|caption lines|lines|text)\b", r"\b(less|fewer) (words|text)\b",
          r"\b(captions?|caption lines|text)\b.{0,12}\btoo long\b")),
    Rule("shorter_hooks", "max_hook_words", 6, -1, 3,
         (r"\bshorter hooks?\b", r"\bhooks?\b.{0,12}\btoo long\b", r"\b(punchier|tighter) hooks?\b")),
    Rule("bigger_captions", "caption_px", 104, 8, 120,
         (r"\b(bigger|larger) (captions?|text|words|font)\b", r"\b(captions?|text)\b.{0,12}\btoo small\b")),
    Rule("smaller_captions", "caption_px", 84, -6, 72,
         (r"\bsmaller (captions?|text|words|font)\b", r"\b(captions?|text)\b.{0,12}\btoo (big|large)\b")),
    Rule("fewer_gold_words", "max_gold_words", 1, 0, 1, (LESS + r" .{0,10}\bgold\b",)),
    Rule("shorter_reels", "max_duration", 45, -5, 15,
         (r"\bshorter (reels?|videos?)\b", r"\b(reels?|videos?)\b.{0,12}\btoo long\b")),
    Rule("longer_reels", "min_duration", 30, 5, 60,
         (r"\blonger (reels?|videos?)\b", r"\b(reels?|videos?)\b.{0,12}\btoo short\b")),
    Rule("slower_cuts", "min_shot_seconds", 1.0, 0.25, 2.0,
         (r"\bslower (cuts|pace|pacing|edit)", r"\btoo (fast|choppy|frantic|busy)\b", r"\blonger shots?\b",
          r"\b(fewer|less) cuts\b", r"\blet (the )?shots breathe\b")),
    Rule("faster_cuts", "max_shot_seconds", 3.0, -0.5, 1.5,
         (r"\bfaster (cuts|pace|pacing|edit)", r"\btoo slow\b", r"\bshorter shots?\b", r"\bmore cuts\b", r"\bsnappier\b")),
    Rule("more_people", "min_people_shots", 2, 1, 6,
         (r"\bmore (people|faces|members|humans)\b", r"\b(too empty|not enough people)\b")),
)
# Pairs where the later note wins (they set the same key or contradict each other).
OPPOSITES = {("min_shot_seconds", "max_shot_seconds"), ("min_duration", "max_duration")}
FILLER = r"\b(please|pls|a bit|a little|a lot|slightly|much|way|kind of|kinda|just|the|on|in|of|use|using|more of|again)\b"


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = re.sub(FILLER, " ", t)
    return " ".join(t.split())


def match_rule(text: str) -> Rule | None:
    t = " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'")).split())
    for r in RULES:
        if any(re.search(p, t) for p in r.patterns):
            return r
    return None


RULE_BY_ID = {r.id: r for r in RULES}


def compute_limits(notes: list[dict]) -> dict:
    """Notes in order; later notes override earlier ones on the same key; contradictions keep the later one."""
    limits: dict[str, float] = {}
    order: dict[str, int] = {}
    for i, n in enumerate(sorted(notes, key=lambda n: (n.get("last_date") or "", n["id"]))):
        r = RULE_BY_ID.get(n.get("rule") or "")
        if r is None:
            continue
        limits[r.key] = r.value(int(n.get("times", 1)))
        order[r.key] = i
    for lo, hi in OPPOSITES:
        if lo in limits and hi in limits and limits[lo] > limits[hi]:
            older = lo if order[lo] < order[hi] else hi
            del limits[older]
    return dict(sorted(limits.items()))


def load(path: Path, create: bool = False) -> dict:
    if not path.exists() and create:
        return {"schema_version": PREFS_SCHEMA_VERSION, "notes": [], "limits": {}}
    data = nc.read_json(path, "preferences file")
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        raise nc.UserError(f"preferences file {path}: expected an object with a 'notes' list")
    for i, n in enumerate(data["notes"]):
        if not isinstance(n, dict) or not isinstance(n.get("text"), str) or not isinstance(n.get("id"), int):
            raise nc.UserError(f"preferences file {path}: notes[{i}] needs an integer id and a text")
        if n.get("rule") is not None and n["rule"] not in RULE_BY_ID:
            raise nc.UserError(f"preferences file {path}: notes[{i}]: unknown rule {n['rule']!r}")
    return data


def save(path: Path, data: dict) -> None:
    data["schema_version"] = PREFS_SCHEMA_VERSION
    data["limits"] = compute_limits(data["notes"])
    nc.write_json(path, data)


def add_note(data: dict, text: str, day: str) -> tuple[dict, bool]:
    """Append or merge a note. Returns (the note, True when it was new)."""
    text = " ".join(text.split())
    if not text:
        raise nc.UserError("the note is empty")
    key = normalize(text)
    rule = match_rule(text)
    for n in data["notes"]:
        same_rule = rule is not None and n.get("rule") == rule.id
        if n.get("key") == key or same_rule:
            n["times"] = int(n.get("times", 1)) + 1
            n["last_date"] = max(day, n.get("last_date") or day)
            if text.lower() != n["text"].lower() and text not in n.setdefault("wordings", []):
                n["wordings"].append(text)
            return n, False
    note = {"id": 1 + max([n["id"] for n in data["notes"]] or [0]), "text": text, "key": key,
            "rule": rule.id if rule else None, "first_date": day, "last_date": day, "times": 1}
    data["notes"].append(note)
    return note, True


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="prefs.py", description="Feedback memory: revision notes and the numeric limits they imply.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    a = sub.add_parser("add", help="record a revision note (repeats are merged)")
    a.add_argument("--file", required=True)
    a.add_argument("note", metavar="NOTE")
    a.add_argument("--date", "--today", dest="date", help="YYYY-MM-DD (default: today)")
    li = sub.add_parser("list", help="every note")
    li.add_argument("--file", required=True)
    li.add_argument("--json", action="store_true")
    lm = sub.add_parser("limits", help="numeric limits for --prefs")
    lm.add_argument("--file", required=True)
    lm.add_argument("--json", action="store_true")
    ex = sub.add_parser("export", help="write the limits as a --prefs file")
    ex.add_argument("--file", required=True)
    ex.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: add, list, limits or export")
    path = Path(args.file).expanduser().resolve()

    if args.cmd == "add":
        try:
            day = date.fromisoformat(args.date).isoformat() if args.date else date.today().isoformat()
        except ValueError:
            raise nc.UsageError(f"--date must be YYYY-MM-DD, got {args.date!r}") from None
        data = load(path, create=True)
        note, new = add_note(data, args.note, day)
        save(path, data)
        r = RULE_BY_ID.get(note.get("rule") or "")
        effect = f"; {r.key} = {data['limits'].get(r.key, 'superseded')}" if r else "; no numeric rule (kept for the Director)"
        if new:
            print(f"Added note #{note['id']}: {note['text']}{effect}")
        else:
            print(f"Already noted (#{note['id']} \"{note['text']}\", now {note['times']} times){effect}")
        return 0
    data = load(path)
    if args.cmd == "list":
        if args.json:
            nc.print_json(data["notes"])
        else:
            for n in data["notes"]:
                times = f" (x{n['times']})" if n.get("times", 1) > 1 else ""
                print(f"#{n['id']} {n['last_date']}  {n['text']}{times}" + (f"  [{n['rule']}]" if n.get("rule") else ""))
            if not data["notes"]:
                print("No notes yet.")
        return 0
    limits = compute_limits(data["notes"])
    if args.cmd == "limits":
        if args.json:
            nc.print_json(limits)
        else:
            for k, v in limits.items():
                print(f"{k} = {v}")
            if not limits:
                print("No numeric limits.")
        return 0
    if args.cmd == "export":
        nc.write_json(Path(args.out).expanduser().resolve(), limits)
        print(f"Wrote {len(limits)} limit(s) to {args.out}")
        return 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
