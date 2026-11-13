---
description: Desktop-only, hourly while Katie's Mac is awake - drain the Claude in Chrome queue (signed-in Scout research, competitor log, Trial Reels, collab invites, AI label, Higgsfield unlimited drafts) in deadline order, run the fallback of anything past its deadline, and start a late build when today's reel was missed
argument-hint: "(no arguments; runs from the desktop scheduled task \"Chrome queue\")"
model: opus
---
# /chrome-queue: do the Chrome steps while the Mac is awake

You are NUMA's **Director**. This runs from the desktop scheduled task **Chrome queue** (hourly at minute 47, created in the Claude desktop app on Katie's Mac, so it runs only while the Mac is awake; docs/SCHEDULED_TASKS.md). Cloud runs cannot reach Claude in Chrome, so they queue those steps in `STATE/chrome_queue.json` with a deadline and a fallback (R342); this task does them. Rules as commands/make-reel.md section 0: never ask Katie anything, never wait, nothing blocks; a step that cannot be done by its deadline gets its fallback.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `STATE` | `~/NUMA Studio/_Plan` (synced with Drive brand.json `drive.plan_dir`) |

**Brand data (DECISIONS D18).** At the start of every Bash call that runs a script:
```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

## 1. Run start

1. `python3 "$S/runlog.py" start chrome_queue --state "$STATE"`; keep the printed run id (`RUN_ID`).
2. `python3 "$S/ensure_env.py" --json`. Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), finish the run `failed` (section 6) and stop.
3. **Sync the queue and the log with Drive.** Download Drive `drive.plan_dir`/`chrome_queue.json` to `STATE/chrome_queue.drive.json` and `runlog.json` to `STATE/runlog.drive.json` (skip a file that does not exist in Drive yet), then:
   ```
   python3 "$S/chrome_queue.py" merge "$STATE/chrome_queue.drive.json" --state "$STATE"
   python3 "$S/runlog.py" merge "$STATE/runlog.drive.json" --state "$STATE"
   ```
   Upload both files back to Drive (update in place). Upload `chrome_queue.json` again after every `done`, `fail` or `expire` below, so a cloud run at the same time sees it.

## 2. Expired items first: run their fallbacks

```
python3 "$S/chrome_queue.py" expire --state "$STATE" --json
```
Run the fallback of every returned item now (table, last column), and add one line per item to `STATE/digest_notes.json` `heads_ups` ("Thursday's Trial Reel went out as a normal reel: Chrome was not available by posting time"). Nothing waits on an expired item.

## 3. Is Chrome here?

Check that the Claude in Chrome tools (`mcp__claude-in-chrome__*`) are visible in this session and answer a harmless call (read the open tab's title). Not visible or no answer (Chrome closed, extension off): log "Chrome not available", skip to section 5. The queue waits for the next hour; deadlines still apply.

## 4. Drain the queue in deadline order

Repeat until `next` returns `"item": null`:
```
python3 "$S/chrome_queue.py" next --state "$STATE" --json
```
Do the item (table below). Success: `python3 "$S/chrome_queue.py" done <id> --result "<what Chrome did: permalink, file, count>" --state "$STATE"`. A failed attempt (logged out, page changed): `python3 "$S/chrome_queue.py" fail <id> --reason "<one line>" --state "$STATE"`, then go on with the next item; it is retried next hour until its deadline. Items held back by `not_before` (`waiting` in the output) are left for a later hour.

| Kind | Payload | Chrome does | Fallback when the deadline passes |
|---|---|---|---|
| `scout_research` | `for`, `what`, `save_to` (a STATE file or a Drive day folder) | Send the **scout** (agents/scout.md) in Chrome mode with `what`; it saves finds to `save_to` (files in the day folder's `scout/`, recorded with sources.py). A fact that differs from what the plan uses (a price, an event date): fix those plan rows, cards and Sheet rows as commands/plan-month.md section 8 does, and log a heads-up | The web-search result stands; heads-up "signed-in check of <what> skipped" |
| `competitor_log` | `month` | The scout's "Competitor log" in Chrome; it replaces `STATE/competitors_<month>.json`; upload it to Drive `drive.plan_dir` (tonight's dashboard refresh reads it) | The web-search log stands; heads-up |
| `trial_reel` | `job`, `slug` | commands/post-reel.md for `job`, section 5 "Claude in Chrome" column (post as a Trial Reel) | commands/post-reel.md `<job> publish` as a normal reel, noted in `work/post.json` and as a heads-up |
| `collab_invite` | `job`, `partner` | commands/post-reel.md section 5 Chrome column (collaborator invite) | Post without the invite; heads-up |
| `ai_label` | `job` | commands/post-reel.md section 6 row 2 (post with **AI label** on) | Not posted: section 6 row 3 (row stays "Ready to post (AI label)", Jude gets its one line) |
| `higgsfield_unlimited` | `day`, `folder`, `photos`, `prompts` | The scout's "Higgsfield unlimited-window drafts" on higgsfield.ai; drafts saved to the day folder's `scout/higgsfield/` for that build's Motion crew | Nothing to redo: that build drafts through the Higgsfield connector at `kling_std_5s` (config `higgsfield.defaults.motion_draft`) |

## 5. Late build (watchdog, R341)

```
python3 "$S/runlog.py" check --state "$STATE" --json
```
For a `build_today` problem with `action` `late_build` and `runs` below 2 (one late try, not one an hour): follow commands/build-today.md for its `date` now. That run records its own `build_today` run, so the next check sees the slot covered. Every other problem is left to the night check and the dashboard refresh (they send Jude's line); do not pass `--mark-reported` here.

## 6. Run end (always, also on failure)

```
python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<n done, n expired, Chrome available or not>" --state "$STATE"
```
`--outcome failed` when the run stopped early (environment, Drive), `partial` when an item's Chrome step failed. Then sync with Drive as in section 1 step 3. Lost the id: `--task chrome_queue` instead of `<RUN_ID>`.

Final message: one short statement of what was done ("Chrome queue: 1 Trial Reel posted, 1 competitor log refreshed"). It is never a question and never asks Katie anything.

## Done means

No pending item is past its deadline, every item that Chrome could do is done or has a failed attempt recorded, the queue and log are back in Drive, and the run is finished in the log.
