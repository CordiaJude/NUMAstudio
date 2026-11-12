---
description: The one-time brand questionnaire (Katie's 51 setup answers, spec p.54-57) and later brand edits - writes each answer into the exact brand.json key, flips it from needs_katie to confirmed, validates brand.json and saves it where every run reads it
argument-hint: "[all | group A-H | Q12 | key path like posting.auto_post | path to a filled answers file] (empty = every unanswered question)"
model: opus
---
# /brand-setup: Katie's answers become brand data

brand/brand.json is the single source of truth for the brand (spec p.29 addition #1; docs/CONTRACTS.md section 6). This command fills it from the setup questionnaire and is the **only** place in NUMA Studio where questions are asked (spec p.54: "These are the only questions the system ever asks, and they're asked once"). Every other command decides on its own and never asks Katie anything.

Who and when: Jude runs it at setup (or right after /numa-setup), with Katie's answers. Short answers are fine; "don't know" is fine too.

| Name | Path |
|---|---|
| `S` | `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts` |
| `BRAND` | `${CLAUDE_PLUGIN_ROOT}/brand/brand.json` |
| `STATE` | `~/NUMA Studio/_Plan` |

## 1. Where the answers come from (first match wins)

1. `$ARGUMENTS` is a file or a Google Doc link: Katie's filled copy of docs/QUESTIONS_FOR_KATIE.md. Read every "Answer:" line; ask live only the questions left blank.
2. `$ARGUMENTS` is a group letter (A-H), a question (`Q12`) or a key path: edit mode for just that (section 3).
3. Empty or `all`: ask live, one group per message, in the order of section 6.

**Asked once.** Record what was asked and when in `STATE/brand_setup.json` (`{"date", "answered": [1, 2, ...], "dont_know": [9, ...]}`, also uploaded to Drive `drive.plan_dir`). A question listed there, or whose keys are all `confirmed` already, is never asked again; only edit mode (section 3) changes it later.

**How to ask live.** Send one group at a time with every question of the group, numbered as in section 6, worded exactly as written there. Wait for the whole group's answers, write them (section 2), then send the next group. Never add questions of your own, never ask a follow-up beyond one short clarification when an answer cannot be written at all (an unreadable price, a hex code with 5 digits). A vague answer is written as given, with a note.

## 2. Writing an answer

Every key in section 6 is a fact `{"value", "status", "source", "note"}` (except `claims.banned`, a plain list of rules, and `claims.dosing_line`, which keeps its own fields). For each answered question:

1. Write `value` in the shape section 6 gives, in Katie's words where it is text (fix spelling only).
2. `status`: `confirmed`.
3. `source`: `"Katie, /brand-setup YYYY-MM-DD (Q<n>)"`.
4. Keep `note` when it still applies; add what she qualified ("prices change in January").

**"Don't know", blank or skipped:** keep the current value and status (the research value stays in use; a `needs_katie` value is never stated as fact), add `note`: `"Q<n>: Katie did not know (YYYY-MM-DD)"`, and list it under "Still open" in the summary. The defaults in the last column are what the runs do meanwhile; the spec's defaults are children never (Q27), auto-post yes (Q34), see-first none (Q35).

**Rules that override an answer:**

| Answer | Rule |
|---|---|
| Q34 "post automatically" | `posting.auto_post` true never bypasses `posting.legal_review_done`; auto-posting stays gated until counsel's review is recorded (section 3) |
| Q35 types to see first | Those types are held as "Ready to post" by /post-reel; `posting.require_approval` becomes true only when she wants **every** reel held |
| Q24 a claim she was told not to make | Add a `claims.banned` rule (see below); never remove or weaken an existing rule |
| Q27 children | Anything short of a clear "yes, with a parent's written consent" stays `never` |
| Q28 cloned voice | `consent.voice_clone` true only with the 1-minute sample recorded and her written consent row on the Consent List (scope `voice clone`) |
| Q46 red light | Never write "FDA-approved" or "FDA-cleared" into any say-line, whatever the answer |
| Q47 the 57/11 line | `claims.dosing_line.blocked` stays true; only counsel's OK unblocks it (section 3) |
| Q48 consent coverage | true only if the signed form's wording covers it |
| Q17 fonts | A new font needs its files under `skills/numa-reel-editor/assets/fonts/` and a license; without them keep the current fonts and note her choice |

**New claims rule (Q24).** For each claim: `{"id": "<snake_case>", "label": "<plain words>", "severity": "fail", "patterns": ["<python regex>"], "applies_to": "all"}` (exactly these keys: the schema rejects any other, so record where each rule came from in `STATE/brand_setup.json` `claims_added` [{"id", "question": 24, "date"}] and in the summary); patterns are case-insensitive regexes with word boundaries (`\\bimmune\\s+boost\\w*`). Prove each one: `python3 "$S/claims_scan.py" "<the claim in her words>"` must exit 1, and a harmless sentence about the same room must exit 0.

**Closures (Q3, Q16).** Also add one row per date to the Closures Sheet (brand.json `closures.location`; columns Date, Name, Note).

## 3. Brand-data edits (addition #1)

The same command changes any brand value later, outside the questionnaire: colours, fonts, logos (light and dark), the end-card tagline and sign-offs (`endcard`), hashtags (`captions.hashtags`), transcript fixes, prices, offers, events, team, partners. `$ARGUMENTS` names the key or the topic ("new logo", "price change"); change only that, with `status`, `source` and `note` as in section 2, then validate and save (section 4).

**Opening the auto-posting gate.** When counsel has reviewed the claims policy, Jude runs `/brand-setup posting.legal_review_done`: set `value` true, `status` confirmed, `source` "<counsel name>, review dated YYYY-MM-DD", and the reviewed brand.json version in `note`. Counsel's written OK of the 57/11 line (Q47) is the only thing that sets `claims.dosing_line.blocked` to false.

## 4. Validate and save (every time)

1. Validate brand.json against schemas/brand.schema.json (and compile every claims pattern); validate `STATE/brand.json` the same way with `NUMA_BRAND` pointing at it:
   ```
   python3 "$S/setup_check.py" --skip-render --json
   NUMA_BRAND="$STATE/brand.json" python3 "$S/setup_check.py" --skip-render --json
   ```
   The `brand.json` check must be `pass`; on `fail` its detail names the field (e.g. `palette.value.cream`). Fix it and run again. Never leave brand.json invalid: every script refuses to run on it.
2. Save it where every run reads it:
   - `STATE/brand.json` (the run-time copy, DECISIONS D18: run commands point `NUMA_BRAND` at it when it is newer than the bundled file), uploaded to Drive brand.json `drive.plan_dir` as `brand.json` so cloud runs get it at once;
   - `BRAND` (the installed plugin's brand.json, without `escalation.channel`; scripts read it through `numa_common.load_brand()` when `NUMA_BRAND` is not set);
   - Jude commits the same file to the plugin's GitHub repo (the marketplace source, spec p.13 step 2) so reinstalls carry the answers, **without** `escalation.channel` (a private address lives only in `STATE/brand.json`, never in the public repo).
3. Summary for Jude: answered, still open ("don't know" list with question numbers), rules applied, new claims rules, and the brand.json line from step 1.

## 5. Status meaning (docs/CONTRACTS.md section 6)

`confirmed` (Katie or the brief confirmed it) · `from_website` · `research` · `needs_katie` (never stated as fact; may be null) · `bundled` · `generated`. Only this command and Jude's edits move a value to `confirmed`.

## 6. The 51 questions (spec p.54-57), grouped as in the spec

### A. The business (Q1-Q12)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 1 | How do you write the name: NUMA, Numa, or NUMA Wellness Collective, and when? | `business.name_usage` | value = the rule in one line ("NUMA in captions; NUMA Wellness Collective in the bio and on first mention"); `business.name` full/short change only if she says so | keep: NUMA short, NUMA Wellness Collective full |
| 2 | Address, the area of Mobile you're in, and how people describe where you are. | `business.location` | value.address, value.street, value.zip, value.area, value.district; add value.described_as (her words) | keep the research address |
| 3 | Regular hours, and every closure or holiday you already know about for the next 6 months. | `business.hours`, `closures.known` | hours: value.regular {mon..sun: "5:30 AM-8 PM"}; closures: value = [{"date": "YYYY-MM-DD", "name": "..."}] and one row each in the Closures Sheet | keep "opens 5:30 AM Mon-Thu"; closures: US holidays only |
| 4 | Every service and its price: memberships, drop-ins, class packs, 1-on-1s, and what's included in each. | `offerings.sessions`, `offerings.memberships` | each session's `price` fact {value, currency} confirmed; memberships value = [{name, price, includes}] | keep; never state a price that is not confirmed |
| 5 | Discover NUMA ($49): exactly what's included, how long it lasts, and where people sign up (which link)? | `offerings.offers`, `business.booking` | the Discover NUMA item: what, length, price, link; `business.booking` value.trial_page = the link | keep $49 / one month / discover.numawellness.org |
| 6 | Numa Nights and Clinical Conversations: how often, who leads them, what happens, and the next dates. | `offerings.events` | each event's `details` fact: {how_often, leads, what_happens, next_dates: [YYYY-MM-DD]} | keep names only; no dates in reels |
| 7 | Who's on the team: names, roles, and who's comfortable being on camera. | `team.collective`, `team.on_camera` | collective items {name, role, credentials}; on_camera value = {yes: [names], no: [names]} | keep research list; on camera: nobody named |
| 8 | The founding story in your words: why NUMA, the old house, the opening date, the hardest moment. | `business.founding_story` | value = {why, old_house, opening_date, hardest_moment} in her words | null: no founding-story reels |
| 9 | What makes NUMA different from every other gym, spa or studio in Mobile? | `positioning.differentiator` | value = 1-3 short lines in her words | keep `positioning.own_in_mobile` research |
| 10 | Who do you see most at NUMA (age, life stage, why they come), and who do you want more of? | `positioning.target_audiences` | value = list of audiences, the ones she wants more of first, each "who - why" | keep the research list |
| 11 | The top three reasons people join, and the top three reasons people hesitate (cold fear, price, time, "not for me"). | `positioning.join_reasons`, `positioning.hesitations` | two lists of 3 short strings | null: scripts answer the common worries (cold, price, time) only in general terms |
| 12 | Any member stories you love, and would those members agree to be featured? | `positioning.member_stories` | value = [{who, story, agrees}]; a story is used only when that member is also on the Consent List | none |

### B. Goals (Q13-Q16)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 13 | What should these reels do in the next 90 days: more trials, more memberships, fuller events, more followers? Rank them. | `positioning.goals_90d` | value = ranked list, first = most important | null: /plan-month keeps the content mix and one sales reel a week |
| 14 | Which offer matters most right now? | `offerings.priority_offer` | value = the offer name exactly as in `offerings.offers` | Discover NUMA |
| 15 | Is anything full (classes at capacity) that you should not promote? | `offerings.do_not_promote` | value = list of names; /plan-month never schedules a sales reel for them | empty list |
| 16 | What's coming in the next 3 months: launches, new services, events, price changes, anniversaries? | `offerings.upcoming`, `offerings.events` | upcoming value = [{date, what}]; a recurring event also goes into `offerings.events`; a closure also into `closures.known` | empty list |

### C. Brand and taste (Q17-Q24)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 17 | Do you have official brand colors (codes) and fonts? Who made your logo, and are there light and dark versions? | `palette`, `fonts`, `assets.wordmark_light`, `assets.logo_credit` | palette value = #RRGGBB per colour; fonts only with font files and a license added under assets/fonts (else keep Liberation Serif, note the wish); a light logo file goes to assets and its path into `assets.wordmark_light` | keep the research palette, Liberation Serif, dark wordmark only |
| 18 | Show us 3 Instagram accounts whose videos you love, and say what you love about each. | `voice.inspiration_accounts` | value = [{handle, what_she_loves}] | none |
| 19 | Anything you dislike seeing in wellness content (too salesy, too clinical, too "influencer")? | `voice.dislikes` | value = list | null: the voice description rules apply |
| 20 | Words you always use, and words you never want used. | `voice.words_always`, `voice.words_never` | two lists; every never-word is also checked by the Critic | none |
| 21 | What do you call the people who come: members, community, the collective? | `voice.community_word`, `captions.hashtags.community_tag` | community_word = her word; a hashtag she already uses becomes community_tag ("#...") | members; community_tag stays null (captions use the 3 base tags) |
| 22 | Emojis in captions: yes, a few, or none? | `voice.emoji` | value = "none" or "0-2 per caption, earthy only" or her rule | 0-2 per caption, earthy only |
| 23 | Music you picture under NUMA videos (calm piano, ambient, acoustic, upbeat), and anything you never want. | `voice.music_taste` | value = {love: [...], never: [...]} | null: calm instrumental beds, licensed only (`posting.music_rule`) |
| 24 | Topics that are off-limits, and anything a lawyer, doctor or insurer has told you not to claim. | `voice.off_limits_topics`, `claims.banned` | topics list; each claim she was told not to make becomes a new `claims.banned` rule {id, label, severity: fail, patterns} (see section 2) | none beyond the existing claims policy |

### D. People and consent (Q25-Q28)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 25 | Is there a consent or photo release for members today? If not, can one be added to sign-up? | `consent.release_form` | value = {exists, where, can_add} | null: no member face without a Consent List row |
| 26 | Who on the team may appear in videos, and who may not? | `team.on_camera` | value = {yes: [names], no: [names]} | nobody named: no team faces |
| 27 | Are children ever at NUMA, and should they ever appear? (Default: never.) | `consent.children` | value = "never" unless she clearly says otherwise | never |
| 28 | Will you record voiceovers yourself? Would you allow a cloned version of your voice for days you don't record? | `team.voiceover`, `consent.voice_clone` | voiceover value = who records; voice_clone value = true only with a recorded sample and written consent in the Consent List (scope `voice clone`), else false | voice_clone false: preset voice or text-only reels |

### E. Filming (Q29-Q31)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 29 | Who will film: you, staff, or both? Which phone? | `team.filming` | value.who, value.phone | null: shoot cards are written to whoever films |
| 30 | Best times for a 20-minute batch shoot each week, and when the light is best in each room. | `team.filming` | value.batch_times, value.best_light {room: time} | null: shoot cards batch by room, no set time |
| 31 | Any rooms or moments that should never be filmed? | `team.filming` | value.never_film = list | null: the consent rules decide who appears |

### F. Accounts and posting (Q32-Q38)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 32 | Is NUMA's Instagram a Business or Creator account, and is it linked to the Facebook Page? Who's the admin? | `socials.instagram_account`, `socials.facebook` | instagram_account value = {type, facebook_page_linked, admin}; facebook = the Page link | null: /numa-setup step 3 reads the account type |
| 33 | Who owns the Google Drive, the Google Business profile and the Higgsfield account? | `business.account_owners`, `socials.google_business_profile` | owners value = {drive, google_business_profile, higgsfield}; google_business_profile = the profile link | null |
| 34 | Should reels post automatically, or land ready-to-post for someone to publish? (Default: post automatically.) | `posting.auto_post` | value = true (post automatically) or false (land ready-to-post); never overrides `posting.legal_review_done` | true |
| 35 | Is there any post type you always want to see first, such as offers or anything showing members? (Default: none.) | `posting.see_first`, `posting.require_approval` | see_first value = list of post types (offer, members, collab, event); require_approval = true only if she wants every reel held | see_first []; require_approval false |
| 36 | Where should every call to action point: the Discover NUMA page, the app, or the link in bio? | `business.cta_link` | value = the URL (or "link in bio") | https://discover.numawellness.org |
| 37 | Are you running paid ads? If so, budget and goal. | `positioning.paid_ads` | value = {running, monthly_budget_usd, goal} | not running |
| 38 | Where should the Monday digest go: email, text, or the Claude app? | `posting.digest_destination` | value = an email address, "text" or "claude app" | claude app (the scheduled task's notification) |

### G. What's worked (Q39-Q41)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 39 | Your best-performing posts ever, and why you think they worked. | `positioning.past_best_posts` | value = [{link, why}] | none |
| 40 | Anything you've tried that flopped. | `positioning.past_flops` | value = [{what, why}] | none |
| 41 | Roughly how many followers today, and how many trials or members come from Instagram? | `positioning.audience_size` | value = {followers, trials_from_instagram_per_month, members_from_instagram} | null |

### H. Confirm what the research found (Q42-Q51)

| # | Question (ask exactly this) | brand.json key | Write the answer as | "Don't know" keeps |
|---|---|---|---|---|
| 42 | Are these right: 1719 Dauphin St; a 14-person Finnish sauna; 4 cold plunges; opening 5:30 AM Monday to Thursday? What temperature are the plunges and the sauna? | `business.location`, `business.facility`, `business.hours`, `business.temperatures` | flip each confirmed item to confirmed, correct the wrong ones; temperatures value = {plunge_f, sauna_f} | keep research; no temperatures in reels |
| 43 | Which phone number should be used everywhere? (Listings show 251-289-1758, 251-310-3656 and 251-423-8238.) | `business.phone` | value = the one number; keep `candidates` | null: no phone number in any post |
| 44 | Is the team list right: counselors Scott Moore, LaJuan Humbert (LPC) and Matt Henson (ALC); massage Kandi Roemhildt; facials Natalia Lichtenberger; breathwork guides Fallon Gleason and Joseph Irby? Who would do collab posts? | `team.collective` | fix names, roles and credentials; `collab: true` on each person who would do collab posts | keep research list; no collab with a provider |
| 45 | Katie: are you comfortable being the on-camera expert for "Ask the DPT"? What topics would you want to cover, and what would you never comment on? | `positioning.ask_the_dpt` | value = {comfortable, topics: [...], never: [...]} | comfortable unknown: Ask the DPT runs as text-on-screen answers |
| 46 | Which red light panels does NUMA use (make and model), and do they have an FDA clearance? For what exactly? | `claims.modalities.red_light.device_facts` | value = {make, model, wavelengths_nm, fda_clearance: what exactly or null}; "FDA-cleared" is never said in a post either way | null: no device facts in reels |
| 47 | Where does the website's "57 minutes of sauna and 11 of cold a week" line come from? (It's a dosing claim that needs a lawyer's OK before it's used in posts.) | `claims.dosing_line` | write her answer into `note`; `blocked` stays true (only counsel's OK, recorded by Jude in edit mode, unblocks it) | blocked stays true |
| 48 | Does the member consent form cover appearing in social posts and AI processing of photos? If not, can that wording be added? | `consent.social_posts_covered`, `consent.ai_processing_covered` | two booleans (true only if the signed form says so) | both false: no member face in posts or AI motion without a Consent List row covering it |
| 49 | Would NUMA partner with Mission Fitness, barre3 Mobile, Pure Barre Mobile, run clubs or University of South Alabama teams for collab posts? Any existing relationships? | `positioning.collab_partners` | keep yes-partners in her order, drop no's; add `relationship` to each existing one | keep the research order |
| 50 | Would NUMA offer a rate for healthcare workers or students, or a bring-a-friend first plunge? | `offerings.rates_considered`, `offerings.offers` | rates_considered value = [{name, yes_no_maybe}]; a confirmed offer with price also goes into `offerings.offers` | null: never promote an unconfirmed rate |
| 51 | Is there an advertising lawyer NUMA already works with to review the claims policy once? | `posting.legal_counsel` | value = {name, firm, contact}; `posting.legal_review_done` stays false until that review is done (edit mode) | null: Jude finds counsel; auto-posting stays gated |

## 7. Done means

Every question was asked once (or read from the answers file), every answer sits in its key with `status` confirmed and a `source`, every "don't know" kept its value with a note, brand.json validates, the copy is in Drive and Jude has the summary.
