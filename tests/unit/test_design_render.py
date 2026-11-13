"""design_render.py (T14, R329-R332): component library, carousel.json validation, canvas build,
canvas and spec rendering with headless Chromium, and the per-slide checks.

Rendering tests skip when Python Playwright or its Chromium is not installed. Canvas tests use a
no-op `support.js` stand-in (the artboards then render as plain HTML, which is enough for the
routing, ordering, image, font and claims checks); the test that runs the real Claude Design
runtime reads it from $NUMA_DC_RUNTIME (the type's artifact-type/dc-runtime.js, never committed)
and skips without it.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

import design_render as dr

PHOTO = "skills/numa-reel-editor/assets/brand-photos/red-light.jpg"
DESIGN_TYPE = "https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd"


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 - not installed here
        return False


CHROMIUM = _chromium_ok()
needs_chromium = pytest.mark.skipif(not CHROMIUM, reason="Python Playwright + Chromium not installed")

ALL_SLIDES = [
    {"component": "cover", "fields": {"kicker": "Ask the DPT", "title": "Sauna vs red light: what's *different*?",
                                      "subtitle": "Two warm rooms, two very different sessions."}},
    {"component": "point", "fields": {"kicker": "The sauna", "number": "1", "title": "Heat that surrounds you",
                                      "body": "Our Finnish sauna warms the air around you. Deep, quiet heat to unwind."}},
    {"component": "stat", "fields": {"kicker": "By the numbers", "stat": "14", "label": "people fit in our Finnish sauna",
                                     "body": "Room for the whole crew.", "source": "NUMA, Midtown Mobile"}},
    {"component": "myth_fact", "fields": {"kicker": "Common mix-up", "myth": "Red light is a sauna with colored bulbs.",
                                          "fact": "A sauna heats the air. A red light panel shines light on you."}},
    {"component": "quote", "fields": {"kicker": "From the collective", "quote": "I come for the quiet and stay for the people.",
                                      "name": "A NUMA member", "role": "Sunday regular"}},
    {"component": "steps", "fields": {"kicker": "Try both", "title": "One easy way to start", "step1": "Begin in the sauna.",
                                      "step2": "Cool down and drink some water.", "step3": "Finish with red light.",
                                      "step4": "Notice how you feel."}},
    {"component": "offer", "fields": {"kicker": "New here?", "title": "Your first month at NUMA", "offer": "Discover NUMA",
                                      "details": "Classes, sauna and cold plunge.", "cta": "discover.numawellness.org"}},
    {"component": "photo", "photo": PHOTO, "photo_position": "50% 38%",
     "fields": {"kicker": "Red light", "caption": "Red light is *light*, not heat."}},
    {"component": "cta", "fields": {"title": "Feel the difference for yourself.", "body": "Your reset starts here.",
                                    "button": "discover.numawellness.org"}},
]


def spec(slides=None, **over) -> dict:
    d = {"schema_version": 1, "slug": "test-carousel", "title": "NUMA Carousel · 2026-12-08 · Test", "date": "2026-12-08",
         "caption": "Sauna vs red light in Mobile, AL. #MobileAL", "slides": copy.deepcopy(slides or ALL_SLIDES[:2])}
    d.update(over)
    return d


def write_spec(tmp_path: Path, data: dict, name: str = "carousel.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- library (no browser)
def test_library_has_every_component_in_both_forms():
    for comp in dr.COMPONENTS:
        html = dr.template_text(comp, "html")
        dc = dr.template_text(comp, "dc")
        assert dr.slide_markup(html) == dr.slide_markup(dc), f"{comp}: plain and .dc.html markup differ"
        assert 'href="carousel.css"' in html
        assert '<script src="./support.js"></script>' in dc and "class Component extends DCLogic" in dc
        assert '"$preview":{"width":1080,"height":1350}' in dc
        assert "width: 1080px; height: 1350px" in dr.slide_markup(html)
    assert (dr.COMPONENTS_DIR / "carousel.css").is_file()


def test_bundled_fonts_and_licences():
    for _, files in dr.BUNDLED_FONTS.values():
        for f in files.values():
            data = (dr.nc.FONTS_DIR / f).read_bytes()
            assert data[:4] == b"wOF2", f
    for lic in ("OFL-Fraunces.txt", "OFL-Inter.txt"):
        assert "SIL Open Font License" in (dr.nc.FONTS_DIR / lic).read_text()


def test_schema_fields_match_templates(repo_root):
    schema = json.loads((repo_root / "schemas" / "carousel.schema.json").read_text())
    assert schema["$defs"]["slide"]["properties"]["component"]["enum"] == list(dr.COMPONENTS)
    for comp in dr.COMPONENTS:
        required, optional = dr.template_fields(comp)
        fields = schema["$defs"][f"fields_{comp}"]
        assert set(fields["required"]) == required, comp
        assert set(fields["properties"]) == required | optional, comp


# --------------------------------------------------------------------------- validate
def test_validate_accepts_good_spec(run_script, tmp_path):
    p = write_spec(tmp_path, spec(ALL_SLIDES))
    proc = run_script("design_render.py", "validate", p, "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] and out["slides"] == 9 and out["errors"] == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["slides"][1]["fields"].update(body="Sweat out the toxins and detox."), "banned claim"),
    (lambda d: d.update(caption="Red light heals your joints."), "banned claim"),
    (lambda d: d["slides"].append({"component": "offer", "fields": {"kicker": "k", "title": "t", "offer": "Contrast Flow",
                                                                    "cta": "c"}}), "needs_katie"),
    (lambda d: d["slides"].append({"component": "offer", "fields": {"kicker": "k", "title": "t", "offer": "Float tank",
                                                                    "cta": "c"}}), "not in brand.json offerings"),
    (lambda d: d["slides"].append({"component": "photo", "photo": "nope/missing.jpg",
                                   "fields": {"kicker": "k", "caption": "c"}}), "photo not found"),
])
def test_validate_rejects(run_script, tmp_path, mutate, needle):
    d = spec(ALL_SLIDES[:2])
    mutate(d)
    proc = run_script("design_render.py", "validate", write_spec(tmp_path, d))
    assert proc.returncode == 1
    assert needle in proc.stderr and "Traceback" not in proc.stderr


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.update(slides=d["slides"][:1]), "slides"),
    (lambda d: d["slides"][0]["fields"].pop("title"), "title"),
    (lambda d: d["slides"][0]["fields"].update(price="$10"), "price"),
    (lambda d: d["slides"][0].update(component="poster"), "component"),
    (lambda d: d["slides"][0].update(photo=PHOTO), "photo"),
])
def test_schema_errors_are_one_line(run_script, tmp_path, mutate, needle):
    d = spec()
    mutate(d)
    proc = run_script("design_render.py", "validate", write_spec(tmp_path, d))
    assert proc.returncode == 1
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("ERROR:")]
    assert len(lines) == 1 and "not a valid carousel.json" in lines[0] and needle in lines[0]


def test_typed_price_is_a_warning(run_script, tmp_path):
    d = spec()
    d["slides"][0]["fields"]["subtitle"] = "Only $12 today."
    proc = run_script("design_render.py", "validate", write_spec(tmp_path, d))
    assert proc.returncode == 0 and "WARN:" in proc.stderr and "$12" in proc.stderr


def test_fill_rich_text_and_optional_blocks():
    t = "<p>{{a}}</p>\n<!--if:b-->\n<p>{{b}}</p>\n<!--/if:b-->\n"
    assert dr.fill(t, {"a": "x"}, set()) == "<p>x</p>\n"
    assert "<p>y</p>" in dr.fill(t, {"a": "x", "b": "y"}, {"b"})
    with pytest.raises(dr.nc.UserError):
        dr.fill("{{nope}}", {}, set())
    out = dr.rich("What's *new* <now>\nnext", "#C8643C")
    assert "What’s" in out and "&lt;now&gt;" in out and "<br>" in out and 'color: #C8643C">new</em>' in out


# --------------------------------------------------------------------------- build (canvas files)
def blobs_for(d: dict) -> dict:
    return {PHOTO: "/_blob/aaaa1111", "wordmark": "/_blob/bbbb2222"}


def test_build_needs_uploads_then_writes_canvas(run_script, tmp_path):
    d = spec(ALL_SLIDES)
    p = write_spec(tmp_path, d)
    root = tmp_path / "root"
    proc = run_script("design_render.py", "build", p, "--root", root, "--uploads-only", "--json")
    assert proc.returncode == 0, proc.stderr
    ups = {u["key"]: Path(u["file"]) for u in json.loads(proc.stdout)["uploads"]}
    assert set(ups) == {PHOTO, "wordmark"} and all(f.is_file() and f.parent == root / "uploads" for f in ups.values())
    proc = run_script("design_render.py", "build", p, "--root", root)
    assert proc.returncode == 1 and "not uploaded yet" in proc.stderr
    d["canvas"] = {"url": "https://claude.ai/artifact/AbC123", "blobs": blobs_for(d)}
    p = write_spec(tmp_path, d)
    proc = run_script("design_render.py", "build", p, "--root", root, "--created-at", "2026-11-13T00:00:00Z", "--json")
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout)
    assert res["boards"][0] == "project/Main.dc.html" and len(res["boards"]) == 9
    assert res["files"] == {b: b for b in res["boards"]}
    index = json.loads((root / "project" / "canvas.json").read_text())
    assert index["v"] == 3 and index["createdOnFiles"] == {"v": 1, "at": "2026-11-13T00:00:00Z"}
    assert index["title"] == d["title"] and index["order"] == [b.split("/", 1)[1] for b in res["boards"]]
    xs = [index["boards"][b]["x"] for b in index["order"]]
    assert xs == [i * 1160 for i in range(9)]
    assert all((v["w"], v["h"]) == (1080, 1350) for v in index["boards"].values())
    assert d["caption"] in index["notes"]["brief"]["text"] and index["designSystems"] == []
    for b in res["boards"]:
        text = (root / b).read_text()
        assert "{{" not in text and "<!--" not in text, b
    photo = (root / "project" / "Slide08.dc.html").read_text()
    assert 'src="/_blob/aaaa1111"' in photo and "object-position: 50% 38%" in photo
    assert 'src="/_blob/bbbb2222"' in (root / "project" / "Slide09.dc.html").read_text()
    assert "$49" in (root / "project" / "Slide07.dc.html").read_text()  # the price comes from brand.json


def test_build_design_system_record(run_script, tmp_path):
    d = spec(ALL_SLIDES[:2], canvas={"url": "https://claude.ai/artifact/AbC123", "blobs": {}})
    p = write_spec(tmp_path, d)
    ds = "https://claude.ai/artifact/DesignSys1"
    proc = run_script("design_render.py", "build", p, "--root", tmp_path / "r", "--design-system", ds, "--json")
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout)
    assert res["files"]["project/ds/numa/tokens.json"] == {"artifact": ds, "path": "project/tokens.json"}
    rec = json.loads((tmp_path / "r" / "project" / "canvas.json").read_text())["designSystems"]
    assert rec[0]["namespace"] == "numa" and rec[0]["artifact"] == ds
    proc = run_script("design_render.py", "build", p, "--root", tmp_path / "r", "--design-system", "https://evil.example/x")
    assert proc.returncode == 1 and "design system" in proc.stderr


# --------------------------------------------------------------------------- spec render
@needs_chromium
def test_spec_renders_every_component(run_script, tmp_path):
    from PIL import Image
    p = write_spec(tmp_path, spec(ALL_SLIDES))
    out = tmp_path / "out"
    (out).mkdir()
    (out / "test-carousel_carousel_12.jpg").write_bytes(b"old")  # a stale slide of the same slug is removed
    proc = run_script("design_render.py", "spec", p, "--out", out, "--json", timeout=180)
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout)
    assert res["ok"] and res["mode"] == "spec" and len(res["files"]) == 9
    assert [Path(f).name for f in res["files"]] == [f"test-carousel_carousel_{n:02d}.jpg" for n in range(1, 10)]
    assert not (out / "test-carousel_carousel_12.jpg").exists()
    for f, s in zip(res["files"], res["slides"]):
        with Image.open(f) as im:
            assert im.size == (1080, 1350) and im.mode == "RGB"
            assert dr.jpeg_quality(im) >= 90 and dr.is_srgb(im.info["icc_profile"])
        assert set(s["fonts"]) <= {"Fraunces normal", "Fraunces italic", "Inter normal"}, s
    assert {"Fraunces normal", "Fraunces italic", "Inter normal"} <= {f for s in res["slides"] for f in s["fonts"]}
    assert "$49" in res["slides"][6]["text"] and "Discover NUMA" in res["slides"][6]["text"].replace("DISCOVER", "Discover")
    assert Path(res["sheet"]).is_file()
    report = json.loads((out / "report.json").read_text())
    assert report["design_render"]["ok"] is True


@needs_chromium
def test_spec_render_is_deterministic(run_script, tmp_path):
    p = write_spec(tmp_path, spec())
    a, b = tmp_path / "a", tmp_path / "b"
    for o in (a, b):
        assert run_script("design_render.py", "spec", p, "--out", o).returncode == 0
    for f in sorted(a.glob("*_carousel_*.jpg")):
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name


@needs_chromium
def test_overflow_is_an_error(run_script, tmp_path):
    d = spec()
    d["slides"][0]["fields"]["title"] = "A very long title that keeps going " * 6
    d["slides"][1]["fields"]["kicker"] = "A kicker far too long for one line here"
    proc = run_script("design_render.py", "spec", write_spec(tmp_path, d), "--out", tmp_path / "out", "--json")
    assert proc.returncode == 1
    errs = json.loads(proc.stdout)["errors"]
    assert any("slide 1" in e and "does not fit its box (title" in e for e in errs), errs
    assert any("slide 2" in e and "does not fit its box (kicker" in e for e in errs), errs
    assert (tmp_path / "out" / "test-carousel_carousel_01.jpg").is_file()  # still written to LOOK at


@needs_chromium
def test_missing_fonts_are_an_error(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "fonts"
    fake.mkdir()
    monkeypatch.setattr(dr.nc, "FONTS_DIR", fake)  # the bundled font files are no longer served
    rc = dr.render_spec(write_spec(tmp_path, spec()), tmp_path / "out", "jpg", as_json=True)
    assert rc == 1
    errs = json.loads(capsys.readouterr().out)["errors"]
    assert any("font Fraunces (normal) is not loaded" in e for e in errs), errs
    assert any("font Inter (normal) is not loaded" in e for e in errs), errs


# --------------------------------------------------------------------------- canvas render
def make_canvas(tmp_path: Path, run_script, slides=None, runtime: Path | None = None) -> Path:
    """A canvas folder as the Artifact read leaves it: project/ files, artifact-type/dc-runtime.js, <id>.<ext> assets."""
    d = spec(slides or [ALL_SLIDES[0], ALL_SLIDES[7], ALL_SLIDES[8]],
             canvas={"url": "https://claude.ai/artifact/AbC123", "blobs": blobs_for({})})
    p = write_spec(tmp_path, d)
    root = tmp_path / "root"
    proc = run_script("design_render.py", "build", p, "--root", root)
    assert proc.returncode == 0, proc.stderr
    canvas = tmp_path / "canvas"
    shutil.copytree(root / "project", canvas / "project")
    (canvas / "artifact-type").mkdir()
    if runtime:
        shutil.copyfile(runtime, canvas / "artifact-type" / "dc-runtime.js")
    else:  # stand-in: no runtime at all, the artboard markup renders as plain HTML
        (canvas / "artifact-type" / "dc-runtime.js").write_text("/* no-op stand-in for tests */\n")
    shutil.copyfile(dr.nc.PLUGIN_ROOT / PHOTO, canvas / "aaaa1111.jpg")
    shutil.copyfile(dr.nc.brand_asset("wordmark"), canvas / "bbbb2222.png")
    return canvas


def test_list_blobs(run_script, tmp_path):
    canvas = make_canvas(tmp_path, run_script)
    (canvas / "bbbb2222.png").unlink()
    proc = run_script("design_render.py", "canvas", canvas, "--list-blobs", "--json")
    assert proc.returncode == 0
    rows = {r["id"]: r["file"] for r in json.loads(proc.stdout)["blobs"]}
    assert rows["aaaa1111"].endswith("aaaa1111.jpg") and rows["bbbb2222"] is None


def test_canvas_missing_blob_or_runtime_is_an_error(run_script, tmp_path):
    canvas = make_canvas(tmp_path, run_script)
    (canvas / "aaaa1111.jpg").unlink()
    proc = run_script("design_render.py", "canvas", canvas, "--out", tmp_path / "out")
    assert proc.returncode == 1 and "aaaa1111" in proc.stderr and "Artifact" in proc.stderr
    shutil.copyfile(dr.nc.PLUGIN_ROOT / PHOTO, canvas / "aaaa1111.jpg")
    shutil.rmtree(canvas / "artifact-type")
    proc = run_script("design_render.py", "canvas", canvas, "--out", tmp_path / "out")
    assert proc.returncode == 1 and "dc-runtime.js" in proc.stderr


@needs_chromium
def test_canvas_renders_in_reading_order(run_script, tmp_path):
    canvas = make_canvas(tmp_path, run_script)
    index = json.loads((canvas / "project" / "canvas.json").read_text())
    index["order"].reverse()  # z-order only; slides follow the layout
    (canvas / "project" / "canvas.json").write_text(json.dumps(index))
    out = tmp_path / "out"
    proc = run_script("design_render.py", "canvas", canvas, "--out", out, "--slug", "test-carousel", "--json")
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout)
    assert [s["board"] for s in res["slides"]] == ["Main.dc.html", "Slide02.dc.html", "Slide03.dc.html"]
    assert res["mode"] == "canvas" and res["ok"]
    assert "Red light" in res["slides"][1]["text"]


@needs_chromium
def test_canvas_checks_edits(run_script, tmp_path):
    canvas = make_canvas(tmp_path, run_script)
    main = canvas / "project" / "Main.dc.html"
    main.write_text(main.read_text().replace("Two warm rooms", "Detox in two warm rooms"))
    s2 = canvas / "project" / "Slide02.dc.html"
    s2.write_text(s2.read_text().replace("family=Inter", "family=Lobster").replace(
        "font-family: Fraunces, Georgia, serif; font-size: 56px", "font-family: Lobster, serif; font-size: 56px"))
    index = json.loads((canvas / "project" / "canvas.json").read_text())
    index["boards"]["Slide03.dc.html"]["w"] = 1080 * 2
    (canvas / "project" / "canvas.json").write_text(json.dumps(index))
    proc = run_script("design_render.py", "canvas", canvas, "--out", tmp_path / "out", "--json")
    assert proc.returncode == 1
    errs = json.loads(proc.stdout)["errors"]
    assert any("slide 1" in e and "banned claim" in e for e in errs), errs
    assert any("'Lobster' is linked but not bundled" in e for e in errs), errs
    assert any("slide 2" in e and "font Lobster" in e for e in errs), errs
    assert any("Slide03.dc.html is 2160x1350" in e for e in errs), errs


@needs_chromium
def test_blank_slide_is_an_error(run_script, tmp_path):
    canvas = make_canvas(tmp_path, run_script, slides=[ALL_SLIDES[0], ALL_SLIDES[8]])
    main = canvas / "project" / "Main.dc.html"
    text = main.read_text()
    for color in ("#133037", "#5E8C8F", "#C8643C", "#F7D6A0"):
        text = text.replace(color, "#FAF6EE")
    main.write_text(text)
    proc = run_script("design_render.py", "canvas", canvas, "--out", tmp_path / "out", "--json")
    assert proc.returncode == 1
    assert any("slide 1: the slide is blank" in e for e in json.loads(proc.stdout)["errors"])


@needs_chromium
@pytest.mark.skipif(not os.environ.get("NUMA_DC_RUNTIME"), reason="set NUMA_DC_RUNTIME to the Design type's dc-runtime.js")
def test_real_design_runtime_matches_spec_render(run_script, tmp_path):
    """R331: the canvas (real Claude Design runtime) and the fallback give the same pixels."""
    runtime = Path(os.environ["NUMA_DC_RUNTIME"])
    slides = [ALL_SLIDES[0], ALL_SLIDES[3], ALL_SLIDES[7], ALL_SLIDES[8]]
    canvas = make_canvas(tmp_path, run_script, slides=slides, runtime=runtime)
    a = run_script("design_render.py", "canvas", canvas, "--out", tmp_path / "c", "--slug", "t", "--json")
    assert a.returncode == 0, a.stderr
    b = run_script("design_render.py", "spec", write_spec(tmp_path, spec(slides, slug="t"), "s.json"),
                   "--out", tmp_path / "s", "--json")
    assert b.returncode == 0, b.stderr
    for fa, fb in zip(json.loads(a.stdout)["files"], json.loads(b.stdout)["files"]):
        assert Path(fa).read_bytes() == Path(fb).read_bytes(), Path(fa).name


def test_no_browser_gives_install_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "none"))
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("Python Playwright not installed")
    with pytest.raises(dr.nc.UserError, match="python -m playwright install chromium"):
        dr.Browser()
