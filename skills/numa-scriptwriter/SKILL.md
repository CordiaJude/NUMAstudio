---
name: numa-scriptwriter
description: Pre-production for NUMA Wellness Collective reels - hook, voiceover script timed to length, shot list tied to script lines, photos, audio direction, on-screen text and CTA, draft caption, and the one-page SHOOT CARD Katie films from. Powers /plan-month (all cards in one pass), rewrites lines when material is missing, and works alone for a one-off reel ("help me plan a reel for Numa Nights"). Enforces the claims policy on every line.
---

# NUMA Scriptwriter

You plan each reel before anything is filmed, so the edit has the right material. Output: one `script.json` per reel (schemas/script.schema.json) and its SHOOT CARD, rendered by `shoot_card.py`. `S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`. Nothing here asks Katie anything: an unknown means the safe choice and a line in `notes`.

## Read first

| Need | Where |
|---|---|
| Voice: honest, grounded, warm, communal; no hype | brand.json `voice.description`, `voice.reference_lines`, `voice.site_lines` |
| Offers, prices, link | `offerings.offers`, `business.cta_link` (a price with status `needs_katie` is never stated) |
| Series and what each is for | `positioning.series` |
| People: the collective, who may be on camera | `team.collective`, `team.on_camera` |
| Collab partners (in order) | `positioning.collab_partners` |
| Claims policy | `claims.banned`, `claims.modalities`, `claims.rules`, `claims.safety_line` |
| Timing | config `render.words_per_second` (2.3), `render.outro_music_only_s` (6-8 s, default 7.5), `render.length_s` |
| Templates and presets | `skills/numa-scriptwriter/templates.json` |
| Feedback memory | `python3 "$S/prefs.py" list --file "$STATE/preferences.json" --json` |

## What each reel gets (spec p.35)

1. **Hook:** the first 2 seconds, on screen in frame zero (`hook_text`) and spoken as the start of line 1. Works muted.
2. **Voiceover script** (`lines`): one short sentence per story beat, in NUMA's voice. Words in all lines <= 2.3 x (`length_s` - `outro_s`): a 30 s voiced part is about 65-70 words, then 6-8 s of music-only outro.
3. **Shot list** (`shots`): numbered, each tied to a line (`line`), with framing (wide, medium, close, overhead), hold (`seconds`, 5 by default), `people`, and exactly one `ai_motion` hero shot. Example: `3. Close-up: hand breaking the water surface of the plunge, 5 s, slow`.
4. **Photos** (`photos`): stills worth grabbing when they beat video (finished space, people mid-laugh, steam, a candle).
5. **Audio direction** (`music`): mood and tempo ("calm, warm piano", `bpm` [90, 100]) and source: `generate` (Higgsfield makes it), `library` (Music Library by mood, files named mood_bpm_title.mp3), `folder` (Katie may drop a track), `natural`. Never a trending song. Who reads (`voiceover_by`) and the recording tips, which the card prints.
6. **On-screen text and CTA** (`cta`, `on_screen`) matched to the day's goal (table below).
7. **Draft caption and hashtags** (`caption`): follow skills/numa-caption/SKILL.md for one recommended caption and 3-5 hashtags; the Copywriter finalizes on build day.

| Goal | CTA style | Example |
|---|---|---|
| education | save or send; never booking | "Save this for your first visit." |
| community | share line | "Send this to the friend who 'could never'." |
| awareness | soft, local | "Midtown Mobile. See you in there." |
| offer | the offer and its link (`business.cta_link`) | "Try a month with Discover NUMA, $49." |

## Rules

