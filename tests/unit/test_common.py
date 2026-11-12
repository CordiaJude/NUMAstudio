"""Unit tests for skills/numa-reel-editor/scripts/numa_common.py."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- locations
def test_paths_resolve_relative_to_the_file(nc, repo_root):
    assert nc.PLUGIN_ROOT == repo_root
    assert (nc.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").is_file()
    assert nc.ASSETS_DIR.is_dir() and nc.FONTS_DIR.is_dir() and nc.BRAND_PHOTOS_DIR.is_dir()
    assert nc.BRAND_PATH.is_file() and nc.CONFIG_PATH.is_file() and nc.SCHEMAS_DIR.is_dir()
    assert nc.plugin_path("brand/brand.json") == nc.BRAND_PATH
    assert nc.plugin_path("/abs/x.png") == Path("/abs/x.png")


def test_import_from_any_cwd(scripts_dir, tmp_path):
    """R8: a script run by absolute path from another folder still finds the plugin's files."""
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(scripts_dir)!r})
        import numa_common as nc
        print(nc.load_brand()['business']['name']['value']['short'], nc.brand_font('regular').is_file())
    """))
    out = subprocess.run([sys.executable, str(probe)], cwd=os.sep, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["NUMA", "True"]


# --------------------------------------------------------------------------- ffmpeg lookup
def test_ffmpeg_bin_prefers_system(nc, monkeypatch):
    monkeypatch.setattr(nc.shutil, "which", lambda name: "/usr/bin/" + name if name == "ffmpeg" else None)
    assert nc.ffmpeg_bin() == "/usr/bin/ffmpeg"


def test_ffmpeg_bin_falls_back_to_imageio(nc, monkeypatch):
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    monkeypatch.setattr(nc.shutil, "which", lambda name: None)
    exe = nc.ffmpeg_bin()
    assert exe == imageio_ffmpeg.get_ffmpeg_exe() and Path(exe).is_file()


def test_ffmpeg_bin_missing_everywhere_is_a_user_error(nc, monkeypatch):
    monkeypatch.setattr(nc.shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)  # import fails
    with pytest.raises(nc.UserError, match="ffmpeg not found"):
        nc.ffmpeg_bin()


def test_ffmpeg_env_override(nc, monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("")
    monkeypatch.setenv("NUMA_FFMPEG", str(fake))
    assert nc.ffmpeg_bin() == str(fake)
    nc.clear_caches()
    monkeypatch.setenv("NUMA_FFMPEG", str(tmp_path / "missing"))
    with pytest.raises(nc.UserError, match="NUMA_FFMPEG"):
        nc.ffmpeg_bin()


def test_ffprobe_bin_none_when_absent(nc, monkeypatch, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg-imageio-linux64"
    fake_ffmpeg.write_text("")
    monkeypatch.setenv("NUMA_FFMPEG", str(fake_ffmpeg))
    monkeypatch.setattr(nc.shutil, "which", lambda name: None)
    assert nc.ffprobe_bin() is None


# --------------------------------------------------------------------------- probing
def test_media_info_video_with_and_without_ffprobe(nc, tmp_path, make_video, monkeypatch):
    clip = make_video(tmp_path / "clip.mp4", seconds=1.0, size=(320, 240), fps=30, audio=True)
    a = nc.media_info(clip)
    assert (a["width"], a["height"], a["has_audio"], a["vcodec"], a["acodec"]) == (320, 240, True, "h264", "aac")
    assert a["fps"] == pytest.approx(30, abs=0.01)
    assert a["duration"] == pytest.approx(1.0, abs=0.1)
    assert a["sample_rate"] == 48000 and a["channels"] == 2

    nc.clear_caches()
    monkeypatch.setenv("NUMA_FFPROBE", str(tmp_path / "no-ffprobe"))
    assert nc.ffprobe_bin() is None
    raw = nc.ffprobe_json(clip)
    assert raw["_fallback"] is True and {s["codec_type"] for s in raw["streams"]} == {"video", "audio"}
    b = nc.media_info(clip)
    for key in ("width", "height", "has_audio", "has_video", "vcodec", "acodec", "sample_rate", "channels", "pix_fmt", "profile"):
        assert a[key] == b[key], key
    assert b["fps"] == pytest.approx(a["fps"], abs=0.01)
    assert b["duration"] == pytest.approx(a["duration"], abs=0.02)


def test_media_info_rotation_and_silent_clip(nc, tmp_path, make_video, monkeypatch):
    clip = make_video(tmp_path / "rot.mp4", seconds=0.5, size=(320, 240), audio=False, rotate=90)
    for fallback in (False, True):
        nc.clear_caches()
        if fallback:
            monkeypatch.setenv("NUMA_FFPROBE", str(tmp_path / "none"))
        info = nc.media_info(clip)
        assert abs(info["rotation"]) == 90
        assert (info["width"], info["height"]) == (240, 320)  # display size
        assert info["has_audio"] is False


def test_media_info_audio_and_image(nc, tmp_path, make_audio, assets_dir):
    wav = make_audio(tmp_path / "a.wav", seconds=1.5, kind="tone")
    info = nc.media_info(wav)
    assert info["has_video"] is False and info["sample_rate"] == 48000
    assert nc.media_duration(wav) == pytest.approx(1.5, abs=0.05)
    img = nc.media_info(assets_dir / "heroimage.jpg")
    assert (img["width"], img["height"]) == (1500, 800)


def test_ffprobe_json_rejects_non_media(nc, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(nc.UserError):
        nc.ffprobe_json(bad)
    with pytest.raises(nc.UserError, match="not found"):
        nc.ffprobe_json(tmp_path / "missing.mp4")


def test_parse_ffmpeg_info_sample():
    import numa_common as nc
    text = textwrap.dedent("""\
        Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'IMG_0001.MOV':
          Duration: 00:00:12.40, start: 0.000000, bitrate: 14123 kb/s
          Stream #0:0[0x1](und): Video: hevc (Main 10) (hvc1 / 0x31637668), yuv420p10le(tv, bt2020nc/bt2020/arib-std-b67), 3840x2160, 13900 kb/s, 29.97 fps, 29.97 tbr, 600 tbn (default)
              Side data:
                displaymatrix: rotation of -90.00 degrees
          Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 96 kb/s (default)
    """)
    d = nc.parse_ffmpeg_info(text)
    v, a = d["streams"]
    assert d["format"]["duration"].startswith("12.4") and d["format"]["bit_rate"] == "14123000"
    assert (v["codec_name"], v["profile"], v["pix_fmt"], v["width"], v["height"]) == ("hevc", "Main 10", "yuv420p10le", 3840, 2160)
    assert v["avg_frame_rate"] == "30000/1001" and v["side_data_list"] == [{"rotation": -90.0}]
    assert (a["codec_name"], a["sample_rate"], a["channels"]) == ("aac", "44100", 1)


# --------------------------------------------------------------------------- JSON IO
def test_write_json_is_atomic_and_stable(nc, tmp_path):
    p = tmp_path / "sub" / "plan.json"
    nc.write_json(p, {"b": 1, "a": [1, 2], "é": "ü"})
    text = p.read_text(encoding="utf-8")
    assert text == '{\n  "b": 1,\n  "a": [\n    1,\n    2\n  ],\n  "é": "ü"\n}\n'
    nc.write_json(p, {"b": 1, "a": 2}, sort_keys=True)
    assert p.read_text().startswith('{\n  "a": 2')
    assert [f.name for f in p.parent.iterdir()] == ["plan.json"]  # no temp files left


def test_write_json_failure_leaves_old_file(nc, tmp_path):
    p = tmp_path / "plan.json"
    nc.write_json(p, {"ok": True})
    for bad in ({"x": float("nan")}, {"x": object()}):
        with pytest.raises(nc.UserError, match="cannot write JSON"):
            nc.write_json(p, bad)
        assert json.loads(p.read_text()) == {"ok": True}
    assert [f.name for f in tmp_path.iterdir()] == ["plan.json"]


def test_write_json_cleans_temp_on_replace_error(nc, tmp_path, monkeypatch):
    p = tmp_path / "x.json"

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(nc.os, "replace", boom)
    with pytest.raises(OSError):
        nc.write_json(p, {"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_read_json_errors_are_readable(nc, tmp_path):
    with pytest.raises(nc.UserError, match="plan not found"):
        nc.read_json(tmp_path / "nope.json", "plan")
    bad = tmp_path / "bad.json"
    bad.write_text('{"duration": 39,\n "shots": [}\n')
    with pytest.raises(nc.UserError, match=r"invalid JSON at line 2 column \d+"):
        nc.read_json(bad)
    with pytest.raises(nc.UserError, match="folder"):
        nc.read_json(tmp_path)


def test_update_report_sections(nc, tmp_path):
    nc.update_report(tmp_path, "finish", {"lufs": -15.0})
    nc.update_report(tmp_path, "formats", {"files": 3})
    nc.update_report(tmp_path, "finish", {"lufs": -14.8})
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep == {"schema_version": 1, "finish": {"lufs": -14.8}, "formats": {"files": 3}}


# --------------------------------------------------------------------------- run_cli
def _exit(nc, func, capsys):
    with pytest.raises(SystemExit) as ex:
        nc.run_cli(func)
    out = capsys.readouterr()
    return ex.value.code, out.out + out.err


@pytest.mark.parametrize("exc, code, text", [
    ("user", 1, "ERROR: plan has no shots"),
    ("usage", 2, "ERROR: need a plan.json"),
    ("json", 1, "ERROR: invalid JSON at line 1 column 1"),
    ("missing", 1, "ERROR: file not found: /no/such/file.json"),
    ("unexpected", 1, "ERROR: unexpected ZeroDivisionError"),
    ("ok", 0, ""),
    ("rc3", 3, ""),
])
def test_run_cli_exit_codes_without_traceback(nc, capsys, exc, code, text):
    def main():
        if exc == "user":
            raise nc.UserError("plan has no shots")
        if exc == "usage":
            raise nc.UsageError("need a plan.json")
        if exc == "json":
            json.loads("not json")
        if exc == "missing":
            open("/no/such/file.json")
        if exc == "unexpected":
            return 1 / 0
        if exc == "rc3":
            return 3
        return None

    got_code, output = _exit(nc, main, capsys)
    assert got_code == code
    assert text in output
    assert "Traceback" not in output
    if text:
        assert output.strip().count("\n") == 0  # exactly one line


def test_run_cli_subprocess_and_debug(scripts_dir, tmp_path):
    script = tmp_path / "tool.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(scripts_dir)!r})
        import numa_common as nc
        def main(argv=None):
            ap = nc.ArgParser(prog="tool.py", description="demo")
            ap.add_argument("plan")
            a = ap.parse_args(argv)
            if a.plan == "boom":
                raise RuntimeError("kaput")
            nc.read_json(a.plan, "plan")
            return 0
        if __name__ == "__main__":
            nc.run_cli(main)
    """))

    def run(*args, env=None):
        e = dict(os.environ)
        e.pop("NUMA_DEBUG", None)
        e.update(env or {})
        return subprocess.run([sys.executable, str(script), *args], cwd=os.sep, capture_output=True, text=True, env=e)

    r = run()
    assert r.returncode == 2 and "ERROR:" in r.stderr and "usage: tool.py" in r.stderr and "Traceback" not in r.stderr
    r = run(str(tmp_path / "missing.json"))
    assert r.returncode == 1 and r.stderr.startswith("ERROR: plan not found") and "Traceback" not in r.stderr
    (tmp_path / "bad.json").write_text("{")
    r = run(str(tmp_path / "bad.json"))
    assert r.returncode == 1 and "invalid JSON" in r.stderr and "Traceback" not in r.stderr
    r = run("boom")
    assert r.returncode == 1 and "unexpected RuntimeError: kaput" in r.stderr and "Traceback" not in r.stderr
    r = run("boom", env={"NUMA_DEBUG": "1"})
    assert r.returncode == 1 and "Traceback" in r.stderr
    r = run("--help")
    assert r.returncode == 0 and "usage: tool.py" in r.stdout


