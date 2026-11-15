---
description: Plan the next month of Numa posts on its own - research, the Strategist's allocation from last month's results (strategy.py plan), every post type (reels, Trial Reels, component and photo carousels, single photos, Stories), the plan Sheet, the day folders and a SHOOT CARD in each. Nobody approves the plan; each post is approved before it goes out.
argument-hint: "[YYYY-MM] (empty = next month)"
model: opus
---
# /plan-month: the Director plans a month

You are Numa's **Director** (`models.agents.director`, effort `models.effort.director` in config/studio.json). This runs from the `plan_month` scheduled task (config `schedule.tasks`: the 24th, 9 pm Central) or by hand. Month = `$ARGUMENTS` (YYYY-MM), else next month.

## 0. Rules

1. **Nobody approves the plan.** Never ask Katie anything and never wait for a reply. Decide, write the reason in `STATE/plans/decisions_YYYY-MM.md` (one line per decision), continue.
2. Facts come from brand/brand.json and config/studio.json by key. A value with status `needs_katie` is never stated as fact: plan around it (a reel that needs the unknown fact waits for a later month).
3. Escalations go only to brand.json `escalation.contact`, one line with the exact fix (same table as commands/make-reel.md section 0).
4. The plan is done when `shoot_card.py check` exits 0 and every folder, card and Sheet row exists.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `STUDIO` | `~/NUMA Studio` (local mirror of Drive brand.json `drive.root`) |
| `STATE` | `STUDIO/_Plan` (local copy of Drive `drive.plan_dir`; the librarian syncs it) |
| `PLAN` | `STATE/plans/plan_YYYY-MM.json` (the month plan: `shoot_card.py` MONTH_JSON) |
| `SPLAN` | `STATE/plans/strategy_YYYY-MM.json` (the Strategist's allocation from `strategy.py plan`: the same MONTH_JSON shape plus `post_type`, `post_time`, `pattern_ids`, `strategy_arm`, `strategy`; skills/numa-scriptwriter/ADAPTIVE.md) |

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## Run start and end (R339-R342)

1. **Log the start (R340).** Download the Drive folder `drive.plan_dir`/`runlog/` (every file) into `STATE/runlog.drive/` and run `python3 "$S/runlog.py" merge-dir "$STATE/runlog.drive" --state "$STATE"`. Then `python3 "$S/runlog.py" start plan_month --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/` (a file only this run ever writes, so no other run's record is overwritten). Download the Drive folder `drive.plan_dir`/`chrome_queue/` (one file per queued item) into `STATE/chrome_queue.drive/` and run `python3 "$S/chrome_queue.py" merge-dir "$STATE/chrome_queue.drive" --state "$STATE"`. **A failed download is never "absent":** merge only after a download that worked, or when Drive confirms a folder does not exist yet (then start from an empty `STATE/runlog.drive/` or `STATE/chrome_queue.drive/`). When the Drive connector fails, upload only this run's own `runlog/<RUN_ID>.json` and upload no queue items this run.
2. **Environment:** `python3 "$S/ensure_env.py" --json` (a fresh cloud machine installs what is missing; a warm one returns in seconds). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), finish `failed` (step 3) and stop; the watchdog re-runs the plan (`rerun`).
3. **Finish, always, also when the run fails or stops early:** `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok --note "<one line>" --state "$STATE"` (`ok` = "Done means" met; `partial` = done with something left out; `failed` = stopped), then upload `STATE/runlog/<RUN_ID>.json` again (and `STATE/runlog/reported-<RUN_ID>.json` when the watchdog wrote one). Upload to Drive `_Plan/chrome_queue/` exactly the item files that this run's `chrome_queue.py` calls listed under `files` (`--json`), never the whole folder (only after the step 1 download worked). Lost the id: `--task plan_month`.

## 1. Gather inputs first (R155)

Run the scout (agents/scout.md) and the data steps in parallel. Missing input: plan with what you have and log it; never wait.

| Input | Where | Save as |
|---|---|---|
| Offers and prices | brand.json `offerings.offers`; Numa's site and socials (brand.json `business.website`, `socials`) via the **scout**: Claude in Chrome when the Mac is awake, else WebSearch/WebFetch. Quote the URL for every fact. | `STATE/plans/inputs_YYYY-MM.json` `offers` |
| Class schedule and events (Numa Nights, classes; never a cancelled event such as Clinical Conversations) | brand.json `offerings.events`; the scout on Numa's site, Instagram and Facebook | `inputs` `events` [{name, date, time, url}] |
| Closures and holidays | the Closures Sheet (brand.json `closures.location`) through the Google Sheets connector, plus `closures.known`, plus US holidays in the month | `STATE/closures.json` [{date, name}] |
| Last month's results | `python3 "$S/metrics.py" compute --store "$STATE/metrics.json" --json`, then `python3 "$S/dashboard.py" "$STATE/metrics.json" "$STATE/dashboard.html" --notes "$STATE/dashboard_notes.json"` and read the "Do more of / Do less of" box | `inputs` `results` |
| Season and Mobile local moments | the table below, plus a web search for this year's dates (Mardi Gras parades, Midtown events, South Alabama home games) | `inputs` `moments` |
| Trend ideas | the newest `STATE/trends/trends_*.json` (trend-check) | `inputs` `trends` |
| Feedback memory | `python3 "$S/prefs.py" list --file "$STATE/preferences.json" --json` | honoured in every card |
| Credit budget | `python3 "$S/ledger.py" report --ledger "$STATE/credit_ledger" --month YYYY-MM --json` (a new month starts at config `budget.monthly_credits`) | `inputs` `credits` |

**Claude in Chrome (R342).** Chrome exists only while Katie's Mac is awake with the desktop app open. Before sending the scout, check that the `mcp__claude-in-chrome__*` tools are visible and answer a harmless call (read the open tab's title). Visible: drain the queue first (commands/chrome-queue.md section 3; a cloud run takes only the non-posting kinds), then the scout researches in Chrome. Not visible: the scout uses WebSearch/WebFetch now and the signed-in check is queued; the plan never waits for it:
```
python3 "$S/chrome_queue.py" add --kind scout_research --payload '{"for": "plan-month 2026-12", "what": "offers, prices and events on the Numa Instagram and Facebook pages", "save_to": "STATE/plans/inputs_2026-12.json"}' --deadline 2026-12-01T00:00:00-06:00 --fallback "The plan stands on the web-search facts" --state "$STATE" --json
```