1. **Length:** growth reels 45-60 s; atmosphere and announcements 15-30 s; never over 3 minutes. Ask the DPT and Regulate run 45-60 s (`positioning.series`). Set `length_class` when it is growth or atmosphere.
2. **Hook first**, and it must be honest: a season or weather hook ("Sauna season in Mobile"), hot/cold contrast, a tease, behind the scenes, a first-timer moment, a myth ("Myth: colder is always better").
3. **One beat per line,** every shot tied to a line. Short sentences. Most reels end with a **share line** (`share_line`): a reason to send it.
4. **Card rules** (spec p.36): at most 8 new shots (`source: "new"`; library shots fill the rest of a 45-60 s reel); every shot says framing and duration; people shots are "consent list only" (`people: true` and `needs_consent: true`); one AI motion shot; the script is under the word limit; `film_by` before the reel's date; `batch_room` set.
5. **Batch-friendly:** prefer shots in the same room as the week's other cards; a shot that repeats across reels (plunge room empty, sauna glowing, the front door) is filmed once (`library_tags`) and reused later as `source: "library"`; a class or event on the calendar becomes a capture moment (`during`).
6. **Claims policy, every line (hard rule):** sell the experience, never the outcome. Good: "Three minutes of cold. Walk out wide awake." "Deep, quiet heat to unwind." Never a health, healing or results claim, never "studies show" or "science-backed", never the website's dosing line. `safety_line: true` for every cold or heat reel. `shoot_card.py script` runs claims_scan over the title, hook, every line, every shot, photos, on-screen text, CTA, share line, caption and hashtags; any `ERROR` is rewritten before the Director sees it.
7. **Ask the DPT** is education only: what research does and doesn't show, no booking pitch in the same reel, her credential never framed as a promise.
8. **Breathwork** staff are guides or facilitators; only licensed counselors talk about mental health, within their scope. Never show breath-holding in or near water.
9. **Offers:** at most one sales-focused reel a week (`sales: true`); nothing inviting on a closure day. **Collabs** are posted as collabs with the partner, never reposts.
10. **No questions to Katie.** Unknown fact: leave it out or choose the safe option, note it in `notes`.

## Templates (templates.json)

Each entry defines the arc (beats in order), beat count, typical length, signature moment, story turn, pacing, look, transitions and hook style; presets are named, fully resolved variants. Put the id in `template`; build day passes it to baseline_plan.py `--template`.

| id | Name | Beats | Length | Signature moment | Goal |
|---|---|---|---|---|---|
| `transformation` | Transformation (before/after) | 6 | 30-45 s | wipe on the turn line, same camera angle | awareness |
| `class_spotlight` | Class spotlight | 6 | 30-45 s | flash into the quiet end of class | community |
| `member_story` | Member story | 6 | 45-60 s | flash on the first-plunge moment | community |
| `modality_explainer` | Modality explainer | 7 | 45-60 s | flash into the water or steam | education |
| `offer_promo` | Offer promo | 5 | 20-30 s | flash on the first-visit line | offer |
| `event_recap` | Event recap | 6 | 20-30 s | flash on the peak moment | community |
| `event_teaser` | Event teaser | 5 | 15-25 s | flash to last time's best moment | offer |
| `behind_the_scenes` | Behind the scenes | 5 | 20-30 s | flash as the doors open | awareness |
| `founder_message` | Founder message | 6 | 45-60 s | flash from the story to the room today | awareness |
| `myth_vs_fact` | Myth vs fact (kinetic MYTH/FACT cards) | 6 | 45-60 s | flash from MYTH to FACT | education |
| `seasonal_holiday` | Seasonal or holiday post | 5 | 15-30 s | flash from outside to the plunge or sauna | awareness |
| `numa_nights_recap` | Preset: Numa Nights recap | 6 | 20-30 s | flash on the peak of the night | community |
| `class_spotlight_reel` | Preset: Class spotlight | 6 | 25-35 s | flash into the quiet end of class | community |
| `member_story_reel` | Preset: Member story (First Plunge) | 6 | 45-60 s | flash on the first seconds in the cold | community |
| `offer_promo_discover` | Preset: Offer promo, Discover NUMA | 5 | 20-30 s | flash on the first-visit line | offer |
| `education_three_things` | Preset: Education "3 things" with kinetic type | 6 | 45-60 s | flash on the first number card | education |
| `holiday_hours` | Preset: Holiday hours (kinetic type, never inviting) | 4 | 15-20 s | flash from title to hours | awareness |

Pick by the row's series and goal; the signature is a wipe only with a true before/after pair from the same angle, else a flash.

## The SHOOT CARD (what Katie reads, under a minute on a phone)

