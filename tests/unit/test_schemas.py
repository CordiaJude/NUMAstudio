"""JSON Schemas (R79-R81, R151), brand.json data (R126, R144-R148, R161, R171) and config/studio.json numbers."""
from __future__ import annotations

import copy
import json
import re

import pytest
from jsonschema import Draft202012Validator

SCHEMAS = ["plan", "analysis", "brand"]


@pytest.fixture(scope="module")
def brand(repo_root):
    return json.loads((repo_root / "brand" / "brand.json").read_text())


@pytest.fixture(scope="module")
def config(repo_root):
    return json.loads((repo_root / "config" / "studio.json").read_text())


@pytest.fixture
def analysis_doc(job):
    return {
        "schema_version": 2,
        "duration": 12.5,
        "bpm": 100.0,
        "beats": [0.6, 1.2, 1.8],
        "words": [{"w": "Katie", "appear": 1.42, "end": 1.66, "p": 0.93}, {"w": "saw.", "appear": 1.7, "end": 1.9}],
        "transcript": "Katie saw.",
        "voice_present": True,
        "audio": {"voice": str(job.raw / "vo.m4a"), "music": str(job.raw / "music.mp3"), "master": str(job.work / "master.wav"),
                  "combined": False, "generated_pad": False,
                  "clip_audio": [{"id": "C0", "peaks": [1.2], "mean_db": -24.0}]},
        "photos": [{"id": "P0", "path": str(job.raw / "a.jpg"), "size": [840, 718], "faces": [[0.4, 0.2, 0.1, 0.15]], "focus": [0.45, 0.3],
                    "sharpness": 120.5, "brightness": 0.42}],
        "clips": [{"id": "C0", "path": str(job.raw / "clip.mov"), "duration": 12.4, "has_audio": True, "fps": 29.97, "size": [1080, 1920],
                   "rotation": -90, "windows": [[2.0, 6.0, 0.8]], "scores": [{"t": 0, "sharpness": 80, "motion": 0.2, "faces": 1, "score": 0.6}]}],
        "corrections": [{"index": 0, "from": "Kate", "to": "Katie", "reason": "brand_fix"}],
        "contact_sheets": {"photos": str(job.work / "contact_photos.jpg"), "clips": None},
        "warnings": [],
    }


