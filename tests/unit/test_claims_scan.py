"""claims_scan.py: brand.json-driven claims checker (R126-R129, R138, R140, spec p.20-22)."""
from __future__ import annotations

import copy
import json

import pytest

import claims_scan as cs


@pytest.fixture(autouse=True)
def _fresh(nc):
    cs._rules_for.cache_clear()
    yield
    cs._rules_for.cache_clear()


def fails(text):
    return sorted({h.rule for h in cs.scan_text(text) if h.severity == "fail"})


def warns(text):
    return sorted({h.rule for h in cs.scan_text(text) if h.severity == "warn"})


# Every banned item on spec p.20-21, plus hashtags and hyphen/space variants.
SPEC_BANNED = [
    ("Reduces inflammation", "inflammation"), ("boosts your immune system", "immunity"), ("Boost immunity", "immunity"),
    ("Full body detox", "detox"), ("sweat out toxins", "detox"), ("burns fat", "fat_weight"),
    ("burn calories", "fat_weight"), ("weight loss", "fat_weight"), ("weight-loss", "fat_weight"),
    ("heals injuries", "heals"), ("Sauna cures stress", "cures"), ("treats depression", "mental_health_conditions"),
    ("prevents illness", "prevents"), ("relieves anxiety", "mental_health_conditions"), ("PTSD", "mental_health_conditions"),
    ("heal trauma", "mental_health_conditions"), ("arthritis", "arthritis"), ("pain relief", "pain_relief"),
    ("pain-relief", "pain_relief"), ("lowers blood pressure", "blood_pressure"), ("heart health", "heart_health"),
    ("anti-aging", "anti_aging"), ("anti aging", "anti_aging"), ("antiaging", "anti_aging"), ("collagen boost", "anti_aging"),
    ("fewer wrinkles", "anti_aging"), ("COVID recovery", "illness"), ("ward off illness", "illness"),
    ("science-backed", "proof_language"), ("science backed", "proof_language"), ("Clinically proven", "proof_language"),
    ("Studies show", "proof_language"), ("FDA-approved", "fda"), ("FDA cleared panels", "fda"),
    ("250% dopamine", "hormones"), ("hormone levels", "hormones"), ("breathwork therapy", "breathwork_therapy"),
    ("57 minutes of sauna and 11 of cold a week", "dosing_line"),
]

HASHTAGS = [
    ("#detox", "detox"), ("#weightloss", "fat_weight"), ("#antiaging", "anti_aging"), ("#painrelief", "pain_relief"),
    ("#immunityboost", "immunity"), ("#anxietyrelief", "mental_health_conditions"), ("#ColdPlungeDetox", "detox"),
    ("#HeartHealth", "heart_health"), ("#cureanxiety", "cures"),
]

TESTIMONIALS = ["It fixed my back pain", "My anxiety is gone since I started", "I lost 10 pounds in a month",
                "This took away my migraines"]

CLEAN = [
    "Three minutes of cold. Walk out wide awake.", "A challenge that leaves many people feeling energized.",
    "Pairs well with the sauna for contrast.", "Deep, quiet heat to unwind.", "A centuries-old Finnish ritual.",
    "Relax, breathe, disconnect.", "our panels use 660 nm and 850 nm light", "A warm, calming session",
    "Guided breathing to help you slow down.", "Feel more centered.", "Learn techniques people use to relax.",
    "Your reset starts here.", "Year one. Thank you, Mobile.", "Treat yourself to a Friday contrast session.",
    "Our new Flow Space is a real treat.", "Our guides are trauma-informed.", "Hormone-free snacks after class.",
    "Talk to your doctor first if you have a heart, blood pressure or breathing condition.",
    "#MobileAL #MidtownMobile #GulfCoastWellness", "Open 11 to 7 on Sundays.", "We are 57 steps from the bay.",
]


@pytest.mark.parametrize("text, rule", SPEC_BANNED)
def test_every_spec_banned_item_fails(text, rule):
    assert rule in fails(text), (text, fails(text))


