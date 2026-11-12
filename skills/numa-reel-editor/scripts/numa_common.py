#!/usr/bin/env python3
"""Shared helpers for the NUMA Studio scripts.

Every stage script imports this module from its own folder:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import numa_common as nc

What it provides (see docs/CONTRACTS.md for the conventions):

* Locations resolved from this file, so scripts work from any working directory:
  PLUGIN_ROOT, SKILL_DIR, SCRIPTS_DIR, ASSETS_DIR, FONTS_DIR, BRAND_PHOTOS_DIR,
  SCHEMAS_DIR, BRAND_PATH, CONFIG_PATH, plugin_path().
* ffmpeg_bin() / ffprobe_bin(): the system binaries, else the imageio-ffmpeg
  fallback. imageio-ffmpeg ships ffmpeg only, so ffprobe_bin() may return None;
  ffprobe_json() and media_info() then parse `ffmpeg -i` output instead.
* load_brand(), load_config(): brand/brand.json and config/studio.json, cached
  and validated. NUMA_BRAND / NUMA_CONFIG environment variables point at other
  files (tests, other businesses).
* read_json() / write_json(): readable errors; atomic writes with indent 2.
* UserError, UsageError and run_cli(main): one-line `ERROR:` messages and exit
  codes 1 (user/input error) and 2 (usage), never a traceback (set
  NUMA_DEBUG=1 to see one for unexpected errors).
* validate_against() / schema_errors(): JSON Schema checks with readable paths
  such as `shots[3].tr`.
* run() / ffmpeg(): subprocess helpers that raise UserError with the stderr tail.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRAND_PHOTOS_DIR = ASSETS_DIR / "brand-photos"
PLUGIN_ROOT = SKILL_DIR.parent.parent
SCHEMAS_DIR = PLUGIN_ROOT / "schemas"
BRAND_PATH = PLUGIN_ROOT / "brand" / "brand.json"
CONFIG_PATH = PLUGIN_ROOT / "config" / "studio.json"

PLAN_SCHEMA_VERSION = 2
ANALYSIS_SCHEMA_VERSION = 2
BRAND_SCHEMA_VERSION = 2

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def plugin_path(p: str | os.PathLike) -> Path:
    """Resolve a path stored in brand/config data: absolute stays, relative is under PLUGIN_ROOT."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else (PLUGIN_ROOT / p).resolve()


# ---------------------------------------------------------------------------
# Errors and CLI wrapper
# ---------------------------------------------------------------------------
class UserError(Exception):
    """A problem with the user's input or environment. Printed as one `ERROR:` line, exit 1."""


class UsageError(UserError):
    """Wrong command-line usage. Printed as one `ERROR:` line, exit 2."""


def warn(msg: str) -> None:
    """Print a `WARN:` line on stderr."""
    print(f"WARN: {msg}", file=sys.stderr, flush=True)


def error_line(msg: str) -> None:
    """Print an `ERROR:` line on stderr (for scripts that report several errors before exiting 1)."""
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)


def info(msg: str) -> None:
    """Progress/info line on stderr (stdout is kept for results and JSON reports)."""
    print(msg, file=sys.stderr, flush=True)


