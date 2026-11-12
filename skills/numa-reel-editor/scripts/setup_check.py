#!/usr/bin/env python3
"""Setup self-check: is this computer ready to run NUMA Studio?

Usage:
    setup_check.py [--skip-render] [--download-model] [--json]

One line per check, ✅ pass / ⚠️ warning / ❌ fail, each failure with a one-line
fix (spec p.13, p.50, p.53; docs/CONTRACTS.md section 9):

  python        Python 3.10 or newer
  import:<mod>  numpy, cv2 (OpenCV < 5 with FaceDetectorYN and CascadeClassifier),
                PIL, pillow_heif, librosa, faster_whisper, jsonschema, imageio_ffmpeg
  ffmpeg        system ffmpeg (or $NUMA_FFMPEG, or the imageio-ffmpeg fallback)
                that can encode libx264 and AAC
  ffprobe       ffprobe, or the `ffmpeg -i` fallback the scripts use without it
  fonts         the brand caption fonts (brand.json `fonts`) load
  assets        wordmark, secondary mark, end-card background, >= 2 brand photos
  brand.json    valid against schemas/brand.schema.json, claims patterns compile
  config        config/studio.json has every section and key the scripts read
  face model    the bundled YuNet model loads and runs (assets/models)
  disk          free space in the temp folder and the home folder (>= 2 GB)
  speech model  faster-whisper small.en is downloaded (--download-model fetches
                it now so the first reel is not slow; without the flag a missing
                model is a warning: the first transcription downloads it)
  test render   a 3-second reel from two bundled brand photos and a generated
                music pad, through engine.py and finish.py, then check_output
                (with the length rule set to this test's 3 s instead of a
                reel's 15-60 s). The folder is kept so the reel and its
                qa_strip.jpg can be looked at; test folders older than 6 hours
                are removed.

--skip-render skips the test render (a few seconds instead of about 30).
--json prints one JSON report on stdout: {"ok", "checks": [{"name", "status",
"detail", "fix"}], "render"}.

Exit 0 when nothing failed (warnings allowed), 1 when any check failed.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

MIN_PYTHON = (3, 10)
MIN_FREE_GB = 2.0
RENDER_SECONDS = 3.0
RENDER_TOLERANCE_S = 0.25
TEST_DIR_PREFIX = "numa-setup-check-"
STALE_TEST_DIR_S = 6 * 3600
WHISPER_MODEL = "small.en"
FACE_MODEL = nc.ASSETS_DIR / "models" / "face_detection_yunet_2023mar.onnx"

PIP = "pip install -r requirements.txt (add --break-system-packages if pip refuses)"
# import name -> (pip package, why NUMA Studio needs it)
IMPORTS: dict[str, tuple[str, str]] = {
    "numpy": ("numpy", "image and audio math"),
    "cv2": ("'opencv-python-headless>=4.8,<5'", "rendering, face and subject detection"),
    "PIL": ("pillow", "images and caption text"),
    "pillow_heif": ("pillow-heif", "iPhone HEIC photos"),
    "librosa": ("librosa", "beat detection"),
    "faster_whisper": ("faster-whisper", "voiceover transcription"),
    "jsonschema": ("jsonschema", "plan and brand validation"),
    "imageio_ffmpeg": ("imageio-ffmpeg", "the bundled ffmpeg fallback"),
}

# Config keys the scripts read (config/studio.json, docs/CONTRACTS.md section 7).
CONFIG_KEYS = [
    "models.agents", "higgsfield.prices", "budget.monthly_credits", "budget.split",
    "critic.rubric", "critic.pass", "render.fps", "render.size", "render.video", "render.audio",
    "render.loudness", "render.length_s.main_reel", "schedule.timezone", "schedule.tasks",
    "instagram.graph_api_version", "instagram.tools", "instagram.publishing_limit_per_24h",
    "instagram.container_max_age_hours", "formats.outputs",
]

# A modest JPEG test photo: big enough for the detector, small enough to be quick.
FACE_TEST_PHOTO = "sauna-people.jpg"


class Result:
    def __init__(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.name, self.status, self.detail, self.fix = name, status, detail, fix

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}

    def line(self) -> str:
        mark = {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}[self.status]
        text = f"{mark} {self.name}: {self.detail}"
        return text + (f" | fix: {self.fix}" if self.fix and self.status != "pass" else "")


def passed(name: str, detail: str) -> Result:
    return Result(name, "pass", detail)


def failed(name: str, detail: str, fix: str) -> Result:
    return Result(name, "fail", detail, fix)


def warned(name: str, detail: str, fix: str) -> Result:
    return Result(name, "warn", detail, fix)


def one_line(e: BaseException) -> str:
    return " ".join(str(e).split()) or type(e).__name__


# --------------------------------------------------------------------------- checks
def check_python() -> Result:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= MIN_PYTHON:
        return passed("python", f"Python {ver}")
    return failed("python", f"Python {ver} is too old (NUMA Studio needs 3.10 or newer)",
                  "install Python 3.10+ (macOS: brew install python@3.12) and run setup again")


def module_version(module: str, mod: Any) -> str:
    dist = IMPORTS[module][0].strip("'").split(">")[0].split("<")[0]
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:  # noqa: BLE001 - not installed as a distribution (vendored, frozen)
        return str(mod.__dict__.get("__version__", "") or "")


def check_import(module: str) -> Result:
    name = f"import {module}"
    pkg, why = IMPORTS[module]
    fix = f"pip install {pkg} (add --break-system-packages if pip refuses), or {PIP}"
    try:
        mod = importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 - ImportError, or a broken install raising anything
        return failed(name, f"cannot import {module} ({why}): {one_line(e)}", fix)
    version = module_version(module, mod)
    if module == "cv2":
        version = str(mod.__dict__.get("__version__", "") or version)  # what the loaded OpenCV reports
        major = int(version.split(".")[0]) if version.split(".")[0].isdigit() else 0
        if major >= 5:
            return failed(name, f"OpenCV {version}: version 5 removed CascadeClassifier (DECISIONS D16)",
                          "pip install 'opencv-python-headless>=4.8,<5' (add --break-system-packages if pip refuses)")
        missing = [a for a in ("FaceDetectorYN", "CascadeClassifier") if not hasattr(mod, a)]
        if missing:
            return failed(name, f"OpenCV {version} has no {' or '.join(missing)}",
                          "pip install --upgrade 'opencv-python-headless>=4.8,<5'")
    return passed(name, f"{module} {version}".strip())


def check_ffmpeg() -> Result:
    fix = "install ffmpeg (macOS: brew install ffmpeg; Linux: apt install ffmpeg) or pip install imageio-ffmpeg"
    try:
        exe = nc.ffmpeg_bin()
    except nc.UserError as e:
        return failed("ffmpeg", one_line(e), fix)
    if os.environ.get("NUMA_FFMPEG"):
        source = "NUMA_FFMPEG"
    elif shutil.which("ffmpeg") == exe:
        source = "system"
    else:
        source = "imageio-ffmpeg fallback"
    try:
        ver = nc.run([exe, "-hide_banner", "-version"], what="ffmpeg -version", timeout=30).stdout
        enc = nc.run([exe, "-hide_banner", "-encoders"], what="ffmpeg -encoders", timeout=30).stdout
        ver, enc = (b.decode("utf-8", "replace") for b in (ver or b"", enc or b""))
    except nc.UserError as e:
        return failed("ffmpeg", f"{exe} does not run: {one_line(e)}", fix)
    names = {parts[1] for parts in (line.split() for line in enc.splitlines()) if len(parts) > 1}
    missing = [e for e in ("libx264", "aac") if e not in names]
    if missing:
        return failed("ffmpeg", f"{exe} has no {' or '.join(missing)} encoder",
                      "install a full ffmpeg build (macOS: brew install ffmpeg) or pip install imageio-ffmpeg")
    first = (ver.splitlines() or ["ffmpeg"])[0]
    version = first.split()[2] if len(first.split()) > 2 else "unknown version"
    return passed("ffmpeg", f"{source} ffmpeg {version} with libx264 and AAC ({exe})")


def check_ffprobe() -> Result:
    try:
        exe = nc.ffprobe_bin()
    except nc.UserError as e:
        return failed("ffprobe", one_line(e), "unset NUMA_FFPROBE or point it at a real ffprobe")
    if exe is None:
        try:
            nc.ffmpeg_bin()
        except nc.UserError:
            return failed("ffprobe", "no ffprobe and no ffmpeg to fall back on",
                          "install ffmpeg (macOS: brew install ffmpeg) or pip install imageio-ffmpeg")
        return passed("ffprobe", "not installed; the scripts read media with the `ffmpeg -i` fallback")
    try:
        nc.run([exe, "-hide_banner", "-version"], what="ffprobe -version", timeout=30)
    except nc.UserError as e:
        return failed("ffprobe", f"{exe} does not run: {one_line(e)}",
                      "reinstall ffmpeg (it ships ffprobe) or unset NUMA_FFPROBE")
    return passed("ffprobe", exe)


def check_fonts() -> Result:
    fix = "reinstall the plugin (fonts ship in skills/numa-reel-editor/assets/fonts) or fix brand.json fonts"
    try:
        paths = [nc.brand_font("regular"), nc.brand_font("italic")]
    except nc.UserError as e:
        return failed("fonts", one_line(e), fix)
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        return failed("fonts", f"missing font file {missing[0]}", fix)
    try:
        from PIL import ImageFont
    except Exception:  # noqa: BLE001 - reported by the PIL import check
        return passed("fonts", f"{', '.join(p.name for p in paths)} present (not loaded: Pillow missing)")
    for p in paths:
        try:
            ImageFont.truetype(str(p), 40)
        except Exception as e:  # noqa: BLE001 - corrupt or unreadable font
            return failed("fonts", f"{p.name} does not load: {one_line(e)}", fix)
    return passed("fonts", ", ".join(p.name for p in paths))


def check_assets() -> Result:
    fix = "reinstall the plugin (assets ship in skills/numa-reel-editor/assets) or fix brand.json assets"
    found = []
    try:
        for key in ("wordmark", "secondary_mark", "endcard_background"):
            p = nc.brand_asset(key)
            if not p.is_file():
                return failed("assets", f"brand asset {key} is missing: {p}", fix)
            found.append(p.name)
        photos_dir = nc.brand_asset("brand_photos_dir")
    except nc.UserError as e:
        return failed("assets", one_line(e), fix)
    photos = sorted(photos_dir.glob("*.jpg")) if photos_dir.is_dir() else []
    if len(photos) < 2:
        return failed("assets", f"{photos_dir} holds {len(photos)} brand photo(s), at least 2 needed", fix)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - reported by the PIL import check
        return passed("assets", f"{', '.join(found)} and {len(photos)} brand photos present")
    for p in [nc.brand_asset(k) for k in ("wordmark", "secondary_mark", "endcard_background")] + photos:
        try:
            with Image.open(p) as im:
                im.verify()
        except Exception as e:  # noqa: BLE001 - corrupt image
            return failed("assets", f"{p.name} is not a readable image: {one_line(e)}", fix)
    return passed("assets", f"{', '.join(found)} and {len(photos)} brand photos")


def check_brand() -> Result:
    path = nc.brand_path()
    try:
        brand = nc.load_brand()
    except nc.UserError as e:
        return failed("brand.json", one_line(e),
                      "fix the field named above (docs/CONTRACTS.md section 6), or re-run /brand-setup")
    open_facts = count_needs_katie(brand)
    note = f"; {open_facts} facts still needs_katie (/brand-setup fills them)" if open_facts else ""
    return passed("brand.json", f"valid ({path}){note}")


def count_needs_katie(node: Any) -> int:
    if isinstance(node, dict):
        own = 1 if node.get("status") == "needs_katie" and "value" in node else 0
        return own + sum(count_needs_katie(v) for k, v in node.items() if k != "value")
    if isinstance(node, list):
        return sum(count_needs_katie(v) for v in node)
    return 0


def check_config() -> Result:
    path = nc.config_path()
    fix = "restore config/studio.json from the plugin (docs/CONTRACTS.md section 7)"
    try:
        cfg = nc.load_config()
    except nc.UserError as e:
        return failed("config", one_line(e), fix)
    missing = [k for k in CONFIG_KEYS if nc.dig(cfg, k) is None]
    if missing:
        return failed("config", f"{path} is missing {', '.join(missing)}", fix)
    tasks = nc.dig(cfg, "schedule.tasks") or []
    if len(tasks) != 6 or not all(isinstance(t, dict) and t.get("cron") for t in tasks):
        return failed("config", f"{path}: schedule.tasks must list the 6 scheduled tasks with cron strings", fix)
    return passed("config", f"valid ({path})")


def check_face_model() -> Result:
    fix = "reinstall the plugin (the model ships in skills/numa-reel-editor/assets/models) and pip install 'opencv-python-headless>=4.8,<5'"
    if not FACE_MODEL.is_file():
        return failed("face model", f"missing {FACE_MODEL}", fix)
    try:
        import cv2
    except Exception:  # noqa: BLE001 - reported by the cv2 import check
        return failed("face model", "OpenCV is not importable", fix)
    if not hasattr(cv2, "FaceDetectorYN"):
        return failed("face model", f"OpenCV {cv2.__version__} has no FaceDetectorYN", fix)
    try:
        img = cv2.imread(str(nc.BRAND_PHOTOS_DIR / FACE_TEST_PHOTO))
        if img is None:
            img = cv2.imread(str(sorted(nc.BRAND_PHOTOS_DIR.glob("*.jpg"))[0]))
        h, w = img.shape[:2]
        net = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (w, h), 0.5, 0.3, 5000)
        _, faces = net.detect(img)
    except Exception as e:  # noqa: BLE001 - unreadable model or unsupported build
        return failed("face model", f"YuNet does not load: {one_line(e)}", fix)
    n = 0 if faces is None else len(faces)
    return passed("face model", f"YuNet loads and runs ({FACE_MODEL.name}, {n} face(s) in a test photo)")


def check_disk() -> Result:
    places = {"temp folder": Path(tempfile.gettempdir()), "home folder": Path.home()}
    lows, report = [], []
    for label, p in places.items():
        try:
            free = shutil.disk_usage(p).free / 1e9
        except OSError as e:
            return failed("disk", f"cannot read free space of the {label} {p}: {one_line(e)}",
                          "check that the folder exists and is readable")
        report.append(f"{free:.1f} GB free in the {label}")
        if free < MIN_FREE_GB:
            lows.append(f"{label} {p} has {free:.1f} GB free")
    if lows:
        return failed("disk", "; ".join(lows) + f" (need {MIN_FREE_GB:g} GB for the speech model and renders)",
                      "free up disk space (empty the Trash, delete old renders in ~/NUMA Studio)")
    return passed("disk", ", ".join(report))


def check_speech_model(download: bool) -> Result:
    name = "speech model"
    try:
        from faster_whisper.utils import download_model
    except Exception as e:  # noqa: BLE001 - reported by the faster_whisper import check
        return failed(name, f"faster-whisper is not importable: {one_line(e)}",
                      f"pip install faster-whisper (add --break-system-packages if pip refuses), or {PIP}")
    try:
        path = download_model(WHISPER_MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001 - not cached yet (the library raises several kinds)
        path = None
    if path is None and not download:
        return warned(name, f"faster-whisper {WHISPER_MODEL} is not downloaded yet; the first transcription "
                            "downloads it (a few hundred MB) and is slow",
                      "run setup_check.py --download-model")
    if path is None:
        nc.info(f"setup_check: downloading faster-whisper {WHISPER_MODEL} (a few hundred MB)...")
        try:
            path = download_model(WHISPER_MODEL)
        except Exception as e:  # noqa: BLE001 - network or disk problems
            return failed(name, f"download of {WHISPER_MODEL} failed: {one_line(e)}",
                          "check the internet connection and free disk space, then run setup_check.py --download-model again")
    if download:
        try:
            from faster_whisper import WhisperModel
            WhisperModel(str(path), device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001 - corrupt download
            return failed(name, f"{WHISPER_MODEL} is downloaded but does not load: {one_line(e)}",
                          f"delete {path} and run setup_check.py --download-model again")
        return passed(name, f"faster-whisper {WHISPER_MODEL} downloaded and loads ({path})")
    return passed(name, f"faster-whisper {WHISPER_MODEL} downloaded ({path})")


# --------------------------------------------------------------------------- test render
def remove_old_test_dirs() -> None:
    """Remove earlier test folders, but only stale ones (older than STALE_TEST_DIR_S), so a
    check running at the same time never loses its folder."""
    now = time.time()
    for old in Path(tempfile.gettempdir()).glob(TEST_DIR_PREFIX + "*"):
        try:
            stale = old.is_dir() and now - old.stat().st_mtime > STALE_TEST_DIR_S
        except OSError:
            continue
        if stale:
            shutil.rmtree(old, ignore_errors=True)


def make_test_plan(work: Path) -> dict:
    photos = sorted(nc.brand_asset("brand_photos_dir").glob("*.jpg"))
    end_t = 2.25
    return {
        "schema_version": nc.PLAN_SCHEMA_VERSION,
        "duration": RENDER_SECONDS,
        "out_dir": str(work),
        "fps": int(nc.config_value("render.fps", 30)),
        "size": list(nc.config_value("render.size", [1080, 1920])),
        "seed": 0,
        "hook": {"text": "Setup check", "t1": 1.5},
        "shots": [
            {"src": str(photos[0]), "look": "warm", "t0": 0.0, "t1": 1.5, "z": [1.0, 1.08], "tr": "cut"},
            {"src": str(photos[1]), "look": "warm", "t0": 1.5, "t1": end_t, "z": [1.08, 1.0], "tr": "flash"},
        ],
        "lines": [{"words": [["Your", 0.3], ["reset", 0.7], ["starts", 1.1], ["here.", 1.5, 1]], "end": 2.2}],
        "endcard": {"t": end_t, "logo": str(nc.brand_asset("wordmark")),
                    "tagline": str(nc.brand_value("endcard.tagline", "") or ""),
                    "subtitle": str(nc.brand_value("endcard.default_subtitle", "") or "")},
        "music": {"source": "pad", "path": str(work / "pad.wav"), "license": "generated offline by analyze.py"},
        "meta": {"slug": "setup-check", "title": "Setup check"},
    }


def run_step(cmd: list[str], what: str, timeout: float) -> str | None:
    """Run a pipeline script; None on success, else a one-line reason."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"{what} took longer than {timeout:g} s"
    if proc.returncode == 0:
        return None
    lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    return f"{what} exit {proc.returncode}: " + ((errors or lines or ["no output"])[-1])