Never hand-write it: `python3 "$S/shoot_card.py" card script.json --out "SHOOT CARD.txt"`. It prints "NO FILMING NEEDED" first when the day needs nothing from her, then the header, the filing rules, the shots, the script with the recording tips, music, length, and always ends "IF YOU CAN'T: skip it.":
```
DAY 07 · Wed Dec 9 · "Your first plunge"    FILM BY: Mon Dec 7 (batch shoot: plunge room)

WHERE TO PUT FILES
  Drive > NUMA Reels > 2026-12 December > Day 07 - 2026-12-09 - Your first plunge
  Photos -> photos/   Videos -> clips/   Voice memo -> name it "voiceover 07"
  Only in this day's folder. File names don't matter; Claude sorts by content.
  Re-record: replace the voiceover file. Reading the week's scripts back to back is fine: one file per day.
  Music: optional. Drop a track here, or Claude picks from Music Library by the mood below.
  Changes: optional. Edit this day's Sheet row; nothing waits on it.

WHAT TO FILM  (phone vertical, 4K at 30 fps, hold each shot 5 seconds, don't zoom)
  [ ] 1. Close-up: a hand touching the water surface, slow, 5 s   (line 1)
  [ ] 3. Close-up: face after, eyes closed, calm, 5 s   (consent list only) (line 3)
  [ ] 5. Photo, overhead: the plunge from above   (line 4) (AI motion shot)

READ THIS OUT LOUD  (quiet room with soft surfaces like a closet or carpeted bedroom, phone 12 inches away, normal voice, one take, 1 second of silence at the start and end)
  "Three minutes. That's all it takes.
   ...

MUSIC: none needed (Claude makes it: calm, warm piano, 90-100 BPM).    LENGTH: 45 seconds (these 5 shots + reused library shots).
IF YOU CAN'T: skip it. Claude will find another way.
```

## Check before handing back

```
python3 "$S/shoot_card.py" script script.json --json
```
`"ok": true` is required: schema, words <= 2.3 x (length - outro), <= 8 new shots, exactly one AI motion shot, every shot tied to a real line with framing and seconds, people => `needs_consent`, a known template id, Ask the DPT without a pitch, and no banned claim anywhere. Reword every claims `WARN` unless it is plainly innocent.

## Modes

- **Month pass (/plan-month):** all reel rows of the plan in one pass, in date order. Keep topics distinct for 14 days, rotate the five series, group each week's new shots into the batch rooms, reuse repeat shots from earlier cards, and give the week's voiceovers to one reader where possible so they are read back to back. Check every row (`rows/day_NN.json`).
- **Missing material (night check or build day):** rewrite only the lines that lost their shot so the reel works with what exists (Scout finds, library shots, brand photos); keep the length target, keep line 1 and the hook unless the hook shot itself is gone, re-run the check, return the new script.json.
- **One-off ("help me plan a reel for Numa Nights"):** pick the template (`numa_nights_recap` for a recap, `event_teaser` before), write script.json into the day folder (or the folder you were given), render the card, and show the card text. Same rules and checks.

## Worked example (script.json, spec p.36)

```json
{"day": 7, "date": "2026-12-09", "title": "Your first plunge", "series": "first_plunge", "pillar": "community",
 "goal": "community", "template": "member_story_reel", "length_s": 45, "hook_text": "Three minutes.",
 "lines": ["Three minutes. That's all it takes.", "The first ten seconds are loud. Then it gets quiet.",
           "You come out different than you went in.", "Try a month with Discover NUMA, $49. Send this to your plunge buddy."],
 "shots": [
  {"n": 1, "line": 1, "what": "a hand touching the water surface, slow", "framing": "close", "seconds": 5, "people": false, "ai_motion": false},
  {"n": 2, "line": 2, "what": "someone stepping into the plunge, shoulders down", "framing": "medium", "seconds": 5, "people": false, "ai_motion": false},
  {"n": 3, "line": 3, "what": "face after, eyes closed, calm", "framing": "close", "seconds": 5, "people": true, "ai_motion": false},
  {"n": 4, "line": 4, "what": "the plunge room, lights on, nobody in it", "framing": "wide", "seconds": 5, "people": false, "ai_motion": false, "library_tags": ["plunge room", "empty"]},
  {"n": 5, "line": 4, "what": "the plunge from above", "framing": "overhead", "seconds": 5, "kind": "photo", "people": false, "ai_motion": true}],
 "photos": ["steam over the sauna stones"],
 "music": {"mood": "calm, warm piano", "bpm": [90, 100], "source": "generate"},
 "cta": "Try a month with Discover NUMA, $49.", "share_line": "Send this to your plunge buddy.",
 "safety_line": true, "needs_consent": true, "film_by": "2026-12-07", "batch_room": "plunge room"}
```
