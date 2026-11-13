# R7 Judging windows: How Long NUMA Should Wait Before Judging an Instagram Post: A Timing Rulebook for a Small Account

> Deep-research result for prompt R7, received 2026-11-13. Imported by `strategy.py import-research` into the playbook's judging-window policy. Orchestrator review notes: docs/research/REVIEW.md.

For an account under 5,000 followers like @numawellnessmobile, don't judge a post for at least the first 24–48 hours. Take a provisional read at 72 hours, which is when about two-thirds of a Reel's views and about three-quarters of a feed post's views have usually arrived. Score feed posts and Reels as final at 7 days, and check Reels again at 30 days for long-tail views. There are two exceptions. Trial Reels are final at Instagram's own 72-hour test window. Stories must be captured at about 20–23 hours, because the API stops returning their data at 24 hours.

## TL;DR

- **Timing rule:** Ignore everything before 24–48 h, since Meta says insights data "can be delayed up to 48 hours." Take an early read at 72 h. Score feed posts and Reels at 7 days. Metricool's 2026 study of 24.4M posts found that 65% of Reel views and 76% of image/carousel views arrive in the first 3 days. Reels have a real long tail (measure.studio: about 70–75 days to reach 95% of lifetime views), so re-audit them at 30 days.
- **Special cases:** Trial Reels are final at 72 h. Meta auto-shares a trial based on "the views it receives within the first 72 hours," and compares it with your previous trials. Stories must be captured before 24 h, because the API serves story metrics "only... for 24 hours." The app itself keeps story insights for up to two years.
- **Early signals:** No study gives a measured correlation showing that 24–72 h skip rate, watch time or sends per reach predict 7- or 30-day results. The only figure found comes from Hootsuite's Iain Beable: "The correlation between first-hour engagement and final engagement was extremely weak (0.14)" (storyy.com, March 2025). It comes from Hootsuite's own corporate account, which Beable cautioned "isn't representative of all Instagram accounts." Treat the early weights below as starting points, and calibrate them on NUMA's own first 20 posts per format.

## Deliverable: Judgment Windows by Post Type

Hours are counted from publish time. "provisional_weight" is how much the 72 h (or equivalent) read should count in a blended score before the final read arrives. Reaching the final read means a weight of 1.0.

| post_type | ignore_before_hours | provisional_hours | provisional_weight | final_hours | best_early_metric | evidence | confidence | sources | how to verify on NUMA's own data |
|---|---|---|---|---|---|---|---|---|---|
| reel | 48 | 72 | 0.6 | 168 (score); 720 long-tail audit | **Skip rate + average watch time** at 72 h. These are rates, so they settle before counts do, and Mosseri names watch time as the top ranking signal. Sends per reach comes second because it drives reach to non-followers. | measured (accumulation curve); opinion (weights) | medium | Meta media insights doc (developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights); Metricool 2026 (metricool.com/instagram-trends/); measure.studio (measure.studio/post/tiktok-vs-instagram); Socialinsider (socialinsider.io/blog/how-long-does-it-take-for-reels-to-get-views/) | Log views, reach, skip rate, avg watch time and shares at 24/72/168/720 h. After 20 Reels, compute the rank correlation (Spearman) of the 72 h score against the 168 h score. If ρ ≥ 0.9, raise the weight to 0.8. If ρ < 0.7, lower it to 0.4 and wait for 7 d. Separately, count how many Reels gained >25% more views between day 7 and day 30. |
| trial_reel | 24 | 24–48 | 0.5 | 72 | **Views compared with your previous trials**, the comparison Instagram itself shows. Then skip rate and shares, since the audience is non-followers only, where sends matter most. | observed (Meta-documented mechanics) | high (timing); medium (metric choice) | Meta Newsroom, Dec 2024 (about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first-see-what-perfoms-best/); Instagram Creators blog (creators.instagram.com/blog/instagram-trial-reels) | After 10 trials, check whether the 24 h ranking matches the 72 h ranking. Track whether trials you graduate keep beating regular Reels at 7 d after sharing. |
| carousel | 24 | 72 | 0.75 | 168 | **Reach vs. NUMA's median, plus likes per reach.** Mosseri says likes matter most for followers (connected reach). Read saves at 7 d, not 72 h. | measured (curve); observed (second-chance re-show) | medium | Metricool 2026 (76% of views / 75% of interactions in 3 days); measure.studio (73% of views on day 1; 95% at about 35 days); Mosseri via Mashable/Yahoo (tech.yahoo.com/social-media/articles/why-instagram-carousels-sometimes-start-200811893.html) | After 20 carousels, compare 72 h and 168 h reach ranks. If the 72 h share of 7 d reach averages ≥85%, raise the weight to 0.85. |
| image | 24 | 72 | 0.8 | 168 | **Likes per reach + profile visits.** Static posts are shown mostly to followers, and they front-load fastest. | measured (curve) | medium | Metricool 2026 (44% of views on day 1; 76% by day 3); measure.studio (95% of views in about 20 days) | Same as carousel. If 72 h ≥ 90% of 7 d reach across 20 posts, move to 0.9. |
| story | 6 | 12 | 0.7 | 20–23 (API capture); in-app re-check at 72 | **Reach (viewers) as % of followers, plus completion: forward taps, exits, replies, link taps.** Stories rarely reach non-followers, so judge them on retention and actions. | observed (official 24 h API limit); opinion (curve) | medium | Meta media insights doc (24 h story metrics, story_insights webhook, under-5-viewers error); Instagram Help Center Stories insights (help.instagram.com/383939598845756/) | Snapshot each Story at about 12 h and about 22 h for 20 Stories. If the 12 h reach is ≥80% of 22 h reach, rely on 12 h for fast decisions. Check the app at 72 h to see whether the lagged numbers moved. |

