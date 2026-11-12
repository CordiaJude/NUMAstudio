# NUMA Studio v2 build plan

Spec: `spec/SPEC.txt` (and `spec/SPEC.pdf`). Requirements: `REQUIREMENTS.md` (R1–R327). Current-state audit: `GAP_AUDIT.md`. Decisions: `DECISIONS.md`. Progress: `STATUS.md`.

## Stack
- Claude plugin: Markdown (`commands/`, `agents/`, `skills/*/SKILL.md`) + Python 3.10+ scripts + JSON data. No server.
- Python deps (`requirements.txt`): numpy, opencv-python-headless, pillow, pillow-heif, librosa, faster-whisper, imageio-ffmpeg, jsonschema; dev: pytest.
- ffmpeg: system binary, else `imageio_ffmpeg` fallback (one helper in `numa_common.py`).
- Tests: `pytest tests/unit` (fast, synthetic fixtures) + `python3 tests/run_tests.py` (end-to-end five-folder suite) + `tests/golden_year_one.py` (M2 harness, needs the test pack path). CI: GitHub Actions.

## Architecture
Stage scripts are standalone CLIs invoked by Claude by absolute path, each with `main()` so tests can import them. Shared helpers in `skills/numa-reel-editor/scripts/numa_common.py`. JSON files are the interface: `analysis.json` (analyze → Claude), `plan.json` (Claude → engine/finish/formats), both versioned and validated by JSON Schemas in `schemas/`. Brand facts in `brand/brand.json`; operational config (model tiers, Higgsfield prices, budget split, schedule, Graph API version) in `config/studio.json`. Work folder per reel: `raw/`, `work/` (analysis, plan, renders, QA), `out/` (deliverables).

## Directory structure (target)
```
.claude-plugin/{plugin.json,marketplace.json}
.github/workflows/ci.yml
brand/brand.json
config/studio.json
schemas/{analysis.schema.json,plan.schema.json,brand.schema.json}
docs/{CONTRACTS.md,SETUP_GUIDE.md,QUESTIONS_FOR_KATIE.md,SCHEDULED_TASKS.md}
commands/*.md        agents/*.md
skills/numa-reel-editor/{SKILL.md,scripts/*.py,assets/}
skills/numa-scriptwriter/{SKILL.md,templates.json}
skills/numa-caption/SKILL.md  skills/numa-brand-check/SKILL.md
tests/{run_tests.py,golden_year_one.py,unit/*.py,conftest.py}
requirements.txt CHANGELOG.md README.md
```

## Shared contracts
Defined by T0 in `schemas/*.json` + `docs/CONTRACTS.md` (authoritative once T0 is accepted). plan.json v2 is a backward-compatible superset of the spec's contract (p.26) adding: `schema_version`, `fps`, `size`, `quality` (final|draft), `seed`, `hook` (frame-zero text), per-shot `focus`/`faces` (smart framing), `signature`, `nat` (natural-sound bursts), `music` (source + license), `ai` (AI-person/scene flags), `template`, `formats` (reach cut-down, story set, carousel, cover). Naming: snake_case JSON keys, times in seconds (float), paths absolute, colors `[r,g,b]`. Script conventions: exit 0 ok / 1 validation or user error with a one-line `ERROR:` message (no traceback) / 2 usage; warnings as `WARN:` lines; machine-readable reports as JSON next to outputs.

## Tasks
Ownership is exclusive. "Tests" = the task's own `tests/unit/test_<name>.py`.

