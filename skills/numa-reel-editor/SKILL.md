---
name: numa-reel-editor
description: The edit grammar and plan-building controller for NUMA Wellness Collective reels. Use whenever a NUMA reel's plan.json is written or changed (the Director's shot plan, the Editor's build, a Critic fix round) and whenever a NUMA reel is previewed, rendered, finished, checked or cut into extra formats. Holds the brand pointers, the exact edit rules with numbers, the claims rules, the Higgsfield summary, every script command, and the Year One worked example.
---

# NUMA Reel Editor

This skill is how a NUMA reel gets made to agency quality. `/make-reel` (the Director) decides the story; the Editor (agents/editor.md) turns it into `plan.json` with the rules below; the scripts render exactly what the plan says. Katie is never asked anything: decide, log it in `work/decisions.md`, continue.

Paths (quote them; folder names contain spaces):

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `JOB` | the reel's job folder (`raw/`, `work/`, `out/`; docs/CONTRACTS.md section 2) |
| `STATE` | `~/NUMA Studio/_Plan` (preferences, ledger, consent list, media library) |
| `SLUG` | `meta.slug` in the plan, else the slugified day folder name |

Every number below that also lives in config/studio.json `render` or brand/brand.json is quoted as an example; the file wins if they differ.

## 1. Brand pointers (brand/brand.json)

Read brand.json before writing a single line. Facts carry a `status`: prefer `confirmed`; never state a `needs_katie` value as fact (leave it out instead).

