# NUMA Studio requirements

Every requirement in `spec/SPEC.pdf` (text: `spec/SPEC.txt`, "NUMA Studio — Product & Engineering Brief", Nov 12 2026), split into atomic, testable items, plus implicit requirements for this project type. Scope decisions are in `DECISIONS.md` (D4: human/external steps are EXTERNAL; D5: what gets built). Status of each item against the current code is in `GAP_AUDIT.md`.

**Tags.** `CODE` deterministic Python, verified by running it. `INSTR` behaviour Claude follows, verified by the instruction being present, concrete and consistent in the right command/skill/agent file. `DATA` brand.json, schemas, config, assets, docs. `EXTERNAL` needs Katie's Mac, live connectors, funded Higgsfield or a human (D4); the acceptance names the in-repo artifact that supports it.

**Format.** `R#` `TAG` requirement. *Accept:* how a reviewer verifies it in this repo. *(spec page)*

**Totals:** 327 requirements: CODE 121, INSTR 155, DATA 39, EXTERNAL 12.

## Plugin packaging and architecture

- **R1** `DATA` Plugin manifest `.claude-plugin/plugin.json` with name `numa-studio`, semver `version`, description. *Accept:* `jq .name,.version,.description` prints all three; version matches `^\d+\.\d+\.\d+$`. *(p.12, 49)*
- **R2** `DATA` Marketplace manifest lists exactly one plugin `numa-studio` with `"source": "./"` and the same version as plugin.json. *Accept:* Test compares marketplace.json `plugins[0]` to plugin.json name/version. *(p.12)*
- **R3** `INSTR` Skills numa-reel-editor, numa-caption, numa-brand-check, numa-scriptwriter each have SKILL.md with YAML frontmatter `name` + `description`. *Accept:* Frontmatter parse test over `skills/*/SKILL.md`. *(p.12, 27)*
- **R4** `INSTR` Commands `/make-reel`, `/plan-month`, `/numa-setup` exist in `commands/` with `description` frontmatter; input commands use `$ARGUMENTS`. *Accept:* Files exist; make-reel and plan-month contain `$ARGUMENTS`. *(p.12, 27)*
- **R5** `INSTR` Each agent is a Markdown file with frontmatter `name`, `description`, `model`, and allowed `tools`. *Accept:* Frontmatter test over `agents/*.md` requires the four keys. *(p.39)*
- **R6** `INSTR` Skill files follow the controller style: say when/why, concrete numbers, a worked example, and "look at your own output" (preview/QA images) steps. *Accept:* numa-reel-editor SKILL.md contains numeric rules, the Year One worked example and preview/QA look steps. *(p.13)*
- **R7** `CODE` Every deterministic step (timing, rendering, audio, file formats, captions files, checks) lives in scripts, not prose. *Accept:* Review: no deterministic computation is delegated to prose (transcript fixes, SRT, claims scan, frame extraction are scripts). *(p.13)*
- **R8** `CODE` Scripts are callable by absolute path from any cwd and locate bundled assets relative to their own file. *Accept:* Run each script from `/` with absolute paths; succeeds. *(p.17, 27)*
- **R9** `CODE` plan.json is the only seam between creative layer and renderer; engine reads no other creative input. *Accept:* engine.py reads only plan.json (+ bundled fonts/assets); a second engine could render the same plan. *(p.15, 31)*
- **R10** `INSTR` Work-folder convention: one folder per reel with `raw/`, `analysis.json`, `plan.json`, clips, renders; files on disk are the state. *Accept:* SKILL.md/editor.md name the folder layout; scripts write into `<work>`. *(p.15)*
- **R11** `CODE` Scripts make no network calls (connectors are the only network path), except the one-time speech-model download. *Accept:* grep scripts for urllib/requests/http: none; tests run offline after model cached. *(p.15)*
- **R12** `INSTR` Everything required lives in Drive + connectors so the daily reel ships with the Mac off; the Scout (Chrome) is a bonus with cloud web-search fallback. *Accept:* make-reel/SKILL state the Chrome-unavailable fallback (web search, media library). *(p.11, 15)*

## Pipeline stage 1: Ingest

- **R13** `INSTR` Find the folder via the Drive connector: named folder, else today's plan-Sheet row, else newest dated folder under the configured parent, else chat attachments. *Accept:* make-reel.md lists this resolution order. *(p.17, 13)*
- **R14** `INSTR` Download every file into `<work>/raw/` (subfolders preserved) via the Librarian. *Accept:* librarian.md step 1. *(p.17, 38)*
- **R15** `CODE` Classify files by extension (case-insensitive): images jpg/jpeg/png/heic/webp; clips mp4/mov/m4v; audio mp3/wav/m4a/aac. *Accept:* Unit test on a folder with mixed-case extensions; analysis.json lists correct photos/clips. *(p.17)*
- **R16** `CODE` Convert HEIC to JPG. *Accept:* heic_photos test case: analysis.json photo paths end in .jpg. *(p.16, 17)*
- **R17** `CODE` Guess audio roles from filenames: vo/voice/memo → voiceover; music/song/track → music; one file holding both → master; overridable with --voice/--music/--master. *Accept:* Unit tests for each name pattern incl. `voiceover_and_music.mp3` (Year One) → master. *(p.17)*
- **R18** `INSTR` If visuals or audio are missing, Scout searches first (NUMA site/socials, then free stock/music), then bundled brand photos. *Accept:* SKILL Step 1.4 and make-reel step 2. *(p.17)*

## Pipeline stage 2: Analyze (analyze.py)

- **R19** `CODE` Separate voice + music: mix voice over music with sidechain ducking; length = voice + ~7.5 s outro, capped at 60 s. *Accept:* voice_and_music test: master.wav duration = min(voice+7.5, 60) ±0.1 s; music RMS lower during speech. *(p.17)*
- **R20** `CODE` Single combined track: normalize it (loudness) into master.wav 48 kHz stereo. *Accept:* combined_track test: master.wav 48 kHz stereo, integrated loudness within target. *(p.17)*
- **R21** `CODE` Transcribe with faster-whisper `small.en`, int8, word timestamps, decoding audio to raw float32 first. *Accept:* Code inspection + Year One golden test transcript includes "Mobile". *(p.17, 28)*
- **R22** `CODE` Word appear time = max(start, end − 0.4 s); `end` kept. *Accept:* Unit test on synthetic segments. *(p.17)*
- **R23** `CODE` No transcription on music-only material (no hallucinated captions). *Accept:* Music-only test: analysis.json `words` == []. *(p.17)*
- **R24** `CODE` Transcription failure degrades the reel (no captions) and never kills analyze. *Accept:* Simulated whisper import failure: analyze exits 0 with empty words and a warning. *(p.48)*
- **R25** `CODE` Beat tracking with librosa on the music gives BPM and beat times. *Accept:* Tests: beats non-empty, BPM within ±3 of generated 100 BPM fixture. *(p.17)*
- **R26** `CODE` Contact sheets: numbered photo thumbnails (P0, P1…) and clip frames sampled about every second labeled `C<k> @<t>s`. *Accept:* contact_photos.jpg / contact_clips.jpg exist; clip label uses clip id + time; ≥1 frame per second of clip (cap). *(p.17)*
- **R27** `CODE` analysis.json matches the contract: duration, bpm, beats, words[{w,appear,end}], transcript, audio{voice,music,master}, photos[{id,path,size}], clips[{id,path,duration}]. *Accept:* Validated against analysis JSON Schema in tests. *(p.26)*
- **R28** `CODE` Transcript correction pass: apply brand.json `transcript_fixes` and align words to the shoot-card script (script is the truth for spelling). *Accept:* Test: "Moby" → "Mobile"; script-alignment replaces misheard word, keeps timing. *(p.8, 6, 53)*
- **R29** `CODE` Analyze reports per-photo resolution/sharpness and per-clip brightness/shake so weak media can be routed to fallbacks. *Accept:* analysis.json has sharpness/brightness metrics per item. *(p.5, 29)*

## Pipeline stages 3-4: Script and Motion

- **R30** `INSTR` Stage 3: Director writes plan.json from analysis.json, contact sheets, brand rules and the day's plan row, following the edit grammar. *Accept:* SKILL Step 4 + make-reel step 4. *(p.18)*
- **R31** `INSTR` Stage 4: check balance, price with `get_cost` dry run, generate 9:16 5 s image-to-video for 2–4 hero photos (Kling 3.0 pro default; Seedance 2.5 for people-free signature shots), add results as video shots in plan.json. *Accept:* motion.md + SKILL Step 5 contain each step and model default. *(p.17)*
- **R32** `INSTR` Motion prompts ask for subtle realistic motion and forbid changing faces/logos/adding objects; inspect a frame of every result; drop warped faces/melted text. *Accept:* motion.md inspection rule (start/middle/end frames). *(p.17)*
- **R33** `INSTR` Reel still renders with zero credits (Higgsfield optional). *Accept:* SKILL/README state no-credit path; tests run with no Higgsfield. *(p.8, 15)*

## Pipeline stages 5-8: Preview, Render, Finish, Deliver

- **R34** `CODE` `engine.py plan.json preview t1 … tn` renders chosen timestamps into one `preview.jpg` grid (5–10 frames). *Accept:* Run preview with 8 times → preview.jpg 5 tiles wide, 2 rows. *(p.16, 18)*
- **R35** `INSTR` Claude looks at preview.jpg, fixes and repeats before the full render. *Accept:* SKILL Step 6.1, editor.md step 3. *(p.16)*
- **R36** `CODE` Full render writes `video_noaudio.mp4`, 1080×1920, 30 fps, piping raw frames into ffmpeg. *Accept:* ffprobe: 1080x1920, r_frame_rate 30/1, frames = duration×30. *(p.16, 18)*
- **R37** `CODE` Voice master chain: HP 85 Hz, cut 180 Hz, cut 3.8 kHz and 7 kHz, LP 11 kHz, optional short room echo, gentle compression, loudnorm −15 LUFS, 48 kHz resample, fades. *Accept:* finish.py filter string contains each stage; `--clean-voice` drops echo. *(p.18)*
- **R38** `CODE` Mux video + mastered audio (H.264 copy + AAC 192k 48 kHz, +faststart) into the final MP4. *Accept:* ffprobe of output: h264 + aac 48000 Hz stereo; moov before mdat. *(p.18, 48)*
- **R39** `CODE` Write a 6-frame `qa_strip.jpg`. *Accept:* qa_strip.jpg exists, 1620×480. *(p.18)*
- **R40** `CODE` Write a loudness report (integrated LUFS, true peak, mean dB) to a file and stdout; warn when mean < −28 dB. *Accept:* `loudness.json` (or similar) present with I, TP, mean; WARNING printed on quiet input. *(p.18, 48)*
- **R41** `INSTR` Deliver: send the file, upload to `Finished/` in Drive, reply with the one-line story, three caption options, and the Decisions list; chat delivery is primary, Drive upload a bonus. *Accept:* SKILL Step 7 + make-reel step 9 contain all items. *(p.18, 53)*