# --------------------------------------------------------------------------- schemas themselves
@pytest.mark.parametrize("name", SCHEMAS)
def test_schema_is_valid_draft_2020_12(repo_root, name):
    schema = json.loads((repo_root / "schemas" / f"{name}.schema.json").read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_schemas_are_versioned(repo_root):
    plan = json.loads((repo_root / "schemas" / "plan.schema.json").read_text())
    analysis = json.loads((repo_root / "schemas" / "analysis.schema.json").read_text())
    brand = json.loads((repo_root / "schemas" / "brand.schema.json").read_text())
    assert plan["properties"]["schema_version"]["enum"] == [1, 2]
    assert analysis["properties"]["schema_version"] == {"const": 2} and "schema_version" in analysis["required"]
    assert brand["properties"]["schema_version"] == {"const": 2}


# --------------------------------------------------------------------------- plan
def test_example_plan_validates(nc, assets_dir):
    plan = nc.read_json(assets_dir / "example-plan-year-one.json")
    assert nc.schema_errors("plan", plan) == []
    assert "schema_version" not in plan  # v1-shaped plans stay valid


def test_v2_example_plan_validates(nc, assets_dir):
    plan = nc.read_json(assets_dir / "example-plan-year-one-v2.json")
    assert nc.schema_errors("plan", plan) == []
    assert plan["schema_version"] == 2
    for key in ("hook", "signature", "music", "meta", "ai", "formats"):
        assert key in plan, key
    assert plan["signature"]["type"] == "wipe"
    assert any(s["tr"] == "wipe" and abs(s["t0"] - plan["signature"]["t"]) < 1e-6 for s in plan["shots"])
    shots = plan["shots"]
    assert shots[0]["t0"] == 0 and shots[-1]["t1"] == plan["duration"]
    assert all(a["t1"] == b["t0"] for a, b in zip(shots, shots[1:]))
    # placeholder prefixes resolve: /NUMA_PLUGIN/ files exist in this checkout
    for path in (plan["font_regular"], plan["font_italic"], plan["endcard"]["logo"], shots[-1]["src"]):
        assert path.startswith("/NUMA_PLUGIN/")
        assert (nc.PLUGIN_ROOT / path[len("/NUMA_PLUGIN/"):]).is_file(), path
    srcs = [s["src"] for s in shots]
    assert all(p.startswith(("/YEAR_ONE_PACK/", "/NUMA_PLUGIN/")) for p in srcs)


def test_full_v2_plan_validates(nc, plan_factory, job):
    clip = str(job.raw / "clip.mp4")
    plan = plan_factory(
        signature={"type": "flash", "t": 5.4},
        nat=[{"src": clip, "start": 1.0, "t": 3.2, "dur": 0.8, "gain_db": -8}],
        music={"source": "higgsfield", "path": str(job.raw / "music.mp3"), "license": "Higgsfield Plus commercial use", "title": "Calm bed"},
        ai={"people": False, "scenes": True, "label_required": True},
        template="modality_explainer",
        formats={
            "reach_cut": {"t0": 0.0, "t1": 9.0, "hook": "Walk out wide awake."},
            "story": [{"t": 1.0, "text": "One"}, {"t": 4.0, "text": "Two", "clip": True}, {"t": 6.0, "text": "Three"}],
            "carousel": [{"t": float(i), "text": f"Slide {i}"} for i in range(4)] + [{"src": clip, "text": "From a photo"}],
            "cover": {"t": 1.2, "title": "Your first plunge"},
            "hook_variants": [{"text": "Everyone hates the cold."}, {"text": "Three minutes.", "src": clip, "start": 0.5}],
        },
        _notes="free-form notes are allowed",
    )
    plan["shots"][1].update({"kind": "video", "src": clip, "start": 2.0, "speed": 1.0, "focus": [0.5, 0.4],
                             "faces": [[0.4, 0.3, 0.1, 0.12]], "peak": True, "people": True, "consent": True,
                             "ai_generated": False, "_why": "hero clip"})
    assert nc.schema_errors("plan", plan) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda p: p["shots"][0].update(tr="zoom"), "shots[0].tr: 'zoom' is not one of"),
    (lambda p: p["shots"][0].update(look="cold"), "shots[0].look: 'cold' is not one of"),
    (lambda p: p["shots"][0].update(z=[1.0]), "shots[0].z: must have at least 2 items"),
    (lambda p: p["shots"][0].update(z=[1.0, 1.1, 1.2]), "shots[0].z: must have at most 2 items"),
    (lambda p: p["shots"][0].update(kind="gif"), "shots[0].kind:"),
    (lambda p: p["shots"][0].update(focus=[1.5, 0.5]), "shots[0].focus[0]: must be <= 1"),
    (lambda p: p["shots"][0].update(zoom=[1, 1.1]), "shots[0]: unknown field 'zoom'"),
    (lambda p: p["shots"][0].update(stabilize=True), "shots[0]: unknown field 'stabilize'"),
    (lambda p: p["shots"][0].pop("t1"), "shots[0]: missing required field 't1'"),
    (lambda p: p["lines"][0]["words"].append(["solo"]), "lines[0].words[4]: must have at least 2 items"),
    (lambda p: p["lines"][0]["words"].append(["x", 1.0, 2]), "lines[0].words[4][2]: 2 is not one of"),
    (lambda p: p["lines"][0]["words"].append(["x", "1.0"]), "lines[0].words[4][1]: must be number"),
    (lambda p: p["lines"][0]["words"].append(["x", 1.0, 1, 0]), "lines[0].words[4]: must have at most 3 items"),
    (lambda p: p["lines"][0].pop("end"), "lines[0]: missing required field 'end'"),
    (lambda p: p.update(leaks=[[1.0, 0.5, 1.4]]), "leaks[0][2]: must be <= 1"),
    (lambda p: p.update(leaks=[[1.0, 0.5]]), "leaks[0]: must have at least 3 items"),
    (lambda p: p.update(duration=0), "duration: must be > 0"),
    (lambda p: p.update(duration="39"), "duration: must be number"),
    (lambda p: p.update(shots=[]), "shots: must have at least 1 items"),
    (lambda p: p.update(quality="best"), "quality: 'best' is not one of"),
    (lambda p: p.update(size=[1080]), "size: must have at least 2 items"),
    (lambda p: p.update(accent_rgb=[300, 0, 0]), "accent_rgb[0]: must be <= 255"),
    (lambda p: p.update(hook={"text": "Hi", "t1": 1.0}), "hook.t1: must be >= 1.5"),
    (lambda p: p.update(signature={"type": "whip", "t": 3}), "signature.type: 'whip' is not one of"),
    (lambda p: p.update(music={"source": "spotify"}), "music.source: 'spotify' is not one of"),
    (lambda p: p.update(nat=[{"src": "/a.mp4", "start": 0, "t": 1}]), "nat[0]: missing required field 'dur'"),
    (lambda p: p.update(formats={"story": [{"t": 1, "text": "a"}]}), "formats.story: must have at least 3 items"),
    (lambda p: p.update(formats={"carousel": [{"t": 1, "src": "/a.jpg", "text": "x"}] * 5}), "formats.carousel[0]:"),
    (lambda p: p.update(schema_version=3), "schema_version: 3 is not one of"),
    (lambda p: p.update(meta={"slug": "Bad Slug"}), "meta.slug: 'Bad Slug' does not match"),
    (lambda p: p.update(endcard={"logo": "/x.png"}), "endcard: missing required field 't'"),
])
def test_malformed_plans_rejected_with_readable_errors(nc, plan_factory, mutate, expected):
    plan = plan_factory()
    mutate(plan)
    errs = nc.schema_errors("plan", plan)
    assert any(e.startswith(expected) for e in errs), errs


