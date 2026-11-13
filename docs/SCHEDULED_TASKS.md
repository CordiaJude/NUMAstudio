# NUMA Studio scheduled tasks

After setup Katie types no commands: scheduled tasks run the whole system (spec p.13-14, p.50). The times and cron lines are config/studio.json `schedule` (timezone `America/Chicago`, Central); this page is what Jude pastes when creating them. Each task runs one plugin command; the command file holds the full procedure.

## Cloud or desktop: where a task runs

| | Cloud scheduled task | Desktop (local) scheduled task |
|---|---|---|
| Where it runs | On Anthropic's servers, on a fresh machine every time | On Katie's Mac, inside the Claude desktop app |
| Runs when | Always, at its time, with the Mac asleep or off | Only while the Mac is awake and the app is open; asleep = skipped |
| Has | Drive, Sheets, Docs, Gmail, Higgsfield, Composio, web search | The same, plus **Claude in Chrome** (the signed-in Chrome profile) |
| Starts with | An empty machine: `ensure_env.py` installs the packages, the speech model and Chromium when missing; state comes from Drive `_Plan/` | A ready machine (setup installed everything); `ensure_env.py` returns in seconds |

Seven tasks are cloud tasks, so the daily reel ships with the Mac off. Only Claude in Chrome needs the Mac (spec p.15), so the steps that need it are queued in `_Plan/chrome_queue.json` with a deadline and a fallback (R342), and the eighth task, **Chrome queue**, is a desktop task that does them whenever the Mac is awake. A step whose deadline passes runs its fallback (a Trial Reel posts as a normal reel, the competitor log keeps its web-search version) and the digest notes it; nothing ever waits for the Mac.

## The eight tasks

| # | Task (name to use) | When (Central) | Cron (Central) | Command | Where | Needs Katie's Mac on? |
|---|---|---|---|---|---|---|
| 1 | Plan next month | The 24th of each month, 9 pm | `CRON_TZ=America/Chicago 0 21 24 * *` | `/plan-month` | Cloud | No (signed-in research is queued for the Mac; web search meanwhile) |
| 2 | Tomorrow's material check + Scout | Daily, 8 pm | `CRON_TZ=America/Chicago 0 20 * * *` | `/night-check` | Cloud | No (same) |
| 3 | Build today's reel and outputs | Daily, 5 am | `CRON_TZ=America/Chicago 0 5 * * *` | `/build-today` | Cloud | No |
| 4 | Dashboard refresh | Daily, 10 pm | `CRON_TZ=America/Chicago 0 22 * * *` | `/dashboard-refresh` | Cloud | No |
| 5 | Weekly trend check | Fridays, 7 pm | `CRON_TZ=America/Chicago 0 19 * * 5` | `/trend-check` | Cloud | No (competitor log queued for the Mac) |
| 6 | Monday digest | Sundays, 6 pm | `CRON_TZ=America/Chicago 0 18 * * 0` | `/digest` | Cloud | No |
| 7 | Quarterly research re-check | The 12th of Feb, May, Aug and Nov, 10 am | `CRON_TZ=America/Chicago 0 10 12 2,5,8,11 *` | (prompt only) | Cloud | No |
| 8 | Chrome queue | Hourly at :47, while the Mac is awake | `CRON_TZ=America/Chicago 47 * * * *` | `/chrome-queue` | **Desktop** | Yes, by design: it only runs when the Mac is awake |

Where the scheduler only takes UTC, convert from Central and re-check at the daylight-saving changes (Central is UTC-6 in winter, UTC-5 in summer). The run log's watchdog evaluates every cron in Central with the daylight-saving rules, so it is never an hour off.

**Watchdog (R341).** Every run records its start and finish in `_Plan/runlog.json`. The 8 pm night check and the 10 pm dashboard refresh run `runlog.py check`: a missed or failed build gets a late build when it can still post the same day, otherwise the day is rescheduled; a missed night check, plan or digest is re-run; Jude gets one line, Katie gets nothing. During the day the Chrome queue task starts the late build when the Mac is awake. The Monday digest shows the week's run health.

