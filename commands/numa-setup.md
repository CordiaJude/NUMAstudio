---
description: One-time setup on Katie's Mac, run by Jude - install and self-check the Python stack with a 3-second test render, pre-download the speech model, confirm every connector, pick the Drive folder, build the Drive structure, approve connector tools, then golden test before the schedule goes on
argument-hint: "[recheck] (empty = full setup; recheck = steps 1-3 only)"
model: opus
---
# /numa-setup: get this computer and these connectors ready

Jude runs this once (spec p.13 step 4, p.49-50 step 8), and again after a connector is reconnected or the plugin is updated (`recheck`). This command and /brand-setup are the **only** places where questions are allowed, and only to the person running setup (Jude). Nothing here is ever asked of Katie, and no scheduled run ever asks anything.

Work through the steps in order. Report each item as ✅ / ❌ with its one-line fix as you go; finish every step you can even when one fails, then list the ❌ items at the end.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `STUDIO` | `~/NUMA Studio` (local mirror of Drive brand.json `drive.root`) |
| `STATE` | `STUDIO/_Plan` |

## 1. Python packages (R265)

```
python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"
```
pip refuses with "externally-managed-environment": re-run with `--break-system-packages`; still refused: add `--user`. OpenCV must stay below 5 (`opencv-python-headless>=4.8,<5`, DECISIONS D16); requirements.txt pins it.

## 2. Self-check, speech model and the 3-second test render (R266, R267, R270)

```
python3 "$S/setup_check.py" --download-model
```
One line per check: Python >= 3.10, every import (numpy, cv2 with FaceDetectorYN and CascadeClassifier, PIL, pillow_heif, librosa, faster_whisper, jsonschema, imageio_ffmpeg), ffmpeg with libx264 and AAC (system or the imageio-ffmpeg fallback), ffprobe or its fallback, fonts, assets, brand.json and config validity, the bundled YuNet face model, free disk space, the faster-whisper small.en model (downloaded now, a few hundred MB, so the first reel is not slow), and a 3-second test reel rendered through engine.py and finish.py and checked with check_output.

- Every line must be ✅ (⚠️ is fine). For each ❌, apply the fix printed on its line and run the command again. Exit code 0 = ready.
- **LOOK at the test reel.** The last line names `qa_strip.jpg`; open it (Read the image). Expect six full-height 9:16 frames with no black bars, the white "Setup *check*" hook near the top in the first frames (gold italic on the last word), the "Your reset starts *here.*" caption in the lower third, warm colour on both brand photos, and the end card fading in on the last frame. Anything else (bars, missing text, a black frame before the end, garbled letters) is a ❌: re-run with `NUMA_DEBUG=1` and fix before going on.
- `recheck` after a plugin update can use `--skip-render` for a quick pass; a first install always renders.

## 3. Connectors (R268)

Confirm each with one real, harmless call. Tool names differ by connector version (DECISIONS D17); use the tool that does what the row says.

| Connector | Call | ✅ when | ❌ fix (one line) |
|---|---|---|---|
| Google Drive | Search for the folder named brand.json `drive.root` ("NUMA Reels") and list its children | The folder list comes back | Claude Settings > Connectors > Google Drive > Connect, signed in as the Drive owner |
| Google Sheets | Read the header row of the Consent List Sheet (step 5 creates it on a first install) | The header row comes back | Connect Google Sheets in Claude Settings > Connectors (same Google account as Drive) |
| Higgsfield | The balance tool, then a dry run of one Kling 3.0 pro 5 s image-to-video job with `get_cost: true` (price id `kling_pro_5s`; nothing is submitted) | A balance and a credit quote come back; a quote different from config `higgsfield.prices` is noted for Jude | Connect Higgsfield in Claude Settings > Connectors; buy the Plus plan (config `higgsfield.plan`) at higgsfield.ai |
| Composio Instagram | The Instagram toolkit's account/user info tool for NUMA's account (find it with COMPOSIO_SEARCH_TOOLS), with `graph_api_version` = config `instagram.graph_api_version` | Username matches brand.json `socials.instagram`, account type Business or Creator, scopes cover config `instagram.scopes` | Composio dashboard > Instagram toolkit > reconnect with NUMA's Instagram (Business or Creator, Instagram Login, no Facebook Page needed) |
| Gmail (only when the digest or Jude's escalations go by email: brand.json `posting.digest_destination`) | List the labels | Labels come back | Connect Gmail in Claude Settings > Connectors |
| Claude in Chrome (optional) | Read the title of the open tab or open instagram.com | The page answers, signed in as NUMA | Install the Claude in Chrome extension in the Chrome profile signed in to NUMA's Instagram, Facebook and Google Business accounts (spec p.49 step 5) |

Then report how many reels the Higgsfield balance covers:
```
python3 "$S/ledger.py" report --ledger "$STATE/credit_ledger" --balance <balance from the connector>
```
Read the "Balance ... covers N reels" line out to Jude together with the monthly budget (config `budget.monthly_credits`). A missing `STATE/credit_ledger` is fine on a first install (the report starts from zero).

Write the results to `STATE/setup.json` (`{"date", "checks": [{"name", "ok", "detail"}], "higgsfield_balance", "reels_covered", "material_folder"}`) and upload it to Drive `drive.plan_dir`.

## 4. The reel-material folder (R269): ask once

Ask Jude this one question, once: "Which Google Drive folder holds NUMA's reel material? (Default: NUMA Reels, created in step 5.)" Show the top-level Drive folders as the choices.

- Store the answer: the folder name goes into brand.json `drive.root` and the folder link into `drive.root_link`, written into the plugin's brand.json, validated (step 2's command with `--skip-render`; the brand.json line must be ✅), and saved the same way /brand-setup saves (its section 4). Every later run reads it from there and never asks again.
- A setup re-run with `drive.root` already set shows the stored folder and moves on.

