"""brand/brand.json carries the owners' setup answers (2026-11-13, DECISIONS D25/D26).

Business facts, offers and promotions, the brand look and voice, posting approval, owner priors
for the strategy engine, the people/consent split (roles only in the public repo; names in the
private STATE/people.json) and the docs that describe them.
"""
from __future__ import annotations

import json
import re
from datetime import date

import pytest

import claims_scan as cs


@pytest.fixture(scope="module")
def brand(repo_root):
    return json.loads((repo_root / "brand" / "brand.json").read_text(encoding="utf-8"))


def v(brand, dotted):
    cur = brand
    for part in dotted.split("."):
        cur = cur[part]
    return cur["value"] if isinstance(cur, dict) and "value" in cur and "status" in cur else cur


def status(brand, dotted):
    cur = brand
    for part in dotted.split("."):
        cur = cur[part]
    return cur["status"]


# --------------------------------------------------------------------------- the business
def test_name_is_numa(brand):
    name = v(brand, "business.name")
    assert name["full"] == "Numa Wellness Collective" and name["short"] == "Numa"
    assert name["free_track"] == "The Numa Reset" and name["paid_trial"] == "Discover Numa"
    assert status(brand, "business.name_usage") == "confirmed"


def test_no_numa_caps_in_user_facing_brand_text(brand):
    """Every say line, reference line, offer name and end card text passes the scanner."""
    texts = (v(brand, "voice.reference_lines") + v(brand, "voice.site_lines") + v(brand, "voice.words_always")
             + [v(brand, "endcard.tagline"), v(brand, "endcard.default_subtitle")]
             + [o["name"] for o in v(brand, "offerings.offers")]
             + [m["name"] for m in v(brand, "offerings.memberships")]
             + [s["name"] for s in v(brand, "offerings.sessions")]
             + v(brand, "business.temperatures")["say"]
             + [line for m in brand["claims"]["modalities"].values() for line in m["say"] if "(" not in line])
    for t in texts:
        assert [h.rule for h in cs.scan_text(t) if h.severity == "fail"] == [], t


def test_location_phone_hours(brand):
    loc = v(brand, "business.location")
    assert loc["address"] == "1719 Dauphin St, Mobile, AL 36604"
    assert "Soul Caffeine" in loc["landmarks"] and "Via" in loc["landmarks"]
    assert v(brand, "business.phone") == "251-310-3656" and status(brand, "business.phone") == "confirmed"
    assert "candidates" not in brand["business"]["phone"]
    hours = v(brand, "business.hours")
    assert hours["regular"]["mon"] == ["05:30", "18:30"] and hours["regular"]["thu"] == ["06:00", "18:30"]
    assert hours["regular"]["sat"] == ["08:00", "11:30"] and hours["regular"]["sun"] is None
    assert hours["class_gap"] == {"start": "13:30", "end": "15:30", "note": "No classes 1:30 to 3:30pm daily."}
    assert hours["under_review"] is True


def test_closures_next_six_months(brand):
    known = v(brand, "closures.known")
    closed = {(c["start"], c["end"]) for c in known if c["closed"]}
    assert {("2026-11-25", "2026-11-27"), ("2026-12-24", "2026-12-25"), ("2027-01-01", "2027-01-01"),
            ("2027-03-26", "2027-03-28")} <= closed
    nye = [c for c in known if c["start"] == "2026-12-31"]
    assert nye and nye[0]["closed"] is False and nye[0]["open_until"] == "12:00"
    for c in known:
        assert date.fromisoformat(c["start"]) <= date.fromisoformat(c["end"])


def test_temperatures_and_unknown_sauna_capacity(brand):
    t = v(brand, "business.temperatures")
    assert t["cold_plunge_f"] == [44, 52] and t["sauna_f"] == [175, 190]
    assert "14" not in json.dumps(v(brand, "business.facility"))
    cap = brand["business"]["sauna_capacity"]
    assert cap["value"] is None and cap["status"] == "needs_katie"


