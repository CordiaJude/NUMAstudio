# NUMA Studio

NUMA Wellness Collective's in-house video studio, as a Claude plugin. Katie films; NUMA Studio does
the rest. Every day it takes the photos, clips, voiceover and music in that day's Google Drive
folder and turns them into a finished, on-brand 1080x1920 Instagram reel with captions, a reach
cut-down, Stories, a carousel, a cover and the post copy. Nobody makes a decision along the way:
a Director agent plans the month, a crew of agents builds each reel, a Critic agent checks it, and
six scheduled tasks run the whole thing.

It is a Claude plugin, not a server or a web app: Markdown instructions (commands, agents, skills),
Python scripts that do every exact step (analysis, planning checks, rendering, mastering, output
checks), and JSON data (brand, config, schemas). Version 2.0.0; see [CHANGELOG.md](CHANGELOG.md).

## Install

In the Claude desktop app: Settings → Plugins → add the marketplace `CordiaJude/numa-studio` (this
GitHub repo), then install **numa-studio**.

In Claude Code:

```
/plugin marketplace add CordiaJude/numa-studio
/plugin install numa-studio@numa-studio
```

Then connect **Google Drive**, **Google Sheets**, **Higgsfield** (Plus plan) and **Composio**
(Instagram toolkit; Gmail optional) under Settings → Connectors, install Claude in Chrome in a
Chrome profile signed in to NUMA's accounts, and run `/numa-setup` once. `/numa-setup` checks
Python and every package, ffmpeg, fonts and brand data, renders a 3-second test reel, pre-downloads
the speech model, confirms each connector with one harmless call, builds the Drive folders and
approves the connector tools so scheduled runs never stop on a permission prompt. Then run
`/brand-setup` to record Katie's brand answers. The full afternoon checklist for Jude is
[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md); the questions only Katie can answer are in
[docs/QUESTIONS_FOR_KATIE.md](docs/QUESTIONS_FOR_KATIE.md).

## Daily use

After setup Katie types no commands. `/plan-month` writes a 30-day plan Sheet and a dated Drive folder
with a SHOOT CARD for every day (`NUMA Reels/Day 07 - 2026-12-09 - Your first plunge/`). Katie
films what the card asks and drops the files in that folder. The scheduled tasks do everything else
and send her a phone notification when the reel is in the day's `Finished/` folder.

To make a reel by hand: drop photos, clips, music and a voiceover in a Drive folder (names like
`music.mp3` and `voiceover.m4a` help; one combined track works too) and run
`/make-reel 2026-11-14 Numa Nights` (or `/make-reel` for the newest folder).

## Commands

| Command | What it does |
|---|---|
| `/make-reel` | The Director's run: one reel and all its outputs from a Drive day folder, hands-off |
| `/build-today` | Daily 5 am: resolves today's plan row and folder, runs the `/make-reel` procedure (or cuts the carousel or Stories), marks the Sheet and notifies Katie |
| `/plan-month` | The 24th, 9 pm: plans next month (research, re-weighting from results, plan Sheet, day folders, SHOOT CARDs); nobody approves it |
| `/night-check` | Daily 8 pm: checks tomorrow's folder against its shoot card, sends the Scout for anything missing, swaps the topic if needed, gives Katie a heads-up |
| `/dashboard-refresh` | Daily 10 pm: pulls Instagram insights through Composio, rebuilds and republishes the performance dashboard |
| `/trend-check` | Fridays 7 pm: three trend ideas that fit NUMA plus a weather check of the coming week |
| `/digest` | Sundays 6 pm: the Monday digest (results, schedule, batched shoot list, credits) as a phone-readable Google Doc |
| `/post-reel` | Auto-posting through Composio at the best time, with the legal-review gate, the approval switch (off by default), the AI label and Trial Reels |
| `/numa-setup` | One-time setup and self-check on Katie's Mac (run by Jude), and `recheck` after updates |
| `/brand-setup` | The brand questionnaire: writes each answer into `brand/brand.json` and the synced copy in `_Plan/` |

## How it runs

- **Scheduled tasks.** Six cloud scheduled tasks (Central time) run `/plan-month`, `/night-check`,
  `/build-today`, `/dashboard-refresh`, `/trend-check` and `/digest`. Times live in
  `config/studio.json` `schedule`; the exact prompts to paste are in
  [docs/SCHEDULED_TASKS.md](docs/SCHEDULED_TASKS.md). The daily reel ships with Katie's Mac asleep;
  only the Scout's Claude in Chrome research needs the desktop app awake, and it falls back to web
  search, the media library and the bundled brand photos.