## 5. Drive structure (spec p.49 step 6): create what is missing

Create only what does not exist yet (search first; never duplicate, never rename or delete Katie's files). Names come from brand.json `drive`.

| Item | Where (brand.json key) | Content |
|---|---|---|
| Root folder | `drive.root` | holds the month folders `drive.month_folder` that /plan-month creates |
| Plan folder | `drive.plan_dir` | state files, the plan Sheet (/plan-month), `setup.json` |
| Music Library | `drive.music_library` | licensed tracks named `drive.music_naming` (mood_bpm_title.mp3) |
| Digests | `drive.digests` | the Monday digest Docs |
| Consent List Sheet | `drive.consent_list` | header row exactly brand.json `consent.list.columns`: `name`, `photo`, `date consented`, `scope` (scope values: `social posts`, `AI motion`, `voice clone`, separated by `;`) |
| Closures Sheet | `drive.closures` | header row exactly: `Date`, `Name`, `Note` (Date as YYYY-MM-DD; one row per closure or holiday; /brand-setup Q3 fills the first rows) |

The plan Sheet (`drive.plan_sheet`) and the metrics Sheet (`drive.metrics_sheet`) are created by /plan-month and /dashboard-refresh on their first run. Re-read both new Sheets' header rows and confirm they match the table exactly.

## 6. Pre-approve connector tools so scheduled runs never stall (R264)

Follow docs/SCHEDULED_TASKS.md section "So runs never stall": every tool of Google Drive, Google Sheets, Google Docs, Gmail, Higgsfield, Composio and Claude in Chrome set to **Always allow** in Claude's settings (Claude Code: `permissions.allow` entries `mcp__Google_Drive__*`, `mcp__Google_Sheets__*`, `mcp__Higgsfield__*`, `mcp__Composio__*`, `mcp__claude-in-chrome__*`, plus `Bash(python3:*)`). Then run the step 3 calls once more: any permission prompt that still appears is a tool not yet set to Always allow.

## 7. Desktop app settings (spec p.15, p.49 step 2)

Have Jude switch on, in the Claude desktop app's settings on Katie's Mac: **Keep computer awake** and **Run on startup**. They keep Claude in Chrome available to the Scout as often as possible; the daily reel ships from the cloud either way. Confirm both are on before going on.

## 8. Brand answers

When brand.json still has `needs_katie` facts (step 2's brand.json line counts them), run /brand-setup now with Katie's answers (docs/QUESTIONS_FOR_KATIE.md is the printable form). It can also run later; until then every run uses the research defaults and never states a `needs_katie` value as fact.

## 9. Golden test before the schedule goes on (M2, spec p.50 step 10)

1. Upload the "2026-11-09 Year One" test pack to Drive under `drive.root` as its own folder.
2. Run `/make-reel 2026-11-09 Year One` with no other input.
3. Pass: finished in under 15 minutes; story arc, before/after wipe, beat-synced cuts and synced captions present; Jude rates it at least as good as the hand-built reference reel. Record the time and Jude's rating in `STATE/setup.json` (`golden_test`).
4. Fail: do not switch the schedule on; fix and repeat.

## 10. Scheduled tasks

Create the six scheduled tasks exactly as docs/SCHEDULED_TASKS.md lists them (names, Central times from config `schedule`, the prompts to paste, notifications on), only after step 9 passed. Run each once with "Run now" and confirm it finishes with no permission prompt.

## 11. Finish

End with a short summary for Jude: every ✅ / ❌ with its fix, the balance and how many reels it covers, the chosen material folder, the golden-test result, and the line "Setup done: the scheduled tasks run on their own; Katie only films what a shoot card lists." When any ❌ remains, list them first under "Still to fix" and leave the schedule off.
