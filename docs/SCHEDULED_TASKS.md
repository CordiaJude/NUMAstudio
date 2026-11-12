# NUMA Studio scheduled tasks

After setup Katie types no commands: six scheduled tasks run the whole system (spec p.13-14, p.50). The times and cron lines are config/studio.json `schedule` (timezone `America/Chicago`, Central); this page is what Jude pastes when creating them. Each task runs one plugin command; the command file holds the full procedure.

## The six tasks

| # | Task (name to use) | When (Central) | Cron (Central) | Command | Needs Katie's Mac on? |
|---|---|---|---|---|---|
| 1 | Plan next month | The 24th of each month, 9 pm | `CRON_TZ=America/Chicago 0 21 24 * *` | `/plan-month` | No (the Scout's Chrome research is used when the Mac is awake; else web search) |
| 2 | Tomorrow's material check + Scout | Daily, 8 pm | `CRON_TZ=America/Chicago 0 20 * * *` | `/night-check` | No (same Scout note) |
| 3 | Build today's reel and outputs | Daily, 5 am | `CRON_TZ=America/Chicago 0 5 * * *` | `/build-today` | No |
| 4 | Dashboard refresh | Daily, 10 pm | `CRON_TZ=America/Chicago 0 22 * * *` | `/dashboard-refresh` | No |
| 5 | Weekly trend check | Fridays, 7 pm | `CRON_TZ=America/Chicago 0 19 * * 5` | `/trend-check` | No (same Scout note) |
| 6 | Monday digest | Sundays, 6 pm | `CRON_TZ=America/Chicago 0 18 * * 0` | `/digest` | No |

Where the scheduler only takes UTC, convert from Central and re-check at the daylight-saving changes (Central is UTC-6 in winter, UTC-5 in summer).

**Needs-Mac note (the Scout).** Every task runs as a cloud scheduled task, so the daily reel always ships with the Mac asleep. Only the Scout's Claude in Chrome needs the desktop app open on Katie's Mac (spec p.15). When it is not, the Scout uses cloud web search and fetch, then the media library, then the bundled brand photos (failure row F17). Setup turns on **Keep computer awake** and **Run on startup** in the desktop app so Chrome is available as often as possible.

## Exact prompts to paste

Each prompt is complete on its own (a scheduled run starts from nothing) and names the command. Paste it as the task's prompt; set notifications on for every task.

**1. Plan next month**
```
Run /plan-month for next month (the NUMA Studio plugin). Follow commands/plan-month.md exactly: gather the inputs, re-weight from last month's results, fill and check the plan with shoot_card.py, have the scriptwriter draft every shoot card in one pass, then write the Sheet tab, the day folders and a SHOOT CARD in each. Nobody approves the plan: never ask Katie anything; decide, log the decision and finish.
```

**2. Tomorrow's material check + Scout**
```
Run /night-check for tomorrow (Central time) with the NUMA Studio plugin. Follow commands/night-check.md exactly: compare tomorrow's Drive folder with its shoot card, send the Scout for anything missing, then pick a substitute or swap the topic yourself. If anything changed, end with a one-line heads-up for Katie that is a statement, never a question.
```

**3. Build today's reel and outputs**
```
Run /build-today for today (Central time) with the NUMA Studio plugin. Follow commands/build-today.md and commands/make-reel.md exactly: build today's planned reel (or carousel or Stories) and every output, save them to the day's Finished/ folder, mark the plan Sheet row, and end with the delivery note. Never ask Katie anything; every failure follows the failure table.
```

**4. Dashboard refresh**
```
Run /dashboard-refresh with the NUMA Studio plugin. Follow commands/dashboard-refresh.md exactly: pull the due Instagram insights through Composio with graph_api_version from config/studio.json (never plays or impressions), store them with metrics.py, rebuild and republish the dashboard artifact, update the NUMA Reel Metrics Sheet, and on Saturdays write the Do more of / Do less of notes.
```

**5. Weekly trend check**
```
Run /trend-check with the NUMA Studio plugin. Follow commands/trend-check.md exactly: check the 7-day forecast for Mobile, AL and swap in a weather hook when one is due, have the Scout find three trend ideas (formats, hooks, editing styles, topics; never songs) with example links, and slot the winner into next week as a Trial Reel if it fits. Never ask anyone anything.
```

**6. Monday digest**
```
Run /digest with the NUMA Studio plugin. Follow commands/digest.md exactly: run digest_data.py, write the six-section digest as a Google Doc in NUMA Reels/_Plan/Digests/, and send it as the notification (or email when a digest address is set). The digest never asks a question.
```

## So runs never stall (R264)

A scheduled run that hits a permission prompt waits forever. Before switching the schedule on (during `/numa-setup`):

1. **Approve the connector tools.** In Claude's settings, set every tool of these connectors to **Always allow**: Google Drive, Google Sheets, Google Docs (when separate from Drive), Gmail (digest email and Jude's one-line escalations), Higgsfield, Composio (Instagram insights and posting) and Claude in Chrome. Claude Code: add them to `permissions.allow` (for example `mcp__Google_Drive__*`, `mcp__Google_Sheets__*`, `mcp__Higgsfield__*`, `mcp__Composio__*`), plus `Bash(python3:*)` for the plugin scripts.
2. **Run each task once by hand** with "Run now" and approve anything it still asks for, until all six finish with no prompt.
3. **Notifications on** for every task, so the build's delivery note and the night check's heads-up reach Katie's phone (R263).
4. Re-check after any connector is reconnected (a reconnect can reset its approvals). A run that still stalls is a setup problem for Jude, never a question for Katie.

## Check the table against config

`config/studio.json` `schedule.tasks` holds the same six rows (id, name, when, cron, command); `tests/unit/test_instructions_month.py` fails if this page and the config disagree or a command file is missing.
