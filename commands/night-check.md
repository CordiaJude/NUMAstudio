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

## Run start and end (R339-R342)

1. **Log the start:** `python3 "$S/runlog.py" start night_check --state "$STATE"`; keep the printed run id (`RUN_ID`). Sync with Drive: download Drive `drive.plan_dir`/`runlog.json` and `chrome_queue.json` to `STATE/runlog.drive.json` and `STATE/chrome_queue.drive.json` (skip what does not exist yet), then `python3 "$S/runlog.py" merge "$STATE/runlog.drive.json" --state "$STATE"` and `python3 "$S/chrome_queue.py" merge "$STATE/chrome_queue.drive.json" --state "$STATE"`, and upload both files back.
2. **Environment:** `python3 "$S/ensure_env.py" --json` (a fresh cloud machine installs what is missing; a warm one returns in seconds). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), still run the watchdog (section 6; runlog.py needs no packages), finish `failed` (step 3) and stop.
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = done with something left out; `failed` = stopped), then merge and upload as in step 1. Lost the id: `--task night_check`.

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

**Claude in Chrome (R342).** Check first that the `mcp__claude-in-chrome__*` tools are visible and answer a harmless call (read the open tab's title). Visible: drain the queue first (commands/chrome-queue.md sections 2 and 4), then the scout searches NUMA's signed-in channels. Not visible: the scout uses web search now, section 4 decides tonight as usual, and the lines still without a shot are queued for a signed-in search before the 5 am build (the build uses whatever lands in the day folder's `scout/`):
```
python3 "$S/chrome_queue.py" add --kind scout_research --payload '{"for": "Day 10", "what": "line 4: sauna glowing, empty", "save_to": "Day 10 - 2026-12-10 - Cold snap calm/scout"}' --deadline 2026-12-10T04:30:00-06:00 --fallback "Tonight's section 4 substitute stands" --state "$STATE"
```

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

## 6. Watchdog (R341)

After section 5's Sheet update and before the run's final message (Katie's heads-up stays the final message), check the last 7 days of scheduled runs:
```
python3 "$S/runlog.py" check --state "$STATE" --json --mark-reported
```
Then expire what the Chrome queue can no longer do: `python3 "$S/chrome_queue.py" expire --state "$STATE" --json`, and run each returned item's fallback (commands/chrome-queue.md table, last column).

Act on every problem with `"new": true` by its `action`:

| `action` | Do now |
|---|---|
| `late_build` | Follow commands/build-today.md for that `date` (it can still post before the posting window ends) |
| `reschedule` | The day could not post: move that date's plan row per commands/make-reel.md "Reschedule" (status `Ready to build`), and add a line to `STATE/digest_notes.json` `heads_ups` |
| `rerun` | Run that task's command file now (`plan_month` = commands/plan-month.md for next month, `digest` = commands/digest.md) |
| `skip` | Nothing: the next run catches up (dashboard pulls stay due; next week's trend check) |

Then send **Jude one line** through the escalation channel in `STATE/brand.json` (DECISIONS D19) naming the new problems and what was done, for example: "NUMA Studio watchdog: Build today missed Tue Nov 10 (day rescheduled); Dashboard refresh failed Sat Nov 7 (Composio unreachable; next run catches up). Fix: none unless it repeats; then check the task in the Claude app's Scheduled list." **Katie gets nothing:** the watchdog line never goes in this run's final message (that message is Katie's notification) and never in her heads-up. No new problems: no line.

## Done means

Tomorrow's row is `Ready to build` (or swapped, with both folders and cards updated), every decision is in `JOB/work/decisions.md`, any heads-up is sent, the watchdog ran and the run is finished in the run log. Nobody was asked anything.
