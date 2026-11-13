# NUMA Studio setup guide

One afternoon, done by Jude on Katie's Mac (spec p.49-51). After this, Katie makes no decisions and types no commands: seven cloud scheduled tasks plan, build and post every reel (with her Mac on or off), and one desktop task does the Claude in Chrome steps whenever her Mac is awake, and her only job is to film what a shoot card lists.

Tick each box in order. Commands are typed in the Claude desktop app (or Claude Code) with the numa-studio plugin installed.

## Before you start: the blocking inputs

Nothing in the code can replace these (spec p.2):

- [ ] **Katie's answers to the 51 setup questions.** Print or send her docs/QUESTIONS_FOR_KATIE.md (phone-friendly; short answers and "don't know" are fine). They become brand data in step 9.
- [ ] **The accounts below** (Claude Max, Higgsfield Plus, Composio, NUMA's Instagram as a Business or Creator account, Google Drive, optionally Gmail).
- [ ] **A lawyer's one-time review of the claims policy** (brand.json `claims`) before auto-posting goes live. Until it is recorded, finished reels land "Ready to post" and you get one reminder a week. Q51 asks Katie whether NUMA already has an advertising lawyer.

## The afternoon checklist

1. [ ] **Claude:** put Katie's account on **Max** ($100/month). It gives 5x Pro's usage and includes Claude's top model for up to half the weekly limit, which the Director and Critic need.
2. [ ] **Desktop app on her Mac:** install it and turn on **Keep computer awake** and **Run on startup** in its settings, so Claude in Chrome (the Scout) is available as often as possible. The daily reel ships from the cloud either way.
3. [ ] **Plugin:** add the marketplace `CordiaJude/numa-studio` and install `numa-studio` (DECISIONS D6: Jude creates and pushes that repo).
4. [ ] **Connectors** (Claude Settings > Connectors):
   - [ ] Google Drive (signed in as the account that owns NUMA's Drive).
   - [ ] Google Sheets (same Google account).
   - [ ] Higgsfield, on the **Plus** plan (1,200 credits a month; config `higgsfield.plan`).
   - [ ] Composio with the **Instagram** toolkit: NUMA's Instagram must be a **Business or Creator** account; it uses Instagram Login, so no Facebook Page is needed and no Meta app review applies. Scopes: config `instagram.scopes` (instagram_business_basic, instagram_business_manage_insights, instagram_business_content_publish).
   - [ ] Gmail, if the Monday digest should arrive by email (Katie's answer to Q38) or your one-line escalations should (/numa-setup asks you once for your escalation channel and keeps it only in `_Plan/brand.json`, never in the public repo).
   - [ ] Google Docs (shoot cards and digests are Docs).
5. [ ] **Claude in Chrome:** install the extension in a Chrome profile that is signed in to NUMA's Instagram, Facebook and Google Business accounts.
6. [ ] **Drive:** `/numa-setup` step 5 creates whatever is missing: `NUMA Reels/` with `_Plan/`, `_Plan/Music Library/`, `_Plan/Digests/`, a **Consent List** Sheet (columns exactly `name`, `photo`, `date consented`, `scope`) and a **Closures** Sheet (columns `Date`, `Name`, `Note`). Check them afterwards.
7. [ ] **Voice (optional, strongly recommended):** Katie records a 1-minute voice sample for her cloned voice, and her written consent goes into the Consent List (scope `voice clone`). Without both, reels without her voiceover use a preset voice or on-screen text.
8. [ ] **Run `/numa-setup`.** It runs the same bootstrap every scheduled run starts with (`ensure_env.py`: Python packages, ffmpeg, the speech model and headless Chromium, installed only when missing), runs `setup_check.py --download-model` (every check green, the speech model pre-downloaded, a 3-second test reel rendered and looked at), confirms every connector, asks you once which Drive folder holds reel material, reports how many reels the Higgsfield balance covers, and has you set every connector tool to **Always allow** so scheduled runs never stall on a permission prompt (docs/SCHEDULED_TASKS.md, "So runs never stall").
9. [ ] **Run `/brand-setup`** with Katie's answers (the filled questions file, or her answers live). Each answer goes into its brand.json key and is marked confirmed; brand.json is validated and a copy is saved to Drive `_Plan/`. Commit the updated `brand/brand.json` to the plugin repo so cloud runs and future installs carry it.
10. [ ] **Golden test (M2) before switching the schedule on:** upload the "2026-11-09 Year One" test pack to Drive, run `/make-reel 2026-11-09 Year One` with no other input. Pass: finished in under 15 minutes; story arc, before/after wipe, beat-synced cuts and synced captions present; you rate it at least as good as the hand-built reference reel. Fail: fix before going on.
11. [ ] **Create the eight scheduled tasks** exactly as docs/SCHEDULED_TASKS.md lists them (all Central time; config `schedule`), pasting each prompt word for word (each one names the plugin and its command file, so it works even when slash commands do not expand):

| Task | When (Central) | Where |
|---|---|---|
| Plan next month | The 24th of each month, 9 pm | Cloud |
| Tomorrow's material check + Scout | Daily, 8 pm | Cloud |
| Build today's reel and outputs | Daily, 5 am | Cloud |
| Dashboard refresh | Daily, 10 pm | Cloud |
| Weekly trend check | Fridays, 7 pm | Cloud |
| Monday digest | Sundays, 6 pm | Cloud |
| Quarterly research re-check | The 12th of Feb, May, Aug and Nov, 10 am | Cloud |
| Chrome queue | Hourly at :47, while the Mac is awake | **Desktop** (Katie's Mac) |

   **Cloud or desktop.** A cloud task runs on Anthropic's servers on a fresh machine at its time, whether the Mac is on or off; that is where the reel is built and posted. A desktop task is created in the Claude desktop app on Katie's Mac as a local scheduled task and runs only while the Mac is awake and the app is open. Chrome queue must be the desktop kind: it does the steps that need Claude in Chrome (signed-in research, competitor log, Trial Reels, collab invites, the AI label, Higgsfield unlimited drafts), which exists only on the awake Mac. Anything it cannot reach by its deadline runs a fallback, so nothing waits for the Mac.

   Turn notifications on for each, then "Run now" each once and confirm it finishes with no permission prompt.
12. [ ] **Check the run log** (R343): `/numa-setup` step 10 runs `runlog.py check --since <the time of the first Run now>`. Every one of the eight tasks must show `OK:` (it started and finished ok). A task that shows `not run` did not follow its prompt: paste the prompt again exactly and Run now. Only then is the schedule left on.

## Account fixes at setup (from the Mobile audit; done once by Jude)

- [ ] **Instagram name field:** "NUMA | Sauna + Cold Plunge Mobile AL" (Instagram search reads the name field; brand.json `business.instagram_name_field`).
- [ ] **Bio** along the lines of brand.json `business.bio_draft`: "Guided contrast therapy + breathwork in Midtown Mobile · 14-person Finnish sauna · 4 cold plunges · red light · yoga · $49 first month", with the Dauphin St address, a Book button and a link to discover.numawellness.org (brand.json `business.cta_link`).
- [ ] **One phone number everywhere** (Katie picks it in Q43; brand.json `business.phone`): Instagram, Google Business Profile, Facebook, Mindbody and the website.
- [ ] **Google Business Profile** categories and wording that match (sauna, cold plunge, breathwork). /post-reel posts the week's best reel there every Monday.
- [ ] **Captions** open with a plain searchable phrase ("cold plunge in Mobile, AL") and use 3-5 hashtags such as #MobileAL #MidtownMobile #GulfCoastWellness plus one NUMA community tag (brand.json `captions`; the numa-caption skill enforces it).
- [ ] **Instagram's AI label** switched on for any reel with AI-animated people or AI-generated scenes (brand.json `posting.ai_label_rule`; /post-reel section 6).

## Verify these first (nobody has confirmed them yet; spec p.2)

The plugin already handles both outcomes of each (DECISIONS D7, D8). Record each answer in `_Plan/setup.json` under `verified` with the date.

| # | Question | How to verify | If yes | If no |
|---|---|---|---|---|
| 1 | Can Instagram's AI label be applied through the API? | Look at the schema of INSTAGRAM_POST_IG_USER_MEDIA (Composio's COMPOSIO_GET_TOOL_SCHEMAS) and Meta's Instagram API reference for media creation for an AI-label field. The first reel with AI-animated people shows which path /post-reel used (`work/post.json`). | The API sets it (post-reel section 6 row 1) | Claude in Chrome posts those reels with the label on; when Chrome is not available they are left for manual posting and you get one line (row 2-3) |
| 2 | Can Trial Reels and collaborator invites go through the Graph API directly? (Composio's tools don't expose them.) | On the first Trial Reel day, /post-reel tries a direct Graph API call through COMPOSIO_PROXY_EXECUTE with `trial_params` (and `collaborators` on a collab day) and records `trial_path` / `collab_path` in `work/post.json`. | Graph API path (post-reel section 5 column 1) | Claude in Chrome, else left for manual posting with one line to you |
| 3 | Can a cloud scheduled task drive Claude in Chrome when the desktop app happens to be open? | With the Mac awake and the desktop app open, create a one-off cloud scheduled task: "Use Claude in Chrome to open instagram.com and report the page title." | Cloud runs that see Chrome drain the Chrome queue themselves; the desktop Chrome queue task still covers the rest | Nothing to change: Chrome steps are queued and the desktop "Chrome queue" task does them while the Mac is awake; past a deadline the fallback runs (failure row F17 covers the Scout) |
| 4 | Where does the performance dashboard store its data: an artifact database, a Google Sheet, or both? | Decided (DECISIONS D7): `_Plan/metrics.json` plus the "NUMA Reel Metrics" Google Sheet; the dashboard page is rebuilt from them each night. After the first dashboard refresh, check that both exist and the dashboard artifact shows the first reel. | - | - |

## Monthly cost

| Item | Cost | Notes |
|---|---|---|
| Claude Max | $100 | Required for a top-model Director and Critic every day |
| Higgsfield Plus | about $47-59 | 1,200 credits; annual billing is cheaper (config `higgsfield.price_usd_per_month`, prices verified on config `higgsfield.prices_verified_on`) |
| Composio | $0 (free Hobby plan) | 100,000 tool calls a month, up to 20,000 on Composio's managed app; NUMA needs a few thousand |
| Music | $0 | Generated by Higgsfield or Meta's Sound Collection; a paid library only if NUMA wants one |
| **Total** | **about $150-160 a month** | For roughly 20 reels plus daily Stories and carousels |

Card renewals on Claude or Higgsfield come to you as a one-line message; credits are never bought beyond the monthly budget.

## Research prompts (re-run quarterly)

Reminder: /numa-setup creates the scheduled task "Quarterly research re-check" (the 12th of Feb, May, Aug and Nov, 10 am Central) that sends Jude this list as a one-line nudge.

All five were run on November 12, 2026 and their findings are folded into the brief. Re-run them every quarter (next: February 12, 2027) because prices, models and platform rules change. Afterwards update config/studio.json (Higgsfield `prices` and `prices_verified_on`, Instagram `graph_api_version`) and brand.json `claims` through `/brand-setup`, and note the changes for the next Monday digest.

1. "For wellness studios offering cold plunge, sauna, breathwork and red light in the US in 2026, which Instagram Reel formats, hooks, lengths and posting cadences perform best? Use studies and specific account examples with numbers; separate what's measured from what's opinion."
2. "What exactly can a US wellness studio say in social media marketing about cold plunge, sauna, red light therapy and breathwork without making unsubstantiated health claims under FTC rules? Give a do and don't phrase list with sources, including any enforcement actions against similar businesses."
3. "Compare Kling 3.0, Seedance 2.5 and other models available on Higgsfield for image-to-video of real interiors and real people: face and text stability, motion realism, best prompt patterns and credit cost per usable clip. Include current Higgsfield plan details."
4. "Audit the Instagram presence of wellness, recovery and fitness studios in Mobile, Alabama: who they are, what they post, what gets the most engagement, and the gaps NUMA Wellness Collective could own."
5. "Setting up the Instagram Graph API through Composio for a Business account to read reel insights and publish reels in 2026: permissions, account linking, token lifetimes, rate limits, and common failure modes."

## After a plugin update

Run `/numa-setup recheck`. If the update replaced `brand/brand.json` with the shipped defaults, restore Katie's answers from the copy in Drive `_Plan/brand.json` (or the repo commit from step 9) and run `/brand-setup` with no arguments: it asks only what is still unanswered.