def test_every_price_exactly_as_given(brand):
    sessions = {s["name"]: s["price"] for s in v(brand, "offerings.sessions")}
    want = {"Visit Pass": (25, 20), "Sauna Session": (25, None), "Cold Plunge Session": (25, None),
            "Experience Pass": (55, 40), "Biohack AM or PM": (45, 35),
            "Personalized Yoga + Mind-Body Integration": (100, None), "Breathwork Coaching 1:1": (150, None),
            "Numa Private": (175, None), "Couples Private Space Access": (195, None), "Group Breathwork": (250, None),
            "Numa Private for Couples": (295, None), "Numa Private Experience": (375, None)}
    assert set(sessions) == set(want)
    for name, (price, member) in want.items():
        assert sessions[name]["value"] == price and sessions[name].get("member_value") == member, name
        assert sessions[name]["status"] == "confirmed"
    bundles = {b["count"]: b["price"]["value"] for b in v(brand, "offerings.visit_pass_bundles")}
    assert bundles == {5: 125, 10: 220, 20: 380}
    mem = {m["name"]: m for m in v(brand, "offerings.memberships")}
    assert [mem[n]["price"]["value"] for n in ("Foundation Membership", "Practice Membership", "Immersion Membership",
                                               "Single Modality Plan", "R.E.N.E.W. Elevated Foundations")] == [99, 149, 199, 99, 97]
    assert mem["Single Modality Plan"]["two_plans"]["value"] == 149
    assert "MD" in mem["R.E.N.E.W. Elevated Foundations"]["provider"]
    assert all(p["price"] == "set by the provider" for p in v(brand, "offerings.provider_services"))


def test_discover_numa_terms(brand):
    offers = {o["name"]: o for o in v(brand, "offerings.offers")}
    d = offers["Discover Numa"]
    assert d["price"]["value"] == 49 and d["link"] == "https://linktr.ee/numawc"
    det = d["details"]["value"]
    assert det["includes"] == ["3 classes", "3 red light sessions", "unlimited Flow Space"]
    assert det["length"] == "one month" and det["one_time_only"] is True
    assert det["commitment"] == "none" and det["renewal"] == "ends on its own"
    assert offers["The Numa Reset"]["role"] == "the free door" and offers["The Numa Reset"]["price"]["value"] == 0
    assert v(brand, "business.cta_link") == "https://linktr.ee/numawc"
    assert v(brand, "offerings.priority_offer") == {"paid_door": "Discover Numa ($49)", "free_door": "The Numa Reset"}


def test_events_and_cancelled_clinical_conversations(brand):
    ev = {e["name"]: e["details"] for e in v(brand, "offerings.events")}
    for name in ("Numa Nights", "Community Days"):
        assert ev[name]["value"]["frequency"] == "about once every 4 months" and ev[name]["status"] == "needs_katie"
    assert ev["Clinical Conversations"]["value"] == {"state": "cancelled for now", "promote": False}
    assert "Clinical Conversations" in [d["what"] for d in v(brand, "offerings.do_not_promote")]


PROMOS = {
    "bring_a_friend": (None, "2026-11-30", True, True),
    "newbie": ("2026-12-01", None, False, True),
    "holiday_day_pass": ("2026-11-23", "2026-12-31", True, True),
    "unlimited_weekly_pass": ("2026-11-23", "2026-12-31", True, True),
    "black_friday_gift_card_bonus": ("2026-11-27", "2026-11-30", True, True),
    "black_friday_membership_bogo": ("2026-11-27", "2026-11-30", True, True),
    "friday_escape_noon": ("2027-01-01", None, True, True),
    "polished_and_prepped": ("2027-01-08", "2027-01-11", True, True),
    "date_night": ("2027-01-15", "2027-01-15", True, True),
    "member_appreciation_party": ("2026-12-01", "2026-12-01", True, False),
    "winter_solstice": ("2026-12-22", "2026-12-22", True, False),
}


def test_promotions_with_windows_and_confirmation(brand):
    promos = {p["id"]: p for p in v(brand, "offerings.promotions")}
    for pid, (start, end, public, confirmed) in PROMOS.items():
        p = promos[pid]
        assert (p["start"], p["end"], p["public"], p["confirmed"]) == (start, end, public, confirmed), pid
    hd, uw = promos["holiday_day_pass"]["price"], promos["unlimited_weekly_pass"]["price"]
    assert (hd["value"], hd["member_value"], uw["value"], uw["member_value"]) == (39, 29, 79, 59)
    assert len(promos["black_friday_membership_bogo"]["open_questions"]) == 2
    assert promos["black_friday_gift_card_bonus"]["open_questions"]
    assert promos["polished_and_prepped"]["dates"] == ["2027-01-08", "2027-01-11"]
    assert promos["super_escape"]["open_questions"]
    assert promos["student_and_over_60_offers"]["confirmed"] is False


def test_newbie_never_public(brand):
    promos = {p["id"]: p for p in v(brand, "offerings.promotions")}
    assert promos["newbie"]["public"] is False and promos["newbie"]["channels"] == ["email", "front desk"]
    for text in ("NEWBIE", "50% off your first class"):
        assert any(h.severity == "fail" for h in cs.scan_text(text)), text


def test_rules_saturday_discounts_no_ads(brand):
    assert "Saturday morning" in v(brand, "offerings.new_people_rule")
    groups = v(brand, "offerings.discounts")["memberships_15_percent_off"]
    assert groups == ["healthcare workers", "veterans", "active military", "police", "firefighters", "EMTs",
                      "teachers", "ministry leaders"]
    assert v(brand, "positioning.paid_ads") == "none" and "tracking" in brand["positioning"]["paid_ads"]["note"]


