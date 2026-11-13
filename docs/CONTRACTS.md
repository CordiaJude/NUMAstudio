# NUMA Studio data and CLI contracts (v2)

This file is authoritative for every script, agent and command in the plugin.
Machine-checkable parts live in `schemas/*.schema.json` (JSON Schema draft
2020-12); this document adds defaults, who writes and reads each field, the
cross-field rules the validator enforces, the work-folder layout, and the
command line of every script. Change it only through the orchestrator.

Spec references are to `spec/SPEC.pdf` ("NUMA Studio - Product & Engineering
Brief", Nov 12 2026). "Interpretation N" refers to the numbered list at the
end of `REQUIREMENTS.md`.

Contents: [1 Conventions](#1-conventions) · [2 Work folder](#2-work-folder-and-deliverables) ·
[3 analysis.json](#3-analysisjson) · [4 plan.json](#4-planjson) ·
[5 Cross-field rules](#5-cross-field-validation-rules-validate_planpy) ·
[6 brand.json](#6-brandbrandjson) · [7 config/studio.json](#7-configstudiojson) ·
[8 Other files](#8-other-files) · [9 Script CLIs](#9-script-command-lines)

---

## 1. Conventions

**Units and names.** JSON keys are `snake_case`. Times are seconds as floats on
the reel timeline (clip times are called `start` or "clip time"). Pixel values
in a plan are output pixels of the plan's `size` (default 1080x1920); when a
render is scaled (`--draft`, `--size`) the engine scales them proportionally.
Colours are `[r, g, b]` integers 0-255 in plans and `#RRGGBB` in brand.json.
Normalized coordinates are fractions 0-1 of the source image, x to the right,
y down; a point is `[x, y]`, a box is `[x, y, w, h]`.

**Paths.** Every path inside analysis.json and plan.json is absolute. Command
line arguments may be relative (resolved against the current folder). Paths
inside brand.json and config/studio.json are relative to the plugin root
(`numa_common.plugin_path()` resolves them). Scripts find their own assets
relative to their own file, never the current folder, so Claude can call them
by absolute path from anywhere (R8).

**Versions.** analysis.json, plan.json and brand.json carry `schema_version`
(analysis 2, plan 2, brand 2). A plan without `schema_version` is a v1 plan
and must still validate and render. Writers of new files always write the
current version.

**Exit codes and output.**

| Exit | Meaning |
|------|---------|
| 0 | Success (warnings allowed) |
| 1 | User, input or validation error (missing file, bad JSON, schema error, no audio, failed check) |
| 2 | Usage error (bad or missing arguments) |
| 130 | Interrupted |

- Errors are one line each: `ERROR: <what>: <problem>` on stderr. A script may
  print several `ERROR:` lines (e.g. the validator) and then exit 1.
- Warnings are `WARN: <what>: <problem>` on stderr; they never change the exit code
  unless the script documents `--strict`.
- Progress/info lines go to stderr. stdout carries the result: a short human
  summary, or, with `--json`, exactly one JSON document and nothing else.
- Never a Python traceback for user errors. Every script wraps `main()` in
  `numa_common.run_cli`, which maps `UserError` to exit 1, `UsageError` to exit
  2, JSON/missing-file errors to exit 1 and anything unexpected to a one-line
  `ERROR: unexpected <Type>: ...` with exit 1 (`NUMA_DEBUG=1` shows the
  traceback). Argument parsing uses `numa_common.ArgParser` (usage + `ERROR:`
  line, exit 2).
- `-h/--help` prints usage and exits 0. Running a script with no arguments
  prints usage and an `ERROR:` line and exits 2 (R321).
- Machine-readable reports are JSON files written next to the outputs
  (`render.json`, `report.json`, `critic_frames/index.json`).

**Other rules for every script.** `main(argv=None)` so tests can import it;
no work at import time. Python 3.10+ syntax. pathlib, `tempfile` for scratch
(no hard-coded `/tmp`, `/home`, `/mnt`). ffmpeg only via
`numa_common.ffmpeg_bin()`/`ffmpeg()`/`media_info()`. JSON writes via
`numa_common.write_json()` (atomic, indent 2). No network calls (R11); the
one exception is faster-whisper's first model download. Deterministic: no
unseeded randomness; same inputs give byte-identical outputs. Idempotent:
re-running a stage overwrites its own outputs and never corrupts inputs.

**Environment variables.** `NUMA_BRAND` (another brand.json), `NUMA_CONFIG`
(another studio.json), `NUMA_FFMPEG` / `NUMA_FFPROBE` (binaries), `NUMA_RENDER_CACHE` (engine video-frame cache folder; default a hidden temp folder under the plan's out_dir, or under the system temp folder when out_dir is cloud-synced: path contains "Google Drive", "GoogleDrive", "CloudStorage", "Dropbox" or "OneDrive"),
`NUMA_DEBUG=1` (tracebacks for unexpected errors).

**Shared helper.** `skills/numa-reel-editor/scripts/numa_common.py`: paths
(`PLUGIN_ROOT`, `ASSETS_DIR`, `FONTS_DIR`, `BRAND_PHOTOS_DIR`, `SCHEMAS_DIR`,
`plugin_path`), `ffmpeg_bin`, `ffprobe_bin` (may be `None` with the
imageio-ffmpeg fallback), `ffmpeg`, `ffprobe_json` (falls back to parsing
`ffmpeg -i`), `media_info` (normalized: duration, size after rotation, fps,
codecs, sample rate, channels, has_audio), `media_duration`, `run`,
`read_json`, `write_json`, `update_report`, `schema_errors`,
`validate_against`, `load_brand`, `load_config`, `brand_value`,
`config_value`, `fact`, `brand_color`, `accent_rgb`, `brand_asset`,
`brand_font`, `hex_to_rgb`, `slugify`, `JobPaths`, `deliverable_name`,
`parse_size`, `require_abs`, `UserError`, `UsageError`, `run_cli`,
`ArgParser`, `warn`, `error_line`, `info`, `print_json`.

---

## 2. Work folder and deliverables

One folder per reel ("job"). Files on disk are the state: every stage reads
its inputs from here and writes its outputs here, so any stage can be re-run.
The Librarian picks the job folder (one per Drive day folder; its name is the
Drive folder name, e.g. `Day 07 - 2026-12-09 - Your first plunge`).

```
<job>/
  raw/                      downloaded material, Drive subfolders preserved (photos/, clips/,
                            voiceover.*, music.*, SHOOT CARD text); never modified by scripts
  work/
    analysis.json           analyze.py (+ fix_transcript.py, vision.py, prep_media.py)
    master.wav              analyze.py: voice+music mix or the single track, 48 kHz stereo
    pad.wav                 analyze.py: offline music pad, only when the folder has no audio
    contact_photos.jpg      analyze.py: numbered photo thumbnails P0, P1, ...
    contact_clips.jpg       analyze.py: clip frames labelled "C<k> @<t>s"
    media/                  analyze.py: converted copies (HEIC -> JPG)
    prep/                   prep_media.py: stabilized / brightened copies (<id>.mp4, <id>.jpg)
    plan.json               the Editor (Claude) or baseline_plan.py
    preview.jpg             engine.py preview
    video_noaudio.mp4       engine.py full render
    video_noaudio_draft.mp4 engine.py --draft
    render.json             engine.py: timing, frames, workers, size, encoder
    aud.wav                 finish.py: mastered audio
    sources.json            sources.py: every outside file and its license
  out/                      deliverables (uploaded to Drive Finished/)
    <slug>_reel.mp4         main reel (finish.py)
    <slug>_reach.mp4        reach cut-down, 8-12 s (formats.py)
    <slug>_story_<N>.jpg    story stills, or <slug>_story_<N>.mp4 5 s clips (formats.py)
    <slug>_carousel_<N>.jpg 1080x1350 carousel slides (formats.py)
    <slug>_cover.jpg        1080x1920 cover, title inside the centre square (formats.py)
    <slug>_hook_<N>.mp4     hook-variant openings (formats.py)
    <slug>.srt              voiceover captions (formats.py)
    <slug>_copy.txt         Instagram caption, Story line, email paragraph (Copywriter)
    sources.txt             human-readable sources and licenses (sources.py)
    qa_strip.jpg            6-frame QA strip, 1620x480 (finish.py)
    critic_frames/          12 Critic frames + index.json (qa_frames.py)
    report.json             per-stage machine report (see section 8)
```

- `<slug>` = `plan.meta.slug` if set, else `slugify(<job folder name>)`
  (lowercase ASCII letters, digits and hyphens). `numa_common.JobPaths` and
  `deliverable_name()` build these names; N counts from 1.
- A plan's `out_dir` is `<job>/work` (renders); finished deliverables go to
  `<job>/out`.
- `numa_common.JobPaths(job).make()` creates `raw/`, `work/`, `out/`.

---

### Local state folder and run files (instruction layer)

- `STUDIO` = `~/NUMA Studio` (the desktop/sandbox working root); `STATE` = `STUDIO/_Plan`, mirrored to Drive `NUMA Reels/_Plan/`. It holds `preferences.json` (prefs.py), `credit_ledger/` (ledger.py folder mode, `ledger_YYYY-MM.json`), `media_library.json` (library.py), `consent_list.json` (export of the Consent List Sheet), `competitors_YYYY-MM.json` (Scout log read by dashboard.py), `metrics.json` (metrics.py), `plans/` (month JSON per month), `closures.json`, `digest_notes.json`, `digest/`, `trends/`, `insights/` (raw Composio pulls), `dashboard.html`, `dashboard_notes.json` (Do more of / Do less of), `dashboard_artifact.json` (published artifact URL).
- Per-reel work files written by the crew: `work/script.txt` (shoot-card script), `work/plan_row.json`, `work/inventory.json` (librarian), `work/ratings.json` (analyst), `work/scout.json`, `work/material.json`, `work/motion.json` (motion crew), `work/decisions.md` (Decisions log), `work/critic_r<N>.json` + `work/critic_rounds.json` (critic_score.py), `work/versions/r<N>/`, `work/upload_queue.json`, `work/delivered.json`; extra material under `raw/scout/`, `raw/library/`, `raw/generated/`.

## 3. analysis.json

Schema: `schemas/analysis.schema.json` (schema_version 2). Written by
`analyze.py`; amended in place by `fix_transcript.py` (words, transcript,
corrections), `vision.py` (faces, focus, windows, scores) and `prep_media.py`
(prepared_path). Read by Claude (Analyst, Director, Editor),
`baseline_plan.py`, `validate_plan.py`, `formats.py` (srt fallback).
Producers may add fields; consumers ignore fields they don't know.

| Field | Type | Req | Meaning / default | Writer |
|-------|------|-----|-------------------|--------|
| `schema_version` | int, const 2 | yes | Contract version | analyze |
| `duration` | number >= 0 | yes | Length of `master.wav` (s); 0 when there is no audio and no pad | analyze |
| `bpm` | number or null | yes | Tempo of the music (else the master); null without audio | analyze |
| `beats` | number[] | yes | Beat times (s), ascending | analyze |
| `words` | object[] | yes | Spoken words in order; `[]` for music-only material (never hallucinated) | analyze, fix_transcript |
| `words[].w` | string | yes | Word text with its punctuation | analyze, fix_transcript |
| `words[].appear` | number | yes | Caption appear time = max(start, end - 0.4) | analyze |
| `words[].end` | number | yes | Recognizer end time | analyze |
| `words[].start` | number | no | Recognizer start time | analyze |
| `words[].p` | number 0-1 | no | Recognizer word probability | analyze |
| `transcript` | string | yes | Words joined with spaces (after corrections) | analyze, fix_transcript |
| `voice_present` | bool | yes | Speech found (voiceover or combined track with voice) | analyze |
| `audio.voice` | path or null | yes | Voiceover file used | analyze |
| `audio.music` | path or null | yes | Music file used (`work/pad.wav` for the offline pad) | analyze |
| `audio.master` | path or null | yes | `work/master.wav`; null only when there is no audio at all | analyze |
| `audio.combined` | bool | no | One file held voice and music | analyze |
| `audio.generated_pad` | bool | no | `music` is the offline pad (last-resort fallback, interpretation 8) | analyze |
| `audio.clip_audio[]` | {id, peaks[], mean_db} | no | Clips with usable natural sound; `peaks` in clip time | analyze |
| `photos[]` | object[] | yes | One per image, ids `P0`, `P1`, ... in sorted file order | analyze |
| `photos[].id` / `.path` / `.size` | `P<n>` / path / [w, h] | yes | `path` is the usable JPG/PNG (converted copy for HEIC) | analyze |
| `photos[].orig_path` | path | no | Original file when converted | analyze |
| `photos[].sharpness` | number >= 0 | no | Variance of Laplacian on a 1080-wide copy | analyze |
| `photos[].brightness` | number 0-1 | no | Mean luma | analyze |
| `photos[].faces` | box[] | no | Face boxes, normalized | vision |
| `photos[].focus` | point | no | Subject point for framing, normalized | vision |
| `photos[].prepared_path` | path | no | Brightened copy; use as shot `src` (D13) | prep_media |
| `clips[]` | object[] | yes | One per video, ids `C0`, `C1`, ... | analyze |
| `clips[].id` / `.path` / `.duration` | `C<n>` / path / s | yes | | analyze |
| `clips[].has_audio` | bool | yes | The clip has an audio stream | analyze |
| `clips[].fps` | number | yes | Average frame rate | analyze |
| `clips[].size` | [w, h] | yes | Display size after rotation metadata | analyze |
| `clips[].rotation` | number | no | Rotation metadata (degrees) | analyze |
| `clips[].sharpness` / `.brightness` / `.shake` | numbers | no | Weak-media signals (R29) | analyze |
| `clips[].faces` / `.focus` | box[] / point | no | From the clip's best window | vision |
| `clips[].windows` | [t0, t1, score][] | no | Best windows in clip time, best first, score 0-1 | vision |
| `clips[].scores` | {t, sharpness, motion, faces, score}[] | no | Per-second scores (R282) | vision |
| `clips[].prepared_path` | path | no | Stabilized/brightened copy; use as shot `src` (D13) | prep_media |
| `corrections[]` | {index, from, to, reason} | no | Applied transcript fixes; `reason` `brand_fix` or `script` | fix_transcript |
| `contact_sheets` | {photos, clips} | no | Contact sheet paths (null when none) | analyze |
| `warnings` | string[] | no | Degradations (no transcript, offline pad used, ...) | all writers |

Timing is never changed by corrections: `fix_transcript.py` edits `w` only.

**v1 analysis files are rejected.** v1 `analyze.py` wrote no `schema_version`,
`voice_present`, `clips[].has_audio`/`fps`/`size`; such a file fails the
schema. There is no migration: re-run `analyze.py` on the job's `raw/` folder
(it is idempotent and cheap compared with a render).

---

Vision fields (written by vision.py): photos[]/clips[] `flags` (subset of landscape, low_res, blurry, shaky, dark), `faces`, `focus`, clips[] `scores` and `windows`. prep_media.py records prepared sources in `WORK/prep/index.json` (source SHA-256, steps, forced steps) and sets `prepared_path`. Optional per-item `consent` (true/"yes", false/"no", absent = unknown; set by the analyst from the Consent List or library tags) is read by baseline_plan for rule 41. When `prepared_path` is set, `faces`/`focus` (and clip `scores[].faces`) describe the prepared copy (the shot source) and `orig_faces`/`orig_focus` describe `path`; sharpness/motion/windows/flags still describe the original.

## 4. plan.json

Schema: `schemas/plan.schema.json`. The edit decision list and the only
creative input the renderer reads (R9): `engine.py` reads plan.json plus the
bundled fonts/assets and brand.json defaults, nothing else, so a second engine
could render the same plan. Written by the Editor (Claude) or
`baseline_plan.py`; read by `validate_plan.py`, `engine.py`, `finish.py`
(`nat`), `formats.py`, `qa_frames.py`, `claims_scan.py --plan`.

The v1 contract (spec p.26-27) is a subset: every v1 plan validates. Keys that
start with `_` (e.g. `"_why": "hero clip"`) are notes, allowed at any object
level and ignored. Any other unknown key is a schema error (typos fail loudly).

### Top level

| Field | Type | Default | Meaning | Since |
|-------|------|---------|---------|-------|
| `schema_version` | 1 or 2 | 1 when absent | Contract version; new plans write 2 | v2 |
| `duration` | number > 0 | required | Reel length (s); the last shot ends here | v1 |
| `out_dir` | abs path | plan's folder | Where renders go (`<job>/work`) | v1 |
| `fps` | number | 30 | Frame rate | v1 |
| `size` | [w, h], even ints | [1080, 1920] | Output size | v2 |
| `quality` | `final`/`draft` | `final` | `draft` = lower resolution + fast preset (config `render.draft`) | v2 |
| `seed` | int >= 0 | 0 | Seeds grain and light-leak motion | v2 |
| `accent_rgb` | [r, g, b] | brand palette `caption_gold` | Gold italic caption colour | v1 |
| `caption_y` | px | 1420 | Vertical centre of the caption block | v1 |
| `font_regular` / `font_italic` | abs path | brand.json fonts | Caption fonts | v1 |
| `caption_px` | px 40-200 | config `render.captions.font_px` (92) | Caption font size (feedback preference `caption_px`); the validator measures rows at this size | v2 |
| `hook` | object | none | Frame-zero hook text (below) | v2 |
| `shots` | shot[] (>= 1) | required | The timeline (below) | v1 |
| `lines` | line[] | [] | Captions (below) | v1 |
| `leaks` | leak[] | [] | Light leaks `[time, duration, strength 0-1]` | v1 |
| `endcard` | object | none | End card (below) | v1 |
| `cards` | card[] | [] | Kinetic type: large animated text cards (below) | v2 |
| `signature` | {type, t} | none | The one signature moment: `type` `wipe` or `flash`, at reel time `t` | v2 |
| `nat` | nat[] | [] | Natural-sound bursts (below) | v2 |
| `music` | object | none (required by the validator for v2) | Music source and license (below) | v2 |
| `ai` | {people, scenes, label_required} | all false | AI content flags; `label_required` = switch on Instagram's AI label | v2 |
| `template` | string | none | Template id from the scriptwriter library | v2 |
| `meta` | object | {} | Tags: `slug` (file names), `title`, `series`, `pillar`, `hook_type`, `goal`, `day`; free-form otherwise | v2 |
| `formats` | object | none | Extra outputs from this plan (below) | v2 |

### `hook`

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `text` | string | required | Hook text, full opacity from frame 0. Wrap words in `*asterisks*` for gold italic; with no markup the last word is gold |
| `t1` | number >= 1.5 | 2.0 | When the hook text fades out (visible at least 1.5 s, interpretation 6) |
| `y` | px | just below the top safe area (0.12 x height) | Vertical centre |

### `shots[]`

Shots tile the timeline: `shots[0].t0 = 0`, each `t0` equals the previous
`t1`, the last `t1` equals `duration`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `kind` | `image`/`video` | `image` | Source type |
| `src` | abs path | required | Photo or clip (use `prepared_path` when prep_media made one) |
| `start` | number >= 0 | 0 | Video: clip time shown at `t0` |
| `speed` | number > 0 (<= 8) | 1.0 | Video: playback speed |
| `look` | `before`/`warm`/`none` | `warm` | Colour look |
| `t0`, `t1` | numbers | required | Shot start/end on the reel timeline |
| `z` | [start, end] > 0 | [1.02, 1.14] | Eased zoom; 1.0 = full frame |
| `pan` | [x, y] | [0, 0] | Drift over the shot as a fraction of frame size |
| `tr` | `cut`/`punch`/`whip`/`leakfade`/`fade`/`flash`/`wipe` | `cut` | Transition into this shot |
| `crop` | [left, top, right, bottom] px | none | Image: crop in source pixels before framing |
| `blur` | [[x,y,w,h], ...] normalized | none | Source regions blurred beyond recognition for the whole shot (non-consented people, spec p.6); engine applies it before framing |
| `focus` | [x, y] 0-1 | centre (or vision focus) | Point zoom/pan centre on (smart framing) |
| `faces` | box[] 0-1 | [] | Faces in the source; captions avoid them |
| `peak` | bool | false | Emotional peak: may exceed 4 beats |
| `people` | bool | unset | A recognizable person is in the shot |
| `consent` | bool | unset | Everyone recognizable is on the consent list |
| `ai_generated` | bool | false | Made or animated by AI (Higgsfield) |

Transitions (spec p.19): `punch` hard cut, new shot starts 16% zoomed and
snaps back over 0.22 s with a brief white lift; `whip` both shots slide
sideways over 0.28 s with up to 160 px motion blur; `leakfade` 0.5 s crossfade
under an automatic warm leak; `fade` plain 0.5 s crossfade; `flash` white
flash decaying over 0.35 s; `wipe` soft glowing vertical line sweeping left to
right over 1 s (before/after); `cut` plain cut.

### `lines[]` (captions)

| Field | Type | Meaning |
|-------|------|---------|
| `words` | word[] (>= 1) | `[text, appear_time]` or `[text, appear_time, 1]` (1 = gold italic; 0 is accepted as "not gold") |
| `end` | number | When the line fades out |

One sentence per line, at most 2 rows; each word fades in and rises 22 px over
0.28 s at its appear time (config `render.captions`).

### `leaks[]`

`[time, duration, strength]`: start (s), length (s, > 0), strength 0-1
(interpretation 3: accepted to 1, the validator warns above 0.6).

### `endcard`

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `t` | number | required | When the end card starts (it holds to the end) |
| `logo` | abs path | brand `assets.wordmark` | Logo, rendered white |
| `logo_width` | px | 820 | Logo width |
| `tagline` | string | brand `endcard.tagline` | Spaced uppercase line |
| `subtitle` | string | brand `endcard.default_subtitle` | Gold italic per-reel sign-off |

The ripple background is an ordinary last shot (`assets/heroimage.jpg`), not
an end-card field.

### `cards[]` (kinetic type, R195)

Large animated text cards drawn over the picture, for education templates
("3 things cold plunge does": a title card, then 1 / 2 / 3). The engine blurs
and darkens the picture under the card (or fills it with brand teal), then
reveals the text word by word (each word rises and grows into place, about
0.45 s, 0.09 s apart), in the caption serif with a gold italic accent, inside
the safe area and above the caption block; the card fades out by `t1`. A card
starting at 0 is fully shown from frame 0 (it is the frame-zero text), and the
hook text is not drawn while a card is on screen. Captions stay on top.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `t0`, `t1` | numbers | required | Reveal start and fade-out end (s) |
| `text` | string | required | `number`: one numeral or short label ("1", "MYTH") in large gold italic. `statement`: a short line; `*asterisks*` mark gold italic words, with no markup the last word is gold |
| `style` | `number`/`statement` | `statement` | Card type |
| `sub` | string | none | Smaller white line under the main text |
| `align` | `center`/`left` | `center` | Horizontal alignment |
| `bg` | `blur`/`teal` | `blur` | Blurred, darkened picture, or brand `water_teal` with cream text |
| `y` | px | 0.40 x height | Vertical centre of the card block (kept inside the safe area, above the captions) |

### `nat[]` (natural sound)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `src` | abs path | required | Clip whose own audio is used |
| `start` | number | required | Clip time where the burst starts |
| `t` | number | required | Reel time where it plays |
| `dur` | number > 0 | required | Burst length |
| `gain_db` | -60..12 | -6 | Level relative to the clip audio; mixed under the music, ducked under the voice (finish.py) |

### `music`

| Field | Type | Meaning |
|-------|------|---------|
| `source` | `folder`/`shoot_card`/`higgsfield`/`library`/`sound_collection`/`natural`/`pad` | Order of preference per interpretation 8: folder file > card-specified Library track > Higgsfield-generated > Library by mood > natural sound / offline pad. `sound_collection` = added in Instagram at posting time |
| `path` | abs path or null | The file used (null for `sound_collection`/`natural`) |
| `license` | string or null | License text or URL; required for every source except `natural` and `pad` |
| `title` | string or null | Track title |

### `formats` (formats.py)

| Field | Type | Meaning |
|-------|------|---------|
| `reach_cut` | {t0, t1, hook} | The best 8-12 s of the reel with new hook text |
| `story` | {t, text, clip?}[3-5] | Story stills (or 5 s clips when `clip` is true) from reel time `t`, one line of text each |
| `carousel` | {t or src, text}[5-8] | 1080x1350 slides from reel time `t` or a source photo `src` (exactly one of them) |
| `cover` | {t, title} | 1080x1920 cover from reel time `t`, title inside the centre 1080x1080 square |
| `hook_variants` | {text, src?, start?}[1-3] | Alternate openings: new hook text, optionally a new first-shot source |

### Example

`skills/numa-reel-editor/assets/example-plan-year-one.json` is the v1 Year One
plan, kept as the v1 compatibility fixture (schema_version 1 shape). Its paths point at the
original build machine (`/home/claude/...`, `/mnt/user-data/...`) and do not
exist here: it validates against the schema but not against the file-existence
rules, and cannot be rendered as is.

`skills/numa-reel-editor/assets/example-plan-year-one-v2.json` is the same
reel as a full v2 plan (`hook`, `signature` wipe, `music`, `ai`, `meta`,
`formats`). Plans require absolute paths, so it uses two placeholder
prefixes: `/YEAR_ONE_PACK/` (the Year One test-pack folder: `raw/`, `work/`)
and `/NUMA_PLUGIN/` (the plugin root, for bundled fonts, wordmark and ripple
image). The golden harness rewrites both prefixes before checking files or
rendering; the plan validates against the schema as is.

---

## 5. Cross-field validation rules (validate_plan.py)

JSON Schema covers types, enums, ranges and shapes. `validate_plan.py`
(owner T4) runs the schema first (every violation is an `ERROR` line with its
path, e.g. `ERROR: shots[3].tr: 'zoom' is not one of ...`) and then these
rules. `E` = ERROR (exit 1), `W` = WARN. Tolerances: tiling 1 ms; beat 1 frame
(1/fps).

| # | Rule | Level | Req |
|---|------|-------|-----|
| 1 | Bad JSON, missing file or schema violation | E | R82, R89 |
| 2 | Tiling: `shots[0].t0 == 0`, `shots[i].t0 == shots[i-1].t1`, last `t1 == duration`, every `t1 > t0` | E | R83 |
| 3 | Shot shorter than 0.3 s | W | |
| 4 | Every path absolute: `out_dir`, `shots[].src`, `font_*`, `endcard.logo`, `nat[].src`, `music.path`, `formats.carousel[].src`, `formats.hook_variants[].src` | E | R86 |
| 5 | Every referenced file exists (incl. the effective fonts and logo when defaulted from brand.json) | E | R85 |
| 6 | `duration` > 180 s | E | R86, R75 |
| 7 | `duration` outside 15-60 s (main reel) | W | R75 |
| 8 | Shot 0 `tr` is `whip`, `wipe`, `fade` or `leakfade` (needs a previous shot) | E | R55 |
| 9 | Shot 0 `tr` is `punch` or `flash` (prefer `cut`) | W | R55 |
| 10 | `z` outside 0.95-1.5 | E | R58 |
| 11 | `z[0] == z[1]` (static shot) | W | R57 |
| 12 | Video shot: `start + (t1 - t0) * speed` beyond the clip's duration | W | R88 |
| 13 | `crop` on a video shot, or crop outside the image | E | |
| 14 | Cut more than one frame off the nearest beat (needs analysis.json) | W | R46 |
| 15 | Shot longer than 4 beats without `peak: true` | W | R48 |
| 16 | More whips than one per three cuts | W | R51 |
| 17 | Fewer than 3 transition types with more than 6 shots | W | R56 |
| 18 | Signature: more than one `wipe`, or no `wipe` and no flash outside the end card; when `signature` is set, no shot boundary at `signature.t` with `tr == signature.type` is an E | W/E | R45 |
| 19 | Caption word times not ascending within a line, or a line starts before the previous line's words | E | R87 |
| 20 | Line `end` before its last word's appear time, or after `duration` | E | R87 |
| 21 | Lines overlap (a line's first word before the previous `end`) | W | |
| 22 | A caption line wraps to 3+ rows (measured with the caption font at 92 px in a 960 px box) | E | R66 |
| 23 | Line longer than 80 characters | W | |
| 24 | Caption vs transcript (needs analysis.json; only words with `appear` < `duration`): words aligned by sequence; text mismatch after normalizing case/punctuation or appear time off by more than 0.15 s is W; off by more than 0.5 s, or a caption word missing from the transcript, is E; spoken words shown neither as captions nor on statement cards (more than 3 and 10%) is W, reporting both counts | W/E | R84 |
| 25 | Caption block or hook outside the safe area (top 12%, bottom 10% of the height) | E | R67 |
| 26 | Caption block overlaps a face box of the shot on screen at that time | W | R68 |
| 27 | Any text (lines, hook, cards text/sub, endcard tagline/subtitle, formats texts) hits a `fail` claim in brand.json (or the dosing line while blocked); `warn`-severity hits are W | E/W | R128 |
| 28 | Shot with `people: true` and `consent` not true | E | R141 |
| 29 | v2 plan without `music`, or `music.license` empty for a source other than `natural`/`pad` (source `folder` = NUMA's own file: W, record it in sources.txt) | E | R141 |
| 30 | `ai.people` or `ai.scenes` true, or any `ai_generated` shot, while `ai.label_required` is not true | E | R139 |
| 31 | End card: `t` not inside (0, duration) | E | R49 |
| 32 | End card holds less than 3.5 s or more than 5 s, or does not start on a shot boundary | W | R49 |
| 33 | Leak `time + duration` past the end, or strength above 0.6 | W | R63 |
| 34 | `hook.t1` beyond `duration`; no `hook` in a v2 plan | E/W | R71 |
| 35 | `nat`: burst past the reel end, past the clip's end, or the clip has no audio | W | R284 |
| 36 | `formats.reach_cut` not 8-12 s long or outside the reel; any `formats` time outside the reel | E | R231 |
| 37 | `fps` other than 30 or `size` other than 1080x1920 for the main reel | W | R36, R230 |
| 38 | Preference limits from `--prefs` broken: `max_whips`, `max_flashes`, `max_leaks` (leaks + `leakfade` transitions), `max_leak_strength`, `max_duration`/`min_duration`, `max_shot_seconds`/`min_shot_seconds` (end card excluded), `max_caption_chars`, `max_gold_words`, `max_hook_words`, `min_people_shots` (shots with `people: true`), `caption_px` (effective caption size differs) | W (E with `--strict`) | R278 |
| 39 | Never open on the logo: shot 0 `src` is the brand wordmark or the phoenix mark (`assets.wordmark`, `assets.secondary_mark`, compared by resolved path) | E | R44, R70 |
| 40 | Movement from frame 1: shot 0 is a still (`kind` image) with `z[0] == z[1]`, no pan (`pan` absent or [0, 0]) and `tr` `cut`, and the plan has no `hook` (no moving hook text) | E | R70 |
| 41 | Consent: the shot's source has detected faces in analysis.json (`faces`, or `orig_faces`, of the photo/clip whose `path` or `prepared_path` equals `src`) and the shot is not marked `people: true`, unless `consent: true` or `blur` boxes cover every face box (containment with a 0.02 margin). `people: true` without consent stays rule 28 | E | R141 |
| 42 | Text cards: `t1` not after `t0`, past `duration`, over the end card (`t1 > endcard.t`), or overlapping another card is E; on screen less than 0.6 s + 0.25 s per word, a statement over 12 words, or a number card with more than one word is W | E/W | R195 |

The validator prints `OK: <n> shots, <duration> s, <w> warnings` on success.

---

## 6. brand/brand.json

Schema: `schemas/brand.schema.json` (schema_version 2). One source of truth
for the brand; every skill, agent and script reads it (`numa_common.load_brand()`
validates it and checks that every claims pattern compiles). `/brand-setup`
(T10) rewrites values and sets `status: confirmed`.

**Facts.** Uncertain values are `{"value": ..., "status": ..., "source": ..., "note": ...}`.
Statuses: `confirmed` (Katie or the brief confirmed), `from_website`
(numawellness.org / NUMA's channels), `research` (Mobile audit, public
research), `needs_katie` (unknown or a stand-in default; value may be null;
never state it as fact), `bundled` (a file shipped in the plugin), `generated`
(written per reel; value is an example). A null value is always
`needs_katie`. `numa_common.fact()` unwraps a fact; `brand_value('a.b.c')`
walks and unwraps.

**Sections and the keys scripts use.**

| Section | Contents | Used by |
|---------|----------|---------|
| `business` | `name` {full, short, with_city}, `name_usage`, `website`, `founders`, `founding_story`, `location` {address, street, city, state, zip, area, district}, `facility`, `temperatures`, `hours`, `phone` (null + `candidates`), `booking`, `cta_link`, `instagram_name_field`, `bio_draft` | scriptwriter, copywriter, critic |
| `socials` | `instagram`, `facebook`, `ios_app`, `google_business_profile` | copywriter, scout |
| `voice` | `description`, `reference_lines`, `site_lines`, `share_line_example`, `community_word`, `emoji`, `words_always`, `words_never`, `dislikes`, `music_taste` | scriptwriter, copywriter |
| `offerings` | `modalities`, `formats`, `sessions` (each with its own `price` fact), `offers` (Discover NUMA $49), `memberships`, `events`, `do_not_promote`, `not_offered` | scriptwriter, critic, motion |
| `team` | `collective` (name, role, org, credentials), `on_camera`, `filming` | scriptwriter, plan-month |
| `positioning` | `own_in_mobile`, `target_audiences`, `series` (id, name, what, length_s, built_for), `collab_partners` (ordered), `competitors`, `content_mix` (sums to 1.0) | plan-month, scout, dashboard |
| `assets` | `wordmark`, `wordmark_light`, `secondary_mark`, `endcard_background`, `brand_photos_dir` (paths relative to plugin root) | engine, baseline_plan, setup_check (`brand_asset()`) |
| `palette` | `value` {cedar_ember, water_teal, cream, caption_gold, caption_text}; `roles` {caption_text, caption_accent, endcard_subtitle, endcard_logo} | engine (`brand_color()`, `accent_rgb()`) |
| `fonts` | `value` {family, caption_regular, caption_italic, license} | engine, validate_plan, formats (`brand_font()`) |
| `endcard` | `tagline`, `default_subtitle`, `signoff_examples` | engine, baseline_plan |
| `captions` | `opening_rule`, `hashtags` {count [3,5], base, community_tag, never}, `disclosure` | copywriter, claims_scan |
| `transcript_fixes` | `protect` (phrases never changed), `fixes[]` {to, variants, case_sensitive, next_words} | fix_transcript, analyze |
| `claims` | `banned[]` {id, label, severity `fail`/`warn` (default `fail`), patterns (Python regex, case-insensitive), applies_to "all"}, `allow_exact` and `allow_patterns` (removed before scanning), `modalities` {say, never_say}, `rules[]`, `safety_line` {text, applies_to}, `dosing_line` {text, blocked, patterns} | claims_scan, validate_plan, scriptwriter, critic |
| `consent` | `list` {location, columns}, `default`, `ai_processing_covered`, `social_posts_covered`, `children`, `voice_clone`, `release_form` | motion, critic, librarian |
| `closures` | `location`, `rule`, `known` | plan-month |
| `drive` | Drive names: `root`, `plan_dir`, `plan_sheet`, `music_library`, `music_naming`, `digests`, `consent_list`, `closures`, `metrics_sheet`, `month_folder`, `day_folder`, `shoot_card`, `photos`, `clips`, `voiceover`, `music`, `finished` | librarian, plan-month |
| `posting` | `auto_post`, `require_approval`, `see_first`, `legal_review_done` (gates auto-post), `platforms`, `posting_time`, `ai_label_rule`, `music_rule`, `digest_destination` | post-reel, make-reel |
| `escalation` | `contact` (Jude Moore), `never_ask`, `for[]`, `rule` | make-reel, all tasks |

**Claims scanning contract.** Scan every text surface (voiceover script,
on-screen text, caption, hashtags, pinned comment). First remove each
`allow_exact` phrase and every match of `allow_patterns` (e.g. "treat
yourself", "a real treat"), then test every `banned[].patterns` and, while
`dosing_line.blocked` is true, `dosing_line.patterns`, all with
`re.IGNORECASE`.

| Severity | Meaning | Script result |
|----------|---------|---------------|
| `fail` (default) | A banned claim from the spec list (or the blocked dosing line) | `ERROR:` line, exit 1; Critic hard gate |
| `warn` | Ambiguous wording that is usually innocent ("Healing Arts", "the cure for Monday", "summer treats", "prevent slipping") or outcome language ("improves sleep", "recover faster", "lowers stress levels") | `WARN:` line, exit 0; the Director rewords or confirms |

Fail patterns use context or lookarounds so innocent uses don't hard-fail
(e.g. `trauma` but not `trauma-informed`, `hormone` but not `hormone-free`,
"treats" only before a condition word). Hashtags are also checked against
`captions.hashtags.never`.

**Key migration (v1 brand.json -> v2).** Readers of the old keys must use the
new ones; there is no compatibility shim.

| v1 key | v2 location |
|--------|-------------|
| `name` {value, short} | `business.name.value` {full, short, with_city} |
| `founders`, `location`, `facility`, `phone`, `hours_note` | `business.founders`, `business.location` (now an object), `business.facility` (now an object), `business.phone` (+ `candidates`), `business.hours` |
| `sessions` (strings) | `offerings.sessions` (objects with `minutes`, `guidance`, `price` fact) |
| `offers` | `offerings.offers` |
| `events` | `offerings.events` |
| `not_offered` | `offerings.not_offered` |
| `collective` | `team.collective` |
| `handles` {instagram} | `socials` {instagram, facebook, ios_app, google_business_profile} |
| `voice` {value, reference_lines} | `voice.description`, `voice.reference_lines` (3 site reference lines), `voice.site_lines` |
| `community_word`, `emoji` | `voice.community_word`, `voice.emoji` |
| `palette` {cedar, teal, cream, caption_gold} | `palette.value` {cedar_ember, water_teal, cream, caption_gold, caption_text} + `palette.roles` |
| `fonts` {caption_regular, caption_italic} (paths relative to the skill) | `fonts.value` {family, caption_regular, caption_italic, license} (paths relative to the plugin root) |
| `assets` {wordmark, ...} (plain paths) | `assets.<key>.value` (facts) |
| `endcard` {tagline, default_subtitle} | `endcard.tagline.value`, `endcard.default_subtitle.value`, `endcard.signoff_examples` |
| `series` (names) | `positioning.series.value` (objects) |
| `content_mix` | `positioning.content_mix.value` |
| `collab_partners` | `positioning.collab_partners` |
| `competitors_to_track` | `positioning.competitors` |
| `hashtags` {base, community_tag, never} | `captions.hashtags` {count, base, community_tag (fact), never} |
| `transcript_fixes` {wrong: right} map | `transcript_fixes.fixes[]` {to, variants, case_sensitive, next_words} + `transcript_fixes.protect` |
| `claims.banned_patterns` | `claims.banned[].patterns` (with id, label, severity) |
| `claims.hold_until_counsel` | `claims.dosing_line` {text, blocked, patterns} |
| `claims.safety_line` (string) | `claims.safety_line.text` |
| `budgets` | `config/studio.json` `budget` (and `higgsfield.credits_per_month`) |
| `instagram_api` | `config/studio.json` `instagram.graph_api_version` |
| `posting.auto_post`, `posting.cta_link`, `posting.default_slots_central` | `posting.auto_post`, `business.cta_link`, `posting.posting_time` |
| `admin_contact` {name, for} | `escalation.contact`, `escalation.for` |
| `consent` {list, ai_processing_covered} | `consent.list.location`, `consent.ai_processing_covered` |
| `closures.source` | `closures.location` |

Operational numbers that used to sit in v1 brand.json (Higgsfield budget,
Instagram API version) now live in `config/studio.json`.

---

## 7. config/studio.json

One place for operational numbers (D11). Each section has a `_source` naming
the spec page. Read with `numa_common.load_config()` / `config_value('a.b')`.
Requirements that name separate files (`config/models.json`,
`config/higgsfield.json`, `config/schedule.json`; R204, R216, R261) are
satisfied by the corresponding sections here.

| Section | Keys |
|---------|------|
| `models` | `tiers` {top: opus, mid: sonnet, small: haiku}; `agents` {director, critic: opus; motion, editor, analyst, scriptwriter, scout: sonnet; librarian, copywriter: haiku}; `effort` |
| `higgsfield` | `plan`, `credits_per_month` 1200, `price_usd_per_month`, `prices_verified_on`, `prices[]` {id, job, model, tool, options, seconds, credits, avoid?}, `defaults` {motion (Kling 3.0 pro), motion_draft (Kling 3.0 standard), signature_people_free (Seedance 2.5 720p), photo_extend, photo_sharpen, music, voice}, `clips_per_reel` {typical [2,3], max 4}, `max_credits_per_reel` 150 |
| `budget` | `monthly_credits` 1200, `reels_per_month` 20, `split` {kling_motion 600, seedance_people_free 140, photo_prep 160, music 120, voice 10, reserve 170}, `pacing` {by_day 15, max_fraction_spent 0.55}, `max_credits_per_reel` 150, `rollover` false |
| `critic` | `rubric[]` {id, label, weight, five_looks_like} (weights sum to 100), `score_formula`, `pass` {min_total 80, min_category_score 3, min_hook_score 4}, `hard_gates[]`, `frames` {count 12}, `max_rounds` 3 |
| `render` | `fps` 30, `size` [1080,1920], `captions` {font_px 92, rise_px 22, fade_in_s 0.28, max_rows 2, default_y 1420}, `safe_area` {top_fraction 0.12, bottom_fraction 0.10}, `hook` {min_visible_s 1.5, max_black_fade_in_s 0.2}, `endcard` {min_hold_s 3.5, max_hold_s 5}, `outro_music_only_s`, `beat_tolerance_frames` 1, `max_shot_beats` 4, `words_per_second` 2.3, `length_s`, `video` {libx264, high, yuv420p, crf 19, maxrate 14M, bufsize 28M, faststart, max_file_mb 100}, `audio` {aac, 192k, 48000, 2}, `loudness` {integrated_lufs -15, tolerance_lu 1, true_peak_db -1.5, lra 9, mean_level_warn_db -28}, `draft` {scale 0.5, preset, crf} |
| `schedule` | `timezone` America/Chicago, `tasks[]` {id, name, when, cron, command}: plan_month `0 21 24 * *`, night_check `0 20 * * *`, build_today `0 5 * * *`, dashboard_refresh `0 22 * * *`, trend_check `0 19 * * 5`, digest `0 18 * * 0` |
| `instagram` | `scopes`, `graph_api_version` v26.0, `tools` {media_insights, user_insights, create_media, publish_media}, `media_type` REELS, `publish_wait_minutes` [3,5], `publishing_limit_per_24h` 100, `container_max_age_hours` 24, `insight_pulls_hours` [48, 72, 168], `metrics[]`, `never_request` [plays, impressions], `tags[]`, `computed`, `judge_at_hours` 72 |
| `formats` | `outputs[]` {id, label, size, length_s or count, kind, file, rule}, `hook_variants`, `crop_rule` |

---

## 8. Other files

**`<job>/out/report.json`** (one JSON object; each stage owns one top-level
key and replaces only it, via `numa_common.update_report(out_dir, key, data)`):

```json
{
  "schema_version": 1,
  "finish":       {"output": "<abs>", "duration": 39.0, "size_mb": 21.4,
                   "loudness": {"integrated_lufs": -15.0, "true_peak_db": -1.6, "lra": 6.1, "mean_db": -19.8},
                   "nat_bursts": 2, "warnings": []},
  "check_output": {"<file name>": {"ok": true, "errors": [], "warnings": [], "probe": {"...": "media_info fields"}}},
  "qa_frames":    {"dir": "<abs>/critic_frames", "count": 12},
  "formats":      {"files": ["<abs>", "..."], "warnings": [], "skipped": [{"kind": "reach", "reason": "..."}], "ok": true}
}
```

**`<job>/work/render.json`** (engine.py): `{"plan": "<abs>", "output": "<abs>",
"size": [w, h], "fps": 30, "frames": N, "seconds": 123.4, "workers": 8,
"quality": "final", "encoder": "libx264", "from": 0.0, "to": 39.0}`.

**`<job>/out/critic_frames/index.json`**: `[{"file": "frame_01.jpg", "t": 0.0,
"why": "first second"}, {"file": "frame_02.jpg", "t": 2.62, "why": "cut 1"}, ...,
{"why": "last second"}]`; 12 frames: first second, every cut (evenly
subsampled when there are more), last second.

**`<job>/work/sources.json`** (sources.py): `[{"kind": "music|photo|clip|voice|stock|font",
"path": "<abs>", "source": "Higgsfield ElevenLabs Music v2.5 | Pexels | NUMA Drive ...",
"license": "...", "url": "... or null", "added": "YYYY-MM-DD"}]`; `out/sources.txt` is
the same list as plain text, one item per line.

**Scheduled tasks** (spec p.50): see `config/studio.json` `schedule`; task
prompts live in `commands/` (T9).

---

## 9. Script command lines

All scripts live in `skills/numa-reel-editor/scripts/` (owner task in
brackets) and follow section 1. `JOB` = the job folder, `WORK` = `JOB/work`.
`--json` always means: print one JSON report on stdout and nothing else.

### analyze.py [T2]
```
analyze.py RAW_DIR WORK_DIR [--voice FILE] [--music FILE] [--master FILE]
           [--script FILE] [--no-transcribe] [--pad-seconds S] [--json]
```
- Classifies `RAW_DIR` recursively by extension, case-insensitive: images
  jpg/jpeg/png/heic/webp; clips mp4/mov/m4v; audio mp3/wav/m4a/aac. HEIC is
  converted to `WORK/media/<name>.jpg` (raw stays untouched).
- Audio roles from file names (vo/voice/narrat/memo/speech -> voice;
  music/song/track/beat -> music; one file holding both -> master), overridable.
  Voice + music: sidechain-ducked mix, length min(voice + 7.5 s, 60 s). One
  track: loudness-normalized. No audio at all: WARN and a deterministic offline
  pad of `--pad-seconds` (default 30) as `WORK/pad.wav` (`audio.generated_pad`).
- Transcribes with faster-whisper `small.en` int8 (word timestamps) unless
  music-only or `--no-transcribe`; a transcription failure is a WARN, never fatal.
  Applies the same correction pass as fix_transcript.py (brand fixes, and the
  script when `--script` is given).
- Writes `WORK/master.wav`, `WORK/analysis.json`, `WORK/contact_photos.jpg`,
  `WORK/contact_clips.jpg`. stdout: duration, bpm, transcript, counts.
- Exit 1: `RAW_DIR` missing/empty of media, unreadable media.

### fix_transcript.py [T2]
```
fix_transcript.py ANALYSIS_JSON [--script FILE] [--dry-run] [--json]
```
Applies brand.json `transcript_fixes` and, with `--script` (plain text of the
shoot card's voiceover script), aligns words to the script (the script wins
for spelling). Rewrites `words[].w`, `transcript`, appends `corrections[]`;
timing unchanged. `--dry-run` prints the corrections without writing.

### baseline_plan.py [T4]
```
baseline_plan.py WORK_DIR [--duration S] [--hook TEXT] [--subtitle TEXT]
                 [--seed N] [--prefs FILE] [--out FILE] [--script FILE]
                 [--before SHOT_ID --after SHOT_ID] [--turn S]
                 [--template NAME] [--library FILE]
```
Reads `WORK/analysis.json`; writes a valid, beat-synced schema_version 2 plan
to `WORK/plan.json` (or `--out`) with `out_dir = WORK`, brand.json defaults
(fonts, accent, wordmark, tagline, subtitle), `focus`/`faces` from vision data,
`prepared_path` sources when present, and `music` filled from the analysis.
Duration = min(`--duration`, audio, 60). A music-only reel with `--script`
and no `--duration` (and no template) runs the script's caption timing
(~2.3 words/s, lines on beats) plus the music-only outro (config
`render.outro_music_only_s.default`, the end card inside it), capped by the
audio and 60 s, at least 15 s.
- `--template NAME`: a template or preset id from
  `skills/numa-scriptwriter/templates.json` (unknown name: `ERROR` listing the
  valid ids, exit 1). Applies its default length (when `--duration` is not
  given; a length outside `typical_length_s` is a WARN), arc (one spoken line
  per beat), pacing (`beats_per_shot`, `hook_s`, `outro_s`), turn (`--turn` =
  `turn.at` x voiced seconds unless given), look (`before_turn` up to the
  turn), signature moment (`wipe` with `--before/--after`, else a flash at
  `signature_moment.at` of the voiced part, snapped to a text card nearby),
  transitions (only the template's, whips only when listed), hook style
  (`meta.hook_type`, plus `goal`, `pillar`, `length_class`), `template`, and
  `cards` from `text_cards` when `kinetic_type` is true (a label card is a
  `number` card, a line card the beat's line shortened to `max_words`: the
  first clause within `max_words`, else that first clause up to 2 words over
  with a WARN, else a later whole clause that fits; each starts on a cut). A card that would cover the hook
  window (before `hook.t1`) starts on the first cut after it unless it shows
  the hook text itself, so the hook is on screen from frame 0. Music-only reels with `--script` spread the script lines
  across the beats.
- `--prefs FILE` (prefs.py limits): every numeric limit is applied where the
  material allows (whips, flashes incl. the end card's, leaks and leakfades,
  leak strength, caption size `caption_px`, characters and gold words per
  line, hook words, reel and shot length, shots with consented people), so the
  plan passes rule 38.
- Consent (rule 41): a source with faces is used as `people: true, consent:
  true` when the analysis item has `consent: true`/`"yes"` or the `--library`
  index (library.py) records consent yes for its path; without known consent
  it is left out when 3+ other photos/clips remain, else used with `blur`
  boxes over the faces (WARN either way).
- `formats.reach_cut.hook` is never the reel's hook: `meta.title`, else the
  strongest other caption line; no reach cut without one.
- `formats.story`/`carousel` use whole sentences only (caption lines joined,
  formats.py's defaults); none when there are too few.
- A template's default length that would cut the voice mid-sentence moves to
  the next sentence end inside `typical_length_s` (else the last whole one), WARN.
- The plan is written either way; exit 1 when its own validation has an ERROR.

### validate_plan.py [T4]
```
validate_plan.py PLAN_JSON [ANALYSIS_JSON] [--prefs FILE] [--strict] [--json]
```
Runs the schema and every rule in section 5. Without `ANALYSIS_JSON`, uses
`analysis.json` next to the plan when it exists. `--strict` makes warnings
fail. Exit 0 valid, 1 any ERROR (or WARN with `--strict`).

### claims_scan.py [T4]
```
claims_scan.py [TEXT ...] [--file FILE ...] [--plan PLAN_JSON] [--hashtags TEXT] [--json]
```
Scans texts (`-` reads stdin), files, and every text field of a plan against
brand.json claims (section 6) and `captions.hashtags.never`. Prints
`ERROR: banned claim "<label>" in <where>: "<matched text>"` per `fail` hit;
exit 1 on any `fail` hit, 0 otherwise (`warn`-severity hits are `WARN:` lines).

### engine.py [T1]
```
engine.py PLAN_JSON [--draft] [--workers N] [--size WxH] [--from S] [--to S]
          [--out FILE] [--encoder libx264|videotoolbox]
engine.py PLAN_JSON preview T1 [T2 ...] [--size WxH] [--out FILE]
```
- Full render: raw frames piped into ffmpeg (H.264 High, yuv420p, crf 19,
  maxrate 14M, config `render.video`) -> `OUT_DIR/video_noaudio.mp4`
  (`--draft`: config `render.draft`, -> `video_noaudio_draft.mp4`).
  `--size` overrides the plan size (pixel fields scale). `--from/--to` render
  only that time range (-> `segment_<from>_<to>.mp4` unless `--out`).
  `--workers N` (default: CPU count) renders frames in parallel with output
  byte-identical to `--workers 1`. `--encoder videotoolbox` (macOS hardware)
  falls back to libx264 when unavailable and is never used for golden or
  determinism tests. Encoding runs in fixed 2 s segments (one GOP each, encoded
  single-threaded, then concatenated and faststarted) so output is identical
  for any worker count. Writes `OUT_DIR/render.json` with keys `sha256`,
  `timings`, `frames`, `size`, `workers`, `encoder`, `preset`, `crf`, `segment_s`
  (`--from/--to` renders write `segment_<from>_<to>.json` instead). Each segment
  gets a rate budget of 0.85 x `render.video.maxrate` with a small VBV buffer so
  every 2 s window stays under the cap. A last segment shorter than 0.5 s joins
  the one before it, so any frame count gives a constant frame rate.
- Render cache: decoded frames go to a hidden temp folder under `OUT_DIR`
  (removed after the render), or under `$NUMA_RENDER_CACHE`; when `OUT_DIR` is
  inside a cloud-synced folder (path contains "Google Drive", "GoogleDrive",
  "CloudStorage", "Dropbox" or "OneDrive") it defaults to the system temp
  folder so the sync client never uploads the cache.
- Text legibility: for each caption line and the hook, per shot it is shown
  over, the engine measures the median luminance under the text's ink box
  (three moments, middle value). Only when white text would read below 4.5:1
  does a soft-edged scrim limited to that box plus a small margin darken the
  picture to about 5:1 and deepen the text shadow; its strength is constant
  while the line stays on one shot. Text that already reads at 4.5:1 is
  rendered exactly as before. Deterministic.
- Preview: renders the listed times into one grid `OUT_DIR/preview.jpg`
  (5 tiles per row).
- Reads only the plan, bundled assets/fonts and brand.json defaults (R9).

### finish.py [T3]
```
finish.py WORK_DIR OUTPUT_MP4 [--video FILE] [--plan PLAN_JSON] [--clean-voice] [--no-qa] [--json]
```
Masters `WORK/master.wav` (voice chain: HP 85 Hz, -2.5 dB at 180 Hz, -4 dB at
3.8 kHz, -2.5 dB at 7 kHz, LP 11 kHz, optional short room echo unless
`--clean-voice`, 2:1 compression, loudness measured (loudnorm pass 1) then one
linear gain to -15 LUFS plus an oversampled true-peak limiter (TP <= -1.5 dB),
re-measured after AAC encoding,
48 kHz, fades), mixes the plan's `nat` bursts (plan defaults to
`WORK/plan.json`), muxes with `WORK/video_noaudio.mp4` (or `--video`) as H.264
copy + AAC 192k 48 kHz stereo `+faststart` into `OUTPUT_MP4`, measures the
result (integrated LUFS, true peak, LRA, mean dB; WARN when mean < -28 dB),
writes `qa_strip.jpg` (6 frames, 1620x480) next to `OUTPUT_MP4` and the
`finish` section of `report.json` there.

### check_output.py [T3]
```
check_output.py FILE.mp4 [--kind reel|reach|story|hook] [--size WxH] [--plan PLAN_JSON] [--report OUT_DIR] [--json]
```
Checks the output spec (spec p.48, config `render`): MP4, H.264 High,
1080x1920, 30 fps, yuv420p, video bitrate <= ~14 Mbps, AAC 192 kbps 48 kHz
stereo, moov before mdat, < 100 MB, length for the kind (reel 15-60 s, reach
8-12 s, story/hook <= 15 s), loudness -15 +/- 1 LUFS and true peak <= -1.5 dB, not silent, not clipped, no black bars
(near-black uniform borders > 2%), no frozen frames >= 1 s (end-card window from
`--plan` exempt).
One `ERROR:` per violation, exit 1; `--report` writes the `check_output`
section of `OUT_DIR/report.json`.

### qa_frames.py [T3]
```
qa_frames.py VIDEO_MP4 PLAN_JSON [--out DIR] [--count 12]
```
Extracts the Critic's frames (first second, every cut, last second; `--count`
total) to `DIR` (default `<video folder>/critic_frames/`) as
`frame_01.jpg ...` plus `index.json`.

### vision.py [T5]
```
vision.py ANALYSIS_JSON [--no-clips] [--json]
```
Detects faces and the main subject (OpenCV, deterministic) for every photo and
clip, scores each clip second for sharpness, motion and faces, and writes
`faces`, `focus`, `scores` and best `windows` into analysis.json in place.

### prep_media.py [T5]
```
prep_media.py ANALYSIS_JSON [--ids C0,P3,...] [--stabilize auto|on|off] [--brighten auto|on|off] [--json]
```
Stabilizes shaky clips (ffmpeg vidstab when available, else OpenCV smoothing)
and brightens dark clips/photos, selected automatically from analysis metrics
(`auto`) or forced. Writes `WORK/prep/<id>.mp4|.jpg` and sets
`prepared_path`; the Editor/baseline use it as the shot `src` (D13). Skips
items already prepared from an unchanged source.

### formats.py [T6]
```
formats.py PLAN_JSON REEL_MP4 [--out DIR] [--slug SLUG] [--only reach,story,carousel,cover,srt,hooks] [--draft] [--json]
```
Renders the plan's `formats` from the same plan (crops in the engine, never
Higgsfield Reframe): `<slug>_reach.mp4`, `<slug>_story_<N>.jpg|.mp4`,
`<slug>_carousel_<N>.jpg` (1080x1350), `<slug>_cover.jpg`,
`<slug>_hook_<N>.mp4`, and `<slug>.srt` (from plan `lines`; one cue per line).
`DIR` defaults to the reel's folder; slug defaults to `plan.meta.slug` or the
job folder name. Missing `formats` entries get sensible defaults derived from
the plan (whole sentences or a whole first clause, never an ellipsis; no two
carousel slides side by side with the same or a near-duplicate picture; a
reach-cut caption repeating the new hook in the first 4 s is dropped; a reach
window lengthened to avoid a tiny last encoder segment is a WARN). Writes the
`formats` section of `report.json`, with `skipped: [{kind, reason}]`.
Skipped vs failed: without `--only`, an output this plan cannot make (no
whole sentences for story/carousel, no new hook text for the reach cut or hook
variants, no captions or transcript for the .srt, a reel shorter than a reach
cut) is skipped with a WARN and `ok` stays true; a kind named in `--only` that
is skipped is an ERROR (exit 1) and `ok` is false. `ok` = every requested
output was made and passed its check.

### ledger.py [T7]
```
ledger.py add    --ledger FILE --category CAT --credits N --job TEXT [--reel SLUG] [--model TEXT] [--date YYYY-MM-DD] [--refunded]
ledger.py check  --ledger FILE [--category CAT --credits N] [--reel SLUG] [--date YYYY-MM-DD] [--json]
ledger.py report --ledger FILE [--month YYYY-MM] [--json]
ledger.py sheet  --ledger FILE [--month YYYY-MM]
```
`CAT` is a `config.budget.split` key. `check` exits 1 when spending (plus the
proposed `--credits`) would exceed the category split, the monthly total, the
per-reel cap (150) or the pacing rule (by day 15 <= 55%). `sheet` prints CSV
rows for the plan Sheet mirror.

### metrics.py [T7]
```
metrics.py ingest   --store FILE --reel ID --pull 48h|72h|7d --data INSIGHTS_JSON [--tags TAGS_JSON]
metrics.py compute  --store FILE [--json]
metrics.py validate --store FILE
```
Stores per-reel pulls (`config.instagram.metrics`) and NUMA tags; rejects
`plays`/`impressions` (exit 1); `compute` adds retention, sends and saves per
1,000 reach, and skip rate against NUMA's median.

### dashboard.py [T7]
```
dashboard.py METRICS_JSON OUT_HTML [--notes NOTES_JSON] [--competitors FILE] [--today YYYY-MM-DD]
```
Builds the self-contained HTML dashboard (leaderboard, results by series,
length and hook type, posting-time heatmap, 90-day trend, competitor tracker,
"Do more of / Do less of").

### library.py [T7]
```
library.py add   --index FILE PATH ... [--tags a,b] [--link URL] [--consent yes|no|unknown]
library.py query --index FILE [--tags a,b] [--kind photo|clip] [--orientation vertical|horizontal|square] [--people yes|no] [--limit N] [--json]
library.py list  --index FILE [--json]
```
Media library index (dims, orientation, duration, sharpness, tags, consent,
Drive link) and tag queries.

### prefs.py [T7]
```
prefs.py add    --file FILE "NOTE" [--date YYYY-MM-DD]
prefs.py list   --file FILE [--json]
prefs.py limits --file FILE [--json]
```
Feedback memory. `limits` prints the numeric limits derived from notes (e.g.
`{"max_whips": 1}`) that `baseline_plan.py`/`validate_plan.py --prefs` honour.

### sources.py [T7]
```
sources.py add   JOB --kind music|photo|clip|voice|stock|font --path FILE --source TEXT --license TEXT [--url URL]
sources.py show  JOB [--json]
sources.py check JOB --plan PLAN_JSON
```
Maintains `JOB/work/sources.json` and regenerates `JOB/out/sources.txt`.
`check` exits 1 when the plan's music or any outside file has no license.

### critic_score.py [T7]
```
critic_score.py score SCORES_JSON [--gate-failed TEXT ...] [--json]
critic_score.py round --rounds FILE --version ID SCORES_JSON [--gate-failed TEXT ...] [--json]
critic_score.py best --rounds FILE [--json]
```
Weighted total (config `critic` weights, out of 100); PASS = total >= 80, no
category < 3, hook >= 4, and no hard gate failed. `round` records a Critic
round (max 3) and returns ship / revise / ship_best / hold; `best` returns the
best-scoring version. Exit 1 on FAIL for `score`.

### digest_data.py [T7]
```
digest_data.py --metrics F --plan-rows ROWS.json|.csv [--ledger PATH] [--notes F]
               [--today YYYY-MM-DD] [--out F] [--text F] [--json]
```
Deterministic numbers for the Monday digest (last week's reels, best reel,
credits used/left, this week's schedule, batched shoot list by room) as JSON,
plus a plain-text phone-readable draft.

### setup_check.py [T10]
```
setup_check.py [--skip-render] [--download-model] [--json]
```
Checks Python >= 3.10, every import, ffmpeg (system or fallback), fonts and
assets, brand.json/config validity, optionally pre-downloads the speech model,
and renders + finishes a 3-second test reel in a temp folder. One line per
check (pass/fail with a one-line fix); exit 1 when any check fails.

### shoot_card.py [T9]
```
shoot_card.py month YYYY-MM [--json]
shoot_card.py card  ROW_JSON [--out FILE]
shoot_card.py check MONTH_JSON [--closures FILE] [--json]
shoot_card.py script SCRIPT_JSON [--json]
shoot_card.py sheet MONTH_JSON [--csv] [--out FILE]
```
`script`: checks one script.json (schemas/script.schema.json) against the card
rules and timing. `sheet`: exports the month as the 13 "NUMA 30-Day Reel Plan"
columns (JSON or CSV), the shape digest_data.py reads. MONTH_JSON is the
`month` output with titles/scripts filled in (shape in the script docstring).
`month`: the deterministic month skeleton (one row per day: day number, date,
`Day NN - YYYY-MM-DD - <title>` folder name, default-week slot). `card`: the
shoot card text for one plan row. `check`: enforces the planning rules (no
topic repeat within 14 days, at most one sales reel a week, nothing inviting
on closure days, 4-5 feed posts a week, at least one collab and one Meet the
Collective a month, event teaser/recap windows); exit 1 on violations.

### photo_post.py [T15]
```
photo_post.py single PHOTO --out OUT [--text TEXT] [--look warm|none] [--slug S] [--consent] [--library FILE] [--blur-faces] [--people-free] [--json]
photo_post.py carousel PHOTOS... --out OUT [--texts FILE] [--look warm|none] [--slug S] [--consent] [--library FILE] [--blur-faces] [--people-free PHOTO ...] [--json]
```
Feed photo posts at 1080x1350 (4:5) rendered by engine.py from a one-shot
plan (the reels' look, bloom, vignette and grain), framed on vision.py's
faces/focus. `single`: OUT is the JPG (a folder gets `<slug>_photo.jpg`);
`--text` is one short line (at most 60 characters, `*gold*` markup, 3 rows
max) drawn as the engine's hook in the brand serif inside the safe areas,
with the engine's legibility scrim; it moves to the bottom when an unblurred
face is under it. `carousel`: 2-10 photos or folders (name order) into OUT as
`<slug>_carousel_NN.jpg` (01, 02, ...; earlier ones replaced); `--texts` is a
JSON list or one line per slide. Every text is claims-scanned (banned claim:
exit 1). People: detectors only ever say yes, so every photo needs a recorded
basis, reported as `people_basis`: `consent` (`--consent`, Consent List
checked), `library_consent` (`--library` entry with consent yes),
`library_tag_no` (library entry with people no and `people_source` "tag"),
`people_free_flag` (`--people-free` after LOOKING: single takes the flag,
carousel names each photo, repeatable) or `blurred` (`--blur-faces` and
detected faces, all blurred). None: exit 1. `--blur-faces` alone never passes
a photo with no detected face; faces on a photo marked people-free need
`--blur-faces` or consent; library consent no is never overridden.
Deterministic bytes. `--json` prints `{ok, kind, files, slides: [{file, src,
text, faces, consent, people_basis, blurred, focus, text_position, upscale}]}`.

### design_render.py [T14]
```
design_render.py validate CAROUSEL_JSON [--json]
design_render.py build    CAROUSEL_JSON --root ROOT [--uploads-only] [--created-at ISO]
                          [--design-system URL [--design-system-title T] [--design-system-version V]] [--json]
design_render.py canvas   DIR --out OUT [--slug SLUG] [--runtime FILE] [--format jpg|png] [--list-blobs] [--json]
design_render.py spec     CAROUSEL_JSON --out OUT [--format jpg|png] [--json]
```
Component carousels (R328-R332, DECISIONS D21). Needs Python Playwright plus
its Chromium (`pip install -r requirements.txt`, then
`python -m playwright install chromium`); no network at render time.
- `validate`: carousel.json against `schemas/carousel.schema.json`, every text
  field + caption + hashtags through `claims_scan` (fail = ERROR, warn = WARN),
  offer prices from brand.json (`needs_katie` price = ERROR), photos exist,
  2-10 slides (outside config `formats` carousel `count`: WARN).
- `build`: writes `ROOT/project/canvas.json` (boards `Main.dc.html`,
  `Slide02.dc.html`, ... 1080x1350, 80 px apart in one row, a sticky with the
  posting date and caption; `designSystems` record when `--design-system`) and
  one `.dc.html` per slide from `assets/carousel/<component>.dc.html`, fields
  filled as literal markup. `--uploads-only` copies the images to upload to
  `ROOT/uploads/` and lists them (keys: the slide's `photo` string, `wordmark`);
  without `canvas.blobs` for each, `build` exits 1. `--json` prints
  `{"ok", "root", "index", "boards", "files", "uploads", "warnings"}`; `files`
  is the Artifact publish `files` map (plus the design system's tokens.json copy).
- `canvas`: renders `DIR` as read back with the Artifact tool: `canvas.json` and
  `*.dc.html` in `DIR/project/` (or `DIR/`), the Design type's runtime
  `DIR/artifact-type/dc-runtime.js` (served as `project/support.js`; `--runtime`
  overrides), images `/_blob/<id>` from `DIR/<id>.<ext>` (where the Artifact
  read saves an asset) or `DIR/_blob/`. Slides in reading order (rows top to
  bottom, left to right); every board must be 1080x1350. Google Fonts links are
  served from the bundled Fraunces/Inter; another family = ERROR. The rendered
  text is claims-scanned (Katie may have edited it). `--list-blobs` prints
  `<id>\t<file|MISSING>` and exits 0. Default slug: `slugify(canvas title)`.
- `spec`: the fallback; same checks, rendering `assets/carousel/<component>.html`
  (identical slide markup to the `.dc.html`, so the same pixels).
- Checks per slide (ERROR, exit 1): 1080x1350 at (0,0), page not larger; every
  font used is loaded (no system fallback); not blank/near-uniform (< 0.3% of
  pixels differ from the background); no text box overflowing (scroll size
  beyond the box by more than 0.3 em, or text outside the slide); no
  `[PRICE]` placeholder (a `$` amount that is not a brand.json price: WARN);
  JPG quality 92 (>= 90 checked), 4:4:4, sRGB ICC embedded.
- Writes `OUT/<slug>_carousel_NN.jpg|png` (01, 02, ... as photo_post.py; old ones of the
  slug removed first), `OUT/carousel_sheet.jpg` (contact sheet) and
  `report.json` `design_render`: `{"mode": "canvas|spec", "source", "slug",
  "ok", "files", "sheet", "slides": [{"n", "file", "board"|"component",
  "title"?, "ok", "errors", "warnings", "fonts", "text"}], "errors",
  "warnings"}`. Exit 1 on any ERROR (the slides are still written to LOOK at).

**carousel.json** (`schemas/carousel.schema.json`; usually `JOB/work/carousel.json`):
```json
{"schema_version": 1, "slug": "2026-12-08-sauna-vs-red-light",
 "title": "NUMA Carousel · 2026-12-08 · Sauna vs red light", "date": "2026-12-08",
 "topic": "Ask the DPT: sauna vs red light", "caption": "Sauna vs red light in Mobile, AL: ...",
 "hashtags": ["#MobileAL"],
 "slides": [
   {"component": "cover", "fields": {"kicker": "Ask the DPT", "title": "Sauna vs red light: what's *different*?", "subtitle": "..."}},
   {"component": "photo", "photo": "skills/numa-reel-editor/assets/brand-photos/red-light.jpg", "photo_position": "50% 38%",
    "fields": {"kicker": "Red light", "caption": "Red light is *light*, not heat."}},
   {"component": "offer", "fields": {"kicker": "New here?", "title": "Your first month", "offer": "Discover NUMA", "cta": "discover.numawellness.org"}},
   {"component": "cta", "fields": {"title": "Feel the difference.", "button": "discover.numawellness.org"}}],
 "canvas": {"url": "https://claude.ai/artifact/<id>",
            "blobs": {"skills/numa-reel-editor/assets/brand-photos/red-light.jpg": "/_blob/<id>", "wordmark": "/_blob/<id>"}}}
```
Components and fields (required, *optional*): `cover` kicker, title, *subtitle*;
`point` kicker, number, title, body; `stat` kicker, stat (<= 8 chars), label,
*body*, *source*; `myth_fact` kicker, myth, fact; `quote` kicker, quote, name,
*role*; `steps` kicker, title, step1-3, *step4*; `offer` kicker, title, offer
(a brand.json offer/session name; price and its note come from brand.json),
cta, *details*; `photo` kicker, caption (+ slide `photo`, *`photo_position`*,
*`photo_alt`*); `cta` title, button, *body* (wordmark added). Text: `\n` line
break, `*word*` italic cedar-ember emphasis; text fits are measured at render.

### strategy.py [T18]
```
strategy.py plan    --month YYYY-MM [--metrics FILE] [--state FILE] [--playbook DIR] [--events FILE] [--closures FILE]
                    [--seed N] [--today YYYY-MM-DD] [--out FILE] [--json]
strategy.py learn   --metrics FILE --state FILE [--playbook DIR] [--today YYYY-MM-DD] [--text FILE] [--json]
strategy.py brief   --plan PLAN_JSON --metrics FILE [--state FILE] [--playbook DIR] [--week YYYY-MM-DD]
                    [--today YYYY-MM-DD] [--out FILE] [--md FILE] [--notes TXT] [--json]
strategy.py explain SLOT --plan PLAN_JSON [--json]
strategy.py diagnose --metrics FILE [--post ID] [--state FILE] [--playbook DIR] [--today YYYY-MM-DD] [--json]
strategy.py score   --metrics FILE [--state FILE] [--playbook DIR] [--today YYYY-MM-DD] [--json]
strategy.py import-research FILE... --state FILE [--playbook DIR] [--kind KIND] [--today YYYY-MM-DD] [--json]
strategy.py validate [--playbook DIR] [--state FILE] [--json]
strategy.py export  [--playbook DIR] [--state FILE] --out FILE
```
The adaptive strategy engine (DECISIONS D23, R344-R350). Reads the playbook
(`skills/numa-scriptwriter/playbook/{patterns,diagnosis,calendar,policies}.json`,
`schemas/playbook.schema.json`; never written at run time), the learned state
`STATE/strategy.json` (same schema, `kind: state`: status overrides, imported
research, judging windows, changelog, insights) and metrics.py's store (read
tolerantly: `pattern_ids`/`strategy_arm` tags allowed). Deterministic: the seed
defaults to YYYYMM; `--today` fixes ages. Judging windows per post type
(policies `judging`): ignored before `ignore_before_hours`, PROVISIONAL from the
first pull at/after `provisional_hours` (weight `provisional_weight`), FINAL
from the pull at/after `final_hours` (7d when later), never counted twice;
metric `exceptions` drop that metric from a provisional score. `plan` writes a
MONTH_JSON (shoot_card.py shape; an `image` row is a single-photo feed post)
whose rows add `post_type`, `post_time` (Central HH:MM), `hour_band`,
`pattern_ids`, `strategy_arm`, `strategy` {mode exploit|explore|rule, goal,
why[]} and `moments`, plus a top-level `strategy` summary (data-led share,
explore slots, violations). It exits 1 when a planning rule fails even with the
bandit off. `learn` updates statuses (promote/retire/demote/start_testing), the
dated changelog and Do more/Do less lines; `--text` writes the plain-text
changelog for the digest. `brief` writes `schemas/strategy_brief.schema.json`.
`import-research` parses the R1-R7 deep-research outputs (markdown or Google
Doc text): pattern blocks, "symptom -> cause -> fix" tables, post-type share
tables, rule tables and the R7 judging-window tables; claims-scans every
example (a failing example is rejected; a pattern with none left is rejected),
de-duplicates by id and name, never changes a status or NUMA's own data.

**Pattern tagging contract (plan row -> script.json -> metrics tags).**

| Field | Type | Written by | Read by |
|---|---|---|---|
| `pattern_ids` | list of playbook pattern ids (kebab-case), in the order hook, structure, CTA or offer | strategy.py plan (row); Scriptwriter (script.json, the ids actually used) | build-today -> metrics.py tag; strategy.py learn/score |
| `strategy_arm` | string `type=<post_type>;pillar=<p>;series=<s>;day=<Mon..Sun>;band=<hour band>;hook=<id>;structure=<id>;offer_week=<w1..w5>;goal=<reach\|saves\|conversion>;mode=<exploit\|explore\|rule>;plan=<YYYY-MM>` (keys always in this order; empty value = none) | strategy.py plan; copied unchanged | metrics.py tag (text); strategy.py (`parse_arm`) |

The weekday and hour credited to a post come from its `posting_time` tag (what
really happened), not from the arm. Posts without these tags are still learned
from: `hook_type` maps to a hook pattern through the playbook's `hook_types`.

**Strategy brief** (`STATE/strategy_brief.json`, `schemas/strategy_brief.schema.json`):
`{schema_version 1, kind "strategy_brief", date, week_of (Monday), month,
data {judged_posts, final_posts, provisional_posts, pending_posts, data_led_share},
provisional [{id, title, post_type, pull, weight, final_after_hours}], pending [ids],
mix {feed_posts, post_types, trial_reels, suggested_pillar_mix}, slots [{date,
weekday, post_type, kind, post_time, hour_band, pillar, series, goal, mode,
pattern_ids, strategy_arm, event, event_role, sales, why}], use_patterns,
avoid_patterns, experiments, diagnoses, do_more, do_less, changes, reasoning,
strategist_notes?, rules_note}`. Written by `strategy.py brief`; the Strategist
adds only `strategist_notes` (`--notes`). Read by /plan-month, /build-today, the
Scriptwriter and the Monday digest.