@pytest.mark.parametrize("text, rule", HASHTAGS)
def test_hashtags_fail(text, rule):
    assert rule in fails(text), (text, fails(text))


@pytest.mark.parametrize("tag", ["#detox", "#weightloss", "#antiaging", "#painrelief", "#immunityboost", "#anxietyrelief"])
def test_never_hashtags_from_brand(tag, nc):
    assert tag in nc.load_brand()["captions"]["hashtags"]["never"]
    assert "hashtag_never" in fails(f"Sunday reset {tag.upper()}")


@pytest.mark.parametrize("text", TESTIMONIALS)
def test_testimonial_outcomes_fail(text):
    assert fails(text), text


@pytest.mark.parametrize("text", CLEAN)
def test_clean_text_passes(text):
    assert fails(text) == [], text


@pytest.mark.parametrize("text, rule", [
    ("Cold brew and summer treats at the front desk.", "treat_ambiguous"),
    ("The cure for Monday: three minutes of cold.", "cure_ambiguous"),
    ("Meet our neighbors at Healing Arts.", "healing_ambiguous"),
    ("Grip mats help prevent slipping.", "prevent_ambiguous"),
    ("Improves sleep", "outcome_verbs"), ("recover faster", "outcome_verbs"),
    ("Try our cryotherapy", "not_offered"), ("IV drips on Fridays", "not_offered"),
])
def test_ambiguous_wording_warns_only(text, rule):
    assert fails(text) == [], text
    assert rule in warns(text), (text, warns(text))


def test_warn_overlapping_a_fail_is_dropped():
    hits = cs.scan_text("healing anxiety")
    assert {h.rule for h in hits} >= {"heals", "mental_health_conditions"}
    assert "healing_ambiguous" not in {h.rule for h in hits}


def test_hit_details_and_suggestion():
    (hit,) = [h for h in cs.scan_text("Sweat out toxins in the sauna", where="lines[2]") if h.rule == "detox"]
    assert hit.severity == "fail" and hit.where == "lines[2]" and hit.match.lower() == "toxins"
    assert hit.label == "detox or toxins"
    assert hit.suggestion == "Deep, quiet heat to unwind."  # brand.json sauna 'say' line
    assert 'banned claim "detox or toxins" in lines[2]: "toxins"' in hit.line()


def test_dosing_line_unblocked_by_brand(nc, tmp_path, monkeypatch):
    brand = copy.deepcopy(nc.load_brand())
    brand["claims"]["dosing_line"]["blocked"] = False
    p = tmp_path / "brand.json"
    p.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(p))
    nc.clear_caches()
    assert fails("57 minutes of sauna and 11 of cold a week") == []


def test_fda_cleared_with_confirmed_device(nc, tmp_path, monkeypatch):
    brand = copy.deepcopy(nc.load_brand())
    brand["claims"]["modalities"]["red_light"]["device_facts"] = {
        "value": {"model": "Lumen X9"}, "status": "confirmed", "source": "test", "note": "test"}
    p = tmp_path / "brand.json"
    p.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(p))
    nc.clear_caches()
    assert "fda" in fails("FDA-cleared panels")
    assert fails("Our Lumen X9 panel is FDA-cleared for temporary muscle relief") == []
    assert "fda" in fails("FDA-approved Lumen X9")


def test_plan_texts_cover_every_surface(plan_factory):
    plan = plan_factory()
    plan["endcard"]["subtitle"] = "No more getting sick"
    plan["hook"]["text"] = "Detox day"
    plan["formats"] = {"cover": {"t": 1.0, "title": "Clinically proven calm"},
                       "story": [{"t": 1, "text": "a"}, {"t": 2, "text": "b"}, {"t": 3, "text": "#weightloss"}]}
    where = {h.where for h in cs.scan_plan(plan) if h.severity == "fail"}
    assert {"hook.text", "endcard.subtitle", "formats.cover.title", "formats.story[2].text"} <= where


