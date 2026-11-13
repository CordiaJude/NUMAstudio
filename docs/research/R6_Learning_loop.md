# R6 Learning loop: How NUMA Wellness Collective Should Learn From Its Own Instagram Data (Without Being Fooled by Noise)

> Deep-research result for prompt R6, received 2026-11-13. This is the basis for strategy.py's scoring and bandit policy. Orchestrator review notes: docs/research/REVIEW.md. Note: the variable examples in section 6 ("stress/sleep", "client stories", "before/after or outcome-first") are generic; for Numa they must stay inside the claims policy (no stress/sleep outcome topics, no before/after).

At 20–25 posts a month, NUMA cannot run statistically clean A/B tests. Its best option is a disciplined "rate, rank, replicate" system. Score every post at fixed ages (a provisional score at 72 hours, a final score at day 7). Measure per-reach rates against the account's own rolling median, not raw counts. Turn each post into a binary "beat our median / didn't" outcome. Feed those outcomes into a discounted Thompson-sampling bandit that spends about 30% of slots on experiments. Promote or retire a pattern only after 6–8 tries, with both a probability threshold and an effect-size threshold. Instagram's own guidance supports the inputs: rates over counts, with sends, likes and watch time as the core signals. The weights, thresholds and slot split are reasoned heuristics, and NUMA should treat them as starting settings to tune.

## TL;DR

- **Score rates, not counts, against your own median.** Use sends, saves and follows per reach, plus average watch time and skip rate. Adam Mosseri has said "the rate is more important than the count" and named watch time, likes and sends as the top three ranking signals. Lock a provisional score at 72 hours and a final one at day 7. Meta says insights data "can be delayed up to 48 hours," and Metricool finds Reels collect about 65% of their views in the first three days.
- **Turn each post into a win/loss against the rolling median and run a discounted Beta-Bernoulli Thompson sampler on ~30% of slots (6–7 of ~22 posts/month).** Test hook patterns first, then topic pillars, then format-per-goal, then CTAs. Leave posting time for last. Promote a pattern after at least 8 tries if it won ≥6 (posterior P(beats median) ≈ 0.91) and its median index is ≥1.25×. Retire it after ≤2 wins in 8 (or ≤1 in 6) with a median index ≤0.8×.
- **Use Trial Reels as cheap, follower-safe hook tests, but compare trials only with other trials.** Ignore Christmas–New Year and the January wellness surge when promoting or retiring patterns. Measure link clicks and bookings with UTM links and booking codes, because Instagram does not reliably attribute them to individual Reels. The scoring weights, thresholds and slot split are heuristics. The signals and data mechanics are well documented.

## Key Findings

1. **Rates beat counts, and Instagram says so.** In May 2024 Mosseri said: "Generally, I think the rate is more important than the count. So the number of sends per reach, the number of likes per reach, the number of comments per reach. But sends per reach correlate more, in my experience, with overall reach than anything else." In January 2025 he said "the top three signals that matter most for ranking are watch time, likes and sends," with likes "slightly more important for connected content" and sends "slightly more important for unconnected content." Instagram's 2023 "Ranking Explained" post lists the most important Reels predictions as how likely you are to "reshare a reel, watch a reel all the way through, like it, and go to the audio page." *Evidence: official statements, high.* Many marketing blogs claim sends are weighted "3–5×" likes. Mosseri has never given a fixed multiplier, so treat that claim as unsupported.

2. **Data lag and decay set the judging window.** Meta's Instagram Media Insights reference states that "data used to calculate metrics can be delayed up to 48 hours," and that Story media metrics are "only available for 24 hours" through the API. Metricool's 2026 study (24.4M posts, 375K accounts) found that 70% of Instagram views happen in the first three days. For Reels that share is 65% of views and 61% of interactions, with day one about 30% of lifetime views. Posts and carousels reach 76% of views in that window. Socialinsider's analysis of 40M Reels shows views still accruing beyond day 5 and flattening around day 20. So 72 hours is a sensible provisional cut-off, but not a final one. *Evidence: platform documentation (high); large benchmark studies (medium-high, vendor data).*

3. **Small-account samples are tiny, so the method must be built for that.** A sign test against the account median needs 6 of 6 wins (one-sided p≈0.016) or 7 of 8 (p≈0.035) to reach conventional significance. At 20–25 posts a month, testing several variables at once means some arms get only 2–4 tries a month. Frequentist A/B testing at the 95% level is not feasible. Bayesian posterior probabilities with explicit decision thresholds are the practical alternative (Russo, Van Roy et al., *A Tutorial on Thompson Sampling*, 2018). *Evidence: statistical literature (high) applied by reasoned inference.*