def print_json(obj: Any) -> None:
    """Machine-readable result on stdout."""
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def run_cli(main: Callable[..., Any], argv: Sequence[str] | None = None) -> None:
    """Run a script's main() and exit with the NUMA Studio conventions.

    main() returns an int exit code (or None for 0). UserError -> exit 1,
    UsageError -> exit 2, bad JSON / missing files -> exit 1, Ctrl-C -> 130,
    anything unexpected -> exit 1. Each prints a single `ERROR: ...` line on
    stderr and no traceback (NUMA_DEBUG=1 adds the traceback for unexpected
    errors). argparse's own usage errors keep exit code 2.
    """
    try:
        rc = main(argv) if argv is not None else main()
    except UsageError as e:
        error_line(_one_line(e))
        sys.exit(EXIT_USAGE)
    except UserError as e:
        error_line(_one_line(e))
        sys.exit(EXIT_ERROR)
    except json.JSONDecodeError as e:
        error_line(f"invalid JSON at line {e.lineno} column {e.colno}: {e.msg}")
        sys.exit(EXIT_ERROR)
    except FileNotFoundError as e:
        error_line(f"file not found: {e.filename or _one_line(e)}")
        sys.exit(EXIT_ERROR)
    except IsADirectoryError as e:
        error_line(f"expected a file but got a folder: {e.filename or _one_line(e)}")
        sys.exit(EXIT_ERROR)
    except NotADirectoryError as e:
        error_line(f"expected a folder: {e.filename or _one_line(e)}")
        sys.exit(EXIT_ERROR)
    except PermissionError as e:
        error_line(f"permission denied: {e.filename or _one_line(e)}")
        sys.exit(EXIT_ERROR)
    except KeyboardInterrupt:
        error_line("interrupted")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - last-resort guard: never show a traceback to Katie
        if os.environ.get("NUMA_DEBUG"):
            traceback.print_exc()
        error_line(f"unexpected {type(e).__name__}: {_one_line(e)} (set NUMA_DEBUG=1 for details)")
        sys.exit(EXIT_ERROR)
    sys.exit(int(rc or 0))


