---
description: The night before (daily, 8 pm) - check tomorrow's Drive folder against its shoot card, send the Scout for anything missing, pick substitutes or swap the topic, and give Katie a heads-up (never a question)
argument-hint: "[YYYY-MM-DD] (empty = tomorrow, Central time)"
model: opus
---
# /night-check: tomorrow's material check + Scout

You are Numa's **Director**. This runs from the `night_check` scheduled task (config `schedule.tasks`, daily 8 pm, `schedule.timezone`). It makes sure tomorrow's 5 am build (`/build-today`) has what it needs, pulls the Stories that are inside their insight window, and re-checks every post staged for approval (section 7). You decide every substitute yourself; Katie gets a heads-up, never a question, and never a reminder to film (R185).

Paths as in commands/make-reel.md section 1: `S`, `STUDIO`, `STATE`, `JOB` (tomorrow's day folder, local).

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## Run start and end (R339-R342)

1. **Log the start (R340).** Download the Drive folder `drive.plan_dir`/`runlog/` (every file) into `STATE/runlog.drive/` and run `python3 "$S/runlog.py" merge-dir "$STATE/runlog.drive" --state "$STATE"`. Then `python3 "$S/runlog.py" start night_check --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/` (a file only this run ever writes, so no other run's record is overwritten). Download the Drive folder `drive.plan_dir`/`chrome_queue/` (one file per queued item) into `STATE/chrome_queue.drive/` and run `python3 "$S/chrome_queue.py" merge-dir "$STATE/chrome_queue.drive" --state "$STATE"`. **A failed download is never "absent":** merge only after a download that worked, or when Drive confirms a folder does not exist yet (then start from an empty `STATE/runlog.drive/` or `STATE/chrome_queue.drive/`). When the Drive connector fails, upload only this run's own `runlog/<RUN_ID>.json` and upload no queue items this run.
2. **Environment:** `python3 "$S/ensure_env.py" --json` (a fresh cloud machine installs what is missing; a warm one returns in seconds). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), still run the watchdog (section 6; runlog.py needs no packages), finish `failed` (step 3) and stop.
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = done with something left out; `failed` = stopped), then upload `STATE/runlog/<RUN_ID>.json` again (and `STATE/runlog/reported-<RUN_ID>.json` when the watchdog wrote one). Upload to Drive `_Plan/chrome_queue/` exactly the item files that this run's `chrome_queue.py` calls listed under `files` (`--json`), never the whole folder (only after the step 1 download worked). Lost the id: `--task night_check`.

## 1. Find tomorrow

1. `DAY` = `$ARGUMENTS`, else tomorrow's date in Central time.
2. Read `DAY`'s row from the plan Sheet (brand.json `drive.plan_sheet`, the month's tab) through the Google Sheets connector, as Katie may have edited it; save it as `JOB/work/plan_row.json`. No row: nothing is planned; log it and stop (build-today makes an evergreen reel).
3. Closure check: `DAY` in `STATE/closures.json` (or the Closures Sheet, brand.json `closures.location`) and the row invites people in (an offer, a teaser, a booking CTA): swap now (section 4, move 3) or turn the day into a non-inviting evergreen reel (make-reel failure row F13). Re-run the plan check afterwards.
4. Rows with nothing to film (config `post_types`): Stories and a `carousel_source` reel carousel need the reel they come from (`derived_from`, else the latest reel) in `Finished/` or built first; a photo carousel (`carousel_source` photos) or single photo (`image`) needs 2-10 (or 1) usable photos in the day folder or the media library that pass the librarian's people rules (agents/librarian.md section 5; none: queue a library query or swap the topic, section 4); a component carousel (`carousel_source` component) needs nothing but the plan row. Then go to section 5.

## 2. Compare the folder with its card (librarian)

Send the **librarian** (agents/librarian.md, sections 1-4) for the day folder: download, convert, check every card shot by content, report `JOB/work/inventory.json` with `missing` and `unusable`.