## Edit grammar: story and rhythm

- **R42** `INSTR` One story beat per spoken line; the picture illustrates the words being said. *Accept:* SKILL Step 4.1, 4.4. *(p.18)*
- **R43** `INSTR` Arcs: transformation, offer, event recap (exact beat sequences). *Accept:* SKILL Step 4.1 lists three arcs. *(p.18)*
- **R44** `INSTR` Hook in the first second: open on the strongest image, never the logo. *Accept:* SKILL Step 4.2. *(p.18)*
- **R45** `CODE` Exactly one signature moment: a before/after `wipe` when a matching pair exists, else a `flash` reveal on the biggest line. *Accept:* validate_plan warns when wipes > 1 or no wipe and no non-endcard flash. *(p.18)*
- **R46** `CODE` Every cut lands on a beat within one frame at 30 fps (validator warns otherwise). *Accept:* validate_plan prints WARN for an off-beat cut fixture. *(p.18, 27)*
- **R47** `INSTR` 2-beat cuts in tense/"before" sections, 4-beat holds on emotional lines; music-only outro recap montage of best 5–8 shots, 2 beats each. *Accept:* SKILL Step 4.3. *(p.18)*
- **R48** `CODE` No shot longer than 4 beats unless flagged as the emotional peak (validator warning). *Accept:* validate_plan warns on a 6-beat shot without `peak: true`. *(p.40)*
- **R49** `CODE` End card holds at least 3.5 s. *Accept:* validate_plan warns when duration − endcard.t < 3.5. *(p.19)*

## Edit grammar: transitions and motion

- **R50** `CODE` `punch`: hard cut, new shot starts 16% zoomed and snaps back over 0.22 s with a brief white lift. *Accept:* Frame diff test / code: zoom 1.16→1.0 within 0.22 s. *(p.19)*
- **R51** `CODE` `whip`: both shots slide sideways over 0.28 s with horizontal motion blur up to 160 px; at most every third cut (validator warns). *Accept:* Code + validate_plan whip-count warning test. *(p.19)*
- **R52** `CODE` `leakfade`: 0.5 s crossfade under a warm light leak (leak applied automatically). *Accept:* Render around a leakfade with no `leaks` entry still shows warm leak. *(p.19)*
- **R53** `CODE` `flash`: white flash decaying over 0.35 s. *Accept:* Code inspection/frame luminance test. *(p.19)*
- **R54** `CODE` `wipe`: soft-edged glowing vertical line sweeps left→right over 1 s from before to after shot. *Accept:* Preview at wipe midpoint shows split with glow. *(p.19)*
- **R55** `CODE` `cut` for the very first shot; `fade` accepted as plain crossfade. *Accept:* validate_plan errors when shot 0 tr ≠ cut (or warns). *(p.19, 27)*
- **R56** `CODE` Transitions varied, not all the same (validator warns on < 3 types for > 6 shots). *Accept:* validate_plan test. *(p.18, 40)*
- **R57** `CODE` Every shot moves: eased zoom in or out, alternating between shots; static z rejected/warned. *Accept:* validate_plan warns when z[0]==z[1]; baseline alternates. *(p.19)*
- **R58** `CODE` Wide/landscape photos pan across, filling the vertical frame (blurred fill only as last resort); never black bars or mirrored edges. *Accept:* Render a landscape photo: no black columns; no reflected borders at z=0.95/pan extremes. *(p.8, 19, 40)*
- **R59** `CODE` Sub-pixel eased (cubic) zoom/pan per frame. *Accept:* Code: warpAffine INTER_CUBIC with float matrix. *(p.18)*

## Edit grammar: color, captions, end card, first second

