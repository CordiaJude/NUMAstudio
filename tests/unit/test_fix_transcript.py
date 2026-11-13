"""Unit tests for scripts/fix_transcript.py (R28, R102 script fallback). No speech model needed."""
from __future__ import annotations

import json

import pytest

import fix_transcript as ft


def W(text, start, end, p=0.9):
    return {"w": text, "appear": ft.appear_time(start, end), "end": end, "start": start, "p": p}


def words_of(sentence, t0=0.0, step=0.5):
    return [W(tok, round(t0 + i * step, 2), round(t0 + i * step + 0.4, 2)) for i, tok in enumerate(sentence.split())]


@pytest.fixture
def analysis_doc(tmp_path):
    def _make(words, **extra):
        doc = {
            "schema_version": 2, "duration": 20.0, "bpm": 100.0, "beats": [0.6, 1.2], "words": words,
            "transcript": " ".join(w["w"] for w in words), "voice_present": bool(words),
            "audio": {"voice": None, "music": None, "master": None},
            "photos": [{"id": "P0", "path": str(tmp_path / "p.jpg"), "size": [100, 100]}], "clips": [],
        }
        doc.update(extra)
        return doc
    return _make


# --------------------------------------------------------------------------- brand fixes
def test_brand_fix_moby_to_mobile_keeps_punctuation_and_timing(nc):
    words = words_of("we are so grateful for you, Moby. Thank you")
    before = [(w["appear"], w["end"], w["start"]) for w in words]
    protect, fixes = ft.load_fixes()
    corr = ft.apply_brand_fixes(words, protect, fixes)
    assert words[6]["w"] == "Mobile."
    assert corr == [{"index": 6, "from": "Moby.", "to": "Mobile.", "reason": "brand_fix"}]
    assert [(w["appear"], w["end"], w["start"]) for w in words] == before


def test_brand_fix_possessive_case_and_protect(nc):
    words = words_of("Moby's best spot is Numa and numa but Numa Nights stays")
    protect, fixes = ft.load_fixes()
    ft.apply_brand_fixes(words, protect, fixes)
    got = [w["w"] for w in words]
    assert got[0] == "Mobile's"
    assert got[4] == "NUMA"          # case-sensitive variant "Numa"
    assert got[6] == "numa"          # lowercase is not a listed variant
    assert got[8:10] == ["Numa", "Nights"]  # protected phrase


def test_brand_fix_next_words_rule(nc):
    words = words_of("meet me on Dolphin St. near the Dolphin pool")
    protect, fixes = ft.load_fixes()
    ft.apply_brand_fixes(words, protect, fixes)
    got = [w["w"] for w in words]
    assert got[3] == "Dauphin" and got[7] == "Dolphin"


# --------------------------------------------------------------------------- script alignment
def test_script_tokens_strip_labels_and_directions():
    toks = ft.script_tokens("VO: This is what Katie saw. [beat]\n(pause) Thank you, Mobile!\n")
    assert toks == ["This", "is", "what", "Katie", "saw.", "Thank", "you,", "Mobile!"]


def test_align_replaces_misheard_word_and_keeps_timing():
    words = words_of("this is what Kadi saw I dont know")
    script = ft.script_tokens("This is what Katie saw. I don't know.")
    new, corr, confirmed = ft.align_to_script(words, script)
    assert [w["w"] for w in new] == ["This", "is", "what", "Katie", "saw.", "I", "don't", "know."]
    assert [(w["appear"], w["end"]) for w in new] == [(w["appear"], w["end"]) for w in words]
    assert {"index": 3, "from": "Kadi", "to": "Katie", "reason": "script"} in corr
    assert confirmed == set(range(8))


def test_align_merges_split_word_with_span_timing():
    words = words_of("grateful for you Moby Le thank you")
    script = ft.script_tokens("grateful for you Mobile thank you")
    new, corr, _ = ft.align_to_script(words, script)
    assert [w["w"] for w in new] == ["grateful", "for", "you", "Mobile", "thank", "you"]
    merged = new[3]
    assert merged["start"] == words[3]["start"] and merged["appear"] == words[3]["appear"]
    assert merged["end"] == words[4]["end"]
    assert any(c["from"] == "Moby Le" and c["to"] == "Mobile" for c in corr)


def test_align_keeps_adlibs_and_dissimilar_runs():
    words = words_of("hello everyone this is what Katie saw")
    script = ft.script_tokens("This is what Katie saw.")
    new, _, _ = ft.align_to_script(words, script)
    assert [w["w"] for w in new] == ["hello", "everyone", "This", "is", "what", "Katie", "saw."]


