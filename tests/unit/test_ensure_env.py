"""ensure_env.py: idempotent environment bootstrap with a fast path (R339). pip, Playwright and the model download
are replaced by fakes: these tests never install or download anything."""
from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

import ensure_env
import numa_common


@pytest.fixture
def env(tmp_path, nc, monkeypatch):
    """A requirements file with one fake package that 'pip' installs by writing a module onto sys.path."""
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setenv("NUMA_CACHE", str(tmp_path / "cache"))
    req = tmp_path / "requirements.txt"
    req.write_text("# test\nnumpy>=1.0\nnuma-fake-pkg>=1.0  # installed by the fake pip\n")
    calls: list[list[str]] = []
    state = {"pip_rc": [0], "pip_err": ""}

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd[1:4] == ["-m", "pip", "install"]:
            rc = state["pip_rc"].pop(0) if state["pip_rc"] else 0
            if rc == 0:
                (site / "numa_fake_pkg.py").write_text("VERSION = '1.0'\n")
            return subprocess.CompletedProcess(cmd, rc, "", state["pip_err"] if rc else "")
        if cmd[1:4] == ["-m", "playwright", "install"]:
            (tmp_path / "chrome").write_text("bin")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected subprocess {cmd}")

    monkeypatch.setattr(ensure_env.subprocess, "run", fake_run)
    monkeypatch.setattr(ensure_env, "ffmpeg_path", lambda: (sys.executable, "system"))
    monkeypatch.setattr(ensure_env, "chromium_path",
                        lambda: str(tmp_path / "chrome") if (tmp_path / "chrome").exists() else None)
    monkeypatch.setattr(ensure_env, "model_cached", lambda: None)
    monkeypatch.setattr(ensure_env, "model_download", lambda: (None, "Connection error"))
    return {"req": req, "calls": calls, "state": state, "site": site, "tmp": tmp_path}


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(ensure_env.main, argv)
    return e.value.code


def pip_calls(env):
    return [c for c in env["calls"] if c[1:3] == ["-m", "pip"]]


def report(capsys, env, *extra, code=0):
    capsys.readouterr()
    assert run(["--requirements", str(env["req"]), "--json", *extra]) == code
    out = capsys.readouterr()
    return json.loads(out.out), out.err


def test_cold_run_installs_then_warm_run_is_fast(env, capsys):
    rep, _ = report(capsys, env)
    assert rep["ready"] and not rep["fast_path"] and rep["installed"] == ["packages"]
    (pip,) = pip_calls(env)
    assert pip[3:] == ["install", "--quiet", "--disable-pip-version-check", "-r", str(env["req"])]
    stamp = json.loads((env["tmp"] / "cache" / "ensure_env.json").read_text())
    assert stamp["key"] == rep["key"] and rep["key"].endswith(f"-py{sys.version_info[0]}.{sys.version_info[1]}")
    t0 = time.monotonic()
    rep2, _ = report(capsys, env)
    assert time.monotonic() - t0 < 5
    assert rep2["ready"] and rep2["fast_path"] and len(pip_calls(env)) == 1  # nothing re-installed


def test_check_only_reports_and_changes_nothing(env, capsys):
    rep, err = report(capsys, env, "--check-only", code=1)
    assert not rep["ready"] and pip_calls(env) == []
    bad = next(c for c in rep["checks"] if c["name"] == "packages")
    assert "numa-fake-pkg (not installed)" in bad["detail"] and "pip install -r" in bad["fix"]
    assert "ERROR: packages: missing or too old: numa-fake-pkg (not installed). Fix: python3 -m pip install -r" in err
    assert not (env["tmp"] / "cache" / "ensure_env.json").exists()


def test_changed_requirements_reinstall_once(env, capsys):
    report(capsys, env)
    env["req"].write_text(env["req"].read_text() + "jsonschema>=4.0\n")
    rep, _ = report(capsys, env)
    assert rep["ready"] and not rep["fast_path"] and len(pip_calls(env)) == 2  # hash changed: pip ran again
    assert "requirements.txt changed" in next(c for c in rep["checks"] if c["name"] == "packages")["detail"]
    rep, _ = report(capsys, env)
    assert rep["fast_path"] and len(pip_calls(env)) == 2


def test_externally_managed_python_retries(env, capsys):
    env["state"].update(pip_rc=[1, 0], pip_err="error: externally-managed-environment")
    rep, _ = report(capsys, env)
    assert rep["ready"]
    assert [c[-1] for c in pip_calls(env)] == [str(env["req"]), "--break-system-packages"]


def test_pip_failure_is_a_clean_error(env, capsys):
    env["state"].update(pip_rc=[1, 1], pip_err="No matching distribution found for numa-fake-pkg")
    rep, err = report(capsys, env, code=1)
    assert not rep["ready"] and [c[-1] for c in pip_calls(env)] == [str(env["req"]), "--user"]
    assert "ERROR: packages: pip could not install numa-fake-pkg" in err and "Traceback" not in err
    assert not (env["tmp"] / "cache" / "ensure_env.json").exists()


