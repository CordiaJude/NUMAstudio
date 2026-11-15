---
description: Auto-posting (addition #11) - posts reels, carousels and photos to Instagram through Composio at the best time, then Facebook, only after a person approves each post (the human-approval gate, DECISIONS D26) and a shown member's yes, the AI label, Trial Reels and collab invites, marks the Sheet row Posted and schedules the insight pulls
argument-hint: "JOB [publish] | approvals | queue (JOB = the job folder make-reel step 13 or /build-today hands over: a reel, carousel, photo or Story set)"
model: opus
---
# /post-reel: publish a finished, approved post

You are Numa's **Director**. make-reel step 13 (or /build-today) hands over `JOB` when the post is finished and in Drive `Finished/`; this command stages it, and posts it only once a person has approved it (DECISIONS D26). Same rules as commands/make-reel.md section 0: never ask Katie anything, never wait on anyone, every failure has a fallback, everything is logged in `JOB/work/decisions.md`. A post that cannot go out today stays "Ready to post" in the Sheet with its files in `Finished/`; that is a valid end of this run.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `STATE` | `~/NUMA Studio/_Plan` (synced with Drive brand.json `drive.plan_dir`) |
| `JOB` | the job folder (docs/CONTRACTS.md section 2); `SLUG` = plan `meta.slug` |
| `POST` | `JOB/work/post.json`: this post's state (status, container, media id, times); re-read it first on every run |
| Queue and log | `STATE/post_queue.json` (posts waiting on a fix), `STATE/post_log.json` (every API post: date, media id, slug, kind), `STATE/escalations.json` (last date each Jude message was sent) |
| Staged posts | `STATE/staged/<SLUG>.json`, one file per staged post, mirrored to Drive `_Plan/staged/` (section 2 step 5): everything a later run on a fresh machine needs to post it once it is approved (section 13) |
| Approval notices | `STATE/approval_notices.json`: the posts named in the last approver notice and when (section 13 step 4) |

**Brand data (DECISIONS D18).** Katie's /brand-setup answers live in `STATE/brand.json` (synced from Drive `drive.plan_dir`) before Jude commits them to the plugin. At the start of the run, and again at the start of every Bash call that runs a script (shell variables do not carry between calls), use that copy when it exists and is newer than the bundled file:

```
if [ "$STATE/brand.json" -nt "${CLAUDE_PLUGIN_ROOT}/brand/brand.json" ]; then export NUMA_BRAND="$STATE/brand.json"; fi
```

Every script then reads brand facts, claims, consent and closures from it. When the copy is missing or older, leave `NUMA_BRAND` unset (the bundled brand.json is used).

`$ARGUMENTS`: `JOB` = stage, then publish at the posting time once approved (section 3); `JOB publish` = publish now if approved (the one-time task from section 3 runs this); `approvals` = the approval re-check of every staged post (section 13; the night check, the dashboard refresh, the midday Story task and the Chrome queue task run it); `queue` = only drain the queue (section 9). Every run drains the queue first.

**Run start and end (R339-R342).** Handed over by /build-today or /make-reel (or run inside the night check, dashboard refresh, midday Story task or Chrome queue task for `approvals`), this runs inside their run-log entry: skip this paragraph. Run on its own (by hand, or from its one-time publish task):
1. Do commands/build-today.md "Run start and end" step 1: `merge-dir` of Drive `_Plan/runlog/` (a failed download is never "absent"), then `python3 "$S/runlog.py" start post_reel --state "$STATE"`; keep the printed run id (`RUN_ID`) and upload `STATE/runlog/<RUN_ID>.json` to Drive `_Plan/runlog/`.
2. `python3 "$S/ensure_env.py" --json` (add `--with-chromium` for a component carousel, section 12 step 0). Exit 1: send Jude its ERROR line's fix through the escalation channel in `STATE/brand.json` (DECISIONS D19), leave the post staged, finish `failed` and stop.
3. Always end, also on failure: `python3 "$S/runlog.py" finish <RUN_ID> --outcome ok|failed|partial --note "<posted / staged / held, and why>" --state "$STATE"`, then upload `STATE/runlog/<RUN_ID>.json` again.

**Approval first (DECISIONS D26).** Nothing is published unless the plan Sheet row reads Approved, set by a person. Unapproved means: the post stays staged ("Ready to post"), nothing is queued for Chrome, the digest lists it, and the approver gets one batched line per run (section 13). **No fallback anywhere in this command may publish**: every fallback stages, holds or queues. A queued Chrome step never delays any other post.

**Post type** (config `post_types`). A `JOB` whose `out/` holds `SLUG_reel.mp4` is a reel or Trial Reel (sections 1-11 as written). A `JOB` without a reel but with carousel slides `out/SLUG_carousel_NN.jpg` (`_01`, `_02`, ...: formats.py, photo_post.py and Claude Design component carousels all use these names) is a **carousel**, and one with `out/SLUG_photo.jpg` is a **single photo**: both follow section 12, which reuses sections 1, 3, 6, 8 and 9 unchanged. A **Story set** day (`out/SLUG_story_<N>.jpg|mp4` and no reel) posts its frames as section 4 step 5 describes, with the same gates.

## 1. Gates, in this order (brand.json `posting`)

| # | Check | Result |
|---|---|---|
| 1 | `POST` status is `published` | Already posted: log it, stop. Never post the same reel twice. |
| 2 | `posting.auto_post.value` is false | Sheet row "Ready to post"; final message "Ready to post: <title> is in Finished/ with its caption." Stop. |
| 3 | **Human approval** (DECISIONS D26): `posting.human_approval_required.value` or `posting.require_approval.value` is true, or the post's type is in `posting.see_first.value` (offer = plan row `sales` true; members = any plan shot with `people: true`; collab = plan row `collab`; event = plan row `event`) | Re-read the plan Sheet row now (never a cached copy). **Approved** = its Status is `Approved` or `Approved - <name or initials>`, set by a person. Approved: record `POST` `approval` = {`by`: the name or initials after "Approved - ", else the Sheet's last modifying user from the Drive file metadata; `at`: that file's `modifiedTime` when it is the approving edit, else the time this run first saw the row Approved; `source`: "plan Sheet row"} and go on to gate 4. An approval set before this post was staged (the row read Approved while it was still Planned, Shot or Ready to build) approved a plan, not this post: set the row back to "Ready to post", hold as below, and say "re-approve after looking at it" in the approver notice. Not approved: **Hold**: stage (section 2), `POST` status `held_for_approval`, row "Ready to post", and add the post to `STATE/digest_notes.json` `awaiting_approval`; final message "Ready to post: <title> is staged and waits for a person to mark its plan row Approved." Never a question, never an escalation. |
| 4 | **Member's yes**: `posting.member_yes_required.value` is true and the post may show a member (any plan shot with `people: true`; for carousels and photos see section 12) | Every member shown must have a consent status of yes with a scope that covers this new post in `STATE/people.json` (or the Consent List row): `one_existing_post_only`, `no`, `unknown` or a child (until the owners decide) all fail. Missing yes: **Hold** as in gate 3 with `POST` status `held_member_yes` and the reason in the digest notes. |
| 5 | Otherwise | Post it (sections 2-7) at the planned time or the next slot (section 3). The approval in `POST` `approval` goes into the run log and the Sheet row's note. |

## 2. Stage the post

1. **Files:** `out/SLUG_reel.mp4` (passed check_output), `out/SLUG_cover.jpg`, `out/SLUG_copy.txt`, the Story set `out/SLUG_story_<N>.jpg|mp4`; their Drive `Finished/` links from `work/delivered.json`.
2. **Caption:** the option named on the copy file's `RECOMMENDED (option N)` line (the Director's pick in make-reel step 12), plus the `HASHTAGS:` line when the caption does not already end with it. Check it before anything goes out (R258, numa-caption skill): the first line is a plain searchable phrase (brand.json `captions.opening_rule`, e.g. "Cold plunge in Mobile, AL: ..."), 3-5 hashtags (`captions.hashtags.count`) with the base tags and, when it has a value, `captions.hashtags.community_tag`, at most 2,200 characters. Scan the final text once more:
   ```
   python3 "$S/claims_scan.py" --file "$JOB/work/caption_final.txt" --hashtags "<hashtags>" --json
   ```
   (`work/caption_final.txt` = the caption exactly as it will post.) Exit 1: take the next copy-file option that passes (log it); none passes: failure row F11 move 1 (rewrite) and scan again. The AI-label and MUSIC lines of the copy file are posting settings, never caption text.
