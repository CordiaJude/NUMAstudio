"""Unit tests for scripts/analyze.py (R15-R17, R19-R27, R29).

Fixtures are synthetic (lavfi audio, bundled brand photos, tiny generated clips,
a HEIC written with pillow-heif). Tests that need the speech model are skipped
when faster-whisper or the cached small.en model is missing (no downloads in tests).
"""
from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import analyze as an


def _model_cached() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    roots = [Path(os.environ.get("HF_HUB_CACHE", "")),
             Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"]
    return any((r / "models--Systran--faster-whisper-small.en").is_dir() for r in roots if str(r))


needs_whisper = pytest.mark.skipif(not _model_cached(), reason="faster-whisper small.en model not cached")


def run_analyze(raw, work, **kw):
    kw.setdefault("transcribe_audio", False)
    return an.analyze(Path(raw), Path(work), **kw)


def read_pcm(path):
    with wave.open(str(path)) as wf:
        rate, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
        data = np.frombuffer(wf.readframes(n), dtype="<i2").reshape(-1, ch)
    return rate, ch, data[:, 0].astype(np.float64) / 32768.0


def band_level(y, sr, t0, t1, freq):
    seg = y[int(t0 * sr):int(t1 * sr)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(seg.size)))
    f = np.fft.rfftfreq(seg.size, 1 / sr)
    return float(spec[(f > freq - 20) & (f < freq + 20)].max())


def sine(make_audio_path, nc, seconds, freq):
    nc.ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}", "-ac", "2",
              str(make_audio_path))
    return make_audio_path


# --------------------------------------------------------------------------- ingest (R15, R16)
def test_classification_mixed_case_recursive_and_hidden(nc, tmp_path, make_image, make_audio, make_video):
    raw = tmp_path / "raw"
    make_image(raw / "photos" / "A.JPG")
    make_image(raw / "photos" / "b.Png")
    make_image(raw / "photos" / "img10.jpeg")
    make_image(raw / "photos" / "img2.jpeg")
    make_image(raw / ".hidden" / "x.jpg")
    make_image(raw / "photos" / "._A.JPG")
    make_video(raw / "clips" / "Clip.MOV", seconds=1.0)
    make_audio(raw / "Music.MP3", seconds=1.0)
    (raw / "SHOOT CARD.txt").write_text("card")
    (raw / "Thumbs.db").write_bytes(b"x")
    found = an.scan_raw(raw, an.Notes())
    names = lambda k: [p.name for p in found[k]]  # noqa: E731
    assert names("photos") == ["A.JPG", "b.Png", "img2.jpeg", "img10.jpeg"]
    assert names("clips") == ["Clip.MOV"] and names("audio") == ["Music.MP3"]
    assert names("other") == ["SHOOT CARD.txt"]


