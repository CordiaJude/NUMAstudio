# Adaptive writing: use the playbook, tag every post, learn from results

NUMA Studio learns from its own engagement what works: which post type, day, hour, hook and structure, and when in the month to place offers (DECISIONS D23). Three roles, one loop:

| Role | Does | Never |
|---|---|---|
| **strategy.py** (`S/strategy.py`) | All the math: scores each post against NUMA's own medians, judges posts provisionally at their early pull and finally at their last, updates the Bayesian models, plans the month with Thompson sampling and an exploration budget, promotes and retires patterns, writes the brief | Decides anything the planning rules forbid |
| **Strategist** (agents/strategist.md) | Decides what and why: runs `learn`, `diagnose`, `plan`, `brief`; reads them; writes `STATE/strategy_brief.json` and its notes | Computes a score itself, overrides a status by hand |
| **Scriptwriter** (this skill) | Writes it: turns each slot's pattern ids into the hook, script, shots, CTA and caption | Picks a retired pattern, invents a pattern id, drops the tags |

`S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`; `STATE` = the local `_Plan` copy; the playbook is `${CLAUDE_PLUGIN_ROOT}/skills/numa-scriptwriter/playbook/` (patterns, diagnosis, calendar, policies; `schemas/playbook.schema.json`).

## 1. Read the slot before writing

For each row you script, read from `STATE/plans/strategy_YYYY-MM.json` (or the week's `STATE/strategy_brief.json` slot, the same fields):

| Field | Use |
|---|---|
| `post_type`, `kind` | reel, trial_reel, carousel, image or stories |
| `post_time` | Central HH:MM to post (the Director schedules it) |
| `pillar`, `series`, `goal` | what the content is for |
| `pattern_ids` | the hook, the structure (script structure, carousel template or photo type) and the CTA or offer framing to use |
| `strategy_arm` | copy it unchanged (section 3) |
| `strategy.mode` | `exploit` (use what works), `explore` (a deliberate test), `rule` (a planning-rule slot: event, offer, signature) |
| `strategy.why` | why the slot got its type, time and patterns |

Explain any slot: `python3 "$S/strategy.py" explain <day> --plan "$STATE/plans/strategy_YYYY-MM.json"`.

## 2. Write from the patterns

1. **Look each id up** in the merged playbook (`python3 "$S/strategy.py" export --state "$STATE/strategy.json" --out "$STATE/playbook_merged.json"`, then read it): `template`, `examples`, `visual` (frame zero), `beats`, `length_s`, `slides`, `when_not`, `needs`.
2. **Hook:** write the hook from the hook pattern's `template` in NUMA's voice; frame zero shows the pattern's `visual`. Example: `contrast-visual` -> hook_text "Sauna heat. Then the cold plunge." over steam cut to the plunge surface.
3. **Structure:** follow the structure's `beats` (one spoken line per beat) and its `templates` id for script.json `template`; carousels follow the carousel pattern's slide outline; images the photo type.
4. **CTA or offer:** the `cta-*` or `offer-*` pattern's template; offers only with a brand.json price whose status is not `needs_katie`.
5. **Explore slots** test the pattern exactly as written; don't blend in a proven hook, or the test means nothing.
6. **`when_not` and `needs` win:** when a pattern's `when_not` applies (e.g. no consent for `first-timer-reaction`), use its first `try_instead` id that is not retired, and say so in script.json `notes` ("pattern swap: first-timer-reaction -> pov-walkthrough, no consent").
7. **Never use a retired pattern.** `strategy.py validate --state "$STATE/strategy.json" --json` lists the playbook; a retired id never appears in a plan, and you never bring one back.

## 3. Tag every post (the learning depends on it)

script.json carries `pattern_ids` (list of ids) and `strategy_arm` (the string from the plan row, unchanged). /build-today copies them into the reel's NUMA tags and /dashboard-refresh stores them with `metrics.py tag`, so each result is credited to the right arm (docs/CONTRACTS.md section 9, strategy.py). After a pattern swap (section 2 step 6), write the id you actually used in `pattern_ids` and keep `strategy_arm` as planned.

## 4. When a post underperforms

The Strategist's brief lists `diagnoses`: for the latest weak post of a series, the matching rows of the playbook diagnosis table (symptom -> cause -> fix, keyed to metrics.py names such as `skip_rate_vs_median`, `retention`, `sends_per_1k_reach`, `saves_per_1k_reach`). On the next post of that series:

| Symptom (example) | Do next |
|---|---|
| `skip-above-median` | open on a contrast or weather visual, hook text at full opacity from frame zero, first shot under 2 s |
| `retention-sags` | no shot over 4 beats, a turn near the middle |
| `sends-low` | build it around a person to send it to and end on the share line |
| `saves-low-carousel` | a concrete protocol or comparison with a save line on the last slide |

Use the row's `try_patterns` (the plan already favours them) and write the fix you applied in `notes`. Or run it yourself: `python3 "$S/strategy.py" diagnose --metrics "$STATE/metrics.json" --state "$STATE/strategy.json" --json`.

## 5. Claims safety is not negotiable

Every line still passes `shoot_card.py script` (claims_scan on the title, hook, lines, shots, on-screen text, CTA, share line, caption, hashtags). Playbook examples are claims-safe, but your filled-in line is new text: sell the experience, never the outcome. A pattern never excuses a health claim, a member face without consent, or a price marked `needs_katie`. Planning rules (claims, consent, budget, events, closures, one sales post a week) override the brief.