### Metric-specific exceptions

| post_type | metric | ignore_before_hours | provisional_hours | provisional_weight | final_hours | best_early_metric | evidence | confidence | sources | how to verify on NUMA's own data |
|---|---|---|---|---|---|---|---|---|---|---|
| reel, carousel, image | saves | 72 | 168 | 0.5 | 336 (14 d) | Use reach-normalized saves (saves per 1,000 reached). Raw counts are too small at under 5K followers. | opinion (no measured per-metric timing curve exists) | low | Metricool 2026 (interactions slightly less front-loaded than views: 61% vs 65% for Reels in 3 days); subagent review found no save-vs-like timing study | After 20 posts, compute what share of 14 d saves had arrived at 7 d. If ≥90%, finalize saves at 7 d. |
| reel, carousel, image | shares / sends | 72 | 168 | 0.5 | 336 (14 d) | Sends per reach (shares ÷ reach). Mosseri says it matters most for reaching non-followers. | observed (signal importance, Mosseri); opinion (timing) | low | Mosseri Jan 2025 via Social Media Today (reported in zoomsphere.com/blog/instagram-algorithm-2026-what-actually-gets-reach); Meta doc lists `shares` for FEED, REELS, STORY | Same method as saves. Also flag any post whose shares jump after day 3, because a share wave usually precedes a reach wave. |
| reel | skip rate, average watch time | 24 | 48 | 0.7 | 72 | These are rate metrics that settle faster than totals. Skip rate may return blank for low-reach Reels, and Meta labels it "estimated and in development." | observed | medium | Meta media insights doc (`reels_skip_rate`, `ig_reels_avg_watch_time`); Social Media Today, Aug 2025 (skip rate replaced view rate) | Compare the 72 h skip rate with the 168 h skip rate on 20 Reels. If the median absolute change is under 3 percentage points, treat 72 h as final. |
| reel | views / reach (long tail) | — | 168 | 0.8 | 720 (30 d) audit | Day 7 to day 30 growth. Resurfacing through Explore, search and sends can add views weeks later. | measured (large mixed-size samples) | medium | measure.studio (Reels: 36% of views on day 1; about 70–75 days to 95%); Mosseri: content "can continue to reach new people for a few weeks after posting" (via socialnationnow.com) | Tag any Reel with >25% view growth from 7 d to 30 d as "evergreen." Look at what those Reels share (topic, hook, search keywords). |
| feed, story | follows, profile visits | 72 | 168 | 0.6 | 168 | Profile visits are the business-relevant action (taps through to booking the $49 "Discover NUMA" offer). | observed | medium | Meta doc: `follows` and `profile_visits` listed for FEED and STORY media, not REELS | Compare post-level profile visits with booking-link clicks in the bio-link tool, week by week. |
| collab / reshared posts | all | 48 | 168 | 0.4 | 168 | Mark these posts as "boosted" and score them against a separate baseline. | observed (practitioner reports) | medium | Collab guides (e.g., nealschaffer.com/instagram-collaborative-posts/) report pooled metrics across co-authors | Keep collab posts out of the main 72 h → 7 d calibration set. |