def test_heic_converted_to_upright_jpg(nc, tmp_path, make_image):
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()
    raw = tmp_path / "raw"
    src = make_image(tmp_path / "src.jpg", size=(320, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    raw.mkdir()
    with Image.open(src) as im:
        im.save(raw / "IMG_0001.HEIC", exif=exif.tobytes())
        im.save(raw / "sideways.jpg", exif=exif.tobytes())
    a = run_analyze(raw, tmp_path / "work", pad_seconds=0)
    p0, p1 = a["photos"]
    assert p0["path"].endswith(".jpg") and p0["orig_path"].endswith("IMG_0001.HEIC")
    assert Path(p0["path"]).parent == (tmp_path / "work" / "media").resolve()
    assert p0["size"] == [200, 320] and p1["size"] == [200, 320]
    with Image.open(p1["path"]) as im:
        assert im.size == (200, 320)
    assert (raw / "IMG_0001.HEIC").is_file()  # raw untouched
    assert nc.schema_errors("analysis", a) == []


# --------------------------------------------------------------------------- audio roles (R17)
@pytest.mark.parametrize("name,role", [
    ("voiceover_and_music.mp3", "master"),
    ("VO.m4a", "voice"),
    ("vo_take2.wav", "voice"),
    ("Voice Memo 3.m4a", "voice"),
    ("VoiceMemo.m4a", "voice"),
    ("narration.mp3", "voice"),
    ("New Recording 12.m4a", "voice"),
    ("music.mp3", "music"),
    ("Song - calm.mp3", "music"),
    ("track01.wav", "music"),
    ("BGM.aac", "music"),
    ("final_mix.wav", "master"),
    ("voice_track.wav", "voice"),
    ("VO Track 2.m4a", "voice"),
    ("voiceover_tracks.wav", "voice"),
    ("voice_track_mix.wav", "master"),
    ("voice_track_music.wav", "master"),
    ("audio.mp3", None),
    ("volume.mp3", None),
])
def test_guess_role_from_name(name, role):
    assert an.guess_role(Path("/raw") / name)[0] == role


def test_guess_role_from_folder():
    assert an.guess_role(Path("/raw/voiceover/take 1.m4a"), Path("/raw"))[0] == "voice"
    assert an.guess_role(Path("/raw/Music/x.mp3"), Path("/raw"))[0] == "music"


def test_assign_roles_ambiguous_cases():
    raw = Path("/raw")
    P = lambda n: raw / n  # noqa: E731
    r = an.assign_roles([P("a.mp3")], raw)
    assert r["master"] == P("a.mp3") and r["voice"] is None
    r = an.assign_roles([P("music.mp3"), P("take.m4a")], raw)
    assert r["voice"] == P("take.m4a") and r["music"] == P("music.mp3")
    r = an.assign_roles([P("vo.m4a"), P("bed.mp3")], raw)
    assert r["voice"] == P("vo.m4a") and r["music"] == P("bed.mp3")
    r = an.assign_roles([P("vo1.m4a"), P("vo2.m4a"), P("music.mp3")], raw)
    assert r["voice"] == P("vo1.m4a")
    assert {"path": str(P("vo2.m4a")), "role": "ignored"}.items() <= next(
        x for x in r["roles"] if x["path"].endswith("vo2.m4a")).items()
    r = an.assign_roles([P("voiceover_and_music.mp3"), P("music.mp3")], raw)
    assert r["master"] == P("voiceover_and_music.mp3") and r["music"] is None
    r = an.assign_roles([P("vo.m4a"), P("music.mp3")], raw, master=P("vo.m4a"))
    assert r["master"] == P("vo.m4a") and r["voice"] is None
    r = an.assign_roles([P("x.mp3"), P("y.mp3")], raw, voice=P("y.mp3"), music=P("x.mp3"))
    assert (r["voice"], r["music"]) == (P("y.mp3"), P("x.mp3"))


# --------------------------------------------------------------------------- audio mix (R19, R20)
def test_voice_and_music_ducked_mix(nc, tmp_path, make_image, make_audio):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    # voice: 4 s of a 200 Hz tone bursting on and off; music: a steady 1 kHz tone
    nc.ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*200*t)*gt(sin(2*PI*2*t),-0.5)':s=48000:d=4",
              "-ac", "2", str(raw / "voiceover.wav"))
    sine(raw / "music.wav", nc, 6, 1000)  # shorter than voice + outro: must loop
    a = run_analyze(raw, tmp_path / "work")
    master = Path(a["audio"]["master"])
    assert a["audio"]["voice"].endswith("voiceover.wav") and a["audio"]["music"].endswith("music.wav")
    assert abs(nc.media_duration(master) - (4 + 7.5)) <= 0.01
    assert a["duration"] == 11.5
    rate, ch, y = read_pcm(master)
    assert rate == 48000 and ch == 2
    during = band_level(y, rate, 1.0, 3.0, 1000)
    outro = band_level(y, rate, 6.0, 9.0, 1000)
    assert during < outro / 2  # music ducked by more than 6 dB under the voice
    assert band_level(y, rate, 7.0, 9.0, 1000) > 0  # music present in the outro (looped)
    assert a["voice_present"] is True
    assert nc.schema_errors("analysis", a) == []


