---
description: Daily dashboard refresh (10 pm) - pull due Instagram insights through Composio (Stories at 12 h and 22 h, every other post at 48 h to 30 d), store them, run the Strategist's learning refresh, rebuild and republish the performance dashboard artifact, mirror it to the metrics Sheet, write the "Do more of / Do less of" and re-check posts staged for approval; `stories` = the light midday Story pull and approval re-check
argument-hint: "[YYYY-MM-DD] | stories (empty = today, Central time; stories = the 12:40 pm Story task)"
model: opus
---
# /dashboard-refresh: the performance loop

You are Numa's **Director**. This runs from the `dashboard_refresh` scheduled task (config `schedule.tasks`, daily 10 pm, `schedule.timezone`). No questions, no waiting; a failed pull is retried the next night (a Story pull by the next Story pull run, while the Story is under 24 h old).

**`stories` (the 12:40 pm Story task, config `schedule.extra_tasks` `story_pulls`).** A light run that exists only so every Story is pulled inside its 12-22 h window (docs/SCHEDULED_TASKS.md "Story capture timing"). Do "Run start and end" with `runlog.py start story_pulls` (and `--task story_pulls`), section 2 for the due items whose `post_type` is `story` only, upload `metrics.json` and `insights/`, then section 7 (approvals). Skip sections 1, 3-6 and the strategist. Its final message is one log line ("Story pulls: 2 stored; 1 post staged for approval"), never a question; the approver line goes by the approval channel (commands/post-reel.md section 13 step 4).

Paths: `S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`, `STATE` = `~/NUMA Studio/_Plan` (sync `metrics.json`, `dashboard_notes.json` and `competitors_*.json` from Drive `drive.plan_dir` first). `STORE` = `STATE/metrics.json`.

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## Run start and end (R339-R342)

1. **Log the start (R340).** Download the Drive folder `drive.plan_dir`/`runlog/` (every file) into `STATE/runlog.drive/` and run `python3 "$S/runlog.py" merge-dir "$STATE/runlog.drive" --state "$STATE"`. Then `python3 "$S/runlog.py" start dashboard_refresh --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/` (a file only this run ever writes, so no other run's record is overwritten). Download the Drive folder `drive.plan_dir`/`chrome_queue/` (one file per queued item) into `STATE/chrome_queue.drive/` and run `python3 "$S/chrome_queue.py" merge-dir "$STATE/chrome_queue.drive" --state "$STATE"`. **A failed download is never "absent":** merge only after a download that worked, or when Drive confirms a folder does not exist yet (then start from an empty `STATE/runlog.drive/` or `STATE/chrome_queue.drive/`). When the Drive connector fails, upload only this run's own `runlog/<RUN_ID>.json` and upload no queue items this run.
2. **Environment:** `python3 "$S/ensure_env.py" --json` (a fresh cloud machine installs what is missing; a warm one returns in seconds). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), still run the watchdog (section 6; runlog.py needs no packages), finish `failed` (step 3) and stop; tonight's pulls stay due.
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = done with something left out; `failed` = stopped), then upload `STATE/runlog/<RUN_ID>.json` again (and `STATE/runlog/reported-<RUN_ID>.json` when the watchdog wrote one). Upload to Drive `_Plan/chrome_queue/` exactly the item files that this run's `chrome_queue.py` calls listed under `files` (`--json`), never the whole folder (only after the step 1 download worked). Lost the id: `--task dashboard_refresh`.

## 1. Tag newly posted posts

