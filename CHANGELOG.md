# Changelog

All notable changes to NUMA Studio are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Entries for 1.0.0-1.3.0 are
reconstructed from the git history.

## [Unreleased]

Nothing yet.

## [2.0.0] - 2026-11-12

NUMA Studio v2: from a hand-run reel editor to a hands-off studio. A Director agent plans the month
and builds every day's reel and outputs with a crew of agents and a Critic, six scheduled tasks run
it, and every exact step is a tested script. Breaking: brand.json moved to schema_version 2 (key
table below) and analysis.json to schema_version 2 (re-run `analyze.py`; v1 plans still render).

### Release check (golden test, spec p.52)
- M2 golden test (`tests/golden_year_one.py`, Year One test pack, Linux sandbox, 4 cores): PASS.
  Analysis 107.7 BPM, transcript with "Mobile", 50 words. Example plan (the hand-built edit, its
  captions in sync as shipped, checked before any re-timing) and baseline plan (`--template
  transformation`, before/after wipe): 0 validator errors, before/after wipe, cuts within one frame of a beat (25/25 and 26/26), every
  caption word within 0.1 s of the transcript, output spec met, 39.0 s vs the reference's 39.0 s,
  -15 LUFS vs the reference's -16 LUFS, drop-to-file 2.0 and 1.7 min (limit 15).
- M3 five-folder suite (`tests/run_tests.py`): 5/5 PASS.
- Jude's rating against the hand-built reference (the manual M2 step) is pending; record it here
  before tagging. Sandbox notes for the rating: the example-plan reel tracks the reference shot for
  shot; the baseline reel reuses a "before" photo in the closing montage and ends on the brand
  default sign-off instead of "Year one. Thank you, Mobile.".

### Added
- **Data and contracts.** `config/studio.json` (agent model tiers, Higgsfield prices and the
  1,200-credit budget split with day-15 pacing, Critic rubric, render and loudness targets, the
  scheduled-task table, Instagram/Composio settings, output formats; each section cites its spec
  page). JSON Schemas (draft 2020-12) for analysis, plan (v2, a superset of the v1 contract: `hook`,
  `fps`, `size`, `quality`, `seed`, per-shot `focus`/`faces`/`peak`/`people`/`consent`/`blur`,
  `signature`, `nat`, `music`, `ai`, `template`, `cards`, `meta`, `formats`), brand and script.
  `docs/CONTRACTS.md`: the authoritative contracts, work-folder layout, deliverable names,
  cross-field validation rules and every script's command line.
- **Shared helper** `numa_common.py`: plugin paths, ffmpeg/ffprobe lookup with the imageio-ffmpeg
  fallback, normalized media probing, brand/config loading, atomic JSON writes, schema validation,
  `run_cli` (one-line `ERROR:` messages, exit codes 1/2, no tracebacks; `NUMA_DEBUG=1` shows them).
- **Analysis.** `analyze.py` rebuilt: recursive ingest with HEIC conversion, audio roles from file
  names, the ducked voice + music mix, clip natural-sound inventory, an offline music pad when a
  folder has no audio, transcripts that never hallucinate words over music, brand transcript fixes
  (Mobile, NUMA, Katie, Scott, Dauphin), beats, contact sheets. `fix_transcript.py` aligns the
  transcript to the shoot-card script.
- **Vision and prep.** `vision.py`: faces (bundled YuNet model) and main subject for smart framing,
  per-second clip scores and best windows. `prep_media.py`: stabilizes shaky clips (ffmpeg vidstab,
  else OpenCV smoothing) and brightens dark media.
- **Planning.** `baseline_plan.py` writes a valid, beat-synced v2 plan: hook from frame 0,
  before/after wipe or flash reveal, smart framing, consent gate (faces only with recorded consent,
  else left out or blurred), reel templates (`--template`, from `numa-scriptwriter/templates.json`),
  kinetic text cards, feedback-memory limits (`--prefs`), music-only captions from `--script`, and
  default `formats`. `validate_plan.py` enforces the schema and the cross-field rules (tiling, beat
  alignment, caption timing against the transcript, file existence, duration, whip spacing,
  claims, consent rule 41, preference limits) before a render. `claims_scan.py` checks every text
  against the claims policy.