def test_mix_length_capped_at_60s(nc, tmp_path):
    voice = tmp_path / "vo.wav"
    music = tmp_path / "music.wav"
    nc.ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*200*t)':s=48000:d=57", "-ac", "1", str(voice))
    sine(music, nc, 10, 800)
    total = an.mix_voice_music(voice, music, tmp_path / "master.wav", an.Notes())
    assert total == 60.0
    assert abs(nc.media_duration(tmp_path / "master.wav") - 60.0) <= 0.01


def test_combined_track_normalized(nc, tmp_path, make_image, make_audio):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    nc.ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=8", "-af", "volume=-24dB",
              "-ac", "1", str(raw / "voiceover_and_music.mp3"))
    a = run_analyze(raw, tmp_path / "work")
    assert a["audio"]["combined"] is True and a["audio"]["source"] == "combined"
    info = nc.media_info(a["audio"]["master"])
    assert info["sample_rate"] == 48000 and info["channels"] == 2
    lufs = an.measure_loudness(a["audio"]["master"])["input_i"]
    assert abs(lufs - (-15.0)) <= 1.0


# --------------------------------------------------------------------------- music only, beats (R23, R25)
def test_music_only_no_words_and_100_bpm(nc, tmp_path, make_image, make_audio):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    make_audio(raw / "music.mp3", seconds=12.0, kind="music")
    a = run_analyze(raw, tmp_path / "work", transcribe_audio=True)
    assert a["words"] == [] and a["transcript"] == "" and a["voice_present"] is False
    assert a["bpm"] is not None and abs(a["bpm"] - 100) <= 3
    assert len(a["beats"]) >= 10 and a["beats"] == sorted(a["beats"])
    b = run_analyze(raw, tmp_path / "work2", transcribe_audio=True)
    assert (b["bpm"], b["beats"]) == (a["bpm"], a["beats"])  # deterministic


@needs_whisper
def test_whisper_no_hallucination_on_music_track(nc, tmp_path, make_image, make_audio):
    """A track whose name gives no role is transcribed as a combined track; pure
    music/tone must give zero words (v1 produced fake words here)."""
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    make_audio(raw / "audio.wav", seconds=10.0, kind="music")
    a = run_analyze(raw, tmp_path / "work", transcribe_audio=True)
    assert a["audio"]["combined"] is True
    assert a["words"] == [] and a["voice_present"] is False
    assert any("no speech" in w for w in a["warnings"])


def test_transcription_import_failure_degrades(nc, tmp_path, make_image, make_audio, monkeypatch, capsys):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    make_audio(raw / "voiceover.wav", seconds=3.0, kind="voice")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import raises ImportError
    rc = an.main([str(raw), str(tmp_path / "work"), "--json"])
    assert rc == 0
    out = capsys.readouterr()
    rep = json.loads(out.out)
    assert rep["words"] == 0 and rep["voice_present"] is True
    assert "WARN: transcription unavailable" in out.err
    doc = json.loads((tmp_path / "work" / "analysis.json").read_text())
    assert doc["words"] == [] and any("transcription unavailable" in w for w in doc["warnings"])


def test_filter_segments_appear_time_and_non_speech():
    def seg(words, nsp=0.01, lp=-0.2, cr=1.4):
        return SimpleNamespace(no_speech_prob=nsp, avg_logprob=lp, compression_ratio=cr,
                               words=[SimpleNamespace(word=w, start=s, end=e, probability=p) for w, s, e, p in words])
    segs = [
        seg([(" Hello", 0.0, 1.0, 0.9), (" there.", 1.0, 1.2, 0.95), (" ♪", 1.2, 1.5, 0.9), (" uh", 1.5, 1.6, 0.05)]),
        seg([(" Thank", 3.0, 3.3, 0.6), (" you.", 3.3, 3.6, 0.6)], nsp=0.9, lp=-1.2),   # judged non-speech
        seg([(" la", 4.0, 4.2, 0.7)], cr=3.0),                                          # repetitive
    ]
    words = an.filter_segments(segs)
    assert [w["w"] for w in words] == ["Hello", "there."]
    assert words[0] == {"w": "Hello", "appear": 0.6, "end": 1.0, "start": 0.0, "p": 0.9}
    assert words[1]["appear"] == 1.0  # max(start 1.0, end 1.2 - 0.4)
    low = [seg([(" a", 0.0, 0.2, 0.2), (" b", 0.2, 0.4, 0.2)])]
    assert an.filter_segments(low) == []  # unlikely on average: not speech


