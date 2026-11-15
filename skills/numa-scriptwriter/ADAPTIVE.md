# Adaptive writing: use the playbook, tag every post, learn from results

Numa Studio learns from its own engagement what works: which post type, hook, structure, CTA, posting time and offer week (DECISIONS D23). The rules are R6 (docs/research/R6_Learning_loop.md) and R7 (docs/research/R7_Judging_windows.md), corrected by docs/research/REVIEW.md, where Numa's facts and rules always win. Three roles, one loop:

| Role | Does | Never |
|---|---|---|
| **strategy.py** (`S/strategy.py`) | All the math: per-reach rates as a log2 index against Numa's last 20 same-format posts, the composite score S and win = S > 0, provisional and final judging windows, discounted Beta posteriors, Thompson sampling with a 30% explore share (Trial Reels on top), the promote / retire / demote rules, the month plan and the brief | Breaks a planning rule |
| **Strategist** (agents/strategist.md) | Decides what and why: runs `learn`, `diagnose`, `plan`, `brief`; reads them; writes `STATE/strategy_brief.json` and its notes | Computes a score itself, overrides a status by hand, invents an offer |
| **Scriptwriter** (this skill) | Writes it: turns each slot's pattern ids into the hook, script, shots, CTA and caption | Picks a retired pattern, invents a pattern id, drops the tags |

`S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`; `STATE` = the local `_Plan` copy; the playbook is `${CLAUDE_PLUGIN_ROOT}/skills/numa-scriptwriter/playbook/` (patterns, diagnosis, calendar, policies; `schemas/playbook.schema.json`).

## 1. Read the slot before writing

For each row you script, read `STATE/strategy_brief.json` (the week's slots) or `STATE/plans/strategy_YYYY-MM.json` (the same fields):

| Field | Use |
|---|---|
| `post_type`, `kind` | reel, trial_reel, carousel, image or stories |
| `post_time` | Central HH:MM to post (a blocked weekly rotation until one slot wins) |
| `pillar`, `series`, `goal` | what the content is for |
| `pattern_ids` | the hook, the structure (script structure, carousel template or photo type) and the CTA or offer framing |
| `strategy_arm` | copy it unchanged (section 3) |
| `strategy.mode`, `strategy.tests` | `exploit` (use what works), `explore` (a deliberate test of one variable: hook first, R6), `rule` (an event, offer or signature slot) |
| `strategy.why` | why the slot got its type, time and patterns |

Explain any slot: `python3 "$S/strategy.py" explain <day> --plan "$STATE/plans/strategy_YYYY-MM.json"`.

## 2. Write from the patterns

1. **Look each id up** in the merged playbook: `python3 "$S/strategy.py" export --state "$STATE/strategy.json" --out "$STATE/playbook_merged.json"`, then read `template`, `examples`, `visual` (frame zero), `beats`, `length_s`, `when_not`, `needs`.
2. **Hook:** write it from the hook pattern's `template` in Numa's voice; frame zero shows its `visual`. Example: `plunge-entry` -> hook_text "48°F. Round two. No backing out." over feet breaking the water.
3. **Structure:** follow the structure's `beats` (one spoken line per beat) and put its `templates` id in script.json `template`; carousels follow the carousel pattern's slide outline; images the photo type.
4. **CTA or offer:** the `cta-*` or `offer-*` template; only offers in brand.json `offerings.offers` (Discover Numa ends on its own: one time, no commitment).
5. **Explore slots** test one variable (`strategy.tests`) exactly as written; keep everything else at the current best, so the win can be credited.
6. **`when_not` and `needs` win:** when a pattern's `when_not` applies (e.g. nobody on camera has a yes on record for `reaction-face`), use its first `try_instead` id that is not retired, and write the swap in script.json `notes`.
7. **Never use a retired pattern** (`clinical-conversations-question` is retired: the event is cancelled).

## 3. Tag every post (the learning depends on it)

script.json carries `pattern_ids` (list of ids) and `strategy_arm` (the plan row's string, unchanged). /build-today copies them into the post's tags and /dashboard-refresh stores them with `metrics.py tag` (docs/CONTRACTS.md section 9, strategy.py). After a pattern swap, write the id you actually used in `pattern_ids` and keep `strategy_arm` as planned. Collab and boosted posts carry `collab: true` or `boosted: true`: they are scored in their own cohort and kept out of the pattern decisions.

## 4. When a post underperforms

The brief lists `diagnoses`: for the latest weak post of a series (index under 0.8x Numa's median), the matching rows of the R3 diagnosis table (symptom -> cause -> fix). On the next post of that series:

| Row | Do next |
|---|---|
| `skip-above-median` | open mid-action on a face or motion, a 5-8 word text hook in frame 1 |
| `retention-mid-dip` | trim the dead beat; a visual change every 2-4 s |
| `sends-low` | name the person to send it to; end on the share line |
| `saves-low` | add times, steps or a packing list; make it a checklist |

Use the row's `try_patterns` (the plan already favours them) and write the fix you applied in `notes`. Or run it yourself: `python3 "$S/strategy.py" diagnose --metrics "$STATE/metrics.json" --state "$STATE/strategy.json" --json`.

## 5. Numa's rules are not negotiable

Every line still passes `shoot_card.py script` (claims_scan on the title, hook, lines, shots, on-screen text, CTA, share line, caption, hashtags). Playbook examples are claims-safe, but your filled-in line is new text: sell the experience, never the outcome. Always "Numa"; no emojis; no quote cards, flyers or posters; no trending songs; plunges 44-52°F, sauna 175-190°F; only amenities brand.json lists; members on camera only with a yes on record; never send new people to Saturday mornings; on a half day (brand.json `closures.partial`) nothing invites people in after closing; name only the co-founders, everyone else by role or `[guide name]`. Planning rules (claims, consent, budget, events, closures, one sales post a week) override the brief.