class ArgParser(argparse.ArgumentParser):
    """argparse with the house style: usage errors print `ERROR: ...` and exit 2."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        error_line(message)
        sys.exit(EXIT_USAGE)


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------
def read_json(path: str | os.PathLike, what: str | None = None) -> Any:
    """Load JSON with one-line errors: missing file, folder, unreadable or invalid JSON -> UserError."""
    p = Path(path)
    label = what or "file"
    if not p.exists():
        raise UserError(f"{label} not found: {p}")
    if p.is_dir():
        raise UserError(f"{label} is a folder, expected a JSON file: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise UserError(f"{label} is not UTF-8 text: {p}") from None
    except OSError as e:
        raise UserError(f"cannot read {label} {p}: {e.strerror or e}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise UserError(f"{p}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from None


def dumps_json(obj: Any, *, sort_keys: bool = False) -> str:
    """Serialize the way write_json() does (indent 2, UTF-8, trailing newline)."""
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=sort_keys, allow_nan=False) + "\n"
    except ValueError as e:  # NaN / Infinity
        raise UserError(f"cannot write JSON: {e}") from None
    except TypeError as e:
        raise UserError(f"cannot write JSON: {e}") from None


def write_json(path: str | os.PathLike, obj: Any, *, sort_keys: bool = False) -> Path:
    """Atomically write JSON: temp file in the same folder, fsync, then rename over the target.

    Key order is the dict's insertion order (stable and deterministic) unless
    sort_keys=True. Readers never see a half-written file; on any error the old
    file is untouched and no temp file is left behind.
    """
    p = Path(path)
    data = dumps_json(obj, sort_keys=sort_keys)  # serialize first: fail before touching the disk
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return p


def update_report(out_dir: str | os.PathLike, section: str, data: Any) -> Path:
    """Set one stage's section of `<out_dir>/report.json` (read-modify-write, atomic).

    Each script owns one top-level key (finish, check_output, qa_frames, formats, ...)
    and replaces only that key.
    """
    p = Path(out_dir) / "report.json"
    report = read_json(p, "report") if p.exists() else {}
    if not isinstance(report, dict):
        raise UserError(f"{p} is not a JSON object")
    report.setdefault("schema_version", 1)
    report[section] = data
    return write_json(p, report)


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------
SCHEMA_FILES = {
    "plan": "plan.schema.json",
    "analysis": "analysis.schema.json",
    "brand": "brand.schema.json",
}


@lru_cache(maxsize=None)
def _validator(schema_name: str):
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise UserError("the jsonschema package is missing: pip install -r requirements.txt") from None
    fname = SCHEMA_FILES.get(schema_name, schema_name)
    path = SCHEMAS_DIR / fname
    schema = read_json(path, f"schema {schema_name}")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def json_path(parts: Iterable[Any]) -> str:
    """['shots', 3, 'tr'] -> 'shots[3].tr'; [] -> '(top level)'."""
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out or "(top level)"


def _short(value: Any, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _describe(err) -> str:
    v = err.validator
    inst = err.instance
    if v == "required":
        missing = [k for k in err.validator_value if isinstance(inst, dict) and k not in inst]
        return f"missing required field {', '.join(repr(m) for m in missing)}" if missing else err.message
    if v == "additionalProperties":
        allowed = set(err.schema.get("properties", {}))
        patterns = list(err.schema.get("patternProperties", {}))
        extra = sorted(
            k for k in inst
            if k not in allowed and not any(re.search(pt, k) for pt in patterns)
        ) if isinstance(inst, dict) else []
        return f"unknown field {', '.join(repr(k) for k in extra)}" if extra else err.message
    if v == "enum":
        return f"{_short(inst)} is not one of {', '.join(json.dumps(x) for x in err.validator_value)}"
    if v == "const":
        return f"must be {json.dumps(err.validator_value)}, got {_short(inst)}"
    if v == "type":
        want = err.validator_value if isinstance(err.validator_value, str) else " or ".join(err.validator_value)
        return f"must be {want}, got {_short(inst)}"
    if v in ("minItems", "maxItems"):
        n = len(inst) if isinstance(inst, list) else "?"
        word = "at least" if v == "minItems" else "at most"
        return f"must have {word} {err.validator_value} items, has {n}"
    if v in ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"):
        op = {"minimum": ">=", "exclusiveMinimum": ">", "maximum": "<=", "exclusiveMaximum": "<"}[v]
        return f"must be {op} {err.validator_value}, got {_short(inst)}"
    if v == "minLength":
        return "must not be empty" if err.validator_value == 1 else f"must be at least {err.validator_value} characters"
    if v == "pattern":
        return f"{_short(inst)} does not match the pattern {err.validator_value}"
    if v == "multipleOf":
        return f"must be a multiple of {err.validator_value}, got {_short(inst)}"
    if v in ("oneOf", "anyOf") and err.context:
        from jsonschema.exceptions import best_match
        sub = best_match(err.context)
        return _describe(sub)
    if v == "false" or err.message.endswith("is not allowed for " + repr(inst)):
        return f"unexpected item {_short(inst)}"
    msg = err.message
    return msg if len(msg) <= 200 else msg[:197] + "..."


def schema_errors(schema_name: str, obj: Any) -> list[str]:
    """All schema violations as readable one-liners: '<path>: <problem>', sorted by path."""
    validator = _validator(schema_name)
    def order(e):
        # int-aware: shots[2] sorts before shots[10]
        return ([(0, p, "") if isinstance(p, int) else (1, 0, str(p)) for p in e.absolute_path], str(e.validator))

    errs = sorted(validator.iter_errors(obj), key=order)
    lines: list[str] = []
    for e in errs:
        line = f"{json_path(e.absolute_path)}: {_describe(e)}"
        if line not in lines:
            lines.append(line)
    return lines


def validate_against(schema_name: str, obj: Any, what: str | None = None, max_shown: int = 8) -> None:
    """Raise UserError listing schema violations (first `max_shown`) if obj doesn't match the schema."""
    errs = schema_errors(schema_name, obj)
    if errs:
        shown = "; ".join(errs[:max_shown])
        more = f" (+{len(errs) - max_shown} more)" if len(errs) > max_shown else ""
        raise UserError(f"{what or schema_name} does not match {SCHEMA_FILES.get(schema_name, schema_name)}: {shown}{more}")


