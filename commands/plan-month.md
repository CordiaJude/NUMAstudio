---
description: Plan the next month of NUMA reels on its own - research, re-weight from last month's results, write the plan Sheet, create the day folders and a SHOOT CARD in each. Nobody approves the plan.
argument-hint: "[YYYY-MM] (empty = next month)"
model: opus
---
# /plan-month: the Director plans a month

You are NUMA's **Director** (`models.agents.director`, effort `models.effort.director` in config/studio.json). This runs from the `plan_month` scheduled task (config `schedule.tasks`: the 24th, 9 pm Central) or by hand. Month = `$ARGUMENTS` (YYYY-MM), else next month.

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

## 1. Gather inputs first (R155)

Run the scout (agents/scout.md) and the data steps in parallel. Missing input: plan with what you have and log it; never wait.

| Input | Where | Save as |
|---|---|---|
| Offers and prices | brand.json `offerings.offers`; NUMA's site and socials (brand.json `business.website`, `socials`) via the **scout**: Claude in Chrome when the Mac is awake, else WebSearch/WebFetch. Quote the URL for every fact. | `STATE/plans/inputs_YYYY-MM.json` `offers` |
| Class schedule and events (Numa Nights, Clinical Conversations, classes) | brand.json `offerings.events`; the scout on NUMA's site, Instagram and Facebook | `inputs` `events` [{name, date, time, url}] |
| Closures and holidays | the Closures Sheet (brand.json `closures.location`) through the Google Sheets connector, plus `closures.known`, plus US holidays in the month | `STATE/closures.json` [{date, name}] |
| Last month's results | `python3 "$S/metrics.py" compute --store "$STATE/metrics.json" --json`, then `python3 "$S/dashboard.py" "$STATE/metrics.json" "$STATE/dashboard.html" --notes "$STATE/dashboard_notes.json"` and read the "Do more of / Do less of" box | `inputs` `results` |
| Season and Mobile local moments | the table below, plus a web search for this year's dates (Mardi Gras parades, Midtown events, South Alabama home games) | `inputs` `moments` |
| Trend ideas | the newest `STATE/trends/trends_*.json` (trend-check) | `inputs` `trends` |
| Feedback memory | `python3 "$S/prefs.py" list --file "$STATE/preferences.json" --json` | honoured in every card |
| Credit budget | `python3 "$S/ledger.py" report --ledger "$STATE/credit_ledger" --month YYYY-MM --json` (a new month starts at config `budget.monthly_credits`) | `inputs` `credits` |

| Months | Local moments to plan around |
|---|---|
| Dec-Feb | Cold snaps ("Sauna season in Mobile"), New Year resets, holiday closures |
| Jan-Mar | Mardi Gras season (parade dates change yearly: look them up), recovery week after Fat Tuesday |
| Jun-Nov | Hurricane season ("hurricane-season calm"), never a storm joke |
| Jun-Sep | Summer heat: Mobile tap water rarely below 70°F, so "Too Hot for a DIY Plunge" |
| Aug-Nov | University of South Alabama semester and game days; back-to-school routines |
| All year | Midtown, Dauphin St, shift workers and the 5:30 AM opening (brand.json `positioning.target_audiences`) |

## 2. Re-weight from performance (R161, R170, R252)

Count posted reels in the metrics store (reels with a 72h or 7d pull).

- **Under 30 posted reels:** keep the mix brand.json `positioning.content_mix` (30/25/15/15/15), lengths config `render.length_s`, posting time brand.json `posting.posting_time` (late afternoon Central).
- **30 or more (rule 10):** re-tune from NUMA's own results, judged at 72 h (config `instagram.judge_at_hours`):
  1. **Mix:** rank pillars by median sends per 1,000 reach plus saves per 1,000 reach. Move at most 5 points per pillar per month toward the top two, keep every pillar between 10% and 40%, sum to 100%. Write it to `PLAN` `mix`.
  2. **Series:** the same ranking by series; the top series gets one extra slot, the bottom one keeps its monthly minimum (all five run every month).
  3. **Lengths:** median retention by length band (15-30, 31-45, 46-60 s); shift the default length of a template toward the best band, inside its `typical_length_s`.
  4. **Posting hours:** the best two-hour window in the dashboard heatmap with at least 5 reels; record it as `posting_time` for the post-reel task.
  5. **Edit rules (hook types, transitions):** turn each clear winner or loser into a feedback note so every build honours it: `python3 "$S/prefs.py" add --file "$STATE/preferences.json" "education reels: hook text 6 words or fewer"`.