## 1. Data lag: when insights become complete and stable

**What Meta officially documents:**
- **The general lag is up to 48 hours.** Meta's Instagram Media Insights reference says: "Data used to calculate metrics can be delayed up to 48 hours." This applies to every media metric served through the API. If data "does not exist or is currently unavailable, the API returns an empty data set instead of `0`." A blank on day one therefore means "not yet," not "zero." Metrics are stored for up to 2 years.
- **Metrics are labeled "estimated" or "in development."** Meta tags `reach` as "estimated," `reels_skip_rate` as "estimated and in development," and `views`, `total_interactions` and `ig_reels_video_view_total_time` as "in development." These numbers can be revised, which is another reason not to freeze scores early.
- **Availability differs by format.** `ig_reels_avg_watch_time` and `reels_skip_rate` are Reels-only. `follows` and `profile_visits` are listed for FEED and STORY media but not REELS. `likes`, `comments` and `saved` exist for FEED and REELS. `shares`, `reach`, `views` and `reposts` cover FEED, REELS and STORY. No insights are available for the individual items inside a carousel.
- **Views replaced impressions.** Per Meta's reference, `impressions` is deprecated for media created after July 2, 2024. `views` is now the cross-format count. Do not compare old impression-era posts with new view-based posts.
- **Story metrics are available via the API for 24 hours only.** Meta recommends the `story_insights` webhook to capture them before they expire. Story metrics with values below 5 return error `(#10) Not enough viewers`. At NUMA's scale, low-view Stories can come back with no data at all.