4. **Trial Reels are the closest thing to a free A/B test, with limits.** The Help Centre says trials go to non-followers, are "evaluated independently in Instagram's ranking and don't impact the performance or ranking of your standard reels content," return Views, Likes, Comments and Shares "within 24 hours," and "may get limited reach if Instagram detects that you've previously shared the same content." Mosseri advised that "the best way to know how a trial reel is doing is to compare it to other trial reels." Eligibility is a public professional account with at least 200 followers. The 72-hour auto-share window comes from the December 2024 launch post. The current Help Centre only says "soon after you publish." *Evidence: official documentation (high); the trial-only comparison rule is an official statement as reported by secondary sources (medium-high).*

5. **Instagram does not report every goal metric per Reel, so bookings and link clicks need outside tracking.** The Help Centre's Reels insights page lists Views, Watch time, Viewers, Average watch time and Follows ("how many accounts started following you as a result of viewing your reel"). The Meta API lists `follows`, `profile_visits` and `profile_activity` (including the BIO_LINK_CLICKED breakdown) for feed posts and Stories only, not Reels. `link_clicks` ("taps on links in your story") is Stories-only. The API provides `saved`, `shares`, `reposts`, `ig_reels_avg_watch_time` and `reels_skip_rate` ("estimated and in development") for Reels. *Evidence: platform documentation (high). Some in-app Reel screens reportedly show more, such as profile activity and follower/non-follower splits, but I could not confirm that against Help Centre text.*

6. **Format should follow goal, and benchmark studies disagree on rankings because their denominators differ.** Socialinsider (engagement by followers) puts carousels at 0.55% and Reels at 0.52%. Buffer (median engagement by reach) puts carousels at 6.90% and Reels at 3.31%. Metricool finds Reels reach 29% more people than carousels, and carousels get about 9× the saves of single images. The consistent picture: Reels drive discovery and sends, carousels drive saves and per-viewer depth. *Evidence: large published benchmark studies (medium; methods differ and vendors sample their own customers).*

## Details

### 1. Metric hygiene: what to log for every post

Log these at **72h (provisional)** and **day 7 (final)**, always at the same post age:

| Field | Source | Notes |
|---|---|---|
| Reach / Viewers | Insights / API `reach` | Denominator for all rates. Meta labels it "estimated." |
| Views | `views` | Counts replays, so don't use it as a denominator. Views replaced impressions for new media after the July 2, 2024 deprecation. |
| Sends/shares, saves, likes, comments, reposts | API / Insights | Divide by reach. |
| Avg watch time, Reel length, skip rate | `ig_reels_avg_watch_time`, `reels_skip_rate` | Watch-through ratio = avg watch ÷ length. |
| Follows | In-app Reel insights; API for posts/Stories | Per-Reel follows are an in-app read only. |
| Profile visits, bio-link taps | Posts/Stories via API; account-level otherwise | For Reels, use account-level daily deltas as a weak proxy. |
| Story link-sticker taps | Story insights / API `link_clicks` | **Capture within 24h** (API expiry). |
| UTM sessions, bookings | Booking system / analytics | Use unique UTM per post or campaign, plus a "how did you hear about us" field. |
| Tags | Your sheet | Format, hook pattern, topic pillar, CTA, slot, Trial Y/N, holiday-week flag. |

### 2. Normalisation: per reach, then against your own median

For each metric *m* and post *i*, compute the rate *r = m / reach*. Then build an **index** against the trailing median of the **last 20 posts of the same format** (Reels separately from carousels), using only posts at least 7 days old:

**I(m) = r_i / median(r over trailing 20 same-format posts)**

Score on a log₂ scale and clip at ±2 (4× either way) so one viral post cannot dominate: **s(m) = clip(log₂ I(m), −2, +2)**. A score of 0 means "at our median," +1 means double, and −1 means half.

Why this design (reasoned inference): per-reach rates remove most of the effect of reach size and follower growth. Same-format medians stop Reels and carousels from being judged against each other's distributions. Medians and clipping resist outliers. A 20-post window (about one month) lets the baseline drift with seasonality and growth. Medians rather than means matter because performance is heavily skewed. viral.app's dataset of 1.2M Reels found 4.9% hit 10× their account's median views (practitioner/vendor data).

### 3. Recommended scoring formula per goal

