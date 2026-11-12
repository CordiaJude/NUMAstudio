#!/usr/bin/env python3
"""Scan text for banned health claims (brand.json `claims`), the reusable claims checker.

Usage:
    claims_scan.py [TEXT ...] [--file FILE ...] [--plan PLAN_JSON] [--hashtags TEXT] [--json]

TEXT "-" reads stdin. --file takes plain text, .srt caption files or a plan.json.
Every `fail` hit prints `ERROR: banned claim "<label>" in <where>: "<matched text>"`
and makes the exit code 1; `warn` hits print `WARN:` lines and keep exit 0.

The rules come from brand/brand.json (one banned list for every script, R128):
`claims.banned[]` (severity fail|warn), `claims.allow_exact` / `allow_patterns`
(removed before scanning), `claims.dosing_line` (banned while `blocked`) and
`captions.hashtags.never`. A few spec p.21 rules that are pure text checks and
are not in brand.json are added here: testimonial-outcome phrasing ("cured my
back pain"), the dosing line with any wording ("57 minutes ... 11 ..."),
services NUMA doesn't offer (`offerings.not_offered`, warn) and "breathwork
therapy" when brand.json has no rule for it. "FDA-cleared" fails unless
brand.json confirms the red-light device facts and the text names that device.

Matching is case-insensitive with the patterns' own word boundaries; hyphen and
space variants ("anti-aging", "anti aging", "antiaging") and CamelCase hashtags
("#ColdPlungeDetox") are scanned too.

As a module:
    import claims_scan
    hits = claims_scan.scan_text("Sauna cures stress", where="caption")
    hits = claims_scan.scan_plan(plan_dict)
    claims_scan.has_fail(hits)
"""
from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

FLAGS = re.IGNORECASE

# Spec p.21 rules that are text-checkable but not part of brand.json's banned list.
_OUTCOME_WORDS = (
    r"pain|back|neck|knees?|joints?|shoulders?|anxiety|depression|insomnia|sleep|arthritis|migraines?|headaches?"
    r"|stress|injur\w*|inflammation|blood\s+pressure|skin|acne|wrinkles?|weight|ptsd|trauma|fatigue|sciatica"
    r"|plantar\s+fasciitis|fibromyalgia|symptoms?|condition"
)
BUILTIN_RULES: list[dict] = [
    {
        "id": "testimonial_outcome",
        "label": "testimonial outcome (\"cured my back pain\"): feature the experience, never a health result",
        "severity": "fail",
        "patterns": [
            r"\b(cured|fixed|healed|solved|reversed|erased|eliminated|got\s+rid\s+of|took\s+away|takes\s+away|"
            r"cleared\s+up)\s+(all\s+)?(of\s+)?my\s+(\w+\s+){0,2}?(" + _OUTCOME_WORDS + r")\b",
            r"\bmy\s+(\w+\s+){0,2}?(" + _OUTCOME_WORDS + r")\s+(is|was|are|were|has\s+been|have\s+been)\s+"
            r"(gone|cured|healed|fixed|better|over)\b",
            r"\bno\s+more\s+(\w+\s+){0,1}?(pain|anxiety|depression|insomnia|migraines?|headaches?|arthritis)\b",
            r"\b(i|i've|i\s+have|she|he|they)\s+(lost|dropped|shed)\s+\d+\s*(pounds|lbs?|kilos?|kg)\b",
            r"\b(off|stopped|quit)\s+(my\s+)?(pain\s+)?(meds|medications?|pills|painkillers)\b",
        ],
        "source": "spec p.21 (testimonials are NUMA's claims)",
    },
    {
        "id": "dosing_line_any",
        "label": "the website dosing line (\"57 minutes of sauna and 11 of cold\"), blocked until counsel clears it",
        "severity": "fail",
        "patterns": [
            r"\b57\s*(min|mins|minutes)\b[^.!?\n]{0,60}?\b(sauna|heat|cold|plunge)\b",
            r"\b(sauna|heat)\b[^.!?\n]{0,30}?\b57\s*(min|mins|minutes)\b",
            r"\b11\s*(min|mins|minutes)\b[^.!?\n]{0,30}?\b(cold|plunge|ice)\b",
            r"\b(cold|plunge|ice)\b[^.!?\n]{0,30}?\b11\s*(min|mins|minutes)\b",
        ],
        "source": "spec p.22",
        "needs_dosing_blocked": True,
    },
    {
        "id": "misspelled_claim",
        "label": "a banned claim, misspelled (inflamation, imunity, detocks, artheritis)",
        "severity": "fail",
        "patterns": [r"\binflam(?!m)\w*", r"\bimun(e|ity|ities)\b", r"\bdetocks\w*", r"\bartherit\w*",
                     r"\bcolagen\b", r"\bwrinkels?\b"],
        "source": "spec p.20 (misspellings carry the same claim)",
    },
    {
        "id": "breathwork_therapy",
        "label": "\"breathwork therapy\" from anyone who isn't licensed for it",
        "severity": "fail",
        "patterns": [r"\bbreath[ -]?work[ -]?therap(y|ies|ist|ists)\b"],
        "source": "spec p.21",
        "only_if_brand_lacks": True,
    },
]