/post-reel tags every post the moment it publishes (its section 7 step 3). As a safety net, for each plan Sheet row with Status `Posted` whose post is not in the store yet, write its Numa tags (config `instagram.tags`) from the staged record `STATE/staged/<SLUG>.json` `tags` (else the job's `work/plan.json` `meta`, `work/script.json` and `work/delivered.json`) into `STATE/insights/tags_<media_id>.json`: length, series, pillar, hook_type, transitions, music_source, posting_time in Central ISO, trial_reel, collab, boosted, `post_type` (reel, trial_reel, carousel, image or story), the strategy tags `pattern_ids`, `strategy_arm` and `story_frames` copied unchanged, plus title, slug, media_id, permalink, thumbnail. Then:
```
python3 "$S/metrics.py" tag --store "$STATE/metrics.json" --post <media_id> --tags "$STATE/insights/tags_<media_id>.json"
```

## 2. Pull what is due

```
python3 "$S/metrics.py" due --store "$STATE/metrics.json" --json
```
Pull whatever `metrics.py due` lists: Stories at `12h` and `22h` (they must be pulled before 24 h: Instagram drops a Story's insights when it expires), every other post at `48h`, `72h`, `7d`, `14d` and `30d` (config `instagram.insight_pulls_hours`). `pull_now` is the label to store (a post caught late gets its latest due label; strategy.py judges by the real age, `pulled_at` minus posting time). For each due post call Composio's `instagram.tools.media_insights` (INSTAGRAM_GET_IG_MEDIA_INSIGHTS) for its media id with:
- `graph_api_version` = config `instagram.graph_api_version` on **every** call (Composio's default version is retired; config `instagram.graph_api_version_rule`);
- metrics, as Graph API metric names (mapped to store names by metrics.py): views, reach, likes, comments, saved, shares, reposts, total_interactions, and for reels only ig_reels_avg_watch_time and reels_skip_rate (config `instagram.metrics`; carousels and photos have no watch time or skip rate; Stories take views, reach, shares, replies and navigation as the API offers them). **Never request plays or impressions** (config `instagram.never_request`); metrics.py rejects them.

Save each response as `STATE/insights/<media_id>_<LABEL>.json` and store it with the time of the pull:
```
python3 "$S/metrics.py" ingest --store "$STATE/metrics.json" --post <media_id> --pull <LABEL> --data "$STATE/insights/<media_id>_<LABEL>.json" --pulled-at <now, Central ISO>
```
(the contract form: `metrics.py ingest --store STORE --post ID --pull LABEL --data INSIGHTS_JSON --pulled-at ISO`).
Then the account insights once a day with `instagram.tools.user_insights` (INSTAGRAM_GET_USER_INSIGHTS, same `graph_api_version`), saved and stored with `python3 "$S/metrics.py" account --store "$STATE/metrics.json" --data "$STATE/insights/account_<DAY>.json" --date <DAY>` (Meta keeps account data only 90 days; the store keeps it for good).

Errors: Meta error 190 (token invalid) goes to brand.json `escalation.contact` as one line ("NUMA Studio: Instagram disconnected (Meta error 190). Fix: in the Composio dashboard, open the Instagram toolkit and reconnect Numa's Instagram (Business or Creator, Instagram Login).") and the dashboard is rebuilt from stored data; Composio unreachable: skip the pulls tonight (failure row F15), they stay due.

## 3. Compute and rebuild

```
python3 "$S/metrics.py" compute --store "$STATE/metrics.json"
python3 "$S/metrics.py" validate --store "$STATE/metrics.json"
python3 "$S/dashboard.py" "$STATE/metrics.json" "$STATE/dashboard.html" --notes "$STATE/dashboard_notes.json" --competitors "$STATE/competitors_<YYYY-MM>.json" --today <DAY>
```
Drop `--competitors` when this month's log does not exist yet. Open `dashboard.html` and LOOK: the leaderboard lists the newest reels, numbers are not blank.

## 4. Republish and mirror (DECISIONS D7)

1. **Artifact:** republish `STATE/dashboard.html` to the same dashboard artifact every time (its link is in `STATE/dashboard_artifact.json`; the first run creates the artifact and saves the link there), so the link Katie and Jude keep never changes.
2. **Sheet mirror:** update the "NUMA Reel Metrics" Google Sheet (brand.json `drive.metrics_sheet`), one row per post: post, title, post type, posted, series, pillar, length, hook type, views, reach, average watch time (s), sends, saves, retention, sends per 1,000 reach, saves per 1,000 reach, skip rate vs median, latest pull. Rewrite the rows from the store; never append duplicates.
3. Upload `metrics.json`, `insights/` and `dashboard.html` to Drive `drive.plan_dir`.

## 5. The Strategist's refresh, then "Do more of / Do less of" (R348, R350; DECISIONS D24)

After the pulls are stored and computed, send the **strategist** (agents/strategist.md) with job `refresh`: it runs `strategy.py learn` (statuses, the dated changelog in `STATE/strategy_changes.txt`, Do more / Do less), `strategy.py diagnose` and `strategy.py brief` for this week (`STATE/strategy_brief.json` + `.md`, with which posts are still provisional), and hands back a headline. Strategist not available (tools not visible): run the three commands of its section 1 yourself. The math is strategy.py's; never re-judge a post by hand. Upload `strategy.json`, `strategy_changes.txt` and the brief to Drive `drive.plan_dir`.

Then write `STATE/dashboard_notes.json` from the brief's lines (no new numbers of your own):
```json
{"week_of": "2026-12-14", "do_more": ["First-timer hooks: 2x Numa's median sends"], "do_less": ["Openers without movement: skip rate 9 points over median"]}
```
Rebuild the dashboard with it (section 3). On Saturday's run (or when `week_of` is more than 7 days old) also add the items that change how you plan or edit to `STATE/digest_notes.json` `changes`. Under 30 judged posts, put "early signal" in front; the Strategist re-weights the next month in /plan-month.

## 6. Watchdog (R341)

The second check of the day (the night check ran the first at 8 pm). Run commands/night-check.md section 6, except the Chrome queue expiry (only the night check expires): `python3 "$S/runlog.py" check --state "$STATE" --json --mark-reported <RUN_ID>`, act on every problem with `"new": true` by its `action` (`late_build`, `reschedule`, `rerun`, `skip`), and send **Jude one line** through the escalation channel in `STATE/brand.json` (DECISIONS D19). A night check missed at 8 pm shows here as `rerun`: run commands/night-check.md for tomorrow now, before the 5 am build. **Katie gets nothing** from the watchdog. No new problems: no line.

## 7. Approval re-check (DECISIONS D26)

Run commands/post-reel.md section 13 (`approvals`): a staged post whose plan row now reads Approved posts at its planned time, or at the next slot when that time has passed (for most posts that is tomorrow's slot at this hour); every post still waiting goes on the approver's one batched line (this run's final message plus the approval channel). Never posts an unapproved row; asks nobody anything.

## Done means

Due pulls are stored (Stories inside 24 h; or left due with the reason logged), the strategist's refresh ran and the brief is current, the dashboard artifact and metrics Sheet show tonight's data, the Do more / Do less box is current, approved posts are scheduled or posted and waiting ones are on the approver's line, the watchdog ran and the run is finished in the run log.