3. **Post kind** from `work/plan_row.json` and plan.json: `kind` reel or trial_reel (plan `meta.trial_reel` true also means Trial Reel), `collab` (partner name; handle from brand.json `positioning.collab_partners`), `ai.label_required`, music source. Write all of it to `POST` (`status: staged`).
4. **Public video URL** (Meta fetches the video itself; the URL must be publicly fetchable, spec p.11):
   - **A. Composio file staging (first choice):** when the create tool's schema (COMPOSIO_GET_TOOL_SCHEMAS on INSTAGRAM_POST_IG_USER_MEDIA) has a file field, pass the local reel; Composio stages it and hands Meta a public URL.
   - **B. Drive public link:** share the `Finished/` reel as "anyone with the link: viewer" (Drive connector), use `https://drive.google.com/uc?export=download&id=<FILE_ID>`, and prove it serves the video: `curl -sIL "<url>" | grep -i "content-type"` must show `video/mp4` (an HTML page means the link is not public yet). Record the file id in `POST` `public_link` so section 7 can remove the sharing.
   - Neither works: failure row F15 move 1 (retry in 15 minutes), then section 9 (queue).
5. **Staged record.** Write `STATE/staged/<SLUG>.json` and upload it to Drive `_Plan/staged/` (a file only this post ever writes): `{"slug", "job": "<month folder>/<day folder>", "date", "post_type" (reel, trial_reel, carousel, image, story), "carousel_source"?, "canvas_url"? (a component carousel's carousel.json `canvas.url`), "title", "planned_time" (Central HH:MM, section 3), "finished": {"<file name>": "<Drive link>"}, "caption_file": "out/SLUG_copy.txt", "caption_final", "alt_text"?, "ai_label_required", "trial_reel", "collab", "shows_members", "tags": {the metrics tags of section 7 step 3 known now}, "status": "staged" | "held_for_approval" | "held_member_yes" | "queued" | "published", "staged_at"}`. Section 13 reads only this file and the Sheet, so a run on a fresh cloud machine can post the post days later. Update its `status` (and upload it) whenever `POST` changes; at `published` add `media_id` and `permalink`.