| Months | Local moments to plan around |
|---|---|
| Dec-Feb | Cold snaps ("Sauna season in Mobile"), New Year resets, holiday closures |
| Jan-Mar | Mardi Gras season (parade dates change yearly: look them up), recovery week after Fat Tuesday |
| Jun-Nov | Hurricane season ("hurricane-season calm"), never a storm joke |
| Jun-Sep | Summer heat: Mobile tap water rarely below 70°F, so "Too Hot for a DIY Plunge" |
| Aug-Nov | University of South Alabama semester and game days; back-to-school routines |
| All year | Midtown, Dauphin St, shift workers and the 5:30 AM opening (brand.json `positioning.target_audiences`) |

## 2. The Strategist plans the month, before any script (R344-R350; DECISIONS D23, D24)

How the learning works is in [skills/numa-scriptwriter/ADAPTIVE.md](../skills/numa-scriptwriter/ADAPTIVE.md): strategy.py does the math, the Strategist decides, the Scriptwriter writes.

1. Write the events and closures you gathered: `STATE/plans/events_YYYY-MM.json` (`inputs` `events`, [{name, date}]) and `STATE/closures.json`.
2. Send the **strategist** (agents/strategist.md) with job `plan YYYY-MM`. It runs `learn` and `diagnose`, then
   ```
   python3 "$S/strategy.py" plan --month YYYY-MM --metrics "$STATE/metrics.json" --state "$STATE/strategy.json" --events "$STATE/plans/events_YYYY-MM.json" --closures "$STATE/closures.json" --out "$STATE/plans/strategy_YYYY-MM.json"
   ```
   and the brief for the month's first week. Strategist not available: run that command yourself (`strategy.py plan --month YYYY-MM`). Exit 1 (`ERROR: rule ...`): a planning rule fails even with the bandit off (usually an event on a closure day); move the event content and run it again. No metrics yet: it plans the spec's default week (cold start).
3. `SPLAN` is the month's allocation: each row's `kind` / `post_type` (reel, trial_reel, carousel, image, stories), `post_time` (Central), `pattern_ids`, `strategy_arm`, `strategy.mode` and `why`, `story_frames` on Stories rows, `partial_closures`. **Use it as the plan** (section 3): never change a row's post type, time or patterns to taste; change a row only to satisfy a planning rule, and log why. `python3 "$S/strategy.py" explain <day> --plan "$SPLAN"` says why a slot got what it got.

