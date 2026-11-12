# NUMA Studio gap audit

Status of every requirement in `REQUIREMENTS.md` against the repo as of v1.3.0 (commit 230a342 + DECISIONS.md). All non-binary repo files were read. EXISTS = meets the acceptance; PARTIAL = some of it; MISSING = absent. EXTERNAL items are rated on their in-repo supporting artifact.

## Test suite result

`python3 tests/run_tests.py` (Linux sandbox, Python 3.13.18, system ffmpeg, all deps importable) on 2026-11-12: **5/5 passed**, exit 0.

```
PASS  photos_music        69s  5 photos, 0 clips, 0 words, 99 BPM, 10.0s
PASS  clips_only         246s  0 photos, 2 clips, 0 words, 99 BPM, 10.0s
PASS  voice_and_music     75s  5 photos, 0 clips, 0 words, 99 BPM, 10.0s
PASS  combined_track      65s  5 photos, 0 clips, 2 words, 99 BPM, 10.0s
PASS  heic_photos         62s  5 photos, 0 clips, 0 words, 99 BPM, 10.0s
5/5 passed
```

Notes: total ~8.5 min for five 10 s renders; clip render is the slow path (246 s for 10 s). `combined_track` (pure synthetic music passed as `--master`) produced 2 hallucinated caption words, because only the auto-guessed music-only path skips Whisper. The suite checks only frame size, 48 kHz and duration (±0.6 s); it does not check loudness, true peak, codec profile, bitrate, faststart or determinism.

## 10 technical facts for the planner

