# Changelog

All notable changes to NUMA Studio are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Entries for 1.0.0-1.3.0 are
reconstructed from the git history.

## [Unreleased] (2.0.0)

### Added
- `config/studio.json`: one place for agent model tiers, the Higgsfield price
  table and default models, the 1,200-credit monthly budget split and day-15
  pacing rule, the Critic's rubric and pass rule, render/loudness targets, the
  scheduled-task table (Central time), Instagram/Composio settings (Graph API
  v26.0, insight pulls at 48 h, 72 h and 7 days) and the output formats. Every
  section cites its spec page.
- JSON Schemas (draft 2020-12) in `schemas/`: `plan.schema.json` (v2, a
  backward-compatible superset of the v1 contract: `schema_version`, `fps`,
  `size`, `quality`, `seed`, `hook`, per-shot `focus`/`faces`/`peak`/
  `people`/`consent`/`ai_generated`, `signature`, `nat`, `music`, `ai`,
  `template`, `meta`, `formats`), `analysis.schema.json` (v2: `voice_present`,
  clip `has_audio`/`fps`/`size`, faces, focus, best windows, corrections) and
  `brand.schema.json`.
- `docs/CONTRACTS.md`: the authoritative data contracts, work-folder layout,
  deliverable names, CLI conventions, every planned script's command line and
  the cross-field validation rules.
- `skills/numa-reel-editor/scripts/numa_common.py`: shared helpers (plugin
  paths, ffmpeg/ffprobe lookup with the imageio-ffmpeg fallback and an
  `ffmpeg -i` probe parser, cached brand/config loading, atomic JSON writes,
  schema validation with readable paths, `run_cli` with `ERROR:` lines and
  exit codes 1/2 and no tracebacks, subprocess helpers).
- `requirements.txt`, `requirements-dev.txt`, a pytest scaffold
  (`tests/conftest.py` with synthetic media factories) and unit tests for
  packaging, schemas, brand/config data and the shared helpers.
- GitHub Actions CI: unit tests and the five-folder suite on every push and
  pull request, plus a Python 3.10 compile check.
- This changelog.

### Changed
- `brand/brand.json` upgraded to schema_version 2: every brief fact with a
  status (`confirmed`, `from_website`, `research`, `needs_katie`, `bundled`,
  `generated`), sessions and prices, the collective, series, collab partners,
  audiences, competitors, palette roles, fonts, Drive layout, consent and
  closures, posting gates, Jude escalation, transcript fixes (Mobile, NUMA,
  Katie, Scott, Dauphin) and the claims policy as data (banned patterns with
  labels, per-modality say/never-say, safety line, dosing line blocked until
  counsel).
- Operational numbers (Higgsfield budget, Instagram API version) moved from
  `brand/brand.json` to `config/studio.json`.
- `assets/example-plan-year-one.json` carries a note that it is an example
  whose paths point at the original build machine.

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

[Unreleased]: https://github.com/CordiaJude/numa-studio/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/CordiaJude/numa-studio/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/CordiaJude/numa-studio/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/CordiaJude/numa-studio/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/CordiaJude/numa-studio/releases/tag/v1.0.0