_FDA_RULE = "fda"


@dataclass
class Hit:
    rule: str
    label: str
    severity: str
    match: str
    where: str
    suggestion: str | None = None

    def line(self) -> str:
        tail = f' (rule {self.rule}' + (f'; try: "{self.suggestion}")' if self.suggestion else ")")
        if self.severity == "fail":
            return f'banned claim "{self.label}" in {self.where}: "{self.match}"{tail}'
        return f'check wording "{self.label}" in {self.where}: "{self.match}"{tail}'

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@dataclass
class _Rule:
    id: str
    label: str
    severity: str
    patterns: list[re.Pattern]
    suggestion: str | None
    builtin: bool = False
    tag_patterns: list[re.Pattern] = field(default_factory=list)


@dataclass
class _Rules:
    rules: list[_Rule]
    allow_exact: list[str]
    allow_patterns: list[re.Pattern]
    never_tags: set[str]
    not_offered: list[str]
    device_names: list[str]
    say_by_modality: dict[str, str] = field(default_factory=dict)


def _modality_suggestion(claims: dict, patterns: list[re.Pattern]) -> str | None:
    """The first 'say' line of the modality whose 'never_say' list contains this kind of claim."""
    for mod in (claims.get("modalities") or {}).values():
        if not isinstance(mod, dict):
            continue
        never = " | ".join(str(x) for x in mod.get("never_say") or [])
        say = [s for s in mod.get("say") or [] if isinstance(s, str) and "(" not in s]
        if say and any(p.search(never) for p in patterns):
            return say[0]
    return None


def _device_names(claims: dict) -> list[str]:
    """Names of a confirmed FDA-cleared red-light device (brand.json modalities.red_light.device_facts)."""
    node = (claims.get("modalities") or {}).get("red_light", {}).get("device_facts")
    if not isinstance(node, dict) or node.get("status") != "confirmed":
        return []
    val = node.get("value")
    names: list[str] = []
    if isinstance(val, str) and val.strip():
        names.append(val.strip())
    elif isinstance(val, dict):
        for key in ("model", "name", "device"):
            if isinstance(val.get(key), str) and val[key].strip():
                names.append(val[key].strip())
    return names


# Words that name a modality in a text (keys of brand.json claims.modalities).
MODALITY_WORDS = {
    "cold_plunge": r"\b(cold|plunges?|plunging|ice\s*bath|chill)\b",
    "sauna": r"\b(sauna|heat|sweat\w*)\b",
    "red_light": r"\b(red[ -]?light|panels?|wavelengths?|nm)\b",
    "breathwork": r"\b(breath\w*)\b",
}

# Hashtag bodies are matched without word boundaries; these innocent words are blanked first.
TAG_GUARDS = ("secur", "procur", "manicur", "pedicur", "obscur", "traumainformed", "traumaaware",
              "hormonefree", "treatyourself", "treatyoself", "community", "mercury", "curious", "curat")


def _tag_pattern(pat: str) -> re.Pattern | None:
    """A rule pattern for run-together hashtag bodies: word boundaries removed; patterns that need spaces skipped."""
    if re.search(r"\\s|\[ -\]| ", pat):
        loose = re.sub(r"\\s[+*]?\??|\[ -\]\??| ", "", pat)
    else:
        loose = pat
    loose = loose.replace("\\b", "")
    try:
        return re.compile(loose, FLAGS)
    except re.error:
        return None


