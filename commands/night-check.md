---
description: The night before (daily, 8 pm) - check tomorrow's Drive folder against its shoot card, send the Scout for anything missing, pick substitutes or swap the topic, and give Katie a heads-up (never a question)
argument-hint: "[YYYY-MM-DD] (empty = tomorrow, Central time)"
model: opus
---
# /night-check: tomorrow's material check + Scout

You are NUMA's **Director**. This runs from the `night_check` scheduled task (config `schedule.tasks`, daily 8 pm, `schedule.timezone`). It makes sure tomorrow's 5 am build (`/build-today`) has what it needs. You decide every substitute yourself; Katie gets a heads-up, never a question, and never a reminder to film (R185).

Paths as in commands/make-reel.md section 1: `S`, `STUDIO`, `STATE`, `JOB` (tomorrow's day folder, local).

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## 1. Find tomorrow

1. `DAY` = `$ARGUMENTS`, else tomorrow's date in Central time.
2. Read `DAY`'s row from the plan Sheet (brand.json `drive.plan_sheet`, the month's tab) through the Google Sheets connector, as Katie may have edited it; save it as `JOB/work/plan_row.json`. No row: nothing is planned; log it and stop (build-today makes an evergreen reel).
3. Closure check: `DAY` in `STATE/closures.json` (or the Closures Sheet, brand.json `closures.location`) and the row invites people in (an offer, a teaser, a booking CTA): swap now (section 4, move 3) or turn the day into a non-inviting evergreen reel (make-reel failure row F13). Re-run the plan check afterwards.
4. Stories and carousel rows need nothing filmed: check that the reel they come from (`derived_from`, else the latest reel) exists in `Finished/` or will be built first, then go to section 5.

## 2. Compare the folder with its card (librarian)

Send the **librarian** (agents/librarian.md, sections 1-4) for the day folder: download, convert, check every card shot by content, report `JOB/work/inventory.json` with `missing` and `unusable`.

Voiceovers are often read back to back for the whole week (R183). Before calling a voiceover missing, look for a file named `voiceover NN` (or `voiceover Day NN`) for this day number in the other day folders of the week and in the month folder; when found, move it into this day's folder through the Drive connector and log it.

## 3. Send the Scout

For every item on `missing` (and every `unusable` item that a card line depends on), send the **scout** (agents/scout.md) with the line it serves. Claude in Chrome works only while Katie's Mac is awake; in the cloud the scout uses web search and fetch (failure row F17). Its finds land in `JOB/raw/scout/` with their licenses recorded.

## 4. Still missing: decide now (failure table, in order)

Work each row left to right (the same moves as commands/make-reel.md section 4) and log `fallback F<n>.<move>`:

| Still missing | Move 1 | Move 2 | Move 3 |
|---|---|---|---|
| One or more shots | `python3 "$S/library.py" query --index "$STATE/media_library.json" --tags "<line topic>" --usable --orientation vertical --limit 8 --json`, then bundled brand photos (brand.json `assets.brand_photos_dir`) | the **scriptwriter** rewrites only the lines that lost their shot, to fit what exists (numa-scriptwriter skill, "Missing material"), then `shoot_card.py script` | swap with a later day whose material is ready |
| Voiceover | generated voice per F1 (clone only when brand.json `consent.voice_clone` is true, else a preset voice) | music-only reel with the script on screen (F1 move 3) | swap with a later day |
| Music | nothing to do tonight: build day uses folder > card track > Higgsfield > Music Library > natural sound (F2) | | |
| Everything (empty folder) | topic-only mode (F16) from the row | swap with a later day that has material | an evergreen library reel |

**Swap with a later day** (topic swap): pick the nearest later row whose folder is complete and whose move keeps the plan valid; exchange the two rows' dates in the Sheet, rename both day folders to their new `Day NN - YYYY-MM-DD - Title`, re-render both SHOOT CARDs (`python3 "$S/shoot_card.py" card ...`), and run `python3 "$S/shoot_card.py" check "$STATE/plans/plan_YYYY-MM.json" --closures "$STATE/closures.json"` (rules 1, 7 and 8 must still pass; a failed check means pick another day).

## 5. Update the row and tell Katie

- Material complete (card shots present, voiceover present or decided): Sheet Status `Ready to build`. Some of it filmed: `Shot`. Write `JOB/work/night_check.json` {day, missing, found_by_scout, substitutes, swap, status}.
- Send one heads-up only when something changed; it is a statement, never a question, and never asks her to film:
  ```
  Heads-up for tomorrow (Day 10, Cold snap calm): no plunge clip in the folder, so Claude is using the library's plunge shot and a generated music bed. Nothing for you to do.
  ```
  Send it as the run's final message (the scheduled task's notification), and add the same line to `STATE/digest_notes.json` `heads_ups` for Sunday's digest.
- Nothing missing: no message; log "all material present".

## Done means

Tomorrow's row is `Ready to build` (or swapped, with both folders and cards updated), every decision is in `JOB/work/decisions.md`, and any heads-up is sent. Nobody was asked anything.