# --------------------------------------------------------------------------- no audio, clips only
def test_no_audio_generates_pad(nc, tmp_path, make_image):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    a = run_analyze(raw, tmp_path / "work", pad_seconds=12)
    assert a["audio"]["generated_pad"] is True and a["voice_present"] is False
    assert Path(a["audio"]["music"]) == (tmp_path / "work" / "pad.wav").resolve()
    assert abs(a["duration"] - 12.0) <= 0.1 and a["bpm"] is not None and abs(a["bpm"] - an.PAD_BPM) <= 3
    assert any("offline" in w for w in a["warnings"])
    assert nc.schema_errors("analysis", a) == []


def test_no_audio_without_pad(nc, tmp_path, make_image):
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    work = tmp_path / "work"
    a = run_analyze(raw, work, pad_seconds=0)
    assert a["audio"]["master"] is None and a["duration"] == 0 and a["bpm"] is None and a["beats"] == []
    assert a["voice_present"] is False and not (work / "master.wav").exists()
    assert nc.schema_errors("analysis", a) == []


def test_clips_only_uses_clip_sound_and_clip_info(nc, tmp_path, make_video):
    raw = tmp_path / "raw"
    make_video(raw / "clips" / "a.mp4", seconds=3.0, size=(270, 480), fps=30, audio=True)
    make_video(raw / "clips" / "b.mov", seconds=2.0, size=(320, 240), fps=25, audio=False, rotate=90)
    work = tmp_path / "work"
    a = run_analyze(raw, work)
    c0, c1 = a["clips"]
    assert c0["has_audio"] is True and c0["fps"] == 30 and c0["size"] == [270, 480] and abs(c0["duration"] - 3) < 0.1
    assert c1["has_audio"] is False and c1["fps"] == 25 and c1["size"] == [240, 320]
    for c in (c0, c1):
        assert c["sharpness"] >= 0 and 0 <= c["brightness"] <= 1 and c["shake"] >= 0
    assert a["audio"]["source"] == "clips" and a["audio"]["master"] and a["audio"]["combined"] is False
    assert [x["id"] for x in a["audio"]["clip_audio"]] == ["C0"]
    assert (work / "contact_clips.jpg").is_file() and not (work / "contact_photos.jpg").exists()
    assert a["contact_sheets"] == {"photos": None, "clips": str(work.resolve() / "contact_clips.jpg")}
    assert nc.schema_errors("analysis", a) == []


# --------------------------------------------------------------------------- contact sheets, metrics (R26, R29)
def test_contact_sheets_and_photo_metrics(nc, tmp_path, make_image, make_video):
    raw = tmp_path / "raw"
    make_image(raw / "p0.jpg", size=(300, 400))
    make_image(raw / "p1.jpg", size=(400, 300))
    make_video(raw / "c.mp4", seconds=4.0, audio=False)
    work = tmp_path / "work"
    a = run_analyze(raw, work, pad_seconds=0)
    assert (work / "contact_photos.jpg").is_file() and (work / "contact_clips.jpg").is_file()
    assert [p["id"] for p in a["photos"]] == ["P0", "P1"] and a["photos"][1]["size"] == [400, 300]
    for p in a["photos"]:
        assert p["sharpness"] > 0 and 0 < p["brightness"] < 1
    first, step, count = an.clip_sample_times(4.0)
    assert (first, step, count) == (0.5, 1.0, 4)            # one frame per second
    assert an.clip_sample_times(120.0)[2] == an.CLIP_FRAMES_MAX  # capped
    with tempfile_dir() as tmp:
        frames = an.extract_frames(a["clips"][0]["path"], 4.0, tmp, "C0")
        assert [t for t, _ in frames] == [0.5, 1.5, 2.5, 3.5]