- **Rendering.** `engine.py` rebuilt: deterministic, byte-identical output for any worker count,
  multi-core frame rendering, `--draft`, `--size`, `--from/--to`, preview grids, smart framing,
  no mirrored edges or black bars, hook text at full opacity from frame 0, blur regions, kinetic
  type, brand fonts and colours from brand.json, a 14 Mbps-capped H.264 High encode.
- **Finishing and checks.** `finish.py`: the voice chain, two-pass loudness to -15 LUFS with a
  true-peak limiter (<= -1.5 dB), natural-sound bursts mixed under the music, 48 kHz AAC 192k,
  `+faststart`, QA strip, `report.json`. `check_output.py`: the full output spec (codec, size, fps,
  bitrate, audio, faststart, size, length per kind, loudness, silence, clipping, black bars, frozen
  frames). `qa_frames.py`: the Critic's 12 frames.
- **Every format from one run.** `formats.py`: the 8-12 s reach cut with new hook text, Story set,
  1080x1350 carousel, cover, .srt and hook-variant openings, all cropped from the same plan.
- **Operations.** `ledger.py` (Higgsfield credit ledger, budget and pacing checks), `metrics.py`,
  `dashboard.py` (self-contained performance dashboard), `library.py` (media library index with
  consent), `prefs.py` (feedback memory), `sources.py` (licenses and `sources.txt`),
  `critic_score.py` (rubric, pass rule, rounds), `digest_data.py` (Monday digest numbers),
  `shoot_card.py` (month skeleton, shoot cards, planning rules, Sheet export), `setup_check.py`
  (readiness check with a 3-second test render and speech-model pre-download).
- **Instruction layer.** The Director's `/make-reel` with the failure table (nothing is fatal,
  Katie is never asked), the crew (`librarian`, `scout`, `analyst`, `motion`, `scriptwriter`,
  `copywriter`, `editor`, `critic`), the 30-day system (`/plan-month`, `/night-check`,
  `/build-today`, `/digest`, `/trend-check`, `/dashboard-refresh`), `/numa-setup`, `/brand-setup`,
  `/post-reel` (Composio auto-posting behind the legal-review gate), the `numa-scriptwriter`,
  `numa-caption`, `numa-brand-check` and `numa-reel-editor` skills, `docs/SETUP_GUIDE.md`,
  `docs/SCHEDULED_TASKS.md` and `docs/QUESTIONS_FOR_KATIE.md`.
- **Tests and CI.** Unit tests for every script, schema, data and instruction file (`tests/unit`,
  synthetic fixtures). `tests/run_tests.py`: the M3 five-folder suite (photos only with no audio,
  clips with their own sound, voice + music, music only with a script, iPhone HEIC photos), each
  through the whole pipeline to a postable reel and its formats. `tests/golden_year_one.py`: the M2
  golden harness for the Year One test pack (path from `--pack`/`NUMA_TEST_PACK`, never committed)
  with a comparison sheet against the hand-built reference. `tests/unit/test_release.py`: version,
  contract, README, secret, media and Python 3.10 consistency checks. GitHub Actions: a Python 3.10
  grammar parse of every file, unit tests on 3.10 and 3.12, and the five-folder suite on every push.
- `requirements.txt` and `requirements-dev.txt` (OpenCV pinned below 5: 5.0 dropped the Haar
  cascades).