def build_rules(brand: dict) -> _Rules:
    claims = brand["claims"]
    principle = claims.get("principle")
    rules: list[_Rule] = []
    brand_ids = set()
    for r in claims["banned"]:
        pats = [re.compile(p, FLAGS) for p in r["patterns"]]
        brand_ids.add(r["id"])
        sugg = r.get("rewrite") or _modality_suggestion(claims, pats) or (principle if r.get("severity", "fail") == "fail" else None)
        rules.append(_Rule(r["id"], r["label"], r.get("severity", "fail"), pats, sugg))
        rules[-1].tag_patterns = [tp for tp in map(_tag_pattern, r["patterns"]) if tp] \
            if r.get("severity", "fail") == "fail" else []
    dosing = claims.get("dosing_line") or {}
    blocked = bool(dosing.get("blocked"))
    if blocked and dosing.get("patterns"):
        rules.append(_Rule("dosing_line", "the website dosing line, blocked until counsel clears it", "fail",
                           [re.compile(p, FLAGS) for p in dosing["patterns"]], principle))
    for b in BUILTIN_RULES:
        if b.get("only_if_brand_lacks") and b["id"] in brand_ids:
            continue
        if b.get("needs_dosing_blocked") and not blocked:
            continue
        pats = [re.compile(p, FLAGS) for p in b["patterns"]]
        rules.append(_Rule(b["id"], b["label"], b["severity"], pats, _modality_suggestion(claims, pats) or principle, True,
                           [tp for tp in map(_tag_pattern, b["patterns"]) if tp] if b["id"] == "misspelled_claim" else []))
    not_offered = [str(x) for x in (nc.fact(brand.get("offerings", {}).get("not_offered")) or []) if x]
    never = {t.lower() for t in (brand.get("captions", {}).get("hashtags", {}).get("never") or [])}
    return _Rules(
        rules=rules,
        allow_exact=[p for p in claims.get("allow_exact", []) if p],
        allow_patterns=[re.compile(p, FLAGS) for p in claims.get("allow_patterns", [])],
        never_tags=never,
        not_offered=not_offered,
        device_names=_device_names(claims),
        say_by_modality={k: say[0] for k, m in (claims.get("modalities") or {}).items() if isinstance(m, dict)
                         for say in [[x for x in m.get("say") or [] if isinstance(x, str) and "(" not in x]] if say},
    )


@lru_cache(maxsize=4)
def _rules_for(path: str, mtime: int) -> _Rules:
    return build_rules(nc.load_brand(path))


def load_rules(brand: dict | None = None) -> _Rules:
    """Compiled rules for brand.json (or the given brand dict)."""
    if brand is not None:
        return build_rules(brand)
    p = nc.brand_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        mtime = -1
    return _rules_for(str(p), mtime)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_HASHTAG = re.compile(r"#(\w+)")


# Common Cyrillic/Greek letters that look like Latin ones.
CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "ɡ": "g",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X",
    "\u200b": None, "\u200c": None, "\u200d": None, "\u2060": None, "\ufeff": None, "\u00ad": None,
})
_SPACED = re.compile(r"(?<![\w.])(?:[^\W\d_][\s.\-_*·•]+){2,}[^\W\d_](?![\w])")


def normalize(text: str) -> str:
    """NFKC, look-alike Cyrillic/Greek letters mapped to Latin, invisible characters removed."""
    return unicodedata.normalize("NFKC", text).translate(CONFUSABLES)


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _remove_allowed(text: str, rules: _Rules) -> str:
    for phrase in rules.allow_exact:
        for m in list(re.finditer(re.escape(phrase), text, FLAGS)):
            text = _blank(text, m.start(), m.end())
    for pat in rules.allow_patterns:
        for m in list(pat.finditer(text)):
            text = _blank(text, m.start(), m.end())
    return text


def _variants(text: str) -> list[str]:
    """The text plus hyphen/space variants and split CamelCase hashtags."""
    out = [text]
    spaced = re.sub(r"(?<=\w)[-‐‑–](?=\w)", " ", text)
    joined = re.sub(r"(?<=\w)[-‐‑–](?=\w)", "", text)
    tags = " ".join(_CAMEL.sub(" ", m.group(1)).replace("_", " ") for m in _HASHTAG.finditer(text))
    collapsed = _SPACED.sub(lambda m: re.sub(r"[\s.\-_*·•]+", "", m.group(0)), text)
    for v in (spaced, joined, tags, collapsed):
        if v and v not in out:
            out.append(v)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_#]+", "", s.lower())


