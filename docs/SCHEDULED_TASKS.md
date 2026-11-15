# NUMA Studio scheduled tasks

After setup Katie types no commands: scheduled tasks run the whole system (spec p.13-14, p.50). The times and cron lines are config/studio.json `schedule` (timezone `America/Chicago`, Central); this page is what Jude pastes when creating them. Each task runs one plugin command; the command file holds the full procedure.

## Cloud or desktop: where a task runs

| | Cloud scheduled task | Desktop (local) scheduled task |
|---|---|---|
| Where it runs | On Anthropic's servers, on a fresh machine every time | On Katie's Mac, inside the Claude desktop app |
| Runs when | Always, at its time, with the Mac asleep or off | Only while the Mac is awake and the app is open; asleep = skipped |
| Has | Drive, Sheets, Docs, Gmail, Higgsfield, Composio, web search | The same, plus **Claude in Chrome** (the signed-in Chrome profile) |
| Starts with | An empty machine: `ensure_env.py` installs the packages, the speech model and Chromium when missing; state comes from Drive `_Plan/` | A ready machine (setup installed everything); `ensure_env.py` returns in seconds |

Eight tasks are cloud tasks, so the daily post is built, checked and staged with the Mac off. **Nothing goes out without a person approving it** (DECISIONS D26): a staged post is published only after it is marked Approved on its plan Sheet row; unapproved posts stay staged and the digest lists them. The night check, the dashboard refresh, the midday Story task and the Chrome queue task each re-check the staged rows (commands/post-reel.md section 13): an approved post is scheduled once (one `publish_at` and one designated `publisher`) and goes out at its planned time, or at the next slot when that time has passed. Only its designated publisher may publish it: its own one-time task (`/post-reel approvals as publisher task:<slug>@<time>`), or, when no one-time task could be created, that day's 8 pm night check (the guaranteed publish slot), or the Chrome queue task for a post that needs Chrome. Every other run only reads it, so no two runs ever race; a publisher that clearly failed is reassigned to the next night check by the 8 pm or 10 pm run, which never publishes it itself. Nothing posts before noon (config `approval.earliest_post_time`; the build runs at 5 am and a person approves after it). The approver gets one batched line per run listing the posts newly waiting, never one per post. Only Claude in Chrome needs the Mac (spec p.15), so the steps that need it are queued in `_Plan/chrome_queue.json` with a deadline and a fallback (R342): signed-in research, the competitor log and Higgsfield unlimited drafts, and, for an approved post only, its Trial Reel, collab invite or AI label. The ninth task, **Chrome queue**, is a desktop task that does them whenever the Mac is awake. A step whose deadline passes runs its fallback, and **no fallback ever publishes**: research keeps its web-search version, an approved post that needed Chrome stays staged and its approver gets one line. The digest notes it; nothing ever waits for the Mac.

## The nine tasks

| # | Task (name to use) | When (Central) | Cron (Central) | Command | Where | Needs Katie's Mac on? | Notifications |
|---|---|---|---|---|---|---|---|
| 1 | Plan next month | The 24th of each month, 9 pm | `CRON_TZ=America/Chicago 0 21 24 * *` | `/plan-month` | Cloud | No (signed-in research is queued for the Mac; web search meanwhile) | On |
| 2 | Tomorrow's material check + Scout | Daily, 8 pm | `CRON_TZ=America/Chicago 0 20 * * *` | `/night-check` | Cloud | No (same) | On (the heads-up) |
| 3 | Build today's reel and outputs | Daily, 5 am | `CRON_TZ=America/Chicago 0 5 * * *` | `/build-today` | Cloud | No | On (the delivery note and the approval line to the owners' phones) |
| 4 | Dashboard refresh | Daily, 10 pm | `CRON_TZ=America/Chicago 0 22 * * *` | `/dashboard-refresh` | Cloud | No | On |
| 5 | Weekly trend check | Fridays, 7 pm | `CRON_TZ=America/Chicago 0 19 * * 5` | `/trend-check` | Cloud | No (competitor log queued for the Mac) | On |
| 6 | Monday digest | Sundays, 6 pm | `CRON_TZ=America/Chicago 0 18 * * 0` | `/digest` | Cloud | No | On (the digest) |
| 7 | Quarterly research re-check | The 12th of Feb, May, Aug and Nov, 10 am | `CRON_TZ=America/Chicago 0 10 12 2,5,8,11 *` | (prompt only) | Cloud | No | **Off** (its line goes to Jude's channel, never Katie's phone) |
| 8 | Story insights + approval re-check | Daily, 12:40 pm | `CRON_TZ=America/Chicago 40 12 * * *` | `/dashboard-refresh stories` | Cloud | No | **Off** (a log line; the approval line goes by the approval channel) |
| 9 | Chrome queue | Hourly at :47, while the Mac is awake | `CRON_TZ=America/Chicago 47 * * * *` | `/chrome-queue` | **Desktop** | Yes, by design: it only runs when the Mac is awake | **Off** (hourly; results go to the run log and the digest) |