**Per-metric guidance** (combining Meta's 48 h lag with observed behavior):
- **Stable at about 48–72 h:** reach, views, skip rate, average watch time and likes. Rate metrics (skip rate, average watch time, likes per reach) stabilize faster than counts because they are ratios. *(observed / opinion)*
- **Still moving at 72 h:** comments, saves, shares/sends, profile visits and follows. These are low-count, event-driven metrics. At under 5K followers, a single extra save can change a post's rank. *(opinion; no measured per-metric lag study exists)*
- **The native app vs. the API:** the app often updates within hours, but Meta's documented lag applies to the underlying data. Third-party dashboards that pull from the API (Metricool, Later and others) inherit the 48 h delay. *(observed: connector vendors such as Power My Analytics document a 48-hour delay)*

## 2. Accumulation curves: how much arrives by when

**Measured data (all from mixed account sizes, mostly brands; none limited to accounts under 5K):**

| Format | By 24 h | By 72 h | By 7 d | By 14 d | By 30 d | Time to 95% | Source |
|---|---|---|---|---|---|---|---|
| Reels (views) | ~30% (Metricool) to 36% (measure.studio) | 65% of views, 61% of interactions | ~75–85% *(interpolated, opinion)* | ~85–90% *(interpolated)* | ~90% *(interpolated)* | ~70–75 days | Metricool 2026; measure.studio |
| Carousels (views) | 44% (Metricool, all static) to 73% (measure.studio) | 76% of views, 75% of interactions | ~85–90% *(interpolated)* | ~90% *(interpolated)* | ~94% *(interpolated)* | ~35 days | Metricool 2026; measure.studio |
| Single images (views) | ~44% | 76% of views, 75% of interactions | ~90% *(interpolated)* | ~93% *(interpolated)* | ~96% *(interpolated)* | ~20 days | Metricool 2026; measure.studio |
| Stories | most views in the first hours *(practitioner observation)* | n/a (expires at 24 h) | n/a | n/a | n/a | 24 h (unless in Highlights) | Meta doc; practitioner reports |

**Notes on the sources:**
- **Metricool 2026 Instagram Study (measured):** 24,364,803 posts from 375,118 accounts. It found that "70% of total views on Instagram happen in the first three days." For Reels, days 1–3 account for 65% of views and 61% of interactions. For posts and carousels, the figure is 76% of views and 75% of interactions. Day 1 alone is about 30% of a Reel's lifetime views and 44% of a static post's. Caveats: the comparison window is January–February, all account sizes are pooled, and "lifetime" is not defined on the public pages.
- **measure.studio (measured, smaller and less transparent sample):** "hundreds of thousands of posts." Reels earn about 36% of lifetime views on day one and take about 70–75 days to reach 95%. Carousels earn 73% on day one and reach 95% in about 35 days. Photos reach 95% in about 20 days. Account-size mix is not disclosed.
- **Socialinsider (measured, large-account-weighted):** 40M Reels from 450K accounts, 2025. Average views were about 17,100 in the first 5 days, about 14,578 by day 10, and plateaued just above 8,000 around day 20. These are averages dominated by big accounts, and the framing is hard to convert into percentages. Use it only as directional support that Reels keep earning for 1–3 weeks.
- **Graffius "half-life" reports (aggregated, methodology opaque):** Instagram post half-life of 18.27 hours (2026). Treat this as opinion-grade.

**The data conflict:** Metricool (30% on day 1) and measure.studio (36% on day 1) roughly agree on Reels' first day, but they disagree on the tail. Metricool shows 65% by day 3, while measure.studio shows Reels still climbing toward 95% at day 70–75. Both can hold if most Reels plateau early and a minority keep resurfacing. That is why this report scores at 7 days and audits at 30, rather than waiting 75 days for every Reel.

**Do saves and sends accumulate more slowly than likes?** No measured study separates them. The subagent review of Metricool, Socialinsider, Buffer, Later, Dash Social, Emplifi, measure.studio and academic sources found no per-metric timing curve. The only indirect hint is Metricool's figure that Reel *interactions* (61%) are slightly less front-loaded than *views* (65%) at 3 days. Claims that "saves lag likes" are practitioner opinion. They are plausible, because saves and sends often come from later, more deliberate viewers and from resurfacing. That is the basis for the 7–14 day exception rows above.

**How the long tail changes things:**
- **Reels resurface** through the Reels tab, Explore, search and DM sends. Mosseri has said content "can continue to reach new people for a few weeks after posting" (reported via a secondary source). *(observed)*
- **Carousels get a "second chance."** Mosseri: "If someone sees your carousel post but they don't swipe, we'll often give that carousel a second chance and automatically move to that second piece of media for the viewer." This adds reach in later sessions, so carousels keep growing modestly after day 1. *(observed, official statement)*
- **Search and keyword captions** extend the life of evergreen topics. For NUMA, examples are "what to expect at a contrast therapy session," "how a Finnish sauna works" and "first visit." *(opinion)*

## 3. Early indicators: what predicts the 7- or 30-day result

**The bottom line is that no published, measured correlation shows 24–72 h Instagram metrics predicting 7- or 30-day outcomes.** The available evidence:
- **Hootsuite experiment (measured, tiny, large account):**
  - Hootsuite Senior Content Marketing Manager Iain Beable reported that "the correlation between first-hour engagement and final engagement was extremely weak (0.14), indicating almost no relationship between the two variables." Many "slow starters" outperformed "good starters" after 24 h.
  - The 0.14 figure is reported secondhand (storyy.com, March 26, 2025), from a test on Hootsuite's corporate account using only 40+ feed posts. Beable cautioned: "Our account isn't representative of all Instagram accounts."
  - A separate Hootsuite blog experiment (Sarah Israel, March 19, 2025) used a single account, @dwellingonthepast, not Hootsuite's corporate account. Over two weeks it posted three carousels per week at 7 pm Tuesday–Thursday. Pushing first-hour engagement (Story shares, DMs to friends, fast replies) meant "our average reach more than tripled (18 → 60.6), and engagement spiked from 0.24% to 1.08%" in the first hour. 24 h reach rose from 80.3 to 229.6.
  - *Large account; not representative of under-5K accounts.*
- **Mosseri (leadership statement, reported secondhand):** Kontentino's Q&A "Does Early Engagement Determine How Well an Instagram Post Will Perform Overall?" says Mosseri "describes a strong correlation between how a post performs in its first hour and how it performs overall," but that it is "not a guarantee in either direction." This conflicts in tone with Hootsuite's 0.14. Neither should be used for NUMA without local calibration.
- **Which signals Instagram ranks on (official):** Mosseri named the top three signals in January 2025 as "watch time, likes and sends." Likes are "slightly more important for connected content" and sends "slightly more important for unconnected content." He told creators to watch average watch time, likes per reach and sends per reach. Earlier (July 2024): "One of the most important signals we use in ranking is sends per reach." *(observed: these are ranking inputs, which makes them sensible leading indicators; it does not prove predictive accuracy)*
- **Skip rate:** Social Media Today (Andrew Hutchinson, August 24, 2025) reported that Instagram added a retention chart and replaced view rate with skip rate. It quoted Instagram: "skip rate is the percentage of views from people who decided to skip your reel during those first 3 seconds." Meta added `reels_skip_rate` to the API in December 2025. It measures the hook, not total performance. Use it to diagnose why a Reel stalled, not to forecast its 30-day views. *(observed)*
- **Adjacent academic evidence (not Instagram):** a Facebook-video study reportedly found about 0.97 Spearman correlation between 24 h views and 7-day popularity. This was seen only in a ResearchGate snippet and is unverified. It suggests 24–72 h *view ranks* can predict 7-day *view ranks* well on algorithmic feeds, but don't apply it until NUMA's own data confirms it.

**Practical rule for NUMA (opinion, to be calibrated):**
- Act at 72 h on *diagnostics*: fix hooks when skip rate is high, and re-share to Stories when likes per reach are fine but reach is low.
- Wait for 7 days before making *portfolio decisions*: which topics to repeat and which to drop.

## 4. Trial Reels: when results are final and what to compare against

- **When it's final:** 72 hours. Meta's announcement says Instagram can automatically share a trial with followers "if we determine it's performing well based on the views it receives within the first 72 hours." Insights appear about 24 hours after posting, per Meta and the Creators blog. *(observed, official)*
- **What to compare against:** Instagram itself shows "how the trial is performing compared to previous trials you've shared." Compare trials with **other trials**, not with regular Reels. Trials reach only non-followers, so their raw reach and engagement differ structurally. The Help Center states trial reels "are evaluated independently in Instagram's ranking and don't impact the performance or ranking of your standard reels content" (as quoted by third-party guides). *(observed)*
- **Eligibility note:** several 2026 guides citing the Instagram Help Center (August–October 2026; e.g., exemplary.ai, creatorflow.so, Planoly via trialreel.app) put the minimum at 200 followers for public professional accounts and 1,000 for personal accounts. The account must also be eligible for recommendations. The 1,000 figure traces to Mosseri's July 2025 expansion (Social Samosa). NUMA's professional account qualifies. *(practitioner reports citing official help docs)*
- **NUMA protocol (opinion):** run trials of the same concept with two hooks, for example "What 4 cold plunges and a 14-person Finnish sauna look like on a Tuesday night" vs. "Your first contrast session at NUMA, step by step." Read skip rate and shares at 24 h, then decide at 72 h. Once graduated, re-score the Reel on the regular reel schedule (7 d plus a 30 d audit), because follower distribution starts fresh at that point.

## 5. Stories: capturing data before the 24-hour limit, and when to judge

- **The constraint (official):** Meta's API serves story metrics "only... for 24 hours." To capture them before expiry, subscribe to the `story_insights` webhook. Data may still arrive after expiry if the Story is added to a Highlight. Stories with fewer than 5 viewers return error #10.
- **The app is different (official):** Instagram's Help Center says that "although stories expire after 24 hours, you can still access insights for up to two years after they're created." Manual review in the app is still possible, but third-party tools lose access after 24 h. Older guides citing "14 days" are out of date.
- **Capture routine for NUMA:**
  1. Have the scheduler/analytics tool pull story data automatically, or connect via Facebook Login so the webhook works. Note that Meta says the insights webhook is *not* supported for Instagram API with Instagram Login.
  2. Snapshot each Story at about 12 h (provisional) and about 22 h (final).
  3. For event Stories (Numa Nights, Clinical Conversations), also screenshot link taps and replies at about 22 h.
  4. Re-check in the app at 72 h to see whether the 48 h data lag moved anything.
- **What to judge:** reach as a % of followers, and drop-off across a sequence (first-frame vs. last-frame viewers). Also judge actions: replies, link taps and profile visits. Socialinsider's Stories benchmarks cover brands with 1K–1M followers. The practitioner view that small accounts reach roughly 10–25% of followers per Story is *observed, not measured*.

## 6. Pitfalls: slow starters, boosts, weekends and holidays

- **Slow starters:**
  - Hootsuite's data (large account) found many slow starters overtaking fast starters by 24 h.
  - measure.studio shows Reels earning only about 36% of views on day 1.
  - Never delete or "repost to fix" a Reel inside 72 h. Meta also notes Instagram "shows less of reels that have already been posted" (per third-party guides citing Instagram). *(measured + observed)*
- **Collab posts and big reshares:** collab metrics are pooled across co-authors (practitioner guides), so a collab with a larger local partner inflates reach and isn't comparable to solo posts. Flag these, along with any post reshared by a large account, and score them against their own baseline. *(observed)*
- **Data-lag artifacts:** a blank metric on day 1 is "no data yet," not zero (Meta). Excluding the last 48 h from weekly reports avoids under-counting the newest posts. *(official)*
- **Weekends and holidays:** no measured study isolated this for small accounts. For a local studio, the risks are audience-schedule effects such as Thanksgiving week (Nov 26, 2026), the December holidays and Mobile's Mardi Gras season. Compare posts against a same-weekday median, and don't let one holiday post reset the baseline. *(opinion)*
- **Judging too late:** waiting 75 days for every Reel's 95% mark stalls learning at 20–25 posts per month. Score at 7 d and audit at 30 d. *(opinion)*
- **Compliance check on "winners":** when a hook wins, confirm it sells the experience (the sauna, the plunge, the community, the $49 first month) and makes no health-outcome claim. Don't scale a high-performing hook if it implies results like recovery, weight loss or treatment. *(FTC context provided by the user)*

## Recommendations

1. **Adopt the table as the default rulebook now.** Reels: 48 h ignore, 72 h read (0.6 weight), 7 d final, 30 d audit. Carousels and images: 24 h ignore, 72 h read (0.75–0.8), 7 d final. Trial Reels: final at 72 h against prior trials. Stories: capture at about 22 h.
2. **Build a snapshot log** (sheet or analytics tool) at 24/72/168/720 h for every post, and exclude the last 48 h from weekly reports.
3. **Calibrate after 20 posts per format.** At NUMA's volume that is about 2–3 months for Reels and carousels. Use Spearman ρ between the 72 h and 7 d ranks to raise or lower each provisional weight.
4. **Lead with reach-normalized metrics**: sends per reach, likes per reach, saves per 1,000 reach, skip rate and average watch time. Raw counts at under 5K followers are too noisy.
5. **Treat collabs, reshared posts and holiday posts as separate cohorts** so they don't distort the baseline.

## Caveats

- **No accumulation study was limited to accounts under 5,000 followers.** Metricool and measure.studio pool sizes, and Socialinsider's Reel averages and Hootsuite's experiments reflect large accounts. Small accounts may front-load even more, because a larger share of their reach comes from followers. That is a hypothesis, not a finding.
- **The 7 d, 14 d and 30 d percentages in the accumulation table are interpolated** between measured anchors (day 1, day 3 and time to 95%) and are labeled as opinion.
- **No measured predictive accuracy exists** for early metrics. The provisional weights are reasoned starting points meant to be replaced by NUMA's own calibration.
- **Instagram's metrics keep changing.** Skip rate, views, reach and total_interactions are flagged by Meta as estimated or in development. Re-check definitions each quarter.