# ---------------------------------------------------------------------------
# Brand and config
# ---------------------------------------------------------------------------
def brand_path() -> Path:
    return Path(os.environ["NUMA_BRAND"]).expanduser() if os.environ.get("NUMA_BRAND") else BRAND_PATH


def config_path() -> Path:
    return Path(os.environ["NUMA_CONFIG"]).expanduser() if os.environ.get("NUMA_CONFIG") else CONFIG_PATH


def _mtime(p: Path) -> int:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return -1


@lru_cache(maxsize=8)
def _load_brand(path: str, _mtime_ns: int) -> dict:
    brand = read_json(path, "brand file")
    validate_against("brand", brand, what=f"brand file {path}")
    claims = brand["claims"]
    rules = list(claims["banned"]) + [
        {"id": "dosing_line", "patterns": claims["dosing_line"]["patterns"]},
        {"id": "allow_patterns", "patterns": claims.get("allow_patterns", [])},
    ]
    for rule in rules:
        for pat in rule["patterns"]:
            try:
                re.compile(pat)
            except re.error as e:
                raise UserError(f"brand file {path}: claims rule {rule['id']!r} has a bad pattern {pat!r}: {e}") from None
    return brand


def load_brand(path: str | os.PathLike | None = None) -> dict:
    """brand/brand.json (or NUMA_BRAND / the given path), validated against brand.schema.json. Cached.

    The returned dict is shared; do not modify it (copy.deepcopy first)."""
    p = Path(path) if path else brand_path()
    return _load_brand(str(p), _mtime(p))


@lru_cache(maxsize=8)
def _load_config(path: str, _mtime_ns: int) -> dict:
    cfg = read_json(path, "config file")
    if not isinstance(cfg, dict):
        raise UserError(f"config file {path} must be a JSON object")
    for key in ("models", "higgsfield", "budget", "critic", "render", "schedule", "instagram", "formats"):
        if key not in cfg:
            raise UserError(f"config file {path} is missing the '{key}' section")
    return cfg


def load_config(path: str | os.PathLike | None = None) -> dict:
    """config/studio.json (or NUMA_CONFIG / the given path). Cached; do not modify the result."""
    p = Path(path) if path else config_path()
    return _load_config(str(p), _mtime(p))


def clear_caches() -> None:
    """Forget cached brand/config/schemas/binaries (tests, long-running callers)."""
    for fn in (_load_brand, _load_config, _validator, ffmpeg_bin, ffprobe_bin):
        clear = getattr(fn, "cache_clear", None)  # absent when a test has swapped the function
        if clear:
            clear()


def dig(data: Any, dotted: str, default: Any = None) -> Any:
    """dig(cfg, 'render.loudness.true_peak_db') -> -1.5. Missing keys return default."""
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def config_value(dotted: str, default: Any = None) -> Any:
    """A value from config/studio.json by dotted path."""
    return dig(load_config(), dotted, default)


def fact(node: Any) -> Any:
    """Unwrap a brand fact {"value": v, "status": s} to v; other values pass through."""
    return node["value"] if isinstance(node, dict) and "value" in node and "status" in node else node


def brand_value(dotted: str, default: Any = None) -> Any:
    """A brand value by dotted path, with facts unwrapped: brand_value('business.name').short works."""
    cur: Any = load_brand()
    for part in dotted.split("."):
        cur = fact(cur)
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return fact(cur)


def hex_to_rgb(color: str) -> list[int]:
    m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", color.strip())
    if not m:
        raise UserError(f"not a #RRGGBB colour: {color!r}")
    h = m.group(1)
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def brand_color(role_or_name: str) -> list[int]:
    """[r, g, b] for a palette role (caption_accent, caption_text, ...) or colour name (caption_gold, ...)."""
    pal = load_brand()["palette"]
    colors = pal["value"]
    name = pal.get("roles", {}).get(role_or_name, role_or_name)
    if name not in colors:
        raise UserError(f"brand palette has no colour or role {role_or_name!r}")
    return hex_to_rgb(colors[name])