# --------------------------------------------------------------------------- run()
def test_run_raises_user_error_with_stderr_tail(nc):
    cmd = [sys.executable, "-c", "import sys; print('line1', file=sys.stderr); print('the real problem', file=sys.stderr); sys.exit(3)"]
    with pytest.raises(nc.UserError) as ex:
        nc.run(cmd, what="demo")
    msg = str(ex.value)
    assert "demo failed (exit 3)" in msg and "the real problem" in msg
    assert nc.run(cmd, check=False).returncode == 3


def test_run_missing_program_and_timeout(nc):
    with pytest.raises(nc.UserError, match="program not found"):
        nc.run(["definitely-not-a-program-numa"])
    with pytest.raises(nc.UserError, match="timed out"):
        nc.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)


def test_ffmpeg_helper_reports_failures(nc, tmp_path):
    with pytest.raises(nc.UserError, match="ffmpeg failed"):
        nc.ffmpeg("-i", str(tmp_path / "missing.wav"), str(tmp_path / "out.wav"))


# --------------------------------------------------------------------------- schemas
def test_validate_against_readable_paths(nc, plan_factory):
    plan = plan_factory()
    nc.validate_against("plan", plan)
    plan["shots"][1]["tr"] = "zoom"
    plan["lines"][0]["words"][2] = ["wide"]
    errs = nc.schema_errors("plan", plan)
    assert any(e.startswith("shots[1].tr: 'zoom' is not one of") for e in errs), errs
    assert any(e.startswith("lines[0].words[2]: must have at least 2 items") for e in errs), errs
    with pytest.raises(nc.UserError, match=r"plan\.json does not match plan\.schema\.json: .*shots\[1\]\.tr"):
        nc.validate_against("plan", plan, what="plan.json")