- Every change goes into `STATE/digest_notes.json` `changes` ("Moved offers to Thursday: offer reels got 2x the sends") so the next Monday digest lists it.

## 3. The skeleton and the calendar (R158-R168, R171, R172)

```
python3 "$S/shoot_card.py" month YYYY-MM --json > "$STATE/plans/plan_YYYY-MM.json"
```
One row per day: day number, date, `Day NN - YYYY-MM-DD - <Title>` folder name, the default-week slot, a suggested `film_by` (Monday films Tue-Thu, Thursday films Fri-Mon). Then fill every row by judgment:

| Day | Post (default week) | Notes |
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

Cadence: something posts every day: 4-5 feed posts a week (about two-thirds Reels, one-third carousels), daily Stories cut from the same material (formats.py on build day), 1-2 Trial Reels a week to test hooks on non-followers, never a week dark. All five series (brand.json `positioning.series`) run every month. Each row gets `title` (short; it becomes the folder name), `topic`, `series`, `pillar`, `goal` (awareness, offer, community, education), `template` (an id from skills/numa-scriptwriter/templates.json), `kind`, `sales`, `collab`, `event`, `event_role`, `signature`.

## 4. Scripts and cards: all in one pass (R186-R191)

Send the **scriptwriter** agent the whole `PLAN` with the inputs file and say "month pass". It fills every reel row with the script.json fields (schemas/script.schema.json): hook, voiceover lines, shots tied to lines, photos, music, CTA, share line, safety line, consent flag, caption draft, and checks each one itself. Read every hook and script yourself: weak hook, unclear story or anything that sounds like a claim goes back with a numbered fix. The scriptwriter rewrites only what you name.

## 5. Batch the shoot (R169, R181-R184)

1. Group every new shot of the month by room (plunge room, sauna, class studio, front of house, outside), then by time of day for light. Set each row's `batch_room` and each shot's `room` and `time_of_day`.
2. One or two sessions a week (the skeleton's Monday and Thursday by default; move them to the brand.json `team.filming` times once known). Every `film_by` is before its day. Rule 9 in the check fails a week with three or more sessions.
3. Shots that repeat across reels (the plunge room empty, the sauna glowing, the front door) are filmed once: the first card lists them with `library_tags`; later cards use them as `source: "library"` shots (not on the card). The librarian tags them in the media library after the first build.
4. Classes and events on the calendar become capture moments: shots with `during` ("during Numa Nights").
5. Voiceovers for a week are read back to back in one sitting, one file per day named by day number (the card says `voiceover NN`); the librarian routes each file to its day.
6. Anything not filmed by its date goes to the failure table on the night check, never a reminder.

## 6. Credits per day

Plan the month's Higgsfield spend (config `budget`): `python3 "$S/ledger.py" price --json` gives each job's credits. Give each reel its one AI motion shot at the Kling draft-then-pro cost and put the number in the row's `credits_planned`; keep the month inside `budget.split` per category, at most `budget.max_credits_per_reel` per reel, and the first half inside the pacing rule (`budget.pacing`: by day 15 no more than 55% spent). When the plan exceeds a split, drop AI motion from the weakest atmosphere days first (engine motion instead).

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
   Columns exactly: Day, Date, Title, Goal, Template, Hook (first 2 seconds), Voiceover script, Shot list, Music mood + BPM, Call to action, Status, Folder link, Reel link. Status starts at `Planned`; later runs move it through Shot, Ready to build, Ready to post, Posted. Katie may edit a row; every run re-reads it.
5. Upload `PLAN`, `STATE/closures.json` and the inputs file to Drive `drive.plan_dir/plans/`.

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

`check` exits 0; every day folder has photos/, clips/, Finished/, a SHOOT CARD and script.json; the Sheet tab has one row per day; the decisions file and digest notes are written. Nobody was asked anything.