1. **Five standalone scripts, no package.** `skills/numa-reel-editor/scripts/{analyze,baseline_plan,validate_plan,engine,finish}.py` run top-level code at import (analyze, engine, finish, baseline have no `main()`), so they cannot be imported or unit-tested without refactor. ffmpeg = `shutil.which` else `imageio_ffmpeg` (only engine guards the ImportError). Nothing reads `brand/brand.json`.
2. **CLIs.** `analyze.py <raw> <work> [--music F] [--voice F] [--master F]` → `work/master.wav`, `analysis.json`, `contact_photos.jpg`, `contact_clips.jpg`, scratch `a.raw`/`tmp.jpg`. `baseline_plan.py <work> [--duration S] [--subtitle TXT]` → `work/plan.json`. `validate_plan.py plan.json [analysis.json]` → WARN/ERROR lines, exit 0/1. `engine.py plan.json [preview t1 t2 …]` → `out_dir/preview.jpg` or `out_dir/video_noaudio.mp4`. `finish.py <work> <out.mp4> [--clean-voice]` → final MP4, `aud.wav`, `qa_0..5.jpg`, `qa_strip.jpg`; prints mean dB.
3. **Engine architecture.** Module-level script: loads plan, pre-builds a source per shot (`ImgSrc` = PIL load → crop → unsharp → `canvas()` 1296×2304 oversized canvas (portrait: cover-fit; landscape: 92%-height foreground over 80 px-blurred, 0.4-brightness fill) → grade once; `VidSrc` = OpenCV sequential reads + `canvas_fast` + per-frame grade). `render(t)` = `frame_at` (view via `warpAffine` INTER_CUBIC, **BORDER_REFLECT**, cosine ease) → bloom (quarter-res screen) → light leak (3 Gaussian blobs, seed `t//5`) → bottom gradient → captions → end card → grain (6 pre-seeded `default_rng(3)` frames) → fade in 0.4 s from black / fade out 0.8 s. Frames piped as raw BGR to `libx264 -preset medium -crf 19 -maxrate 14M -bufsize 28M yuv420p`; single process; W/H fixed 1080×1920, fps from plan (default 30).
4. **Transitions** are computed inside `frame_at` from the incoming shot's `tr`: punch (zoom ×1.16→1 + white lift 0.28 over 0.22 s, eout), whip (straddles cut ±0.14 s, 0.28 s slide with box blur 6–166 px), fade/leakfade (0.5 s crossfade only; leak needs a `leaks` entry), flash (white 0.85 decaying 0.35 s), wipe (1 s Gaussian-feathered mask + glowing line). Wide images auto-pan side to side when canvas wider than 1296, direction alternating by shot index.
5. **Captions** are pre-rendered PIL sprites (Liberation Serif 92 px regular / 100 px italic in `accent_rgb`, shadow = blurred alpha ×0.75), word-wrapped at 960 px with no row limit, rows 124 px apart, block centred on `caption_y` (default 1420). Each word fades in + rises 22 px over 0.28 s from its time; line fades over 0.35 s after `end`. No hook-text field, no safe-area or face checks. End card draws logo (alpha, or inverted luminance for opaque logos) at y=900, spaced uppercase tagline at 1040, gold italic subtitle at 1500.
6. **validate_plan checks:** duration > 0, ERROR > 180 s, WARN > 90 s; shots non-empty, src/t0/t1 present, absolute + existing src, tiling from 0 to duration (1 ms tol), t1 > t0, WARN < 0.3 s; tr/look enums; first shot not whip; z in 0.95–1.5; video start ≥ 0; whip count WARN; < 3 transition types WARN; beats within 1/fps (WARN); caption line order/end/overlap, end ≤ duration, > 80 chars WARN; its own hard-coded banned-regex list over caption text only (ERROR); caption vs transcript word-count WARN; end card t inside video, < 3.5 s WARN, logo exists; leaks len 3 and strength 0–0.6. No schema, no fonts, no clip-length, no safe area, no signature-moment check; malformed JSON/words → traceback.
7. **Audio.** analyze: voice+music → `sidechaincompress` ducking, music −14 dB, voice weight 1.6, length min(voice+7.5, 60); else single track resampled to 48 kHz stereo (no normalization). Whisper `small.en` int8 on 16 kHz f32 raw; appear = max(start, end−0.4); librosa beats on the music (or master) at 22.05 kHz. finish: HP85 → EQ −2.5@180, −4@3.8k, −2.5@7k → LP11k → optional `aecho` room → `acompressor` 2:1 → `loudnorm I=-15:TP=-1.5:LRA=9` (single pass) → fades → AAC 192k 48 kHz `+faststart`, `-c:v copy`. Loudness is never measured afterwards; clip audio is never used.
8. **run_tests.py** builds five folders in a temp dir from `assets/brand-photos` + ffmpeg `lavfi aevalsrc` audio (100 BPM pad with kick; "fake voice" = gated wobbling tone; HEIC via pillow_heif; clips via `zoompan` stills, one 1080×1920 mp4 + one 1920×1080 mov), then runs analyze → baseline (`--duration 10`) → validate → engine → finish as subprocesses and checks h264 1080×1920, AAC 48 kHz, duration ±0.6 s via `ffmpeg -i` stderr regex. Options `--keep --voice FILE --only NAME --seconds S`. No unit tests, no CI, no golden test.
9. **baseline_plan** = deterministic starting plan: duration = min(--duration, audio, 60); cuts every 2 beats in the first 20% then 4 beats; transitions cycle punch,punch,whip,punch,leakfade,punch,flash (first = cut); zoom alternates [1.02,1.14]/[1.15,1.03]; media round-robin (photos then clips at mid-clip, else bundled brand photos); end card on the last beat ≤ D−4 s with `heroimage.jpg` + flash; captions split on > 0.45 s pauses, sentence ends or 7 words, last word gold; two leaks.
10. **Instruction layer.** `commands/make-reel.md` is the Director script (9 steps over 8 agents); agent models are hard-coded per file (`opus` critic; `sonnet` analyst/editor/motion/scout/scriptwriter; `haiku` librarian/copywriter) with no `tools`. brand.json holds brand facts with status flags, banned patterns, budget split, graph API v26.0, admin contact, consent/closure locations — but no script reads it. Missing entirely: schemas/, CHANGELOG, requirements.txt, .github/, /brand-setup, digest, night-before, scheduled-task prompts, dashboard, v2 output exporters, setup guide, questionnaire.

## Counts

327 requirements. By status: EXISTS 132, PARTIAL 98, MISSING 97.

| Tag | Total | EXISTS | PARTIAL | MISSING |
|---|---|---|---|---|
| CODE | 121 | 39 | 31 | 51 |
| INSTR | 155 | 82 | 49 | 24 |
| DATA | 39 | 10 | 13 | 16 |
| EXTERNAL | 12 | 1 | 5 | 6 |

## Plugin packaging and architecture