# --------------------------------------------------------------------------- look and voice
OFFICIAL = {"dark_teal": "#06272E", "tan_gold": "#CA8B3A", "beige": "#F2EADB", "light_blue": "#C6E2E3",
            "blue": "#94BBC7", "light": "#FBFAF8"}


def test_palette_official_and_aliases(brand):
    pal = brand["palette"]
    assert pal["status"] == "confirmed" and pal["official"] == list(OFFICIAL)
    for key, hexv in OFFICIAL.items():
        assert pal["value"][key] == hexv
    for alias, target in pal["aliases"].items():
        assert pal["value"][alias] == pal["value"][target], alias
    assert set(pal["aliases"]) == {"cedar_ember", "water_teal", "cream", "ink"}
    for role, name in pal["roles"].items():
        assert name in pal["value"], role


def test_brand_fonts_recorded_never_bundled(brand, repo_root):
    names = [f["name"] for f in brand["fonts"]["brand_fonts"]["value"]]
    assert names == ["Domaine Sans Text Light", "Avenir Next"]
    assert all(f["licence"] == "commercial" and f["bundled"] is False for f in brand["fonts"]["brand_fonts"]["value"])
    found = [p for p in repo_root.rglob("*") if p.is_file() and ".git" not in p.parts
             and re.search(r"domaine|avenir", p.name, re.I) and p.suffix.lower() in (".otf", ".ttf", ".woff", ".woff2")]
    assert found == [], found
    assert brand["fonts"]["stand_ins"]["status"] == "bundled"


def test_logo_and_voice(brand):
    logo = v(brand, "assets.logo")
    assert logo["mark"] == "phoenix" and logo["wordmark"] is True and logo["files_supplied"] is False
    assert v(brand, "voice.emoji") == "none"
    assert v(brand, "voice.people_words") == ["members", "our people", "the movement", "the collective"]
    assert {"transformation", "transformative", "journey"} == set(v(brand, "voice.words_ok"))
    assert {"NUMA", "credits", "Explore Numa", "Discover Pass", "cheap", "heal", "treats", "cures"} == set(
        v(brand, "voice.words_never"))
    assert "quote cards" in v(brand, "voice.dislikes") and "\"optimized\" talk" in v(brand, "voice.dislikes")
    assert v(brand, "voice.voiceover_by") == "Scott Moore"
    assert v(brand, "voice.clone_allowed") is False and v(brand, "consent.voice_clone") is False
    gen = brand["voice"]["generic_ai_allowed"]
    assert gen["value"] is None and gen["status"] == "needs_katie"


def test_every_never_word_is_flagged():
    for word in ("NUMA", "credits", "Explore Numa", "Discover Pass", "cheap", "heal", "treats", "cures"):
        text = f"Come in: {word} today." if word != "treats" else "Red light treats acne."
        assert any(h.severity == "fail" for h in cs.scan_text(text)), word


# --------------------------------------------------------------------------- claims
def test_owner_confirmed_claims_in_policy(brand):
    ids = {r["id"] for r in brand["claims"]["banned"]}
    assert {"name_casing", "wrong_offer_name", "credits_word", "cheap_word", "no_emoji", "newbie_code", "half_off",
            "sauna_capacity", "cancelled_event", "plunge_temp_34", "sauna_alcohol", "red_light_elasticity", "hsa_fsa",
            "competitor_comparison", "inflammation", "heals", "treats", "cures"} <= ids
    kinds = {r.get("kind", "claim") for r in brand["claims"]["banned"]}
    assert kinds == {"claim", "brand", "fact", "offer"}
    dl = brand["claims"]["dosing_line"]
    assert dl["blocked"] is True and dl["status"] == "blocked_source_pending" and dl["reason"] == "source pending (Scott)"


# --------------------------------------------------------------------------- posting
def test_posting_policy(brand):
    p = brand["posting"]
    assert p["human_approval_required"]["value"] is True and p["human_approval_required"]["status"] == "confirmed"
    assert p["member_yes_required"]["value"] is True
    assert p["require_approval"]["value"] is True  # the existing post-reel gate holds every post
    assert p["approver"]["value"] is None and p["approver"]["status"] == "needs_katie"
    lr = p["legal_review_done"]
    assert lr["required"] is False and lr["waived"] is True and lr["value"] is True
    assert "skip" in v(brand, "posting.legal_counsel")
    assert "Approving a legal review" not in brand["escalation"]["for"]