def accent_rgb() -> list[int]:
    """Gold-italic caption colour (plan default for accent_rgb)."""
    return brand_color("caption_accent")


def brand_asset(key: str) -> Path:
    """Absolute path of a brand asset: wordmark, secondary_mark, endcard_background, brand_photos_dir."""
    node = load_brand()["assets"].get(key)
    value = fact(node)
    if not value:
        raise UserError(f"brand asset {key!r} is not set in brand.json")
    return plugin_path(value)


def brand_font(style: str = "regular") -> Path:
    """Absolute path of the caption font: style 'regular' or 'italic'."""
    fonts = fact(load_brand()["fonts"])
    key = f"caption_{style}"
    if key not in fonts:
        raise UserError(f"brand fonts have no {key!r}")
    return plugin_path(fonts[key])


# ---------------------------------------------------------------------------
# Work-folder layout and deliverable names
# ---------------------------------------------------------------------------
def slugify(text: str, max_len: int = 48) -> str:
    """'2026-11-09 Year One!' -> '2026-11-09-year-one'. Never empty."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    s = s[:max_len].rstrip("-")
    return s or "reel"


class JobPaths:
    """The per-reel folder: <job>/raw (downloaded material), <job>/work (analysis, plan, renders, QA),
    <job>/out (deliverables). See docs/CONTRACTS.md."""

    def __init__(self, job_dir: str | os.PathLike, slug: str | None = None):
        self.job = Path(job_dir).expanduser().resolve()
        self.raw = self.job / "raw"
        self.work = self.job / "work"
        self.out = self.job / "out"
        self.analysis = self.work / "analysis.json"
        self.plan = self.work / "plan.json"
        self.master = self.work / "master.wav"
        self.video_noaudio = self.work / "video_noaudio.mp4"
        self.slug = slugify(slug or self.job.name)

    def make(self) -> "JobPaths":
        for d in (self.raw, self.work, self.out):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def deliverable(self, kind: str, n: int | None = None, ext: str | None = None) -> Path:
        return self.out / deliverable_name(self.slug, kind, n, ext)


_DELIVERABLES = {
    "reel": ("_reel", "mp4"),
    "reach": ("_reach", "mp4"),
    "story": ("_story_{n}", "jpg"),
    "carousel": ("_carousel_{n}", "jpg"),
    "cover": ("_cover", "jpg"),
    "srt": ("", "srt"),
    "copy": ("_copy", "txt"),
    "hook": ("_hook_{n}", "mp4"),
}


def deliverable_name(slug: str, kind: str, n: int | None = None, ext: str | None = None) -> str:
    """deliverable_name('year-one', 'story', 2, 'mp4') -> 'year-one_story_2.mp4'. N counts from 1."""
    if kind not in _DELIVERABLES:
        raise UserError(f"unknown deliverable kind {kind!r}; one of {', '.join(_DELIVERABLES)}")
    suffix, default_ext = _DELIVERABLES[kind]
    if "{n}" in suffix:
        if not n or n < 1:
            raise UserError(f"deliverable {kind!r} needs a number N >= 1")
        suffix = suffix.format(n=n)
    return f"{slugify(slug)}{suffix}.{(ext or default_ext).lstrip('.')}"


# ---------------------------------------------------------------------------
# Subprocess and ffmpeg
# ---------------------------------------------------------------------------
def _tail(text: str | bytes | None, lines: int) -> str:
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    kept = [ln.strip() for ln in text.strip().splitlines() if ln.strip()][-lines:]
    return " | ".join(kept)


def run(cmd: Sequence[str | os.PathLike], *, cwd: str | os.PathLike | None = None, check: bool = True,
        capture: bool = True, timeout: float | None = None, input: bytes | None = None,
        tail: int = 6, what: str | None = None) -> subprocess.CompletedProcess:
    """Run a command (no shell). Missing program, timeout or non-zero exit -> UserError with the stderr tail.

    Output is captured as bytes in .stdout/.stderr (use .stderr.decode() or the text helpers)."""
    args = [str(c) for c in cmd]
    name = what or Path(args[0]).name
    try:
        proc = subprocess.run(args, cwd=cwd, input=input, timeout=timeout,
                              stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError:
        raise UserError(f"program not found: {args[0]}") from None
    except PermissionError:
        raise UserError(f"program is not executable: {args[0]}") from None
    except subprocess.TimeoutExpired:
        raise UserError(f"{name} timed out after {timeout:g} s") from None
    if check and proc.returncode != 0:
        detail = _tail(proc.stderr, tail) or _tail(proc.stdout, tail) or "no error output"
        raise UserError(f"{name} failed (exit {proc.returncode}): {detail}")
    return proc


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    """Path to ffmpeg: $NUMA_FFMPEG, else the system ffmpeg, else imageio-ffmpeg's bundled binary."""
    env = os.environ.get("NUMA_FFMPEG")
    if env:
        if not Path(env).is_file():
            raise UserError(f"NUMA_FFMPEG points to a missing file: {env}")
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - ImportError or imageio's own RuntimeError when the binary is absent
        exe = None
    if exe and Path(exe).is_file():
        return exe
    raise UserError("ffmpeg not found: install it (macOS: brew install ffmpeg; Linux: apt install ffmpeg) "
                    "or pip install imageio-ffmpeg")