| Need | Key |
|---|---|
| Name and spelling (always "NUMA" on screen; "Numa Nights" and the iOS app keep theirs) | `business.name` |
| Address, area, facility (14-person Finnish sauna, 4 plunge tubs) | `business.location`, `business.facility` |
| Prices and offers (Discover NUMA, $49 one month) | `offerings.offers`, `offerings.sessions` |
| Never show or imply (IV drips, cryotherapy, compression boots, float tanks, reformer Pilates) | `offerings.not_offered` |
| Voice, reference lines, share line example | `voice.description`, `voice.reference_lines`, `voice.share_line_example` |
| Team names and titles | `team.collective` |
| Series | `positioning.series` |
| Wordmark, phoenix mark, ripple end-card image, brand photos | `assets.wordmark`, `assets.secondary_mark`, `assets.endcard_background`, `assets.brand_photos_dir` |
| Colours (caption gold #F7D6A0, cedar ember, water teal, cream) | `palette.value`, `palette.roles` |
| Caption fonts | `fonts.value` |
| End-card tagline and sign-off | `endcard.tagline`, `endcard.default_subtitle`, `endcard.signoff_examples` |
| Claims, safety line, dosing line | `claims.banned`, `claims.modalities`, `claims.rules`, `claims.safety_line`, `claims.dosing_line` |
| Consent | `consent.list`, `consent.ai_processing_covered`, `consent.children`, `consent.voice_clone` |
| Music and AI-label rules | `posting.music_rule`, `posting.ai_label_rule` |

## 2. Research rules (Nov 2026) the plan must serve

1. **Ranking:** watch time, sends per reach and likes per reach matter most. Sends reach new people, so most scripts end with a share line ("Send this to the friend who needs a reset", `voice.share_line_example`). The Editor keeps that line on screen as a caption and gives it a 4-beat hold.
2. **Length is set by the script, not the material** (config `render.length_s`): growth reels 45-60 s, atmosphere and announcements 15-30 s, main reel 15-60 s, never over 180 s. Voiceover runs about 2.3 words a second (`render.words_per_second`): a 45 s reel is about 100 spoken words and 10-14 shots. The shoot card asks for that much material.
3. **Sound-off:** every reel works muted. The hook is on screen as text from frame zero, captions carry every spoken word, and the payoff is visible (a face, a reveal), not only spoken.
4. **Skip rate:** about 65% of small-account viewers skip in 3 s. Frame zero needs movement, a contrast visual and full-opacity hook text.
5. **Originals only.** Other people's content only as collab posts. New hooks get tested as Trial Reels (section 6.9).
6. **Cadence (month planning):** 4-5 feed posts a week, about two-thirds Reels and one-third carousels, daily Stories, 1-2 Trial Reels a week, never a week dark; judge each reel at 72 hours.
7. **Music:** NUMA posts as a business, so trending and popular songs are never used. Order (REQUIREMENTS interpretation 8): the folder's own file, then the Music Library track the shoot card names, then a Higgsfield instrumental made to the reel's exact length and tempo, then a Music Library track by mood, then natural clip sound with the offline pad. Meta's Sound Collection is added only at posting time (`music.source: sound_collection`). A commercial-library track needs a license that names social media. Every source is recorded and lands in `out/sources.txt`; for NUMA's own file in the folder:
   ```
   python3 "$S/sources.py" add "$JOB" --kind music --path "$JOB/raw/music.mp3" --source "NUMA reel folder" --license numa_owned
   ```
   (Higgsfield music: `--source "Higgsfield ElevenLabs Music v2.5" --license higgsfield_paid`; Sound Collection: `--license meta_sound_collection`.)

## 3. Claims rules (brand.json `claims`)

Sell the experience, never the outcome. The FTC judges the overall impression: voiceover, on-screen text, visuals, caption, hashtags, pinned comment and the linked page.

- "May help", "studies suggest" and disclaimers like #notmedicaladvice do not fix a claim; "science-backed" and "clinically proven" make it worse. Rewrite to experience language instead.
- `claims_scan.py` checks every text (section 7); the validator runs the same list on the plan (rule 27). A `fail` hit never ships; a `warn` hit is reworded or kept with a logged reason.

| Modality | Say | Never say |
|---|---|---|
| Cold plunge | "Three minutes of cold. Walk out wide awake." · "A challenge that leaves many people feeling energized." · "Pairs well with the sauna for contrast." | Reduces inflammation · boosts immunity · burns fat · heals injuries · treats depression |
| Sauna | "Deep, quiet heat to unwind." · "A centuries-old Finnish ritual." · "Relax, breathe, disconnect." | Detox or sweat out toxins · burns calories · lowers blood pressure · prevents heart disease or dementia |
| Red light | Accurate device facts ("our panels use 660 nm and 850 nm light") only when `claims.modalities.red_light.device_facts` confirms them · "A warm, calming session" | Anti-aging, wrinkles, collagen · heals or reduces inflammation · "FDA-approved" · "FDA-cleared" unless it names the exact device and its exact cleared use |
| Breathwork | "Guided breathing to help you slow down." · "Feel more centered." · "Learn techniques people use to relax." | Cures anxiety · treats depression · heals trauma · boosts immunity · "breathwork therapy" from anyone not licensed for it |

Rules beyond words (`claims.rules`):
1. **Visuals count:** no limping-in, jogging-out stories; no before/after of bodies, skin or bloodwork. A before/after wipe is for buildings and rooms only.
2. **Testimonials are NUMA's claims:** experience ("my favorite hour of the week"), never outcomes; never repost or pin a member's health claim.
3. **Ask the DPT is education only:** no booking pitch in the same reel; Katie's credential is never a promise of results.
4. **Titles:** breathwork staff are "guides" or "facilitators"; only licensed counselors talk about mental health, within scope.
5. **Safety:** cold and heat reels carry `claims.safety_line.text` as a caption line or end-card subtitle; never show breath-holding in or near water.
6. **Paid or comped creators** disclose in the video (a caption line) and in the post's first line ("#ad" or "I get free sessions"); reviews are never bought or conditioned.
7. **The dosing line** ("57 minutes of sauna and 11 of cold a week") stays out while `claims.dosing_line.blocked` is true.
8. **AI disclosure:** any AI-animated person or AI-generated scene sets `ai.people` / `ai.scenes` and `ai.label_required: true` in the plan; posting switches on Instagram's AI label.

## Step 4: The edit grammar

These rules are the product's IP. The validator enforces the ones marked (rule N) in docs/CONTRACTS.md section 5.

### 4.1 Story: one beat per line, pick an arc

- **One story beat per spoken line.** Each caption line gets its own shot (or a 2-beat run of shots), and the picture illustrates the words being said: "breathe" -> the breathwork class, "cold" -> water, "Mobile" -> the street or the building.
- **Pick one arc** before placing a shot:

| Arc | Beat sequence | Typical reels |
|---|---|---|
| Transformation | before -> struggle -> turn -> payoff -> gratitude -> logo | Year One, a first plunge, a renovation |
| Offer | problem -> modality -> feeling -> call to action | Discover NUMA $49, a new class |
| Event recap | arrival -> energy -> faces -> community -> logo | Numa Nights, Clinical Conversations |

### 4.2 The hook and the first second

1. **Open on the strongest image**, never the logo (the wordmark or phoenix mark as shot 0 is an ERROR, rule 39).
2. **Movement from frame 1:** a motion clip, a zoom (`z` start != end), a pan, or a punch. No black fade-in longer than 0.2 s (`render.hook.max_black_fade_in_s`).
3. **Hook text at full opacity in frame zero:** plan `hook` = {`text`, `t1` >= 1.5 s (default 2.0), optional `y`}. Wrap 1-2 words in `*asterisks*` for gold italic. Keep it under 8 words; it usually equals the first spoken line.
4. Shot 0 `tr` is `cut` (rule 8 errors on whip/wipe/fade/leakfade; rule 9 warns on punch/flash).

### 4.3 Rhythm

| Rule | Number | Validator |
|---|---|---|
| Every cut lands on a beat | within 1 frame at 30 fps (`analysis.json` `beats`) | rule 14 (WARN) |
| Tense or "before" sections | 2-beat cuts | |
| Emotional lines and the share line | 4-beat holds | |
| Longest shot | 4 beats, unless `peak: true` on the one emotional peak | rule 15 (WARN) |
| Music-only outro (6-8 s, default 7.5) | recap montage of the best 5-8 shots, 2 beats each; when the end card leaves only about 4 s, 3-8 shots at 2 beats (DECISIONS D15). Year One's single-beat montage in a short outro is an accepted exception, not the default | |
| End card | holds 3.5-5 s and starts on a shot boundary | rules 31-32 |
| Shortest shot | 0.3 s | rule 3 (WARN) |

### 4.4 Matching and the signature moment

- The picture on screen illustrates the word being said at that moment ("breathe" -> breathwork); a cut lands where the line changes subject.
- Exactly one signature moment per reel:
  - A true before and after of the same subject (building, room) exists: a `wipe` from the before shot to the after shot. Set `signature` = {`type`: `wipe`, `t`: the after shot's `t0`}.
  - Otherwise: a white `flash` reveal on the reel's biggest line, `signature` = {`type`: `flash`, `t`}.
- Never two wipes; the end card's flash does not count (rule 18).

### 4.5 Transitions (`tr` is the transition into the shot)

| `tr` | What it does | Use for | Limit |
|---|---|---|---|
| `punch` | Hard cut; new shot starts 16% zoomed and snaps back over 0.22 s with a brief white lift | The default beat cut | |
| `whip` | Both shots slide sideways over 0.28 s with horizontal motion blur up to 160 px | Energy | At most every third cut (rule 16) |
| `leakfade` | 0.5 s crossfade under a warm light leak (added automatically) | Emotional shifts, the turn | |
| `flash` | White flash decaying over 0.35 s | Reveals and the end card | |
| `wipe` | Soft-edged glowing vertical line sweeps left to right over 1 s | The before/after signature only | One per reel |
| `cut` | Plain cut | The very first shot | |
| `fade` | Plain 0.5 s crossfade | Rarely; prefer `leakfade` | |

More than 6 shots need at least 3 transition types (rule 17): varied, never random.

### 4.6 Motion and framing

- **Every shot moves.** Alternate zoom in and zoom out: in `z: [1.02, 1.14]`, out `z: [1.15, 1.03]`. `z` stays in 0.95-1.5 (rule 10); `z[0] == z[1]` is a static shot (rule 11 WARN).
- **Pan** (`pan: [x, y]`, fraction of the frame, typically 0.02-0.03) adds drift; wide and landscape photos pan across so they fill the vertical frame. Never black bars or mirrored edges; blurred fill is the last resort (failure row F4: outpaint first, section 5).
- **Smart framing:** `vision.py` writes each item's `focus` (subject point) and `faces` into analysis.json; `baseline_plan.py` copies them into the shots. When you change a shot's `src`, copy `focus` and `faces` from that item (from the prepared copy when `prepared_path` is set). Zoom and pan centre on `focus`, so a face stays in frame. `faces`/`focus` describe the shot source (the prepared copy when `prepared_path` is set; `orig_faces`/`orig_focus` describe the original, CONTRACTS section 3). An item with non-empty `orig_faces` but empty `faces` had a face pushed out of the prepared copy by the stabilize zoom: LOOK at that shot in the preview before using it (a half-cut face at the edge still needs consent or `blur`, and may need the original `path` instead).
- `crop` [left, top, right, bottom] in source pixels removes black borders or a distracting edge (images only, rule 13). For a photo with black bars, crop to the box of pixels brighter than 18.

### 4.7 Colour looks

| `look` | What it does | Use for |
|---|---|---|
| `before` | 55% saturation, cool shift, lifted blacks | Anything "before" or struggling, up to the turn |
| `warm` | Slightly richer saturation, warm shift, gentle S-curve | Everything after the turning point (the default) |
| `none` | Ungraded | The end-card ripple background |

Every frame also gets darkened edges, soft bloom on highlights, light seeded grain and the bottom gradient (engine, automatic). Light leaks: 4-8 `leaks` entries `[time, duration, strength]` at key transitions, strength 0.3-0.45 (above 0.6 warns, rule 33).

### 4.8 Captions (`lines`)

| Rule | Number |
|---|---|
| Every spoken word, timed to `analysis.json` `words[].appear` | caption vs transcript within 0.15 s (rule 24) |
| Each word fades in and rises 22 px over 0.28 s | `render.captions` |
| Serif, about 92 px, white; 1-2 key words per line gold italic (#F7D6A0) | third element `1` on the word |
| One sentence per line, at most 2 rows | 3 rows is an ERROR (rule 22); over 80 characters warns (rule 23) |
| Line `end` about 0.15 s before the next line's first word | no overlap (rule 21) |
| Out of the top 12% and bottom 10% | `caption_y` default 1420; rows inside 230-1728 px (rule 25) |
| Off faces | move `caption_y` within 1300-1500, or higher, when a face sits at caption height (rule 26) |

Every caption and the hook get a soft shadow, over the subtle dark gradient at the bottom of the frame (engine, automatic). No emojis in burned-in text.

### 4.9 Audio

- Voice clear but not in-your-face; music ducks under the voice and comes up for the outro (analyze.py mixes; finish.py masters to -15 LUFS, 48 kHz AAC, always).
- Add `--clean-voice` to finish.py when the voice is already distant or studio-clean (no room tone).
- **Natural sound (`nat`):** short bursts of a clip's own sound (a splash, the sauna door, laughter) under the music. Take candidates from `analysis.json` `audio.clip_audio[].peaks` (clip time): `{"src": "<clip>", "start": 3.1, "t": 12.4, "dur": 0.8, "gain_db": -6}`. 0.4-1.2 s each, 1-3 per reel, on the shot that shows that clip; finish.py ducks them under the voice.
- Record the music in `music` = {`source`, `path`, `license`, `title`} (required in v2, rule 29).

### 4.10 End card

The last shot is the ripple image (`assets.endcard_background`, `look: none`, `tr: flash`, slow zoom). `endcard` = {`t` (= that shot's `t0`), `tagline` (default `endcard.tagline`), `subtitle`}: a gold italic sign-off written for this reel in NUMA's voice ("Year one. Thank you, Mobile."). The wordmark renders white. Holds 3.5-5 s.

## Step 5: Higgsfield (the motion agent does the work)

The motion agent (agents/motion.md) owns prompts, models, inspection, re-rolls and the ledger; the Director picks 2-3 hero stills per reel (config `higgsfield.clips_per_reel`, 4 max). Ranked by impact per credit (prices: config `higgsfield.prices`, re-checked with the connector's `get_cost` before every job):

1. Outpaint every landscape photo to 9:16 (2 credits); extend only walls, floor, sky or background.
2. Upscale weak phone photos to 2K (2) before any motion.
3. Kling 3.0 motion for 2-3 hero stills: draft at standard 720p (7.5), finalize only the keeper at pro (8.75).
4. Real-room moves from start + end frames (two real photos of the same room); also the AI before/after of a building.
5. People: Kling 3.0 with the person bound as an Element, consent list only, medium shot, one simple action, under 8 s, hands low and still.
6. Custom instrumental music to the exact length and tempo (about 6).
7. Voice fallback (0.5 a line): a preset voice, or Katie's clone only when `consent.voice_clone` is true.
8. Seedance 2.5 for people-free spaces only (35 at 720p); long empty-room walkthroughs up to 30 s.
9. Logos and signs: frontal, slow move; the engine overlays the real wordmark on the end card.
10. Motion transfer (Genjutsu or Kling Motion Control) for trend formats on NUMA's own material.
11. Virality predictor on the final cut and hook variants: a second opinion for the Critic, never a gate.
12. Marketing Studio ad variants: not built (DECISIONS D5; only if NUMA runs ads).

**Prompt rules:** describe the motion, not the room; one camera move per clip with a size ("about ten percent"); end with a keep clause; prototype at 720p and change one thing per retry. Safe moves: small push-ins, pull-backs, short lateral slides. Risky: crane or vertical moves, orbits, anything that reveals space outside the photo. Kling order: scene, Element, camera, action timing, lighting, audio ("no music, no dialogue"), locks. The full prompt library is in agents/motion.md.

**Budget** (config `budget`): 1,200 credits a month, split Kling 600 / Seedance 140 / photo prep 160 / music 120 / voice 10 / reserve 170; at most 55% spent by day 15; at most 150 per reel; never buy credits. Credits reset monthly; failed generations are usually refunded, unwanted ones are not, so draft cheap and finalize only keepers. Never use Reframe (245 credits): the engine and formats.py crop for free.

**Privacy:** only the chosen hero photos are uploaded; no member face goes to Higgsfield unless `consent.ai_processing_covered` is true and the person is on the Consent List.

In the plan, an approved clip is a `kind: video` shot with `ai_generated: true`; set `ai.scenes` (and `ai.people` for a person) and `ai.label_required: true` (rule 30).

## Step 6: Build the plan (numbered, every run)

1. **Read the feedback memory** and honour every note (R277); skip `prefs.py list` while `STATE/preferences.json` does not exist yet:
   ```
   python3 "$S/prefs.py" list --file "$STATE/preferences.json" --json
   ```
   Numeric limits (for example `max_whips`) are applied by passing `--prefs "$STATE/preferences.json"` to baseline and validate (omit it while the file does not exist). Notes no rule understands ("more people shots") are honoured by judgment.
2. **Prepare weak media** when vision flags an item `shaky` or `dark` (the analyst runs the auto pass; force it for one item when a shot still looks bad):
   ```
   python3 "$S/prep_media.py" "$JOB/work/analysis.json" --ids C2 --stabilize on --brighten on --json
   ```
   Use the item's `prepared_path` as the shot `src`.
3. **Start from the baseline** (valid, beat-synced, smart-framed, music filled in):
   ```
   python3 "$S/baseline_plan.py" "$JOB/work" --hook "This is what Katie saw." --duration 39 --before P0 --after P10 --turn 6.2 --prefs "$STATE/preferences.json"
   ```
   `--before/--after/--turn` only for a true before/after pair; `--script "$JOB/work/script.txt"` for a music-only reel (the script goes on screen at about 2.3 words a second); `--subtitle` for the sign-off.
4. **Improve it by judgment**, shot by shot, against Step 4: the arc, the strongest image first, the picture matching each line, video shots starting at the clip's best window (`clips[].windows` and per-second `scores` from vision.py, best first), 2-beat "before" cuts and 4-beat holds, the one signature moment, varied transitions, alternating zooms, looks switching at the turn, 1-2 gold words per line, `nat` bursts, the outro montage of the best shots, the end card sign-off. Mark notes with `_why` keys (ignored by the engine). Fill:
   - `people: true` + `consent: true` on a shot only after checking `STATE/consent_list.json`; a recognizable person not on the list is blurred (`blur: [[x, y, w, h]]`, normalized source box around each non-consented person, failure row F12) or the shot is replaced;
   - `music`, `ai`, `meta` (`slug`, `title`, `series`, `pillar`, `hook_type`, `goal`, `day`);
   - `formats`: `reach_cut` {t0, t1, hook} (8-12 s, the best stretch with a new hook), 3-5 `story` frames with one line each, 5-8 `carousel` slides, `cover` {t, title}, 2-3 `hook_variants` {text, src?, start?}.
5. **Validate** (0 ERRORs before any render; fix WARNs unless the plan needs them, and log why):
   ```
   python3 "$S/validate_plan.py" "$JOB/work/plan.json" "$JOB/work/analysis.json" --prefs "$STATE/preferences.json"
   ```
6. **Preview** frame 0, 0.5 s, each cut zone, the signature, a caption mid-fade and the end card:
   ```
   python3 "$S/engine.py" "$JOB/work/plan.json" preview 0 0.5 2.7 6.4 14.1 14.8 21.0 30.5 35.0
   ```
7. **LOOK at `work/preview.jpg`.** Check: hook text readable in frame 0; every tile filled edge to edge (no bars, no mirrored edges); captions clear of faces and inside the safe area; the right picture on each line; the wipe or flash where planned; the end-card wordmark crisp and the sign-off readable.
8. **Fix and repeat** steps 5-7 until the preview is clean. Then render (section 7).

### 6.9 Hook variants and Trial Reels (R281)

Write 2-3 `formats.hook_variants`: a different hook text (a question, a contrast, a local hook), optionally a different first shot. formats.py renders `<slug>_hook_<N>.mp4`. The motion agent scores them with Higgsfield's virality predictor (reserve credits); the best-scoring variant becomes the Trial Reel. The score is a second opinion only.

## 7. Render, finish, check, outputs

Never two renders at once (CPU-bound). A 40 s render takes about 3-6 minutes: run it in the background and poll.

```
python3 "$S/engine.py" "$JOB/work/plan.json"
python3 "$S/finish.py" "$JOB/work" "$JOB/out/SLUG_reel.mp4" --json
python3 "$S/check_output.py" "$JOB/out/SLUG_reel.mp4" --kind reel --plan "$JOB/work/plan.json" --report "$JOB/out" --json
python3 "$S/qa_frames.py" "$JOB/out/SLUG_reel.mp4" "$JOB/work/plan.json"
```

1. **LOOK at `out/qa_strip.jpg`** (6 frames) and `out/critic_frames/` (12 frames: first second, every cut, last second). Anything off: fix plan.json, validate, re-render.
2. check_output must exit 0: 1080x1920, 30 fps, H.264 High, AAC 48 kHz stereo, -15 LUFS +/- 1, true peak <= -1.5 dB, not silent, not clipped, no black bars, no frozen frame, 15-60 s.
3. A quick revision draft: `engine.py ... --draft` (half size, fast preset); finish it with `--video "$JOB/work/video_noaudio_draft.mp4"`. Never ship a draft unless failure row F14 says so.

After the Critic passes, all outputs come from the same plan (crops in the engine, never Higgsfield Reframe):
```
python3 "$S/formats.py" "$JOB/work/plan.json" "$JOB/out/SLUG_reel.mp4" --out "$JOB/out" --json
python3 "$S/check_output.py" "$JOB/out/SLUG_reach.mp4" --kind reach --report "$JOB/out"
```
LOOK at the cover (title inside the centre square) and two carousel slides.

## 8. Worked example: Year One

`assets/example-plan-year-one-v2.json` (39 s, 108 BPM, 1 beat = 0.556 s, 26 shots). The voiceover: *This is what Katie saw. / I don't know how she does it, but she does. / And we took a chance. / It's been one whole year. / And now we're beginning to see. / We are so grateful for you, Mobile. / Thank you for making this year awesome. / Looking forward to so many more.* Arc: transformation.

| Time (s) | Shots | Choice | Why |
|---|---|---|---|
| 0-2.62 | 0: the old house, `before`, `z` [1.0, 1.14] + pan, `tr: cut` | Hook text "This is what Katie saw." from frame 0 (`hook.t1` 2.62) | The strongest contrast image first, moving from frame 1, hook readable muted; never the logo |
| 2.62-6.2 | 1-4: demolition, `before`, punch / whip / punch / punch, 1-2 beats each | 2-beat (and shorter) cuts | The struggle section: tense, fast, cool and washed out |
| 6.2 | 5: Katie and Scott clip, `leakfade`, `warm` from here | The turn on "And we took a chance" | An emotional shift gets the warm leak; the look switches at the turning point |
| 9.59-14.07 | 6: ribbon cutting, slow push `z` [1.0, 1.2] | A long hold on "It's been one whole year" | Emotional line: hold, don't cut |
| 14.07-16.3 | 7: flash back to the old house (`before`), 8: `wipe` to the finished exterior | `signature` {wipe, 14.63} | A true before/after of the same building exists, so the signature is the wipe, on "now we're beginning to see" |
| 16.3-30.28 | 9-17: lit sauna (flash), brand photos, whips and leakfades | One picture per line, transitions varied | The gratitude lines get people and places in Mobile; leaks at each emotional line. Note: the reference puts a whip on every second cut here, which breaks rule 16; new plans keep whips at least 3 cuts apart |
| 30.28-34.16 | 18-24: recap montage, 7 shots, one beat each, all `punch` | The music-only outro | The best shots again, fast; only about 4 s remain before the end card, so single beats: an accepted exception to D15's 2 beats |
| 34.16-39.0 | 25: ripple image, `look: none`, `tr: flash` | `endcard` subtitle "Year one. Thank you, Mobile." | Holds 4.84 s (3.5-5 s rule), white wordmark, gold sign-off written for this reel |

Also in the plan: `music` (source `folder`, license recorded), `ai` all false (no AI shots, so no label), `meta.slug` "year-one", and `formats` (reach cut 14.07-25.82 s with hook "One whole year.", three Story frames, cover at 15.5 s titled "Year One").

## 9. Quality bar (before handing over)

- Frame zero grabs: movement, the strongest image, hook text. Every cut on a beat (within 1 frame).
- Captions match the spoken words exactly, spelled right (NUMA), no line over 2 rows, clear of faces and the app's interface.
- No shot repeats outside the outro montage; no bars, no mirrored edges, no frozen frame.
- Exactly one signature moment; end card 3.5-5 s.
- Voice clear, music under it, -15 LUFS, 48 kHz.
- Would a paying client post this today without notes? If not, fix it first.