def test_schema_error_messages(nc, plan_factory):
    plan = plan_factory()
    del plan["duration"]
    plan["colour"] = "gold"
    plan["size"] = [1081, 1920]
    errs = nc.schema_errors("plan", plan)
    assert "(top level): missing required field 'duration'" in errs
    assert "(top level): unknown field 'colour'" in errs
    assert "size[0]: must be a multiple of 2, got 1081" in errs


# --------------------------------------------------------------------------- brand and config
def test_load_brand_and_config(nc):
    brand = nc.load_brand()
    assert brand is nc.load_brand()  # cached
    assert nc.brand_value("business.name.short") == "NUMA"
    assert nc.accent_rgb() == [247, 214, 160]
    assert nc.brand_color("caption_text") == [255, 255, 255]
    for key in ("wordmark", "secondary_mark", "endcard_background", "brand_photos_dir"):
        assert nc.brand_asset(key).exists(), key
    assert nc.brand_font("regular").is_file() and nc.brand_font("italic").is_file()
    cfg = nc.load_config()
    assert nc.config_value("render.fps") == 30 and nc.config_value("render.size") == [1080, 1920]
    assert nc.config_value("models.agents.critic") == "opus"
    assert nc.config_value("no.such.key", "dflt") == "dflt"
    assert cfg is nc.load_config()


