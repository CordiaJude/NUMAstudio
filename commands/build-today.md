---
description: Build today's planned post (daily, 5 am) - resolve today's plan row and Drive folder, run the /make-reel procedure (or cut the carousel or Stories), mark the Sheet row and notify Katie's phone
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /build-today: build today's reel and outputs

You are NUMA's **Director**. This runs from the `build_today` scheduled task (config `schedule.tasks`, daily 5 am, `schedule.timezone`); no one types a command. Same rules as commands/make-reel.md section 0: never ask Katie anything, never wait, every failure follows the failure table, the run ends with a finished post or a rescheduled day.

Paths as in commands/make-reel.md section 1 (`S`, `STUDIO`, `STATE`, `JOB`).

## 1. Resolve today's row and folder

1. `DAY` = `$ARGUMENTS`, else today's date in Central time.
2. Upload anything waiting in a `work/upload_queue.json` from an earlier run first (failure row F15).
3. Read `DAY`'s row from the plan Sheet (brand.json `drive.plan_sheet`, month tab) through the Google Sheets connector; save it as `JOB/work/plan_row.json`. Its Folder link names the day folder (`drive.day_folder` pattern).
4. Status `Ready to post` or `Posted`: already done; log it and stop. Status `Planned` or `Shot` (the night check did not finish): run commands/night-check.md sections 2-4 for `DAY` now, then continue.
5. No row at all: make-reel's folder rules decide (newest folder, else topic-only F16, else an evergreen reel F13 move 1).

## 2. Build by the row's kind

| Kind | What to run |
|---|---|
| reel, trial_reel | Read commands/make-reel.md and follow every section with `$ARGUMENTS` = `DAY` (it resolves the day folder from the date). Make-reel step 5 runs `baseline_plan.py --template NAME` with the row's Template column. For a Trial Reel set plan `meta` tag `trial_reel: true`; posting it as a Trial Reel goes through the Graph API or Claude in Chrome (Composio has no Trial Reels). |
| carousel | Today's carousel comes from the reel it is `derived_from` (the Shot list says so; default: yesterday's reel). With that reel's job: `python3 "$S/formats.py" "$SRC/work/plan.json" "$SRC/out/<slug>_reel.mp4" --out "$JOB/out" --slug "<today's slug>" --only carousel,cover --json`; LOOK at two slides; caption via the copywriter (numa-caption skill); `claims_scan.py --file` on the copy. |
| stories | The Story set from the most recent finished reel: `python3 "$S/formats.py" "$SRC/work/plan.json" "$SRC/out/<slug>_reel.mp4" --out "$JOB/out" --slug "<today's slug>" --only story --json`; one line of text per frame from the reel's lines. |

Closure day (`STATE/closures.json`): make-reel failure row F13 first; nothing that invites people in.

## 3. Deliver and mark the row (R173, R263)

1. Everything in `JOB/out/` goes to the day folder's `Finished/` (make-reel step 13).
2. Sheet Status: `Ready to post` and the Reel link (the Finished/ file link). When brand.json `posting.auto_post.value` and `posting.legal_review_done.value` are both true, posting happens per make-reel step 13 and the status becomes `Posted`.
3. Rescheduled day (make-reel "Reschedule"): the row moves, status back to `Ready to build`, and a line goes to `STATE/digest_notes.json` `heads_ups`.
4. **Phone notification:** the run's final message is make-reel's delivery note (section 6), headed "NUMA reel ready: Day NN - Title". The scheduled task has notifications on (docs/SCHEDULED_TASKS.md), so it reaches Katie's phone. It is a statement, never a question.

## Done means

Today's post is in `Finished/` (or posted), the row says `Ready to post` / `Posted` / rescheduled, the delivery note is sent, and the Decisions log is complete.
