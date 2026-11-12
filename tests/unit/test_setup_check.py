"""setup_check.py (T10, R267, R270): the real checks, simulated failures, exit codes."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import types
from pathlib import Path

import pytest

import setup_check

EXPECTED = ["python", "import numpy", "import cv2", "import PIL", "import pillow_heif", "import librosa",
            "import faster_whisper", "import jsonschema", "import imageio_ffmpeg", "ffmpeg", "ffprobe",
            "fonts", "assets", "brand.json", "config", "face model", "disk", "speech model"]


def clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NUMA_")}
    env.update(extra)
    return env


def run_check(run_script, *args, env: dict | None = None, timeout: float = 180):
    full = clean_env(**(env or {}))
    # run_script merges into os.environ; drop inherited NUMA_* overrides explicitly
    for k in [k for k in os.environ if k.startswith("NUMA_") and k not in full]:
        full[k] = ""
    return run_script("setup_check.py", *args, env=full, timeout=timeout)


def by_name(report: dict) -> dict:
    return {c["name"]: c for c in report["checks"]}


# --------------------------------------------------------------------------- real runs
def test_skip_render_real_environment(run_script):
    proc = run_check(run_script, "--skip-render", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True and report["render"] is None
    names = [c["name"] for c in report["checks"]]
    assert names == EXPECTED
    for c in report["checks"]:
        assert c["status"] in ("pass", "warn"), c
        if c["status"] == "warn":
            assert c["fix"], c


def test_human_output_one_line_per_check(run_script):
    proc = run_check(run_script, "--skip-render")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.strip().splitlines()
    marked = [ln for ln in lines if ln.startswith(("✅", "❌", "⚠️"))]
    assert len(marked) == len(EXPECTED)
    assert lines[-1].startswith("READY: ")
    assert "test render skipped" in proc.stdout


def test_full_run_renders_and_checks_a_3s_reel(run_script):
    proc = run_check(run_script, "--json", timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    render = report["render"]
    try:
        assert by_name(report)["test render"]["status"] == "pass"
        reel, strip = Path(render["reel"]), Path(render["qa_strip"])
        assert reel.is_file() and strip.is_file()
        probe = render["check_output"]["probe"]
        assert (probe["width"], probe["height"]) == (1080, 1920)
        assert abs(probe["duration"] - 3.0) < 0.1
        assert render["check_output"]["ok"] is True
        assert Path(render["folder"]).name.startswith(setup_check.TEST_DIR_PREFIX)
    finally:
        shutil.rmtree(render["folder"], ignore_errors=True)


# --------------------------------------------------------------------------- simulated failures (subprocess)
def test_missing_import_fails_with_fix(run_script, tmp_path):
    fake = tmp_path / "fake_site"
    fake.mkdir()
    (fake / "librosa.py").write_text("raise ImportError(\"No module named 'librosa'\")\n")
    proc = run_check(run_script, "--skip-render", env={"PYTHONPATH": str(fake)})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if "import librosa" in ln)
    assert line.startswith("❌") and "fix: pip install librosa" in line
    assert proc.stdout.strip().splitlines()[-1].startswith("NOT READY")
    assert "Traceback" not in proc.stderr


def test_missing_ffmpeg_fails_and_blocks_render(run_script, tmp_path):
    proc = run_check(run_script, "--json", env={"NUMA_FFMPEG": str(tmp_path / "no-ffmpeg")})
    assert proc.returncode == 1
    checks = by_name(json.loads(proc.stdout))
    assert checks["ffmpeg"]["status"] == "fail" and "brew install ffmpeg" in checks["ffmpeg"]["fix"]
    assert checks["test render"]["status"] == "fail" and "not run" in checks["test render"]["detail"]


@pytest.mark.skipif(sys.platform == "win32", reason="shell script stand-in for ffmpeg")
def test_ffmpeg_without_x264_or_aac_fails(run_script, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho 'ffmpeg version 0.0-test'\necho ' V....D mpeg4  MPEG-4 part 2'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    proc = run_check(run_script, "--skip-render", "--json", env={"NUMA_FFMPEG": str(fake)})
    assert proc.returncode == 1
    ff = by_name(json.loads(proc.stdout))["ffmpeg"]
    assert ff["status"] == "fail" and "libx264" in ff["detail"]


def test_broken_brand_json_fails(run_script, tmp_path):
    bad = tmp_path / "brand.json"
    bad.write_text('{"schema_version": 2}')
    proc = run_check(run_script, "--skip-render", "--json", env={"NUMA_BRAND": str(bad)})
    assert proc.returncode == 1
    b = by_name(json.loads(proc.stdout))["brand.json"]
    assert b["status"] == "fail" and "/brand-setup" in b["fix"]


def test_usage_error_exits_2(run_script):
    proc = run_check(run_script, "--bogus")
    assert proc.returncode == 2 and "ERROR:" in proc.stderr


# --------------------------------------------------------------------------- unit checks (in process)
def test_python_version_rule(monkeypatch):
    assert setup_check.check_python().status == "pass"
    monkeypatch.setattr(sys, "version_info", types.SimpleNamespace(major=3, minor=9, micro=7))
    r = setup_check.check_python()
    assert r.status == "fail" and "3.9.7" in r.detail and r.fix


def test_opencv_5_is_rejected(monkeypatch):
    fake = types.ModuleType("cv2")
    fake.__version__ = "5.0.0"
    fake.FaceDetectorYN = object
    monkeypatch.setitem(sys.modules, "cv2", fake)
    r = setup_check.check_import("cv2")
    assert r.status == "fail" and "<5" in r.fix


def test_opencv_without_haar_is_rejected(monkeypatch):
    fake = types.ModuleType("cv2")
    fake.__version__ = "4.11.0"
    fake.FaceDetectorYN = object
    monkeypatch.setitem(sys.modules, "cv2", fake)
    r = setup_check.check_import("cv2")
    assert r.status == "fail" and "CascadeClassifier" in r.detail


def test_low_disk_fails(monkeypatch):
    monkeypatch.setattr(setup_check.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=int(0.5e9)))
    r = setup_check.check_disk()
    assert r.status == "fail" and "0.5 GB" in r.detail and r.fix


def test_speech_model_missing_is_a_warning_and_download_failure_a_failure(monkeypatch):
    import faster_whisper.utils as fwu

    def no_model(name, local_files_only=False, **kw):
        raise OSError("offline" if not local_files_only else "not cached")

    monkeypatch.setattr(fwu, "download_model", no_model)
    r = setup_check.check_speech_model(download=False)
    assert r.status == "warn" and "--download-model" in r.fix
    r = setup_check.check_speech_model(download=True)
    assert r.status == "fail" and "offline" in r.detail


def test_download_model_fetches_when_not_cached(monkeypatch, tmp_path):
    import faster_whisper
    import faster_whisper.utils as fwu
    calls = []

    def fake_download(name, local_files_only=False, **kw):
        calls.append(local_files_only)
        if local_files_only:
            raise OSError("not cached")
        return str(tmp_path)

    monkeypatch.setattr(fwu, "download_model", fake_download)
    monkeypatch.setattr(faster_whisper, "WhisperModel", lambda *a, **k: object())
    r = setup_check.check_speech_model(download=True)
    assert r.status == "pass" and calls == [True, False]


def test_one_crashing_check_does_not_hide_the_others(monkeypatch):
    monkeypatch.setattr(setup_check, "check_fonts", lambda: 1 / 0)
    results, render = setup_check.run_checks(skip_render=True, download_model=False)
    fonts = next(r for r in results if r.name == "fonts")
    assert fonts.status == "fail" and "ZeroDivisionError" in fonts.detail
    assert [r.name for r in results] == EXPECTED and render == {}


def test_render_is_blocked_by_failed_prerequisites():
    r, info = setup_check.test_render(["ffmpeg"])
    assert r.status == "fail" and "ffmpeg" in r.detail and info == {}