def render_test_reel(blockers: list[str]) -> tuple[Result, dict]:
    name = "test render"
    fix = "fix the failed checks above, then run setup_check.py again (NUMA_DEBUG=1 shows details)"
    if blockers:
        return failed(name, f"not run: {', '.join(blockers)} failed", fix), {}
    remove_old_test_dirs()
    folder = Path(tempfile.mkdtemp(prefix=TEST_DIR_PREFIX))
    work, out = folder / "work", folder / "out"
    work.mkdir()
    out.mkdir()
    reel = out / "setup-check_reel.mp4"
    info: dict[str, Any] = {"folder": str(folder), "reel": str(reel), "qa_strip": str(out / "qa_strip.jpg")}
    started = time.monotonic()
    try:
        import analyze  # the same offline pad the pipeline uses when a folder has no audio
        analyze.make_pad(work / "pad.wav", RENDER_SECONDS)
        analyze.normalize_to(work / "pad.wav", work / "master.wav", seconds=RENDER_SECONDS)
        nc.write_json(work / "plan.json", make_test_plan(work))
    except Exception as e:  # noqa: BLE001 - any failure here is a setup problem to report
        return failed(name, f"cannot prepare the test plan: {one_line(e)}", fix), info
    scripts = Path(__file__).resolve().parent
    py = sys.executable
    for cmd, what, timeout in (
        ([py, str(scripts / "engine.py"), str(work / "plan.json")], "engine.py", 600),
        ([py, str(scripts / "finish.py"), str(work), str(reel), "--plan", str(work / "plan.json")], "finish.py", 300),
    ):
        problem = run_step(cmd, what, timeout)
        if problem:
            return failed(name, problem, fix), info
    try:
        import check_output
        original = check_output.kind_lengths
        check_output.kind_lengths = lambda kind: (RENDER_SECONDS - RENDER_TOLERANCE_S, RENDER_SECONDS + RENDER_TOLERANCE_S)
        try:
            result = check_output.check_file(reel, "story", plan=work / "plan.json")
        finally:
            check_output.kind_lengths = original
    except Exception as e:  # noqa: BLE001 - report, never crash
        return failed(name, f"check_output could not read the test reel: {one_line(e)}", fix), info
    seconds = round(time.monotonic() - started, 1)
    info.update(seconds=seconds, check_output=result)
    if not result["ok"]:
        return failed(name, f"test reel fails the output spec: {result['errors'][0]}", fix), info
    probe = result["probe"]
    return passed(name, f"{probe['width']}x{probe['height']} {probe['duration']:.2f} s reel passes check_output "
                        f"in {seconds:g} s; look at {info['qa_strip']}"), info