def scan_text(text: str, where: str = "text", brand: dict | None = None) -> list[Hit]:
    """All claim hits in one text. Warn hits overlapping a fail hit are dropped; duplicates merged."""
    rules = load_rules(brand)
    hits: list[Hit] = []
    seen: set[tuple[str, str]] = set()
    if not text or not text.strip():
        return hits
    text = normalize(text)
    mentioned = [(m.start(), k) for k, pat in MODALITY_WORDS.items() if k in rules.say_by_modality
                 for m in [re.search(pat, text, FLAGS)] if m]
    text_say = rules.say_by_modality[min(mentioned)[1]] if mentioned else None
    hit_rules: set[str] = set()
    for variant in _variants(text):
        clean = _remove_allowed(variant, rules)
        found: list[tuple[int, int, _Rule, str]] = []
        for rule in rules.rules:
            for pat in rule.patterns:
                for m in pat.finditer(clean):
                    if m.end() > m.start():
                        found.append((m.start(), m.end(), rule, m.group(0)))
        fail_spans = [(s, e) for s, e, r, _ in found if r.severity == "fail"]
        brand_fail_spans = [(s, e) for s, e, r, _ in found if r.severity == "fail" and not r.builtin]
        for s, e, rule, matched in found:
            severity = rule.severity
            if severity == "warn" and any(s < fe and fs < e for fs, fe in fail_spans):
                continue
            if rule.builtin and any(s < fe and fs < e for fs, fe in brand_fail_spans):
                continue  # already reported by the brand.json rule
            if rule.id == _FDA_RULE and re.search(r"clear", matched, FLAGS) and rules.device_names and any(
                    re.search(re.escape(d), text, FLAGS) for d in rules.device_names):
                severity = "warn"  # FDA-cleared naming the confirmed device: allowed, but have it checked
            key = (rule.id, _norm(matched))
            if key in seen:
                continue
            seen.add(key)
            hit_rules.add(rule.id)
            sugg = (text_say or rule.suggestion) if rule.suggestion else None
            hits.append(Hit(rule.id, rule.label, severity, " ".join(matched.split()), where, sugg))
    for m in _HASHTAG.finditer(text):  # run-together hashtags: #sundaydetox, #boostimmunity
        body = m.group(1).lower().replace("_", "")
        for g in TAG_GUARDS:
            body = body.replace(g, " " * len(g))
        for rule in rules.rules:
            if rule.id in hit_rules or rule.severity != "fail":
                continue
            if any(tp.search(body) for tp in rule.tag_patterns):
                hit_rules.add(rule.id)
                seen.add((rule.id, _norm(m.group(0))))
                hits.append(Hit(rule.id, rule.label, "fail", "#" + m.group(1), where,
                                text_say or rule.suggestion))
    for m in _HASHTAG.finditer(text):
        tag = "#" + m.group(1)
        if tag.lower() in rules.never_tags and ("hashtag_never", tag.lower()) not in seen:
            seen.add(("hashtag_never", tag.lower()))
            hits.append(Hit("hashtag_never", "hashtag on the never-use list (brand.json captions.hashtags.never)",
                            "fail", tag, where, None))
    for service in rules.not_offered:
        pat = r"\b" + r"[\s-]*".join(re.escape(w) for w in service.split()) + r"\b"
        m = re.search(pat, text, FLAGS) or re.search(r"#" + re.escape(re.sub(r"\s+", "", service)), text, FLAGS)
        if m and ("not_offered", _norm(service)) not in seen:
            seen.add(("not_offered", _norm(service)))
            hits.append(Hit("not_offered", f"{service}: a service NUMA doesn't offer; never show or imply it",
                            "warn", m.group(0), where, None))
    return hits


def has_fail(hits: Iterable[Hit]) -> bool:
    return any(h.severity == "fail" for h in hits)


def _text(v: Any) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


def plan_texts(plan: dict) -> list[tuple[str, str]]:
    """Every on-screen text of a plan as (where, text): hook, caption lines, text cards, end card, formats, meta title."""
    out: list[tuple[str, str]] = []
    if not isinstance(plan, dict):
        return out
    hook = plan.get("hook")
    if isinstance(hook, dict) and _text(hook.get("text")):
        out.append(("hook.text", hook["text"]))
    for i, ln in enumerate(plan.get("lines") or []):
        if isinstance(ln, dict) and isinstance(ln.get("words"), list):
            words = [str(w[0]) for w in ln["words"] if isinstance(w, list) and w and isinstance(w[0], str)]
            if words:
                out.append((f"lines[{i}]", " ".join(words)))
    for i, card in enumerate(plan.get("cards") or []):
        if isinstance(card, dict):
            for k in ("text", "sub"):
                if _text(card.get(k)):
                    out.append((f"cards[{i}].{k}", card[k].replace("*", "")))
    ec = plan.get("endcard")
    if isinstance(ec, dict):
        for k in ("tagline", "subtitle"):
            if _text(ec.get(k)):
                out.append((f"endcard.{k}", ec[k]))
    fm = plan.get("formats")
    if isinstance(fm, dict):
        rc = fm.get("reach_cut")
        if isinstance(rc, dict) and _text(rc.get("hook")):
            out.append(("formats.reach_cut.hook", rc["hook"]))
        for key in ("story", "carousel", "hook_variants"):
            for i, item in enumerate(fm.get(key) or []):
                if isinstance(item, dict) and _text(item.get("text")):
                    out.append((f"formats.{key}[{i}].text", item["text"]))
        cover = fm.get("cover")
        if isinstance(cover, dict) and _text(cover.get("title")):
            out.append(("formats.cover.title", cover["title"]))
    meta = plan.get("meta")
    if isinstance(meta, dict) and _text(meta.get("title")):
        out.append(("meta.title", meta["title"]))
    return out