All weights are **heuristic**. The ordering of signals is anchored in Mosseri's statements. The exact numbers are my judgement and should be revisited after a quarter of data.

| Goal | Formula (log₂-index components, clipped) | Why |
|---|---|---|
| **Reach** | 0.40·s(reach) + 0.30·s(watch-through) + 0.30·s(sends/reach) | Reach itself is the outcome but noisy. Watch time and sends are Mosseri's named drivers of distribution, especially to non-followers, so they stabilise the score and point to causes. |
| **Sends** | 0.80·s(sends/reach) + 0.20·s(watch-through) | Sends per reach is the stated strongest correlate of reach. Watch time is a guardrail against clickbait hooks. |
| **Saves** | 0.80·s(saves/reach) + 0.20·s(watch-through or carousel swipe depth) | Saves signal reference value. Instagram lists saves among Explore's predictions but not among the Reels top three, so saves get a goal score of their own but less weight in the composite. |
| **Follows** | 0.70·s(follows/reach) + 0.30·s(sends/reach) | Follows per reach is the direct growth outcome. Counts are small (often 0–5), so sends add a smoother leading indicator. |
| **Profile visits** | 0.70·s(profile visits/reach) + 0.30·s(follows/reach) | Available per post for feed posts and Stories. For Reels use the in-app figure if shown; otherwise drop this goal for Reels. |
| **Link clicks** | 0.60·s(link taps/profile visits) + 0.40·s(UTM sessions/1,000 reach) | Bio-link taps belong to the profile, not the post. Story link stickers are the cleanest per-item click metric. |
| **Bookings** | Bookings per 1,000 reach, by campaign/week (not per post) | Too sparse for per-post scoring. Attribute with UTMs or codes and judge monthly. |

**Composite score for experiments (the bandit reward):**
**S = 0.30·s(sends/reach) + 0.20·s(follows/reach) + 0.20·s(watch-through) + 0.15·s(saves/reach) + 0.15·s(reach)**

Sends get the most weight because Instagram links them most closely to reach and non-follower discovery. Follows and watch time come next as the growth outcome and the gating signal. Saves and raw reach get the least: saves are less central to Reels ranking, and raw reach is the noisiest term. For carousels, replace watch-through with a swipe-depth or "views per reach" index. Run a **separate monthly conversion review** (link taps, UTM sessions, bookings). Bookings are NUMA's real goal but are far too sparse to steer post-level learning.

### 4. How long to wait before judging a post

- **0–24h: don't judge.** Metrics can lag up to 48 hours, and Trial Reel insights only appear within 24 hours.
- **72h: provisional score.** By then a typical Reel has about 65% of its views (Metricool). Use this score only to *continue* an experiment, never to promote or retire.
- **Day 7: final score for decisions.** Lock it and never update it. Later views from Search or Explore resurfacing are real but would make scores incomparable across posts of different ages.
- **Stories: capture at 20–24h**, because API story metrics expire after 24 hours and values under 5 are not returned.

### 5. Minimum sample sizes and decision rules

Convert each post's composite S into a **win** (S > 0, i.e., beat the same-format median) or a **loss**. Under "no effect," a pattern wins 50% of the time. Track each pattern with a Beta(1+wins, 1+losses) posterior.

| Rule | Threshold | What it means |
|---|---|---|
| **Minimum tries before any decision** | 6 (Trial Reels count, but in a separate trial-only pool) | Below 6, even 5/5 is too fragile against novelty and luck. |
| **Promote to "core" pattern** | ≥8 tries, ≥6 wins **and** median composite index ≥1.25× (S ≥ +0.32) | 6/8 gives posterior P(win rate > 50%) ≈ 0.91. The effect-size bar stops promotion of patterns that win often but only barely. |
| **Fast-track promote** | 5 of first 6 wins and median ≥1.4× | Posterior ≈ 0.94. Still re-check at 10 tries. |
| **Retire** | ≥6 tries with ≤1 win, or ≥8 tries with ≤2 wins, **and** median ≤0.8× | 2/8 gives posterior P(>50%) ≈ 0.09. 1/6 gives ≈ 0.06. |
| **Keep testing** | Anything in between | Leave it in the explore pool. The bandit naturally down-weights it. |
| **Demote a core pattern** | Rolling last-8 drops to ≤3 wins or median <1.0× | Catches decay and fatigue in winners. |
| **Ignore for decisions** | Posts flagged holiday-week, paid-boosted, or collab | Log them but exclude them from pattern posteriors. |

