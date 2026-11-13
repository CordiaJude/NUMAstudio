#!/usr/bin/env python3
"""Environment bootstrap every scheduled or manual command runs first (R339).

Usage:
    ensure_env.py [--check-only] [--json] [--with-model] [--with-chromium] [--requirements FILE]

Scheduled tasks run in the cloud on a fresh machine each time, so the Python
packages, the speech model and headless Chromium may be missing. This script
makes the machine ready, and does nothing when it already is:

1. Python 3.10 or newer.
2. Packages: every line of requirements.txt is importable at a version that
   satisfies it. Something missing, or requirements.txt changed since the last
   ready run: `python -m pip install --quiet -r requirements.txt` (retried with
   --break-system-packages on an "externally-managed-environment" refusal, then
   with --user).
3. ffmpeg: the system binary, else imageio-ffmpeg's bundled one ($NUMA_FFMPEG
   overrides both).
4. `--with-model`: the faster-whisper small.en speech model is in the local
   cache; downloaded when it is not (a few hundred MB). Offline, the download
   fails with a clear ERROR.
5. `--with-chromium`: headless Chromium for slide rendering. When playwright is
   in requirements.txt: `python -m playwright install chromium` if its browser
   is missing. When it is not, a WARN says slides cannot be rendered.

Fast path: after a ready run a stamp is written to `$NUMA_CACHE` (else
`~/.cache/numa-studio`)/ensure_env.json, keyed by the sha256 of
requirements.txt and the Python version. With a matching stamp the run only
confirms the modules can be found and the recorded ffmpeg / model / Chromium
paths still exist, which takes well under 5 s.

`--check-only` installs and downloads nothing and writes no stamp; it reports.

Output: one line per check (`OK:`, `WARN:`, or `ERROR: ... Fix: <exact
command>`); `--json` prints one report instead:
    {"ready": true, "fast_path": false, "key": "<hash16>-py3.12", "python": "3.12.3",
     "cache_dir": "...", "installed": ["packages"],
     "checks": [{"name": "packages", "ok": true, "level": "ok", "detail": "...", "fix": null}]}

Exit 0 when the machine is ready, 1 when it is not (the ERROR lines say what is
missing and the fix), 2 on usage errors.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

STAMP_VERSION = 1
WHISPER_MODEL = "small.en"
MIN_PYTHON = (3, 10)
PIP_TIMEOUT_S = 1800
# distribution name (lower case) -> import name, where they differ
IMPORT_NAMES = {
    "opencv-python-headless": "cv2", "opencv-python": "cv2", "pillow": "PIL", "pillow-heif": "pillow_heif",
    "faster-whisper": "faster_whisper", "imageio-ffmpeg": "imageio_ffmpeg", "playwright": "playwright",
}
_SPEC_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
_CLAUSE_RE = re.compile(r"^(~=|==|!=|<=|>=|<|>)\s*([0-9][0-9A-Za-z.*+-]*)$")


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------
def parse_requirements(path: Path) -> list[dict]:
    reqs = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()  # environment markers are not evaluated
        m = _SPEC_RE.match(line)
        if not m:
            raise nc.UserError(f"{path.name} line {n}: cannot read {raw.strip()!r}")
        dist = m.group(1)
        clauses = []
        rest = m.group(3).strip()
        if rest.startswith("@"):  # PEP 508 direct reference (`pkg @ <url>`): presence is all that can be checked
            if not rest[1:].strip():
                raise nc.UserError(f"{path.name} line {n}: {raw.strip()!r} has '@' but no URL")
            rest = ""
        for c in [c.strip() for c in rest.split(",") if c.strip()]:
            cm = _CLAUSE_RE.match(c)
            if not cm:
                raise nc.UserError(f"{path.name} line {n}: unsupported version clause {c!r}")
            clauses.append((cm.group(1), cm.group(2)))
        reqs.append({"dist": dist, "module": IMPORT_NAMES.get(dist.lower(), dist.replace("-", "_").lower()),
                     "clauses": clauses, "line": line})
    return reqs


def _vtuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group(0)))
    while out and out[-1] == 0:
        out.pop()
    return tuple(out)


def _padded(t: tuple[int, ...], n: int) -> tuple[int, ...]:
    return tuple(list(t) + [0] * (n - len(t)))[:n]


def satisfies(version: str, clauses: list[tuple[str, str]]) -> bool:
    """PEP 440 comparison for plain release numbers (enough for requirements.txt)."""
    have = _vtuple(version)
    for op, want in clauses:
        if want.endswith(".*"):
            prefix = tuple(int(x) for x in want[:-2].split(".") if x.isdigit())
            hit = _padded(have, len(prefix)) == prefix
            if (op == "==" and not hit) or (op == "!=" and hit):
                return False
            continue
        w = _vtuple(want)
        if op == "~=":
            parts = [int(x) for x in re.findall(r"\d+", want)]
            prefix = tuple(parts[:-1]) if len(parts) > 1 else tuple(parts)
            ok = have >= w and _padded(have, len(prefix)) == prefix
        else:
            ok = {"==": have == w, "!=": have != w, ">=": have >= w, "<=": have <= w, ">": have > w,
                  "<": have < w}[op]
        if not ok:
            return False
    return True


def missing_packages(reqs: list[dict]) -> list[str]:
    """Requirement lines that are not importable at a satisfying version."""
    importlib.invalidate_caches()
    bad = []
    for r in reqs:
        if importlib.util.find_spec(r["module"]) is None:
            bad.append(f"{r['dist']} (not installed)")
            continue
        if r["clauses"]:
            try:
                v = importlib.metadata.version(r["dist"])
            except importlib.metadata.PackageNotFoundError:
                continue  # importable under another distribution name: accept it
            if not satisfies(v, r["clauses"]):
                bad.append(f"{r['dist']} {v} (needs {','.join(o + w for o, w in r['clauses'])})")
    return bad


# ---------------------------------------------------------------------------
# cache and stamp
# ---------------------------------------------------------------------------
def cache_dir() -> Path:
    env = os.environ.get("NUMA_CACHE")
    return Path(env).expanduser() if env else Path.home() / ".cache" / "numa-studio"


def stamp_key(req_path: Path) -> str:
    digest = hashlib.sha256(req_path.read_bytes()).hexdigest()[:16]
    return f"{digest}-py{sys.version_info[0]}.{sys.version_info[1]}"


def read_stamp(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == STAMP_VERSION else None


# ---------------------------------------------------------------------------
# installers and probes (module-level so tests can replace them)
# ---------------------------------------------------------------------------
def pip_install(req_path: Path) -> tuple[bool, str]:
    """pip install --quiet -r; on an externally-managed refusal retry with --break-system-packages, then --user."""
    base = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(req_path)]
    p = subprocess.run(base, capture_output=True, text=True, timeout=PIP_TIMEOUT_S)
    if p.returncode == 0:
        return True, "plain"
    out = (p.stderr or "") + (p.stdout or "")
    tries = (["--break-system-packages"], ["--user"]) if "externally-managed-environment" in out else (["--user"],)
    for extra in tries:
        p = subprocess.run(base + extra, capture_output=True, text=True, timeout=PIP_TIMEOUT_S)
        if p.returncode == 0:
            return True, extra[0]
        out = (p.stderr or "") + (p.stdout or "")
    return False, " ".join(out.split())[-300:]


def ffmpeg_path() -> tuple[str | None, str]:
    nc.clear_caches()
    try:
        exe = nc.ffmpeg_bin()
    except nc.UserError as e:
        return None, str(e)
    src = "NUMA_FFMPEG" if os.environ.get("NUMA_FFMPEG") else ("system" if shutil.which("ffmpeg") == exe
                                                               else "imageio-ffmpeg fallback")
    return exe, src


def model_cached() -> str | None:
    try:
        from faster_whisper.utils import download_model
        return str(download_model(WHISPER_MODEL, local_files_only=True))
    except Exception:  # noqa: BLE001 - not cached, or faster-whisper unusable (reported by the package check)
        return None


def model_download() -> tuple[str | None, str]:
    try:
        from faster_whisper.utils import download_model
    except Exception as e:  # noqa: BLE001
        return None, f"faster-whisper is not importable: {' '.join(str(e).split())}"
    try:
        return str(download_model(WHISPER_MODEL)), ""
    except Exception as e:  # noqa: BLE001 - network, proxy or disk problems
        return None, " ".join(str(e).split())[:200]


def chromium_path() -> str | None:
    code = ("from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n    print(p.chromium.executable_path)\n")
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    path = (p.stdout or "").strip().splitlines()[-1:] if p.returncode == 0 else []
    return path[0] if path and Path(path[0]).exists() else None


def chromium_install() -> tuple[bool, str]:
    p = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True,
                       timeout=PIP_TIMEOUT_S)
    return p.returncode == 0, " ".join((p.stderr or p.stdout or "").split())[-300:]


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.installed: list[str] = []

    def add(self, name: str, level: str, detail: str, fix: str | None = None) -> None:
        self.checks.append({"name": name, "ok": level != "error", "level": level, "detail": detail, "fix": fix})

    @property
    def ready(self) -> bool:
        return all(c["ok"] for c in self.checks)


def _me(req_path: Path, extra: str = "") -> str:
    return f"python3 \"{Path(__file__).resolve()}\" --requirements \"{req_path}\"{extra}"


def fast_path(stamp: dict | None, key: str, reqs: list[dict], want_model: bool, want_chromium: bool) -> bool:
    if not stamp or stamp.get("key") != key:
        return False
    if want_model and not (stamp.get("model") and Path(stamp["model"]).exists()):
        return False
    if want_chromium and stamp.get("chromium") is None and stamp.get("chromium_in_requirements", True):
        return False
    if want_chromium and stamp.get("chromium") and not Path(stamp["chromium"]).exists():
        return False
    if not (stamp.get("ffmpeg") and Path(stamp["ffmpeg"]).exists()):
        return False
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(r["module"]) is not None for r in reqs)


def run(req_path: Path, check_only: bool, want_model: bool, want_chromium: bool) -> tuple[Report, dict]:
    rep = Report()
    info = {"fast_path": False, "key": None, "python": platform.python_version(), "cache_dir": str(cache_dir())}
    if sys.version_info < MIN_PYTHON:
        rep.add("python", "error", f"Python {platform.python_version()} is too old",
                "install Python 3.10 or newer (macOS: brew install python@3.12) and run with it")
        return rep, info
    if not req_path.is_file():
        rep.add("requirements", "error", f"{req_path} not found", "reinstall the numa-studio plugin")
        return rep, info
    reqs = parse_requirements(req_path)
    key = stamp_key(req_path)
    info["key"] = key
    stamp_file = cache_dir() / "ensure_env.json"
    stamp = read_stamp(stamp_file)

    if fast_path(stamp, key, reqs, want_model, want_chromium):
        info["fast_path"] = True
        rep.add("python", "ok", platform.python_version())
        rep.add("packages", "ok", f"{len(reqs)} requirements present (stamp {key})")
        rep.add("ffmpeg", "ok", stamp["ffmpeg"])
        if want_model:
            rep.add("speech model", "ok", f"faster-whisper {WHISPER_MODEL} cached ({stamp['model']})")
        if want_chromium:
            if stamp.get("chromium"):
                rep.add("chromium", "ok", stamp["chromium"])
            else:
                rep.add("chromium", "warn", "playwright is not in requirements.txt: component carousel slides "
                        "cannot be rendered here", "add playwright to requirements.txt")
        return rep, info

    rep.add("python", "ok", platform.python_version())

    # 2. packages
    missing = missing_packages(reqs)
    changed = bool(stamp and stamp.get("key") != key)
    pip_fix = f"python3 -m pip install -r \"{req_path}\" (add --break-system-packages if pip refuses)"
    if missing and check_only:
        rep.add("packages", "error", "missing or too old: " + ", ".join(missing), pip_fix)
    elif missing or (changed and not check_only):
        why = "missing: " + ", ".join(missing) if missing else "requirements.txt changed"
        ok, how = pip_install(req_path)
        nc.clear_caches()
        still = missing_packages(reqs)
        if ok and not still:
            rep.installed.append("packages")
            rep.add("packages", "ok", f"installed ({why}; pip {how})")
        else:
            rep.add("packages", "error", "pip could not install " + (", ".join(still) or "the requirements")
                    + (f" ({how})" if not ok and how else ""), pip_fix)
    else:
        rep.add("packages", "ok", f"{len(reqs)} requirements present")

    # 3. ffmpeg
    exe, src = ffmpeg_path()
    if exe:
        rep.add("ffmpeg", "ok", f"{exe} ({src})")
    else:
        rep.add("ffmpeg", "error", src, "install ffmpeg (macOS: brew install ffmpeg; Linux: apt install ffmpeg) "
                f"or {pip_fix}")

    # 4. speech model
    model = None
    if want_model:
        model = model_cached()
        if model:
            rep.add("speech model", "ok", f"faster-whisper {WHISPER_MODEL} cached ({model})")
        elif check_only:
            rep.add("speech model", "error", f"faster-whisper {WHISPER_MODEL} is not downloaded",
                    _me(req_path, " --with-model"))
        else:
            nc.info(f"ensure_env: downloading faster-whisper {WHISPER_MODEL} (a few hundred MB)...")
            model, why = model_download()
            if model:
                rep.installed.append("speech model")
                rep.add("speech model", "ok", f"downloaded faster-whisper {WHISPER_MODEL} ({model})")
            else:
                rep.add("speech model", "error", f"faster-whisper {WHISPER_MODEL} is not cached and the download "
                        f"failed; this machine looks offline or cannot reach Hugging Face ({why})",
                        "connect to the internet (or allow huggingface.co), then run " + _me(req_path, " --with-model"))

    # 5. headless Chromium
    chromium = None
    in_reqs = any(r["dist"].lower() == "playwright" for r in reqs)
    if want_chromium:
        if not in_reqs:
            rep.add("chromium", "warn", "playwright is not in requirements.txt: component carousel slides cannot be "
                    "rendered here", "add playwright to requirements.txt")
        else:
            chromium = chromium_path()
            linux = sys.platform.startswith("linux")
            fix = ("python3 -m playwright install chromium"
                   + (" (if Chromium then fails to start: python3 -m playwright install --with-deps chromium)"
                      if linux else ""))
            if chromium:
                rep.add("chromium", "ok", chromium)
            elif check_only:
                rep.add("chromium", "error", "headless Chromium for slide rendering is not installed", fix)
            else:
                ok, tail = chromium_install()
                chromium = chromium_path() if ok else None
                if chromium:
                    rep.installed.append("chromium")
                    rep.add("chromium", "ok", f"installed {chromium}")
                else:
                    rep.add("chromium", "error", "could not install headless Chromium"
                            + (f" ({tail})" if tail else ""), fix)

    if rep.ready and not check_only:
        old = stamp if stamp and stamp.get("key") == key else {}
        data = {"version": STAMP_VERSION, "key": key, "python": platform.python_version(),
                "requirements": str(req_path), "ffmpeg": exe,
                "model": model or old.get("model"),
                "chromium": chromium or old.get("chromium"),
                "chromium_in_requirements": in_reqs,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            nc.write_json(stamp_file, data)
        except OSError as e:
            nc.warn(f"could not write the fast-path stamp {stamp_file}: {e.strerror or e}")
    return rep, info


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="ensure_env.py", description="Make this machine ready for NUMA Studio (idempotent).")
    ap.add_argument("--check-only", action="store_true", help="report only: install and download nothing")
    ap.add_argument("--json", action="store_true", help="print one JSON report")
    ap.add_argument("--with-model", action="store_true", help="also ensure the faster-whisper small.en speech model")
    ap.add_argument("--with-chromium", action="store_true", help="also ensure headless Chromium for slide rendering")
    ap.add_argument("--requirements", help="requirements file (default: the plugin's requirements.txt)")
    a = ap.parse_args(argv)
    req = Path(a.requirements).expanduser() if a.requirements else nc.PLUGIN_ROOT / "requirements.txt"
    t0 = time.monotonic()
    rep, info = run(req, a.check_only, a.with_model, a.with_chromium)
    seconds = round(time.monotonic() - t0, 2)
    if a.json:
        nc.print_json({"ready": rep.ready, **info, "seconds": seconds, "installed": rep.installed,
                       "checks": rep.checks})
    else:
        for c in rep.checks:
            if c["level"] == "ok":
                print(f"OK: {c['name']}: {c['detail']}")
            elif c["level"] == "warn":
                nc.warn(f"{c['name']}: {c['detail']}" + (f". Fix: {c['fix']}" if c["fix"] else ""))
    for c in rep.checks:
        if c["level"] == "error":
            nc.error_line(f"{c['name']}: {c['detail']}. Fix: {c['fix']}")
    if not a.json:
        print(("ready" if rep.ready else "NOT ready") + f" ({'fast path, ' if info['fast_path'] else ''}{seconds} s)")
    return 0 if rep.ready else 1


if __name__ == "__main__":
    nc.run_cli(main)