# --------------------------------------------------------------------------- owner priors
def test_owner_priors_for_the_strategy_engine(brand):
    pri = v(brand, "positioning.owner_priors")
    assert pri["baseline"] == {"followers": 807, "followers_as_of": "2026-08-31", "views_per_post": [400, 700]}
    assert {f["id"] for f in pri["favour"]} >= {"real_people", "collabs", "walk_out_lines"}
    assert {a["id"] for a in pri["avoid"]} >= {"graphics", "quote_cards", "posters", "hashtag_only_captions",
                                               "broken_bio_link"}
    for item in pri["favour"] + pri["avoid"]:
        assert re.fullmatch(r"[a-z_]+", item["id"]) and item["what"] and item["evidence"]
    aud = v(brand, "positioning.audience_size")
    assert aud["followers"] == 807 and aud["reach_per_post"] == [400, 700]
    assert max(p["views"] or 0 for p in v(brand, "positioning.past_best_posts")) == 13100


# --------------------------------------------------------------------------- people and consent
ALLOWED_NAMES = {"Scott Moore", "Katie Moore"}


def test_team_is_roles_only(brand):
    for m in v(brand, "team.collective"):
        assert "name" not in m or m["name"] in ALLOWED_NAMES, m
        assert m["role"]
    assert v(brand, "consent.people_file") == "STATE/people.json"
    assert v(brand, "team.on_camera")["people_file"] == "STATE/people.json"


def test_people_named_in_brand_are_only_the_cofounders(brand):
    """Every 'name' field in brand.json that names a person is a co-founder."""
    def walk(node):
        if isinstance(node, dict):
            for k, val in node.items():
                if k == "name" and isinstance(val, str) and re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", val):
                    yield val
                yield from walk(val)
        elif isinstance(node, list):
            for x in node:
                yield from walk(x)
    people = set(walk({k: brand[k] for k in ("business", "team", "consent", "posting", "voice")}))
    assert people <= ALLOWED_NAMES, people


def test_never_film_kids_and_consent(brand):
    nf = v(brand, "consent.never_film")
    assert len(nf) == 3 and any("counseling" in z for z in nf) and any("locker" in z for z in nf)
    assert any("kitchen" in z for z in nf)
    kids = brand["consent"]["children"]
    assert kids["value"] == "never" and kids["status"] == "needs_katie"
    assert v(brand, "consent.ai_processing_covered") is False
    assert "Doc 04" in v(brand, "consent.release_form")


def test_people_schema_and_placeholder_example(nc, repo_root):
    ex = json.loads((repo_root / "docs" / "examples" / "people.example.json").read_text(encoding="utf-8"))
    assert nc.schema_errors("people.schema.json", ex) == []
    for person in ex["people"]:
        assert re.fullmatch(r"(Founder|Instructor|Staff|Provider|Member|Child) [A-Z]", person["name"]), person["name"]
    bad = dict(ex, people=[dict(ex["people"][0], kind="celebrity")])
    assert any("kind" in e for e in nc.schema_errors("people.schema.json", bad))
    for key in ("lead_member_stories_with", "cleared_for_one_existing_post_only", "do_not_feature"):
        assert set(ex["rules"][key]) <= {p["id"] for p in ex["people"]}


def test_no_real_people_file_in_the_repo(repo_root):
    found = [p for p in repo_root.rglob("people*.json") if ".git" not in p.parts and not p.name.endswith(".schema.json")]
    assert {p.relative_to(repo_root).as_posix() for p in found} == {"docs/examples/people.example.json"}
    gi = (repo_root / ".gitignore").read_text(encoding="utf-8").split()
    assert "STATE/" in gi and "people.json" in gi


# --------------------------------------------------------------------------- docs
def test_questions_doc_marks_answers_and_open_items(repo_root):
    t = (repo_root / "docs" / "QUESTIONS_FOR_KATIE.md").read_text(encoding="utf-8")
    assert t.count("_Answer (2026-11-13):_") == 51
    assert "## Still open" in t and "## Open questions from the plugin" in t
    for owner in ("Katie", "Scott and Katie", "Scott", "Emma", "Emma or Jodie"):
        assert f"| {owner} |" in t, owner
    for needle in ("`posting.approver`", "`voice.generic_ai_allowed`", "`posting.music_source`", "`consent.log`",
                   "`fonts.brand_fonts`", "`assets.logo`", "`posting.email_tool`", "Mindbody"):
        assert needle in t, needle


def test_project_instructions_match_the_owners(repo_root):
    t = (repo_root / "docs" / "PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8")
    for needle in ("Always \"Numa\", never \"NUMA\"", "Scott records the voiceovers", "No cloned voices",
                   "Human approval before posting", "No emojis", "No quote cards",
                   "Children never appear until the owners decide", "Never film", "Emma",
                   "answered them in setup", "people.json"):
        assert needle in t, needle
    assert "legal_review_done` is true" not in t
