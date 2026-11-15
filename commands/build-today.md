---
description: Build today's planned post (daily, 5 am) - resolve today's plan row, brief slot and Drive folder, build the right asset for its post type (reel, Trial Reel, component carousel, photo carousel, single photo, Stories), stage it for a person's approval, mark the Sheet row and notify Katie's phone
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /build-today: build and stage today's post

You are Numa's **Director**. This runs from the `build_today` scheduled task (config `schedule.tasks`, daily 5 am, `schedule.timezone`); no one types a command. Same rules as commands/make-reel.md section 0: never ask Katie anything, never wait, every failure follows the failure table, the run ends with a finished, staged post or a rescheduled day. **Nothing posts without a person's approval (DECISIONS D26):** this run builds the post and stages it as "Ready to post"; it never posts an unapproved row and asks nobody anything.

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

**Story pulls first (Story capture timing).** A Story's insights vanish at 24 h, so this 5 am run is one of the four Story pull runs (docs/SCHEDULED_TASKS.md "Story capture timing"): sync `STATE/metrics.json` from Drive `drive.plan_dir`, run commands/dashboard-refresh.md section 2 for the due items whose `post_type` is `story` only, then upload `metrics.json` and `insights/` back. A failed pull never stops the build.

## 1. Resolve today's row and folder