**Re-weighting is the Strategist's (R161, R170, R252, rule 10).** strategy.py moves the mix, post types, posting hours, cadence and patterns from Numa's own judged posts, with a data-led share of min(1, judged posts / 30), so the first months stay near the defaults below and later months follow the data. Posts are judged at 72 h first (config `instagram.judge_at_hours`), then finally at strategy.py's later pulls (R7 windows). What is still yours:

- **Under 30 judged posts:** keep the mix brand.json `positioning.content_mix` (30/25/15/15/15), lengths config `render.length_s`, posting time brand.json `posting.posting_time` (late afternoon Central).
- **30 or more (rule 10):** the brief's `mix.suggested_pillar_mix` becomes `PLAN` `mix` (at most 5 points per pillar per month, every pillar 10-40%, summing to 100%); posting hours come from `SPLAN` `post_time` (post-reel reads it); and you still:
  1. **Series:** the top series by the brief gets one extra slot, the bottom one keeps its monthly minimum (all five run every month).
  2. **Lengths:** median retention by length band (15-30, 31-45, 46-60 s); shift a template's default length toward the best band, inside its `typical_length_s`.
  3. **Edit rules (hook types, transitions):** turn each clear winner or loser in the brief into a feedback note so every build honours it: `python3 "$S/prefs.py" add --file "$STATE/preferences.json" "education reels: hook text 6 words or fewer"`.
- Every change goes into `STATE/digest_notes.json` `changes` ("Moved offers to Thursday: offer reels got 2x the sends") so the next Monday digest lists it.

## 3. The skeleton and the calendar (R158-R168, R171, R172)

```
cp "$STATE/plans/strategy_YYYY-MM.json" "$STATE/plans/plan_YYYY-MM.json"
```
(No `SPLAN` because strategy.py could not run: `python3 "$S/shoot_card.py" month YYYY-MM --json > "$STATE/plans/plan_YYYY-MM.json"`, the default week, and log it.) One row per day: day number, date, `Day NN - YYYY-MM-DD - <Title>` folder name, the slot and its post type, a suggested `film_by` (Monday films Tue-Thu, Thursday films Fri-Mon). Then fill every row by judgment (title, topic, series, script), keeping each row's post type, time and patterns.

**Post types (config `post_types`, R336).** Every row gets exactly one:

| `kind` | Post | How it is built on its day | Filming |
|---|---|---|---|
| `reel` | Reel, 15-60 s | /make-reel | the card's shots and Scott's voiceover |
| `trial_reel` | Trial Reel (non-followers first) | /make-reel, posted as a Trial Reel after approval | as a reel |
| `carousel` + `carousel_source: component` | Component carousel: explainer, protocol, myth vs fact, FAQ, offer, from the slot's carousel pattern | the **designer** in Claude Design (numa-carousel skill) | none; real photos from the library |
| `carousel` + `carousel_source: photos` | Photo carousel (2-10 real photos, short lines) | photo_post.py carousel | optional: a few stills on the card's `photos` |
| `carousel` + `carousel_source: reel` | Carousel cut from a reel (`derived_from`) | formats.py | none |
| `image` | Single photo post on a topic | photo_post.py single | none (a still from the day folder or the library) |
| `stories` | Story set (`story_frames` 3-5 from `SPLAN`) | formats.py from the latest reel | none |

`SPLAN` already sets `carousel_source` on every carousel row with the one rule of `shoot_card.carousel_source_of` (component when `pattern_ids` name a carousel pattern, else reel when `derived_from`, else component); change it to `photos` only for a member, class or room moment told in pictures, and log why. Statics (carousels and photos) are about a third of feed posts unless `SPLAN` moved them (format arms).

| Day | Post (default week, the cold start) | Notes |
|---|---|---|
| Mon | Ask the DPT reel, 45-60 s | Education; no booking pitch in it |
| Tue | Carousel | Saveable explainer or protocol from Monday's topic (`derived_from` Monday) |
| Wed | Community reel (First Plunge or member moment) | Built for sends; consent list only |
| Thu | Trial Reel + Stories | Tests a new hook on non-followers (often the trend winner) |
| Fri | Offer, event or collab reel | The week's one sales moment; collab weeks alternate with offer weeks |
| Sat | Stories | Behind the scenes, class energy |
| Sun | Regulate reel or Stories | Calm, reflective; led by a breathwork guide from `team.collective` |

Planning rules (spec p.34-35); `shoot_card.py check` enforces the mechanical ones:

1. No topic repeats within 14 days; at most one sales-focused reel a week (`sales`).
2. Lengths: growth reels 45-60 s, atmosphere and announcements 15-30 s, nothing over 3 minutes (config `render.length_s`).
3. Every reel is original. Other people's content only as a collab post, never a repost.
4. At least one collab reel and one Meet the Collective feature a month. Collabs: "Sweat there, recover here" with brand.json `positioning.collab_partners` in their `order` (Mission Fitness first, then barre3 Mobile, Pure Barre Mobile, run clubs, South Alabama teams), skipping a partner featured in the last 2 months. Meet the Collective rotates through `team.collective`, posted as a collab with that provider.
5. Weather: the Friday trend-check swaps in weather hooks; at planning, give each week one seasonal slot it can swap.
6. One signature transformation or reveal reel a month (`signature: true`, template `transformation` when a true before/after pair exists).
7. Every event: a teaser 2-3 days before and a recap within 2 days after (`event`, `event_role`). Put the event in `PLAN` `events`; its class or event becomes a **capture moment**: the recap card lists the shots to grab during it (`during`).
8. Nothing that invites people in on a closure day (`STATE/closures.json`): use an evergreen, non-inviting reel or Stories (`invites: false`, no booking CTA).
9. Shoot cards grouped so Katie films a week in one or two short sessions (section 5).
10. After 30 posted reels, the mix, lengths and posting hours are re-tuned (section 2).

Cadence: something posts every day: 4-5 feed posts a week (about two-thirds Reels, one-third carousels and photos, as `SPLAN` allocates), daily Stories cut from the same material (formats.py on build day), 1-2 Trial Reels a week to test hooks on non-followers, never a week dark. Every post still waits for a person's approval before it goes out (DECISIONS D26), so plan no more posts a week than the approvers can review (`strategy.py` caps volume at the policies' `approval_capacity_per_week`). All five series (brand.json `positioning.series`) run every month. Each row gets `title` (short; it becomes the folder name), `topic`, `series`, `pillar`, `goal` (awareness, offer, community, education), `template` (an id from skills/numa-scriptwriter/templates.json), `kind` (and `carousel_source` on carousels), `sales`, `collab`, `event`, `event_role`, `signature`, and keeps `SPLAN`'s `post_type`, `post_time`, `pattern_ids`, `strategy_arm` and `strategy`.

## 4. Scripts and cards: all in one pass (R186-R191)

Send the **scriptwriter** agent the whole `PLAN`, the inputs file and `STATE/strategy_brief.json`, and say "month pass". It writes each row from its slot's `pattern_ids` (skills/numa-scriptwriter/ADAPTIVE.md: never a retired pattern, never an invented id, `pattern_ids` and `strategy_arm` copied into script.json) and fills every reel row with the script.json fields (schemas/script.schema.json): hook, voiceover lines (Scott reads them, `voiceover_by`), shots tied to lines, photos, music, CTA, share line, safety line, consent flag, caption draft, and checks each one itself. Carousel and image rows get a title, topic, the carousel outline or photo idea from their pattern and a caption draft (the designer and photo_post.py build them on the day). Read every hook and script yourself: weak hook, unclear story or anything that sounds like a claim goes back with a numbered fix. The scriptwriter rewrites only what you name.

## 5. Batch the shoot (R169, R181-R184)