## 3. When to post (R257)

Planned time = the row's `post_time` in `STATE/plans/strategy_YYYY-MM.json` (the Strategist's blocked rotation, Central HH:MM), else `STATE/plans/plan_YYYY-MM.json` `posting_time` when /plan-month re-tuned it, else brand.json `posting.posting_time` (late afternoon Central: 5:00 pm). Instagram's API has no scheduled publishing, so, **only for an approved post** (section 1 gate 3):

- **Approved before the planned time:** stage now (section 2), then create a one-time scheduled task for the planned time, today, with the prompt "Run /post-reel <JOB> publish with the NUMA Studio plugin; never ask anyone anything; post only if the plan row still reads Approved." Log it and end this run. No way to create a one-time task in this run: publish now only when the planned time is less than an hour away, else leave it for the next re-check run (section 13), which posts it at its slot.
- **Approved after the planned time (or `publish` past it):** the **next slot** (config `approval.next_slot_rule`): the next posting time at least `approval.min_lead_minutes` away (today's when one is left, else tomorrow's row `post_time`, else the default posting time), never after `approval.latest_post_time` (9 pm Central), and `approval.min_gap_between_feed_posts_minutes` (2 h) from any other feed post that day. When the next slot is now (this run is inside its window), publish now (sections 4-7); otherwise create the one-time task for it as above. A Story set takes the next slot the same way.
- **Not approved:** nothing is scheduled; the post stays staged and section 13 re-checks it every scheduled run.
- A post whose moment has passed (an event teaser after its event, an offer after its end date, a closure-day line) is never posted late: row note "not posted: its date passed", digest heads-up, record `status: expired`.

## 4. Publish on Instagram through Composio (R253; spec p.47-48)

