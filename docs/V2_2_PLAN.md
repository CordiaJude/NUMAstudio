# NUMA Studio v2.2 plan: from content studio to complete social media manager

Status: planned 2026-11-14, approved in principle by Jude. Build starts after v2.1 ships (v2.1 = Claude Design carousels, photo posts, scheduling reliability, adaptive strategy, owners' answers).

Goal: do the work around the posts that a real social media manager does: get approvals fast, answer people, prove that posts bring members, run Stories, Google, collabs, events, consent, reporting, and the extra channels. Everything keeps the existing rules: Numa's facts from brand.json, the claims scanner on every word, consent before any person, **nothing goes out without a person approving it (D26)**, nobody is asked questions during a run except through the approval inbox, escalations to Jude only (or to the owners where the item is theirs, e.g. a complaint).

## Design rules for the crew

1. **One job family per agent.** An agent owns one kind of work and the scripts behind it. If a job needs two very different skills (e.g. writing replies and judging a crisis), it is two agents.
2. **Scripts do anything exact** (classifying by rule, scheduling, link checks, money, numbers, consent lookups); agents do judgment and writing.
3. **Every outward action goes through the approval inbox** (posts, replies, review responses, collab messages, emails). Agents draft; people approve; the Publisher sends.
4. **The Director stays the conductor, not a worker.** In v2.1 the Director still does posting itself; in v2.2 posting moves to the Publisher so the Director only plans, delegates and judges.
5. **Model tiers in config** (`models.agents.*`), small/mid/top as today.

## The crew after v2.2

Existing (unchanged job): Director, Librarian, Scout, Analyst, Scriptwriter, Motion, Editor, Copywriter (gains alt text), Critic, Designer, Strategist.

New agents:

| Agent | Tier | Owns | Does not do |
|---|---|---|---|
| **Publisher** | small | The approval inbox, link/CTA health checks, posting to Instagram/Facebook (and TikTok/YouTube/email when enabled), the Chrome posting queue items, posting-time re-renders. | Write or judge content. Reply to people. |
| **Community Manager** | mid | Instagram and Facebook comments and DMs: triage (by script), draft replies in Numa's voice, send approved replies, log questions as content ideas. | Google reviews, complaints that look like a crisis (hands to Reputation Manager). |
| **Reputation Manager** | mid | Google Business Profile (weekly posts, review alerts, review reply drafts, search insights) and crisis handling: negative reviews, angry comments, safety or medical complaints, anything legal-sounding, routed to the owners with a suggested reply. | Everyday comments. |
| **Growth Analyst** | mid | Attribution: Mindbody weekly totals (read-only, no names), tracked links per post/campaign, "how did you hear about us" data; the monthly owner report. Feeds bookings into the Strategist. | Change the plan (that's the Strategist). |
| **Stories Producer** | small | The daily Story set (open slots, polls, countdowns, reshares with link stickers, member moments), Story metric capture before 24 h. | Feed posts. |
| **Partnerships Manager** | mid | Partner and collab register, outreach drafts, collab invites, creator briefs with FTC disclosure, event co-hosts, results per partner. | Event content itself (Scriptwriter/Editor make it). |
| **Consent Clerk** | small | The member consent workflow: consent form, sync with Doc 04 into private `STATE/people.json`, per-post people check before approval, consent expiry and withdrawals. | Decide what to film. |

Event campaigns, repurposing to other channels, email drafts and alt text need no new agent: they are planner rules (Strategist + plan-month), format jobs (Editor), and copy (Copywriter), each a small, bounded addition.

Load check (what each agent touches per day, typical): Publisher 1–3 posts + 1 inbox sync; Community Manager 0–20 comments/DMs; Reputation Manager 0–3 reviews + 1 GBP post a week; Growth Analyst 1 daily pull + 1 monthly report; Stories Producer 1 set of 2–5 frames; Partnerships Manager 1–3 items a week; Consent Clerk 0–5 checks a day. No agent has more than one daily duty and one periodic duty.

## Features, in build order

### Phase A: foundations (everything else depends on these)

**T20 Approval inbox + Publisher (v2.2 item 1).**
- Inbox lives on the plan Google Sheet as an "Approvals" tab built for a phone: one row per item (post, reply, review response, collab message, email), thumbnail/preview link to the Drive file, the caption or text, the reason, deadline, and a dropdown Approve / Edit (with a note) / Skip. Sheets works from every scheduled cloud run; a richer artifact inbox page is a later option once it is verified that scheduled runs can read its data.
- One notification per batch to the approver (who is an open question; default the owners or the social media lead), never one per item.
- Publisher reads decisions each run: Approve → posts at the planned time (or next slot); Edit → back to the crew with the note, re-staged; Skip → archived, and the Strategist logs it. Unapproved items past their deadline roll to the next slot once, then drop and appear in the digest.
- Posting moves from the Director to the Publisher (post-reel becomes the Publisher's procedure). Re-render of Claude Design carousels right before posting stays (D21).
- Approval times are logged so the system can learn when the approver usually responds and schedule staging earlier.

**T21 Link and CTA health check (item 4).**
- Before staging and again right before posting anything with a call to action: check linktr.ee/numawc loads, its Discover Numa and Numa Reset entries resolve, and the booking page answers. Broken → the post is held, the fix goes to Jude and the social media lead in one line, the post is not published with a dead link.
- Weekly scan of all brand.json links.

**T22 Consent Clerk + consent workflow (item 8).**
- A short consent form (Google Form) members fill on their phone or at the desk: name, what may be used (photo, video, words, first name), where (Instagram, Facebook, Google, email), AI editing yes/no, kids (parent's yes), expiry. Answers land in a Sheet; the Clerk syncs them and Doc 04 into private `STATE/people.json` (schema from v2.1).
- Every staged item with a person passes the Clerk's check before it reaches the inbox; withdrawals remove pending items and list posted ones for the owners to take down.
- "Member moment" checklist for staff (what to capture, never-film zones, ask first).

### Phase B: conversations and proof

**T23 Community Manager (item 2).**
- Daily (and after each post's first hours): pull comments and DMs through Composio (needs the comments/messages permissions on the Instagram connection; verify scopes first).
- Triage by script into: question (price, hours, what to bring), booking intent, praise, member chat, complaint, spam, health/medical question. Complaints and medical questions go to the Reputation Manager.
- Drafts replies in Numa's voice (facts from brand.json, claims scanner, no emojis, "Numa"), into the inbox. DMs carry Meta's 24-hour reply window as the deadline.
- Saved replies for the top questions so approval is one tap; repeated questions become content ideas for the Strategist.

**T24 Reputation Manager: Google Business Profile + crisis (items 6 and crisis).**
- Google Business Profile through Composio (needs the owners' Google Cloud login and Google's Business Profile API approval; Chrome fallback): weekly post from the week's best content, review alerts, reply drafts into the inbox, monthly search insights to the Growth Analyst.
- Crisis rules (script): 1–2 star reviews, safety/injury/medical complaints, legal words, pile-ons → immediate one-line alert to the owners with a calm suggested reply; nothing is posted without them; Jude is told if a system failure caused it.

**T25 Growth Analyst: attribution + monthly owner report (items 3 and 10).**
- Mindbody through Composio, read-only, weekly totals only (Discover Numa sales, first visits, memberships by type, source if recorded); never names.
- Tracked links: a unique tracked link (UTM) per campaign behind the one bio link; Linktree link-level clicks if available; "how did you hear about us" field added at booking (owners' action).
- Bookings per 1,000 reach by campaign and week (R6 says too sparse per post) feed the Strategist's goals in the owners' order (memberships, trials, events, followers).
- Monthly owner report (Google Doc, one page): members and trials gained, what brought them, top posts, what the system learned and will change, open questions. Separate from the Monday digest.

### Phase C: more content work, bounded

**T26 Stories Producer (item 5).**
- Daily Story set from the day's plan: open-slot frame (from Mindbody availability if connected), poll or question sticker, countdown for events, reshare of the latest post with the linktr link sticker, a member moment when consent allows. Frame 1 is the strongest (R1: 23.8% exit on frame 1).
- Story metric capture 20–23 h after posting (R7): a small cloud task several times a day captures any Story in that window; numbers feed metrics.json.

**T27 Partnerships Manager + event campaign autopilot (items 7 and 9).**
- Partner register in private STATE (AMP and the providers who collab, their handles, terms, posting rules, results).
- Collab flow: brief (what, when, FTC disclosure, claims rules), invite through the Chrome queue after approval, results per partner, follow-ups drafted into the inbox.
- Event autopilot: for each confirmed event in brand.json the planner schedules teaser (T−7 to −10), reminder (T−3), day-before and day-of Stories, recap within 48 h with the next date; unconfirmed events are never promoted.

**T28 Channels and accessibility (later items).**
- TikTok and YouTube Shorts: the Editor exports the platform versions (already partly in formats.py), the Publisher posts after approval, only if Numa has those accounts (open question); metrics come back into the store.
- Email: the Copywriter's email paragraph becomes a draft in the owners' email tool (open question which) for approval.
- Alt text: the Copywriter writes alt text for every photo and carousel slide; the Publisher sends it.
- Paid boosts: not built until website tracking exists (owners' rule); when it does, read-only Meta Ads insights first.

### Phase D: integrate and prove

**T29 Integration, docs and end-to-end proof.** Wire all commands and scheduled tasks (add: approvals sync, community check, story capture, weekly GBP, monthly owner report), update PROJECT_INSTRUCTIONS, SETUP_GUIDE, Katie's Guide (how to approve from her phone), README, CONTRACTS, config; a full simulated week with mocked connectors through every new path; independent review; version 2.2.0.

## What the owners or Jude must provide (blocks the matching feature only)

| Needed | For | Owner |
|---|---|---|
| Who approves, on which phone | T20 | Scott and Katie |
| Instagram comment and message permissions on the Composio connection | T23 | Jude |
| Mindbody API access (developer account, site activation, per-call fee OK) | T25, T26 open slots | Scott |
| "How did you hear about us" field at booking | T25 | Scott/Katie |
| Google Business Profile manager access, Google Cloud login, Business Profile API approval | T24 | Scott/Katie + Jude |
| Doc 04 location; OK to use a consent form | T22 | Scott and Katie |
| Whether Numa has TikTok and YouTube accounts | T28 | the social media lead |
| Email tool | T28 | Scott and Katie |
| Where partner agreements live (AMP terms) | T27 | Scott |

Every feature ships with a working "not connected yet" mode: the plugin keeps running and says in the digest what turning it on would add.

## Scheduled tasks after v2.2

Existing 8 (v2.1) plus: approvals sync (several times a day, cloud), community check (twice daily, cloud), Story capture (every few hours, cloud, lightweight), Google weekly (cloud), monthly owner report (1st of month, cloud). The Publisher's posting runs inside the approvals sync, so no separate posting task is needed.

## Risks and how the plan handles them

- **Approval fatigue** → one batched notification, one-tap rows, saved replies, deadlines that roll once then drop.
- **Meta API limits and permission changes** → every Composio call has a Chrome fallback where one exists, and a clear "not connected" mode.
- **Privacy** → people data only in private STATE; Mindbody totals only; no names in metrics or reports.
- **Agent overload** → the load table above is a requirement; T29's review checks each agent's daily work against it.
