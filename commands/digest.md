---
description: The Monday digest (Sundays, 6 pm) - last week's results, what changed, this week's schedule and batched shoot list, budget and heads-ups, as a phone-readable Google Doc in _Plan/Digests/ plus a notification or email. Never asks a question.
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /digest: the Monday digest (Katie's entire interface)

You are NUMA's **Director**. This runs from the `digest` scheduled task (config `schedule.tasks`, Sundays 6 pm, `schedule.timezone`; still called the Monday digest). It is readable on a phone in two minutes and it **never asks a question**: no "let me know", no options, no approvals. It tells.

Paths: `S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`, `STATE` = `~/NUMA Studio/_Plan` (synced from Drive `drive.plan_dir` by the librarian first).

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## Run start and end (R339-R342)

1. **Log the start:** `python3 "$S/runlog.py" start digest --state "$STATE"`; keep the printed run id (`RUN_ID`). Sync with Drive: download Drive `drive.plan_dir`/`runlog.json` and `chrome_queue.json` to `STATE/runlog.drive.json` and `STATE/chrome_queue.drive.json` (skip what does not exist yet), then `python3 "$S/runlog.py" merge "$STATE/runlog.drive.json" --state "$STATE"` and `python3 "$S/chrome_queue.py" merge "$STATE/chrome_queue.drive.json" --state "$STATE"`, and upload both files back.
2. **Environment:** `python3 "$S/ensure_env.py" --json` (a fresh cloud machine installs what is missing; a warm one returns in seconds). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), finish `failed` (step 3) and stop; the watchdog re-runs the digest (`rerun`).
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = sent without the Doc or thumbnails; `failed` = stopped), then merge and upload as in step 1. Lost the id: `--task digest`.

## 1. Gather the data

1. Export the plan Sheet (brand.json `drive.plan_sheet`): this month's tab and, near a month's end, next month's, through the Google Sheets connector, header row included, to `STATE/digest/plan_rows.csv`. The columns are the plan Sheet's (Day, Date, Title, Goal, Template, Hook (first 2 seconds), Voiceover script, Shot list, Music mood + BPM, Call to action, Status, Folder link, Reel link).
2. `STATE/digest_notes.json` holds the week's `changes` (plan-month re-weights, dashboard-refresh "Do more of / Do less of") and `heads_ups` (night-check swaps and substitutes, Scout finds, trend-check picks, skips and reschedules). Missing file: start it as `{"changes": [], "heads_ups": []}`.
3. Run the deterministic builder:
   ```
   python3 "$S/digest_data.py" --metrics "$STATE/metrics.json" --plan-rows "$STATE/digest/plan_rows.csv" --ledger "$STATE/credit_ledger" --notes "$STATE/digest_notes.json" --today <DAY> --out "$STATE/digest/digest_<DAY>.json" --text "$STATE/digest/digest_<DAY>.txt"
   ```
   It returns the numbers and a plain-text draft; `needs_director` lists the parts only you can write.
4. **Run health for the week (R341)** and the Chrome steps that ran out of time:
   ```
   python3 "$S/runlog.py" summary --week --state "$STATE" --json
   python3 "$S/chrome_queue.py" list --status expired --state "$STATE" --json
   ```
   `line` is the week's run health; the expired items (their `expired_at` within the last 7 days) are the Chrome steps whose fallback ran.

## 2. Write the six sections (R239)

| # | Section | Content |
|---|---|---|
| 1 | Last week | Each reel: thumbnail (metrics tag `thumbnail`, else the reel's `_cover.jpg` in `Finished/`), link, views, average watch time, sends. Then the best one and **why you think it worked**, in one sentence, from its tags and the signals digest_data gives (hook type, length, series, retention vs NUMA's median). |
| 2 | What changed | The `changes` list: what you changed because of last week's results ("Shorter hooks on education reels", "Moved offers to Thursday"). |
| 3 | This week | The schedule, day by day: weekday, title, goal; "no filming needed" days marked. |
| 4 | This week's shoot list | The batched list by room (plunge room, sauna, class studio, front of house, outside), then time of day, with the total time estimate and the voiceovers to read back to back (one file per day, named by day number). |
| 5 | Budget | Higgsfield credits used and left this month (and whether spending is on pace, config `budget.pacing`); Claude usage on track or not (on track unless a run this week hit a usage limit or was cut short; say which). |
| 6 | Heads-ups | Days swapped, material the Scout found, anything skipped and why. Chrome steps that ran their fallback ("Thursday's Trial Reel went out as a normal reel"). Last, one plain line of run health from `summary` (healthy: "All 23 scheduled runs this week finished."; otherwise what happened and that it is handled: "Tuesday's reel was built late and still posted; nothing for you to do."). |

Rules: plain sentences, no jargon, no questions, nothing for Katie to decide. A section with no data says so in one line ("No reels posted last week."). Run `python3 "$S/claims_scan.py" --file "$STATE/digest/digest_<DAY>.txt"` on the final text; reword any hit.

## 3. Save and send (R238)

1. Create a Google Doc named `NUMA Digest - week of <Mon date>` in Drive brand.json `drive.digests` (`_Plan/Digests/`) with the six sections, thumbnails as images and links as links. Read it back once and LOOK: it fits a phone, numbered sections, nothing cut off.
2. Send it: brand.json `posting.digest_destination.value` is an email address and the Gmail connector is connected: email the digest text with the Doc link (when the connector can only draft, create the draft and rely on the notification). Otherwise the run's final message is the digest text with the Doc link; the scheduled task's notification carries it to her phone.
3. **Jude-only footer:** when `summary` has problems, the full `line` and each problem go to the escalation channel in `STATE/brand.json` (DECISIONS D19; when that is the `STATE/escalations.md` file, as its footer), never into Katie's text.
4. Archive the notes: move `STATE/digest_notes.json` to `STATE/digest/notes_<DAY>.json` and start a fresh one, so next week's digest only carries new items. Upload `STATE/digest/` to Drive `drive.plan_dir`.

## Example (shortened)

```
NUMA MONDAY DIGEST · week of Dec 14
1. LAST WEEK
- Your first plunge: 2,140 views, 14.2 s avg watch, 38 sends · <link>
- Box breathing at your desk: 1,020 views, 21.0 s avg watch, 12 sends · <link>
Best: Your first plunge. The first-timer hook kept 62% watching to the end, NUMA's best yet.
2. WHAT CHANGED
- Education hooks now 6 words or fewer.
3. THIS WEEK
- Mon Dec 14: Sauna vs infrared (education)
- Tue Dec 15: Carousel from Monday · no filming needed
4. SHOOT LIST · about 25 min
PLUNGE ROOM (~9 min) ... SAUNA (~7 min) ... Voiceovers back to back: Day 14, 16, 17, 18
5. BUDGET
- Higgsfield: 410 credits used, 790 left this month · on pace. Claude usage on track.
6. HEADS-UPS
- Day 10 used the library's plunge shot; the folder had none.
```

## Done means

The Doc is in `_Plan/Digests/` with the week's run health, the notification or email is sent, the notes are archived, and the run is finished in the run log. Nobody was asked anything.