def tempfile_dir():
    import tempfile
    class _D:
        def __enter__(self):
            self._t = tempfile.TemporaryDirectory()
            return Path(self._t.name)

        def __exit__(self, *exc):
            self._t.cleanup()
    return _D()


# --------------------------------------------------------------------------- errors and CLI (R27)
def test_errors(nc, tmp_path, make_audio, run_script):
    r = run_script("analyze.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    r = run_script("analyze.py", tmp_path / "nope", tmp_path / "work")
    assert r.returncode == 1 and "raw folder not found" in r.stderr and "Traceback" not in r.stderr
    (tmp_path / "empty").mkdir()
    r = run_script("analyze.py", tmp_path / "empty", tmp_path / "work")
    assert r.returncode == 1 and "no photos, clips or audio" in r.stderr


def test_audio_only_folder_still_analyzed(nc, tmp_path, make_audio, run_script):
    make_audio(tmp_path / "audio_only" / "music.mp3", seconds=4.0, kind="music")
    work = tmp_path / "work"
    r = run_script("analyze.py", tmp_path / "audio_only", work, "--json")
    assert r.returncode == 0, r.stderr
    assert "WARN: no usable photos or clips" in r.stderr and "brand photos" in r.stderr
    doc = json.loads((work / "analysis.json").read_text())
    assert doc["photos"] == [] and doc["clips"] == [] and doc["duration"] > 0
    assert doc["contact_sheets"] == {"photos": None, "clips": None}
    assert nc.schema_errors("analysis", doc) == []


def test_unreadable_file_skipped_and_cli_json(nc, tmp_path, make_image, run_script):
    raw = tmp_path / "raw"
    make_image(raw / "good.jpg", size=(200, 300))
    (raw / "broken.jpg").write_bytes(b"not a jpeg at all")
    (raw / "broken.mp4").write_bytes(b"not a video")
    work = tmp_path / "work"
    r = run_script("analyze.py", raw, work, "--pad-seconds", "0", "--json", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "WARN: broken.jpg: unreadable image" in r.stderr and "WARN: broken.mp4" in r.stderr
    rep = json.loads(r.stdout)
    assert rep["photos"] == 1 and rep["clips"] == 0
    doc = json.loads((work / "analysis.json").read_text())
    assert nc.schema_errors("analysis", doc) == []
    assert doc["photos"][0]["path"] == str((raw / "good.jpg").resolve())
    assert all(os.path.isabs(p["path"]) for p in doc["photos"])


def test_script_captions_on_combined_track_without_vad(nc, tmp_path, make_image, make_audio, monkeypatch):
    """Whisper unavailable (and with it Silero VAD): captions come from the script,
    voice_present is true, and the energy fallback keeps them out of the music outro."""
    raw = tmp_path / "raw"
    make_image(raw / "p.jpg", size=(200, 300))
    make_audio(raw / "voiceover_and_music.mp3", seconds=20.0, kind="music")
    script = tmp_path / "script.txt"
    script.write_text("Walk out wide awake. Three minutes of cold, and the whole day changes.")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", None)
    rc = an.main([str(raw), str(tmp_path / "work"), "--script", str(script)])
    assert rc == 0
    doc = json.loads((tmp_path / "work" / "analysis.json").read_text())
    assert doc["voice_present"] is True
    assert [w["w"] for w in doc["words"]][:2] == ["Walk", "out"] and len(doc["words"]) == 13
    assert doc["words"][-1]["end"] <= doc["duration"] - 7.5 + 0.01
    assert nc.schema_errors("analysis", doc) == []


YEAR_ONE = os.environ.get("NUMA_TEST_PACK")


@needs_whisper
@pytest.mark.skipif(not YEAR_ONE, reason="set NUMA_TEST_PACK to the test-pack folder to run the Year One check")
def test_year_one_golden(nc, tmp_path):
    pack = Path(YEAR_ONE)
    raw = pack / "2026-11-09 Year One" if (pack / "2026-11-09 Year One").is_dir() else pack
    a = an.analyze(raw, tmp_path / "work")
    assert abs(a["bpm"] - 107.7) <= 1
    assert "Mobile" in a["transcript"]
    assert nc.schema_errors("analysis", a) == []