1. `DAY` = `$ARGUMENTS`, else today's date in Central time.
2. Upload anything waiting in a `work/upload_queue.json` from an earlier run first (failure row F15).
3. Read `DAY`'s row from the plan Sheet (brand.json `drive.plan_sheet`, month tab) through the Google Sheets connector; save it as `JOB/work/plan_row.json`. Its Folder link names the day folder (`drive.day_folder` pattern).
4. Status `Ready to post`, `Approved` (or `Approved - <name>`) with a staged record in `STATE/staged/`, or `Posted`: already built; log it and stop (an approved post is posted by commands/post-reel.md section 13, never rebuilt here). Status `Approved` with no staged post: a person approved the plan before the post existed; build it, and the staging step below sets the row back to `Ready to post` for a real approval. Status `Planned` or `Shot` (the night check did not finish): run commands/night-check.md sections 2-4 for `DAY` now, then continue.
5. No row at all: make-reel's folder rules decide (newest folder, else topic-only F16, else an evergreen reel F13 move 1).
6. **Today's brief slot (R350).** Read `STATE/strategy_brief.json` `slots[]` for `DAY` (else the row in `STATE/plans/strategy_YYYY-MM.json`): `post_type`, `kind`, `post_time`, `pattern_ids`, `strategy_arm`, `goal`, `mode` and `why`. The slot's `post_type` decides section 2 when the Sheet row does not name one (a person's edit to the row wins); hand `pattern_ids`, `strategy_arm` and `mode` to the scriptwriter, designer and copywriter (skills/numa-scriptwriter/ADAPTIVE.md), and keep the slot's `post_time` as the planned posting time. No brief and no strategy plan (the first month): the default week from the row.

## 2. Build by post type (config `post_types`, R336)

The row's `kind` (from the brief slot or the plan row) picks one asset. A carousel's `carousel_source` is the row's (strategy.py plan writes it); missing, the one rule of `shoot_card.carousel_source_of`: component when `pattern_ids` name a carousel pattern, else reel when `derived_from` is set, else component. Every type ends the same way: files in `JOB/out/`, the caption from the **copywriter** (numa-caption skill) in `out/SLUG_copy.txt`, `claims_scan.py` clean on every text, and section 3 stages it.

| Post type (`kind`) | What to cut | Output |
|---|---|---|
| reel, trial_reel | Read commands/make-reel.md and follow every section with `$ARGUMENTS` = `DAY` (it resolves the day folder from the date; its step 13 stages the reel, never posts an unapproved row). Make-reel step 5 runs `baseline_plan.py --template NAME` with the row's Template column. For a Trial Reel set plan `meta` tag `trial_reel: true`; posting it as a Trial Reel goes through the Graph API or, after approval, the Chrome queue (Composio has no Trial Reels). | `SLUG_reel.mp4` + formats |
| carousel, `carousel_source` component (new copy: an explainer, protocol, myth vs fact, FAQ, offer; the default when the slot's `pattern_ids` name a carousel pattern) | `python3 "$S/ensure_env.py" --json --with-chromium`, then send the **designer** (agents/designer.md, numa-carousel skill): carousel.json from the slot's patterns, one Claude Design canvas, `design_render.py canvas` (fallback `design_render.py spec`), LOOK, checks clean. Chromium missing: numa-carousel fallback row 5 (a photo carousel instead). | `SLUG_carousel_NN.jpg` + `carousel_sheet.jpg`; canvas link in `work/carousel.json` |
| carousel, `carousel_source` photos (2-10 fitting photos in the day folder or the library, no new copy) | Pick the photos (librarian people rules, agents/librarian.md section 5), then `python3 "$S/photo_post.py" carousel "$JOB/raw/photos" --out "$JOB/out" --slug SLUG --texts "$JOB/work/slide_texts.json" --json > "$JOB/work/photo_post.json"` with the people basis per photo (commands/post-reel.md section 12 step 1); LOOK at every slide. | `SLUG_carousel_NN.jpg` |
| carousel, `carousel_source` reel (`derived_from` a reel and no carousel pattern in `pattern_ids`) | With that reel's job `SRC`: `python3 "$S/formats.py" "$SRC/work/plan.json" "$SRC/out/<slug>_reel.mp4" --out "$JOB/out" --slug "<today's slug>" --only carousel,cover --json`; LOOK at two slides. | `SLUG_carousel_NN.jpg` + cover |
| image (a single-photo feed post on a topic; nothing filmed) | Pick the best photo (day folder, else `library.py query --usable`, else brand photos) under the librarian people rules, then `python3 "$S/photo_post.py" single "<photo>" --out "$JOB/out/SLUG_photo.jpg" --text "<short line, *gold* word>" --json > "$JOB/work/photo_post.json"` with its people basis; LOOK at it. | `SLUG_photo.jpg` |
| stories | The Story set from the most recent finished reel: `python3 "$S/formats.py" "$SRC/work/plan.json" "$SRC/out/<slug>_reel.mp4" --out "$JOB/out" --slug "<today's slug>" --only story --json`; one line of text per frame from the reel's lines; `story_frames` from the slot (3-5). | `SLUG_story_<N>.jpg|mp4` |

Closure day (`STATE/closures.json`): make-reel failure row F13 first; nothing that invites people in. A half day (brand.json `closures.partial`): the planned time is before closing.

**Tags for learning (R350).** Copy `pattern_ids`, `strategy_arm`, `boosted` and `story_frames` from `work/script.json` (else the plan row or brief slot), unchanged, plus `post_type` (reel, trial_reel, carousel, image or story), title, slug, series, pillar, hook_type and length, into `STATE/insights/tags_<SLUG>.json` and the staged record's `tags`. The post is tagged the moment it is published, with its media id (commands/post-reel.md section 7 step 3, in this run or a later re-check run):
```
python3 "$S/metrics.py" tag --store "$STATE/metrics.json" --post <media_id> --tags "$STATE/insights/tags_<SLUG>.json"
```
Never tag by slug before posting: a slug entry would never get insights.

## 3. Deliver, stage for approval and mark the row (R173, R263, D26)

1. Everything in `JOB/out/` goes to the day folder's `Finished/` (make-reel step 13).
2. **Stage it** (a reel or Trial Reel: make-reel step 13 already did this): run commands/post-reel.md for `JOB` (sections 1-2): it writes `work/post.json` and the staged record `STATE/staged/<SLUG>.json` (uploaded to Drive `_Plan/staged/`) and re-reads the row. Sheet Status: `Ready to post` and the Reel link (the Finished/ file link). Posting happens, and the status becomes `Posted`, only when **the plan row is Approved by a person** (its Status reads Approved, set after the post was staged; DECISIONS D26) and brand.json `posting.auto_post.value` is true; post-reel records who approved it and when. Not approved (the usual case at 5 am): the post stays staged as `Ready to post`, the digest lists it, and the night check, dashboard refresh, midday Story task and Chrome queue task re-check it (commands/post-reel.md section 13); once a person marks it Approved it posts at its planned time, or at the next slot when that time has passed. Nothing posts and nothing is asked here.
3. Rescheduled day (make-reel "Reschedule"): the row moves, status back to `Ready to build`, and a line goes to `STATE/digest_notes.json` `heads_ups`.
4. **Phone notification:** the run's final message is make-reel's delivery note (section 6), headed "Numa post ready: Day NN - Title (<post type>)", ending with the line "Staged for approval: mark the plan row Approved to post it at <planned time>." This is the run's one approver notice (commands/post-reel.md section 13 step 5). Record it in `STATE/approval_notices.json` **only when it was delivered**: the 5 am scheduled task has notifications on, so its final message counts; a late build or a hand run (notifications off) records it only when Gmail sent it to the `STATE/setup.json` `approval_notify` addresses. When those addresses are set, the same line goes there by Gmail. The scheduled task has notifications on (docs/SCHEDULED_TASKS.md), so it reaches the owners' phones. It is a statement, never a question.

## Done means

Today's post is in `Finished/` and staged for approval (or, already approved, posted), the row says `Ready to post` / `Posted` / rescheduled, the staged record and tags file are written, no unapproved post went out, the delivery note is sent, the Decisions log is complete, and the run is finished in the run log.