The thresholds trade speed for accuracy deliberately. At roughly 90% posterior confidence, about 1 in 10 promotions will be a false positive. That is acceptable because promotions are cheap to reverse and the demotion rule catches them.

### 6. Explore/exploit policy for ~22 posts a month

**Split:** about **70% exploit / 30% explore**. That is 15–16 posts using current best patterns and 6–7 experimental slots. **Add 3–4 Trial Reels a month on top** where production allows. Trials don't reach followers, so they don't cost feed slots, and Instagram says they don't affect your standard reels' ranking.

**Mechanism: discounted Beta-Bernoulli Thompson sampling.**
1. Keep 3–5 candidate *arms* per variable (for example, 4 hook patterns). More arms than that cannot be learned at this volume.
2. For each explore slot, draw a sample from each arm's Beta posterior and use the arm with the highest draw.
3. After the day-7 score, add 1 to wins or losses.
4. **Discount old evidence:** multiply all α and β counts by 0.97 after each new post (half-life ≈ 23 posts ≈ 1 month), with a floor at the Beta(1,1) prior. This is the "discounted Thompson sampling" approach from the non-stationary bandit literature (e.g., Raj & Kalyani, "Taming Non-stationary Bandits: A Bayesian Approach," 2017, which "works by discounting the effect of past observations"; Zhu, "Thompson Sampling for Non-Stationary Bandit Problems," *Entropy* 2025; Trovò et al., sliding-window TS, 2020). It lets the system adapt when audiences tire of a hook or Instagram changes. The specific factor 0.97 is a heuristic.
5. Exploit slots use the current best pattern (highest posterior mean among promoted patterns). Keep exploit content varied in topic so the audience doesn't fatigue.

**Which variables to test first, in order:**

1. **Hook pattern (first 1–3 seconds / first slide).** This is the biggest lever and the cheapest to vary. Skip rate and watch-through respond immediately, and Instagram's ranking predicts early drop-off and watching to the end. Example arms: question hook, bold claim/myth-bust, "POV/relatable" scene, practitioner-to-camera tip, before/after or outcome-first.
2. **Topic pillar** (e.g., stress/sleep, mobility, nutrition myths, studio behind-the-scenes, client stories). This drives sends ("send this to a friend who…") and saves.
3. **Format by goal** (Reel vs carousel). Benchmarks consistently show Reels for reach and carousels for saves. Test whether that holds for NUMA rather than assuming it.
4. **CTA type** (send-to-friend, save-for-later, comment keyword → DM, book via link). Score these on the conversion review, not the composite.
5. **Time slot: last, and not with the bandit.** Public studies disagree. Buffer's 9.6M-post analysis favours Thursday 9 a.m. and Wednesday noon/6 p.m., while Sprout Social's 2025 study of 30K brands and creators (reported by Social Media Today) found the best times were "Mondays through Thursdays between 10am and 3pm." Effects are small relative to content variance. Rotate 2–3 slots in a fixed block over a month and compare medians. Change slot only if one differs by ≥1.25× over at least 8 posts each.

**Test one variable at a time per post.** Keep everything else at the current "core" setting so wins can be attributed.

### 7. Using Trial Reels as A/B tests

- **Design:** Make 2–3 versions of one idea that differ **only in the hook** (first 3 seconds and on-screen text). Post them as trials on the same day, an hour or so apart. Practitioners report doing exactly this (e.g., five trials of one clip, one morning). Use *new* footage or recuts. Instagram warns repeats "may get limited reach," and one practitioner's 40-trial log found new footage beat recycled footage (median 2,274 vs 564 views).
- **Read at 24–72h** on views, shares/views and likes/views. These are the metrics Trial insights expose.
- **Compare only against other trials.** Trials reach non-followers only, start slower, and lack follower engagement, so they will look worse than regular Reels. Mosseri explicitly recommends trial-vs-trial comparison.
- **Graduate the winner** by sharing it to everyone, and count its regular-post score in the main pool.
- **Limits:** This is not a randomised split. Each version gets a different non-follower audience at a different time, and Instagram may treat near-duplicates as repeats. Treat a trial win as one "try" for the hook arm, not as proof. Trials say nothing about follower-side metrics, saves from loyal clients, or bookings. Instagram's own success figure is narrow. After trying trials, "40% of creators started posting reels more often and of those who did, 80% saw an increase in reels reach from non-followers" (an internal before/after look at 400K+ creators). It shows association, not a causal 80% lift.