| Id | Wave | Goal | Owns | Covers |
|----|------|------|------|--------|
| T0 | 0 (alone) | Foundation: shared helper, config, brand data v2, JSON Schemas, contracts doc, requirements.txt, pytest scaffold, packaging tests, CI skeleton, CHANGELOG skeleton | `numa_common.py`, `config/`, `brand/brand.json`, `schemas/`, `docs/CONTRACTS.md`, `requirements.txt`, `tests/conftest.py`, `tests/unit/test_packaging.py`, `tests/unit/test_schemas.py`, `tests/unit/test_common.py`, `.github/workflows/ci.yml`, `CHANGELOG.md`, `.claude-plugin/*`, `assets/example-plan-year-one.json` (upgrade to v2) | R1–R2, R8–R11, R79–R82, R144–R153 (data), config items, R319–R327 scaffolding |
| T1 | 1 | Engine: spec fixes + v2 features | `engine.py`, `tests/unit/test_engine.py` | R34–R35, R50–R78 (code), determinism, multi-core, draft, output size, hook, framing focus, no mirrored edges/black bars, brand.json fonts/colors |
| T2 | 1 | Analyze: ingest classify, mix, transcript (no hallucinated words on music), corrections, beats, contact sheets, clip-audio inventory | `analyze.py`, `fix_transcript.py`, `tests/unit/test_analyze.py` | R13–R29 (code), R102 code part |
| T3 | 1 | Finish: mastering, 2-pass loudness + true peak, mean-level warn, nat-sound mix, mux, output-spec check, QA strip + 12-frame critic set | `finish.py`, `check_output.py`, `qa_frames.py`, `tests/unit/test_finish.py` | R36–R40, R284–R285, R291–R293 |
| T4 | 1 | Validator + baseline planner + claims scanner | `validate_plan.py`, `baseline_plan.py`, `claims_scan.py`, tests | R42–R49 (code), R83–R90, R126–R143 (code), R303-ish |
| T5 | 2 | Vision: faces/subjects for smart framing, clip scoring + best windows, stabilize/brighten prep | `vision.py`, `prep_media.py`, tests | R276–R281 (framing), R286–R288, failure rows for shaky/dark/low-res |
| T6 | 2 | Formats: reach cut-down, story set, carousel 4:5, cover, .srt from one plan | `formats.py`, tests | R229–R237 |
| T7 | 2 | Ops scripts: credit ledger/budget pacing, metrics + dashboard HTML, media library index, feedback memory, sources.txt | `ledger.py`, `metrics.py`, `dashboard.py`, `library.py`, `prefs.py`, `sources.py`, tests | R216–R228 (code), R243–R252, R276–R277, R289 |
| T8 | 2 | Instruction layer A: Director + crew + Critic + reel-editor/caption/brand-check skills | `commands/make-reel.md`, `agents/*.md`, `skills/numa-reel-editor/SKILL.md`, `skills/numa-caption/SKILL.md`, `skills/numa-brand-check/SKILL.md`, `tests/unit/test_instructions_a.py` | R30–R33, R41, R91–R125, R126–R143 (instr), R196–R228 (instr), R282–R283 |
| T9 | 3 | Instruction layer B: 30-day system, scriptwriter, templates, shoot cards, night-before, digest, trend check, dashboard refresh, daily build, scheduled tasks | `commands/{plan-month,night-check,build-today,digest,trend-check,dashboard-refresh}.md`, `skills/numa-scriptwriter/*`, `docs/SCHEDULED_TASKS.md`, `shoot_card.py`, tests | R154–R195, R238–R242, R261–R264 |
| T10 | 3 | Setup + posting: /numa-setup, /brand-setup, setup_check.py (3 s test render, model pre-download), setup guide, questions for Katie, auto-posting via Composio | `commands/{numa-setup,brand-setup,post-reel}.md`, `setup_check.py`, `docs/SETUP_GUIDE.md`, `docs/QUESTIONS_FOR_KATIE.md`, tests | R253–R275, R315–R318 |
| T11 | 4 | Integration: five-folder suite per M3, golden Year One harness, CI final, README, CHANGELOG 2.0.0, version bump, cross-file consistency | `tests/run_tests.py`, `tests/golden_year_one.py`, `README.md`, final edits to CHANGELOG/plugin.json/marketplace.json/ci.yml | R304–R314, R319–R327 |

Dependencies: T0 → wave 1 → wave 2 → wave 3 → T11. Changes to T0-owned shared files after T0 go through the orchestrator (small) or a sequential task.