| R# | Tag | Status | Note |
|---|---|---|---|
| R1 | DATA | EXISTS | plugin.json v1.3.0 has all fields. |
| R2 | DATA | EXISTS | Both 1.3.0; no automated consistency test. |
| R3 | INSTR | EXISTS | All four present with frontmatter. |
| R4 | INSTR | EXISTS | All three present. |
| R5 | INSTR | PARTIAL | agents/*.md lack `tools`; model hard-coded per file. |
| R6 | INSTR | EXISTS | SKILL.md has numbers, reference edit, look steps. |
| R7 | CODE | PARTIAL | Transcript fixes, claims scan, QA frames, SRT only in prose/missing. |
| R8 | CODE | EXISTS | All scripts use `__file__`-relative ASSETS. |
| R9 | CODE | EXISTS | engine.py reads only plan + assets. |
| R10 | INSTR | EXISTS | SKILL Step 1-3 and scripts use work dir. |
| R11 | CODE | EXISTS | No network code in scripts. |
| R12 | INSTR | PARTIAL | scout.md has web-search fallback; make-reel lacks Mac-off design rule. |

## Pipeline stage 1: Ingest

| R# | Tag | Status | Note |
|---|---|---|---|
| R13 | INSTR | EXISTS | make-reel.md "Material:" line. |
| R14 | INSTR | EXISTS | librarian.md step 1. |
| R15 | CODE | EXISTS | analyze.py IMG/VID/AUD tuples. |
| R16 | CODE | EXISTS | analyze.py via pillow_heif. |
| R17 | CODE | PARTIAL | analyze.py guesses, but substring 'vo' and 'audio' are over-broad; untested. |
| R18 | INSTR | EXISTS | SKILL Step 1.4. |

## Pipeline stage 2: Analyze (analyze.py)

| R# | Tag | Status | Note |
|---|---|---|---|
| R19 | CODE | EXISTS | analyze.py filter_complex; ducking not measured by tests. |
| R20 | CODE | PARTIAL | Resampled only; no normalization. |
| R21 | CODE | EXISTS | analyze.py lines 62-68. |
| R22 | CODE | EXISTS | analyze.py line 68. |
| R23 | CODE | EXISTS | music_only short-circuit. |
| R24 | CODE | EXISTS | try/except prints and continues. |
| R25 | CODE | EXISTS | Tests only check beats non-empty. |
| R26 | CODE | PARTIAL | Clips sampled max(1, d/8) s; label uses thumb index not clip id. |
| R27 | CODE | EXISTS | Fields match; no schema to validate. |
| R28 | CODE | PARTIAL | Only analyst.md prose; no code. |
| R29 | CODE | MISSING | No quality metrics computed. |

## Pipeline stages 3-4: Script and Motion

| R# | Tag | Status | Note |
|---|---|---|---|
| R30 | INSTR | EXISTS | SKILL Step 4. |
| R31 | INSTR | EXISTS | motion.md/SKILL Step 5. |
| R32 | INSTR | EXISTS | motion.md. |
| R33 | INSTR | EXISTS | README Costs; tests offline. |

## Pipeline stages 5-8: Preview, Render, Finish, Deliver

| R# | Tag | Status | Note |
|---|---|---|---|
| R34 | CODE | EXISTS | engine.py preview mode. |
| R35 | INSTR | EXISTS | SKILL Step 6.1. |
| R36 | CODE | EXISTS | engine.py main. |
| R37 | CODE | EXISTS | finish.py af chain. |
| R38 | CODE | EXISTS | finish.py mux. |
| R39 | CODE | EXISTS | finish.py QA strip. |
| R40 | CODE | PARTIAL | Prints mean dB only; no LUFS/TP, no report file. |
| R41 | INSTR | PARTIAL | SKILL Step 7 gives one suggested caption, not three. |

## Edit grammar: story and rhythm

| R# | Tag | Status | Note |
|---|---|---|---|
| R42 | INSTR | EXISTS | SKILL Step 4. |
| R43 | INSTR | EXISTS | SKILL Step 4.1. |
| R44 | INSTR | EXISTS | SKILL Step 4.2. |
| R45 | CODE | PARTIAL | Instruction only; validator does not check. |
| R46 | CODE | EXISTS | validate_plan beat check. |
| R47 | INSTR | EXISTS | SKILL Step 4.3. |
| R48 | CODE | MISSING | Not checked. |
| R49 | CODE | EXISTS | validate_plan endcard check. |

## Edit grammar: transitions and motion

| R# | Tag | Status | Note |
|---|---|---|---|
| R50 | CODE | EXISTS | engine.py frame_at punch. |
| R51 | CODE | EXISTS | engine whip(); validator warns. |
| R52 | CODE | PARTIAL | Crossfade only; leak needs manual `leaks` entry. |
| R53 | CODE | EXISTS | engine.py flash. |
| R54 | CODE | EXISTS | engine.py wipe. |
| R55 | CODE | PARTIAL | Validator only forbids whip first; fade supported. |
| R56 | CODE | EXISTS | validate_plan warning. |
| R57 | CODE | PARTIAL | Baseline alternates; no check for static shots. |
| R58 | CODE | PARTIAL | Pan + blurred fill exist; BORDER_REFLECT can mirror edges. |
| R59 | CODE | EXISTS | Uses cosine ease + cubic interpolation. |

## Edit grammar: color, captions, end card, first second

| R# | Tag | Status | Note |
|---|---|---|---|
| R60 | CODE | EXISTS | engine grade_arr. |
| R61 | CODE | EXISTS | engine grade_arr. |
| R62 | CODE | EXISTS | engine render(). |
| R63 | CODE | PARTIAL | validate_plan rejects strength > 0.6 (contract says 0–1). |
| R64 | CODE | EXISTS | engine draw_caps. |
| R65 | CODE | EXISTS | engine sprite(); italic 100 px. |
| R66 | CODE | PARTIAL | Heuristic 80-char warning; engine wraps unlimited rows. |
| R67 | CODE | MISSING | No safe-area check. |
| R68 | CODE | MISSING | Instruction only ("move caption_y"). |
| R69 | CODE | EXISTS | engine endcard(). |
| R70 | CODE | PARTIAL | engine fades from black over 0.4 s; frame 0 is black. |
| R71 | CODE | MISSING | No hook-text field or rendering. |
| R72 | CODE | EXISTS | engine render(). |
| R73 | INSTR | EXISTS | SKILL rules. |
| R74 | CODE | EXISTS | analyze sidechain. |
| R75 | CODE | PARTIAL | Warns only above 90 s. |
| R76 | INSTR | EXISTS | SKILL research rules. |
| R77 | INSTR | EXISTS | SKILL research rules. |
| R78 | INSTR | EXISTS | scriptwriter rule 4. |

## Data contracts, JSON Schemas, validate_plan

| R# | Tag | Status | Note |
|---|---|---|---|
| R79 | DATA | MISSING | No schemas/ directory. |
| R80 | DATA | MISSING | No plan schema. |
| R81 | DATA | MISSING | No version field. |
| R82 | CODE | MISSING | Hand-written checks only. |
| R83 | CODE | EXISTS | validate_plan tiling. |
| R84 | CODE | PARTIAL | Only compares word counts. |
| R85 | CODE | PARTIAL | No font check. |
| R86 | CODE | EXISTS | validate_plan. |
| R87 | CODE | PARTIAL | Enums checked; malformed word crashes (IndexError). |
| R88 | CODE | MISSING | Not checked. |
| R89 | CODE | PARTIAL | Bad JSON or args raise tracebacks. |
| R90 | INSTR | EXISTS | editor.md step 2. |

## Failure and fallback table

| R# | Tag | Status | Note |
|---|---|---|---|
| R91 | INSTR | PARTIAL | Generic fallback list; order/consent detail missing. |
| R92 | CODE | MISSING | No script-to-captions code. |
| R93 | INSTR | PARTIAL | Generate step present; library/pad order absent. |
| R94 | CODE | MISSING | analyze exits "NO AUDIO FOUND". |
| R95 | INSTR | PARTIAL | Day swap not in make-reel. |
| R96 | CODE | EXISTS | baseline_plan fallback. |
| R97 | INSTR | EXISTS | SKILL Step 5 + engine. |
| R98 | INSTR | PARTIAL | Upscale only; montage/drop steps absent. |
| R99 | INSTR | MISSING | Not in instructions. |
| R100 | INSTR | PARTIAL | Model-switch step missing. |
| R101 | INSTR | PARTIAL | Never-exceed rule only. |
| R102 | INSTR | PARTIAL | Last-resort step missing. |
| R103 | INSTR | PARTIAL | Only ship-best present. |
| R104 | INSTR | PARTIAL | Rewrite implied; explicit order absent. |
| R105 | INSTR | MISSING | Not in instructions. |
| R106 | CODE | PARTIAL | `crop` exists; no blur. |
| R107 | INSTR | PARTIAL | plan-month only bans inviting content. |
| R108 | INSTR | MISSING | Not in instructions; no draft mode. |
| R109 | INSTR | MISSING | Not in instructions. |
| R110 | INSTR | PARTIAL | Decisions log mentioned; per-row logging not. |

## Decision authority

| R# | Tag | Status | Note |
|---|---|---|---|
| R111 | INSTR | EXISTS | make-reel.md line 1. |
| R112 | INSTR | EXISTS | SKILL decision authority. |
| R113 | INSTR | EXISTS | SKILL; plan-month "never ask to approve". |
| R114 | INSTR | EXISTS | SKILL. |
| R115 | INSTR | EXISTS | SKILL. |
| R116 | INSTR | EXISTS | SKILL Step 7. |
| R117 | INSTR | EXISTS | SKILL. |
| R118 | INSTR | EXISTS | make-reel + brand.json. |
| R119 | CODE | MISSING | No lint test. |

## Scout

| R# | Tag | Status | Note |
|---|---|---|---|
| R120 | INSTR | EXISTS | scout.md. |
| R121 | INSTR | EXISTS | scout.md. |
| R122 | INSTR | PARTIAL | License-page copy for music missing. |
| R123 | INSTR | EXISTS | SKILL. |
| R124 | INSTR | PARTIAL | Web-search fallback present; desktop-task split absent. |
| R125 | INSTR | EXISTS | model: sonnet. |

## Claims policy and safety rails

| R# | Tag | Status | Note |
|---|---|---|---|
| R126 | DATA | PARTIAL | Missing 'illness', 'hormone', 'burns calories' form. |
| R127 | CODE | MISSING | Only validate_plan regex over captions. |
| R128 | CODE | MISSING | Separate hard-coded BANNED list. |
| R129 | CODE | MISSING | No hashtag check. |
| R130 | INSTR | EXISTS | SKILL. |
| R131 | INSTR | PARTIAL | Only sample "say" lines; no never-say table. |
| R132 | INSTR | PARTIAL | Bloodwork/limping not mentioned. |
| R133 | INSTR | PARTIAL | Repost covered; experience-only/pin absent. |
| R134 | INSTR | EXISTS | scriptwriter rule 7. |
| R135 | INSTR | EXISTS | scriptwriter rule 8. |
| R136 | INSTR | EXISTS | brand.json + scriptwriter rule 6/8. |
| R137 | INSTR | PARTIAL | Caption first line only; video disclosure/reviews absent. |
| R138 | INSTR | EXISTS | brand.json. |
| R139 | INSTR | PARTIAL | People only; no flag in plan/outputs. |
| R140 | INSTR | EXISTS | brand.json + critic. |
| R141 | CODE | MISSING | No consent/music fields or check. |
| R142 | DATA | MISSING | Not in plan contract. |
| R143 | EXTERNAL | MISSING | No flag in brand.json. |

## Brand kit and brand.json

| R# | Tag | Status | Note |
|---|---|---|---|
| R144 | DATA | PARTIAL | Facebook page and iOS app missing. |
| R145 | DATA | PARTIAL | Booking/Mindbody missing. |
| R146 | DATA | PARTIAL | Series names only; no audiences. |
| R147 | DATA | EXISTS | brand.json _readme. |
| R148 | DATA | PARTIAL | No Scott entry. |
| R149 | CODE | MISSING | engine/baseline hard-code fonts, accent, tagline. |
| R150 | INSTR | PARTIAL | Caption and brand-check do not. |
| R151 | CODE | MISSING | No validation. |
| R152 | DATA | EXISTS | All present. |
| R153 | INSTR | MISSING | No brand-setup command. |

## 30-day system: /plan-month, Sheet, Drive

| R# | Tag | Status | Note |
|---|---|---|---|
| R154 | INSTR | EXISTS | plan-month.md. |
| R155 | INSTR | EXISTS | plan-month step 1. |
| R156 | DATA | PARTIAL | plan-month columns differ: no Template, Reel link, status enum. |
| R157 | INSTR | PARTIAL | Music Library naming and Digests missing. |
| R158 | CODE | MISSING | No code. |
| R159 | CODE | MISSING | Rules only in prose. |
| R160 | INSTR | EXISTS | plan-month step 2. |
| R161 | DATA | EXISTS | brand.json content_mix. |
| R162 | INSTR | MISSING | Not present. |
| R163 | INSTR | PARTIAL | Retune after 30 reels absent. |
| R164 | INSTR | EXISTS | plan-month. |
| R165 | INSTR | EXISTS | scriptwriter/SKILL. |
| R166 | INSTR | PARTIAL | Series rotation listed without counts. |
| R167 | INSTR | PARTIAL | Weather only at month planning. |
| R168 | INSTR | EXISTS | plan-month step 2. |
| R169 | INSTR | EXISTS | plan-month step 4. |
| R170 | INSTR | MISSING | Absent. |
| R171 | DATA | PARTIAL | Names only in brand.json. |
| R172 | INSTR | PARTIAL | Partners listed; concept/order absent. |
| R173 | INSTR | PARTIAL | Says "update the Sheet row", not status values. |
| R174 | INSTR | MISSING | No night-before instructions. |

## Shoot cards and batched shoots

| R# | Tag | Status | Note |
|---|---|---|---|
| R175 | INSTR | EXISTS | scriptwriter SKILL. |
| R176 | INSTR | PARTIAL | Missing 4K/30 fps, music rule, changes rule. |
| R177 | INSTR | EXISTS | scriptwriter SKILL. |
| R178 | INSTR | EXISTS | scriptwriter rule 5. |
| R179 | DATA | MISSING | Example only, no schema. |
| R180 | CODE | MISSING | No checker. |
| R181 | INSTR | MISSING | Absent. |
| R182 | INSTR | PARTIAL | reuse_ok + library sheet; no film-once rule. |
| R183 | INSTR | MISSING | Absent. |
| R184 | INSTR | MISSING | Absent. |
| R185 | INSTR | MISSING | Absent. |

## Scriptwriter skill

| R# | Tag | Status | Note |
|---|---|---|---|
| R186 | INSTR | PARTIAL | plan-month delegates per day, not one pass. |
| R187 | INSTR | PARTIAL | Says 4-6 s outro, spec 6-8 s. |
| R188 | INSTR | EXISTS | scriptwriter SKILL. |
| R189 | INSTR | PARTIAL | No caption draft field. |
| R190 | INSTR | PARTIAL | 1 s silence tip missing. |
| R191 | INSTR | EXISTS | scriptwriter SKILL. |

## Templates library and reel templates

| R# | Tag | Status | Note |
|---|---|---|---|
| R192 | DATA | MISSING | No template data. |
| R193 | DATA | MISSING | Absent. |
| R194 | CODE | MISSING | No template option. |
| R195 | CODE | MISSING | Engine has no text cards. |

## Agent crew and Critic

| R# | Tag | Status | Note |
|---|---|---|---|
| R196 | INSTR | EXISTS | make-reel.md. |
| R197 | INSTR | EXISTS | librarian.md. |
| R198 | INSTR | EXISTS | analyst.md. |
| R199 | INSTR | EXISTS | motion.md. |
| R200 | INSTR | EXISTS | copywriter.md. |
| R201 | INSTR | EXISTS | editor.md (single-renderer rule implicit). |
| R202 | INSTR | EXISTS | critic.md. |
| R203 | INSTR | EXISTS | Both present. |
| R204 | DATA | MISSING | model: sonnet/haiku/opus per agent file. |
| R205 | INSTR | EXISTS | make-reel.md. |
| R206 | INSTR | EXISTS | critic.md. |
| R207 | CODE | MISSING | finish.py makes 6-frame strip only. |
| R208 | INSTR | EXISTS | critic.md + SKILL. |
| R209 | CODE | MISSING | No automated gate script. |
| R210 | INSTR | EXISTS | critic.md. |
| R211 | CODE | MISSING | Prose only. |
| R212 | INSTR | EXISTS | critic.md. |
| R213 | INSTR | EXISTS | critic.md. |
| R214 | INSTR | EXISTS | make-reel step 7. |
| R215 | INSTR | PARTIAL | Brand-check allows 44.1 kHz; not called by make-reel. |

## Higgsfield

| R# | Tag | Status | Note |
|---|---|---|---|
| R216 | DATA | PARTIAL | Prices only in SKILL prose. |
| R217 | INSTR | EXISTS | motion.md. |
| R218 | INSTR | PARTIAL | Motion transfer (#10) missing. |
| R219 | DATA | EXISTS | brand.json budgets. |
| R220 | CODE | PARTIAL | Rule in motion.md; no code. |
| R221 | INSTR | EXISTS | SKILL. |
| R222 | INSTR | EXISTS | SKILL. |
| R223 | DATA | MISSING | One generic example only. |
| R224 | INSTR | EXISTS | motion.md. |
| R225 | INSTR | EXISTS | SKILL Step 5. |
| R226 | INSTR | EXISTS | SKILL Step 5. |
| R227 | INSTR | MISSING | Absent. |
| R228 | INSTR | PARTIAL | Uses Seedance 35/clip estimate. |

## v2 outputs: one reel, many outputs

| R# | Tag | Status | Note |
|---|---|---|---|
| R229 | CODE | MISSING | W,H hard-coded. |
| R230 | CODE | EXISTS | engine default. |
| R231 | CODE | MISSING | Absent. |
| R232 | CODE | MISSING | Absent. |
| R233 | CODE | MISSING | Absent. |
| R234 | CODE | MISSING | Absent. |
| R235 | CODE | MISSING | Absent. |
| R236 | INSTR | EXISTS | copywriter.md. |
| R237 | CODE | MISSING | Absent. |

## Monday digest and weekly trend check

| R# | Tag | Status | Note |
|---|---|---|---|
| R238 | INSTR | MISSING | No digest instructions (make-reel only appends notes). |
| R239 | INSTR | MISSING | Absent. |
| R240 | CODE | MISSING | Absent. |
| R241 | INSTR | EXISTS | scout.md weekly trend. |
| R242 | INSTR | PARTIAL | Trial-Reel testing/slotting absent. |

## Performance dashboard and learning loop

| R# | Tag | Status | Note |
|---|---|---|---|
| R243 | INSTR | PARTIAL | SKILL mentions Login; scopes/setup absent. |
| R244 | DATA | EXISTS | brand.json + SKILL. |
| R245 | INSTR | PARTIAL | Timing in SKILL; no storage instructions. |
| R246 | CODE | MISSING | Absent. |
| R247 | DATA | MISSING | Absent. |
| R248 | CODE | MISSING | Absent. |
| R249 | CODE | MISSING | Absent. |
| R250 | INSTR | EXISTS | scout.md + brand.json. |
| R251 | DATA | MISSING | Absent. |
| R252 | INSTR | PARTIAL | "re-weighted by last month" only. |

## Auto-posting

| R# | Tag | Status | Note |
|---|---|---|---|
| R253 | INSTR | EXISTS | SKILL research rules. |
| R254 | INSTR | EXISTS | make-reel. |
| R255 | INSTR | PARTIAL | Only "apply the AI label". |
| R256 | DATA | PARTIAL | auto_post exists; no approval switch. |
| R257 | INSTR | PARTIAL | Facebook not mentioned. |
| R258 | INSTR | EXISTS | numa-caption. |
| R259 | INSTR | PARTIAL | "update the Sheet row" only. |
| R260 | INSTR | MISSING | Absent. |

## Scheduled tasks

| R# | Tag | Status | Note |
|---|---|---|---|
| R261 | DATA | MISSING | Absent. |
| R262 | INSTR | MISSING | Only plan-month and make-reel exist. |
| R263 | INSTR | MISSING | Absent. |
| R264 | INSTR | MISSING | Absent. |

## Setup

| R# | Tag | Status | Note |
|---|---|---|---|
| R265 | INSTR | PARTIAL | Import check omits pillow_heif, PIL, numpy. |
| R266 | INSTR | PARTIAL | Only a preview, not a 3 s render. |
| R267 | CODE | MISSING | Absent. |
| R268 | INSTR | PARTIAL | Drive and Higgsfield only. |
| R269 | INSTR | EXISTS | numa-setup step 3. |
| R270 | INSTR | MISSING | Absent (gap 10). |
| R271 | DATA | MISSING | README covers install + connectors only. |
| R272 | DATA | MISSING | Absent. |
| R273 | INSTR | MISSING | Absent. |
| R274 | EXTERNAL | MISSING | Supporting artifacts missing. |
| R275 | DATA | MISSING | Absent. |

## Feedback memory, smart framing, hook variants

| R# | Tag | Status | Note |
|---|---|---|---|
| R276 | DATA | MISSING | Absent. |
| R277 | INSTR | MISSING | Absent. |
| R278 | CODE | MISSING | Absent. |
| R279 | CODE | MISSING | Absent. |
| R280 | CODE | MISSING | Absent. |
| R281 | INSTR | MISSING | Absent. |
| R282 | CODE | MISSING | Absent; not in D5 build list. |
| R283 | INSTR | PARTIAL | Covered partly by generic fallbacks. |

## Natural sound, media library, stabilize/brighten, draft and multi-core render

| R# | Tag | Status | Note |
|---|---|---|---|
| R284 | CODE | MISSING | Clip audio ignored (gap 7). |
| R285 | DATA | PARTIAL | librarian.md mentions a Sheet; no schema. |
| R286 | CODE | MISSING | Absent. |
| R287 | CODE | MISSING | Absent. |
| R288 | CODE | MISSING | Absent. |
| R289 | CODE | MISSING | Single process. |
| R290 | CODE | MISSING | Absent; beyond D5 list. |

## Non-functional requirements

| R# | Tag | Status | Note |
|---|---|---|---|
| R291 | CODE | PARTIAL | Encoder flags set; tests check only size, Hz, duration. |
| R292 | CODE | PARTIAL | Single-pass loudnorm; never measured; AAC may overshoot TP. |
| R293 | CODE | MISSING | No timing target/measure. |
| R294 | EXTERNAL | MISSING | No timing log. |
| R295 | INSTR | PARTIAL | Digest reporting absent. |
| R296 | CODE | PARTIAL | Stages re-runnable; no skip/resume logic; untested. |
| R297 | CODE | PARTIAL | Grain seeded; never tested. |
| R298 | CODE | PARTIAL | Linux only verified. |
| R299 | DATA | PARTIAL | pip line in prose; no requirements.txt. |
| R300 | INSTR | EXISTS | None used. |
| R301 | INSTR | EXISTS | SKILL + motion.md. |
| R302 | DATA | EXISTS | README + LICENSE. |
| R303 | DATA | PARTIAL | No CHANGELOG.md. |

## Milestones and test harnesses

| R# | Tag | Status | Note |
|---|---|---|---|
| R304 | EXTERNAL | PARTIAL | Manifest ok; no setup script. |
| R305 | CODE | MISSING | Absent. |
| R306 | CODE | MISSING | Absent. |
| R307 | EXTERNAL | MISSING | No comparison artifact. |
| R308 | CODE | PARTIAL | Cases differ: no audio-less photos-only, clips carry music. |
| R309 | CODE | MISSING | No .github/. |
| R310 | EXTERNAL | PARTIAL | Instructions only; no ledger code. |
| R311 | EXTERNAL | MISSING | Scheduled prompts missing. |
| R312 | CODE | MISSING | No golden test yet. |
| R313 | EXTERNAL | PARTIAL | Night-before missing. |
| R314 | INSTR | MISSING | Absent. |

## Open verifications and blocking inputs

| R# | Tag | Status | Note |
|---|---|---|---|
| R315 | EXTERNAL | PARTIAL | D8 decided; instructions not yet written. |
| R316 | EXTERNAL | EXISTS | make-reel step 9. |
| R317 | EXTERNAL | PARTIAL | No desktop-task variant. |
| R318 | EXTERNAL | MISSING | Not implemented. |

## Implicit project requirements

| R# | Tag | Status | Note |
|---|---|---|---|
| R319 | CODE | PARTIAL | Passes here (see audit); no requirements/CI. |
| R320 | CODE | PARTIAL | Most bad inputs raise tracebacks. |
| R321 | CODE | PARTIAL | engine/finish/validate use raw argv. |
| R322 | DATA | PARTIAL | Exists for v1.3; needs v2 update. |
| R323 | DATA | EXISTS | grep found none. |
| R324 | DATA | EXISTS | spec/ ignored; fixtures synthesized. |
| R325 | CODE | EXISTS | Scripts clean; example plan holds old Linux paths (docs only). |
| R326 | CODE | EXISTS | No 3.11+ syntax seen; untested on 3.10. |
| R327 | CODE | PARTIAL | voice_and_music triggers whisper model download. |