Every Instagram call sets `graph_api_version` = config `instagram.graph_api_version` (Composio's default version is retired; config `instagram.graph_api_version_rule`). Call the Composio tool directly when it is listed, else through COMPOSIO_MULTI_EXECUTE_TOOL with its slug; read field names from COMPOSIO_GET_TOOL_SCHEMAS each run. The IG user id comes from the connected account.

1. **Publishing limit first:** read the account's content publishing limit (the Instagram toolkit's publishing-limit tool, found with COMPOSIO_SEARCH_TOOLS, or COMPOSIO_PROXY_EXECUTE `GET /<ig-user-id>/content_publishing_limit?fields=quota_usage,config`) and count `STATE/post_log.json` entries in the last 24 hours. Usage plus this run's posts at or over config `instagram.publishing_limit_per_24h` (100 API posts per rolling 24 h): queue for tomorrow (section 9).
2. **Container:** reuse the container in `POST` only when it is younger than config `instagram.container_max_age_hours` (24 h; containers expire) and its status is not `EXPIRED` or `ERROR`; never reuse an older one. Else create a new one with **INSTAGRAM_POST_IG_USER_MEDIA**: `media_type` = config `instagram.media_type` (REELS), the staged video or `video_url`, `caption`, the cover (`cover_url` from the cover's public link when the schema has it), `share_to_feed` true. Trial Reel or collab invite: create the container through the Graph API instead (section 5). Save `container_id` and `created_at` in `POST`.
3. **Wait for processing:** config `instagram.publish_wait_minutes` (3-5 minutes). Wait 3 minutes (`sleep 180`), then read the container's `status_code` (COMPOSIO_PROXY_EXECUTE `GET /<container-id>?fields=status_code`): `FINISHED` -> step 4; `IN_PROGRESS` -> wait 1 minute and read again, up to 5 minutes in all, then section 8 row "not ready"; `ERROR` or `EXPIRED` -> section 8.
4. **Publish** with **INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH** (`creation_id` = the container id). Save the media id, then read its `permalink` and `timestamp` (COMPOSIO_PROXY_EXECUTE `GET /<media-id>?fields=permalink,timestamp,thumbnail_url`). `POST` status `published`. Publish the same day the container was made.
5. **Stories:** the day's Story set goes up after the reel the same way, one container per file with `media_type` STORIES (images by `image_url`, clips by `video_url`), each published after its processing wait. A Story that fails is logged and skipped; it never blocks the reel.

## 5. Trial Reels and collab invites (R254, R316; spec p.2, p.48)

Composio's Instagram tools expose neither, so (DECISIONS D8, both paths):

| Need | 1. Direct Graph API | 2. Claude in Chrome | 3. Neither works |
|---|---|---|---|
| Trial Reel (plan row `kind` trial_reel) | COMPOSIO_PROXY_EXECUTE (the connected Instagram account) `POST /<ig-user-id>/media` with the REELS fields of section 4 step 2 plus `trial_params` `{"graduation_strategy": "SS_PERFORMANCE"}` (shared to followers only if it performs with non-followers); then section 4 steps 3-4 | instagram.com in the signed-in Chrome profile: new reel, same file, cover and caption, switch on **Trial** before sharing | Do not post; row "Ready to post (Trial Reel)"; one line to Jude (section 8) |
| Collab invite (plan row `collab`) | Same proxy call with `collaborators` = `["<partner handle without @>"]` (up to 3) | instagram.com: **Invite collaborator** with the partner's handle before sharing | Do not post; row "Ready to post (collab)"; one line to Jude (section 8) |

A partner without a known handle (brand.json `positioning.collab_partners`, the private `STATE/people.json` `collab_handle`): post without the invite and name them by role or business in the caption's second line; log it. Record which path worked in `POST` (`trial_path`, `collab_path`) and in the Decisions log so the setup guide's "verify first" items get their answer.

**Chrome posting steps, only after approval (R342, D26).** When an **approved** post needs a Trial Reel, a collab invite or the AI label and the Composio/Graph path cannot do it, the "Claude in Chrome" column runs from the Mac's hourly **Chrome queue** task, never from a cloud run:
1. Sync the queue first: download Drive `_Plan/chrome_queue/` into `STATE/chrome_queue.drive/` and `python3 "$S/chrome_queue.py" merge-dir "$STATE/chrome_queue.drive" --state "$STATE"` (a failed download is never "absent": then queue nothing this run and say so in the run note).
2. Queue it at approval time, then upload the item file listed under `files` to Drive `_Plan/chrome_queue/`:
   ```
   python3 "$S/chrome_queue.py" add --kind trial_reel --payload '{"job": "<JOB>", "slug": "<SLUG>"}' --not-before <posting time - 75 min> --deadline <posting time> --fallback "Stays staged; the approver is told to post it from the Instagram app as a Trial Reel, or to approve it as a normal reel" --state "$STATE" --json
   ```
   `collab_invite` with `{"job", "partner"}` and the fallback "Stays staged; the approver is told to post it from the Instagram app with the collaborator, or to approve it without the invite"; `ai_label` with `{"job"}` and section 6 row 3 as the fallback, unchanged. The 75-minute window means the hourly :47 desktop run always lands inside it. Only that desktop task drains posting kinds, and it re-checks the approval before posting (commands/chrome-queue.md).
3. **At the posting time** (section 3's one-time task): sync the queue first (`merge-dir`). The item for this JOB is `done`: record the permalink from its `result` and stop. `pending` or `in_progress`: do **not** publish and do **not** expire it (only the 8 pm night check expires items, after a 60-minute margin; its fallback leaves the post staged and sends the approver one line). Never post it as a normal reel without a new approval.
4. **Never block:** a queued Chrome step never delays any other post.

## 6. The AI label (R255, R315; DECISIONS D8)

When plan `ai.label_required` is true (AI-animated people or AI-generated scenes; brand.json `posting.ai_label_rule`), the label must be on; a reel that needs it never posts without it.

1. **API:** when the create tool's schema or the Graph API media fields offer an AI-label flag, set it on the container (section 4 step 2 or section 5) and confirm it on the published media.
2. **Claude in Chrome:** post this reel through instagram.com instead (same file, cover, caption, Trial/collab settings), switching on **AI label** under Advanced settings.
3. **Neither** (or the queued `ai_label` item expired): do not post. Row "Ready to post (AI label)", files in `Finished/`, one line to Jude: "NUMA Studio: <title> needs Instagram's AI label, which the API can't set. Fix: post Finished/<file> from the Instagram app with Advanced settings > AI label on; caption in <copy file>."

The copy file's `MUSIC:` line asking for a Sound Collection track at posting follows the same three rows (API field if any, Chrome composer, else manual post plus one line to Jude).

## 7. After posting (R259)

1. **Sheet:** plan Sheet row Status `Posted` and Reel link = the Instagram permalink.
2. **Records:** `POST` and the `post` key of `work/delivered.json`: media id, permalink, `posted_at` (Central ISO 8601), container id, kind, `trial_reel`, `collab`, AI label on/off and how, Facebook result. Append to `STATE/post_log.json`.
3. **Insight pulls:** write the post's Numa tags (config `instagram.tags`: length, series, pillar, hook_type, transitions, music_source, posting_time, trial_reel, collab, boosted, `post_type` (reel or trial_reel), and the strategy tags `pattern_ids`, `strategy_arm` and `story_frames` copied unchanged from `work/script.json` or the plan row, plus title, slug, media_id, permalink, thumbnail) to `STATE/insights/tags_<media_id>.json`, then
   ```
   python3 "$S/metrics.py" tag --store "$STATE/metrics.json" --post <media_id> --tags "$STATE/insights/tags_<media_id>.json"
   ```
   Each published Story frame is tagged the same way with `post_type` story (and the day's `story_frames`). From here `metrics.py due` lists the post at each pull age (config `instagram.insight_pulls_hours`: Stories at 12 h and 22 h, never after 24 h; every other post at 48 h, 72 h, 7 d, 14 d and 30 d), and the pull runs (the 5 am build, the 12:40 pm Story task, the 8 pm night check and the 10 pm dashboard refresh) pull each with INSTAGRAM_GET_IG_MEDIA_INSIGHTS (account level: INSTAGRAM_GET_USER_INSIGHTS). Never request plays or impressions (config `instagram.never_request`).
4. **Facebook** (brand.json `posting.platforms`), same file and caption to the Page `socials.facebook`:
   1. Composio's Facebook toolkit when connected (find the Page video/reel tool with COMPOSIO_SEARCH_TOOLS);
   2. Claude in Chrome: Meta Business Suite > Create reel;
   3. neither: skip Facebook for this reel and add one line to `STATE/digest_notes.json` `heads_ups`. Facebook never blocks or delays Instagram. AI-labelled reels go to Facebook only where the label can be set (Meta Business Suite in Chrome).
5. **Close the public link:** remove the "anyone with the link" sharing from section 2 step 4 B.
6. **Final message** (the scheduled task's notification): "Posted: Day 07 - Your first plunge · <permalink>" plus "Facebook: posted" or the reason it was skipped, and "Approved by <by>". A statement, never a question.
7. **Staged record:** `STATE/staged/<SLUG>.json` `status: published` with `media_id` and `permalink`; upload it.

## 8. Errors, retries and Jude-only escalations

Send each escalation as one line to brand.json `escalation.contact` through `escalation.channel` (read from `STATE/brand.json`; an email address goes by Gmail when connected, anything else or no Gmail goes as the run's notification), at most once a day per kind, dated in `STATE/escalations.json`. Never to Katie.

| Error | What to do |
|---|---|
| Meta error 190 (token invalid or expired) | No retry. One line to Jude: "NUMA Studio: Instagram disconnected (Meta error 190). Fix: in the Composio dashboard, open the Instagram toolkit and reconnect Numa's Instagram (Business or Creator, Instagram Login)." Queue the post (section 9), row "Ready to post". |
| Rate limit (Graph codes 4, 17, 32, 613) or Composio 429 | Wait 15 minutes and retry, twice; then queue. |
| Composio or Meta unreachable, 5xx, timeout | Retry after 1, 5 and 15 minutes (failure row F15); then queue. |
| Container `ERROR` | Create one new container (fresh public URL); a second `ERROR`: queue and add a digest heads-up with Meta's error text. |
| Container `EXPIRED` or older than 24 h | New container; never publish the old one. |
| Publish says the media is not ready (code 9007) | Wait 1 minute and retry, up to 5 times; then queue (the next run makes a new container). |
| Publishing limit reached | Queue for tomorrow. |
| Any other 4xx naming a field (caption too long, too many hashtags, bad cover) | Fix that field once and retry; else row "Ready to post" and a digest heads-up. |
| Card declined on Claude or Higgsfield | Not a posting error; make-reel's escalation table covers it. |

Before any retry of a publish call, re-read `POST` and the account's latest media: if the reel is already live, record it and stop (no duplicates).

## 9. The queue

`STATE/post_queue.json`: `[{"job", "slug", "queued_at", "reason"}]`. Every /post-reel run drains it first, oldest first, at most 2 queued posts per run besides today's, each with a fresh container (section 4) and the same gates (section 1). A queued post older than 3 days leaves the queue: row "Ready to post", one digest heads-up line. Upload the queue and log to Drive `drive.plan_dir` at the end of every run.

## 10. Weekly: the Google Business Profile (R260)

On the first /post-reel run of each week (Monday, Central), post last week's best reel to the Google Business Profile (brand.json `socials.google_business_profile`, `posting.google_business_profile`):

1. Best reel: `python3 "$S/metrics.py" compute --store "$STATE/metrics.json" --json`, highest sends plus saves per 1,000 reach among last week's posts; fewer than 2 with a pull: most views; no pulls yet: the highest Critic total in the week's `work/critic_rounds.json`.
2. Claude in Chrome on the profile: an update with the cover image, the caption's first line and a "Learn more" button to brand.json `business.cta_link`, and the reach cut `SLUG_reach.mp4` (under 30 s) added to the profile's videos.
3. Record `{"week", "slug", "date"}` under `gbp` in `STATE/post_log.json`. Chrome unavailable: try again on the next run; still not done by Sunday: one digest heads-up line.

## 11. Done means

The post was approved by a person, is live on Instagram with the right settings (label, Trial, collab) and on Facebook or skipped with a reason; the Sheet says `Posted` with the permalink; the tags are in the metrics store; the public link is closed. Or it is staged, held or queued with the reason logged, the staged record is in Drive `_Plan/staged/`, and, only for the cases in section 8 and section 6, one line sent to Jude.

## 12. Carousels and single photos (R333, R335)

Same gates (section 1, in that order: `posting.auto_post.value`, human approval on the plan Sheet row (`posting.human_approval_required.value`, `posting.require_approval.value`, the `posting.see_first.value` types), the member's yes (`posting.member_yes_required.value`)), same posting time (section 3), same errors and queue (sections 8-9), same AI-label rule (section 6). Never ask Katie anything; a carousel or photo that cannot go out stays "Ready to post" with its files in `Finished/`. For the see-first types, "members" means any slide that may show a person: every photo_post.py slide whose `people_basis` (in `work/photo_post.json`) is anything other than `people_free_flag` or `library_tag_no`, and any component slide whose photo shows a person when you LOOK at it.

**0. Component carousel: re-render the canvas right before posting (DECISIONS D21).** When the staged record has `canvas_url` (a Claude Design canvas from the designer agent), right before step 3 run `python3 "$S/ensure_env.py" --json --with-chromium`, then send the **designer** (agents/designer.md, "Posting time"): it reads the canvas back with the Artifact tool (numa-carousel skill step 4) and renders it:
```
python3 "$S/design_render.py" canvas "$JOB/work/canvas" --out "$JOB/out" --slug SLUG --json
```
Exit 0: these slides (`SLUG_carousel_NN.jpg`, Katie's latest edits included) replace the staged ones; upload them to `Finished/`, rewrite the alt texts from the new `report.json` `design_render` slide `text`, and re-scan (step 2). The approval stands for the canvas as it is at posting time (D21: the canvas is the approved post's source; a person editing it is part of approving it), but a slide that now fails a check never posts. Read or render fails (Artifact tool not visible, Chromium missing, exit 1): post the staged slides already in `JOB/out` and log `fallback carousel.3`.

**1. The slides.** Photo carousels are built from a folder of photos, not only from a reel (R333): pick 2-10 photos (the day's Drive `drive.photos` folder, else the media library, else the bundled brand photos), then
```
python3 "$S/photo_post.py" carousel "$JOB/raw/photos" --out "$JOB/out" --slug SLUG --texts "$JOB/work/slide_texts.json" --json > "$JOB/work/photo_post.json"
python3 "$S/photo_post.py" single "$JOB/raw/photos/<best>.jpg" --out "$JOB/out/SLUG_photo.jpg" --text "<short line, *gold* word>" --json > "$JOB/work/photo_post.json"
```
Same grade, framing, safe areas and claims rules as the reels (1080x1350 JPG). People: face detection only ever says yes (it misses people lying down, backs, profiles, small figures), so every photo needs a recorded basis or the script stops with exit 1. LOOK at each photo first, then:

| What you see | Pass |
|---|---|
| Truly no people at all | `--people-free` (single), `--people-free <file name>` per photo (carousel); or a library tag `people no` (`--library "$STATE/media_library.json"`) |
| People, all with a yes on record whose scope covers new posts (`STATE/people.json` first, then `STATE/consent_list.json`; agents/librarian.md section 5) | `--consent`, or `--library` when the library records consent yes |
| People not on the list (no consent recorded either way), faces detected | `--blur-faces` (failure row F12), then LOOK that every face is blurred |
| People not on the list, no face detected | A different photo (`--blur-faces` cannot pass it: there is nothing it can find to blur) |
| Consent recorded as no (people.json, the Consent List or the library's `consent` no), anyone `do_not_feature`, a yes scoped `one_existing_post_only`, a child, or a never-film place (brand.json `consent.never_film`) | A different photo, always: never blurred, never posted; the script stops with "consent recorded as no: use a different photo" when the library records it |

Never pass `--people-free` for a photo you have not looked at. Exit 1 is a one-line ERROR with the fix; apply it and run again. LOOK at every slide before posting: any unlisted face means blur or a different photo. Component carousels arrive ready-made (`SLUG_carousel_NN.jpg`); post them as they are. Slide order = the number in the file name, read as a number. Checks per file: JPEG, 1080 wide, 4:5, at most 8 MB (Instagram's image limits); 2-10 slides for a carousel.

**2. Caption and alt text.** Caption from `out/SLUG_copy.txt` exactly as in section 2 step 2 (RECOMMENDED option, first-line rule, 3-5 hashtags, at most 2,200 characters, `claims_scan.py`); no copy file: write it with the numa-caption skill first. Alt text, one per image: LOOK at the slide and write `work/alt_text.json` `{"<file name>": "<alt text>"}`: what the picture shows, then the slide's on-image words verbatim, plain sentences, at most 1,000 characters (the API limit). Scan it with the caption:
```
python3 "$S/claims_scan.py" --file "$JOB/work/caption_final.txt" --file "$JOB/work/alt_text.txt" --hashtags "<hashtags>" --json
```
(`work/alt_text.txt` = the alt texts, one per line.) Write `POST` with `status: staged`, `post_type` (`carousel` or `image`), the slide list in order and the alt texts.

**3. Public image URLs** (Meta and Facebook fetch each image themselves):
- **A. Drive public link (first choice, `image_url`):** share each `Finished/` slide "anyone with the link: viewer", use `https://drive.google.com/uc?export=download&id=<FILE_ID>` (or any other direct HTTPS URL that serves the JPG itself) and prove it: `curl -sIL "<url>" | grep -i "content-type"` must show `image/jpeg` (an HTML page means the link is not public yet). Record the file ids in `POST` `public_links` (closed in step 7). Facebook always needs these URLs.
- **B. Composio file staging (fallback, `image_file`):** when no public URL works, INSTAGRAM_POST_IG_USER_MEDIA takes `image_file` (check COMPOSIO_GET_TOOL_SCHEMAS each run), a Composio file object `{"name": "<file name>.jpg", "mimetype": "image/jpeg", "s3key": "<key>"}`; `s3key` is the key a Composio action returned when it stored that file (for example a Google Drive file download run through Composio). Composio then hands Meta a temporary public URL. No `s3key` available: this path is closed.
- Neither: failure row F15 move 1, then section 9.

**4. Limits and containers.** Read the publishing limit first with INSTAGRAM_GET_IG_USER_CONTENT_PUBLISHING_LIMIT (`fields` `quota_usage,config`) plus `STATE/post_log.json`: a carousel counts as **one** post, like a reel or a photo; at or over config `instagram.publishing_limit_per_24h`: queue for tomorrow. Every call sets `graph_api_version` = config `instagram.graph_api_version`. Containers (children and parent alike) live at most config `instagram.container_max_age_hours` (24 h): reuse one from `POST` only when younger and not `ERROR`/`EXPIRED`, and make and publish them in the same run. A container's state: COMPOSIO_PROXY_EXECUTE `GET /<container-id>?fields=status_code`. INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH also waits for `FINISHED` itself: its `max_wait_seconds` (default 60, at most 300) is that status wait; keep it at 60 or more and never 0 unless the status was just read as `FINISHED`.

| Post | Instagram calls, in order |
|---|---|
| Single photo (IMAGE) | 1. **INSTAGRAM_POST_IG_USER_MEDIA** with `image_url` (else `image_file`), `caption`, `alt_text`, and no `media_type` (an image alone is an IMAGE container; the tool's `media_type` list has only REELS, CAROUSEL and STORIES). 2. Status `FINISHED` (images are usually ready at once; else wait 1 minute, up to 5). 3. **INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH** with `creation_id` = the container id. |
| Carousel (2-10 slides) | 1. One child per slide, in slide order: **INSTAGRAM_POST_IG_USER_MEDIA** with `image_url` (else `image_file`), `is_carousel_item` true, `alt_text` (no caption on children); save each child id in `POST` `children`. 2. Every child `FINISHED`. 3. The parent: **INSTAGRAM_POST_IG_USER_MEDIA** with `media_type` CAROUSEL, `children` = the child ids in slide order, `caption` (no `alt_text`: the parent takes none). When that call is refused, **INSTAGRAM_CREATE_CAROUSEL_CONTAINER** with the same `children` and `caption`. 4. Parent `FINISHED`. 5. **INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH** with `creation_id` = the parent id. |

Then read `permalink` and `timestamp` (COMPOSIO_PROXY_EXECUTE `GET /<media-id>?fields=permalink,timestamp,media_type`); `POST` status `published`. Only after section 1's gates (approval on the plan Sheet row, re-read now) passed in this run.

**5. AI label.** Required when any slide's picture was made or animated by AI (a Higgsfield image, `ai_generated` in its source record). INSTAGRAM_POST_IG_USER_MEDIA has no AI-label field, so section 6 rows 2-3 apply: Claude in Chrome (instagram.com, the same images in order, caption, alt texts under Advanced settings, **AI label** on), else do not post and send Jude section 6's one line naming the carousel. After any post, INSTAGRAM_GET_IG_MEDIA with `fields` `is_ai_generated` records the label state in `POST`.

**6. Retries and duplicates.**
- Before creating anything and before every publish retry: re-read `POST` (status `published`: stop), then list the latest posts with INSTAGRAM_GET_IG_USER_MEDIA (`fields` `id,caption,media_type,timestamp,permalink`); a `CAROUSEL_ALBUM` or `IMAGE` from the last 24 hours whose caption starts with this caption's first line is this post: record its id and permalink, status `published`, stop. Never publish the same carousel or photo twice.
- A child container `ERROR`: make that one child again once (fresh public URL); a second `ERROR`: queue the post with Meta's error text. The parent `ERROR` or any child older than 24 h: make every child and the parent again; never publish an old container.
- Publish says not ready (code 9007): wait 1 minute and retry, up to 5 times, then queue. Error 190, rate limits, 5xx and timeouts: section 8, unchanged.

**7. After posting.**
1. **Sheet:** the plan row's Status `Posted` and its link column (Reel link) = the permalink.
2. **Records:** `POST` and `work/delivered.json` `post`: media id, permalink, `posted_at` (Central ISO 8601), `post_type`, child and parent container ids, AI label on/off and how, Facebook result. Append `{"date", "media_id", "slug", "kind": "carousel"|"image"}` to `STATE/post_log.json`.
3. **Metrics:** write the tags with `post_type` (`carousel` or `image`; metrics.py accepts reel, carousel, image, story, trial_reel) plus title, slug, media_id, permalink, posting_time, series, pillar, hook_type, and `pattern_ids`, `strategy_arm` and `boosted` copied unchanged from the plan row or script.json, to `STATE/insights/tags_<media_id>.json`, then
   ```
   python3 "$S/metrics.py" tag --store "$STATE/metrics.json" --post <media_id> --tags "$STATE/insights/tags_<media_id>.json"
   ```
   Pulls follow at 48 h, 72 h, 7 d, 14 d and 30 d as for reels (config `instagram.insight_pulls_hours`); carousels and photos have no watch time or skip rate, and metrics.py and the dashboard show those as blank.
4. **Facebook mirror** (brand.json `posting.platforms`) to the Page `socials.facebook` (its id from FACEBOOK_LIST_MANAGED_PAGES): a carousel with **FACEBOOK_CREATE_MULTI_PHOTO_POST** (`page_id`, `photo_urls` = the Drive public links in slide order, `message` = the caption); a single photo with **FACEBOOK_CREATE_PHOTO_POST** (`page_id`, `url`, `message`). No Facebook connection: Claude in Chrome, Meta Business Suite > Create post with the same images in order; neither: skip Facebook and add one line to `STATE/digest_notes.json` `heads_ups`. Facebook never blocks Instagram; an AI-labelled post goes to Facebook only where the label can be set.
5. **Close the public links** from step 3 B.
6. **Final message:** "Posted: <title> (carousel, 6 slides) · <permalink>" or "Posted: <title> (photo) · <permalink>", plus the Facebook result. A statement, never a question.

## 13. Approval re-check (`approvals`; DECISIONS D26)

Run by the 8 pm night check, the 10 pm dashboard refresh, the 12:40 pm Story task and, on the Mac, the hourly Chrome queue task (config `approval.recheck_in`). It never asks anyone anything and never waits.

1. **Sync.** Download Drive `_Plan/staged/` (one file per staged post) into `STATE/staged/` (a failed download is never "absent": then skip this section this run and note it). Read the plan Sheet rows (this month's tab, and last month's in the first week) through the Google Sheets connector, fresh, never a cached copy.
2. **For each staged record** with `status` staged, held_for_approval or held_member_yes, oldest first:
   - Its row reads **Approved** (`Approved` or `Approved - <name or initials>`, set after the post was staged; section 1 gate 3): rebuild `JOB` on this machine when it is not here (download the day folder's `Finished/` into `JOB/out/`, write `JOB/work/post.json` from the staged record), then run this command for `JOB` (sections 1-12): the gates are re-checked, and it posts at the planned time or at the next slot (section 3).
   - Its row still reads `Ready to post`: leave it staged; it goes on the approver notice (step 4) and the digest's "Waiting for approval".
   - Its row reads `Posted`, or the record is older than config `approval.stale_after_days` (7) with its moment passed: close it (`status: expired` or `published`), one digest heads-up line for an expired one.
3. A row marked Approved whose post was never built (no staged record): nothing to post yet; the build stages it and asks for a fresh approval.
4. **One notice per run, never one per post.** Collect every post newly waiting for approval since the last notice (`STATE/approval_notices.json`) plus any approved post that could not go out (an expired Chrome item, a failed gate). Nothing new: no notice. Otherwise send **one** line to the approver: brand.json `posting.approver.value` once the owners name one; until then the owners and the social media lead, by role (config `approval.notify_until_approver_named`), through the approval channel /numa-setup stored in `STATE/setup.json` `approval_notify` (an email list sent by Gmail when connected; else the line goes in this run's final message, which reaches the owners' phones when the task's notifications are on, and in `STATE/digest_notes.json` `awaiting_approval`). Example: "Waiting for approval (2): Tue Dec 8 Sauna vs red light (carousel, 4:30 pm); Wed Dec 9 Your first plunge (reel, 5:00 pm). Mark a plan row Approved to post it; files in each day's Finished/." A statement, never a question. Record the posts named and the time in `STATE/approval_notices.json` and upload it to Drive `_Plan/`.
5. Upload every staged record this run changed to Drive `_Plan/staged/` (only those files).
