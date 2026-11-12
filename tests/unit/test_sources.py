"""sources.py: sources.json / sources.txt and the license check (R77, R122, R141)."""
from __future__ import annotations

import json

import pytest

import baseline_plan
import numa_common
import sources as src


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(src.main, argv)
    return e.value.code


@pytest.mark.parametrize("text,lid,ok", [
    ("pexels", "pexels", True),
    ("Pexels License", "pexels", True),
    ("Unsplash license", "unsplash", True),
    ("Pixabay Content License", "pixabay", True),
    ("NUMA-owned", "numa_owned", True),
    ("Shot by Katie", "numa_owned", True),
    ("Higgsfield Plus paid plan", "higgsfield_paid", True),
    ("Meta Sound Collection", "meta_sound_collection", True),
    ("CC BY-NC 4.0", "non_commercial", False),
    ("Pixabay, non-commercial only", "non_commercial", False),
    ("Personal use only", "personal_use", False),
    ("trending sound", "trending_audio", False),
    ("unknown", "unknown", False),
    ("some blog", None, False),
    ("no permission", "no_permission", False),
    ("permission pending", "no_permission", False),
    ("Asked for permission, waiting", None, False),
    ("Written permission from Mission Fitness", "partner_permission", True),
    ("Higgsfield free plan", "higgsfield_free", False),
    ("Higgsfield trial", "higgsfield_free", False),
    ("Higgsfield", "higgsfield_unstated", False),
    ("Higgsfield ElevenLabs Music v2.5 (Plus plan)", "higgsfield_paid", True),
])
def test_license_classes(nc, text, lid, ok):
    assert src.classify(text) == lid
    assert src.license_ok(text)[0] is ok


def test_add_show_and_baseline_reads_license(nc, job, make_audio, capsys):
    music = make_audio(job.raw / "music.mp3", 2.0, kind="music")
    assert run(["add", str(job.job), "--kind", "music", "--path", str(music), "--source", "Higgsfield ElevenLabs Music v2.5",
                "--license", "higgsfield_paid", "--date", "2026-12-01"]) == 0
    entries = json.loads((job.work / "sources.json").read_text())
    assert entries[0]["license"] == "Higgsfield paid plan (commercial use included)"
    assert entries[0]["license_url"] == "higgsfield.ai/terms" and entries[0]["added"] == "2026-12-01"
    assert set(entries[0]) >= {"kind", "path", "source", "license", "url", "added"}
    txt = (job.out / "sources.txt").read_text().splitlines()
    assert txt[1] == ("music.mp3 | music | from Higgsfield ElevenLabs Music v2.5 | license: Higgsfield paid plan "
                      "(commercial use included) higgsfield.ai/terms | 2026-12-01")
    # baseline_plan picks the music license from sources.json
    assert baseline_plan.recorded_license(job.work, str(music)) == entries[0]["license"]
    # re-adding replaces the line
    assert run(["add", str(job.job), "--kind", "music", "--path", str(music), "--source", "Katie",
                "--license", "NUMA-owned", "--date", "2026-12-02"]) == 0
    assert len(json.loads((job.work / "sources.json").read_text())) == 1
    capsys.readouterr()
    assert run(["show", str(job.job), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["source"] == "Katie"


def test_check(nc, job, make_audio, make_image, plan_factory, tmp_path, capsys):
    music = make_audio(job.raw / "music.mp3", 2.0, kind="music")
    make_audio(job.raw / "voiceover.m4a", 2.0, kind="voice")  # Katie's voice memo needs no line
    stock = make_image(job.raw / "downloads" / "sauna.jpg")
    outside = make_image(tmp_path / "elsewhere" / "pexels-123.jpg")
    plan = plan_factory()
    plan["music"] = {"source": "higgsfield", "path": str(music), "license": "Higgsfield paid plan", "title": None}
    plan["shots"][1]["src"] = str(outside)
    plan_path = job.work / "plan.json"
    plan_path.write_text(json.dumps(plan))
    assert run(["check", str(job.job)]) == 1
    err = capsys.readouterr().err
    assert "music.mp3: no sources line" in err and "sauna.jpg: no sources line" in err
    assert "pexels-123.jpg: no sources line" in err and "voiceover" not in err

    run(["add", str(job.job), "--kind", "music", "--path", str(music), "--source", "Higgsfield", "--license", "higgsfield_paid"])
    run(["add", str(job.job), "--kind", "stock", "--path", str(stock), "--source", "Pexels", "--license", "pexels",
         "--url", "https://www.pexels.com/photo/1/"])
    run(["add", str(job.job), "--kind", "stock", "--path", str(outside), "--source", "Some blog", "--license", "CC BY-NC"])
    capsys.readouterr()
    assert run(["check", str(job.job), "--plan", str(plan_path)]) == 1
    assert "not allowed" in capsys.readouterr().err
    run(["add", str(job.job), "--kind", "stock", "--path", str(outside), "--source", "Unsplash", "--license", "unsplash"])
    assert run(["check", str(job.job)]) == 0

    plan["music"] = {"source": "sound_collection", "path": None, "license": "Pexels", "title": "x"}
    plan_path.write_text(json.dumps(plan))
    capsys.readouterr()
    assert run(["check", str(job.job)]) == 1
    assert "Meta Sound Collection" in capsys.readouterr().err
    plan["music"] = {"source": "library", "path": str(music), "license": None, "title": "x"}
    plan_path.write_text(json.dumps(plan))
    assert run(["check", str(job.job)]) == 1
    plan["music"] = {"source": "pad", "path": None, "license": None, "title": "pad"}
    plan_path.write_text(json.dumps(plan))
    assert run(["check", str(job.job)]) == 0


def test_errors(nc, job, tmp_path):
    assert run(["add", str(tmp_path / "nojob"), "--kind", "music", "--path", "x", "--source", "s", "--license", "l"]) == 1
    assert run(["add", str(job.job), "--kind", "music", "--path", str(tmp_path / "missing.mp3"), "--source", "s",
                "--license", "pexels"]) == 1
    assert run(["add", str(job.job), "--kind", "gif", "--path", "x", "--source", "s", "--license", "l"]) == 2
    assert run(["check", str(job.job), "--plan", str(tmp_path / "none.json")]) == 1
    assert run([]) == 2
