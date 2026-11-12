"""Shared pytest fixtures for NUMA Studio unit tests.

Fixtures build small synthetic media (from the bundled brand photos and ffmpeg
lavfi sources) so no member photos or test-pack files are ever needed.

    repo_root, scripts_dir, assets_dir        paths
    nc                                        the numa_common module (caches cleared per test)
    job                                       a fresh JobPaths with raw/, work/, out/ created
    work_dir                                  shortcut for job.work
    make_image(path, size=(w, h), photo=None) a JPG/PNG made from a bundled brand photo
    make_audio(path, seconds, kind=...)       'tone' | 'music' (100 BPM pad + kick) | 'voice' | 'silence'
    make_video(path, seconds, size, fps, audio=True, rotate=0)
    plan_factory(**overrides)                 a valid schema_version 2 plan pointing at real files
    run_script(name, *args, cwd=None)         run scripts/<name> as a subprocess from any cwd
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "numa-reel-editor" / "scripts"
ASSETS_DIR = REPO_ROOT / "skills" / "numa-reel-editor" / "assets"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import numa_common  # noqa: E402

BRAND_PHOTOS = sorted((ASSETS_DIR / "brand-photos").glob("*.jpg"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def assets_dir() -> Path:
    return ASSETS_DIR


@pytest.fixture
def nc(monkeypatch):
    """numa_common with fresh caches and no NUMA_* overrides leaking in from the environment."""
    for var in ("NUMA_BRAND", "NUMA_CONFIG", "NUMA_FFMPEG", "NUMA_FFPROBE", "NUMA_DEBUG"):
        monkeypatch.delenv(var, raising=False)
    numa_common.clear_caches()
    yield numa_common
    numa_common.clear_caches()


@pytest.fixture
def job(tmp_path):
    return numa_common.JobPaths(tmp_path / "2026-12-01 Test Reel").make()


@pytest.fixture
def work_dir(job) -> Path:
    return job.work


def _ff(*args: str) -> None:
    numa_common.ffmpeg(*args)


@pytest.fixture
def make_image():
    from PIL import Image, ImageOps

    def _make(path, size=(840, 718), photo: str | None = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = ASSETS_DIR / "brand-photos" / photo if photo else BRAND_PHOTOS[0]
        with Image.open(src) as im:
            out = ImageOps.fit(im.convert("RGB"), tuple(size))
        out.save(path, quality=90) if path.suffix.lower() in (".jpg", ".jpeg") else out.save(path)
        return path

    return _make


@pytest.fixture
def make_audio():
    def _make(path, seconds: float = 3.0, kind: str = "tone", rate: int = 48000) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        d = f"{seconds:.3f}"
        if kind == "tone":
            src = f"sine=frequency=440:sample_rate={rate}:duration={d}"
        elif kind == "silence":
            src = f"anullsrc=r={rate}:cl=stereo:d={d}"
        elif kind == "music":
            # 100 BPM: a soft chord pad plus a decaying kick every 0.6 s
            src = (f"aevalsrc='0.15*sin(2*PI*220*t)+0.1*sin(2*PI*277*t)+0.1*sin(2*PI*330*t)"
                   f"+0.6*exp(-30*mod(t,0.6))*sin(2*PI*60*t)':s={rate}:d={d}")
        elif kind == "voice":
            # a gated, wobbling tone: speech-like energy bursts (not real words)
            src = (f"aevalsrc='0.5*sin(2*PI*(180+40*sin(2*PI*3*t))*t)*gt(sin(2*PI*1.7*t),-0.3)'"
                   f":s={rate}:d={d}")
        else:
            raise ValueError(f"unknown audio kind {kind!r}")
        _ff("-f", "lavfi", "-i", src, "-ac", "2", "-ar", str(rate), str(path))
        return path

    return _make


@pytest.fixture
def make_video():
    def _make(path, seconds: float = 2.0, size=(270, 480), fps: int = 30, audio: bool = True,
              rotate: int = 0) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        w, h = size
        args = ["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration={seconds:.3f}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={seconds:.3f}"]
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        args += ["-c:a", "aac", "-ac", "2", "-shortest"] if audio else ["-an"]
        if not rotate:
            _ff(*args, str(path))
            return path
        tmp = path.with_name(path.stem + "_unrotated" + path.suffix)
        _ff(*args, str(tmp))
        _ff("-display_rotation", str(rotate), "-i", str(tmp), "-c", "copy", str(path))
        tmp.unlink()
        return path

    return _make


@pytest.fixture
def plan_factory(job, make_image):
    """A valid v2 plan (3 photo shots, captions, end card) with real files under job/raw."""
    photos = [make_image(job.raw / f"p{i}.jpg", size=(720, 1280), photo=BRAND_PHOTOS[i % len(BRAND_PHOTOS)].name)
              for i in range(3)]
    wordmark = str(ASSETS_DIR / "Numa_Workmark_Dark.png")
    base = {
        "schema_version": 2,
        "duration": 9.0,
        "out_dir": str(job.work),
        "fps": 30,
        "size": [1080, 1920],
        "quality": "final",
        "seed": 0,
        "accent_rgb": [247, 214, 160],
        "caption_y": 1420,
        "hook": {"text": "Three minutes of cold.", "t1": 2.0},
        "shots": [
            {"src": str(photos[0]), "look": "warm", "t0": 0.0, "t1": 3.0, "z": [1.0, 1.12], "pan": [0, 0.02], "tr": "cut"},
            {"src": str(photos[1]), "look": "warm", "t0": 3.0, "t1": 5.4, "z": [1.14, 1.02], "tr": "punch"},
            {"src": str(photos[2]), "look": "none", "t0": 5.4, "t1": 9.0, "z": [1.0, 1.08], "tr": "flash"},
        ],
        "lines": [{"words": [["Walk", 0.3], ["out", 0.6], ["wide", 0.9], ["awake.", 1.2, 1]], "end": 2.6}],
        "leaks": [[3.0, 0.8, 0.4]],
        "endcard": {"t": 5.4, "logo": wordmark, "tagline": "Wellness Collective", "subtitle": "Your reset starts here."},
        "meta": {"slug": "test-reel"},
    }

    def _make(**overrides):
        plan = copy.deepcopy(base)
        plan.update(overrides)
        return plan

    return _make


@pytest.fixture
def run_script():
    def _run(name: str, *args, cwd: str | os.PathLike | None = None, env: dict | None = None,
             timeout: float = 120) -> subprocess.CompletedProcess:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run([sys.executable, str(SCRIPTS_DIR / name), *map(str, args)],
                              cwd=str(cwd or Path(os.sep)), env=full_env, capture_output=True,
                              text=True, timeout=timeout)

    return _run