### Changed
- `brand/brand.json` upgraded to schema_version 2: every fact with a status (`confirmed`,
  `from_website`, `research`, `needs_katie`, `bundled`, `generated`), sessions and prices, the
  collective, series, collab partners, audiences, competitors, palette roles, fonts, Drive layout,
  consent and closures, posting gates, escalation to Jude, transcript fixes and the claims policy as
  data (banned patterns with labels and a `fail`/`warn` severity, allow-patterns, per-modality
  say/never-say, safety line, dosing line blocked until counsel). Operational numbers moved to
  `config/studio.json`. Key migration (no compatibility shim; full table in `docs/CONTRACTS.md`
  section 6):

  | v1 key | v2 location |
  |--------|-------------|
  | `claims.banned_patterns` | `claims.banned[].patterns` (with id, label, severity `fail`/`warn`) |
  | `claims.hold_until_counsel` | `claims.dosing_line` |
  | `competitors_to_track` | `positioning.competitors` |
  | `collab_partners`, `series`, `content_mix` | `positioning.collab_partners`, `positioning.series`, `positioning.content_mix` |
  | `budgets` | `config/studio.json` `budget` |
  | `instagram_api` | `config/studio.json` `instagram.graph_api_version` |
  | `admin_contact` | `escalation.contact` / `escalation.for` |
  | `handles` | `socials` |
  | `hashtags` | `captions.hashtags` |
  | `posting.cta_link` | `business.cta_link` |
  | `posting.default_slots_central` | `posting.posting_time` |
  | `name`, `founders`, `location`, `facility`, `phone`, `hours_note` | `business.*` (`hours_note` -> `business.hours`) |
  | `sessions`, `offers`, `events`, `not_offered` | `offerings.*` |
  | `collective` | `team.collective` |
  | `community_word`, `emoji` | `voice.*` |
  | `transcript_fixes` map | `transcript_fixes.fixes[]` + `protect` |
  | `closures.source` | `closures.location` |
- Main reels are 15-60 s (45-60 s for growth); 8-12 s is the reach cut. Audio is 48 kHz only.
- The five-folder suite follows the M3 cases (REQUIREMENTS.md interpretation 7): "photos only" has
  no audio at all, "clips only" uses the clips' own sound, "music only" takes its captions from the
  script; the v1 combined-track case stays as `--extra`.
- `assets/example-plan-year-one-v2.json`: the Year One reel as a v2 plan (placeholder prefixes the
  golden harness rewrites); the v1 example stays as the compatibility fixture. Its caption words
  are re-timed to the Year One transcript's appear times (48 words moved, at most 0.9 s) and the
  unspoken "And" at 7.00 s is removed, so the shipped example is in sync (validate_plan rule 24).

### Fixed
- Transcripts no longer invent words over music-only audio; brand names are spelled right.
- Renders are deterministic and have no mirrored edges, black bars or long fade-ins.
- Loudness lands at -15 LUFS with true peak <= -1.5 dB after AAC encoding.

## [1.3.0] - 2026-11-12

### Added
- `validate_plan.py`: fails a bad plan before a long render.
- `baseline_plan.py`: a valid, beat-synced starting plan.
- Five-case end-to-end test suite (`tests/run_tests.py`).
- `numa-scriptwriter` skill and the `/plan-month` command.
- Agent crew: librarian, scout, analyst, motion, scriptwriter, copywriter,
  editor and critic.
- `brand/brand.json` with research and placeholder values.

### Fixed
- The separate voice + music ducking mix in `analyze.py` (the voice fed two
  filters unsplit).

### Changed
- Faster video canvas in the engine.
- Bundled brand assets replaced with real JPEG/PNG files.

## [1.2.0] - 2026-11-12

### Changed
- Deep-research updates: 45-60 s growth reels, Seedance face block, claims
  policy, Composio Instagram Login, escalations go to Jude.

## [1.1.0] - 2026-11-12

### Added
- Research-backed edit rules, the full-power Higgsfield workflow and monthly
  budget, Critic gates.

### Changed
- The Director makes every decision; Katie is never asked; sourcing missing
  material with Claude in Chrome is encouraged.

## [1.0.0] - 2026-11-12

### Added
- NUMA Studio plugin: hands-off branded reel editor (`analyze.py`,
  `engine.py`, `finish.py`), the `numa-caption` and `numa-brand-check`
  skills, `/make-reel` and `/numa-setup`, bundled wordmark, phoenix mark,
  ripple image, six brand photos and the Liberation Serif caption fonts.

[Unreleased]: https://github.com/CordiaJude/numa-studio/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/CordiaJude/numa-studio/compare/v1.3.0...v2.0.0
[1.3.0]: https://github.com/CordiaJude/numa-studio/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/CordiaJude/numa-studio/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/CordiaJude/numa-studio/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/CordiaJude/numa-studio/releases/tag/v1.0.0