### 8. Seasonality and holiday effects

Wellness has strong calendar effects, and they will mislead a naive tracker. Adjust's 2024 data showed health & fitness app installs falling 18% on Christmas Eve/Day, then rising 27% on December 30 and 46% on January 1. Placer.ai found US fitness visits in January 2025 were 21.2% higher than in December 2024. These figures are for app and foot traffic, not Instagram engagement, so read them as directional for NUMA's audience (evidence: medium).

Rules:
- **Flag holiday weeks** (roughly Dec 20–Jan 5, plus local holidays and school breaks). Score these posts but **exclude them from promote/retire decisions.**
- **Treat January wins as provisional.** A pattern that wins in January must win again in February–March before promotion, because the resolution surge lifts everything.
- The rolling 20-post median absorbs slow seasonal drift automatically. Never compare a post with a different season's median.
- Year-over-year comparisons only become possible after 12+ months of logging. Plan to build a simple monthly seasonal index from NUMA's own reach medians.

### 9. When to retire or promote, in practice

- **Promoted patterns** become the default for exploit slots, but cap any single hook pattern at about 40% of monthly posts to slow fatigue.
- **Retired patterns** leave the explore pool for 3 months. After that they may re-enter once, because audiences and the algorithm change.
- **Re-validate every quarter.** Any core pattern whose last-8 median falls below 1.0× gets demoted to explore.

## Recommendations (operating checklist)

1. Build a sheet or Notion database with the fields above. Pull API metrics daily with a scheduler or connector, and **save Story metrics before 24h.**
2. Pre-tag every post (format, hook, topic, CTA, slot, trial, holiday) **before** publishing, to avoid post-hoc storytelling.
3. Score at 72h (provisional) and day 7 (final) with the log₂-index formulas. Compute wins against the trailing 20-post same-format median.
4. Each month: about 15 exploit posts, 6–7 explore posts chosen by discounted Thompson sampling over hook patterns, then topics, then formats. Add 3–4 hook-variant Trial Reels.
5. Apply the promote/retire table at a fixed monthly review and change it only at that review.
6. Put UTM links in the bio and on every Story link sticker. Add booking codes or a "how did you hear" field. Review bookings per 1,000 reach monthly by campaign.
7. After 3 months, check whether the composite weights predict what NUMA actually cares about (follows and bookings). If sends correlate with bookings for NUMA, raise their weight. If not, shift weight toward follows and profile activity.

## Pitfalls and How to Avoid Them

| Pitfall | Why it fools you | Fix |
|---|---|---|
| **Viral outliers** | One 10× post inflates means and "proves" whatever pattern it used. Breakouts are a few percent of Reels. | Medians, log₂ clipping at ±2, and win/loss outcomes. A viral post counts as one win, not twenty. |
| **Regression to the mean** | The post after a breakout almost always "underperforms," which tempts you to abandon what worked. | Judge patterns over ≥6–8 tries, never one-off pairs. |
| **Novelty effects** | A new hook style wins at first because it is different, then fades. Kohavi and colleagues treat novelty and primacy as core threats to experiment validity. | Discounting (γ≈0.97), the demotion rule, and the 40% usage cap. |
| **Follower growth shifting baselines** | More followers raises raw reach and likes without any content improvement. | Per-reach rates and rolling same-format medians. Watch the follower vs non-follower split where Instagram shows it. |
| **Comparing different ages** | A 3-day-old post looks worse than a 3-week-old one. | Score at fixed ages (72h, day 7) only. |
| **Data lag** | Fresh numbers can be up to 48h behind. | No decisions before 72h. |
| **Confounded tests** | Changing hook, topic and slot together makes wins unattributable. | One variable per experimental post. Keep the rest at core settings. |
| **Format cross-comparison** | Reels and carousels have different distributions and denominators (benchmarks even disagree on which "engages more"). | Separate medians per format. Compare formats only on per-goal scores. |
| **Metric definition changes** | Impressions were deprecated for new media from July 2, 2024, and "views" now counts replays. Some metrics are "in development" or "estimated." | Version your sheet. When Meta changes a definition, restart the affected medians. |
| **Trial Reels misread** | Trials lack follower lift, so they look weak against regular Reels. | Compare trials only with trials. |
| **Attribution gaps for clicks and bookings** | Reels don't expose per-post link taps or profile visits via the API. | UTMs, codes, Story link stickers, monthly campaign-level review. |
| **Too many arms** | Eight hook styles at ~6 explore slots a month never converge. | 3–5 arms per variable. Retire fast. |
| **Posting-time obsession** | Generic "best time" studies conflict and the effects are small. | Test time last, with blocked rotation, and require ≥1.25× over ≥8 posts each. |

