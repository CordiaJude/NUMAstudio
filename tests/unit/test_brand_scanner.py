"""claims_scan.py with the owners' rules (setup answers 2026-11-13, DECISIONS D25).

Name casing, the owners' never-words, emojis, private and unconfirmed offers, facts Numa must not
state, the owner-confirmed claims, the dosing line kept blocked with "source pending (Scott)", and
no false positives on Numa's own everyday copy.
"""
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


FAIL = [
    # name casing
    ("Welcome to NUMA", "name_casing"), ("NUMA's sauna at sunrise", "name_casing"),
    ("#NUMAwellness", "name_casing"), ("#NUMAStudio", "name_casing"), ("N U M A", "name_casing"),
    # the owners' never-words
    ("Grab a Discover Pass", "wrong_offer_name"), ("Explore Numa this month", "wrong_offer_name"),
    ("Use your credits on a plunge", "credits_word"), ("10 class credits", "credits_word"),
    ("The cheapest way to start", "cheap_word"), ("cheap and cheerful", "cheap_word"),
    ("Come heal with us", "heals"), ("Red light treats acne", "treats"), ("The sauna cures Mondays", "cures"),
    # emojis
    ("Calm in the chaos 🌙", "no_emoji"), ("Show up ✨", "no_emoji"), ("❌ myth ✅ fact", "no_emoji"),
    ("Time it ⏱", "no_emoji"), ("Love this ❤️", "no_emoji"), ("👀", "no_emoji"),
    # private offer
    ("Use code NEWBIE at checkout", "newbie_code"), ("newbie special", "newbie_code"),
    ("50% off your first class", "half_off"), ("Half-off your first visit", "half_off"),
    ("50 percent off this week", "half_off"),
    # facts Numa must not state
    ("Our 14-person Finnish sauna", "sauna_capacity"), ("a 14 person sauna", "sauna_capacity"),
    ("The sauna holds 14", "sauna_capacity"),
    ("Join us for Clinical Conversations", "cancelled_event"),
    ("The plunge hit 34° this morning", "plunge_temp_34"), ("34 degrees of pure cold", "plunge_temp_34"),
    # owner-confirmed claims
    ("Red light restores elasticity", "red_light_elasticity"),
    ("restores your skin's elasticity", "red_light_elasticity"),
    ("Sweat out last night's alcohol", "sauna_alcohol"), ("The sauna clears alcohol", "sauna_alcohol"),
    ("Hangover? The sauna is your friend", "sauna_alcohol"),
    ("The cold plunge lowers inflammation", "inflammation"), ("less inflammation after a plunge", "inflammation"),
    ("Every session is HSA eligible", "hsa_fsa"), ("HSA/FSA eligible memberships", "hsa_fsa"),
    ("Memberships qualify for FSA", "hsa_fsa"),
    ("Colder than any other plunge in town", "competitor_comparison"),
    ("Better than the gym", "competitor_comparison"),
    ("Unlike other studios in Mobile", "competitor_comparison"),
    ("Skip Beyond The Plunge", "competitor_comparison"),
    # dosing line: approved by the owners, blocked until its source is recorded
    ("57 minutes of sauna and 11 of cold a week", "dosing_line"),
]


@pytest.mark.parametrize("text, rule", FAIL)
def test_owner_rules_fail(text, rule):
    assert rule in fails(text), (text, fails(text))


WARN = [
    ("The plunge sits at 39°F", "plunge_temp_low"),
    ("Can I use my HSA card?", "hsa_fsa_mention"),
    ("The best sauna in Mobile", "superlative"),
    ("Robes and a tea lounge", "unconfirmed_amenity"),
    ("A 60-minute session", "unconfirmed_amenity"),
]


@pytest.mark.parametrize("text, rule", WARN)
def test_owner_rules_warn_only(text, rule):
    assert rule in warns(text), (text, warns(text))
    assert fails(text) == [], (text, fails(text))


