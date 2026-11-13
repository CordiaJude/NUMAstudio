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
                "--link", "https://drive.google.com/file/d/abc"]) == 0
    assert run(["add", "--index", str(idx), str(media["clip"]), "--people", "no"]) == 2  # only `tag` can say no
    data = json.loads(idx.read_text())
    items = {it["name"]: it for it in data["items"]}
    assert items["plunge_sharp.jpg"]["orientation"] == "vertical" and items["outside.jpg"]["orientation"] == "horizontal"
    assert items["sauna.mp4"]["kind"] == "clip" and items["sauna.mp4"]["duration"] == pytest.approx(2.0, abs=0.1)
    assert items["sauna.mp4"]["link"].startswith("https://drive") and items["sauna.mp4"]["consent"] == "unknown"
    assert items["sauna.mp4"]["people"] is None  # nothing found proves nothing
    assert items["plunge_sharp.jpg"]["tags"] == ["cold plunge", "morning", "smiling", "group"]
    assert items["plunge_sharp.jpg"]["consent"] == "unknown"
    assert items["plunge_sharp.jpg"]["sharpness"] > items["plunge_blurry.jpg"]["sharpness"]

    res = lib.query(data, lib.split_tags("cold plunge, morning, smiling, group"))
    assert [r["name"] for r in res] == ["plunge_sharp.jpg", "plunge_blurry.jpg"]  # ranked by sharpness
    assert [r["name"] for r in lib.query(data, ["plunge"])][:1] == ["plunge_sharp.jpg"]  # word match
    assert [r["name"] for r in lib.query(data, ["morning"], kind="clip", min_duration=1.5)] == ["sauna.mp4"]
    assert lib.query(data, ["morning"], min_duration=5) == []
    assert [r["name"] for r in lib.query(data, [], orient="horizontal")] == ["outside.jpg"]
    assert lib.query(data, [], usable=True) == []  # nothing is cleared yet
    assert run(["tag", "--index", str(idx), items["sauna.mp4"]["id"], "--people", "no"]) == 0
    data = json.loads(idx.read_text())
    assert [r["name"] for r in lib.query(data, ["morning"], usable=True)] == ["sauna.mp4"]
    assert data["items"][[i["name"] for i in data["items"]].index("sauna.mp4")]["consent"] == "n/a"

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
    assert run(["add", "--index", str(idx), str(media["clip"])]) == 0  # re-add keeps the tag decision
    clip = {it["name"]: it for it in json.loads(idx.read_text())["items"]}["sauna.mp4"]
    assert clip["people"] is False and clip["people_source"] == "tag"


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


def test_people_detection_on_bundled_photos(nc, tmp_path, assets_dir):
    """Consent gate: detectors only ever say yes; 'no people' needs an explicit tag after looking."""
    idx = tmp_path / "lib.json"
    photos = assets_dir / "brand-photos"
    names = ["sauna-people.jpg", "breathwork-class.jpg", "mats-bolsters.jpg"]
    assert run(["add", "--index", str(idx), *[str(photos / n) for n in names]]) == 0
    items = {it["name"]: it for it in json.loads(idx.read_text())["items"]}
    if not lib.face_detector().available:
        pytest.skip("no face detector in this OpenCV build")
    assert items["sauna-people.jpg"]["people"] is True and items["sauna-people.jpg"]["faces"] >= 3
    assert items["sauna-people.jpg"]["people_source"] == "detector"
    for n in ("breathwork-class.jpg", "mats-bolsters.jpg"):  # people lying down / empty room: both unknown
        assert items[n]["people"] in (None, True) and items[n]["consent"] == "unknown"
    data = json.loads(idx.read_text())
    assert lib.query(data, [], usable=True) == []
    assert lib.query(data, [], people=False) == []
    # the Director looks: the mats photo has nobody in it, the breathwork class has people
    assert run(["tag", "--index", str(idx), items["mats-bolsters.jpg"]["id"], "--people", "no"]) == 0
    assert run(["tag", "--index", str(idx), items["breathwork-class.jpg"]["id"], "--people", "yes"]) == 0
    data = json.loads(idx.read_text())
    assert [r["name"] for r in lib.query(data, [], usable=True)] == ["mats-bolsters.jpg"]
    assert [r["name"] for r in lib.query(data, [], people=False, usable=True)] == ["mats-bolsters.jpg"]
    # consent for the sauna group makes it usable too
    assert run(["tag", "--index", str(idx), items["sauna-people.jpg"]["id"], "--consent", "yes"]) == 0
    data = json.loads(idx.read_text())
    assert sorted(r["name"] for r in lib.query(data, [], usable=True)) == ["mats-bolsters.jpg", "sauna-people.jpg"]


def test_no_detector_means_unknown(nc, tmp_path, assets_dir, monkeypatch):
    class NoDetector:
        available = False
        reason = "test"
    monkeypatch.setattr(lib, "_DETECTOR", [NoDetector()])
    idx = tmp_path / "lib.json"
    assert run(["add", "--index", str(idx), str(assets_dir / "brand-photos" / "mats-bolsters.jpg")]) == 0
    data = json.loads(idx.read_text())
    assert data["items"][0]["people"] is None and data["items"][0]["consent"] == "unknown"
    assert lib.query(data, [], usable=True) == [] and lib.query(data, [], people=False) == []


def test_unreadable_file_skipped(nc, tmp_path, media, capsys):
    bad = media["dir"] / "broken.jpg"
    bad.write_bytes(b"not a jpeg")
    idx = tmp_path / "lib.json"
    assert run(["add", "--index", str(idx), str(bad), str(media["sharp"]), "--no-faces"]) == 0
    assert "WARN: skipped" in capsys.readouterr().err
    assert [it["name"] for it in json.loads(idx.read_text())["items"]] == ["plunge_sharp.jpg"]