# --------------------------------------------------------------------------- main
def run_checks(skip_render: bool, download_model: bool) -> tuple[list[Result], dict]:
    results: list[Result] = []

    def guarded(name: str, fn: Callable[[], Result]) -> Result:
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001 - one broken check never hides the others
            r = failed(name, f"check crashed: {type(e).__name__}: {one_line(e)}", "run with NUMA_DEBUG=1 and report it")
        results.append(r)
        return r

    guarded("python", check_python)
    for module in IMPORTS:
        guarded(f"import {module}", lambda m=module: check_import(m))
    guarded("ffmpeg", check_ffmpeg)
    guarded("ffprobe", check_ffprobe)
    guarded("fonts", check_fonts)
    guarded("assets", check_assets)
    guarded("brand.json", check_brand)
    guarded("config", check_config)
    guarded("face model", check_face_model)
    guarded("disk", check_disk)
    guarded("speech model", lambda: check_speech_model(download_model))

    render: dict = {}
    if not skip_render:
        needed = {"python", "import numpy", "import cv2", "import PIL", "import jsonschema", "ffmpeg",
                  "fonts", "assets", "brand.json", "config"}
        blockers = [r.name for r in results if r.name in needed and r.status == "fail"]
        try:
            r, render = render_test_reel(blockers)
        except Exception as e:  # noqa: BLE001
            r = failed("test render", f"crashed: {type(e).__name__}: {one_line(e)}", "run with NUMA_DEBUG=1 and report it")
        results.append(r)
    return results, render


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="setup_check.py", description="Check that this computer can run NUMA Studio.")
    ap.add_argument("--skip-render", action="store_true", help="skip the 3-second test render (fast)")
    ap.add_argument("--download-model", action="store_true",
                    help="download the faster-whisper small.en speech model now")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    args = ap.parse_args(argv)

    results, render = run_checks(args.skip_render, args.download_model)
    fails = [r for r in results if r.status == "fail"]
    warns = [r for r in results if r.status == "warn"]
    if args.json:
        nc.print_json({"ok": not fails, "checks": [r.as_dict() for r in results], "render": render or None})
    else:
        for r in results:
            print(r.line())
        if args.skip_render:
            print("(test render skipped: --skip-render)")
        summary = f"{len(results) - len(fails) - len(warns)} passed, {len(warns)} warnings, {len(fails)} failed"
        print(("READY: " if not fails else "NOT READY: ") + summary)
    return 1 if fails else 0


if __name__ == "__main__":
    nc.run_cli(main)