CLEAN = [
    "Take a deep breath.", "Return to yourself.", "Calm in the chaos.", "Show up for yourself this week.",
    "Find your rhythm.", "Visit Passes are $25 ($20 for members).", "A transformative hour.",
    "Your transformation starts with one breath.", "Every journey starts somewhere.",
    "We started Numa because we needed it.", "Numa Wellness Collective, Mobile, Alabama.",
    "Discover Numa: one month for $49. 3 classes, 3 red light sessions, unlimited Flow Space. Ends on its own.",
    "The Numa Reset is free: link in bio.", "Numa Nights is back in February.",
    "Our plunges are kept at 44 to 52°F.", "Our sauna runs 175 to 190°F.", "Plunge at 44°F, sauna at 190°F.",
    "Bring a friend who is new to Numa: they come free through Nov 30.",
    "Holiday Day Pass: $39 ($29 members), Nov 23 to Dec 31.",
    "Buy a membership, give a friend a free month.",
    "Red light supports how you feel after a long week.", "A guide is always nearby.",
    "Weekday classes have room for you.", "Members, our people, the movement, the collective.",
    "Call 251-310-3656.", "1719 Dauphin St, across from Soul Caffeine.", "Open 5:30am Monday.",
    "Our members walk out wide awake.", "Thank you, Mobile. 807 of you and counting.",
    "Talk to your doctor first if you have a heart, blood pressure or breathing condition.",
    "Feels like 9 o'clock — slow down.", "44–52°F · 175–190°F",
]


@pytest.mark.parametrize("text", CLEAN)
def test_normal_copy_has_no_false_positives(text):
    assert fails(text) == [], (text, fails(text))
    assert warns(text) == [], (text, warns(text))


def test_lowercase_plugin_and_file_names_pass():
    for text in ("numa-studio", "numa_wellness_reel.mp4", "linktr.ee/numawc", "@numawellnessmobile", "#numawellness"):
        assert "name_casing" not in fails(text), text


def test_brand_rules_carry_their_own_rewrite_and_kind():
    (hit,) = [h for h in cs.scan_text("NUMA sauna night", where="hook.text") if h.rule == "name_casing"]
    assert hit.kind == "brand" and hit.suggestion == "Numa"  # not the sauna 'say' line
    assert 'banned claim "the name is "Numa", never "NUMA"' in hit.line()
    (hit,) = [h for h in cs.scan_text("50% off with NEWBIE") if h.rule == "newbie_code"]
    assert hit.kind == "offer"
    (hit,) = [h for h in cs.scan_text("Clinical Conversations tonight") if h.rule == "cancelled_event"]
    assert hit.kind == "fact"
    (hit,) = [h for h in cs.scan_text("Red light restores elasticity") if h.rule == "red_light_elasticity"]
    assert hit.kind == "claim" and hit.suggestion  # claims keep the experience rewrite


def test_dosing_line_reason_is_source_pending(nc):
    hits = [h for h in cs.scan_text("57 minutes of sauna and 11 of cold a week") if h.rule == "dosing_line"]
    assert hits and "source pending (Scott)" in hits[0].label
    dl = nc.load_brand()["claims"]["dosing_line"]
    assert dl["blocked"] is True and dl["reason"] == "source pending (Scott)"


def test_fda_cleared_needs_a_confirmed_clearance(nc, tmp_path, monkeypatch):
    brand = nc.load_brand()
    df = brand["claims"]["modalities"]["red_light"]["device_facts"]
    assert df["status"] == "confirmed" and df["fda_clearance"]["status"] == "needs_katie"
    assert "fda" in fails("FDA-cleared Block Blu Light Elite XL panels")
    brand = copy.deepcopy(brand)
    brand["claims"]["modalities"]["red_light"]["device_facts"]["fda_clearance"] = {
        "value": "temporary relief of minor muscle pain", "status": "confirmed", "source": "test"}
    p = tmp_path / "brand.json"
    p.write_text(json.dumps(brand))
    monkeypatch.setenv("NUMA_BRAND", str(p))
    nc.clear_caches()
    assert "fda" not in fails("Our Elite XL panel is FDA-cleared")


def test_plan_texts_are_scanned_for_owner_rules(plan_factory):
    plan = plan_factory()
    plan["hook"]["text"] = "Your first NUMA plunge 🧊"
    hits = cs.scan_plan(plan)
    assert {"name_casing", "no_emoji"} <= {h.rule for h in hits if h.severity == "fail"}


def test_cli_fails_on_owner_rules(run_script):
    r = run_script("claims_scan.py", "Grab a Discover Pass at NUMA")
    assert r.returncode == 1 and "wrong_offer_name" in r.stderr + r.stdout
    r = run_script("claims_scan.py", "Take a deep breath. Return to yourself.")
    assert r.returncode == 0, r.stderr