**Mac settings.** Setup turns on **Keep computer awake** and **Run on startup** in the desktop app so the Chrome queue task runs as often as possible.

## Exact prompts to paste

Each prompt is complete on its own (a scheduled run starts from nothing): it names the plugin, says which command file to read, and works even when slash commands do not expand in a scheduled run. Paste it as the task's prompt, word for word; set notifications on for every task.

**1. Plan next month**
```
Run /plan-month for next month with the NUMA Studio plugin (numa-studio). If /plan-month does not expand into instructions, read commands/plan-month.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/plan-month.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start plan_month, then ensure_env.py), and always end with runlog.py finish, also when something fails. Gather the inputs, re-weight from last month's results, fill and check the plan with shoot_card.py, have the scriptwriter draft every shoot card in one pass, then write the Sheet tab, the day folders and a SHOOT CARD in each. Nobody approves the plan: never ask Katie anything; decide, log the decision and finish.
```

**2. Tomorrow's material check + Scout**
```
Run /night-check for tomorrow (Central time) with the NUMA Studio plugin (numa-studio). If /night-check does not expand into instructions, read commands/night-check.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/night-check.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start night_check, then ensure_env.py), and always end with runlog.py finish, also when something fails. Compare tomorrow's Drive folder with its shoot card, send the Scout for anything missing, pick a substitute or swap the topic yourself, then run the watchdog (runlog.py check) and send Jude its one line if anything new is wrong. If anything changed for tomorrow, end with a one-line heads-up for Katie that is a statement, never a question; the watchdog line never goes to Katie.
```

**3. Build today's reel and outputs**
```
Run /build-today for today (Central time) with the NUMA Studio plugin (numa-studio). If /build-today does not expand into instructions, read commands/build-today.md and commands/make-reel.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/build-today.md) and follow them exactly. Start with build-today's "Run start and end" steps (runlog.py start build_today, then ensure_env.py --with-model), and always end with runlog.py finish, also when something fails. Build today's planned reel (or carousel or Stories) and every output, save them to the day's Finished/ folder, mark the plan Sheet row, and end with the delivery note. Never ask Katie anything; every failure follows the failure table.
```

**4. Dashboard refresh**
```
Run /dashboard-refresh with the NUMA Studio plugin (numa-studio). If /dashboard-refresh does not expand into instructions, read commands/dashboard-refresh.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/dashboard-refresh.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start dashboard_refresh, then ensure_env.py), and always end with runlog.py finish, also when something fails. Pull the due Instagram insights through Composio with graph_api_version from config/studio.json (never plays or impressions), store them with metrics.py, rebuild and republish the dashboard artifact, update the NUMA Reel Metrics Sheet, on Saturdays write the Do more of / Do less of notes, then run the watchdog (runlog.py check) and send Jude its one line if anything new is wrong. Never ask anyone anything.
```

**5. Weekly trend check**
```
Run /trend-check with the NUMA Studio plugin (numa-studio). If /trend-check does not expand into instructions, read commands/trend-check.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/trend-check.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start trend_check, then ensure_env.py), and always end with runlog.py finish, also when something fails. Check the 7-day forecast for Mobile, AL and swap in a weather hook when one is due, have the Scout find three trend ideas (formats, hooks, editing styles, topics; never songs) with example links, and slot the winner into next week as a Trial Reel if it fits. Never ask anyone anything.
```

**6. Monday digest**
```
Run /digest with the NUMA Studio plugin (numa-studio). If /digest does not expand into instructions, read commands/digest.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/digest.md) and follow it exactly. Start with its "Run start and end" steps (runlog.py start digest, then ensure_env.py), and always end with runlog.py finish, also when something fails. Run digest_data.py and runlog.py summary --week, write the six-section digest (with the week's run health) as a Google Doc in NUMA Reels/_Plan/Digests/, and send it as the notification (or email when a digest address is set). The digest never asks a question.
```