@lru_cache(maxsize=1)
def ffprobe_bin() -> str | None:
    """Path to ffprobe ($NUMA_FFPROBE, system, or next to ffmpeg), or None.

    $NUMA_FFPROBE pointing at a missing file is a UserError (like $NUMA_FFMPEG).
    The imageio-ffmpeg fallback ships no ffprobe; ffprobe_json()/media_info() then
    parse `ffmpeg -i` output instead, so callers never need ffprobe directly."""
    env = os.environ.get("NUMA_FFPROBE")
    if env:
        if not Path(env).is_file():
            raise UserError(f"NUMA_FFPROBE points to a missing file: {env}")
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    try:
        ff = Path(ffmpeg_bin())
    except UserError:
        return None
    sibling = ff.with_name("ffprobe" + ff.suffix) if ff.name.startswith("ffmpeg") else None
    return str(sibling) if sibling and sibling.is_file() else None


def ffmpeg(*args: str | os.PathLike, timeout: float | None = None, what: str = "ffmpeg") -> subprocess.CompletedProcess:
    """Run ffmpeg quietly with overwrite: ffmpeg -hide_banner -nostdin -v error -y <args>."""
    return run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", *args], timeout=timeout, what=what)


def ffprobe_json(path: str | os.PathLike) -> dict:
    """ffprobe-style {"format": {...}, "streams": [...]} for a media file.

    Uses ffprobe when available; otherwise parses `ffmpeg -i` output into the same
    shape (numbers as strings like ffprobe, plus "_fallback": true). The fallback
    fills: format.duration, format.bit_rate, format.format_name; per stream
    index, codec_type, codec_name, profile, width, height, pix_fmt, r_frame_rate,
    avg_frame_rate, sample_rate, channels, channel_layout, bit_rate and
    side_data_list[{"rotation": deg}] when the file carries rotation.
    """
    p = Path(path)
    if not p.is_file():
        raise UserError(f"media file not found: {p}")
    probe = ffprobe_bin()
    if probe:
        proc = run([probe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                   what="ffprobe")
        try:
            return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            raise UserError(f"ffprobe returned unreadable output for {p}") from None
    proc = run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(p)], check=False, what="ffmpeg")
    text = proc.stderr.decode("utf-8", "replace")
    if "Invalid data found" in text or "No such file" in text or "Stream #" not in text:
        raise UserError(f"not a readable media file: {p} ({_tail(text, 2) or 'no streams'})")
    return parse_ffmpeg_info(text)


