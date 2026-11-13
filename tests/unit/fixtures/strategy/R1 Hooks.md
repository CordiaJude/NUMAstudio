# R1: Hooks and openings that stop the scroll

Sample research output used by tests/unit/test_strategy.py. It follows the R1 field list in docs/RESEARCH_PROMPTS_PLAYBOOK.md; the sources are illustrative placeholders for the parser, not findings.

## 1. `steam-reveal` — Steam reveal

- **id, name:** steam-reveal, Steam reveal
- **Format(s):** reel, trial reel, story
- **Template:** "Watch the steam roll off the {place}." Open on steam, cut on the first beat.
- **NUMA examples:**
  - "Watch the steam roll off the sauna stones."
  - "Steam, then silence. Tuesday night at NUMA."
- **Visual for frame 0:** steam rising in warm light, text at full opacity
- **Best use:** local/seasonal, community
- **Evidence:** observed (example account posts, https://example.org/steam-study) low confidence
- **Expected effect:** lower skip rate, more sends
- **When NOT to use it:** in summer heat waves when steam reads as sweaty
- **What to try instead if it underperforms:** contrast-visual or seasonal-weather

## 2. `detox-hook` — Sweat it out

- **id, name:** detox-hook, Sweat it out
- **Format(s):** reel
- **Template:** "Sweat it out at NUMA."
- **NUMA examples:**
  - "Detox your body in the sauna."
  - "Sauna burns calories while you relax."
- **Best use:** education
- **Evidence:** opinion (agency blog)
- **When NOT to use it:** never
- **What to try instead if it underperforms:** question-hook

## 3. `contrast-visual` — Hot/cold contrast

- **id, name:** contrast-visual, Hot/cold contrast
- **Format(s):** reel, carousel
- **Template:** "{Heat}. Then {cold}."
- **NUMA examples:**
  - "Heat on the left. Cold on the right."
- **Evidence:** measured (Example 2026 hook study, https://example.org/hooks-2026)
- **When NOT to use it:** twice in a row
- **What to try instead if it underperforms:** seasonal-weather

## 4. `cold-plunge-pov` — First person into the plunge

- **id, name:** cold-plunge-pov, First person into the plunge
- **Format(s):** reel, trial reel
- **Template:** "POV: your feet touch the cold water."
- **NUMA examples:**
  - "POV: your feet touch the cold water."
  - "Ten seconds in. Breathe out slow."
- **Best use:** community
- **Evidence:** opinion (practitioner reports)
- **When NOT to use it:** when the plunge room is crowded
- **What to try instead if it underperforms:** first-timer-reaction

## The 10 patterns to test first

1. steam-reveal, because it is cheap to film.