Use the Central cron lines (`CRON_TZ=America/Chicago`) so the tasks follow daylight saving. Where a scheduler only takes a fixed UTC cron, convert from Central (UTC-6 in winter, UTC-5 in summer) and re-enter the UTC lines at each change (the second Sunday of March and the first Sunday of November); until then every task runs an hour early or late. The watchdog itself always works in Central with the daylight-saving rules and matches a run to its slot from 2 hours before the scheduled time, so an hour-off run still counts as that day's run and is not reported as missed; it just starts at the wrong hour.

**Watchdog (R341).** Every run records its start and finish in its own file in Drive `_Plan/runlog/` (one file per run, so two runs never overwrite each other). The 8 pm night check and the 10 pm dashboard refresh run `runlog.py check`. A build missed outright (no run at all) gets one late build when it is still early enough in the day (config `schedule.runlog.late_build_by`, default 3 pm) for a person to approve and post it the same day; the late build only builds and stages. Any other missed, failed or stuck build moves the day (unless the build already moved it itself). A missed night check, plan or digest is re-run. Jude gets one line; Katie gets nothing. During the day the Chrome queue task starts the late build when the Mac is awake. The Monday digest shows the week's run health.

**Story capture timing.** Instagram keeps a Story's insights only while the Story is live, so a Story must be pulled between 12 h and 22 h after it posts, and never after 24 h (docs/research/R7; `metrics.py due` stops listing a Story at 24 h). Four runs pull due Stories: the 5 am build, the **12:40 pm Story task** (task 8), the 8 pm night check and the 10 pm dashboard refresh. The math:

- The window from 12 h to 22 h is **10 hours** wide. A Story is caught as long as no gap between two pull runs is longer than 10 hours.
- The 10 pm refresh alone (one run a day, a 24-hour gap) misses most Stories: one posted at 5 pm is 5 h old at 10 pm that day and 29 h old the next night.
- With the night check added (8 pm and 10 pm), the gap from 10 pm to 8 pm is still 22 hours: a 5 pm Story is 27 h old at 8 pm the next day, too late.
- Add the 5 am build and the longest gap is still 15 hours (5 am to 8 pm): a Story posted at 5:30 pm is 11.5 h old at 5 am (too early) and 26.5 h old at 8 pm (too late), so it is missed. That is why task 8 exists.
- **With the 12:40 pm task:** runs at 05:00, 12:40, 20:00 and 22:00 Central leave gaps of 7 h 40 min, 7 h 20 min, 2 h and 7 h. The longest, 7 h 40 min, is shorter than the 10-hour window, so every Story, whatever its posting time, gets at least one pull between 12 h and 22 h, stored as `12h` (a second, `22h`, when a run also lands between 22 h and 24 h). Examples: a Story posted at 5:30 pm is 11.5 h old at 5 am (not yet due) and is pulled at 12:40 pm (19 h 10 min); one posted at 5:00 pm is pulled at 5:00 am (12 h); one posted at 9:00 am is pulled at 10:00 pm (13 h); one posted at 10:30 pm the night before is pulled at 12:40 pm (14 h 10 min), and again at 10:00 pm (23 h 30 min) as `22h`.
- A missed Story run is `skip` for the watchdog (the next pull run catches the Story while it is under 24 h). Config: `schedule.story_pulls` and `instagram.insight_pulls_hours`.

**Mac settings.** Setup turns on **Keep computer awake** and **Run on startup** in the desktop app so the Chrome queue task runs as often as possible.

## Exact prompts to paste

Each prompt is complete on its own (a scheduled run starts from nothing): it names the plugin, says which command file to read, and works even when slash commands do not expand in a scheduled run. Paste it as the task's prompt, word for word; set notifications per the table's last column.

**1. Plan next month**
```
Run /plan-month for next month with the NUMA Studio plugin (numa-studio). If /plan-month does not expand into instructions, read commands/plan-month.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/plan-month.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start plan_month, then ensure_env.py), and always end with runlog.py finish, also when something fails. Gather the inputs, have the strategist plan the month with strategy.py plan --month before any script is written (it writes _Plan/plans/strategy_YYYY-MM.json with every post type, time and pattern), fill and check the plan with shoot_card.py, have the scriptwriter draft every post in one pass from that plan, then write the Sheet tab, the day folders and a SHOOT CARD in each. Nobody approves the plan (each post is approved before it goes out): never ask Katie anything; decide, log the decision and finish.
```