def test_plan_enums_match_spec(repo_root):
    schema = json.loads((repo_root / "schemas" / "plan.schema.json").read_text())
    shot = schema["$defs"]["shot"]["properties"]
    assert shot["look"]["enum"] == ["before", "warm", "none"]
    assert shot["tr"]["enum"] == ["cut", "punch", "whip", "leakfade", "fade", "flash", "wipe"]
    for field in ("duration", "out_dir", "fps", "accent_rgb", "caption_y", "shots", "lines", "leaks", "endcard"):
        assert field in schema["properties"], field
    for field in ("kind", "src", "start", "speed", "look", "t0", "t1", "z", "pan", "tr", "crop"):
        assert field in shot, field


# --------------------------------------------------------------------------- analysis
def test_analysis_document_validates(nc, analysis_doc):
    assert nc.schema_errors("analysis", analysis_doc) == []
    music_only = dict(analysis_doc, words=[], transcript="", voice_present=False,
                      audio={"voice": None, "music": "/m.mp3", "master": "/w/master.wav"})
    assert nc.schema_errors("analysis", music_only) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda a: a.pop("voice_present"), "(top level): missing required field 'voice_present'"),
    (lambda a: a.pop("schema_version"), "(top level): missing required field 'schema_version'"),
    (lambda a: a["clips"][0].pop("has_audio"), "clips[0]: missing required field 'has_audio'"),
    (lambda a: a["clips"][0].update(id="clip1"), "clips[0].id: 'clip1' does not match"),
    (lambda a: a["clips"][0].update(windows=[[1, 2]]), "clips[0].windows[0]: must have at least 3 items"),
    (lambda a: a["words"][0].update(p=1.5), "words[0].p: must be <= 1"),
    (lambda a: a["photos"][0].update(faces=[[0.1, 0.2, 0.3]]), "photos[0].faces[0]: must have at least 4 items"),
    (lambda a: a["photos"][0].update(size=[840]), "photos[0].size: must have at least 2 items"),
    (lambda a: a["audio"].update(generated_pad="yes"), "audio.generated_pad: must be boolean"),
])
def test_bad_analysis_rejected(nc, analysis_doc, mutate, expected):
    mutate(analysis_doc)
    errs = nc.schema_errors("analysis", analysis_doc)
    assert any(e.startswith(expected) for e in errs), errs


# --------------------------------------------------------------------------- brand.json
def test_brand_validates(nc, brand):
    assert nc.schema_errors("brand", brand) == []
    assert brand["schema_version"] == 2