def test_align_keeps_sentence_initial_capital():
    # a 1.6 s pause after "cold" breaks the caption line: "We" starts it and keeps its capital
    words = words_of("It was cold") + words_of("We took a chance", t0=3.0)
    script = ft.script_tokens("It was cold, we took a chance.")
    new, corr, _ = ft.align_to_script(words, script)
    assert [w["w"] for w in new] == ["It", "was", "cold,", "We", "took", "a", "chance."]
    assert not any(c["to"] == "we" for c in corr)
    # no pause and the script joins the sentences: lowercase is right there
    new, _, _ = ft.align_to_script(words_of("It was cold We took a chance"), script)
    assert new[3]["w"] == "we"
    # first word of the transcript (a caption line start) keeps its capital too
    new, _, _ = ft.align_to_script(words_of("We took a chance"), ft.script_tokens("we took a chance."))
    assert new[0]["w"] == "We"
    # mid-sentence the script's lowercase still wins
    new, _, _ = ft.align_to_script(words_of("thank You so much"), ft.script_tokens("Thank you so much."))
    assert [w["w"] for w in new] == ["Thank", "you", "so", "much."]


def test_align_inserts_dropped_script_word_with_interpolated_timing(nc, analysis_doc):
    words = words_of("It was hard. We took a chance")   # 0.5 s apart, 0.4 s long: 0.1 s gaps
    doc = analysis_doc(words)
    ft.correct(doc, ft.script_tokens("It was hard. And we took a chance."))
    got = doc["words"]
    assert [w["w"] for w in got] == ["It", "was", "hard.", "And", "we", "took", "a", "chance."]
    ins = got[3]
    assert ins["source"] == "script" and got[2]["end"] <= ins["start"] < ins["end"] <= got[4]["start"]
    assert ins["appear"] == ft.appear_time(ins["start"], ins["end"])
    assert {"index": 3, "from": "", "to": "And", "reason": "script"} in doc["corrections"]
    assert [w["appear"] for w in got] == sorted(w["appear"] for w in got)
    assert nc.schema_errors("analysis", doc) == []
    # sentence-initial drop with no word before it: placed just before the next word
    new, _, _ = ft.align_to_script(words_of("We took a chance", t0=1.0), ft.script_tokens("And we took a chance."))
    assert [w["w"] for w in new] == ["And", "we", "took", "a", "chance."]
    assert 0 <= new[0]["start"] < new[0]["end"] <= 1.0


def test_align_does_not_insert_long_or_cross_sentence_gaps():
    # three missing words: too long a gap to invent timing
    new, _, _ = ft.align_to_script(words_of("we went to the beach"),
                                   ft.script_tokens("we went all the way to the beach"))
    assert [w["w"] for w in new] == ["we", "went", "to", "the", "beach"]
    # a whole missing sentence ("Yes.") between two heard sentences is not inserted
    new, _, _ = ft.align_to_script(words_of("It was cold. We stayed"),
                                   ft.script_tokens("It was cold. Yes. We stayed."))
    assert [w["w"] for w in new] == ["It", "was", "cold.", "We", "stayed."]
    # nothing heard after the missing words: no right neighbour
    new, _, _ = ft.align_to_script(words_of("we took a"), ft.script_tokens("we took a chance"))
    assert [w["w"] for w in new] == ["we", "took", "a"]


def test_script_wins_over_brand_list(nc, analysis_doc):
    # the script spells it "Moby" (e.g. a person's name): the brand fix must not override the script
    doc = analysis_doc(words_of("say hi to Moby today"))
    ft.correct(doc, ft.script_tokens("Say hi to Moby today."))
    assert doc["transcript"] == "Say hi to Moby today."
    assert all(c["reason"] == "script" for c in doc["corrections"])


def test_correct_without_script_applies_brand_fixes(nc, analysis_doc):
    doc = analysis_doc(words_of("thank you Moby"))
    ft.correct(doc)
    assert doc["transcript"] == "thank you Mobile"
    assert doc["corrections"][0]["reason"] == "brand_fix"
    assert nc.schema_errors("analysis", doc) == []


# --------------------------------------------------------------------------- captions from the script
def test_words_from_script_spread_over_spans():
    toks = ft.script_tokens("One two three. Four five six.")
    out = ft.words_from_script(toks, [(1.0, 3.0), (4.0, 6.0)])
    assert [w["w"] for w in out] == toks
    assert out[0]["start"] >= 1.0 and out[-1]["end"] <= 6.0 + 1e-6
    appears = [w["appear"] for w in out]
    assert appears == sorted(appears)
    for w in out:
        assert w["appear"] == round(max(w["start"], w["end"] - 0.4), 2)
        assert w["source"] == "script"