- **R60** `CODE` `before` look: 55% saturation, cool shift, lifted blacks. *Accept:* grade_arr unit test on gray/colour patch. *(p.19)*
- **R61** `CODE` `warm` look: slightly richer saturation, warm shift, gentle S-curve; `none` ungraded. *Accept:* grade_arr unit test. *(p.19)*
- **R62** `CODE` Every frame: darkened edges (vignette), soft bloom on highlights, light seeded film grain, bottom gradient. *Accept:* Code inspection; corner luminance < centre on a flat white plan. *(p.19, 18)*
- **R63** `CODE` Light leaks from plan `leaks` = [time, duration, strength 0–1]. *Accept:* Plan with strength 0.9 validates and renders. *(p.27)*
- **R64** `CODE` Captions: each word fades in and rises 22 px over 0.28 s at its appear time; line fades out at `end`. *Accept:* Preview frames at appear+0.14 s show partial alpha. *(p.19)*
- **R65** `CODE` Captions serif ~92 px white, 1–2 key words per line gold italic (#F7D6A0), soft shadow. *Accept:* Code: FR 92 px, accent from plan/brand. *(p.19)*
- **R66** `CODE` One sentence per caption line, max 2 rows; validator errors/warns when a line would wrap to 3 rows (measured with the font). *Accept:* validate_plan measures text width with the caption font. *(p.19)*
- **R67** `CODE` Captions stay out of the top 12% and bottom 10% of the frame (230 ≤ y, bottom ≤ 1728). *Accept:* validate_plan errors on caption_y that puts rows outside the safe area. *(p.19)*
- **R68** `CODE` Captions stay off faces (move automatically via smart framing face detection). *Accept:* Fixture with a face at caption height → caption_y moved. *(p.19, 29)*
- **R69** `CODE` End card: ripple background, wordmark rendered white, spaced uppercase tagline, gold italic per-reel sign-off subtitle. *Accept:* Preview of end card frame. *(p.22, 19)*
- **R70** `CODE` First second: movement from frame 1, no black fade-in longer than 0.2 s, never the logo. *Accept:* Render: frame 0 mean luminance > 0; frame 6 (0.2 s) full brightness. *(p.19)*
- **R71** `CODE` Full-opacity hook text on screen in frame zero (plan field, e.g. `hook`), works muted. *Accept:* Plan with `hook` renders text at frame 0 at full alpha. *(p.8, 19, 40)*
- **R72** `CODE` Global fade-out over the last ~0.8 s. *Accept:* Last frame luminance near 0. *(p.18)*
- **R73** `INSTR` Sound-off: captions carry the whole voiceover, payoff visible, hook on screen. *Accept:* SKILL Research rules "work muted". *(p.19)*
- **R74** `CODE` Music ducks under voice and returns for the outro. *Accept:* Covered by analyze ducking test. *(p.19)*
- **R75** `CODE` Length rules: validator warns outside 15–60 s, errors over 180 s. *Accept:* validate_plan on 70 s plan prints WARN. *(p.9, 19, 48)*
- **R76** `INSTR` Script sets length (45 s ≈ 100 words, 10–14 shots); shoot card asks for enough material. *Accept:* SKILL rules + scriptwriter rule 1. *(p.19)*
- **R77** `INSTR` Music order: Higgsfield instrumental to exact length/tempo, Meta Sound Collection at posting, licensed library; never trending; source recorded in sources.txt. *Accept:* SKILL research rules. *(p.19)*
- **R78** `INSTR` Most scripts end with a share line ("Send this to…"). *Accept:* Scriptwriter rule 4 + SKILL. *(p.19, 8)*

## Data contracts, JSON Schemas, validate_plan

- **R79** `DATA` JSON Schema for analysis.json. *Accept:* `schemas/analysis.schema.json` validates a produced analysis.json in tests. *(p.27, 51)*
- **R80** `DATA` JSON Schema for plan.json covering all fields (duration, out_dir, fps, accent_rgb, caption_y, shots{kind,src,start,speed,look,t0,t1,z,pan,tr,crop}, lines, leaks, endcard). *Accept:* `schemas/plan.schema.json`; example plan validates; bad enum fails. *(p.26-27, 51)*
- **R81** `DATA` Contracts are versioned (e.g. `schema_version` field) and kept stable. *Accept:* Both schemas and outputs carry a version. *(p.26)*
- **R82** `CODE` validate_plan validates plan.json (and analysis.json) against the schemas. *Accept:* Malformed plan → schema ERROR, exit 1, no traceback. *(p.27)*
- **R83** `CODE` validate_plan: shots tile the timeline (first t0 = 0, each t0 = previous t1, last t1 = duration). *Accept:* Unit tests with gap/overlap fixtures. *(p.27)*
- **R84** `CODE` validate_plan: caption timing checked against transcript (words and appear times match within tolerance). *Accept:* Fixture with shifted/misspelled words → WARN/ERROR. *(p.27)*
- **R85** `CODE` validate_plan: file existence for every shot src, endcard logo and fonts. *Accept:* Missing font path → ERROR. *(p.27)*
- **R86** `CODE` validate_plan: duration cap and absolute paths. *Accept:* Fixtures: relative path ERROR; 200 s ERROR. *(p.27)*
- **R87** `CODE` validate_plan: enums for look and tr; caption word format `[text, t]` or `[text, t, 1]`; line `end` ≥ last word. *Accept:* Fixture with 1-element word → ERROR not traceback. *(p.27)*
- **R88** `CODE` validate_plan: video shot `start + (t1−t0)×speed` within clip duration. *Accept:* Fixture past clip end → WARN. *(p.27)*
- **R89** `CODE` validate_plan fails loudly before a render: non-zero exit, readable ERROR lines, no tracebacks on bad JSON/missing files. *Accept:* Invalid JSON input → "ERROR …" and exit 1. *(p.27)*
- **R90** `INSTR` Editor always runs validate_plan and fixes every ERROR before preview/render. *Accept:* editor.md step 2, SKILL Step 6.1. *(p.27, 52)*

## Failure and fallback table

- **R91** `INSTR` No voiceover: cloned Katie voice from the shoot-card script (consent on file) → Higgsfield preset voice → music-only reel with on-screen text carrying the script. *Accept:* make-reel/SKILL has this ordered row. *(p.5)*
- **R92** `CODE` Music-only fallback renders the script as timed on-screen text (lines spread over beats at ~2.3 words/s) without a transcript. *Accept:* Script→lines tool produces valid plan lines from script.json and beats. *(p.5)*
- **R93** `INSTR` No music: Higgsfield instrumental (exact length/tempo) → licensed Music Library → natural clip sound plus a soft pad. *Accept:* Row present in instructions. *(p.5)*
- **R94** `CODE` Last-resort music: generate a soft pad offline and mix natural clip sound so a reel never fails for lack of audio. *Accept:* Photos-only folder (no audio) → analyze/fallback produces master.wav, reel renders. *(p.5)*
- **R95** `INSTR` Too few photos/clips: Scout on NUMA site/socials → media library + bundled brand photos → swap with a later ready day. *Accept:* Row present. *(p.5)*
- **R96** `CODE` Baseline planner falls back to bundled brand photos when the folder has no visuals. *Accept:* Audio-only folder → plan uses assets/brand-photos. *(p.5)*
- **R97** `INSTR` Landscape photos: Higgsfield outpaint to 9:16 (subject untouched) → engine pan-across → blurred fill. *Accept:* Row present in SKILL/motion. *(p.5)*
- **R98** `INSTR` Low-res/blurry photo: Higgsfield upscale to 2K → use small inside a montage → drop. *Accept:* Row present. *(p.5)*
- **R99** `INSTR` Shaky or dark clip: stabilize + brighten in the engine → Higgsfield upscale/denoise → motion clip from a still. *Accept:* Row present. *(p.6)*
- **R100** `INSTR` Higgsfield clip warps face/text/logo: re-roll once with lower motion + stronger keep line → switch model (Kling↔Seedance) → still with engine motion. *Accept:* Row present in motion.md. *(p.6)*
- **R101** `INSTR` Credits running low: cut motion clips to strongest days → engine motion only → never buy credits beyond setup budget. *Accept:* Row present. *(p.6)*
- **R102** `INSTR` Transcript mishears: fix against shoot-card script → correct names from brand data → captions from script timed to audio. *Accept:* Row present (analyst.md). *(p.6)*
- **R103** `INSTR` Critic fails 3 rounds: ship best-scoring version and log weaknesses → shorten to strongest 10–15 s → move topic later. *Accept:* Row present. *(p.6)*
- **R104** `INSTR` Health/results claim in script: rewrite to experience language → remove the line → never ship it. *Accept:* Row present. *(p.6)*
- **R105** `INSTR` Person not on consent list: crop or blur → different shot → drop. *Accept:* Row present. *(p.6)*
- **R106** `CODE` Engine supports crop and blur regions per shot so non-consented people can be removed. *Accept:* Plan shot with `blur: [[x,y,w,h]]` renders blurred region. *(p.6)*
- **R107** `INSTR` Closure/holiday day: evergreen reel that does not invite people in → Story instead → skip. *Accept:* Row present. *(p.6)*
- **R108** `INSTR` Render/encode crash: re-run the stage from saved files → draft-quality render → retry next hour, then reschedule. *Accept:* Row present. *(p.6)*
- **R109** `INSTR` Drive/Higgsfield connector down: retry after 15 min → work from local copy and queue uploads → reschedule and note in the Monday digest. *Accept:* Row present. *(p.6)*
- **R110** `INSTR` The Director works each row in order, logs which fallback it used, and never asks Katie. *Accept:* make-reel/SKILL state logging per fallback in Decisions log. *(p.5)*

## Decision authority

- **R111** `INSTR` Director (top model, high effort) owns every decision in the authority table (plan, script, shots, transitions, motion, ship, caption pick, missing material, fixes). *Accept:* make-reel.md + SKILL decision section. *(p.3)*
- **R112** `INSTR` Never ask Katie a question during a run; note decisions in the Decisions log and continue. *Accept:* Present in make-reel, SKILL, agents. *(p.4)*
- **R113** `INSTR` Never block on Katie: no approval/confirm step anywhere in the pipeline. *Accept:* grep shows no confirm step. *(p.4)*
- **R114** `INSTR` Never stop: every run ends with a finished reel or a rescheduled slot. *Accept:* SKILL "Never stop". *(p.4)*
- **R115** `INSTR` Fixed limits set at setup are rules, not questions: credits, consent for faces, licensed music. *Accept:* SKILL fixed limits. *(p.4)*
- **R116** `INSTR` Tell, don't ask: Katie gets a short note with each reel (what was made, what was decided and why). *Accept:* SKILL Step 7; never end with a question. *(p.4)*
- **R117** `INSTR` Optional steering: Sheet row edits or `note.txt` in the folder are input, re-read each run, never required. *Accept:* SKILL decision section. *(p.4, 14, 33)*
- **R118** `INSTR` Human-only escalations (Meta error 190, card renewal, legal review) go to Jude as a one-line message with the exact fix; work continues (queue posts, save to Drive). *Accept:* make-reel + brand.json admin_contact. *(p.4)*
- **R119** `CODE` Lint test: no run-time instruction file asks Katie a question or adds a confirm step (setup questionnaire excepted). *Accept:* tests scan commands/agents/skills for "ask Katie"/"confirm with"/"which do you prefer" patterns. *(p.4)*

## Scout

- **R120** `INSTR` Scout search order: NUMA channels (site, IG, FB, Google Business) → NUMA accounts (Drive, Photos, IG archive) → free stock with license check → royalty-free music → facts for the script. *Accept:* scout.md lists order. *(p.4-5)*
- **R121** `INSTR` Never take other businesses'/creators' content; never member photos from posts without recorded consent. *Accept:* scout.md. *(p.5)*
- **R122** `INSTR` Every download saved in the day's folder with `sources.txt` (file, source URL, license, date); music license page saved next to the file. *Accept:* scout.md. *(p.4-5)*
- **R123** `INSTR` Director decides what to use from Scout finds; Scout is encouraged before weaker substitutes. *Accept:* SKILL + make-reel. *(p.5, 39)*
- **R124** `INSTR` When Chrome is unavailable, Scout uses cloud web search; may run as a separate desktop task (D8). *Accept:* scout.md fallback. *(p.2, 15)*
- **R125** `INSTR` Scout model small/mid, paired with the Librarian. *Accept:* scout.md frontmatter tier. *(p.39)*

## Claims policy and safety rails

- **R126** `DATA` Banned list in brand.json covers every spec item: inflammation, immune/immunity, detox/toxins, burns fat/calories/weight loss, heals/cures/treats/prevents, anxiety/depression/PTSD/trauma, arthritis, pain relief, blood pressure, heart health, anti-aging/collagen/wrinkles, COVID/illness, science-backed/clinically proven/studies show, FDA-approved/FDA logo, dopamine/hormone numbers. *Accept:* Test asserts each term is matched by `claims.banned_patterns`. *(p.20-21)*
- **R127** `CODE` A claims checker script scans any text (voiceover script, on-screen text, captions, hashtags) against brand.json banned patterns with word boundaries; non-zero exit on hits. *Accept:* `claims_check.py "Sauna cures stress"` exits 1 naming the hit; clean text exits 0. *(p.20, 31)*
- **R128** `CODE` One banned list: validate_plan reads brand.json instead of a duplicated regex list. *Accept:* Change brand.json term → validate_plan catches it. *(p.49)*
- **R129** `CODE` Hashtags checked against banned list and brand.json `hashtags.never`. *Accept:* claims_check on "#detox" fails. *(p.20, 30)*
- **R130** `INSTR` "May help"/"studies suggest"/disclaimers don't fix a claim; "science-backed"/"clinically proven" make it worse. *Accept:* SKILL claims rules. *(p.20)*
- **R131** `INSTR` Per-modality Say / Never-say table (cold plunge, sauna, red light incl. FDA-cleared exception, breathwork) in instructions. *Accept:* SKILL contains all four rows. *(p.21)*
- **R132** `INSTR` Visuals count: no limping-in/jogging-out stories; no before/after of bodies, skin or bloodwork. *Accept:* SKILL rule. *(p.21)*
- **R133** `INSTR` Testimonials are NUMA's claims: experience only; never repost or pin a member's health claim. *Accept:* SKILL rule. *(p.21)*
- **R134** `INSTR` Ask the DPT is education only: no booking pitch in the same reel; credential never a promise of results. *Accept:* scriptwriter rule 7. *(p.21)*
- **R135** `INSTR` Titles: breathwork staff are guides/facilitators; only licensed counselors talk about mental health, within scope. *Accept:* scriptwriter rule 8. *(p.21)*
- **R136** `INSTR` Safety line on cold and heat reels; never show breath-holding in or near water. *Accept:* brand.json safety_line + scriptwriter. *(p.22)*
- **R137** `INSTR` Paid/comped creators disclose in the video and first line (#ad / "I get free sessions"); reviews never bought or conditioned. *Accept:* Caption skill + SKILL. *(p.22)*
- **R138** `INSTR` The website 57/11 dosing line is never used until counsel clears it. *Accept:* brand.json hold_until_counsel + scriptwriter. *(p.22)*
- **R139** `INSTR` AI disclosure: any reel with AI-animated people or AI-generated scenes gets Instagram's AI label (plan/metadata flag). *Accept:* Flag in output metadata; posting instructions apply it. *(p.22)*
- **R140** `INSTR` Never show or imply services NUMA doesn't offer (IV drips, cryotherapy, compression boots, float tanks, reformer Pilates). *Accept:* brand.json not_offered + critic gate. *(p.24)*
- **R141** `CODE` Caption safety rails (#15): pre-render/pre-post check fails on medical claims, people shots without a consent flag, or music without a license source. *Accept:* Plan with `people: true, consent: false` or `music_source` missing → ERROR. *(p.31)*
- **R142** `DATA` Plan/outputs carry `music_source`/license, per-shot `people`/`consent`, and `ai_label` flags. *Accept:* Schema includes the fields. *(p.19, 31)*
- **R143** `EXTERNAL` An advertising lawyer reviews the claims policy once before auto-posting is switched on. *Accept:* brand.json flag `legal_review_done` (default false) gates auto-post. *(p.2, 20)*

## Brand kit and brand.json

- **R144** `DATA` brand.json holds the brand kit: name, social handles (IG, Facebook, iOS app), voice, reference lines, offerings, wordmark, secondary mark, end-card background, B-roll dir, palette, caption fonts, end-card sign-off, each with a status. *Accept:* Test asserts keys present. *(p.22-23)*
- **R145** `DATA` brand.json holds the business facts: founders, location, facility, sessions, collective, booking (Mindbody, app, trial page), hours, site voice lines, not-offered list, one phone number. *Accept:* Keys present with status. *(p.23-24)*
- **R146** `DATA` brand.json positioning: five series with descriptions/length/built-for, collab partners in order, target audiences. *Accept:* Keys present. *(p.24-25)*
- **R147** `DATA` Status convention confirmed/research/placeholder on every uncertain value; skills prefer confirmed values. *Accept:* brand.json `_readme`; SKILL instruction. *(p.22)*
- **R148** `DATA` Transcript correction list covers NUMA, Katie, Scott, Mobile. *Accept:* transcript_fixes includes Scott variants. *(p.53)*
- **R149** `CODE` Engine and scripts read brand.json (accent colour, fonts, wordmark, end-card background/tagline/default sign-off) instead of hard-coded values. *Accept:* Change brand.json accent → rendered caption colour changes. *(p.22, 29, 49)*
- **R150** `INSTR` Every skill reads brand.json (reel-editor, scriptwriter, caption, brand-check). *Accept:* Each SKILL.md references brand/brand.json. *(p.22, 29)*
- **R151** `CODE` brand.json is validated (schema or loader) with clear errors. *Accept:* `schemas/brand.schema.json`; bad brand.json → readable error. *(p.26, 49)*
- **R152** `DATA` Bundled assets: wordmark, phoenix mark, ripple hero image, 6 brand photos, open-licensed caption fonts + LICENSE. *Accept:* Files exist in skills/numa-reel-editor/assets. *(p.22-23, 49)*
- **R153** `INSTR` `/brand-setup` command builds/updates brand.json from setup answers so any local business can use the plugin. *Accept:* commands/brand-setup.md exists, writes brand.json with status confirmed. *(p.29, 51)*

## 30-day system: /plan-month, Sheet, Drive

- **R154** `INSTR` /plan-month runs automatically monthly, researches offers/events/season/last month, needs no approval. *Accept:* plan-month.md. *(p.31)*
- **R155** `INSTR` Inputs gathered first: offers/prices, class schedule/events, closures calendar, last month's dashboard, season, Mobile local moments. *Accept:* plan-month step 1. *(p.33)*
- **R156** `DATA` Sheet "NUMA 30-Day Reel Plan" columns exactly: Day, Date, Title, Goal (awareness/offer/community/education), Template, Hook (first 2 s), Voiceover script, Shot list, Music mood + BPM, Call to action, Status (Planned/Shot/Ready to build/Ready to post/Posted), Folder link, Reel link. *Accept:* Column list in plan-month/config matches spec; status enum defined. *(p.33)*
- **R157** `INSTR` Drive structure: `NUMA Reels/_Plan/` (Sheet, `Music Library/` named mood_bpm_title.mp3, `Digests/`), `YYYY-MM Month/Day NN - YYYY-MM-DD - Title/` with SHOOT CARD, photos/, clips/, voiceover, optional music, Finished/. *Accept:* plan-month step 5 + setup guide. *(p.32)*
- **R158** `CODE` Deterministic helper for month skeleton: dates, day numbers, folder names, default-week slot types. *Accept:* Script output for 2026-12 gives 31 rows and names like "Day 01 - 2026-12-01 - …". *(p.13, 32)*
- **R159** `CODE` Month-plan checker enforces planning rules on the plan rows: no topic repeat within 14 days, ≤1 sales reel/week, inviting content not on closure days, cadence 4–5 feed posts/week, ≥1 collab + 1 Meet the Collective per month, event teaser/recap windows. *Accept:* Checker fails crafted bad month fixtures. *(p.34)*
- **R160** `INSTR` Cadence: 4–5 feed posts/week (~2/3 Reels, 1/3 carousels), daily Stories, 1–2 Trial Reels/week, never a week dark. *Accept:* plan-month step 2. *(p.33)*
- **R161** `DATA` Starting content mix 30/25/15/15/15 (education/community/local-seasonal/collective-collabs/offers-events), re-weighted monthly from performance. *Accept:* brand.json content_mix sums to 1.0; plan-month re-weights. *(p.33)*
- **R162** `INSTR` Default week: Mon Ask the DPT reel; Tue carousel; Wed community reel; Thu Trial Reel + Stories; Fri offer/event/collab reel; Sat Stories; Sun Regulate reel or Stories. *Accept:* plan-month or SKILL contains the table. *(p.34)*
- **R163** `INSTR` Posting hours start late afternoon Central, re-tuned after first 30 reels; each reel judged at 72 h. *Accept:* brand.json slot + instructions. *(p.34)*
- **R164** `INSTR` Planning rule: no topic repeats within 14 days; ≤1 sales-focused reel a week. *Accept:* plan-month step 2. *(p.34)*
- **R165** `INSTR` Planning rule: lengths (growth 45–60, atmosphere 15–30, never > 3 min) and originality (collabs only, never reposts). *Accept:* scriptwriter rule 1 + SKILL. *(p.34)*
- **R166** `INSTR` Planning rule: ≥1 collab reel and 1 Meet the Collective feature a month. *Accept:* plan-month text. *(p.34)*
- **R167** `INSTR` Planning rule: Director checks the 7-day forecast every Friday and swaps in weather hooks (cold snaps, heat waves, storms). *Accept:* Friday task instruction. *(p.34)*
- **R168** `INSTR` Planning rule: one signature transformation/reveal reel a month; event teaser 2–3 days before and recap within 2 days; nothing inviting on closure days. *Accept:* plan-month step 2. *(p.34)*
- **R169** `INSTR` Planning rule: shoot cards grouped so Katie films a week in 1–2 short sessions. *Accept:* plan-month step 4. *(p.35)*
- **R170** `INSTR` Planning rule: after 30 posted reels re-tune mix, lengths and posting hours to NUMA's results. *Accept:* plan-month text. *(p.35)*
- **R171** `DATA` Five recurring series defined (Ask the DPT 45–60 s education; First Plunge with consent + share line; Too Hot for a DIY Plunge; Regulate 45–60 s guided breath by Fallon/Joseph; Meet the Collective monthly collab) and rotated every month. *Accept:* brand.json/series data with definitions. *(p.25)*
- **R172** `INSTR` Collabs: "Sweat there, recover here" with Mission Fitness first, then barre3, Pure Barre, run clubs, South Alabama teams; collab posts not reposts. *Accept:* Instructions + brand.json collab_partners. *(p.25)*
- **R173** `INSTR` Build day: read the day's row and folder, run crews + Critic, save to `Finished/`, mark row "Ready to post" (or post). *Accept:* make-reel step 9. *(p.32)*
- **R174** `INSTR` Night-before check (daily 8 pm): compare tomorrow's folder to its shoot card, Scout for missing items, pick substitute or swap topic, send Katie a heads-up (never a question). *Accept:* Command/task prompt file (e.g. commands/night-before.md). *(p.13, 32)*

## Shoot cards and batched shoots

- **R175** `INSTR` Shoot card format: header (DAY · date · title · FILM BY), WHERE TO PUT FILES, WHAT TO FILM checklist with line refs, READ THIS OUT LOUD, MUSIC, LENGTH, last line "IF YOU CAN'T: skip it."; phone-readable in < 1 min. *Accept:* scriptwriter SKILL card template. *(p.36)*
- **R176** `INSTR` Filing rules at the top of every card: where (photos/, clips/), voiceover naming/re-record, optional music else Music Library by mood, any file names, phone settings (vertical, 4K 30 fps, hold 5 s, no zoom), optional Sheet changes. *Accept:* Card template includes all rows. *(p.32-33)*
- **R177** `INSTR` Days needing nothing say "No filming needed" in the first line. *Accept:* scriptwriter SKILL. *(p.31, 36)*
- **R178** `INSTR` Card rules: ≤ 8 new shots; each tied to a script line with framing + duration; people shots marked "consent list only"; one AI-motion shot; script under target word count; last line "If you can't: skip it." *Accept:* scriptwriter rule 5 + template. *(p.36)*
- **R179** `DATA` JSON Schema for script.json (day, date, title, series, pillar, goal, template, length_s, hook_text, lines, shots, photos, music, cta, share_line, safety_line, needs_consent, film_by, batch_room). *Accept:* `schemas/script.schema.json` validates the documented example. *(p.35-36)*
- **R180** `CODE` script.json checker enforces card rules and timing (words ≤ 2.3 × (length − outro), ≤ 8 new shots, one ai_motion, people ⇒ consent flag, every shot has line/framing/seconds) and runs the claims check. *Accept:* Checker fails crafted bad cards. *(p.35-36)*
- **R181** `INSTR` Weekly shoot list in the digest sorted by room (plunge room, sauna, class studio, front of house, outside), then time of day, with a total time estimate. *Accept:* Digest instructions. *(p.37, 45)*
- **R182** `INSTR` Shots that repeat across reels are filmed once and reused, tagged in the media library. *Accept:* plan-month/librarian instructions. *(p.37)*
- **R183** `INSTR` Week's voiceovers read in one sitting, one file per day named by day number; Librarian routes them to the right day. *Accept:* Card + librarian instructions. *(p.37)*
- **R184** `INSTR` Calendar classes/events become capture moments listing shots to grab during them. *Accept:* plan-month instruction. *(p.37)*
- **R185** `INSTR` Anything not filmed by its date triggers the failure table, never a reminder nag. *Accept:* Instruction present. *(p.37)*

## Scriptwriter skill

- **R186** `INSTR` numa-scriptwriter powers /plan-month (all 30 cards in one pass) and works alone for one-off reels. *Accept:* Skill description + plan-month step 3. *(p.35, 39)*
- **R187** `INSTR` Per reel: hook (first 2 s, on screen and spoken); VO script at ~2.3 words/s (30 s ≈ 65–70 words) plus 6–8 s music-only outro, one short sentence per beat. *Accept:* scriptwriter rules 1-2. *(p.35)*
- **R188** `INSTR` Per reel: numbered shot list tied to lines (framing, hold 5 s, one AI hero shot); photos to take; audio direction (mood, tempo, source, recording). *Accept:* script.json example + rule 5. *(p.35)*
- **R189** `INSTR` Per reel: on-screen text + CTA matched to the day's goal; draft caption and hashtags via numa-caption. *Accept:* script.json has cta and caption fields. *(p.35)*
- **R190** `INSTR` VO recording tips: quiet soft room, phone ~12 in, normal voice, one take, 1 s silence at start and end. *Accept:* Card template text. *(p.35)*
- **R191** `INSTR` Claims policy run on every line before the Director sees it; rewrite affected lines on build day when material is missing. *Accept:* scriptwriter rules 6 + missing-material section. *(p.39)*

## Templates library and reel templates

- **R192** `DATA` Template library: transformation, class spotlight, member story, modality explainer, offer promo, event recap, event teaser, behind the scenes, founder message, myth vs fact, seasonal/holiday; each defines arc, beat count, typical length, signature moment. *Accept:* `templates/*.json` (or one file) with 11 entries and required fields. *(p.35)*
- **R193** `DATA` Reel templates (#13) as named presets: Numa Nights recap, class spotlight, member story, offer promo, education with kinetic type, holiday hours. *Accept:* Presets present and loadable. *(p.30)*
- **R194** `CODE` `baseline_plan.py --template NAME` applies the template's arc, pacing and signature moment to the starting plan. *Accept:* Each template yields a valid plan. *(p.30, 35)*
- **R195** `CODE` Kinetic type: engine renders large animated text cards for education templates. *Accept:* Plan with a text card renders it. *(p.30)*

## Agent crew and Critic

- **R196** `INSTR` Director role (top model, high effort): reads plan row + folder, writes story and shot plan, assigns crews, final go/no-go. *Accept:* make-reel.md acts as Director script. *(p.38)*
- **R197** `INSTR` Librarian (small): downloads, converts, checks against card; returns inventory + missing list. *Accept:* agents/librarian.md. *(p.38)*
- **R198** `INSTR` Analyst (small/mid): runs analyze.py, fixes names, rates every shot; returns ratings + best clip windows. *Accept:* agents/analyst.md. *(p.38)*
- **R199** `INSTR` Motion (mid): uploads hero photos, generates, rejects warped results, stays in budget; returns approved clips + credits spent. *Accept:* agents/motion.md. *(p.39)*
- **R200** `INSTR` Copywriter (small): 3 captions, 1 recommended (plus Story line and email paragraph). *Accept:* agents/copywriter.md. *(p.39, 46)*
- **R201** `INSTR` Editor (mid): shot plan → plan.json → validate → preview → render → finish; returns MP4 + QA strip; the only agent that renders. *Accept:* agents/editor.md. *(p.39)*
- **R202** `INSTR` Critic (top, fresh context): scores against the rubric; never sees Director/Editor reasoning. *Accept:* agents/critic.md. *(p.39-40)*
- **R203** `INSTR` Scout (small/mid, Chrome) and Scriptwriter (mid) agents exist. *Accept:* agents/scout.md, scriptwriter.md. *(p.39)*
- **R204** `DATA` Model tiers in one config line (e.g. `config/models.json` top/mid/small → model ids); agent files and commands refer to tiers only. *Accept:* grep finds model ids only in the config file. *(p.39, 52)*
- **R205** `INSTR` /make-reel starts crews in parallel, waits, hands the plan to the Editor, sends the result to the Critic. *Accept:* make-reel steps 1-7. *(p.39)*
- **R206** `INSTR` Critic inputs: QA strip, 12 frames (every cut + first and last second), loudness report, transcript, plan, shoot card. *Accept:* critic.md. *(p.40)*
- **R207** `CODE` Frame extractor produces the Critic's 12 frames (every cut + first and last second) from the MP4 and plan. *Accept:* Script writes 12 JPGs/contact strip for a test render. *(p.40)*
- **R208** `INSTR` Critic hard gates: banned claims anywhere; non-consented person; unlicensed/trending music; silent/clipped/non-48 kHz audio or not 1080×1920; NUMA misspelled or wrong price/date/offer; warped AI shot or invented equipment/rooms; black bars/mirrored edges/frozen frame; content NUMA didn't make; AI person without AI label. *Accept:* critic.md lists all gates. *(p.40)*
- **R209** `CODE` Automated gate checks on the final MP4: 1080×1920, 48 kHz, not silent, not clipped (TP), no black bars, no frozen frames, banned words in captions/copy. *Accept:* `qa_check.py out.mp4 plan.json` JSON report; failing fixtures detected. *(p.40)*
- **R210** `INSTR` Weighted rubric: hook 20, retention 15, story 15, shareability 10, beat sync 10, captions 10, brand look 10, audio 10 (1–5 each). *Accept:* critic.md. *(p.40-41)*
- **R211** `CODE` Pass rule computed deterministically: weighted total ≥ 80, no category < 3, hook ≥ 4. *Accept:* Scorer unit tests on edge cases (79.9, hook 3). *(p.41)*
- **R212** `INSTR` Virality predictor score attached as a second opinion only, never overriding. *Accept:* critic.md. *(p.41)*
- **R213** `INSTR` Critic output: score table, then numbered fixes each naming the exact plan.json field or shot; no unactionable fixes. *Accept:* critic.md. *(p.41)*
- **R214** `INSTR` Critic loop capped at 3 rounds; then ship the best version and list what is still imperfect. *Accept:* make-reel step 7. *(p.38-39)*
- **R215** `INSTR` Every reel passes the brand check (look, type, logo, voice) before delivery. *Accept:* make-reel invokes numa-brand-check or Critic brand look. *(p.3)*

## Higgsfield

- **R216** `DATA` Pricing table as config (job, model, credits, verified date): Kling std 5 s 7.5; Kling pro 5 s 8.75; Kling pro 10 s 17.5; Seedance 720p 35; Seedance 1080p 80; outpaint 2; upscale 2K 2; music 40 s 5.82; voice line 0.5; reframe 20 s 245. *Accept:* `config/higgsfield.json` with these values; instructions reference it. *(p.41-42)*
- **R217** `INSTR` Director re-checks every price with `get_cost` before each job. *Accept:* motion.md. *(p.41)*
- **R218** `INSTR` Ranked uses 1–11: outpaint, upscale, Kling hero motion (draft std, finalize pro), start+end real-room moves/before-after, people as Elements, custom music, voice fallback, Seedance people-free, logos frontal + engine wordmark, motion transfer, virality predictor (Marketing Studio #12 deferred per D5). *Accept:* SKILL Step 5 lists all. *(p.42-43)*
- **R219** `DATA` Monthly budget split 600/140/160/120/10/170 = 1,200 credits. *Accept:* brand.json budgets sum test. *(p.43)*
- **R220** `CODE` Credit ledger tool: records each job, enforces monthly split, ≤ 55% spent by day 15, ≤ 150 credits/reel, never over budget; mirrors to the plan Sheet. *Accept:* `ledger.py check` fails on day-15 overspend fixture. *(p.3, 43)*
- **R221** `INSTR` Credits reset monthly; failed generations refunded, unwanted ones not: draft cheap, finalize keepers only. *Accept:* SKILL Step 5. *(p.43)*
- **R222** `INSTR` Prompt rules: describe motion not room; one camera move with a size; end with keep clause; prototype 720p, change one thing per retry; safe vs risky moves; Kling order scene, Element, camera, action timing, lighting, audio, locks. *Accept:* SKILL Step 5 prompt rules. *(p.43)*
- **R223** `DATA` Prompt library with the 7 spec prompts (cold plunge empty, sauna glow, real room move, member/guide, exterior/sign, before→after, empty walkthrough) and their models. *Accept:* Library file/section with all 7. *(p.43-45)*
- **R224** `INSTR` Model choice by faces: Kling for anything with a person (Element, consent list only); Seedance only for people-free spaces. *Accept:* motion.md. *(p.10, 42)*
- **R225** `INSTR` No member face uploaded unless the consent form covers AI processing (brand.json consent flag). *Accept:* SKILL + brand.json consent. *(p.45, 49)*
- **R226** `INSTR` Never use Reframe (245 credits); crops for other formats happen in the engine. *Accept:* SKILL. *(p.42, 46)*
- **R227** `INSTR` Unlimited Kling 720p window: Scout may batch drafts on higgsfield.ai via Chrome when active, after confirming terms. *Accept:* motion/scout instructions. *(p.45)*
- **R228** `INSTR` /numa-setup reports how many reels the balance covers using current Kling-based per-reel cost. *Accept:* numa-setup.md uses config prices. *(p.13)*

## v2 outputs: one reel, many outputs

- **R229** `CODE` Engine output-size setting (width/height from plan or CLI) for all formats. *Accept:* Render plan at 1080×1350: ffprobe matches. *(p.46)*
- **R230** `CODE` Main reel 1080×1920 (length per script; see ambiguity on 8–45 s). *Accept:* ffprobe on main output. *(p.46)*
- **R231** `CODE` Reach cut-down: best 8–12 s of the same reel with new hook text, from the same plan. *Accept:* Output MP4 8–12 s, 1080×1920, hook text in frame 0. *(p.46)*
- **R232** `CODE` Story set: 3–5 vertical stills or 5 s clips, one line of text each. *Accept:* 3–5 files 1080×1920. *(p.46)*
- **R233** `CODE` Carousel: 5–8 stills at 1080×1350 (4:5) with short captions. *Accept:* 5–8 JPGs 1080×1350. *(p.46)*
- **R234** `CODE` Cover image 1080×1920 with the title kept inside the centre square (y 420–1500). *Accept:* Cover PNG; title bbox within centre 1080×1080. *(p.46)*
- **R235** `CODE` `.srt` caption file of the voiceover from plan lines/transcript. *Accept:* SRT parses; cue count = caption lines; times match. *(p.29, 46)*
- **R236** `INSTR` Copy: Instagram caption, one-line Story text, short email paragraph. *Accept:* copywriter.md. *(p.46)*
- **R237** `CODE` All outputs come from one run/command off the same plan (crops in engine, never Higgsfield reframe), behind /make-reel. *Accept:* One command writes the full output family to Finished/. *(p.29, 46, 52)*

## Monday digest and weekly trend check

- **R238** `INSTR` Monday digest every Sunday 6 pm: phone-readable in 2 min, saved as Google Doc in `_Plan/Digests/`, sent as notification or email, never asks a question. *Accept:* Digest command/task file. *(p.45, 50)*
- **R239** `INSTR` Digest sections: last week (thumbnail, link, views, avg watch time, sends, best + why); changes made; this week's schedule; batched shoot list by room with time estimate; budget (credits used/left, Claude usage); heads-ups (swaps, Scout finds, skips). *Accept:* Digest template has six sections. *(p.45-46)*
- **R240** `CODE` Deterministic digest builder assembles numbers from metrics store, ledger and plan rows. *Accept:* Script renders digest Markdown from fixtures. *(p.45)*
- **R241** `INSTR` Weekly trend check (Fridays 7 pm): Scout (Chrome or web search) reviews formats, hooks, editing styles, topics for wellness studios and Mobile businesses, never songs; uses a trend only with NUMA's audio or Sound Collection. *Accept:* scout.md. *(p.46-47)*
- **R242** `INSTR` Trend output: 3 ideas each with example link, fit, how to make it (often motion transfer); winner tested as a Trial Reel; Director may slot one into next week. *Accept:* scout.md + plan instructions. *(p.47)*

## Performance dashboard and learning loop

- **R243** `INSTR` Composio Instagram toolkit via Instagram Login (no Facebook Page), scopes instagram_business_basic, _manage_insights, _content_publish. *Accept:* Setup guide + numa-setup check. *(p.47, 49)*
- **R244** `DATA` Every Composio call sets `graph_api_version` to a current version (v26.0). *Accept:* brand.json instagram_api + instructions. *(p.11, 47)*
- **R245** `INSTR` Pull INSTAGRAM_GET_IG_MEDIA_INSIGHTS at 48 h and 7 days per reel plus INSTAGRAM_GET_USER_INSIGHTS; store everything (Meta keeps 90 days). *Accept:* Dashboard refresh task instructions. *(p.47)*
- **R246** `CODE` Metrics store schema: views, reach, likes, comments, saves, shares, reposts, total_interactions, avg watch time (ms), skip rate; rejects plays/impressions. *Accept:* Metrics loader test rejects `plays`. *(p.47)*
- **R247** `DATA` NUMA tags per reel: length, series, pillar, hook type, transitions, music source, posting time, Trial Reel, collab. *Accept:* Schema/tag fields present. *(p.47)*
- **R248** `CODE` Computed metrics: retention = avg watch time ÷ length (ms→s), sends/1,000 reach, saves/1,000 reach, skip rate vs NUMA median. *Accept:* Unit tests on fixtures. *(p.47)*
- **R249** `CODE` Dashboard (self-contained HTML per D7): leaderboard, results by series/length/hook type, posting-time heatmap, 90-day trend, Do more/Do less box. *Accept:* Generator builds HTML from fixture metrics.json. *(p.47)*
- **R250** `INSTR` Monthly competitor tracker: Scout logs the last 12 posts of Beyond The Plunge, Mission Fitness, barre3 Mobile, Pure Barre Mobile, Mobile Cryotherapy. *Accept:* scout.md + brand.json competitors. *(p.47)*
- **R251** `DATA` Storage per D7: `metrics.json` + "NUMA Reel Metrics" Sheet in `_Plan/`; dashboard republished by daily refresh. *Accept:* Instructions + sample file. *(p.2, 47)*
- **R252** `INSTR` Loop: at month planning read the dashboard, re-weight series, lengths, posting hours (and hook types/transitions in edit rules); list changes in the next digest. *Accept:* plan-month instructions. *(p.30, 47)*

## Auto-posting

- **R253** `INSTR` Post via Composio: INSTAGRAM_POST_IG_USER_MEDIA (REELS, staged file or public URL) then INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH after 3–5 min; check publishing limit (100/24 h); never reuse a container > 24 h; publish same day. *Accept:* SKILL Instagram rules. *(p.11, 48)*
- **R254** `INSTR` Trial Reels and collaborator invites via direct Graph API or Claude in Chrome. *Accept:* make-reel step 9. *(p.2, 48)*
- **R255** `INSTR` AI label: API path if supported, else Claude in Chrome, else leave for manual posting and notify Jude (D8). *Accept:* Posting instructions. *(p.2)*
- **R256** `DATA` Approval step exists only as an off-by-default switch; auto-post default on (Q34) and gated by legal review. *Accept:* brand.json posting.require_approval=false, auto_post. *(p.30, 56)*
- **R257** `INSTR` Post to Instagram and Facebook at the best time (late afternoon Central until retuned). *Accept:* Posting instructions. *(p.30, 34)*
- **R258** `INSTR` Captions open with a plain searchable phrase and use 3–5 hashtags incl. one NUMA community tag. *Accept:* numa-caption SKILL. *(p.50)*
- **R259** `INSTR` After posting, mark the Sheet row Posted with the Reel link. *Accept:* make-reel step 9. *(p.33)*
- **R260** `INSTR` Weekly best reel also posted to the Google Business Profile. *Accept:* Instruction present. *(p.50)*

## Scheduled tasks

- **R261** `DATA` Scheduled-task table as config: plan next month (24th, 9 pm), material check + Scout (daily 8 pm), build reel + outputs (daily 5 am), dashboard refresh (daily 10 pm), trend check (Fri 7 pm), Monday digest (Sun 6 pm), all Central. *Accept:* `config/schedule.json` (or doc) with 6 entries and cron strings. *(p.50)*
- **R262** `INSTR` A prompt/command file for each scheduled task, runnable unattended (no command typed by Katie). *Accept:* One file per task. *(p.14, 50)*
- **R263** `INSTR` Phone notification when a reel is ready. *Accept:* Build task instructions. *(p.30)*
- **R264** `INSTR` Scheduled runs never stall on permission prompts: /numa-setup approves connector tools. *Accept:* numa-setup step. *(p.50)*

## Setup

- **R265** `INSTR` /numa-setup installs Python packages (pip with --break-system-packages fallback) and verifies all imports (cv2, librosa, faster_whisper, imageio_ffmpeg, PIL, numpy, pillow_heif). *Accept:* numa-setup step 1. *(p.13, 50)*
- **R266** `INSTR` /numa-setup renders a 3-second test (full render + finish) and looks at it. *Accept:* numa-setup step 2. *(p.13, 50)*
- **R267** `CODE` Setup self-check script: Python ≥ 3.10, imports, ffmpeg (system or imageio fallback), fonts/assets, 3 s test render; ✅/❌ with one-line fix; exit code. *Accept:* `setup_check.py` passes in CI; fails clearly with a missing module. *(p.13, 50, 53)*
- **R268** `INSTR` /numa-setup confirms every connector: Drive, Higgsfield, Composio Instagram, Gmail (optional). *Accept:* numa-setup steps. *(p.50)*
- **R269** `INSTR` /numa-setup asks once which Drive folder holds reel material and remembers it. *Accept:* numa-setup step 3. *(p.13)*
- **R270** `INSTR` /numa-setup pre-downloads the speech model so the first run is not slow. *Accept:* numa-setup step. *(p.29)*
- **R271** `DATA` Setup guide doc: Max plan, desktop app Keep awake + Run on startup, marketplace install, connectors (Drive, Higgsfield Plus, Composio IG Business/Creator, Gmail), Chrome extension profile, Drive structure incl. Consent List (name, photo, date, scope) and Closures, voice sample + consent, /numa-setup, scheduled tasks, golden test, account fixes, monthly cost table. *Accept:* `docs/SETUP.md` covers each step. *(p.49-51)*
- **R272** `DATA` Questions for Katie stored as the setup questionnaire: all 51 questions grouped, each mapped to a brand.json field or planning rule, with defaults (children never, auto-post yes, see-first none). *Accept:* `setup/questions.json` with 51 entries and target keys. *(p.54-57)*
- **R273** `INSTR` The questionnaire is the only time questions are asked; short or "don't know" answers keep research defaults. *Accept:* /brand-setup instructions. *(p.54)*
- **R274** `EXTERNAL` Katie answers the 51 questions; Jude creates accounts and runs setup on her Mac. *Accept:* In-repo: questionnaire + /brand-setup + setup guide. *(p.2, 49)*
- **R275** `DATA` Research prompts (5) stored in the repo with a quarterly re-check reminder; prices carry a verified date. *Accept:* docs file with prompts; pricing config has `verified`. *(p.8, 57)*

## Feedback memory, smart framing, hook variants

- **R276** `DATA` Feedback memory: a preferences file (revision notes like "fewer whips") stored durably (Drive `_Plan/` + local copy). *Accept:* File format documented; example present. *(p.30)*
- **R277** `INSTR` Every run reads the preferences file; new notes are appended so Katie never repeats one. *Accept:* make-reel/SKILL step. *(p.30)*
- **R278** `CODE` Numeric preferences (e.g. max whips, caption size) are honoured by baseline_plan/validate_plan. *Accept:* Pref "fewer whips" → validator threshold tightens. *(p.30)*
- **R279** `CODE` Smart framing: OpenCV face/subject detection so zooms and pans centre on people. *Accept:* Fixture with off-centre face → plan/engine focus point on face. *(p.29)*
- **R280** `CODE` Hook variants: render 2–3 alternate openings (different first shot/hook text) from one plan. *Accept:* Command writes 2–3 short MP4s. *(p.30)*
- **R281** `INSTR` Score hook variants with Higgsfield's virality predictor; pick the best; feed into Trial Reels. *Accept:* Instructions present. *(p.30, 43)*
- **R282** `CODE` Clip intelligence: score every second of each clip for sharpness, motion and faces to pick windows (deferred per D5 except stabilize). *Accept:* Per-second scores in analysis.json. *(p.29)*
- **R283** `INSTR` Topic-only mode: with no VO/footage, write script, generate voice + music, pull B-roll (cloned voice only with consent). *Accept:* make-reel fallback text. *(p.30)*

## Natural sound, media library, stabilize/brighten, draft and multi-core render

- **R284** `CODE` Natural sound: mix short bursts of each clip's own audio (per-shot gain/window) under the music, ducked under voice. *Accept:* Plan with `nat` on a clip shot → output audio contains clip audio during that shot. *(p.29, 28)*
- **R285** `DATA` Media library index of past Drive photos/clips with tags (room, subject, morning, smiling, group, people, consent, link). *Accept:* Index schema + Sheet name documented. *(p.30, 37)*
- **R286** `CODE` Media library indexer builds/updates a local JSON index (dims, orientation, duration, sharpness, tags) and queries by tag. *Accept:* `media_index.py add/query` tests. *(p.30)*
- **R287** `CODE` Stabilize shaky clips (vidstab or OpenCV) and brighten dark clips in the engine, per-shot flag or auto-detected. *Accept:* Shaky fixture: inter-frame motion reduced; dark fixture: mean luma raised. *(p.5, 29)*
- **R288** `CODE` Draft-quality render mode (lower resolution, faster preset) for revisions and crash fallback. *Accept:* `engine.py plan.json --draft` renders much faster at lower res. *(p.6, 30, 48)*
- **R289** `CODE` Multi-core rendering across CPU cores with output identical to single-core. *Accept:* `--workers N` hash equals single-process output. *(p.30, 48)*
- **R290** `CODE` Per-shot cache and Mac hardware encoder (h264_videotoolbox) option (not used for golden/determinism). *Accept:* Flag present; falls back to libx264. *(p.30)*

## Non-functional requirements

- **R291** `CODE` Output spec: MP4, H.264 High, 1080×1920, 30 fps, yuv420p, ≤ ~14 Mbps, AAC 192 kbps 48 kHz stereo, +faststart, < 100 MB, 15–60 s; verified by ffprobe in tests. *Accept:* Test asserts each property with ffprobe. *(p.48)*
- **R292** `CODE` Loudness: −15 LUFS integrated (±1), true peak ≤ −1.5 dBTP measured on the final file; mean level > −28 dB else warn. *Accept:* ebur128 measurement on test outputs meets limits. *(p.48)*
- **R293** `CODE` Speed: revision render under 3 min (draft/multi-core); 40 s render time logged. *Accept:* Timed test of a 40 s draft render. *(p.48)*
- **R294** `EXTERNAL` Drop-to-file under 15 min for a 40 s reel incl. up to 4 Higgsfield clips, on Katie's Mac. *Accept:* In-repo: golden test logs stage timings. *(p.2, 48, 51)*
- **R295** `INSTR` Cost: never exceed Higgsfield Plus 1,200 credits or the Claude Max plan; report spend in the Monday digest. *Accept:* motion.md + digest instructions. *(p.48)*
- **R296** `CODE` Reliability: every stage idempotent and resumable from its files (re-running a stage gives the same outputs, skips completed work). *Accept:* Re-run analyze/engine/finish twice: identical outputs, no errors. *(p.16, 48)*
- **R297** `CODE` Determinism: same inputs + same plan = byte-identical render (seeded grain, no other randomness). *Accept:* Test renders twice and compares SHA-256 of video_noaudio.mp4 and final MP4. *(p.48)*
- **R298** `CODE` Platform: macOS (Apple Silicon) primary; Linux sandbox and Claude Code also work. *Accept:* CI matrix ubuntu + macos runs the suite. *(p.48)*
- **R299** `DATA` Dependencies: Python 3.10+, OpenCV, NumPy, Pillow, librosa, faster-whisper, pillow-heif; system ffmpeg or imageio-ffmpeg; declared in a requirements file. *Accept:* `requirements.txt` exists; clean venv install + tests pass. *(p.49)*
- **R300** `INSTR` No paid APIs beyond Higgsfield (Composio free tier). *Accept:* grep: no other paid service. *(p.49, 51)*
- **R301** `INSTR` Privacy: raw files stay in Drive/machine; only chosen hero photos go to Higgsfield; no member faces without consent. *Accept:* SKILL/motion instructions. *(p.49)*
- **R302** `DATA` Licensing: music Katie's or licensed; bundled font open-licensed with LICENSE; NUMA owns brand files (stated in README). *Accept:* fonts/LICENSE present; README note. *(p.49)*
- **R303** `DATA` Maintainability: brand in data, edit rules in SKILL.md, exact logic in scripts; semver in plugin.json; CHANGELOG.md. *Accept:* CHANGELOG.md exists with an entry per version. *(p.49)*

## Milestones and test harnesses

- **R304** `EXTERNAL` M1: repo pushed (CordiaJude/numa-studio, D6), installed from the marketplace on Katie's Mac, /numa-setup all green, 3 s render looks right. *Accept:* In-repo: setup_check script + marketplace manifest. *(p.51)*
- **R305** `CODE` M2 golden test harness: runs the Year One test pack (path via CLI/env, never committed) end to end with no other input and checks: < 15 min, story arc, before/after wipe, beat-synced cuts, synced captions, output spec; writes a side-by-side comparison vs the reference. *Accept:* `tests/golden_year_one.py --pack PATH` exits 0 and writes a report. *(p.51-52)*
- **R306** `CODE` Golden test checks analysis of Year One: BPM ≈ 107.7 (±2) and transcript contains "Mobile". *Accept:* Assertions in golden harness. *(p.28)*
- **R307** `EXTERNAL` M2 quality: Jude rates the result at least as good as the hand-built reference. *Accept:* Harness output comparison sheet supports review. *(p.51)*
- **R308** `CODE` M3 five-folder suite: photos only; clips only; separate voice + music; music only (no voice); HEIC photos — each produces a postable reel with no human input. *Accept:* `python3 tests/run_tests.py` 5/5 PASS with these exact cases. *(p.51)*
- **R309** `CODE` CI runs the suite on every push (GitHub Actions workflow). *Accept:* `.github/workflows/*.yml` runs tests on push. *(p.28, 51)*
- **R310** `EXTERNAL` M4: funded Higgsfield; 2–4 clips used, none warped, credits within budget and reported. *Accept:* In-repo: motion instructions + ledger. *(p.52)*
- **R311** `EXTERNAL` M5: five scheduled days on Katie's real material; ≥ 4 post-ready unchanged; zero questions, zero commands. *Accept:* In-repo: scheduled-task prompts + night-before. *(p.52)*
- **R312** `CODE` M6: each addition ships behind the same /make-reel and M2 still passes (order: brand.json, feedback memory, all formats, smart framing, scheduled runs, auto-posting). *Accept:* Golden test re-run recorded per addition. *(p.52)*
- **R313** `EXTERNAL` M7: Director plans December alone; ≥ 25/30 days produce a reel from the right folder with no command; Critic catches ≥ 1 real flaw a week. *Accept:* In-repo: plan-month, scriptwriter, night-before, agents. *(p.52)*
- **R314** `INSTR` Release rule: every release re-runs the M2 golden test; if Year One gets worse the release does not ship (recorded in CHANGELOG). *Accept:* README/CHANGELOG release checklist. *(p.52)*

## Open verifications and blocking inputs

- **R315** `EXTERNAL` Verify whether Instagram's AI label can be applied via the API (else Chrome/manual). *Accept:* D8 fallback instructions in repo. *(p.2)*
- **R316** `EXTERNAL` Verify Trial Reels/collab invites path (Graph API direct or Chrome). *Accept:* Instructions cover both paths. *(p.2)*
- **R317** `EXTERNAL` Verify whether a cloud scheduled task can drive Claude in Chrome; else Scout runs as a desktop task. *Accept:* D8 instructions. *(p.2)*
- **R318** `EXTERNAL` Decide dashboard storage (artifact DB, Sheet, or both). *Accept:* D7 implemented as metrics.json + Sheet. *(p.2)*

## Implicit project requirements

- **R319** `CODE` Tests pass from a clean install (fresh venv + requirements file + ffmpeg). *Accept:* CI job on clean runner passes. *(implicit)*
- **R320** `CODE` Scripts give clear errors for user errors (missing args/files, bad JSON, no audio) with non-zero exit and no traceback. *Accept:* Tests call each script with bad input and assert no "Traceback". *(implicit)*
- **R321** `CODE` Every script has a usage/--help line describing its CLI. *Accept:* `script.py --help` or no-arg prints usage. *(implicit)*
- **R322** `DATA` README covers install, setup, daily use, running tests, and v2 features. *Accept:* README sections present and current. *(implicit)*
- **R323** `DATA` No secrets committed (no tokens/keys in repo). *Accept:* Secret scan (grep/gitleaks) clean. *(p.49)*
- **R324** `DATA` No member photos or test-pack media committed; `spec/` gitignored; tests synthesize fixtures. *Accept:* `git ls-files` has no test-pack media; .gitignore has spec/. *(p.49)*
- **R325** `CODE` Scripts work on Linux and macOS: no Linux-only paths or flags; temp files via tempfile. *Accept:* grep for /tmp, /home, /mnt in scripts: none. *(p.48)*
- **R326** `CODE` Python 3.10+ compatible syntax (no newer-only features). *Accept:* `vermin`/py_compile under 3.10 in CI. *(p.49)*
- **R327** `CODE` Tests need no network or credits once the speech model is cached. *Accept:* Run suite offline after setup. *(implicit)*

## Spec contradictions and ambiguities (interpretation used)

1. **Main reel length.** v2 outputs table says main reel "8–45 s" (p.46); research, planning rules and NFR say growth reels 45–60 s, output 15–60 s, never > 3 min. *Interpretation:* main reel 15–60 s set by the script (45–60 s growth); 8–12 s is the reach cut-down only; validator warns outside 15–60 s, errors > 180 s.
2. **First second vs global fade-in.** Engine spec lists "global fades" (p.18) but the first second must have movement and full-opacity hook text from frame 0, with no black fade-in > 0.2 s (p.8, 19, 40). *Interpretation:* no picture fade-in longer than 0.2 s, hook text drawn at full opacity from frame 0.
3. **Leak strength range.** Contract says strength 0–1 (p.27); v1 validator caps at 0.6. *Interpretation:* accept 0–1 per contract; warn above 0.6.
4. **`fade` transition** appears in the plan enum (p.27) but not in the transition table (p.19). *Interpretation:* `fade` = plain 0.5 s crossfade, allowed.
5. **Music-only outro length.** Analyze adds ~7.5 s (p.17); scriptwriter says 6–8 s (p.35); v1 scriptwriter SKILL says 4–6 s; end card ≥ 3.5 s. *Interpretation:* 6–8 s outro (default 7.5), end card 3.5–5 s inside it.
6. **Hook window.** "first second" (p.19), Critic "first 1.5 s" (p.40), Sheet/scriptwriter "first 2 seconds" (p.33, 35). *Interpretation:* hook text visible at full opacity from frame 0 through ≥ 1.5 s; the spoken hook is the first ~2 s.
7. **M3 suite cases.** Spec: photos only; clips only; voice + music; music only (no voice); HEIC (p.51). v1 suite: photos+music, clips+music, voice+music, combined track, HEIC. *Interpretation:* "photos only" = no audio at all (exercises the music fallback), "clips only" = clips with their own sound, "music only" = photos + music; keep combined track as an extra case.
8. **Music source order.** Failure table: generate → Music Library → natural sound (p.5); Drive filing rules: folder music → Music Library by card mood (p.32); music section: generated → Sound Collection → commercial library (p.19). *Interpretation:* folder file > card-specified Library track > Higgsfield-generated > Library by mood > natural sound + offline pad; Sound Collection only at posting time.
9. **Insights timing.** Pull at 48 h and 7 days (p.47) but judge each reel at 72 h (p.34). *Interpretation:* add a 72 h pull (or judge on the first pull at/after 72 h).
10. **Auto-posting.** "Not the goal (v1)" (p.3) vs default "post automatically" (Q34, p.56) and lawyer review required first (p.2). *Interpretation:* auto_post default true but blocked until `legal_review_done` is true; approval switch exists, off by default.
11. **Sheet columns.** Spec list (p.33) differs from v1 plan-month (adds Series, Pillar, Trial Reel?; lacks Template, Reel link). *Interpretation:* spec columns required, extra columns allowed.
12. **Audio sample rate.** Spec: 48 kHz always, hard gate (p.19, 40); v1 brand-check accepts 44.1 kHz. *Interpretation:* 48 kHz only.
13. **Critic frames.** Critic gets "QA strip" plus "12 frames" (p.40) while finish writes a 6-frame strip (p.18). *Interpretation:* keep the 6-frame strip and add a separate 12-frame extractor.
14. **Clips per reel.** "2–4 best hero photos" (p.17), "2–3 hero stills" (p.42), NFR "up to 4" (p.48). *Interpretation:* 2–3 typical, 4 max.
15. **Monday digest** is sent Sunday 6 pm (p.45, 50); name kept as "Monday digest".

## v2.1 additions (user request, 2026-11-13): Claude Design carousels, carousel and single-photo posts

- **R328** `INSTR` Component carousels are designed in Claude Design (Artifact type "Design"): one canvas per carousel, one 1080×1350 artboard per slide, in NUMA's brand. Slides can be pure components (title, numbered point, stat, myth/fact, quote, steps, price/offer, CTA) or include photos. *Accept:* designer agent + numa-carousel skill describe the full flow with exact Artifact calls.
- **R329** `DATA` A NUMA carousel component library ships in the plugin (plain HTML/CSS templates with fields, brand fonts bundled under open licences). *Accept:* each component renders standalone at 1080×1350.
- **R330** `CODE` `design_render.py` turns a Claude Design canvas (files read with the Artifact tool into a local folder) into ordered 1080×1350 PNG/JPG slides with headless Chromium, waiting for fonts and failing loudly on missing fonts, wrong size or blank slides. *Accept:* renders a canvas folder; tests with fixtures.
- **R331** `CODE` Fallback: the same renderer builds slides straight from a `carousel.json` spec with the bundled components when the Artifact tool or canvas is unavailable, so posting never blocks. *Accept:* identical layout; tests.
- **R332** `CODE` Carousel copy passes the claims scanner and per-slide fit checks (text fits its component box). *Accept:* validator rejects overflowing or banned text.
- **R333** `INSTR` Photo carousels can be built from a folder of photos (not only from a reel), graded and framed by the engine. *Accept:* documented path + command.
- **R334** `CODE` Single-photo posts: one 1080×1350 (4:5) image from a chosen photo, NUMA grade, smart-framed crop, optional short text overlay within safe areas. *Accept:* script output + tests.
- **R335** `INSTR` `/post-reel` publishes carousels (child containers + CAROUSEL container) and single images (IMAGE) through Composio, with the same gates, limits, AI label and Sheet updates as reels. *Accept:* exact tool flow documented; tests check tool names and gates.
- **R336** `INSTR` The month planner, shoot cards, daily build, digest and dashboard handle the post types reel / component carousel / photo carousel / single photo / stories; the content mix and default week include them. *Accept:* plan-month, build-today, shoot_card.py, digest_data, dashboard and config updated with tests.
- **R337** `CODE` Metrics store tags each post with its post type and the dashboard breaks results down by post type. *Accept:* tests.
- **R338** `CODE` `/numa-setup` checks headless Chromium is available for slide rendering (with the install command as the fix). *Accept:* setup_check line + test.

## v2.1 scheduling reliability (user request, 2026-11-13): the Mac is on and off like a normal Mac

- **R339** `CODE` `ensure_env.py`: an idempotent environment bootstrap every scheduled or manual command runs first. It installs or verifies the Python packages from requirements.txt, ffmpeg (system or imageio fallback), the faster-whisper model cache, and headless Chromium for slide rendering. It has a fast path when nothing changed (a stamp keyed by the requirements hash) and a clean ERROR naming what is missing and the fix; Jude is escalated only when it cannot self-heal. *Accept:* cold run installs, warm run < 5 s, tests.
- **R340** `CODE` `runlog.py`: every scheduled command records start/finish/outcome to `STATE/runlog.json` (synced to Drive). `runlog.py check` compares the log with the schedule in config/studio.json and lists runs that were missed, failed or are still running too long. *Accept:* tests over a synthetic week incl. DST.
- **R341** `INSTR` Watchdog: the 10 pm dashboard refresh and the 8 pm night check run `runlog.py check`. A missed or failed build gets a late build when it can still post the same day; otherwise the day is rescheduled. Jude gets one line; Katie never gets one. The Monday digest shows run health for the week. *Accept:* instructions + tests.
- **R342** `CODE`+`INSTR` Mac on/off: steps that need Claude in Chrome (signed-in Scout research, competitor log, Trial Reels, collab invites, AI label when the API can't set it, Higgsfield unlimited drafts) are queued in `STATE/chrome_queue.json` with a deadline and a fallback. Any run that finds Chrome available drains the queue, and an hourly desktop-only scheduled task drains it whenever the Mac is awake. When a deadline passes, the fallback runs: the post goes out without that feature, the step is noted in the digest, and nothing blocks. The planner avoids AI-animated people on days when the label can't be guaranteed. *Accept:* `chrome_queue.py` add/list/next/done/expire with tests; commands updated.
- **R343** `INSTR` Every scheduled prompt in docs/SCHEDULED_TASKS.md is self-contained and works even if slash commands don't expand. Setup verifies each task with "Run now" and checks that the runlog recorded it. *Accept:* doc + setup step + test.

## v2.1 adaptive strategy (user request)

- **R344** `DATA` A playbook ships in `skills/numa-scriptwriter/playbook/` (patterns, diagnosis, calendar, policies), valid against `schemas/playbook.schema.json`; every pattern has id, kind, name, formats, goals, template, claims-safe examples, evidence {level measured|observed|opinion|numa, sources, notes}, status, when_not and try_instead; seeds come only from the spec and the kit research, and no seed is `proven`. *Accept:* schema test; a test runs every example and template through claims_scan with no `fail` or `warn`. *(user request; spec p.8-11, p.33-35)*
- **R345** `CODE` `strategy.py` scores each judged post against NUMA's own rolling medians per post type with goal-specific weights (reach: views, sends/1k, skip, retention; saves: saves/1k; conversion: profile visits, follows, link clicks), winsorises outliers, and judges posts by per-post-type windows: ignored before the provisional pull, PROVISIONAL at reduced weight, FINAL at the final pull, never counted twice. *Accept:* tests on a synthetic store (pending/provisional/final, weights, metric exceptions). *(user request; spec p.34, p.47)*
- **R346** `CODE` `strategy.py plan --month` allocates the month (post types per week, weekdays, Central posting hours, offer weeks, events, hook/structure/CTA patterns per slot) with factored Bayesian models (Normal priors from the playbook, research weaker than NUMA's data, time decay) and Thompson sampling with an explicit exploration budget (Trial Reels first); cold start = the spec default week, data-led share = min(1, judged posts / 30); same inputs + seed = identical plan. *Accept:* cold-start, determinism and synthetic-learning tests (allocation shifts toward the true winners within 6-8 weeks while exploration stays at or above the budget's weekly share). *(user request; spec p.34 rule 10)*
- **R347** `CODE` Planning rules win over the bandit: every plan passes shoot_card.py's checks (14-day topics, one sales post a week, closures, collab, Meet the Collective, signature, series, event teaser/recap windows, cadence, mix), retired patterns are never planned, and a plan that still breaks a rule with the bandit off exits 1. *Accept:* rule-compliance tests with events and closures. *(spec p.34)*
- **R348** `CODE` `strategy.py learn` promotes, retires, demotes or starts testing patterns by research-backed thresholds and minimum samples, writes a dated changelog in plain sentences and the "Do more of / Do less of" lines; `explain SLOT` says why a slot got its type, time and patterns; `diagnose` matches underperformers to the diagnosis table and the next plan favours the documented fix. *Accept:* tests. *(user request; spec p.45-47)*
- **R349** `CODE` `strategy.py import-research` parses the R1-R7 deep-research outputs (markdown or Doc text in the prompts' field lists and tables, including the R7 judging-window tables with per-metric exceptions and Story windows under 24 h), adds candidates and priors with evidence levels, de-duplicates by id and name, rejects examples that fail claims_scan, and never overwrites NUMA's own data. *Accept:* fixture import tests. *(user request; docs/RESEARCH_PROMPTS_PLAYBOOK.md)*
- **R350** `INSTR` The Strategist agent owns the learning loop (learn, diagnose, plan, a schema-valid weekly brief in STATE with which posts are still provisional), the Scriptwriter executes the brief from `skills/numa-scriptwriter/ADAPTIVE.md` (patterns from the plan, `pattern_ids` and `strategy_arm` tags, documented fixes, no retired pattern, claims safety), and the tags flow into metrics.py (CONTRACTS section 9). *Accept:* agent/skill lint tests; brief validates against `schemas/strategy_brief.schema.json`. *(user request; DECISIONS D23)*