def _facts(node, path=""):
    if isinstance(node, dict):
        if "value" in node and "status" in node:
            yield path, node
        for k, v in node.items():
            yield from _facts(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _facts(v, f"{path}[{i}]")


def test_every_fact_has_a_known_status_and_unknowns_are_flagged(brand):
    statuses = {"confirmed", "from_website", "research", "needs_katie", "bundled", "generated"}
    facts = list(_facts(brand))
    assert len(facts) > 60
    for path, f in facts:
        assert f["status"] in statuses, path
        if f["value"] is None:
            assert f["status"] == "needs_katie", f"{path}: null value must be needs_katie"


def test_brand_kit_keys_r144(brand):
    assert brand["business"]["name"]["value"]["full"] == "NUMA Wellness Collective"
    assert brand["business"]["name"]["status"] == "confirmed"
    assert brand["socials"]["instagram"]["value"] == "@numawellnessmobile"
    assert {"facebook", "ios_app"} <= set(brand["socials"])
    assert brand["voice"]["description"]["status"] == "from_website"
    assert len(brand["voice"]["reference_lines"]["value"]) == 3
    assert "Discover NUMA" in [o["name"] for o in brand["offerings"]["offers"]["value"]]
    for key in ("wordmark", "secondary_mark", "endcard_background", "brand_photos_dir"):
        assert brand["assets"][key]["status"] == "bundled"
    pal = brand["palette"]["value"]
    assert (pal["cedar_ember"], pal["water_teal"], pal["cream"], pal["caption_gold"]) == ("#C8643C", "#5E8C8F", "#FAF6EE", "#F7D6A0")
    assert brand["fonts"]["value"]["family"] == "Liberation Serif"
    assert brand["endcard"]["signoff_examples"]["value"] == ["Year one. Thank you, Mobile."]


def test_brand_assets_exist(nc, brand):
    for key in ("wordmark", "secondary_mark", "endcard_background", "brand_photos_dir"):
        assert nc.plugin_path(brand["assets"][key]["value"]).exists(), key
    for key in ("caption_regular", "caption_italic", "license"):
        assert nc.plugin_path(brand["fonts"]["value"][key]).is_file(), key
    assert len(list(nc.plugin_path(brand["assets"]["brand_photos_dir"]["value"]).glob("*.jpg"))) == 6


def test_business_facts_r145(brand):
    biz = brand["business"]
    assert biz["location"]["value"]["address"] == "1719 Dauphin St, Mobile, AL 36604"
    assert biz["facility"]["value"]["cold_plunge_tubs"] == 4
    assert "14-person Finnish sauna" in biz["facility"]["value"]["sauna"]
    assert [f["name"] for f in biz["founders"]["value"]] == ["Scott Moore", "Katie Moore"]
    assert biz["booking"]["value"]["platforms"] == ["Mindbody", "the NUMA app"]
    assert biz["booking"]["value"]["trial_page"] == "https://discover.numawellness.org"
    assert biz["hours"]["value"]["summary"] == "Opens 5:30 AM Monday to Thursday"
    phone = biz["phone"]
    assert phone["value"] is None and phone["status"] == "needs_katie" and len(phone["candidates"]) == 3
    sessions = {s["name"]: s for s in brand["offerings"]["sessions"]["value"]}
    assert sessions["Free Flow"]["price"]["value"] == 30 and sessions["Free Flow"]["minutes"] == 45
    assert sessions["NUMA Experience"]["price"] == {"value": None, "status": "needs_katie"}
    assert brand["offerings"]["not_offered"]["value"] == ["IV drips", "cryotherapy", "compression boots", "float tanks", "reformer Pilates"]
    names = [m["name"] for m in brand["team"]["collective"]["value"]]
    for n in ("LaJuan Humbert", "Matt Henson", "Kandi Roemhildt", "Natalia Lichtenberger", "Fallon Gleason", "Joseph Irby"):
        assert n in names
    assert "Less Noise. More Presence." in brand["voice"]["site_lines"]["value"]


def test_positioning_r146_r161_r171(brand):
    pos = brand["positioning"]
    series = pos["series"]["value"]
    assert [s["name"] for s in series] == ["Ask the DPT", "First Plunge", "Too Hot for a DIY Plunge", "Regulate", "Meet the Collective"]
    assert all(s["what"] and s["built_for"] for s in series)
    assert series[0]["length_s"] == [45, 60] and series[3]["length_s"] == [45, 60]
    assert [p["name"] for p in pos["collab_partners"]["value"]][:3] == ["Mission Fitness", "barre3 Mobile", "Pure Barre Mobile"]
    assert len(pos["target_audiences"]["value"]) == 4
    assert sum(pos["content_mix"]["value"].values()) == pytest.approx(1.0)


def test_transcript_fixes_r148(brand):
    fixes = {f["to"]: f for f in brand["transcript_fixes"]["fixes"]}
    assert "Moby" in fixes["Mobile"]["variants"]
    assert "Numa" in fixes["NUMA"]["variants"]
    assert fixes["Katie"]["variants"] and fixes["Scott"]["variants"]
    assert fixes["Dauphin"]["next_words"]
    assert "Numa Nights" in brand["transcript_fixes"]["protect"]


def _scan(brand, text, severity="fail"):
    """The scanning contract from docs/CONTRACTS.md section 6; returns rule ids hit at `severity`."""
    claims = brand["claims"]
    for phrase in claims["allow_exact"]:
        text = text.replace(phrase, " ")
    for pat in claims.get("allow_patterns", []):
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)
    rules = [r for r in claims["banned"] if r.get("severity", "fail") == severity]
    if severity == "fail" and claims["dosing_line"]["blocked"]:
        rules.append({"id": "dosing_line", "patterns": claims["dosing_line"]["patterns"]})
    return [r["id"] for r in rules if any(re.search(p, text, re.IGNORECASE) for p in r["patterns"])]