def test_srt_parsing():
    srt = "1\n00:00:00,500 --> 00:00:02,000\nThis is <i>what</i> Katie saw.\n\n2\n00:00:02,100 --> 00:00:03,000\nNo detox here\n"
    assert cs.srt_text(srt) == "This is what Katie saw.\nNo detox here"


# ---- CLI ----------------------------------------------------------------------
def test_cli_hit_exits_1(run_script):
    r = run_script("claims_scan.py", "Sauna cures stress")
    assert r.returncode == 1
    assert 'ERROR: banned claim "cures" in text: "cures"' in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_clean_exits_0(run_script):
    r = run_script("claims_scan.py", "Three minutes of cold. Walk out wide awake.")
    assert r.returncode == 0 and r.stdout.startswith("OK")


def test_cli_warn_only_exits_0(run_script):
    r = run_script("claims_scan.py", "The cure for Monday")
    assert r.returncode == 0 and "WARN:" in r.stderr


def test_cli_hashtags_and_json(run_script):
    r = run_script("claims_scan.py", "--hashtags", "#MobileAL #detox", "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert report["ok"] is False and {h["rule"] for h in report["hits"]} >= {"detox", "hashtag_never"}


def test_cli_stdin(scripts_dir):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(scripts_dir / "claims_scan.py"), "-"], input="It heals your body\n",
                       capture_output=True, text=True)
    assert r.returncode == 1 and "in stdin" in r.stderr


def test_cli_files_and_plan(run_script, tmp_path, plan_factory):
    srt = tmp_path / "reel.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nBurns fat fast\n")
    txt = tmp_path / "copy.txt"
    txt.write_text("Cold plunge in Mobile, AL\nfeel wide awake\n")
    r = run_script("claims_scan.py", "--file", srt, "--file", txt)
    assert r.returncode == 1 and "reel.srt line 1" in r.stderr and "copy.txt" not in r.stderr
    plan = plan_factory()
    plan["lines"][0]["words"][0][0] = "Detox"
    pp = tmp_path / "plan.json"
    pp.write_text(json.dumps(plan))
    r = run_script("claims_scan.py", "--plan", pp)
    assert r.returncode == 1 and "plan lines[0]" in r.stderr


def test_cli_usage_and_missing_file(run_script, tmp_path):
    r = run_script("claims_scan.py")
    assert r.returncode == 2 and "ERROR:" in r.stderr
    r = run_script("claims_scan.py", "--file", tmp_path / "nope.txt")
    assert r.returncode == 1 and "ERROR:" in r.stderr and "Traceback" not in r.stderr


# ---- revision 2: run-together hashtags, obfuscation, dosing context, modality-aware rewrites ----
@pytest.mark.parametrize("tag, rule", [
    ("#sundaydetox", "detox"), ("#sweatoutthetoxins", "detox"), ("#boostimmunity", "immunity"),
    ("#antiinflammatory", "inflammation"), ("#fatburning", "fat_weight"), ("#painreliefnow", "pain_relief"),
    ("#curestress", "cures"), ("#healsyourbody", "heals"), ("#nomoreanxiety", "mental_health_conditions"),
    ("#weightlossjourney", "fat_weight"), ("#sciencebackedwellness", "proof_language"),
])
def test_run_together_hashtags_fail(tag, rule):
    assert rule in fails(tag), (tag, fails(tag))


@pytest.mark.parametrize("tag", ["#securesleep", "#community", "#traumainformed", "#hormonefree", "#treatyourself",
                                 "#influencer", "#heartwarming", "#MobileAL", "#coldplunge", "#curiouscat",
                                 "#manicuremonday", "#saunasunday"])
def test_innocent_hashtags_pass(tag):
    assert fails(tag) == [], (tag, fails(tag))


