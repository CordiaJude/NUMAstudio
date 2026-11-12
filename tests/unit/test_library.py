"""library.py: media library index, probing and tag queries (R285, R286)."""
from __future__ import annotations

import json

import pytest

import library as lib
import numa_common


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(lib.main, argv)
    return e.value.code


@pytest.fixture
def media(tmp_path, make_image, make_video):
    from PIL import Image, ImageFilter
    d = tmp_path / "drive"
    sharp = make_image(d / "plunge_sharp.jpg", size=(720, 1280))
    blurry = d / "plunge_blurry.jpg"
    with Image.open(sharp) as im:
        im.filter(ImageFilter.GaussianBlur(8)).save(blurry, quality=90)
    wide = make_image(d / "outside.jpg", size=(1280, 720))
    clip = make_video(d / "clips" / "sauna.mp4", 2.0, size=(360, 640), fps=30, audio=False)
    return {"dir": d, "sharp": sharp, "blurry": blurry, "wide": wide, "clip": clip}


def test_add_probe_and_query(nc, tmp_path, media, capsys):
    idx = tmp_path / "library.json"
    assert run(["add", "--index", str(idx), str(media["sharp"]), str(media["blurry"]),
                "--tags", "Cold Plunge, morning, smiling, group", "--people", "yes"]) == 0
    assert run(["add", "--index", str(idx), str(media["wide"]), "--tags", "outside,sign", "--no-faces"]) == 0
    assert run(["add", "--index", str(idx), str(media["clip"]), "--tags", "sauna, morning",
                "--link", "https://drive.google.com/file/d/abc", "--people", "no"]) == 0
    data = json.loads(idx.read_text())
    items = {it["name"]: it for it in data["items"]}
    assert items["plunge_sharp.jpg"]["orientation"] == "vertical" and items["outside.jpg"]["orientation"] == "horizontal"
    assert items["sauna.mp4"]["kind"] == "clip" and items["sauna.mp4"]["duration"] == pytest.approx(2.0, abs=0.1)
    assert items["sauna.mp4"]["link"].startswith("https://drive") and items["sauna.mp4"]["consent"] == "n/a"
    assert items["plunge_sharp.jpg"]["tags"] == ["cold plunge", "morning", "smiling", "group"]
    assert items["plunge_sharp.jpg"]["consent"] == "unknown"
    assert items["plunge_sharp.jpg"]["sharpness"] > items["plunge_blurry.jpg"]["sharpness"]

    res = lib.query(data, lib.split_tags("cold plunge, morning, smiling, group"))
    assert [r["name"] for r in res] == ["plunge_sharp.jpg", "plunge_blurry.jpg"]  # ranked by sharpness
    assert [r["name"] for r in lib.query(data, ["plunge"])][:1] == ["plunge_sharp.jpg"]  # word match
    assert [r["name"] for r in lib.query(data, ["morning"], kind="clip", min_duration=1.5)] == ["sauna.mp4"]
    assert lib.query(data, ["morning"], min_duration=5) == []
    assert [r["name"] for r in lib.query(data, [], orient="horizontal")] == ["outside.jpg"]
    assert all(not r["people"] or r["consent"] == "yes" for r in lib.query(data, [], usable=True))
    assert len(lib.query(data, ["morning"], usable=True)) == 1

    # tag: consent granted makes the people shots usable; ids are stable
    sid = items["plunge_sharp.jpg"]["id"]
    assert run(["tag", "--index", str(idx), sid, "--consent", "yes", "--add", "front of house", "--remove", "group"]) == 0
    capsys.readouterr()
    assert run(["query", "--index", str(idx), "--tags", "cold plunge", "--usable", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [o["id"] for o in out] == [sid] and "group" not in out[0]["tags"]

    # re-adding refreshes the probe and keeps tags
    assert run(["add", "--index", str(idx), str(media["sharp"])]) == 0
    again = {it["name"]: it for it in json.loads(idx.read_text())["items"]}
    assert again["plunge_sharp.jpg"]["tags"] == ["cold plunge", "morning", "smiling", "front of house"]
    assert again["plunge_sharp.jpg"]["consent"] == "yes" and len(again) == 4


def test_folder_add_and_errors(nc, tmp_path, media):
    idx = tmp_path / "lib.json"
    assert run(["add", "--index", str(idx), str(media["dir"]), "--no-faces"]) == 0
    assert len(json.loads(idx.read_text())["items"]) == 4
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    assert run(["add", "--index", str(idx), str(txt)]) == 1
    assert run(["add", "--index", str(idx), str(tmp_path / "missing.jpg")]) == 1
    assert run(["add", "--index", str(idx), str(media["dir"]), "--link", "x"]) == 2
    assert run(["tag", "--index", str(idx), "M0000000000", "--add", "x"]) == 1
    assert run(["query", "--index", str(tmp_path / "none.json")]) == 1
    assert run([]) == 2