@pytest.mark.parametrize("text", [
    "Reduces inflammation", "boosts your immune system", "Boost immunity", "Full body detox", "sweat out toxins",
    "burns fat", "burn calories", "weight loss", "#weightloss", "heals injuries", "cures stress", "treats depression",
    "prevents illness", "relieves anxiety", "#anxietyrelief", "PTSD", "heal trauma", "arthritis", "pain relief", "#painrelief",
    "lowers blood pressure", "heart health", "#hearthealth", "anti-aging", "#antiaging", "collagen boost", "fewer wrinkles",
    "COVID recovery", "science-backed", "Clinically proven", "Studies show", "FDA-approved", "FDA cleared panels",
    "250% dopamine", "hormone levels", "breathwork therapy", "#immunityboost", "#detox",
    "57 minutes of sauna and 11 of cold a week",
    "Sauna cures stress", "treating anxiety", "heals your body", "#cureanxiety",
    "fights disease", "no more getting sick", "beat flu season", "fewer colds this winter", "ward off illness", "#flushot",
    "trauma", "hormones", "depression",
])
def test_banned_claims_catch_every_spec_item(brand, text):
    assert _scan(brand, text), text


@pytest.mark.parametrize("text", [
    "Three minutes of cold. Walk out wide awake.", "A challenge that leaves many people feeling energized.",
    "Pairs well with the sauna for contrast.", "Deep, quiet heat to unwind.", "A centuries-old Finnish ritual.",
    "Relax, breathe, disconnect.", "our panels use 660 nm and 850 nm light", "A warm, calming session",
    "Guided breathing to help you slow down.", "Feel more centered.", "Learn techniques people use to relax.",
    "Find a collective rhythm in the chaos of life.", "Your reset starts here.", "Take your first deep breath.",
    "Less Noise. More Presence.", "Everyone hates the cold.", "We started Numa because we needed it.",
    "Healthcare and shift workers welcome at 5:30 AM.", "Try a month with Discover NUMA, $49. Send this to your plunge buddy.",
    "Talk to your doctor first if you have a heart, blood pressure or breathing condition.",
    "#MobileAL #MidtownMobile #GulfCoastWellness", "Year one. Thank you, Mobile.",
])
def test_brand_voice_lines_pass_the_scanner(brand, text):
    assert _scan(brand, text) == [], text