## Sources and Evidence Levels

| Recommendation | Primary basis | Evidence level |
|---|---|---|
| Optimise per-reach rates (sends, likes) and watch time | Mosseri (May 2024 Q&A, Jan 2025 ranking video via Social Media Today); "Instagram Ranking Explained" (May 31, 2023) | **Official statements: high.** "Sends = 3–5× likes" is unsupported. |
| Sends weighted highest in composite | Mosseri: sends per reach "correlate more… with overall reach than anything else"; sends "slightly more important for unconnected content" | Official direction: high. **Exact weights: heuristic.** |
| Saves lower weight for Reels | Ranking Explained lists saves for Explore, not among Reels' top predictions | Official (medium-high) plus inference |
| 48h data lag; Story metrics expire in 24h via API; <5 not returned | Meta Instagram Media Insights API reference | **Platform documentation: high** |
| 72h provisional / day-7 final judging | Metricool 2026 (65% of Reel views in 3 days); Socialinsider (40M Reels, decline after day 5–10) | Large vendor studies: medium-high. **Day-7 lock: reasoned inference.** |
| Per-Reel metrics available (Follows in-app; follows/profile visits API-only for posts/Stories) | Instagram Help Centre (Reels insights); Meta API reference | Platform documentation: high (some in-app screens may show more; unconfirmed) |
| Normalise to own rolling median; log clip | Statistical practice for skewed data; viral.app breakout data (4.9% of Reels ≥10× median) | Statistical reasoning (high) plus practitioner/vendor data (medium) |
| Bayesian win/loss with 6–8-try thresholds | Beta-Bernoulli posteriors (Russo et al., 2018); sign-test arithmetic | Statistical literature: high. **Threshold choices: heuristic.** |
| Thompson sampling with discounting | Russo, Van Roy et al. (2018); discounted/sliding-window TS (Raj & Kalyani 2017; Zhu, *Entropy* 2025; Trovò et al. 2020) | Bandit literature: high. **Discount factor 0.97: heuristic.** |
| 70/30 explore/exploit split | No published Instagram-specific evidence | **Reasoned inference / heuristic** |
| Test hooks first | Ranking predicts early drop-off and completion; skip rate metric exists | Official (medium) plus practitioner reports (low-medium) |
| Trial Reels as hook tests; compare trial vs trial | Help Centre (independent ranking, 24h insights, repeat-content warning, 200-follower eligibility); Dec 2024 launch post (72h auto-share); Mosseri trial-vs-trial advice; June 2025 "40%/80%" figure | Official: high (the "40/80" stat is self-reported and correlational) |
| Format-by-goal (Reels for reach/sends, carousels for saves) | Socialinsider, Buffer, Metricool 2026 benchmarks | Large benchmark studies: medium (conflicting denominators) |
| Posting time tested last | Buffer 9.6M posts vs Sprout Social's Mon–Thu 10am–3pm finding | Benchmarks conflict: low-medium |
| Holiday exclusion / January caution | Adjust 2024 holiday app data; Placer.ai fitness visits | Adjacent-industry data: medium (not Instagram-specific) |
| Novelty-effect guardrails | Kohavi, Tang & Xu, *Trustworthy Online Controlled Experiments* (2020); Sadeghi et al., "Novelty and Primacy: A Long-Term Estimator for Online Experiments," *Technometrics* 2022 | Experimentation literature: high (transfer to social content is inference) |

## Caveats

- **Thin evidence.** No published study tests bandit policies, thresholds or explore ratios on small Instagram accounts. Everything in sections 5–6 is a principled heuristic built from general statistics and bandit theory. Calibrate it on NUMA's own data after a quarter.
- **Changing documentation.** Instagram's documentation changes often. The Trial Reels 72-hour window and follower thresholds have already been reworded, several metrics are labelled "estimated" or "in development," and in-app screens may show metrics (such as follower/non-follower splits on Reels) that the Help Centre text I checked does not document.
- **Vendor-sourced benchmarks.** Metricool, Socialinsider and Buffer sample their own customers and use different denominators. Use them for direction, not as targets.
- **Correlation, not causation.** Even with this system, NUMA learns which patterns *coincide* with better performance. The algorithm, audience mood and competitors all shift, which is why the system discounts old evidence and re-validates winners.
