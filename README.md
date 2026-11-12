# NUMA Studio

NUMA Wellness Collective's in-house video studio for Claude. Drop the day's photos, clips, music and voiceover in Google Drive, run `/make-reel`, and get back a finished, on-brand vertical reel with an Instagram caption.

## Install (one time)
In the Claude desktop app, open the plugin settings, add the marketplace `CordiaJude/numa-studio` (the GitHub repo), then install **numa-studio**.
In Claude Code: `/plugin marketplace add CordiaJude/numa-studio` then `/plugin install numa-studio@numa-studio`.

Then connect **Google Drive** and **Higgsfield** under Settings → Connectors and run `/numa-setup` once.

## Daily use
1. In Google Drive, make a folder for the reel (e.g. `2026-11-14 Numa Nights`) and drop in photos/clips, the music, and the voiceover (name them like `music.mp3`, `voiceover.m4a`; a single combined track works too).
2. In Claude: `/make-reel 2026-11-14 Numa Nights` (or just `/make-reel` for the newest folder).
3. Claude finds the files, writes the script from the voiceover, adds Higgsfield motion, edits to the beat, captions every word, ends on the NUMA logo, and sends back the MP4 with a caption.

## What's inside
| Piece | What it does |
|---|---|
| `skills/numa-reel-editor` | The editor: brand kit, edit rules, Higgsfield workflow, and the render engine (`scripts/engine.py`), analyzer (`scripts/analyze.py`) and finisher (`scripts/finish.py`) |
| `skills/numa-caption` | Captions and hashtags in NUMA's voice |
| `skills/numa-brand-check` | Reviews any video or graphic against the brand before posting |
| `commands/make-reel` | One command, whole workflow |
| `commands/numa-setup` | Readiness check for packages, Drive and Higgsfield |
| `commands/plan-month` | Plans 30 days: Sheet, Drive folders, shoot cards, credit split |
| `skills/numa-scriptwriter` | Scripts, hooks, shot lists and shoot cards, with the claims check |
| `agents/` | The crew: librarian, scout, analyst, motion, scriptwriter, copywriter, editor (mid/small models) and critic (top model) |
| `brand/brand.json` | Single source of truth for NUMA's brand; values marked research/placeholder until Katie confirms |
| `scripts/baseline_plan.py`, `scripts/validate_plan.py` | Valid beat-synced starting plan; plan checker that fails before a long render |
| `tests/run_tests.py` | Five-folder test suite (milestone M3) |

## Tests
`python3 tests/run_tests.py` builds five material folders from the bundled brand photos and generated audio and runs analyze, baseline plan, validate, render and finish on each. Add `--voice some_voice_file` to test with a real voiceover. Last run (v1.3.0, Linux sandbox, 10 s renders): all 5 passed (photos + music 71 s, clips only 202 s, voice + music 136 s, combined track 116 s, HEIC photos 73 s). Clip-heavy renders are the slow path; see "Faster renders" in the brief.

## Costs
Plan on Higgsfield Plus (1,200 credits a month). Kling 3.0 motion clips cost about 9 credits each, photo outpaint and upscale 2, a custom music bed about 6. With no credits, reels are still made, just without AI motion.

Fonts: Liberation Serif (SIL Open Font License, see `skills/numa-reel-editor/assets/fonts/LICENSE`). Brand assets © NUMA Wellness Collective.
