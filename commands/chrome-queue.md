---
description: Desktop-only, hourly while Katie's Mac is awake - claim and do the queued Claude in Chrome steps (signed-in Scout research, competitor log, Higgsfield unlimited drafts, and for approved posts only the Trial Reel, collab invite or AI label), and start a late build that stages the day's post for approval when today's build was missed
argument-hint: "(no arguments; runs from the desktop scheduled task \"Chrome queue\")"
model: opus
---
# /chrome-queue: do the Chrome steps while the Mac is awake

You are NUMA's **Director**. This runs from the desktop scheduled task **Chrome queue** (hourly at minute 47, created in the Claude desktop app on Katie's Mac, so it runs only while the Mac is awake; docs/SCHEDULED_TASKS.md). Cloud runs cannot reach Claude in Chrome, so they queue those steps in `STATE/chrome_queue.json` with a deadline and a fallback (R342); this task does them. Rules as commands/make-reel.md section 0: never ask Katie anything, never wait, nothing blocks. **Nothing goes out without a person approving it (DECISIONS D26):** posting steps are queued only for approved posts, and no fallback ever publishes.

This is the only drainer of the posting kinds (`trial_reel`, `collab_invite`, `ai_label`), so one machine, Katie's Mac, ever posts through Chrome; its claims (below) keep two overlapping runs on the Mac from taking the same item. Cloud runs that happen to see Chrome take only the other kinds. Expiry is not done here: the 8 pm night check is the one designated runner that expires items and runs their fallbacks.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `STATE` | `~/NUMA Studio/_Plan` (synced with Drive brand.json `drive.plan_dir`) |

**Brand data (DECISIONS D18).** At the start of every Bash call that runs a script:
```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

## 1. Run start

1. **Sync, then log the start.** Download the Drive folder `drive.plan_dir`/`runlog/` (every file) into `STATE/runlog.drive/`, run `python3 "$S/runlog.py" merge-dir "$STATE/runlog.drive" --state "$STATE"`, then `python3 "$S/runlog.py" start chrome_queue --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/`. An earlier run cut off by sleep is recorded as interrupted, not stuck.
2. **Sync the queue.** Download Drive `chrome_queue.json` to `STATE/chrome_queue.drive.json`, then `python3 "$S/chrome_queue.py" merge "$STATE/chrome_queue.drive.json" --state "$STATE"`. **A failed download is never "absent":** if the Drive connector fails, skip section 3 this hour (no claims, no uploads of the queue) and go to section 4. Merge, and later upload, only after a download that worked or when Drive confirms there is no `chrome_queue.json` yet.
3. `python3 "$S/ensure_env.py" --json`. Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), finish the run `failed` (section 5) and stop.

## 2. Is Chrome here?

Check that the Claude in Chrome tools (`mcp__claude-in-chrome__*`) are visible in this session and answer a harmless call (read the open tab's title). Not visible or no answer (Chrome closed, extension off): log "Chrome not available" and go to section 4 (a late build needs no Chrome). The queue waits for the next hour; the night check handles deadlines.

## 3. Claim and do the queue in deadline order

Repeat until `next` returns `"item": null`:
```
python3 "$S/chrome_queue.py" next --claim <RUN_ID> --state "$STATE" --json
```
The claim is taken under a lock with a 45-minute lease (the `schedule.chrome_queue.lease_minutes` setting, once the config has it); right after claiming, upload `chrome_queue.json` (download and `merge` first) so the claim is visible. Do the item (table below), then:
- success: `python3 "$S/chrome_queue.py" done <id> --claim <RUN_ID> --result "<what Chrome did: permalink, file, count>" --state "$STATE"`;
- a failed attempt (logged out, page changed): `python3 "$S/chrome_queue.py" fail <id> --claim <RUN_ID> --reason "<one line>" --state "$STATE"`; it is pending again for the next hour, until its deadline;
- `done` exits 1 with "conflict" when the night check already ran the item's fallback: leave it, the conflict is in the queue for Jude's line.

Upload `chrome_queue.json` after every `done` or `fail` (download and `merge` first). A cloud run that drains (it saw Chrome) adds `--kinds scout_research,competitor_log,higgsfield_unlimited` to `next`. Items held back by `not_before` (`waiting` in the output) are left for a later hour: a posting step's window opens 75 minutes before its posting time, so the hourly :47 run always lands inside it.

| Kind | Payload | Chrome does | Fallback when the deadline passes (night check; never publishes) |
|---|---|---|---|
| `scout_research` | `for`, `what`, `save_to` (a STATE file or a Drive day folder) | Send the **scout** (agents/scout.md) in Chrome mode with `what`; it saves finds to `save_to` (files in the day folder's `scout/`, recorded with sources.py). A fact that differs from what the plan uses (a price, an event date): fix those plan rows, cards and Sheet rows as commands/plan-month.md section 8 does, and log a heads-up | The web-search result stands; heads-up "signed-in check of <what> skipped" |
| `competitor_log` | `month` | The scout's "Competitor log" in Chrome; it replaces `STATE/competitors_<month>.json`; upload it to Drive `drive.plan_dir` (tonight's dashboard refresh reads it) | The web-search log stands; heads-up |
| `trial_reel` | `job`, `slug` | First re-read the plan Sheet row: still **Approved** and not yet `Posted`, else `done` with result "not posted: no longer approved". Then commands/post-reel.md for `job`, section 5 "Claude in Chrome" column (post as a Trial Reel) | Stays staged and approved; one line to the approver and Jude: "<title> is approved but Chrome was not available for the Trial Reel: post it from the Instagram app as a Trial Reel, or approve it as a normal reel" |
| `collab_invite` | `job`, `partner` | Same approval re-check; commands/post-reel.md section 5 Chrome column (post with the collaborator invite) | Stays staged; same kind of line: post it from the app with the collaborator, or approve it without the invite |
| `ai_label` | `job` | Same approval re-check; commands/post-reel.md section 6 row 2 (post with **AI label** on) | Stays staged: section 6 row 3 (row "Ready to post (AI label)", Jude gets its one line) |
| `higgsfield_unlimited` | `day`, `folder`, `photos`, `prompts` | The scout's "Higgsfield unlimited-window drafts" on higgsfield.ai; drafts saved to the day folder's `scout/higgsfield/` for that build's Motion crew | Nothing to redo: that build drafts through the Higgsfield connector at `kling_std_5s` (config `higgsfield.defaults.motion_draft`) |

## 4. Late build (watchdog, R341)

```
python3 "$S/runlog.py" check --state "$STATE" --json
```
For a `build_today` problem with `action` `late_build` (the build was missed outright today, no run at all in its slot, and it is still before `late_build_by`): follow commands/build-today.md for its `date` now, starting its run with `runlog.py start build_today --late`. It builds and stages the post for a person to approve; it never posts by itself. Its run fills the slot, so no second late build follows, whatever its outcome. Every other problem is left to the night check and the dashboard refresh (they send Jude's line); do not pass `--mark-reported` here.

## 5. Run end (always, also on failure)

```
python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<n done, n failed, Chrome available or not>" --state "$STATE"
```
`--outcome failed` when the run stopped early (environment), `partial` when an item's Chrome step failed or Drive was unreachable. Then upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/`. Lost the id: `--task chrome_queue` instead of `<RUN_ID>`.

This task runs with notifications off: its final message is one short statement for the log ("Chrome queue: 1 Trial Reel posted, 1 competitor log refreshed"), never a question, and never a message to Katie.

## Done means

Every item Chrome could do is done or has a failed attempt recorded, no claim of this run is left open, the queue and this run's log file are back in Drive, and the run is finished in the run log.