Voiceovers are often read back to back for the whole week (R183). Before calling a voiceover missing, look for a file named `voiceover NN` (or `voiceover Day NN`) for this day number in the other day folders of the week and in the month folder; when found, move it into this day's folder through the Drive connector and log it.

## 3. Send the Scout

For every item on `missing` (and every `unusable` item that a card line depends on), send the **scout** (agents/scout.md) with the line it serves. Claude in Chrome works only while Katie's Mac is awake; in the cloud the scout uses web search and fetch (failure row F17). Its finds land in `JOB/raw/scout/` with their licenses recorded.

**Claude in Chrome (R342).** Check first that the `mcp__claude-in-chrome__*` tools are visible and answer a harmless call (read the open tab's title). Visible: drain the queue first (commands/chrome-queue.md section 3; a cloud run takes only the non-posting kinds), then the scout searches Numa's signed-in channels. Not visible: the scout uses web search now, section 4 decides tonight as usual, and the lines still without a shot are queued for a signed-in search before the 5 am build (the build uses whatever lands in the day folder's `scout/`):
```
python3 "$S/chrome_queue.py" add --kind scout_research --payload '{"for": "Day 10", "what": "line 4: sauna glowing, empty", "save_to": "Day 10 - 2026-12-10 - Cold snap calm/scout"}' --deadline 2026-12-10T04:30:00-06:00 --fallback "Tonight's section 4 substitute stands" --state "$STATE" --json
```

## 4. Still missing: decide now (failure table, in order)

Work each row left to right (the same moves as commands/make-reel.md section 4) and log `fallback F<n>.<move>`:

| Still missing | Move 1 | Move 2 | Move 3 |
|---|---|---|---|
| One or more shots | `python3 "$S/library.py" query --index "$STATE/media_library.json" --tags "<line topic>" --usable --orientation vertical --limit 8 --json`, then bundled brand photos (brand.json `assets.brand_photos_dir`) | the **scriptwriter** rewrites only the lines that lost their shot, to fit what exists (numa-scriptwriter skill, "Missing material"), then `shoot_card.py script` | swap with a later day whose material is ready |
| Voiceover | Scott's take for this day in another folder of the week (above), else F1: a generic, non-cloned voice only when brand.json `voice.generic_ai_allowed.value` is true, never a clone | music plus on-screen text (F1 move 3) | swap with a later day |
| Music | nothing to do tonight: build day uses folder > card track > Higgsfield > Music Library > natural sound (F2) | | |
| Everything (empty folder) | topic-only mode (F16) from the row | swap with a later day that has material | an evergreen library reel |

**Swap with a later day** (topic swap): pick the nearest later row whose folder is complete and whose move keeps the plan valid; exchange the two rows' dates in the Sheet, rename both day folders to their new `Day NN - YYYY-MM-DD - Title`, re-render both SHOOT CARDs (`python3 "$S/shoot_card.py" card ...`), and run `python3 "$S/shoot_card.py" check "$STATE/plans/plan_YYYY-MM.json" --closures "$STATE/closures.json"` (rules 1, 7 and 8 must still pass; a failed check means pick another day).

## 5. Update the row and tell Katie (one final message)

- Material complete (card shots present, voiceover present or decided): Sheet Status `Ready to build`. Some of it filmed: `Shot`. Write `JOB/work/night_check.json` {day, missing, found_by_scout, substitutes, swap, status}.
- Send one heads-up only when something changed; it is a statement, never a question, and never asks her to film:
  ```
  Heads-up for tomorrow (Day 10, Cold snap calm): no plunge clip in the folder, so Claude is using the library's plunge shot and a generated music bed. Nothing for you to do.
  ```
  Send it as the run's final message (the scheduled task's notification), and add the same line to `STATE/digest_notes.json` `heads_ups` for Sunday's digest.
- Nothing missing: no heads-up; log "all material present".
- The run's final message also carries section 7's approver line when there is one (one notification per run, never one per post).

## 6. Watchdog (R341)

After section 5's Sheet update and before the run's final message (Katie's heads-up and the approver line stay the final message), check the last 7 days of scheduled runs:
```
python3 "$S/runlog.py" check --state "$STATE" --json --mark-reported <RUN_ID>
```
Then expire what the Chrome queue can no longer do. This 8 pm run is the **only** one that expires (one designated runner, so a fallback runs once), and it waits an hour past each deadline so a Chrome step finishing just in time is not undone: `python3 "$S/chrome_queue.py" expire --run <RUN_ID> --state "$STATE" --json`. Run each returned item's fallback (commands/chrome-queue.md table, last column; no fallback ever publishes, DECISIONS D26) and upload the item files it lists under `files` to Drive `_Plan/chrome_queue/`. Each item under `conflicts` (Chrome did it after its fallback ran) goes into Jude's line below.

Act on every problem with `"new": true` by its `action`:

| `action` | Do now |
|---|---|
| `late_build` | Follow commands/build-today.md for that `date` as a late build (`runlog.py start build_today --late`). Only a slot missed outright before `late_build_by` gets one, at most once. It builds and stages the post for a person to approve; nothing posts without approval (DECISIONS D26) |
| `reschedule` | The day's post could not be built in time: move that date's plan row per commands/make-reel.md "Reschedule" (status `Ready to build`), and add a line to `STATE/digest_notes.json` `heads_ups` |
| `rerun` | Run that task's command file now (`plan_month` = commands/plan-month.md for next month, `digest` = commands/digest.md) |
| `skip` | Nothing: the next run catches up (dashboard pulls stay due; next week's trend check) |

Then send **Jude one line** through the escalation channel in `STATE/brand.json` (DECISIONS D19) naming the new problems and what was done, for example: "NUMA Studio watchdog: Build today missed Tue Nov 10 (day rescheduled); Dashboard refresh failed Sat Nov 7 (Composio unreachable; next run catches up). Fix: none unless it repeats; then check the task in the Claude app's Scheduled list." **Katie gets nothing:** the watchdog line never goes in this run's final message (that message is Katie's notification) and never in her heads-up. No new problems: no line.

## 7. Story pulls and the approval re-check (before the final message)

1. **Story pulls.** This 8 pm run is one of the four Story pull runs (5 am, 12:40 pm, 8 pm, 10 pm; docs/SCHEDULED_TASKS.md "Story capture timing"): sync `STATE/metrics.json` from Drive, run commands/dashboard-refresh.md section 2 for the due items whose `post_type` is `story` only (a Story posted at 9 am is 11 h old now and is caught at 10 pm; one posted at 5 pm yesterday is past 24 h and `metrics.py due` no longer lists it), then upload `metrics.json` and `insights/`.
2. **Approvals and the guaranteed 8 pm publish slot (DECISIONS D26).** Run commands/post-reel.md section 13 (`approvals`): a staged post whose plan row now reads Approved is scheduled once (`status: scheduled`, `publish_at`); and this 8 pm run is the **guaranteed 8 pm publish slot**: every approved, `scheduled` post due by 21:00 today and not yet published is published now (under the publish claim, after the duplicate check), even when no one-time task ran and the Mac is off. Every post still staged goes on the approver's one batched line, which joins this run's final message (section 5). It never posts an unapproved row and asks nobody anything.
3. **Tomorrow's half-day post.** When tomorrow's plan row has `build_evening_before` (a half day that posts before config `approval.earliest_post_time`), run commands/build-today.md for tomorrow now, so it is built and staged tonight and can be approved before its morning time.

## Done means

Tomorrow's row is `Ready to build` (or swapped, with both folders and cards updated), every decision is in `JOB/work/decisions.md`, due Story pulls are stored, approved posts are scheduled or posted and waiting ones are on the approver's line, any heads-up is sent, the watchdog ran and the run is finished in the run log. Nobody was asked anything.