def test_brand_override_changes_accent(nc, monkeypatch, tmp_path):
    brand = json.loads(nc.BRAND_PATH.read_text())
    brand["palette"]["value"]["caption_gold"] = "#102030"
    alt = tmp_path / "brand.json"
    alt.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(alt))
    assert nc.accent_rgb() == [16, 32, 48]


def test_bad_brand_is_a_readable_error(nc, monkeypatch, tmp_path):
    brand = json.loads(nc.BRAND_PATH.read_text())
    brand["palette"]["value"]["caption_gold"] = "gold"
    del brand["claims"]["banned"]
    alt = tmp_path / "brand.json"
    alt.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(alt))
    with pytest.raises(nc.UserError) as ex:
        nc.load_brand()
    msg = str(ex.value)
    assert "claims: missing required field 'banned'" in msg
    assert "palette.value.caption_gold: 'gold' does not match the pattern" in msg

    brand = json.loads(nc.BRAND_PATH.read_text())
    brand["claims"]["banned"][0]["patterns"] = ["(unclosed"]
    alt.write_text(json.dumps(brand))
    nc.clear_caches()
    with pytest.raises(nc.UserError, match="bad pattern"):
        nc.load_brand()


def test_config_missing_section(nc, monkeypatch, tmp_path):
    alt = tmp_path / "studio.json"
    alt.write_text(json.dumps({"models": {}}))
    monkeypatch.setenv("NUMA_CONFIG", str(alt))
    with pytest.raises(nc.UserError, match="missing the 'higgsfield' section"):
        nc.load_config()


# --------------------------------------------------------------------------- small helpers
def test_slug_job_paths_and_deliverables(nc, tmp_path):
    assert nc.slugify("2026-11-09 Year One!") == "2026-11-09-year-one"
    assert nc.slugify("***") == "reel"
    jp = nc.JobPaths(tmp_path / "Day 07 - 2026-12-09 - Your first plunge").make()
    assert jp.raw.is_dir() and jp.work.is_dir() and jp.out.is_dir()
    assert jp.plan == jp.work / "plan.json" and jp.analysis == jp.work / "analysis.json"
    assert jp.deliverable("reel").name == "day-07-2026-12-09-your-first-plunge_reel.mp4"
    assert nc.deliverable_name("year-one", "story", 2, "mp4") == "year-one_story_2.mp4"
    assert nc.deliverable_name("year-one", "carousel", 1) == "year-one_carousel_1.jpg"
    assert nc.deliverable_name("year-one", "srt") == "year-one.srt"
    assert nc.deliverable_name("year-one", "cover") == "year-one_cover.jpg"
    with pytest.raises(nc.UserError):
        nc.deliverable_name("x", "story")
    with pytest.raises(nc.UserError):
        nc.deliverable_name("x", "poster")


def test_parse_size_and_misc(nc):
    assert nc.parse_size("1080x1350") == (1080, 1350)
    for bad in ("1080", "1081x1920", "8x8", ""):
        with pytest.raises(nc.UsageError):
            nc.parse_size(bad)
    assert nc.hex_to_rgb("#F7D6A0") == [247, 214, 160]
    with pytest.raises(nc.UserError):
        nc.hex_to_rgb("gold")
    with pytest.raises(nc.UserError, match="absolute"):
        nc.require_abs("raw/a.jpg", "shot src")
    assert nc.dig({"a": [{"b": 2}]}, "a.0.b") == 2
    assert nc.fact({"value": 3, "status": "confirmed"}) == 3 and nc.fact(5) == 5
