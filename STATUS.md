# Status

| Task | State | Round | Open findings |
|------|-------|-------|---------------|
| T0 Foundation | ACCEPTED (review PASS x2, 223 unit tests green) | 2 | 2 minor logged below |
| T1 Engine | ACCEPTED (re-review 11/11 PASS) | 2 | 2 minor logged |
| T2 Analyze | ACCEPTED (re-review PASS 7/7; orchestrator fixed minor: no script alignment on mismatch) | 2 | |
| T3 Finish | ACCEPTED (round 3 re-review 4/4 PASS) | 3 | 2 minor logged |
| T4 Validator/baseline/claims | ACCEPTED (re-review 10/10 PASS) | 2 | cosmetic: duplicate hits per rule |
| T5 Vision/prep | ACCEPTED (re-review 6/6 PASS) | 2 | minor: color_range tag on OpenCV path |
| T6 Formats | IN REVIEW | 1 | |
| T7 Ops scripts | ACCEPTED (round 3 re-review PASS) | 3 | |
| T8a Director+librarian/scout/analyst | ACCEPTED (9/10; --template depends on T12, verified in T11) | 2 | |
| T8b Crew agents + skills | ACCEPTED (re-review 8/8 PASS) | 2 | |
| T9 30-day system | REVISING | 2 | B: stale sales flag; M: card length, prose flag test |
| T10 Setup/posting | IN REVIEW | 1 | |
| T12 Templates/prefs/kinetic/rule41 | IN PROGRESS | 1 | |
| T11 Integration | PENDING | 0 | |

## Minor findings for final polish
- T0: example-plan-year-one-v2.json whips on shots 10,12,14,16 violate "at most every third cut" (fix after T4 adds spacing check).
- T0: brand.json outcome_verbs misses "good for your joints/heart".

## Traceability (filled in Phase 5)
- T2: R13/R14/R18/R102 instruction rows go to T8 (librarian.md, analyst.md, make-reel.md): fix_transcript --script order.
- T12: baseline_plan should honour max_flashes pref (T7 review).
- T3: finish.py loudness loop keeps refining after in-spec pass 1 (stop when in spec ±0.5 LU or no improvement); report.json add delivered_pass; log line shows next-pass values.
- T1: render cache under out_dir may sync if work folder is in Drive; document NUMA_RENDER_CACHE / prefer system temp for synced paths.
- Cleanup for user: empty folder /nonexistent_ro/x created by a reviewer test (safety check blocked removal).
- T8a follow-up (from T8b): make-reel step 10 pass critic analysis.json, sources.json, plan_row.json, STATE/consent_list.json; scout.md add Higgsfield unlimited-window draft batching (R227).
- T12: baseline_plan reach_cut.hook should differ from the reel hook (e.g. meta.title or second line).
- T12: add validate_plan rule 41: shot whose analysis item has faces/orig_faces but plan people!=true → ERROR unless consent true or blur covers all faces (T8b review).
- T12: claims_scan illness rule false-fails 'I said I could never do a cold plunge' (T9 report).
- shoot_card.py month | head prints BrokenPipe ERROR (minor).
- T11: wire NUMA_BRAND=STATE/brand.json (when newer) into make-reel, librarian, build-today, plan-month, night-check, digest (D18).
