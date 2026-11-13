# Status

| Task | State | Round | Open findings |
|------|-------|-------|---------------|
| T0 Foundation | ACCEPTED (review PASS x2, 223 unit tests green) | 2 | 2 minor logged below |
| T1 Engine | ACCEPTED (re-review 11/11 PASS) | 2 | 2 minor logged |
| T2 Analyze | ACCEPTED (re-review PASS 7/7; orchestrator fixed minor: no script alignment on mismatch) | 2 | |
| T3 Finish | ACCEPTED (round 3 re-review 4/4 PASS) | 3 | 2 minor logged |
| T4 Validator/baseline/claims | ACCEPTED (re-review 10/10 PASS) | 2 | cosmetic: duplicate hits per rule |
| T5 Vision/prep | ACCEPTED (re-review 6/6 PASS) | 2 | minor: color_range tag on OpenCV path |
| T6 Formats | ACCEPTED (re-review 6/6 PASS) | 2 | minors logged |
| T7 Ops scripts | ACCEPTED (round 3 re-review PASS) | 3 | |
| T8a Director+librarian/scout/analyst | ACCEPTED (9/10; --template depends on T12, verified in T11) | 2 | |
| T8b Crew agents + skills | ACCEPTED (re-review 8/8 PASS) | 2 | |
| T9 30-day system | ACCEPTED (re-review 6/6 PASS) | 2 | |
| T10 Setup/posting | ACCEPTED (re-review 7/7 PASS; 2 minors fixed by orchestrator) | 2 | |
| T12 Templates/prefs/kinetic/rule41 | ACCEPTED (re-review 5/5 PASS) | 2 | minors logged |
| T11 Integration | ACCEPTED (re-review 6/6 PASS) | 2 | |

## Minor findings (all resolved)
All minor findings logged during review rounds (example-plan whip spacing, claims gaps/false positives, finish loudness loop, render cache in synced folders, shoot_card BrokenPipe, D18 NUMA_BRAND wiring, formats/baseline sentence fragments, rule 24 counting, card clause length, analyze role guess, transcript capitals and dropped words, outro-aware caption spans, music-only reel length, myth_vs_fact hook, caption legibility over bright frames, prep colour tags, macOS CI, real-3.10 parse) were fixed in the round revisions or the final polish tasks P1-P3.

Open for the user: empty folder `/nonexistent_ro/x` left by a reviewer test outside the repo (the sandbox blocked its removal).

## Traceability (Phase 5)

Totals: 315 PASS, 0 FAIL, 12 EXTERNAL of 327. Verified by three independent Opus verifiers on 2026-11-12/13; post-verify fixes re-checked by the final polish review.

