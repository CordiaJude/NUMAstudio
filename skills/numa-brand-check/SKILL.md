---
name: numa-brand-check
description: The pre-post review of a NUMA reel, image or post against NUMA's brand, the claims policy, consent, music licensing, the AI label and the output spec, each check mapped to a script. Use on every shipped /make-reel version (after the Critic) and whenever a NUMA video, graphic or caption needs an on-brand check before it goes out.
---

# NUMA Brand Check

Run every row; a row that fails names the fix. Nothing here waits on anyone: the verdict goes to the Director (or the Editor, for edit-level fixes).

`S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`. For a /make-reel job: `JOB`, `SLUG`, `STATE` as in the Director's run. For a file from outside the pipeline, run the rows that apply to it (an MP4 gets rows 1, 2 and 7 from the file alone).

## Checklist

| # | Check | Command or method | Pass when |
|---|---|---|---|
| 1 | Output spec | `python3 "$S/check_output.py" "$JOB/out/SLUG_reel.mp4" --kind reel --plan "$JOB/work/plan.json" --json` | Exit 0: 1080x1920, 30 fps, H.264 High, AAC **48 kHz only** (REQUIREMENTS interpretation 12; 44.1 or 96 kHz fails), -15 LUFS +/- 1, true peak <= -1.5 dB, not silent or clipped, no black bars, no frozen frame, 15-60 s |
| 2 | Claims (every text and hashtag) | `python3 "$S/claims_scan.py" --plan "$JOB/work/plan.json" --file "$JOB/out/SLUG.srt" --file "$JOB/out/SLUG_copy.txt" --hashtags "<hashtags>" --json`; then LOOK at the frames for visual claims (body before/after, breath-holding near water, `offerings.not_offered`) | Exit 0, no visual claim; WARN lines reworded or kept with a reason |
| 3 | Consent | `python3 "$S/validate_plan.py" "$JOB/work/plan.json" "$JOB/work/analysis.json" --json` (rule 28) and LOOK: every recognizable person is on `STATE/consent_list.json` (`consent.list`), blurred, or absent; `consent.children`. Items with `orig_faces` but empty `faces` get checked by eye | No rule-28 ERROR; no unlisted face in any frame |
| 4 | Music license | `python3 "$S/sources.py" check "$JOB" --plan "$JOB/work/plan.json"` | Exit 0; never trending audio (`posting.music_rule`) |
| 5 | AI label | Plan `ai` and every `ai_generated` shot; validate_plan rule 30 | `ai.label_required` is true whenever AI people or AI scenes appear (`posting.ai_label_rule`), and the copy file says `AI label: ON` |
| 6 | Facts | Every on-screen word, the transcript and the copy against brand.json: `business.name` (on-screen "NUMA"), prices in `offerings.offers` / `offerings.sessions`, dates against the plan row and `offerings.events`, `business.location` | No misspelling, wrong price, date or offer; no `needs_katie` value stated as fact |
| 7 | Brand look | LOOK at `out/qa_strip.jpg` and `out/critic_frames/` (for an outside video: `python3 "$S/qa_frames.py" FILE.mp4 PLAN_JSON` when a plan exists, else 8-12 evenly spaced frames) | Warm grade (cool "before" only before the turn); serif captions, white with 1-2 gold italic words (#F7D6A0, `palette.value`); nothing in the top 12% or bottom 10%; the white wordmark on the ripple end card, not stretched or recoloured; NUMA's voice (`voice.description`), no hype |

## Verdict

- **Ship**: every row passes.
- **Ship after fixes**: up to 3 fixes, most important first, each naming the plan.json field or shot ("Shot 5: `look` warm, not before") or the copy line; hand them to the Editor or Copywriter.
- **Redo**: row 2, 3, 4 or 6 fails and the fix is not a field change (the claim is the reel's point, the person is the whole reel): back to the Director (failure rows F11, F12).

Rows 1-6 are the Critic's hard gates; row 7 is the Critic's brand-look category. Record the verdict in the Decisions log.