@pytest.mark.parametrize("text, warn_id", [
    ("Treat yourself to a Friday contrast session.", None),
    ("Our new Flow Space is a real treat.", None),
    ("A little treat after work.", None),
    ("Cold brew and summer treats at the front desk.", "treat_ambiguous"),
    ("The cure for Monday: three minutes of cold.", "cure_ambiguous"),
    ("Meet our neighbors at Healing Arts.", "healing_ambiguous"),
    ("Grip mats help prevent slipping.", "prevent_ambiguous"),
    ("Our guides are trauma-informed.", None),
    ("Hormone-free snacks after class.", None),
    ("Depress the button to start the circuit.", None),
    ("That first plunge was sick.", "sick_flu_ambiguous"),
])
def test_innocent_wording_never_hard_fails(brand, text, warn_id):
    assert _scan(brand, text) == [], text
    warns = _scan(brand, text, "warn")
    if warn_id:
        assert warn_id in warns, (text, warns)
    else:
        assert warns == [], (text, warns)


@pytest.mark.parametrize("text", [
    "Improves sleep", "better sleep tonight", "boost metabolism", "Boost your energy", "reduce soreness",
    "less muscle soreness", "recover faster", "faster recovery", "speeds recovery", "speed up your recovery",
    "lowers stress levels", "reduce stress", "improve circulation",
])
def test_outcome_language_warns(brand, text):
    assert "outcome_verbs" in _scan(brand, text, "warn"), text
    assert _scan(brand, text) == [], text


def test_every_claim_rule_has_a_severity(brand):
    sev = {r["id"]: r["severity"] for r in brand["claims"]["banned"]}
    assert set(sev.values()) == {"fail", "warn"}
    assert "warn" not in brand["claims"]  # unified into banned[] with severity
    for pat in brand["claims"]["allow_patterns"]:
        re.compile(pat)


def test_claims_structure(brand):
    claims = brand["claims"]
    assert set(claims["modalities"]) == {"cold_plunge", "sauna", "red_light", "breathwork"}
    assert all(r["applies_to"] == "all" for r in claims["banned"])
    assert claims["dosing_line"]["blocked"] is True and claims["dosing_line"]["status"] == "blocked_until_counsel"
    assert claims["safety_line"]["text"].startswith("Talk to your doctor first")
    assert len(claims["rules"]) == 8
    for tag in brand["captions"]["hashtags"]["never"]:
        assert _scan(brand, tag), tag
    for tag in brand["captions"]["hashtags"]["base"]:
        assert _scan(brand, tag) == [], tag


def test_consent_drive_posting_escalation(brand):
    assert brand["consent"]["list"]["location"] == "NUMA Reels/_Plan/Consent List"
    assert brand["consent"]["children"]["value"] == "never"
    assert brand["closures"]["location"] == "NUMA Reels/_Plan/Closures"
    assert brand["drive"]["plan_sheet"] == "NUMA 30-Day Reel Plan"
    assert brand["drive"]["music_library"] == "_Plan/Music Library"
    assert brand["captions"]["hashtags"]["count"] == [3, 5]
    assert brand["captions"]["hashtags"]["base"] == ["#MobileAL", "#MidtownMobile", "#GulfCoastWellness"]
    post = brand["posting"]
    assert post["auto_post"]["value"] is True and post["require_approval"]["value"] is False
    assert post["legal_review_done"]["value"] is False
    assert brand["escalation"]["contact"] == "Jude Moore" and len(brand["escalation"]["for"]) == 3


def test_brand_schema_rejects_bad_status(nc, brand):
    bad = copy.deepcopy(brand)
    bad["business"]["phone"]["status"] = "placeholder"
    errs = nc.schema_errors("brand", bad)
    assert any(e.startswith("business.phone.status: 'placeholder' is not one of") for e in errs), errs


# --------------------------------------------------------------------------- config/studio.json
def test_config_sections_cite_sources(config):
    for key, section in config.items():
        if key.startswith("_") or key == "schema_version":
            continue
        assert "_source" in section, f"{key} has no _source"
        assert "spec p." in section["_source"] or "default" in section["_source"], key


def test_config_models(config, repo_root):
    agents = config["models"]["agents"]
    assert agents["director"] == agents["critic"] == "opus"
    for a in ("motion", "editor", "analyst", "scriptwriter", "scout"):
        assert agents[a] == "sonnet", a
    assert agents["librarian"] == agents["copywriter"] == "haiku"
    assert set(agents.values()) <= set(config["models"]["tiers"].values())