def test_garbage_transcript_replaced_by_script_timed_to_voice(nc, analysis_doc, make_audio, tmp_path):
    voice = make_audio(tmp_path / "voice.wav", seconds=6.0, kind="voice")
    garbage = words_of("la la la la la la")
    for w in garbage:
        w["p"] = 0.3   # the recognizer was unsure: garbage, not an ad-lib
    doc = analysis_doc(garbage, duration=6.0)
    doc["audio"]["voice"] = str(voice)
    script = ft.script_tokens("Walk out wide awake. Three minutes of cold.")
    ft.correct(doc, script)
    assert [w["w"] for w in doc["words"]] == script
    assert ft.SCRIPT_FALLBACK_WARNING in doc["warnings"]
    assert all(0 <= w["appear"] <= w["end"] <= 6.0 for w in doc["words"])
    assert nc.schema_errors("analysis", doc) == []


def test_missing_transcript_uses_script_with_audio_duration(nc, analysis_doc):
    doc = analysis_doc([], duration=20.0)
    doc["audio"]["music"] = "/abs/music.wav"
    ft.correct(doc, ft.script_tokens("A short line for the reel."))
    assert len(doc["words"]) == 6
    assert doc["words"][-1]["end"] <= 20.0 - 7.5 + 1e-6   # the music outro stays caption-free


def test_silent_voice_with_music_keeps_script_captions_out_of_outro(nc, analysis_doc, make_audio, tmp_path):
    # the voice file holds no detectable speech or energy: the fallback span must stop
    # before the music-only outro instead of spreading over the whole reel
    voice = make_audio(tmp_path / "voice.wav", seconds=1.0, kind="silence")
    doc = analysis_doc([], duration=20.0)
    doc["audio"]["voice"] = str(voice)
    doc["audio"]["music"] = "/abs/music.wav"
    spans = ft.speech_spans(doc)
    assert spans and spans[-1][1] <= 20.0 - 7.5 + 1e-6
    ft.correct(doc, ft.script_tokens("A short line for the reel."))
    assert doc["words"] and doc["words"][-1]["end"] <= 20.0 - 7.5 + 1e-6
    # without music the whole duration stays available
    doc = analysis_doc([], duration=20.0)
    doc["audio"]["voice"] = str(voice)
    assert ft.speech_spans(doc)[-1][1] > 20.0 - 7.5


def test_music_only_never_gets_script_captions(nc, analysis_doc):
    doc = analysis_doc([])
    ft.correct(doc, ft.script_tokens("Never shown."), allow_script_timing=False)
    assert doc["words"] == [] and doc["transcript"] == ""


# --------------------------------------------------------------------------- CLI
def test_cli_writes_corrections_and_is_deterministic(nc, analysis_doc, run_script, tmp_path):
    path = tmp_path / "analysis.json"
    nc.write_json(path, analysis_doc(words_of("we love you Moby")))
    script = tmp_path / "script.txt"
    script.write_text("We love you, Mobile.\n")
    r = run_script("fix_transcript.py", path, "--script", script, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["transcript"] == "We love you, Mobile."
    first = path.read_bytes()
    r2 = run_script("fix_transcript.py", path, "--script", script)
    assert r2.returncode == 0, r2.stderr
    assert "applied 0 correction(s)" in r2.stdout
    assert path.read_bytes() == first   # idempotent: nothing new to correct
    doc = json.loads(first)
    assert nc.schema_errors("analysis", doc) == []
    assert doc["words"][3]["w"] == "Mobile."


def test_cli_dry_run_does_not_write(nc, analysis_doc, run_script, tmp_path):
    path = tmp_path / "analysis.json"
    nc.write_json(path, analysis_doc(words_of("thanks Moby")))
    before = path.read_bytes()
    r = run_script("fix_transcript.py", path, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert '"Moby" -> "Mobile"' in r.stdout
    assert path.read_bytes() == before


def test_cli_errors(nc, run_script, tmp_path):
    r = run_script("fix_transcript.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps({"duration": 10, "words": []}))
    r = run_script("fix_transcript.py", v1)
    assert r.returncode == 1 and "re-run analyze.py" in r.stderr and "Traceback" not in r.stderr
    r = run_script("fix_transcript.py", tmp_path / "missing.json")
    assert r.returncode == 1 and r.stderr.startswith("ERROR:")


def test_confident_transcript_kept_when_script_unrelated(nc, analysis_doc):
    words = words_of("today we are opening the doors to our new studio space for everyone")
    for w in words:
        w["p"] = 0.95
    doc = analysis_doc(words)
    ft.correct(doc, ft.script_tokens("Cold water resets the nervous system in three minutes flat."))
    assert doc["transcript"] == " ".join(w["w"] for w in words)
    assert not any(w.get("source") == "script" for w in doc["words"])
    assert ft.SCRIPT_MISMATCH_WARNING in doc["warnings"]


def test_unsure_transcript_replaced_by_script(nc, analysis_doc):
    words = words_of("uh the of a an the of uh")
    for w in words:
        w["p"] = 0.2
    doc = analysis_doc(words, duration=10.0)
    ft.correct(doc, ft.script_tokens("Cold water resets the nervous system."))
    assert doc["transcript"] == "Cold water resets the nervous system."
    assert doc["voice_present"] is True