def scan_plan(plan: dict, brand: dict | None = None, prefix: str = "") -> list[Hit]:
    hits: list[Hit] = []
    for where, text in plan_texts(plan):
        hits += scan_text(text, f"{prefix}{where}", brand)
    return hits


_SRT_TIME = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}.*$")


def srt_text(text: str) -> str:
    """Caption text of an .srt/.vtt file: cue numbers, timings and tags removed."""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.isdigit() or s.upper() == "WEBVTT" or _SRT_TIME.match(s):
            continue
        lines.append(re.sub(r"<[^>]+>", "", s))
    return "\n".join(lines)


def scan_file(path: str | Path, brand: dict | None = None) -> list[Hit]:
    """A plan.json (every text field), an .srt/.vtt caption file, or any text file (line by line)."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = nc.read_json(p, "file")
        if isinstance(data, dict) and "shots" in data:
            return scan_plan(data, brand, prefix=f"{p.name}:")
        raise nc.UserError(f"{p}: a JSON file to scan must be a plan.json (with 'shots')")
    if not p.exists():
        raise nc.UserError(f"file not found: {p}")
    if p.is_dir():
        raise nc.UserError(f"expected a text file but got a folder: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise nc.UserError(f"{p} is not UTF-8 text") from None
    if p.suffix.lower() in (".srt", ".vtt"):
        text = srt_text(text)
    hits: list[Hit] = []
    for n, line in enumerate(text.splitlines(), 1):
        hits += scan_text(line, f"{p.name} line {n}", brand)
    return hits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="claims_scan.py",
                      description="Scan text, caption files and plans for banned health claims (brand.json claims).")
    ap.add_argument("texts", nargs="*", metavar="TEXT", help='text to scan ("-" reads stdin)')
    ap.add_argument("--file", action="append", default=[], metavar="FILE", help="text, .srt or plan.json file (repeatable)")
    ap.add_argument("--plan", metavar="PLAN_JSON", help="scan every text field of a plan")
    ap.add_argument("--hashtags", action="append", default=[], metavar="TEXT", help="hashtags to scan")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not (args.texts or args.file or args.plan or args.hashtags):
        ap.print_usage(sys.stderr)
        raise nc.UsageError("nothing to scan: give TEXT, --file, --plan or --hashtags")

    nc.load_brand()  # fail early, readably, on a broken brand.json
    hits: list[Hit] = []
    for i, t in enumerate(args.texts):
        if t == "-":
            hits += scan_text(sys.stdin.read(), "stdin")
        else:
            hits += scan_text(t, f"text {i + 1}" if len(args.texts) > 1 else "text")
    for f in args.file:
        hits += scan_file(Path(f).expanduser().resolve())
    if args.plan:
        plan = nc.read_json(Path(args.plan).expanduser().resolve(), "plan")
        hits += scan_plan(plan, prefix="plan ")
    for i, t in enumerate(args.hashtags):
        hits += scan_text(t, "hashtags")

    fails = [h for h in hits if h.severity == "fail"]
    warns = [h for h in hits if h.severity != "fail"]
    for h in warns:
        nc.warn(h.line())
    for h in fails:
        nc.error_line(h.line())
    if args.json:
        nc.print_json({"ok": not fails, "fail": len(fails), "warn": len(warns), "hits": [h.as_dict() for h in hits]})
    else:
        print("OK: no banned claims" + (f" ({len(warns)} wording warnings)" if warns else "") if not fails
              else f"FAILED: {len(fails)} banned claim(s), {len(warns)} warning(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    nc.run_cli(main)