**2. Tomorrow's material check + Scout**
```
Run /night-check for tomorrow (Central time) with the NUMA Studio plugin (numa-studio). If /night-check does not expand into instructions, read commands/night-check.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/night-check.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start night_check, then ensure_env.py), and always end with runlog.py finish, also when something fails. Compare tomorrow's Drive folder with its shoot card, send the Scout for anything missing, pick a substitute or swap the topic yourself, pull the Stories that are due (metrics.py due, Stories only), re-check every staged post for approval (post-reel section 13: an approved one is scheduled once; publish only the approved posts designated to tonight's night check and due by 9 pm, after the duplicate check; reassign any whose designated publisher clearly failed to tomorrow's night check; never post an unapproved one), then run the watchdog (runlog.py check) and send Jude its one line if anything new is wrong. If anything changed for tomorrow, end with a one-line heads-up for Katie and, when posts are newly waiting, one line for the approver, both statements, never questions; the watchdog line never goes to Katie.
```

**3. Build today's reel and outputs**
```
Run /build-today for today (Central time) with the NUMA Studio plugin (numa-studio). If /build-today does not expand into instructions, read commands/build-today.md and commands/make-reel.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/build-today.md) and follow them exactly. Start with build-today's "Run start and end" steps (runlog.py start build_today, then ensure_env.py --with-model), and always end with runlog.py finish, also when something fails. First pull any Stories that are due. Then build today's planned post for its type (reel, Trial Reel, component carousel, photo carousel, single photo or Stories) from today's plan row and strategy brief slot, save it to the day's Finished/ folder, stage it for approval with post-reel, mark the plan Sheet row Ready to post, and end with the delivery note. Nothing is posted until a person approves it. Never ask Katie anything; every failure follows the failure table.
```

**4. Dashboard refresh**
```
Run /dashboard-refresh with the NUMA Studio plugin (numa-studio). If /dashboard-refresh does not expand into instructions, read commands/dashboard-refresh.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/dashboard-refresh.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start dashboard_refresh, then ensure_env.py), and always end with runlog.py finish, also when something fails. Pull whatever metrics.py due lists through Composio with graph_api_version from config/studio.json (Stories at 12h and 22h, other posts at 48h, 72h, 7d, 14d and 30d; never plays or impressions), store them with metrics.py ingest --pulled-at, have the strategist run its refresh (strategy.py learn, diagnose and brief), rebuild and republish the dashboard artifact, update the Numa Reel Metrics Sheet, write the Do more of / Do less of notes, re-check every staged post for approval (never post an unapproved one), then run the watchdog (runlog.py check) and send Jude its one line if anything new is wrong. Never ask anyone anything.
```

**5. Weekly trend check**
```
Run /trend-check with the NUMA Studio plugin (numa-studio). If /trend-check does not expand into instructions, read commands/trend-check.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/trend-check.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start trend_check, then ensure_env.py), and always end with runlog.py finish, also when something fails. Check the 7-day forecast for Mobile, AL and swap in a weather hook when one is due, have the Scout find three trend ideas (formats, hooks, editing styles, topics; never songs) with example links, and slot the winner into next week as a Trial Reel if it fits. Never ask anyone anything.
```

**6. Monday digest**
```
Run /digest with the NUMA Studio plugin (numa-studio). If /digest does not expand into instructions, read commands/digest.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/digest.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start digest, then ensure_env.py), and always end with runlog.py finish, also when something fails. Run digest_data.py (with --learned and --brief) and runlog.py summary --week, write the digest (the posts staged for approval first, the six sections with What we learned, and the week's run health) as a Google Doc in Numa Reels/_Plan/Digests/, and send it as the notification (or email when a digest address is set). The digest never asks a question.
```

**7. Quarterly research re-check**
```
NUMA Studio quarterly reminder for Jude, with the NUMA Studio plugin (numa-studio). Scripts are in the plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/skills/numa-reel-editor/scripts/runlog.py). First download the Drive folder Numa Reels/_Plan/runlog/ into "$HOME/NUMA Studio/_Plan/runlog.drive" and run python3 <scripts>/runlog.py merge-dir "$HOME/NUMA Studio/_Plan/runlog.drive" --state "$HOME/NUMA Studio/_Plan" (only after a download that worked), then python3 <scripts>/runlog.py start quarterly_research --state "$HOME/NUMA Studio/_Plan", note the run id and upload "$HOME/NUMA Studio/_Plan/runlog/<run id>.json" to Drive Numa Reels/_Plan/runlog/. Then send Jude one line through the escalation channel in _Plan/brand.json: re-run the five research prompts in docs/SETUP_GUIDE.md (Research prompts), then update config/studio.json higgsfield.prices and prices_verified_on and instagram.graph_api_version, and brand.json claims through /brand-setup. Change nothing yourself and ask nobody anything. Last, also if sending failed: runlog.py finish <run id> --outcome ok (or failed) --state "$HOME/NUMA Studio/_Plan", and upload runlog/<run id>.json to Drive Numa Reels/_Plan/runlog/ again.
```