def test_too_old_version_counts_as_missing(env, capsys):
    env["req"].write_text("numpy>=999\n")
    rep, _ = report(capsys, env, "--check-only", code=1)
    assert "numpy" in rep["checks"][1]["detail"] and "needs >=999" in rep["checks"][1]["detail"]


def test_speech_model_offline_and_online(env, capsys, monkeypatch):
    rep, err = report(capsys, env, "--with-model", code=1)
    model = next(c for c in rep["checks"] if c["name"] == "speech model")
    assert not model["ok"] and "offline" in model["detail"] and "--with-model" in model["fix"]
    assert "ERROR: speech model:" in err
    rep, _ = report(capsys, env, "--with-model", "--check-only", code=1)
    assert "not downloaded" in next(c for c in rep["checks"] if c["name"] == "speech model")["detail"]
    cached = env["tmp"] / "model"
    cached.mkdir()
    monkeypatch.setattr(ensure_env, "model_download", lambda: (str(cached), ""))
    rep, _ = report(capsys, env, "--with-model")
    assert rep["ready"] and "speech model" in rep["installed"]
    rep, _ = report(capsys, env, "--with-model")
    assert rep["fast_path"]  # the stamp remembers the model path


def test_chromium_installed_when_missing(env, capsys):
    env["req"].write_text(env["req"].read_text() + "playwright>=1.45\n")
    (env["site"] / "playwright.py").write_text("")  # importable for the package check
    (env["site"] / "numa_fake_pkg.py").write_text("")
    rep, _ = report(capsys, env, "--with-chromium", "--check-only", code=1)
    assert "playwright install chromium" in next(c for c in rep["checks"] if c["name"] == "chromium")["fix"]
    rep, _ = report(capsys, env, "--with-chromium")
    assert rep["ready"] and "chromium" in rep["installed"]
    assert [c[1:5] for c in env["calls"] if "playwright" in c] == [["-m", "playwright", "install", "chromium"]]
    rep, _ = report(capsys, env, "--with-chromium")
    assert rep["fast_path"]


def test_chromium_without_playwright_in_requirements_warns(env, capsys):
    capsys.readouterr()
    assert run(["--requirements", str(env["req"]), "--with-chromium"]) == 0
    out = capsys.readouterr()
    assert "WARN: chromium: playwright is not in requirements.txt" in out.err and "ready" in out.out


def test_ffmpeg_missing(env, capsys, monkeypatch):
    monkeypatch.setattr(ensure_env, "ffmpeg_path", lambda: (None, "ffmpeg not found"))
    rep, err = report(capsys, env, code=1)
    assert "brew install ffmpeg" in next(c for c in rep["checks"] if c["name"] == "ffmpeg")["fix"]


def test_missing_requirements_file(env, capsys, tmp_path):
    capsys.readouterr()
    assert run(["--requirements", str(tmp_path / "nope.txt")]) == 1
    assert "ERROR: requirements:" in capsys.readouterr().err


@pytest.mark.parametrize("version,clauses,ok", [
    ("4.10.0", [(">=", "4.8"), ("<", "5")], True),
    ("5.0.1", [(">=", "4.8"), ("<", "5")], False),
    ("1.0", [("==", "1.0.0")], True),
    ("1.4.2", [("~=", "1.4")], True),
    ("2.0", [("~=", "1.4")], False),
    ("1.4.9", [("~=", "1.4.2")], True),
    ("1.5.0", [("~=", "1.4.2")], False),
    ("3.2.1", [("==", "3.2.*")], True),
    ("3.3", [("!=", "3.2.*")], True),
    ("0.10.2.post1", [(">=", "0.10")], True),
])
def test_version_clauses(version, clauses, ok):
    assert ensure_env.satisfies(version, clauses) is ok


def test_parses_the_plugin_requirements(repo_root):
    reqs = ensure_env.parse_requirements(repo_root / "requirements.txt")
    mods = {r["dist"]: r["module"] for r in reqs}
    assert mods["opencv-python-headless"] == "cv2" and mods["pillow"] == "PIL" and mods["faster-whisper"] == "faster_whisper"
    assert mods["imageio-ffmpeg"] == "imageio_ffmpeg" and "playwright" in mods
    assert next(r for r in reqs if r["dist"] == "opencv-python-headless")["clauses"] == [(">=", "4.8"), ("<", "5")]


def test_default_cache_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("NUMA_CACHE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ensure_env.cache_dir() == tmp_path / ".cache" / "numa-studio"


def test_real_warm_run_under_five_seconds(tmp_path, scripts_dir):
    """End to end with the real interpreter: a requirement that is installed, so nothing is installed."""
    req = tmp_path / "requirements.txt"
    req.write_text("numpy>=1.0\n")
    env = {**__import__("os").environ, "NUMA_CACHE": str(tmp_path / "cache")}
    cmd = [sys.executable, str(scripts_dir / "ensure_env.py"), "--requirements", str(req)]
    first = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    assert first.returncode == 0, first.stderr
    t0 = time.monotonic()
    warm = subprocess.run(cmd + ["--json"], capture_output=True, text=True, env=env, timeout=60)
    assert time.monotonic() - t0 < 5
    rep = json.loads(warm.stdout)
    assert warm.returncode == 0 and rep["ready"] and rep["fast_path"] and rep["installed"] == []
