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

1. **Log the start (R340).** Download the Drive folder `drive.plan_dir`/`runlog/` (every file) into `STATE/runlog.drive/` and run `python3 "$S/runlog.py" merge-dir "$STATE/runlog.drive" --state "$STATE"`. Then `python3 "$S/runlog.py" start build_today --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/` (a file only this run ever writes, so no other run's record is overwritten). A late build the watchdog started adds `--late` to `start`. Download the Drive folder `drive.plan_dir`/`chrome_queue/` (one file per queued item) into `STATE/chrome_queue.drive/` and run `python3 "$S/chrome_queue.py" merge-dir "$STATE/chrome_queue.drive" --state "$STATE"`. **A failed download is never "absent":** merge only after a download that worked, or when Drive confirms a folder does not exist yet (then start from an empty `STATE/runlog.drive/` or `STATE/chrome_queue.drive/`). When the Drive connector fails, upload only this run's own `runlog/<RUN_ID>.json` and upload no queue items this run.
2. **Environment:** `python3 "$S/ensure_env.py" --json --with-model` (a fresh cloud machine installs the packages and the speech model; a warm one returns in seconds); add `--with-chromium` when today's row is a component carousel (slides need headless Chromium). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), reschedule the day (section 3 step 3), finish `failed --rescheduled` (step 3) and stop. The night check's watchdog sees the failed slot.
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = done with something left out; `failed` = stopped; add `--rescheduled` when this run already moved the day (step 2 or a failure-table reschedule), so the watchdog does not move it again), then upload `STATE/runlog/<RUN_ID>.json` again (and `STATE/runlog/reported-<RUN_ID>.json` when the watchdog wrote one). Upload to Drive `_Plan/chrome_queue/` exactly the item files that this run's `chrome_queue.py` calls listed under `files` (`--json`), never the whole folder (only after the step 1 download worked). Lost the id: `--task build_today`.

**Claude in Chrome (R342).** When the `mcp__claude-in-chrome__*` tools are visible and answer a harmless call (read the open tab's title), drain the queue first (commands/chrome-queue.md section 3; a cloud run takes only the non-posting kinds). Nothing posts without a person's approval (DECISIONS D26): this run builds and stages today's post; the Chrome posting steps (Trial Reel, collab invite, AI label) are queued by the `post-reel` command only after the post is approved, so nothing here waits for Chrome.

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
2. Sheet Status: `Ready to post` and the Reel link (the Finished/ file link). Posting happens per make-reel step 13, and the status becomes `Posted`, only when **the plan row is Approved by a person** (DECISIONS D26: nothing goes out without a person approving it) and brand.json `posting.auto_post.value` and `posting.legal_review_done.value` are both true. Not approved: the post stays staged as `Ready to post` and the digest lists it; nothing posts and nothing is asked.
3. Rescheduled day (make-reel "Reschedule"): the row moves, status back to `Ready to build`, and a line goes to `STATE/digest_notes.json` `heads_ups`.
4. **Phone notification:** the run's final message is make-reel's delivery note (section 6), headed "NUMA reel ready: Day NN - Title". The scheduled task has notifications on (docs/SCHEDULED_TASKS.md), so it reaches Katie's phone. It is a statement, never a question.

## Done means

Today's post is in `Finished/` (or posted), the row says `Ready to post` / `Posted` / rescheduled, the delivery note is sent, the Decisions log is complete, and the run is finished in the run log.