1. Group every new shot of the month by room (plunge room, sauna, class studio, front of house, outside), then by time of day for light. Set each row's `batch_room` and each shot's `room` and `time_of_day`.
2. One or two sessions a week (the skeleton's Monday and Thursday by default; move them to the brand.json `team.filming` times once known). Every `film_by` is before its day. Rule 9 in the check fails a week with three or more sessions.
3. Shots that repeat across reels (the plunge room empty, the sauna glowing, the front door) are filmed once: the first card lists them with `library_tags`; later cards use them as `source: "library"` shots (not on the card). The librarian tags them in the media library after the first build.
4. Classes and events on the calendar become capture moments: shots with `during` ("during Numa Nights").
5. Voiceovers for a week are read back to back in one sitting, one file per day named by day number (the card says `voiceover NN`); the librarian routes each file to its day.
6. Anything not filmed by its date goes to the failure table on the night check, never a reminder.

## 6. Credits per day

Plan the month's Higgsfield spend (config `budget`): `python3 "$S/ledger.py" price --json` gives each job's credits. Give each reel its one AI motion shot at the Kling draft-then-pro cost and put the number in the row's `credits_planned`; keep the month inside `budget.split` per category, at most `budget.max_credits_per_reel` per reel, and the first half inside the pacing rule (`budget.pacing`: by day 15 no more than 55% spent). When the plan exceeds a split, drop AI motion from the weakest atmosphere days first (engine motion instead).

**AI-animated people (R342).** Instagram's AI label is required on any reel with AI-animated people (brand.json `posting.ai_label_rule`), and it cannot be guaranteed: INSTAGRAM_POST_IG_USER_MEDIA has no AI-label field, so it is set only through Claude in Chrome, which works only while Katie's Mac happens to be awake at posting time. So plan a day's AI motion shot on a **people-free** still (rooms, water, steam, the sauna glow) and give people shots engine motion. Plan AI motion of a person only when `STATE/setup.json` `verified` records that the API sets the label (docs/SETUP_GUIDE.md "Verify these first" #1). Log each such choice in the decisions file.

## 7. Check until clean

```
python3 "$S/shoot_card.py" check "$STATE/plans/plan_YYYY-MM.json" --closures "$STATE/closures.json" --json
```
Exit 1 lists each violation with its rule and days. Fix the rows (swap topics, move a sales reel, add the missing teaser) and run it again until it exits 0. `WARN` lines: fix them or log why they stay.

## 8. Write Drive and the Sheet (R156, R157)

Through the Google Drive and Google Sheets connectors (names from brand.json `drive`):

1. Make sure `drive.root/_Plan/` holds `drive.plan_sheet`, `drive.music_library` (tracks named `drive.music_naming`) and `drive.digests`; create what is missing.
2. Create the month folder (`drive.month_folder`, e.g. `2026-12 December`) and one day folder per row (`drive.day_folder`, e.g. `Day 07 - 2026-12-07 - Your first plunge`), each with `photos/`, `clips/` and `Finished/`.
3. In each day folder: the shoot card as a Google Doc named `drive.shoot_card` with the text of
   ```
   python3 "$S/shoot_card.py" card "$STATE/plans/rows/day_NN.json" --out "$STATE/plans/cards/day_NN.txt"
   ```
   (`rows/day_NN.json` = that row of `PLAN`), and the row as `script.json`. Open two cards and LOOK: header, filing rules, shots, script, last line "IF YOU CAN'T: skip it."
4. Put each folder's link in the row's `folder_link`, then write the Sheet tab for the month (named YYYY-MM) from
   ```
   python3 "$S/shoot_card.py" sheet "$STATE/plans/plan_YYYY-MM.json" --csv --out "$STATE/plans/sheet_YYYY-MM.csv"
   ```
   Columns exactly: Day, Date, Title, Goal, Template, Hook (first 2 seconds), Voiceover script, Shot list, Music mood + BPM, Call to action, Status, Folder link, Reel link. Status starts at `Planned`; later runs move it through Shot, Ready to build, Ready to post (built and staged), then a person sets `Approved` (or `Approved - <name or initials>`; DECISIONS D26) once they have looked at the finished post, and the post goes out and becomes Posted. Katie may edit a row; every run re-reads it. An Approved set before the post is built does not count: the build sets the row back to Ready to post for a real approval.
5. Upload `PLAN`, `SPLAN`, `STATE/plans/events_YYYY-MM.json`, `STATE/closures.json`, the inputs file, `STATE/strategy.json` and the brief to Drive `drive.plan_dir/plans/` (`strategy.json` and the brief to `drive.plan_dir`).

## 9. Tell, don't ask

Add the month overview to `STATE/digest_notes.json` `changes` (series rotation, the collab partner, events, re-weights) so the next Monday digest carries it with the first week's shoot list. No message asks anything; nothing waits on Katie.

## Worked example: one December row (after the scriptwriter)

```json
{"day": 9, "date": "2026-12-09", "kind": "reel", "slot": "community_reel", "title": "Your first plunge",
 "topic": "first plunge", "series": "first_plunge", "pillar": "community", "goal": "community",
 "template": "member_story_reel", "length_s": 45, "sales": false, "film_by": "2026-12-07", "batch_room": "plunge room",
 "hook_text": "Three minutes.", "lines": ["Three minutes. That's all it takes.", "..."], "shots": ["..."],
 "credits_planned": 40, "status": "Planned"}
```

## Done means

The run is finished in the run log (section "Run start and end", step 3); the Strategist's `SPLAN` and brief exist (or the default week is logged); `check` exits 0; every day folder has photos/, clips/, Finished/, a SHOOT CARD and script.json; the Sheet tab has one row per day; the decisions file and digest notes are written. Nobody was asked anything.