def _split_top(s: str) -> list[str]:
    """Split on commas that are not inside parentheses or brackets."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


_LAYOUT_CHANNELS = {"mono": 1, "stereo": 2, "2.1": 3, "3.0": 3, "quad": 4, "4.0": 4, "5.0": 5,
                    "5.1": 6, "6.1": 7, "7.1": 8, "downmix": 2}


def _rate_str(x: float) -> str:
    if float(x).is_integer():
        return f"{int(x)}/1"
    ntsc = round(x * 1.001)
    if abs(x * 1.001 - ntsc) < 0.005:  # ffmpeg prints 29.97 for 30000/1001
        return f"{ntsc * 1000}/1001"
    return f"{round(x * 1000)}/1000"


def parse_ffmpeg_info(text: str) -> dict:
    """Parse `ffmpeg -i <file>` stderr into an ffprobe-like dict (see ffprobe_json)."""
    fmt: dict[str, Any] = {}
    m = re.search(r"Input #0, ([^,]+(?:,[^,\s]+)*), from", text)
    if m:
        fmt["format_name"] = m.group(1).strip()
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, s = m.groups()
        fmt["duration"] = f"{int(h) * 3600 + int(mi) * 60 + float(s):.6f}"
    m = re.search(r"bitrate:\s*(\d+)\s*kb/s", text)
    if m:
        fmt["bit_rate"] = str(int(m.group(1)) * 1000)
    streams: list[dict] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        sm = re.search(r"Stream #\d+:(\d+)[^:]*:\s*(Video|Audio|Subtitle|Data|Attachment):\s*(.*)$", line)
        if not sm:
            continue
        idx, kind, rest = int(sm.group(1)), sm.group(2).lower(), sm.group(3)
        st: dict[str, Any] = {"index": idx, "codec_type": kind}
        parts = _split_top(rest)
        if parts:
            cm = re.match(r"(\w+)(?:\s*\(([^)]*)\))?", parts[0])
            if cm:
                st["codec_name"] = cm.group(1)
                if cm.group(2) and "/" not in cm.group(2):
                    st["profile"] = cm.group(2)
        if kind == "video":
            if len(parts) > 1:
                pm = re.match(r"(\w+)", parts[1])
                if pm and not re.match(r"\d+x\d+", parts[1]):
                    st["pix_fmt"] = pm.group(1)
            for part in parts:
                dm = re.match(r"(\d{1,5})x(\d{1,5})\b", part)
                if dm:
                    st["width"], st["height"] = int(dm.group(1)), int(dm.group(2))
                    break
            fm = re.search(r"([\d.]+)\s*fps", rest) or re.search(r"([\d.]+k?)\s*tbr", rest)
            if fm:
                val = fm.group(1)
                rate = float(val[:-1]) * 1000 if val.endswith("k") else float(val)
                st["avg_frame_rate"] = st["r_frame_rate"] = _rate_str(rate)
            bm = re.search(r"(\d+)\s*kb/s", rest)
            if bm:
                st["bit_rate"] = str(int(bm.group(1)) * 1000)
            # rotation is printed in the following side-data / metadata lines
            for nxt in lines[i + 1:i + 12]:
                if re.search(r"Stream #\d+:\d+", nxt):
                    break
                rm = re.search(r"rotation of (-?[\d.]+) degrees", nxt) or re.search(r"\brotate\s*:\s*(-?\d+)", nxt)
                if rm:
                    st["side_data_list"] = [{"rotation": float(rm.group(1))}]
                    break
        elif kind == "audio":
            for part in parts[1:]:
                hz = re.match(r"(\d+)\s*Hz", part)
                if hz:
                    st["sample_rate"] = hz.group(1)
                    continue
                lay = part.split("(")[0].strip()
                if lay in _LAYOUT_CHANNELS:
                    st["channel_layout"] = part.strip()
                    st["channels"] = _LAYOUT_CHANNELS[lay]
                    continue
                ch = re.match(r"(\d+)\s*channels", part)
                if ch:
                    st["channels"] = int(ch.group(1))
            bm = re.search(r"(\d+)\s*kb/s", rest)
            if bm:
                st["bit_rate"] = str(int(bm.group(1)) * 1000)
        streams.append(st)
    return {"format": fmt, "streams": streams, "_fallback": True}


def _to_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _rate(r: Any) -> float | None:
    if not r or r in ("0/0", "N/A"):
        return None
    if isinstance(r, str) and "/" in r:
        a, b = r.split("/", 1)
        fa, fb = _to_float(a), _to_float(b)
        return fa / fb if fa is not None and fb else None
    return _to_float(r)


def media_info(path: str | os.PathLike) -> dict:
    """Normalized facts about a media file (works with or without ffprobe):

    {"path", "duration" (s or None), "has_video", "has_audio", "width", "height"
     (display size after rotation), "coded_width", "coded_height", "rotation"
     (degrees, 0 if none), "fps", "vcodec", "profile", "pix_fmt", "acodec",
     "sample_rate", "channels", "bit_rate", "format_name"}"""
    data = ffprobe_json(path)
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info: dict[str, Any] = {
        "path": str(Path(path).resolve()),
        "duration": _to_float(fmt.get("duration")),
        "has_video": v is not None,
        "has_audio": a is not None,
        "width": None, "height": None, "coded_width": None, "coded_height": None,
        "rotation": 0.0, "fps": None, "vcodec": None, "profile": None, "pix_fmt": None,
        "acodec": None, "sample_rate": None, "channels": None,
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "format_name": fmt.get("format_name"),
    }
    if v:
        w, h = v.get("width"), v.get("height")
        rot = 0.0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = float(sd["rotation"])
        if not rot and (v.get("tags") or {}).get("rotate"):
            rot = float(v["tags"]["rotate"])
        info.update({
            "coded_width": w, "coded_height": h, "rotation": rot,
            "vcodec": v.get("codec_name"), "profile": v.get("profile"), "pix_fmt": v.get("pix_fmt"),
            "fps": _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")),
        })
        if w and h:
            swap = int(round(abs(rot))) % 180 == 90
            info["width"], info["height"] = (h, w) if swap else (w, h)
        if info["duration"] is None:
            info["duration"] = _to_float(v.get("duration"))
    if a:
        info.update({
            "acodec": a.get("codec_name"),
            "sample_rate": int(a["sample_rate"]) if str(a.get("sample_rate", "")).isdigit() else None,
            "channels": a.get("channels"),
        })
        if info["duration"] is None:
            info["duration"] = _to_float(a.get("duration"))
    return info


def media_duration(path: str | os.PathLike) -> float:
    """Duration in seconds; UserError when the file has none (e.g. a still image)."""
    d = media_info(path)["duration"]
    if d is None:
        raise UserError(f"cannot read a duration from {path}")
    return d


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def require_abs(path: str, what: str = "path") -> Path:
    """UserError unless path is absolute (plan.json rule: all paths absolute)."""
    if not os.path.isabs(path):
        raise UserError(f"{what} must be an absolute path: {path}")
    return Path(path)


def parse_size(text: str) -> tuple[int, int]:
    """'1080x1920' -> (1080, 1920); both even and >= 16, else UsageError."""
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", text or "")
    if not m:
        raise UsageError(f"size must look like WIDTHxHEIGHT (e.g. 1080x1920), got {text!r}")
    w, h = int(m.group(1)), int(m.group(2))
    if w < 16 or h < 16 or w % 2 or h % 2:
        raise UsageError(f"size {w}x{h}: width and height must be even and at least 16")
    return w, h