| R# | Result | Evidence |
|---|---|---|
| R1 | PASS | .claude-plugin/plugin.json name numa-studio, version 2.0.0, description present |
| R2 | PASS | marketplace.json plugins[0] numa-studio, source ./, version 2.0.0 = plugin.json |
| R3 | PASS | 4 skills/*/SKILL.md, frontmatter name+description each |
| R4 | PASS | make-reel/plan-month/numa-setup have description; $ARGUMENTS make-reel.md:59, plan-month.md:8 |
| R5 | PASS | all 8 agents/*.md have name, description, model, tools |
| R6 | PASS | reel-editor SKILL: numeric tables §4, Year One §8, LOOK steps 6.7, §7.1 |
| R7 | PASS | fix_transcript.py, formats.py srt_cues, claims_scan.py, qa_frames.py exist |
| R8 | PASS | analyze/baseline/validate/engine/finish/fix_transcript run from cwd /; all 24 scripts --help rc 0 |
| R9 | PASS | engine reads plan only; brand.json used only for defaults if plan omits (engine.py:521,545) |
| R10 | PASS | SKILL.md:15 JOB raw/work/out; make-reel.md:92 files-on-disk state table |
| R11 | PASS | grep urllib/requests/http/socket in scripts: none; analyze ran with HF_HUB_OFFLINE=1 |
| R12 | PASS | make-reel.md:125 + F17 row :226 Chrome-unavailable -> web search, library, brand photos |
| R13 | PASS | make-reel.md:58-65 resolution order incl. plan row, newest folder, chat attachments |
| R14 | PASS | librarian.md §1 steps 1-2 download into raw/, subfolders kept |
| R15 | PASS | mixed-case .JPG/.Jpeg/.PNG/.WEBP/.HEIC/.MOV/.M4V/.M4A/.WAV fixture: 5 photos, 2 clips, roles right |
| R16 | PASS | sauna.HEIC -> work/media/sauna.jpg in analysis.json |
| R17 | PASS | guess_role: vo/voice/memo/music/song/track/bgm right; voiceover_and_music.mp3 -> master (note: voice_track.wav -> master) |
| R18 | PASS | make-reel.md:125-129 step 4 scout first, then library, then brand photos; scout.md order |
| R19 | PASS | 12 s voice+music -> master 19.5 s; 58 s voice -> 60.0 s; music low band -36 dB in speech vs -23 dB outro |
| R20 | PASS | Year One combined -> master.wav 48 kHz stereo, ebur128 I -15.1 LUFS |
| R21 | PASS | analyze.py:51,471-473 small.en int8 word_timestamps float32 decode; Year One transcript has "Mobile." |
| R22 | PASS | 'This' start 0.0 end 1.08 -> appear 0.68, end kept |
| R23 | PASS | photos + music-only folder: words 0, voice_present false |
| R24 | PASS | faster_whisper ImportError stub: analyze rc 0, words 0, WARN printed |
| R25 | PASS | 100 BPM synthetic music -> bpm 99.38, 45 beats |
| R26 | PASS | contact_photos.jpg labels P0..P4; contact_clips.jpg "C0 @0.5s"... 1 frame/s (viewed) |
| R27 | PASS | 4 produced analysis.json validate vs schemas/analysis.schema.json (jsonschema) |
| R28 | PASS | fix_transcript: Kitty->Katie, Moby.->Mobile. (script), timing kept (note: missing 'And' leaves 'we' lowercase) |
| R29 | PASS | photos sharpness/brightness/size; clips brightness/shake/sharpness in analysis.json |
| R30 | PASS | make-reel.md:138-142 step 5; SKILL Step 6 with plan row/ratings/prefs inputs |
| R31 | PASS | motion.md §1 balance, get_cost dry run, 9:16, kling 5 s draft->pro keeper, Seedance people-free, video shots |
| R32 | PASS | motion.md §4 locks/no new objects; §6 start/middle/end frames, drop warped faces/text |
| R33 | PASS | README.md:209 no-credit path; make-reel.md:149; suite runs with no Higgsfield |
| R34 | PASS | engine preview 8 times -> preview.jpg 1800x1280 = 5 tiles x 2 rows |
| R35 | PASS | SKILL 6.7-6.8; editor.md:21-30 look/fix/repeat |
| R36 | PASS | Year One render: h264 1080x1920 30/1, 1169 frames = 38.97x30; rawvideo pipe engine.py:962 |
| R37 | PASS | finish chain HP85, EQ180/3800/7000 cuts, LP11k, aecho, acompressor, loudnorm -15, 48k, fades; --clean-voice drops aecho (finish.py:70) |
| R38 | PASS | out mp4 h264 High + aac 48000 2ch ~192k; moov@36 before mdat@43474 |
| R39 | PASS | out/qa_strip.jpg 1620x480 |
| R40 | PASS | out/report.json loudness I/TP/mean + stdout; mean<-28 warn finish.py:462, test_quiet_output_warns |
| R41 | PASS | make-reel.md:197-202 chat first, Finished/ upload, §6 note: story, 3 captions, Decisions |
| R42 | PASS | SKILL 4.1 one beat per spoken line, picture illustrates words |
| R43 | PASS | SKILL 4.1 table: transformation/offer/event recap sequences match spec p.18 |
| R44 | PASS | SKILL 4.2.1 strongest image never logo; validator rule 39 ERROR on wordmark shot 0 |
| R45 | PASS | validate: 2 wipes WARN; no wipe/no flash WARN [rule 18] |
| R46 | PASS | cut shifted 100 ms -> WARN rule 14; baseline plan has no beat warnings |
| R47 | PASS | SKILL 4.3 2-beat before, 4-beat holds, outro montage (D15) |
| R48 | PASS | 11-beat shot WARN rule 15; same with peak:true no warning |
| R49 | PASS | end card 3.0 s -> WARN rule 32 |
| R50 | PASS | engine.py:88,743-746 zoom 1.16->1 over 0.22 s + white lift; preview at 2.0 s shows lift |
| R51 | PASS | engine.py:698-710 slide 0.28 s blur 160 px; all-whip plan WARN rule 16 |
| R52 | PASS | engine.py:412 auto leak; preview at leakfade (no leaks entry) shows warm leak |
| R53 | PASS | engine.py:751-753 white flash 0.9 decaying over 0.35 s; preview at 6.0 s white |
| R54 | PASS | Year One preview at 6.7 s: glowing vertical line splitting before/after |
| R55 | PASS | shot0 whip ERROR rule 8; punch WARN rule 9; fade in enum/engine |
| R56 | PASS | all-punch 23-shot plan WARN rule 17 |
| R57 | PASS | z [1.1,1.1] WARN rule 11; baseline alternates [1.02,1.14]/[1.14,1.02] |
| R58 | PASS | 840x548 exterior at z 0.95, pan +-0.5: frames filled, no bars/mirroring (viewed) |
| R59 | PASS | engine_media.py:236 warpAffine INTER_CUBIC float64 matrix, cubic motion_ease |
| R60 | PASS | grade before: (200,80,60)->(145,92,87), gray B>R, black 10->20 |
| R61 | PASS | grade warm: (200,80,60)->(219,75,50), gray R>B, S-curve; none unchanged |
| R62 | PASS | flat white plan: corner 83 vs centre 254; bloom/leak/grain/gradient engine.py:384,758-863 |
| R63 | PASS | leaks strength 0.9 validates (WARN rule 33) and renders a leak |
| R64 | PASS | preview at appear+0.1 s shows partially faded word; rise 22/0.28 s config |
| R65 | PASS | config captions.font_px 92; gold italic accent words seen in previews |
| R66 | PASS | long line -> ERROR "wraps to 6 rows" rule 22, measured with PIL truetype font |
| R67 | PASS | caption_y 1800 / 150 -> ERROR outside 230-1728 rule 25 |
| R68 | PASS | face box at caption height on shot: engine moved caption block 1382->1538 px |
| R69 | PASS | end-card preview: ripple, white wordmark, spaced uppercase tagline, gold italic sign-off |
| R70 | PASS | Year One frame 0 lum 72.7 = frame 6; motion from frame 1; logo shot 0 is ERROR |
| R71 | PASS | hook text full opacity in frame 0 preview |
| R72 | PASS | last frame mean lum 0.7 (from 92 at -0.8 s) |
| R73 | PASS | SKILL §2 rule 3 sound-off |
| R74 | PASS | ducking measured (R19): -36 dB under voice, -23 dB in outro |
| R75 | PASS | 70 s plan WARN rule 7; 200 s ERROR rule 6 |
| R76 | PASS | SKILL §2 rule 2 (45 s ~100 words, 10-14 shots); scriptwriter rules 1, word limit |
| R77 | PASS | SKILL §2 rule 7 order per interpretation 8, never trending, sources.py -> sources.txt |
| R78 | PASS | scriptwriter SKILL rule 3 share line; reel-editor SKILL §2 rule 1 |
| R79 | PASS | schemas/analysis.schema.json validates produced analysis.json |
| R80 | PASS | plan.schema.json $defs shot covers all fields; both example plans validate; bad tr enum rejected |
| R81 | PASS | schema_version const 2 (analysis), enum 1/2 (plan); outputs carry 2; report.json schema_version 1 |
| R82 | PASS | bad tr/look -> "ERROR ... is not one of" rc 1, no traceback |
| R83 | PASS | gap and overlap fixtures -> ERROR rule 2 |
| R84 | PASS | 0.3 s shift WARN, misspelled WARN, 0.7 s shift ERROR rule 24 |
| R85 | PASS | missing font/src/logo -> ERROR rule 5 |
| R86 | PASS | relative src ERROR rule 4; 200 s ERROR rule 6 |
| R87 | PASS | 1-element word ERROR (no traceback); line end before last word ERROR rule 20 |
| R88 | PASS | video start 5.5+2.4 > 6 s clip -> WARN rule 12 |
| R89 | PASS | truncated/empty JSON, missing plan/analysis -> "ERROR ..." rc 1, no traceback |
| R90 | PASS | editor.md:21-30, SKILL 6.5, make-reel step 7 |
| R91 | PASS | make-reel F1 row clone(consent)->preset->music-only text |
| R92 | PASS | baseline --script on music-only: 8 lines from script, line starts on beats, valid plan |
| R93 | PASS | make-reel F2 row Higgsfield->Music Library->nat+pad |
| R94 | PASS | photos-only folder -> pad.wav/master.wav; rendered+finished 16 s, -15 LUFS, aac 48k |
| R95 | PASS | make-reel F3 row |
| R96 | PASS | audio-only folder: plan shots from assets/brand-photos + heroimage |
| R97 | PASS | make-reel F4 + motion.md F4 row |
| R98 | PASS | make-reel F5 row |
| R99 | PASS | make-reel F6 row (prep_media.py) |
| R100 | PASS | motion.md §7 F7 row + make-reel F7 |
| R101 | PASS | make-reel F8 row; motion.md F8 |
| R102 | PASS | make-reel F9; analyst.md §2 F9 |
| R103 | PASS | make-reel F10 row |
| R104 | PASS | make-reel F11 row |
| R105 | PASS | make-reel F12 row |
| R106 | PASS | blur [[0.3,0.55,0.5,0.4]] renders region unrecognizable (side-by-side viewed) |
| R107 | PASS | make-reel F13 row |
| R108 | PASS | make-reel F14 row; draft command verified renders 1080x1920 |
| R109 | PASS | make-reel F15 row incl. Monday digest note |
| R110 | PASS | make-reel.md:206 rows in order, log fallback F<n>.<move>, never ask Katie |
| R111 | PASS | make-reel.md:8,22-32 authority table; month topic/goal/template decided by Director in plan-month.md:8,91 |
| R112 | PASS | make-reel.md:12; reel-editor SKILL:8; every agents/*.md "never contact Katie"; scriptwriter SKILL:8 |
| R113 | PASS | make-reel.md:13; grep approv/confirm: only post-reel off-by-default hold switch (interp. 10), non-blocking |
| R114 | PASS | make-reel.md:14 "Never stop"; failure table F1-F17 + Reschedule (make-reel.md:204-228) |
| R115 | PASS | make-reel.md:15-19 credits/consent/music/claims as fixed rules |
| R116 | PASS | make-reel.md:241-258 delivery note, "No questions, no let me know" |
| R117 | PASS | make-reel.md:67 plan row + note.txt re-read each run, never required |
| R118 | PASS | make-reel.md:34-44 Jude-only table w/ exact fixes + workarounds; brand.json escalation.contact |
| R119 | PASS | tests/unit/test_instructions_director.py:405-505 lint over commands/agents/skills; suite 1131 passed |
| R120 | PASS | scout.md:18-26 five-step order matches spec p.4-5 |
| R121 | PASS | scout.md:30-31 no other creators' content; members only with Consent List |
| R122 | PASS | scout.md:33-39; sources.py add wrote out/sources.txt with file/kind/source URL/license/date |
| R123 | PASS | make-reel.md:125 Scout before weaker substitutes; :136 "You decide what to use from the Scout's finds" |
| R124 | PASS | scout.md:11-16 WebSearch/WebFetch fallback; SETUP_GUIDE.md:63 desktop-task option (D8) |
| R125 | PASS | scout.md:4 model sonnet (mid), :7 paired with Librarian; config models.agents.scout |
| R126 | PASS | claims_scan.py exit 1 on all 31 spec terms (inflammation..norepinephrine); FDA logo = visual, critic.md G1 |
| R127 | PASS | `claims_scan.py "Sauna cures stress"` exit 1 naming "cures"; clean text exit 0 (script named claims_scan.py) |
| R128 | PASS | NUMA_BRAND copy with new term "zorblax" -> validate_plan ERROR rule 27; default brand -> OK |
| R129 | PASS | `--hashtags "#detox"` exit 1 (banned + hashtags.never rule); base tags exit 0 |
| R130 | PASS | reel-editor SKILL.md:60; brand.json claims.banned hedges/proof_language |
| R131 | PASS | reel-editor SKILL.md:63-68 four modality rows incl. FDA-cleared exact-device exception |
| R132 | PASS | reel-editor SKILL.md:71 visuals rule; critic.md:39 G1 look check |
| R133 | PASS | reel-editor SKILL.md:72 testimonials experience-only, never repost/pin |
| R134 | PASS | numa-scriptwriter SKILL.md:49 rule 7; shoot_card.py check flags Ask the DPT sales |
| R135 | PASS | numa-scriptwriter SKILL.md:50 rule 8 guides/facilitators, licensed counselors only |
| R136 | PASS | brand.json claims.safety_line text+also; scriptwriter SKILL:48,50; caption SKILL:39 |
| R137 | PASS | numa-caption SKILL.md:50 #ad/"I get free sessions" in video + first line; reviews never bought |
| R138 | PASS | brand.json claims.dosing_line.blocked=true; claims_scan exit 1 on "57 minutes of sauna...11 of cold a week" |
| R139 | PASS | validate rule 30 ERROR when ai_generated/ai.scenes w/o label_required; post-reel.md:72-77 applies label |
| R140 | PASS | brand.json offerings.not_offered (5 items); critic.md G1/G6; motion.md prompt rule 7 |
| R141 | PASS | validate: people w/o consent ERROR r28, music missing ERROR r29, claim ERROR r27; sources.py check ERROR no license |
| R142 | PASS | plan.schema.json music.license, $defs/shot people/consent/ai_generated/blur, ai.label_required |
| R143 | EXTERNAL | Lawyer review. brand.json posting.legal_review_done=false gates post-reel.md:26 (gate 3); adequate |
| R144 | PASS | brand.json business.name, socials ig/facebook/ios_app, voice, assets wordmark/secondary/endcard/brand_photos_dir, palette, fonts, endcard; each with status |
| R145 | PASS | brand.json founders, location, facility, offerings.sessions, team.collective, booking, hours, site_lines, not_offered, phone (status each) |
| R146 | PASS | positioning.series 5 w/ what/length_s/built_for; collab_partners ordered 1-5; target_audiences |
| R147 | PASS | brand.json _status_legend (confirmed/from_website/research/needs_katie); reel-editor SKILL.md:23 prefer confirmed |
| R148 | PASS | transcript_fixes: Mobile, NUMA, Katie, Scott (Scot/Skot/Skott), Dauphin |
| R149 | PASS | brand copy caption_gold #00FF00 + tagline -> baseline accent_rgb [0,255,0]; preview shows green gold words + new tagline |
| R150 | PASS | all 4 SKILL.md reference brand/brand.json keys (reel-editor:21, scriptwriter:14, caption:10, brand-check rows) |
| R151 | PASS | NUMA_BRAND bad file -> "does not match brand.schema.json: missing required field 'business'; ...must be array"; broken JSON -> readable, exit 1 |
| R152 | PASS | assets/: Numa_Workmark_Dark.png, Numa-Phoenix-transparent.png, heroimage.jpg, 6 brand-photos, LiberationSerif x2 + LICENSE |
| R153 | PASS | commands/brand-setup.md writes keys status confirmed, validates (setup_check), saves STATE + plugin copy |
| R154 | PASS | plan-month.md:2,8,12 monthly task (config cron 24th 9 pm), no approval |
| R155 | PASS | plan-month.md:24-46 offers, events, closures, last month dashboard, season + Mobile moments |
| R156 | PASS | `shoot_card.py sheet --csv` header exact 13 spec columns; STATUSES enum shoot_card.py:111 |
| R157 | PASS | plan-month.md:117-133 _Plan/ Sheet, Music Library (mood_bpm_title), Digests; month/day folders w/ photos/clips/Finished + SHOOT CARD |
| R158 | PASS | `shoot_card.py month 2026-12` -> 31 rows, "Day 01 - 2026-12-01 - <Title>", Tue=carousel, film_by |
| R159 | PASS | check on good Dec fixture exit 0; crafted: topic repeat, 2 sales/wk, closure invite, cadence, no collab, no MtC, event window -> exit 1 |
| R160 | PASS | plan-month.md:91 cadence; shoot_card check cadence 4-5 feed + 1-2 Trial/week |
| R161 | PASS | brand.json positioning.content_mix sums 1.0 (30/25/15/15/15); plan-month.md:48-59 re-weight |
| R162 | PASS | plan-month.md:68-76 default-week table; skeleton slots match (Sun regulate_reel, Mon ask_the_dpt) |
| R163 | PASS | brand.json posting.posting_time late afternoon Central; plan-month.md:53-57; config judge_at_hours 72 |
| R164 | PASS | plan-month.md:80 rule 1; enforced by shoot_card check rule 1 |
| R165 | PASS | scriptwriter SKILL.md:43 rule 1, :51 collabs never reposts; reel-editor SKILL.md:45,48 |
| R166 | PASS | plan-month.md:83 rule 4; check 4-collab / 4-meet-the-collective |
| R167 | PASS | trend-check.md:105-115 Friday NWS 7-day forecast thresholds, weather hook swap |
| R168 | PASS | plan-month.md:85-87 rules 6-8; check 6-signature, 7-event-window, 8-closure |
| R169 | PASS | plan-month.md:97-100; check rule 9 (<=2 sessions/week, film_by before day) |
| R170 | PASS | plan-month.md:53-58,89 re-tune mix, lengths, posting hours after 30 reels |
| R171 | PASS | brand.json positioning.series five defs; plan-month.md:91 all five monthly; check "series" rule |
| R172 | PASS | plan-month.md:83 "Sweat there, recover here" Mission Fitness first...; brand.json collab_partners order |
| R173 | PASS | make-reel.md:197-202 Finished/, row "Ready to post", post-reel handoff; build-today.md:84-89 |
| R174 | PASS | commands/night-check.md (8 pm task): card compare, Scout, substitutes/swap, statement heads-up :45-49 |
| R175 | PASS | `shoot_card.py card` output: DAY · date · title · FILM BY, WHERE TO PUT FILES, WHAT TO FILM (line refs), READ, MUSIC, LENGTH, IF YOU CAN'T |
| R176 | PASS | card: photos/ clips/, "voiceover NN" re-record, music optional / MUSIC line per source (Music Library by mood), any names, phone settings, Sheet optional |
| R177 | PASS | stories row card first line "NO FILMING NEEDED. ..." |
| R178 | PASS | script check errors: 9 new shots, 0/2 AI shots, people w/o needs_consent, word limit; card "(consent list only)" |
| R179 | PASS | schemas/script.schema.json has all listed fields (+caption); spec example validates (jsonschema) |
| R180 | PASS | `shoot_card.py script` exit 1 on words>86, 9 new, 0/2 ai, consent, missing framing/seconds, bad line, "inflammation" |
| R181 | PASS | digest.md:174 by room then time of day w/ total; digest_data.py:52-61 rooms + minute estimate |
| R182 | PASS | plan-month.md:101 library_tags/source library; librarian.md:52-55 library.py add with tags |
| R183 | PASS | FIXED post-verify (librarian batch voiceover routing); minor: card says "voiceover NN" but agents/librarian.md has no routing step; plan-month.md:103 claims librarian routes (done by Director in night-check.md:23) |
| R184 | PASS | plan-month.md:86,102 capture moments (`during`) |
| R185 | PASS | plan-month.md:104; night-check.md:8 "never a reminder to film" |
| R186 | PASS | scriptwriter SKILL.md:3,118 month pass; plan-month.md:93-95; one-off mode :120 |
| R187 | PASS | scriptwriter SKILL.md:26-27 hook 2 s; words <= 2.3 x (length-outro), 6-8 s outro; checker enforces |
| R188 | PASS | scriptwriter SKILL.md:28-30 numbered shots tied to lines, framing, hold 5 s, one AI shot, photos, audio direction |
| R189 | PASS | script.schema.json cta + caption + on_screen; scriptwriter SKILL.md:31-39 goal-matched CTA table |
| R190 | PASS | FIXED post-verify (card "normal voice"); minor: card RECORDING_TIPS (shoot_card.py:161) omits "normal talking voice" (spec p.35 "too loud" fix); only in SKILL.md:30 |
| R191 | PASS | scriptwriter SKILL.md:48 rule 6 claims on every line via shoot_card script; :119 missing-material rewrite |
| R192 | PASS | skills/numa-scriptwriter/templates.json 11 templates w/ arc, beat_count, typical_length_s, signature_moment |
| R193 | PASS | templates.json presets: numa_nights_recap, class_spotlight_reel, member_story_reel, offer_promo_discover, education_three_things, holiday_hours |
| R194 | PASS | baseline_plan.py --template for all 17 ids -> validate_plan exit 0, 0 ERRORs |
| R195 | PASS | education_three_things rendered: big "1" kinetic card at 7.0 s (looked at frame); MYTH/FACT cards in preview |
| R196 | PASS | make-reel.md:6-8 Director script (reads row + folder, plan, crews, go/no-go) |
| R197 | PASS | agents/librarian.md haiku; download, HEIC convert, card check, inventory.json w/ missing |
| R198 | PASS | agents/analyst.md sonnet; analyze/fix_transcript/vision, ratings.json + best_window |
| R199 | PASS | agents/motion.md sonnet; upload hero only, inspect/drop warps, ledger gate, motion.json credits_spent |
| R200 | PASS | agents/copywriter.md haiku; 3 captions, 1 recommended, Story line, email paragraph |
| R201 | PASS | agents/editor.md sonnet "only agent that renders"; validate/preview/render/finish/check/qa_frames |
| R202 | PASS | agents/critic.md opus, fresh context, never reads decisions.md/Editor hand-back |
| R203 | PASS | agents/scout.md (sonnet, Chrome tools), agents/scriptwriter.md (sonnet) |
| R204 | PASS | config/studio.json models (tiers+agents); no claude-* model ids anywhere; frontmatter aliases match config (test) |
| R205 | PASS | make-reel.md:73-88 parallel crews table; editor renders; critic after each render |
| R206 | PASS | critic.md:11-22 qa_strip, 12 critic frames, report.json loudness, transcript, plan, shoot card |
| R207 | PASS | `qa_frames.py reel plan` -> 12 JPGs + index.json (first second, cuts, last second) |
| R208 | PASS | critic.md:37-45 G1-G7 cover all listed gates; config critic.hard_gates |
| R209 | PASS | check_output.py fails fixtures: 44.1 kHz, letterbox, frozen, silent, clipped, 720x1280; real render ok. Claims via claims_scan |
| R210 | PASS | critic.md:49-58 weights 20/15/15/10/10/10/10/10; config critic.rubric |
| R211 | PASS | critic_score.py: all-4 =80 pass; hook 3 fail; cat 2 fail; gate fail; 78 fail |
| R212 | PASS | critic.md:73 virality second opinion, never changes verdict |
| R213 | PASS | critic.md:75-90 score table, numbered fixes naming plan.json field; unactionable fixes banned |
| R214 | PASS | make-reel.md:171-179 max 3 rounds, ship_best restores best version + logs weak points |
| R215 | PASS | make-reel.md:180 numa-brand-check on shipped version; critic brand_look |
| R216 | PASS | config/studio.json higgsfield.prices all 10 values match spec, prices_verified_on 2026-11-12 (D11 single config) |
| R217 | PASS | motion.md:34 get_cost dry run before every job, re-check ledger with quote |
| R218 | PASS | reel-editor SKILL.md:180-193 ranked uses 1-11 + Marketing Studio deferred (D5) |
| R219 | PASS | config budget.split 600/140/160/120/10/170 = 1200 |
| R220 | PASS | ledger.py check: day 15 630+40>660 BLOCKED exit 1; split + 150/reel blocks; `sheet` CSV mirror; motion.md:41 |
| R221 | PASS | SKILL.md:197 + agents/motion.md:22 reset monthly, refunds, draft cheap/finalize keepers |
| R222 | PASS | SKILL.md:195 + motion.md §4: motion not room, one move+size, keep clause, 720p, safe/risky, Kling order |
| R223 | PASS | motion.md §5: all 7 prompts with models (Kling x6, Seedance walkthrough) |
| R224 | PASS | motion.md §3 "Model choice by faces" Kling-with-person, Seedance people-free |
| R225 | PASS | motion.md §2.2 + SKILL.md:199; brand.json consent.ai_processing_covered (null, needs_katie) |
| R226 | PASS | SKILL.md:197, motion.md §1 "Never ... Reframe (245)" |
| R227 | PASS | motion.md §1 unlimited window -> scout.md:53-59 via Chrome after terms check |
| R228 | PASS | numa-setup.md:50; `ledger.py report --balance 1000` -> "covers 20 reels at 48.75 credits/reel" |
| R229 | PASS | `engine.py --size 1080x1350` -> ffprobe 1080x1350 |
| R230 | PASS | Year One reel ffprobe 1080x1920, 38.97 s |
| R231 | PASS | yo_reach.mp4 11.10 s 1080x1920, check_output --kind reach OK; hook text in frame 0 (viewed) |
| R232 | PASS | 4 story JPGs 1080x1920 |
| R233 | PASS | 6 carousel JPGs 1080x1350 |
| R234 | PASS | yo_cover.jpg 1080x1920, title at y~850-1070 (viewed; JPG not PNG) |
| R235 | PASS | yo.srt 9 cues = 9 plan lines; times from transcript |
| R236 | PASS | agents/copywriter.md:3,13-14 (3 captions, Story line, email para) |
| R237 | PASS | formats.py one plan -> 16 files; make-reel.md:199 uploads out/ to Finished/ |
| R238 | PASS | commands/digest.md §3: Doc in _Plan/Digests, notification/email, never asks |
| R239 | PASS | digest.md §2 six sections |
| R240 | PASS | digest_data.py on fixtures -> six-section text, byte-identical rerun |
| R241 | PASS | commands/trend-check.md §2 (in command, not scout.md); never songs, own audio/Sound Collection |
| R242 | PASS | trend-check.md §3-4: 3 ideas, link/fit/how, winner Trial Reel, slot optional |
| R243 | PASS | SETUP_GUIDE.md:24 + numa-setup.md:45 Instagram Login, 3 scopes |
| R244 | PASS | config/studio.json instagram.graph_api_version v26.0 (D11 location, not brand.json); post-reel.md:53 |
| R245 | PASS | dashboard-refresh.md §2: 48h/72h/7d + user insights, stored forever |
| R246 | PASS | metrics.py ingest of `plays` -> ERROR, exit 1; schema metrics stored |
| R247 | PASS | config instagram.tags 9 tags; metrics.py tag |
| R248 | PASS | compute: r1 retention 12/30=0.4, sends 8/900*1000=8.889 correct |
| R249 | PASS | dashboard.py fixture -> self-contained HTML with all sections (Py>=3.11 only, see R326) |
| R250 | PASS | scout.md:62-71 + brand.json positioning.competitors (5 named) |
| R251 | PASS | FIXED post-verify (docs/examples/metrics.example.json); Instructions OK (dashboard-refresh §4, D7) but no sample metrics.json file; only docstring shape |
| R252 | PASS | plan-month.md:48-59 re-weight mix/series/length/hours/edit rules -> digest_notes |
| R253 | PASS | post-reel.md §4: REELS create, 3-5 min wait, 100/24h, no container >24h, same day |
| R254 | PASS | post-reel.md §5 Graph API proxy / Chrome / manual |
| R255 | PASS | post-reel.md §6 API->Chrome->manual+notify Jude |
| R256 | PASS | brand.json posting.require_approval=false, auto_post=true, legal_review_done=false gate |
| R257 | PASS | post-reel.md §3 5 pm Central default; §7.4 Facebook |
| R258 | PASS | numa-caption SKILL.md:35,40 |
| R259 | PASS | post-reel.md §7.1 Posted + permalink |
| R260 | PASS | post-reel.md §10 weekly GBP |
| R261 | PASS | config/studio.json schedule: 6 tasks with cron, America/Chicago |
| R262 | PASS | commands/plan-month, night-check, build-today, dashboard-refresh, trend-check, digest |
| R263 | PASS | build-today.md:35 phone notification |
| R264 | PASS | numa-setup.md §6 Always allow + permissions.allow list |
| R265 | PASS | numa-setup.md §1 pip, --break-system-packages, --user; imports via setup_check |
| R266 | PASS | numa-setup.md §2 3 s render + LOOK at qa_strip |
| R267 | PASS | setup_check.py 19/19 OK rc0; fake librosa -> one-line fix, rc1 |
| R268 | PASS | numa-setup.md §3 table Drive/Sheets/Higgsfield/Composio/Docs/Gmail/Chrome |
| R269 | PASS | numa-setup.md §4 ask once, store in setup.json |
| R270 | PASS | setup_check --download-model in step 2 |
| R271 | PASS | docs/SETUP_GUIDE.md covers every listed item (file name differs) |
| R272 | PASS | brand-setup.md: 51 questions, keys, "don't know" defaults (table, not setup/questions.json) |
| R273 | PASS | brand-setup.md:10,37; numa-setup.md:8 only places questions allowed |
| R274 | EXTERNAL | questionnaire + /brand-setup + SETUP_GUIDE adequate |
| R275 | PASS | SETUP_GUIDE.md:78-88 5 prompts, quarterly task numa-setup.md:110; prices_verified_on |
| R276 | PASS | prefs.py docstring format+example; _Plan + local copy |
| R277 | PASS | make-reel.md:71, SKILL 6.1 list + add |
| R278 | PASS | "fewer whips"x2 -> max_whips 0; baseline --prefs 0 whips; validate WARN rule 38 (E with --strict) |
| R279 | PASS | vision: Katie&Scott photo focus [0.60,0.21] on faces; engine uses focus |
| R280 | PASS | formats.py wrote yo_hook_1..3.mp4 (3.17 s, check OK) |
| R281 | PASS | SKILL.md 6.9 + motion.md §9 |
| R282 | PASS | vision.py clip fixture: per-second sharpness/motion/faces scores + windows |
| R283 | PASS | make-reel.md:65,225 F16 topic-only mode |
| R284 | PASS | nat burst t=8-10: 440 Hz tone +114 dB vs outside window, under music |
| R285 | PASS | library.py docstring schema; STATE/media_library.json (spec names no Sheet) |
| R286 | PASS | library add/query by tag returns dims, orientation, sharpness, faces |
| R287 | PASS | prep_media: shaky median flow 58.4->0.27 px; dark luma 33.2->52.5 |
| R288 | PASS | --draft 540x960, 16 s vs 237 s full |
| R289 | PASS | --workers 1 vs 4 draft and 1 vs 3 range: identical SHA-256 |
| R290 | PASS | --encoder videotoolbox falls back to libx264; NUMA_RENDER_CACHE |
| R291 | PASS | ffprobe: H.264 High 1080x1920 30fps yuv420p 7.3 Mbps; AAC 195k 48k stereo; moov@36<mdat; 36.6 MB |
| R292 | PASS | ebur128 peak=true: I -15.0 LUFS, TP -2.4 dBFS; mean -17.7 dB |
| R293 | PASS | 40 s draft 16 s; render.json timings logged |
| R294 | EXTERNAL | full drop-to-file 297 s and 231 s here (no Higgsfield); golden logs stage timings |
| R295 | PASS | motion.md §1 + digest.md §2 row 5 |
| R296 | PASS | re-run analyze/vision/prep/engine/finish: identical bytes; prep "unchanged" skip |
| R297 | PASS | two independent full runs: video_noaudio 8192553..., final e11fb8cf... identical |
| R298 | PASS | FIXED post-verify (macOS CI job); ci.yml runs ubuntu-latest only; no macOS job |
| R299 | PASS | FIXED post-verify (py3.10); requirements.txt ok; clean py3.10 venv: dashboard.py SyntaxError, 3 unit tests fail |
| R300 | PASS | grep: no paid API in scripts; free stock only |
| R301 | PASS | motion.md §2, SKILL.md:199, README privacy |
| R302 | PASS | assets/fonts/LICENSE; README licensing |
| R303 | PASS | CHANGELOG 1.0.0-2.0.0; plugin.json 2.0.0 |
| R304 | EXTERNAL | setup_check.py + marketplace.json (source ./) adequate |
| R305 | PASS | golden_year_one.py --pack: rc0, 416 s, report + comparison.jpg |
| R306 | PASS | golden: 107.7 BPM, transcript has "Mobile" |
| R307 | EXTERNAL | comparison.jpg + rating steps printed; adequate |
| R308 | PASS | run_tests.py 5/5 PASS (552 s) with the 5 spec cases |
| R309 | PASS | ci.yml on push/PR (but currently red, see R326) |
| R310 | EXTERNAL | motion.md + ledger.py adequate |
| R311 | EXTERNAL | scheduled-task commands + night-check adequate |
| R312 | PASS | FIXED post-verify (CHANGELOG golden note); CHANGELOG has one golden record for 2.0.0, not per addition |
| R313 | EXTERNAL | plan-month, scriptwriter, night-check, critic adequate |
| R314 | PASS | README release checklist; CHANGELOG release check |
| R315 | EXTERNAL | post-reel §6 + SETUP_GUIDE verify-first #1 |
| R316 | EXTERNAL | post-reel §5 both paths |
| R317 | EXTERNAL | SETUP_GUIDE verify #3, SCHEDULED_TASKS needs-Mac note |
| R318 | EXTERNAL | D7 implemented: metrics.json + Sheet + regenerated HTML |
| R319 | PASS | FIXED post-verify (real 3.10 suite green); CI parse/unit-3.10 jobs would fail on dashboard.py:287 |
| R320 | PASS | 30 bad-input calls: ERROR line, non-zero exit, 0 tracebacks |
| R321 | PASS | all 22 scripts --help print usage, rc0 |
| R322 | PASS | README install/setup/daily/tests/v2 |
| R323 | PASS | secret regex scan of tracked files clean |
| R324 | PASS | no test-pack-only media tracked; spec/ ignored; brand photos are spec-bundled assets |
| R325 | PASS | grep /tmp,/home,/mnt in scripts: none |
| R326 | PASS | FIXED post-verify (dashboard py3.10 syntax; real 3.10 parse); dashboard.py:287,291 backslash in f-string expr: SyntaxError on 3.10 |
| R327 | PASS | run_tests 5/5 and unit suite with dead proxy; transcription worked offline |