def test_config_higgsfield_and_budget(config):
    prices = {p["id"]: p["credits"] for p in config["higgsfield"]["prices"]}
    assert prices == {"kling_std_5s": 7.5, "kling_pro_5s": 8.75, "kling_pro_10s": 17.5, "seedance_720p_5s": 35,
                      "seedance_1080p_5s": 80, "outpaint_9x16": 2, "upscale_2k": 2, "music_40s": 5.82,
                      "voice_line": 0.5, "reframe_20s_1080p": 245}
    ids = set(prices)
    for d in config["higgsfield"]["defaults"].values():
        assert d["price_id"] in ids
    assert config["higgsfield"]["defaults"]["motion"]["model"] == "Kling 3.0"
    assert config["higgsfield"]["defaults"]["motion"]["quality"] == "pro"
    assert config["higgsfield"]["defaults"]["signature_people_free"]["model"] == "Seedance 2.5"
    budget = config["budget"]
    split = {k: v["credits"] for k, v in budget["split"].items()}
    assert split == {"kling_motion": 600, "seedance_people_free": 140, "photo_prep": 160, "music": 120, "voice": 10, "reserve": 170}
    assert sum(split.values()) == budget["monthly_credits"] == 1200
    assert budget["pacing"] == {"by_day": 15, "max_fraction_spent": 0.55, "rule": budget["pacing"]["rule"]}
    assert budget["max_credits_per_reel"] == 150


def test_config_critic(config):
    rubric = config["critic"]["rubric"]
    assert sum(r["weight"] for r in rubric) == 100
    assert {r["id"]: r["weight"] for r in rubric}["hook"] == 20
    assert config["critic"]["pass"] == {"min_total": 80, "min_category_score": 3, "min_hook_score": 4}
    assert config["critic"]["max_rounds"] == 3 and len(config["critic"]["hard_gates"]) == 7


def test_config_render(config):
    r = config["render"]
    assert r["fps"] == 30 and r["size"] == [1080, 1920]
    assert r["captions"]["font_px"] == 92
    assert r["safe_area"]["top_fraction"] == 0.12 and r["safe_area"]["bottom_fraction"] == 0.10
    assert r["video"]["maxrate"] == "14M" and r["video"]["pix_fmt"] == "yuv420p" and r["video"]["profile"] == "high"
    assert r["audio"] == {"codec": "aac", "bitrate": "192k", "sample_rate": 48000, "channels": 2}
    assert r["loudness"]["integrated_lufs"] == -15 and r["loudness"]["true_peak_db"] == -1.5
    assert r["loudness"]["mean_level_warn_db"] == -28
    assert r["hook"]["min_visible_s"] == 1.5 and r["length_s"]["hard_max"] == 180


def test_config_schedule(config):
    sched = config["schedule"]
    assert sched["timezone"] == "America/Chicago"
    crons = {t["id"]: t["cron"] for t in sched["tasks"]}
    assert crons == {"plan_month": "0 21 24 * *", "night_check": "0 20 * * *", "build_today": "0 5 * * *",
                     "dashboard_refresh": "0 22 * * *", "trend_check": "0 19 * * 5", "digest": "0 18 * * 0"}


def test_config_instagram_and_formats(config):
    ig = config["instagram"]
    assert ig["graph_api_version"] == "v26.0"
    assert ig["tools"]["media_insights"] == "INSTAGRAM_GET_IG_MEDIA_INSIGHTS"
    assert ig["tools"]["publish_media"] == "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH"
    assert ig["insight_pulls_hours"] == [48, 72, 168]
    assert set(ig["never_request"]) == {"plays", "impressions"}
    assert not set(ig["never_request"]) & set(ig["metrics"])
    outs = {o["id"]: o for o in config["formats"]["outputs"]}
    assert outs["carousel"]["size"] == [1080, 1350] and outs["carousel"]["count"] == [5, 8]
    assert outs["story"]["count"] == [3, 5] and outs["reach"]["length_s"] == [8, 12]
    assert outs["cover"]["size"] == [1080, 1920]
