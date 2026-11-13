---
description: Weekly trend and weather check (Fridays, 7 pm) - the Scout finds three trend ideas that fit NUMA (formats, hooks, editing styles, topics; never songs), the Director checks the 7-day forecast for weather hooks and may slot one idea into next week as a Trial Reel
argument-hint: "[YYYY-MM-DD] (empty = today, Central time)"
model: opus
---
# /trend-check: what's working this week, and the weather

You are NUMA's **Director**. This runs from the `trend_check` scheduled task (config `schedule.tasks`, Fridays 7 pm, `schedule.timezone`). You may change next week's plan; you never have to, and you never ask anyone.

Paths: `S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`, `STATE` = `~/NUMA Studio/_Plan`, `PLAN` = `STATE/plans/plan_YYYY-MM.json`.

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

## 1. Weather: the 7-day forecast (planning rule 5, R167)

Look up the National Weather Service 7-day forecast for Mobile, AL (web search and fetch). A weather hook is due when the next 7 days have:

| Condition | Threshold | Hook ("Too Hot for a DIY Plunge", seasonal_holiday template) |
|---|---|---|
| Cold snap | a low at or under 40°F, or a high at or under 50°F | "Sauna season in Mobile" |
| Heat wave | a high at or over 95°F, or a heat index at or over 105°F | Mobile tap water won't cool you; the plunge will |
| Storm | a tropical storm or hurricane watch, or a severe-storm warning | Calm before or after the storm; nothing inviting while a warning is active; never a joke |

When one applies, swap next week's Thursday Trial Reel (or the Sunday slot) for the weather hook: the **scriptwriter** writes the new row (numa-scriptwriter skill), then re-render the card into the day folder, update `script.json` and the Sheet row, and run `python3 "$S/shoot_card.py" check "$PLAN" --closures "$STATE/closures.json"` (exit 0, else pick the other slot). Log it as a heads-up.

## 2. Trends (R241)

Send the **scout** (agents/scout.md) to look at what is working this week for wellness studios (sauna, cold plunge, breathwork, recovery) and Mobile businesses: **formats, hooks, editing styles and topics, never songs**. It uses Claude in Chrome when Katie's Mac is awake, else web search (failure row F17). It watches the formats that travel in this niche: seasonal and weather hooks, hot/cold contrast, teasers, behind-the-scenes and first-timer reactions.

Trending audio is off-limits for a business account (brand.json `posting.music_rule`): a trend is used only if its idea works with NUMA's own audio or a Sound Collection track.

## 3. Three ideas (R242)

Write `STATE/trends/trends_<DAY>.json` with exactly three ideas and one winner:
```json
{"date": "2026-12-11", "ideas": [
  {"idea": "POV first plunge, filmed from the water line", "example_link": "https://www.instagram.com/reel/...",
   "why_it_fits": "First-timer reactions are NUMA's best sends format", "how_with_numa": "Katie films a 5 s water-line clip in the plunge room; one hero still gets Higgsfield motion transfer from the example's camera move",
   "audio": "NUMA voiceover + generated bed", "claims_ok": true}],
 "winner": 0, "slotted": "2026-12-17"}
```
Each idea: a real example link the scout opened, why it fits NUMA (series, audience, the claims policy), and how to make it with NUMA's own material (often Higgsfield motion transfer onto a NUMA still; motion agent, within `ledger.py check`). Scan each idea's text: `python3 "$S/claims_scan.py" "<idea>" "<why_it_fits>" "<how_with_numa>"`; drop an idea that only works with a claim.

## 4. Slot the winner (optional)

The winner is tested as a **Trial Reel** before it reaches the grid. You may slot it into next week's Thursday Trial Reel row (template, hook, script by the scriptwriter, card and Sheet row updated, plan check exit 0) or keep it for later; either way write `slotted` (date or null) and add one line to `STATE/digest_notes.json` `heads_ups` ("Trying a water-line first-plunge Trial Reel on Thursday").

## 5. Competitor log (first Friday of the month)

On the first Friday of a month, the scout also writes the competitor log (agents/scout.md "Competitor log") to `STATE/competitors_YYYY-MM.json` for the dashboard.

## Done means

The trends file has three ideas and a winner, any weather swap and slotted Trial Reel are in the plan, cards and Sheet, and the heads-ups are noted. Nobody was asked anything.