@pytest.mark.parametrize("text, rule", [
    ("D e t o x", "detox"), ("d.e.t.o.x your body", "detox"), ("D-E-T-O-X", "detox"),
    ("Dеtox", "detox"),            # Cyrillic e
    ("іmmunity boost", "immunity"),  # Cyrillic i
    ("ＤＥＴＯＸ", "detox"),        # full-width (NFKC)
    ("de\u200btox", "detox"),       # zero-width space
    ("reduces inflamation", "misspelled_claim"), ("boost your imunity", "misspelled_claim"),
])
def test_obfuscated_and_misspelled_claims_fail(text, rule):
    assert rule in fails(text), (text, fails(text))


@pytest.mark.parametrize("text", ["Only 57 spots left for the 11 am class", "Doors open at 11, 57 Dauphin St.",
                                  "a b c d e f g", "I. AM. HERE."])
def test_no_false_positive_for_numbers_and_spaced_letters(text):
    assert fails(text) == [], (text, fails(text))


@pytest.mark.parametrize("text", ["57 min in the sauna and 11 in the cold", "Sauna for 57 minutes a week",
                                  "11 minutes of cold plunge a week"])
def test_dosing_line_variants_fail(text):
    assert {"dosing_line", "dosing_line_any"} & set(fails(text)), (text, fails(text))


@pytest.mark.parametrize("text, say", [
    ("Sauna cures stress", "Deep, quiet heat to unwind."),
    ("The cold plunge cures stress", "Three minutes of cold. Walk out wide awake."),
    ("Breathwork cures stress", "Guided breathing to help you slow down."),
])
def test_rewrite_follows_the_modality_named(text, say):
    (hit,) = [h for h in cs.scan_text(text) if h.rule == "cures"]
    assert hit.suggestion == say


def test_cli_run_together_hashtag(run_script):
    r = run_script("claims_scan.py", "--hashtags", "#sundaydetox")
    assert r.returncode == 1 and '"#sundaydetox"' in r.stderr


# The illness rule lives in brand.json (orchestrator-owned). Its "never ... cold" branch flagged the
# modality ("I said I could never do a cold plunge"). PROPOSED_COLD is the requested brand.json change:
# "colds?" in the illness pattern is not the illness when a modality word follows it.
PROPOSED_COLD = r"colds?(?!\s*(plunges?|water|tubs?|showers?|exposure|immersion|therapy|dips?|soaks?|baths?)\b)|"


def _brand_with_illness_fix():
    brand = copy.deepcopy(cs.nc.load_brand(cs.nc.brand_path()))
    rule = next(r for r in brand["claims"]["banned"] if r["id"] == "illness")
    rule["patterns"] = [p.replace("colds?|", PROPOSED_COLD) if "never" in p and PROPOSED_COLD not in p else p
                        for p in rule["patterns"]]
    return brand


@pytest.mark.parametrize("text", ["I said I could never do a cold plunge", "never a cold plunge person",
                                  "no more cold showers at home, just the plunge"])
def test_cold_plunge_is_not_the_illness(text):
    brand = _brand_with_illness_fix()
    assert "illness" not in {h.rule for h in cs.scan_text(text, brand=brand) if h.severity == "fail"}


@pytest.mark.parametrize("text", ["I never get colds now", "fewer colds this winter", "beat the flu",
                                  "never get sick", "never catch a cold again", "fight off colds and flu"])
def test_illness_true_positives_survive_the_fix(text):
    brand = _brand_with_illness_fix()
    assert "illness" in {h.rule for h in cs.scan_text(text, brand=brand) if h.severity == "fail"}


def test_plan_cards_are_scanned():
    plan = {"shots": [], "cards": [{"t0": 0, "t1": 2, "text": "*Detox* in 3 minutes"},
                                   {"t0": 3, "t1": 5, "text": "1", "style": "number", "sub": "Boost immunity"}]}
    wheres = {h.where for h in cs.scan_plan(plan) if h.severity == "fail"}
    assert {"cards[0].text", "cards[1].sub"} <= wheres