- **Connectors.** Google Drive (material in, finished files out), Google Sheets (plan Sheet, consent
  list, metrics), Higgsfield (motion clips, outpaint/upscale, music beds; credits tracked by
  `ledger.py` against the 1,200-credit monthly budget), Composio Instagram (posting and insights),
  Claude in Chrome (the Scout), Gmail (optional digest e-mail).
- **The crew.** The Director (the main session) decides everything and never asks Katie anything;
  every failure follows the failure table in `commands/make-reel.md`. Agents:

  | Agent | Job |
  |---|---|
  | `librarian` | Downloads the day folder into `raw/`, converts HEIC, checks it against the shoot card |
  | `analyst` | Runs analyze, fix_transcript, vision and prep_media; rates every photo and clip |
  | `scout` | Finds missing photos, clips, music and facts (NUMA's channels first, then licensed stock) |
  | `motion` | Higgsfield: outpaint, upscale, Kling/Seedance motion clips, music beds, within budget |
  | `scriptwriter` | Hook, voiceover script, shot list and SHOOT CARD with the claims check |
  | `copywriter` | Three caption options, hashtags, Story line and e-mail paragraph, claims-scanned |
  | `editor` | Writes plan.json, validates, previews, renders, finishes, checks the output |
  | `critic` | Fresh-context judge of every render: hard gates plus the weighted rubric, up to 3 rounds |

- **Skills.** `numa-reel-editor` (edit grammar, plan building and every script),
  `numa-scriptwriter` (pre-production and `templates.json`, the reel templates), `numa-caption`
  (copy in NUMA's voice) and `numa-brand-check` (the pre-post review).

## What v2 adds

Brand as data (`brand/brand.json` + `/brand-setup`), operational config in one place
(`config/studio.json`), JSON Schemas and a plan validator that fails a bad plan before a render,
every format from one run (reach cut, Stories, 4:5 carousel, cover, .srt, hook variants), smart
framing (faces and subjects), clip intelligence and stabilize/brighten, natural clip sound,
draft and multi-core deterministic rendering, broadcast-grade mastering (-15 LUFS, true peak
-1.5 dB) with an output-spec checker and 12 Critic frames, reel templates and kinetic text cards,
feedback memory, the media library, the credit ledger and budget pacing, the 30-day system with
shoot cards, the night-before check, the performance dashboard and Monday digest, auto-posting, and
CI. Details per release: [CHANGELOG.md](CHANGELOG.md).

## Development

Requirements: Python 3.10+ and ffmpeg (the system binary; `imageio-ffmpeg` is the fallback, and
`vidstab` in the ffmpeg build is used for stabilization when present).

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# macOS: brew install ffmpeg      Debian/Ubuntu: sudo apt-get install ffmpeg
```

The first transcription downloads the faster-whisper `small.en` model (a few hundred MB, once);
`setup_check.py --download-model` fetches it ahead of time. After that nothing needs the network or
credits.

### Running the tests

| Suite | Command | What it covers | Time |
|---|---|---|---|
| Unit | `python3 -m pytest tests/unit -q` | Every script, schema, data file and instruction file, on small synthetic fixtures | ~6 min |
| End-to-end (M3) | `python3 tests/run_tests.py` | Five material folders (photos only with no audio; clips with their own sound; voice + music; music only with a script; iPhone HEIC photos) through the whole pipeline to a postable reel and its formats | ~15-20 min (`--draft` is faster; `--only NAME`, `--seconds S`, `--keep`, `--extra`) |
| Golden (M2) | `NUMA_TEST_PACK=/path/to/test-pack python3 tests/golden_year_one.py` | The Year One test pack end to end: BPM, transcript, story arc, before/after wipe, cuts on beats, synced captions, output spec, time; comparison with the hand-built reference | ~10 min; prints SKIP without a pack |

The fixtures are synthetic (bundled brand photos, ffmpeg-generated audio and voice); the golden test
reads the test pack from a path you pass and never copies it into the repo. CI
([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the unit tests on Python 3.10 and 3.12,
a Python 3.10-grammar parse check of every `.py` file, and the five-folder suite on every push and
pull request.

### Release checklist

Every release re-runs the M2 golden test (spec p.52). If the Year One reel gets worse, the release
does not ship.

1. `python3 -m pytest tests/unit -q` and `python3 tests/run_tests.py`: all green.
2. `NUMA_TEST_PACK=... python3 tests/golden_year_one.py`: exit 0; Jude rates the reel against the
   hand-built reference with the comparison sheet and the steps the harness prints.
3. Record the golden result and Jude's verdict in CHANGELOG.md under the release.
4. Bump the version in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (kept
   equal; `tests/unit/test_release.py` checks), tag `vX.Y.Z`, push.

### Repo layout

```
.claude-plugin/          plugin.json, marketplace.json (source "./")
.github/workflows/ci.yml unit tests (3.10/3.12), parse check, five-folder suite
brand/brand.json         brand facts with a status each (confirmed, needs_katie, ...)
config/studio.json       model tiers, Higgsfield prices and budget, render and loudness targets,
                         Critic rubric, schedule, Instagram settings, output formats
schemas/                 analysis, plan, brand and script JSON Schemas (draft 2020-12)
commands/                the slash commands above
agents/                  the crew above
skills/numa-reel-editor/ SKILL.md, scripts/ (every pipeline script), assets/ (wordmark, phoenix,
                         hero image, 6 brand photos, fonts, face model, example plans)
skills/numa-scriptwriter/ SKILL.md, templates.json
skills/numa-caption/     SKILL.md
skills/numa-brand-check/ SKILL.md
docs/                    CONTRACTS.md, SETUP_GUIDE.md, SCHEDULED_TASKS.md, QUESTIONS_FOR_KATIE.md
tests/                   unit/, run_tests.py (M3), golden_year_one.py (M2), conftest.py
```

Scripts (in `skills/numa-reel-editor/scripts/`, each with `--help`; command lines in
[docs/CONTRACTS.md](docs/CONTRACTS.md) section 9): `analyze.py`, `fix_transcript.py`, `vision.py`,
`prep_media.py`, `baseline_plan.py`, `validate_plan.py`, `claims_scan.py`, `engine.py`, `finish.py`,
`check_output.py`, `qa_frames.py`, `formats.py`, `ledger.py`, `metrics.py`, `dashboard.py`,
`library.py`, `prefs.py`, `sources.py`, `critic_score.py`, `digest_data.py`, `setup_check.py`,
`shoot_card.py`; shared helpers in `numa_common.py`.

### Environment variables

| Variable | Effect |
|---|---|
| `NUMA_BRAND` | Use another brand.json (run commands point it at `_Plan/brand.json` when that copy is newer) |
| `NUMA_CONFIG` | Use another `config/studio.json` |
| `NUMA_FFMPEG`, `NUMA_FFPROBE` | Paths to the ffmpeg / ffprobe binaries |
| `NUMA_RENDER_CACHE` | Engine video-frame cache folder (default: a hidden temp folder under the plan's out_dir; set it outside a synced Drive folder) |
| `NUMA_DEBUG=1` | Show Python tracebacks for unexpected errors (scripts otherwise print one `ERROR:` line) |
| `NUMA_TEST_PACK` | Year One test pack folder for `tests/golden_year_one.py` |
| `NUMA_REFERENCE_REEL` | Hand-built reference reel for the golden comparison sheet |

### Docs

- [docs/CONTRACTS.md](docs/CONTRACTS.md): data contracts, work-folder layout, deliverable names,
  validation rules and every script's command line (authoritative).
- [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md): Jude's one-afternoon setup.
- [docs/SCHEDULED_TASKS.md](docs/SCHEDULED_TASKS.md): the six scheduled tasks and their prompts.
- [docs/QUESTIONS_FOR_KATIE.md](docs/QUESTIONS_FOR_KATIE.md): the brand questions only Katie can answer.

## Privacy and licensing

- The repo is public. Never commit secrets (API keys, tokens; connectors hold the credentials) or
  member photos. The only media in the repo are NUMA's own brand assets under
  `skills/numa-reel-editor/assets/`; the test pack and the developer kit stay outside the repo
  (`spec/` is git-ignored) and the tests build their own fixtures. `tests/unit/test_release.py`
  scans for both.
- Raw files stay in Katie's Drive and on her machine. Only chosen hero photos go to Higgsfield, and
  never a member's face without consent on the Consent List.
- Music must be Katie's or licensed; every outside file is recorded in `sources.txt`.
- Fonts: Liberation Serif (SIL Open Font License, `skills/numa-reel-editor/assets/fonts/LICENSE`).
  Face detection model: YuNet (`skills/numa-reel-editor/assets/models/LICENSE`). Brand assets ©
  NUMA Wellness Collective.

## Costs

Higgsfield Plus (1,200 credits a month, split per `config/studio.json` `budget`), Claude Max, Composio
free plan: about $150-160 a month. With no credits left, reels are still made, just without AI motion.