**7. Quarterly research re-check**
```
NUMA Studio quarterly reminder for Jude, with the NUMA Studio plugin (numa-studio). Scripts are in the plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/skills/numa-reel-editor/scripts/runlog.py). First run: python3 <scripts>/runlog.py start quarterly_research --state "$HOME/NUMA Studio/_Plan" after merging Drive NUMA Reels/_Plan/runlog.json into it (runlog.py merge), and note the run id. Then send Jude one line through the escalation channel in _Plan/brand.json: re-run the five research prompts in docs/SETUP_GUIDE.md (Research prompts), then update config/studio.json higgsfield.prices and prices_verified_on and instagram.graph_api_version, and brand.json claims through /brand-setup. Change nothing yourself and ask nobody anything. Last, also if sending failed: runlog.py finish <run id> --outcome ok (or failed) --state "$HOME/NUMA Studio/_Plan", and upload runlog.json back to Drive NUMA Reels/_Plan/.
```

**8. Chrome queue** (create it in the Claude desktop app on Katie's Mac as a local/desktop scheduled task, not in the cloud)
```
Run /chrome-queue with the NUMA Studio plugin (numa-studio). If /chrome-queue does not expand into instructions, read commands/chrome-queue.md in the numa-studio plugin folder (${CLAUDE_PLUGIN_ROOT}; else search the disk for numa-studio/commands/chrome-queue.md) and follow it exactly. Start with runlog.py start chrome_queue and ensure_env.py, and always end with runlog.py finish, also when something fails. Sync the Chrome queue with Drive, run the fallback of every item past its deadline, and when the Claude in Chrome tools answer, do the queued items in deadline order; start a late build if the watchdog says today's reel can still post. Never ask Katie anything.
```

## So runs never stall (R264)

A scheduled run that hits a permission prompt waits forever. Before switching the schedule on (during `/numa-setup`):

1. **Approve the connector tools.** In Claude's settings, set every tool of these connectors to **Always allow**: Google Drive, Google Sheets, Google Docs (when separate from Drive), Gmail (digest email and Jude's one-line escalations), Higgsfield, Composio (Instagram insights and posting) and Claude in Chrome. Claude Code: add them to `permissions.allow` (for example `mcp__Google_Drive__*`, `mcp__Google_Sheets__*`, `mcp__Higgsfield__*`, `mcp__Composio__*`), plus `Bash(python3:*)` for the plugin scripts (ensure_env.py also runs `python3 -m pip` and `python3 -m playwright` through it).
2. **Run each task once by hand** with "Run now" and approve anything it still asks for, until all eight finish with no prompt (the Chrome queue task from the desktop app, with the Mac awake).
3. **Check the run log (R343).** After the "Run now" round, `/numa-setup` step 10 runs `runlog.py check --since <time of the first Run now>`; every task must show `OK:`. A task with no entry did not follow its prompt's run-log steps: re-paste the prompt exactly and run it again.
4. **Notifications on** for every task, so the build's delivery note and the night check's heads-up reach Katie's phone (R263). The watchdog and every other Jude-only line go through Jude's escalation channel, never through these notifications.
5. Re-check after any connector is reconnected (a reconnect can reset its approvals). A run that still stalls is a setup problem for Jude, never a question for Katie.

**Fresh cloud machines.** A cloud run starts with nothing installed, so its first minutes go to `ensure_env.py` (pip install, the speech model for the build, Chromium on component-carousel days). That is expected. Where the cloud environment offers a setup script, `pip install -r requirements.txt` there makes every run start warm.

## Check the table against config

`config/studio.json` `schedule.tasks` holds the same six cloud rows (id, name, when, cron, command); `tests/unit/test_instructions_month.py` fails if this page and the config disagree or a command file is missing. Tasks 7 and 8 belong in `schedule.extra_tasks` (task 8 with `"where": "desktop"`), which the run log's watchdog reads; a desktop task is never reported as missed.
