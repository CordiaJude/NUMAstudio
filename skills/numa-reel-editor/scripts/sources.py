#!/usr/bin/env python3
"""Sources and licenses for every outside file in a reel (spec p.4-5, p.19, p.40 hard gate, p.49).

Usage:
    sources.py add   JOB --kind music|photo|clip|voice|stock|font --path FILE --source TEXT --license TEXT
                     [--license-url URL] [--url URL] [--date YYYY-MM-DD]
    sources.py show  JOB [--json]
    sources.py check JOB [--plan PLAN_JSON] [--json]
    sources.py licenses [--json]

JOB is the reel's job (day) folder. `add` records one file in
`JOB/work/sources.json` (the list baseline_plan.py reads for the music
license) and rewrites `JOB/out/sources.txt`, one line per file:

    <file> | <kind> | from <source> <url> | license: <license> <license URL> | <date>

Re-adding the same path replaces its line. `--license` is a known license id
(see `sources.py licenses`) or free text; free text is classified by the same
table, so "Pexels License" and "pexels" both resolve to the Pexels license.

`check` exits 1 when
* the plan's music (default plan: JOB/work/plan.json) has no license, or its
  file has no line in sources.json, or a `sound_collection` source is not the
  Meta Sound Collection;
* any music file in JOB/raw (audio not named like a voiceover), any file in a
  download folder (raw/downloads, raw/stock, raw/scout, raw/library) or named
  like a stock download (pexels-, unsplash-, pixabay-, mixkit-), any plan shot
  outside the job folder and the plugin, and any AI-generated shot has no line;
* any recorded license is not cleared for business social-media use
  (non-commercial, personal-use, editorial-only, trending audio, unknown).
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

KINDS = ("music", "photo", "clip", "voice", "stock", "font")
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff"}
MEDIA_EXT = AUDIO_EXT | {".jpg", ".jpeg", ".png", ".heic", ".webp", ".mp4", ".mov", ".m4v"}
VOICE_NAME = re.compile(r"(^|[^a-z])(vo|voice|voiceover|narrat\w*|memo|speech)([^a-z]|$)", re.I)
DOWNLOAD_DIRS = {"downloads", "download", "stock", "scout", "library"}
DOWNLOAD_NAME = re.compile(r"^(pexels|unsplash|pixabay|mixkit|stock)[-_ ]", re.I)

# License kinds NUMA may use on its business Instagram/Facebook. Data, not code paths:
# id -> name, official URL, whether business social use is allowed, and text patterns that identify it.
# URLs are written without the scheme (scripts never hold web addresses they could fetch; R11).
LICENSES: dict[str, dict[str, Any]] = {
    "numa_owned": {"name": "NUMA-owned (shot by Katie or NUMA's team)", "url": None, "ok": True,
                   "patterns": [r"\bnuma\b.*\bown", r"\bown(ed)? by numa\b", r"\bkatie\b", r"\bnuma[- ]owned\b"]},
    "pexels": {"name": "Pexels License", "url": "www.pexels.com/license/", "ok": True, "patterns": [r"\bpexels\b"]},
    "unsplash": {"name": "Unsplash License", "url": "unsplash.com/license", "ok": True, "patterns": [r"\bunsplash\b"]},
    "pixabay": {"name": "Pixabay Content License", "url": "pixabay.com/service/license-summary/", "ok": True,
                "patterns": [r"\bpixabay\b"]},
    "mixkit": {"name": "Mixkit License", "url": "mixkit.co/license/", "ok": True, "patterns": [r"\bmixkit\b"]},
    "higgsfield_paid": {"name": "Higgsfield paid plan (commercial use included)", "url": "higgsfield.ai/terms",
                        "ok": True,
                        "patterns": [r"\bhiggsfield\b.*\b(paid|plus|pro|ultra|creator|business|team|enterprise|"
                                     r"starter|basic|subscription|annual|monthly)\b"]},
    "meta_sound_collection": {"name": "Meta Sound Collection", "url": "www.facebook.com/sound/collection/",
                              "ok": True, "patterns": [r"\bsound collection\b", r"\bmeta sound\b"]},
    "cc0": {"name": "CC0 / public domain", "url": "creativecommons.org/publicdomain/zero/1.0/", "ok": True,
            "patterns": [r"\bcc0\b", r"\bpublic domain\b"]},
    "cc_by": {"name": "Creative Commons Attribution (credit in the caption)", "url": "creativecommons.org/licenses/by/4.0/",
              "ok": True, "patterns": [r"\bcc[- ]by(?![- ]?nc)(?![- ]?nd)\b(?!-nc)", r"creative commons attribution(?! ?-? ?non)"]},
    "ofl": {"name": "SIL Open Font License", "url": "openfontlicense.org/", "ok": True,
            "patterns": [r"\bofl\b", r"open font license", r"\bliberation\b"]},
    "partner_permission": {"name": "Written permission from a collab partner", "url": None, "ok": True,
                           "patterns": [r"\b(written|signed|email(ed)?) permission\b",
                                        r"\bpermission (granted|given|received|in writing)\b",
                                        r"\bcollab partner\b.*\b(permission|agreement|approved)\b"]},
    # Not allowed on a business account:
    "no_permission": {"name": "No permission (missing, pending or refused)", "url": None, "ok": False,
                      "patterns": [r"\b(no|without|missing|pending|awaiting|requested|refused|denied|declined)\b.{0,20}"
                                   r"\bpermission\b", r"\bpermission\b.{0,20}\b(pending|requested|asked|not|refused|"
                                   r"denied|declined|awaiting|tbd|unclear)\b"]},
    "higgsfield_free": {"name": "Higgsfield free plan or trial (no commercial use)", "url": "higgsfield.ai/terms",
                        "ok": False, "patterns": [r"\bhiggsfield\b.*\b(free|trial|unpaid)\b",
                                                  r"\b(free|trial)\b.*\bhiggsfield\b"]},
    "higgsfield_unstated": {"name": "Higgsfield, plan not stated (only paid plans include commercial use)",
                            "url": "higgsfield.ai/terms", "ok": False, "last": True, "patterns": [r"\bhiggsfield\b"]},
    "non_commercial": {"name": "Non-commercial only", "url": None, "ok": False,
                       "patterns": [r"non[- ]?commercial", r"\bcc[- ]by[- ]nc", r"\bnc\b"]},
    "personal_use": {"name": "Personal use only", "url": None, "ok": False, "patterns": [r"personal use"]},
    "editorial_only": {"name": "Editorial use only", "url": None, "ok": False, "patterns": [r"editorial"]},
    "trending_audio": {"name": "Trending / commercial song (not licensed for business accounts)", "url": None,
                       "ok": False, "patterns": [r"\btrending\b", r"\btiktok sound\b", r"\bspotify\b", r"\bitunes\b"]},
    "unknown": {"name": "Unknown license", "url": None, "ok": False,
                "patterns": [r"^\s*(unknown|none|n/?a|tbd|\?)\s*$", r"\bnot sure\b", r"\bfound (it )?online\b", r"\bgoogle images\b"]},
}
# Checked first: a "not allowed" match beats an allowed one ("Pixabay ... non-commercial").
# Catch-alls marked "last" are tried after everything else ("Higgsfield" with no plan named).
_ORDER = ([k for k, v in LICENSES.items() if not v["ok"] and not v.get("last")]
          + [k for k, v in LICENSES.items() if v["ok"]] + [k for k, v in LICENSES.items() if v.get("last")])


def classify(text: str | None) -> str | None:
    """License id for a license text or id; None when nothing matches."""
    if not text or not text.strip():
        return None
    t = text.strip().lower()
    if t in LICENSES:
        return t
    for lid in _ORDER:
        if any(re.search(p, t) for p in LICENSES[lid]["patterns"]):
            return lid
    return None


def license_ok(text: str | None) -> tuple[bool, str]:
    lid = classify(text)
    if lid is None:
        return False, f"license {text!r} is not a known business/social-use license (see sources.py licenses)"
    if not LICENSES[lid]["ok"]:
        return False, f"license {text!r} is {LICENSES[lid]['name']}: not allowed on NUMA's business account"
    return True, LICENSES[lid]["name"]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def job_paths(job: str) -> tuple[Path, Path, Path]:
    root = Path(job).expanduser().resolve()
    if not root.is_dir():
        raise nc.UserError(f"job folder not found: {root}")
    return root, root / "work" / "sources.json", root / "out" / "sources.txt"


def load_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = nc.read_json(path, "sources file")
    if not isinstance(data, list) or not all(isinstance(e, dict) and e.get("path") for e in data):
        raise nc.UserError(f"sources file {path}: expected a list of objects with a 'path'")
    return data


def text_line(e: dict) -> str:
    url = f" {e['url']}" if e.get("url") else ""
    lurl = f" {e['license_url']}" if e.get("license_url") else ""
    return (f"{Path(e['path']).name} | {e.get('kind', '?')} | from {e.get('source') or '?'}{url} | "
            f"license: {e.get('license') or 'NONE'}{lurl} | {e.get('added') or '?'}")


def write_all(src_json: Path, src_txt: Path, entries: list[dict]) -> None:
    entries.sort(key=lambda e: (e.get("kind", ""), Path(e["path"]).name.lower(), e["path"]))
    nc.write_json(src_json, entries)
    src_txt.parent.mkdir(parents=True, exist_ok=True)
    header = "Sources and licenses (file | kind | from | license | date added)\n"
    tmp = src_txt.with_name(f".{src_txt.name}.tmp")
    tmp.write_text(header + "".join(text_line(e) + "\n" for e in entries), encoding="utf-8", newline="\n")
    tmp.replace(src_txt)


def _resolved(p: str | None) -> str | None:
    return str(Path(p).expanduser().resolve()) if p else None


def required_files(root: Path, plan: dict | None) -> list[tuple[str, str]]:
    """(path, why) for every file that needs a sources line."""
    out: dict[str, str] = {}
    raw = root / "raw"
    if raw.is_dir():
        for f in sorted(raw.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in MEDIA_EXT:
                continue
            rel = f.relative_to(raw)
            if f.suffix.lower() in AUDIO_EXT and not VOICE_NAME.search(f.stem):
                out[str(f.resolve())] = "music file in the folder"
            elif any(part.lower() in DOWNLOAD_DIRS for part in rel.parts[:-1]) or DOWNLOAD_NAME.match(f.name):
                out[str(f.resolve())] = "downloaded media"
    if plan:
        music = plan.get("music") or {}
        if music.get("path") and music.get("source") not in ("pad", "natural"):
            out[_resolved(music["path"])] = "the plan's music"
        plugin = nc.PLUGIN_ROOT.resolve()
        for i, s in enumerate(plan.get("shots") or []):
            src = _resolved(s.get("src"))
            if not src:
                continue
            p = Path(src)
            if s.get("ai_generated"):
                out.setdefault(src, f"AI-generated shot {i}")
            elif not (p.is_relative_to(root) or p.is_relative_to(plugin)):
                out.setdefault(src, f"shot {i} from outside the job folder")
    return sorted(out.items())


def check(root: Path, entries: list[dict], plan: dict | None) -> list[str]:
    errors: list[str] = []
    by_path = {_resolved(e["path"]): e for e in entries}
    for e in entries:
        ok, why = license_ok(e.get("license"))
        if not ok:
            errors.append(f"{Path(e['path']).name}: {why}")
        if not Path(e["path"]).exists():
            nc.warn(f"{Path(e['path']).name}: recorded in sources.json but the file is missing: {e['path']}")
    for path, why in required_files(root, plan):
        if path not in by_path:
            errors.append(f"{Path(path).name}: no sources line ({why}); record it with sources.py add")
    if plan:
        music = plan.get("music")
        if not music:
            if plan.get("schema_version") == 2:
                errors.append("plan: no music section (record the music and its license)")
        else:
            src = music.get("source")
            if src not in ("natural", "pad"):
                ok, why = license_ok(music.get("license"))
                if not music.get("license"):
                    errors.append(f"plan music ({src}): no license recorded")
                elif not ok:
                    errors.append(f"plan music ({src}): {why}")
                if src == "sound_collection" and classify(music.get("license")) != "meta_sound_collection":
                    errors.append("plan music: source sound_collection needs the Meta Sound Collection license")
    return errors


def load_plan(root: Path, plan_arg: str | None) -> dict | None:
    p = Path(plan_arg).expanduser().resolve() if plan_arg else root / "work" / "plan.json"
    if not p.exists():
        if plan_arg:
            raise nc.UserError(f"plan not found: {p}")
        return None
    plan = nc.read_json(p, "plan")
    if not isinstance(plan, dict):
        raise nc.UserError(f"plan {p}: not a JSON object")
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="sources.py", description="Record and check sources and licenses for a reel.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", parser_class=nc.ArgParser)
    a = sub.add_parser("add", help="record one file's source and license")
    a.add_argument("job", metavar="JOB")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--path", required=True)
    a.add_argument("--source", required=True, help="where it came from: site, Drive, Higgsfield model, Katie ...")
    a.add_argument("--license", required=True, help="license id (sources.py licenses) or text")
    a.add_argument("--license-url", help="license page (default: the known license's URL)")
    a.add_argument("--url", help="page the file came from")
    a.add_argument("--date", "--today", dest="date", help="YYYY-MM-DD (default: today)")
    s = sub.add_parser("show", help="print the sources list")
    s.add_argument("job", metavar="JOB")
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="fail when music or outside media lacks a usable license")
    c.add_argument("job", metavar="JOB")
    c.add_argument("--plan", metavar="PLAN_JSON", help="default: JOB/work/plan.json when present")
    c.add_argument("--json", action="store_true")
    li = sub.add_parser("licenses", help="known license kinds")
    li.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        raise nc.UsageError("choose a command: add, show, check or licenses")

    if args.cmd == "licenses":
        if args.json:
            nc.print_json({k: {kk: vv for kk, vv in v.items() if kk not in ("patterns", "last")} for k, v in LICENSES.items()})
        else:
            for k, v in LICENSES.items():
                print(f"{k:<22} {'allowed' if v['ok'] else 'NOT allowed':<12} {v['name']}" + (f"  {v['url']}" if v["url"] else ""))
        return 0

    root, src_json, src_txt = job_paths(args.job)
    entries = load_entries(src_json)
    if args.cmd == "add":
        try:
            day = date.fromisoformat(args.date).isoformat() if args.date else date.today().isoformat()
        except ValueError:
            raise nc.UsageError(f"--date must be YYYY-MM-DD, got {args.date!r}") from None
        path = Path(args.path).expanduser().resolve()
        if not path.exists():
            raise nc.UserError(f"file not found: {path}")
        lid = classify(args.license)
        lic = LICENSES[lid]["name"] if lid and args.license.strip().lower() == lid else args.license.strip()
        entry = {"kind": args.kind, "path": str(path), "source": args.source.strip(), "license": lic,
                 "license_kind": lid, "license_url": args.license_url or (LICENSES[lid]["url"] if lid else None),
                 "url": args.url, "added": day}
        entries = [e for e in entries if _resolved(e["path"]) != str(path)] + [entry]
        write_all(src_json, src_txt, entries)
        ok, why = license_ok(lic)
        if not ok:
            nc.warn(f"{path.name}: {why}")
        print(text_line(entry))
        return 0
    if args.cmd == "show":
        if args.json:
            nc.print_json(entries)
        else:
            for e in entries:
                print(text_line(e))
            if not entries:
                print("No sources recorded.")
        return 0
    if args.cmd == "check":
        plan = load_plan(root, args.plan)
        errors = check(root, entries, plan)
        if args.json:
            nc.print_json({"ok": not errors, "errors": errors, "entries": len(entries)})
        for e in errors:
            nc.error_line(e)
        if not errors and not args.json:
            print(f"OK: {len(entries)} source(s), every license cleared for business social use")
        return 1 if errors else 0
    raise nc.UsageError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    nc.run_cli(main)
