---
description: Daily dashboard refresh (10 pm) - pull due Instagram insights through Composio, store them, rebuild and republish the performance dashboard artifact, mirror it to the metrics Sheet, and write the weekly "Do more of / Do less of"
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /dashboard-refresh: the performance loop

You are NUMA's **Director**. This runs from the `dashboard_refresh` scheduled task (config `schedule.tasks`, daily 10 pm, `schedule.timezone`). No questions, no waiting; a failed pull is retried the next night.

Paths: `S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`, `STATE` = `~/NUMA Studio/_Plan` (sync `metrics.json`, `dashboard_notes.json` and `competitors_*.json` from Drive `drive.plan_dir` first). `STORE` = `STATE/metrics.json`.

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## 1. Tag newly posted reels

For each plan Sheet row with Status `Posted` whose reel is not in the store yet, write its NUMA tags (config `instagram.tags`) from the job's `work/plan.json` `meta` and `work/delivered.json` into `STATE/insights/tags_<reel>.json` (length, series, pillar, hook_type, transitions, music_source, posting_time in Central ISO, trial_reel, collab, plus title, slug, media_id, permalink, thumbnail), then:
```
python3 "$S/metrics.py" tag --store "$STATE/metrics.json" --reel <media_id> --tags "$STATE/insights/tags_<reel>.json"
```

## 2. Pull what is due

```
python3 "$S/metrics.py" due --store "$STATE/metrics.json" --json
```
For each due reel and pull (48h, 72h, 7d; config `instagram.insight_pulls_hours`), call Composio's `instagram.tools.media_insights` (INSTAGRAM_GET_IG_MEDIA_INSIGHTS) for the reel's media id with:
- `graph_api_version` = config `instagram.graph_api_version` on **every** call (Composio's default version is retired; config `instagram.graph_api_version_rule`);
- metrics, as Graph API metric names (mapped to store names by metrics.py): views, reach, likes, comments, saved, shares, reposts, total_interactions, ig_reels_avg_watch_time, reels_skip_rate (config `instagram.metrics`). **Never request plays or impressions** (config `instagram.never_request`); metrics.py rejects them.

Save each response as `STATE/insights/<reel>_<pull>.json` and store it:
```
python3 "$S/metrics.py" ingest --store "$STATE/metrics.json" --reel <media_id> --pull 72h --data "$STATE/insights/<reel>_72h.json"
```
Then the account insights once a day with `instagram.tools.user_insights` (INSTAGRAM_GET_USER_INSIGHTS, same `graph_api_version`), saved and stored with `python3 "$S/metrics.py" account --store "$STATE/metrics.json" --data "$STATE/insights/account_<DAY>.json" --date <DAY>` (Meta keeps account data only 90 days; the store keeps it for good).

Errors: Meta error 190 (token invalid) goes to brand.json `escalation.contact` as one line ("NUMA Studio: Instagram disconnected (Meta error 190). Fix: in the Composio dashboard, open the Instagram toolkit and reconnect NUMA's Instagram (Business or Creator, Instagram Login).") and the dashboard is rebuilt from stored data; Composio unreachable: skip the pulls tonight (failure row F15), they stay due.

## 3. Compute and rebuild

```
python3 "$S/metrics.py" compute --store "$STATE/metrics.json"
python3 "$S/metrics.py" validate --store "$STATE/metrics.json"
python3 "$S/dashboard.py" "$STATE/metrics.json" "$STATE/dashboard.html" --notes "$STATE/dashboard_notes.json" --competitors "$STATE/competitors_<YYYY-MM>.json" --today <DAY>
```
Drop `--competitors` when this month's log does not exist yet. Open `dashboard.html` and LOOK: the leaderboard lists the newest reels, numbers are not blank.

## 4. Republish and mirror (DECISIONS D7)

1. **Artifact:** republish `STATE/dashboard.html` to the same dashboard artifact every time (its link is in `STATE/dashboard_artifact.json`; the first run creates the artifact and saves the link there), so the link Katie and Jude keep never changes.
2. **Sheet mirror:** update the "NUMA Reel Metrics" Google Sheet (brand.json `drive.metrics_sheet`), one row per reel: reel, title, posted, series, pillar, length, hook type, views, reach, average watch time (s), sends, saves, retention, sends per 1,000 reach, saves per 1,000 reach, skip rate vs median, latest pull. Rewrite the rows from the store; never append duplicates.
3. Upload `metrics.json`, `insights/` and `dashboard.html` to Drive `drive.plan_dir`.

## 5. Weekly "Do more of / Do less of" (Saturday's run)

On Saturday's run (or when `STATE/dashboard_notes.json` `week_of` is more than 7 days old), compare the reels judged at 72 h this week (config `instagram.judge_at_hours`) with NUMA's medians and write 1-3 items each:
```json
{"week_of": "2026-12-14", "do_more": ["First-timer hooks: 2x NUMA's median sends"], "do_less": ["Openers without movement: skip rate 9 points over median"]}
```
Rebuild the dashboard with it (section 3) and add the items that change how you plan or edit to `STATE/digest_notes.json` `changes`. Under 30 posted reels, write what the data shows with "early signal" in front; re-tuning waits for plan-month (rule 10).

## Done means

Due pulls are stored (or left due with the reason logged), the dashboard artifact and metrics Sheet show tonight's data, and on Saturdays the Do more / Do less box is current.
