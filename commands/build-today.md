---
description: Build today's planned post (daily, 5 am) - resolve today's plan row and Drive folder, run the /make-reel procedure (or cut the carousel or Stories), mark the Sheet row and notify Katie's phone
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /build-today: build today's reel and outputs

You are NUMA's **Director**. This runs from the `build_today` scheduled task (config `schedule.tasks`, daily 5 am, `schedule.timezone`); no one types a command. Same rules as commands/make-reel.md section 0: never ask Katie anything, never wait, every failure follows the failure table, the run ends with a finished post or a rescheduled day.

Paths as in commands/make-reel.md section 1 (`S`, `STUDIO`, `STATE`, `JOB`).

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## Run start and end (R339-R342)

This run's log entry also covers the /make-reel procedure it follows (make-reel skips its own).

1. **Log the start:** `python3 "$S/runlog.py" start build_today --state "$STATE"`; keep the printed run id (`RUN_ID`). Sync with Drive: download Drive `drive.plan_dir`/`runlog.json` and `chrome_queue.json` to `STATE/runlog.drive.json` and `STATE/chrome_queue.drive.json` (skip what does not exist yet), then `python3 "$S/runlog.py" merge "$STATE/runlog.drive.json" --state "$STATE"` and `python3 "$S/chrome_queue.py" merge "$STATE/chrome_queue.drive.json" --state "$STATE"`, and upload both files back.
2. **Environment:** `python3 "$S/ensure_env.py" --json --with-model` (a fresh cloud machine installs the packages and the speech model; a warm one returns in seconds); add `--with-chromium` when today's row is a component carousel (slides need headless Chromium). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), reschedule the day (section 3 step 3), finish `failed` (step 3) and stop. The night check's watchdog sees the failed slot.
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = posted or saved with something left out, such as a Chrome step that went to its fallback; `failed` = stopped or rescheduled by a failure), then merge and upload as in step 1. Lost the id: `--task build_today`.

**Claude in Chrome (R342).** When the `mcp__claude-in-chrome__*` tools are visible and answer a harmless call (read the open tab's title), drain the queue first (commands/chrome-queue.md sections 2 and 4). The steps of today's post that need Chrome (Trial Reel, collab invite, AI label) are queued by the `post-reel` command with a deadline at the posting time and run their fallback there, so nothing here waits for Chrome.

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

Today's post is in `Finished/` (or posted), the row says `Ready to post` / `Posted` / rescheduled, the delivery note is sent, the Decisions log is complete, and the run is finished in the run log.