**8. Story insights + approval re-check**
```
Run /dashboard-refresh stories with the NUMA Studio plugin (numa-studio). If /dashboard-refresh does not expand into instructions, read commands/dashboard-refresh.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/dashboard-refresh.md) and follow its stories mode exactly. Start with its "Run start and end" steps (runlog.py start story_pulls, then ensure_env.py), and always end with runlog.py finish, also when something fails. Pull only the Stories that metrics.py due lists (a Story must be pulled before 24 h), store them with metrics.py ingest --pulled-at and upload the store, then re-check every staged post for approval with post-reel section 13: an approved post goes out at its planned time or the next slot; never post an unapproved one. Never ask anyone anything; end with one log line.
```

**9. Chrome queue** (create it in the Claude desktop app on Katie's Mac as a local/desktop scheduled task, not in the cloud)
```
Run /chrome-queue with the NUMA Studio plugin (numa-studio). If /chrome-queue does not expand into instructions, read commands/chrome-queue.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/chrome-queue.md) and follow it exactly. Start with runlog.py start chrome_queue and ensure_env.py, and always end with runlog.py finish, also when something fails. Sync the Chrome queue with Drive and, when the Claude in Chrome tools answer, claim and do the queued items in deadline order (posting steps only for posts a person approved). If the watchdog reports today's build missed and a late build is still allowed, build and stage it for approval. Re-check staged posts for approval (post-reel section 13); never post anything by yourself that a person has not approved. Never ask Katie anything.
```

## So runs never stall (R264)

A scheduled run that hits a permission prompt waits forever. Before switching the schedule on (during `/numa-setup`):

1. **Approve the connector tools.** In Claude's settings, set every tool of these connectors to **Always allow**: Google Drive, Google Sheets, Google Docs (when separate from Drive), Gmail (digest email and Jude's one-line escalations), Higgsfield, Composio (Instagram insights and posting) and Claude in Chrome. Claude Code: add them to `permissions.allow` (for example `mcp__Google_Drive__*`, `mcp__Google_Sheets__*`, `mcp__Higgsfield__*`, `mcp__Composio__*`), plus `Bash(python3:*)` for the plugin scripts (ensure_env.py also runs `python3 -m pip` and `python3 -m playwright` through it).
2. **Run each task once by hand** with "Run now" and approve anything it still asks for, until all nine finish with no prompt (the Chrome queue task from the desktop app, with the Mac awake). The build task's Run now stages today's post and posts nothing: nothing goes out until a person marks it Approved.
3. **Check the run log (R343).** After the "Run now" round, `/numa-setup` step 10 runs `runlog.py check --since <time of the first Run now>`; every task must show `OK:` (or `WARN:` for a run that finished `partial`, with its note). A task with no entry did not follow its prompt's run-log steps: re-paste the prompt exactly and run it again.
4. **Notifications on** for tasks 1-6 and off for 7, 8 and 9, as the table's last column says: on for tasks 1-6, so the build's delivery note, the night check's heads-up and each run's one approval line reach the owners' phones (R263); **off** for the quarterly reminder (Jude-only), the midday Story task and the hourly Chrome queue (their approval line goes by the approval channel /numa-setup stored), so neither repeats on Katie's phone. The watchdog and every other Jude-only line go through Jude's escalation channel, never through these notifications.
5. Re-check after any connector is reconnected (a reconnect can reset its approvals). A run that still stalls is a setup problem for Jude, never a question for Katie.

**Fresh cloud machines.** A cloud run starts with nothing installed, so its first minutes go to `ensure_env.py` (pip install, the speech model for the build, Chromium on component-carousel days). That is expected. Where the cloud environment offers a setup script, `pip install -r requirements.txt` there makes every run start warm.

## Check the table against config

`config/studio.json` `schedule.tasks` holds the same six cloud rows (id, name, when, cron, command); `tests/unit/test_instructions_month.py` fails if this page and the config disagree or a command file is missing. Tasks 7, 8 and 9 are `schedule.extra_tasks` (task 9 with `"where": "desktop"`), which the run log's watchdog reads; a desktop task is never reported as missed, and a missed Story task is `skip` (the next pull run catches the Story while it is under 24 h).
