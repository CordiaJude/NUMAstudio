# Questions for Katie

**NUMA Studio setup: asked once, and never again.**

These 51 questions are the only ones NUMA Studio will ever ask (spec p.54-57). Every answer becomes brand data (brand/brand.json) or a planning rule, so the system can make every reel, caption and post on its own from then on.

- Short answers are fine. A few words, a link or a list is plenty.
- "Don't know" is fine too. The system keeps its researched default (shown under each question) until you know.
- Write on a printout, reply in a copy of this page, or answer out loud while Jude types. Jude enters them with `/brand-setup`.
- Three defaults if you skip them: children never appear (Q27), reels post automatically (Q34), nothing needs to be seen first (Q35).

Under each question, "Fills" is where the answer is stored, so Jude knows exactly where it goes.

## A. The business

**1.** How do you write the name: NUMA, Numa, or NUMA Wellness Collective, and when?  
_Fills:_ `business.name_usage`  
_If you don't know:_ keep: NUMA short, NUMA Wellness Collective full

_Answer:_ ______________________________________

**2.** Address, the area of Mobile you're in, and how people describe where you are.  
_Fills:_ `business.location`  
_If you don't know:_ keep the research address

_Answer:_ ______________________________________

**3.** Regular hours, and every closure or holiday you already know about for the next 6 months.  
_Fills:_ `business.hours`, `closures.known`  
_If you don't know:_ keep "opens 5:30 AM Mon-Thu"; closures: US holidays only

_Answer:_ ______________________________________

**4.** Every service and its price: memberships, drop-ins, class packs, 1-on-1s, and what's included in each.  
_Fills:_ `offerings.sessions`, `offerings.memberships`  
_If you don't know:_ keep; never state a price that is not confirmed

_Answer:_ ______________________________________

**5.** Discover NUMA ($49): exactly what's included, how long it lasts, and where people sign up (which link)?  
_Fills:_ `offerings.offers`, `business.booking`  
_If you don't know:_ keep $49 / one month / discover.numawellness.org

_Answer:_ ______________________________________

**6.** Numa Nights and Clinical Conversations: how often, who leads them, what happens, and the next dates.  
_Fills:_ `offerings.events`  
_If you don't know:_ keep names only; no dates in reels

_Answer:_ ______________________________________

**7.** Who's on the team: names, roles, and who's comfortable being on camera.  
_Fills:_ `team.collective`, `team.on_camera`  
_If you don't know:_ keep research list; on camera: nobody named

_Answer:_ ______________________________________

**8.** The founding story in your words: why NUMA, the old house, the opening date, the hardest moment.  
_Fills:_ `business.founding_story`  
_If you don't know:_ left empty for now; no founding-story reels

_Answer:_ ______________________________________

**9.** What makes NUMA different from every other gym, spa or studio in Mobile?  
_Fills:_ `positioning.differentiator`  
_If you don't know:_ keep `positioning.own_in_mobile` research

_Answer:_ ______________________________________

**10.** Who do you see most at NUMA (age, life stage, why they come), and who do you want more of?  
_Fills:_ `positioning.target_audiences`  
_If you don't know:_ keep the research list

_Answer:_ ______________________________________

**11.** The top three reasons people join, and the top three reasons people hesitate (cold fear, price, time, "not for me").  
_Fills:_ `positioning.join_reasons`, `positioning.hesitations`  
_If you don't know:_ left empty for now; scripts answer the common worries (cold, price, time) only in general terms

_Answer:_ ______________________________________

**12.** Any member stories you love, and would those members agree to be featured?  
_Fills:_ `positioning.member_stories`  
_If you don't know:_ none

_Answer:_ ______________________________________

## B. Goals

**13.** What should these reels do in the next 90 days: more trials, more memberships, fuller events, more followers? Rank them.  
_Fills:_ `positioning.goals_90d`  
_If you don't know:_ left empty for now; /plan-month keeps the content mix and one sales reel a week

_Answer:_ ______________________________________

**14.** Which offer matters most right now?  
_Fills:_ `offerings.priority_offer`  
_If you don't know:_ Discover NUMA

_Answer:_ ______________________________________

**15.** Is anything full (classes at capacity) that you should not promote?  
_Fills:_ `offerings.do_not_promote`  
_If you don't know:_ empty list

_Answer:_ ______________________________________

**16.** What's coming in the next 3 months: launches, new services, events, price changes, anniversaries?  
_Fills:_ `offerings.upcoming`, `offerings.events`  
_If you don't know:_ empty list

_Answer:_ ______________________________________

## C. Brand and taste

**17.** Do you have official brand colors (codes) and fonts? Who made your logo, and are there light and dark versions?  
_Fills:_ `palette`, `fonts`, `assets.wordmark_light`, `assets.logo_credit`  
_If you don't know:_ keep the research palette, Liberation Serif, dark wordmark only

_Answer:_ ______________________________________

**18.** Show us 3 Instagram accounts whose videos you love, and say what you love about each.  
_Fills:_ `voice.inspiration_accounts`  
_If you don't know:_ none

_Answer:_ ______________________________________

**19.** Anything you dislike seeing in wellness content (too salesy, too clinical, too "influencer")?  
_Fills:_ `voice.dislikes`  
_If you don't know:_ left empty for now; the voice description rules apply

_Answer:_ ______________________________________

**20.** Words you always use, and words you never want used.  
_Fills:_ `voice.words_always`, `voice.words_never`  
_If you don't know:_ none

_Answer:_ ______________________________________

**21.** What do you call the people who come: members, community, the collective?  
_Fills:_ `voice.community_word`, `captions.hashtags.community_tag`  
_If you don't know:_ members; community_tag stays null (captions use the 3 base tags)

_Answer:_ ______________________________________

**22.** Emojis in captions: yes, a few, or none?  
_Fills:_ `voice.emoji`  
_If you don't know:_ 0-2 per caption, earthy only

_Answer:_ ______________________________________

**23.** Music you picture under NUMA videos (calm piano, ambient, acoustic, upbeat), and anything you never want.  
_Fills:_ `voice.music_taste`  
_If you don't know:_ left empty for now; calm instrumental beds, licensed only (`posting.music_rule`)

_Answer:_ ______________________________________

**24.** Topics that are off-limits, and anything a lawyer, doctor or insurer has told you not to claim.  
_Fills:_ `voice.off_limits_topics`, `claims.banned`  
_If you don't know:_ none beyond the existing claims policy

_Answer:_ ______________________________________

## D. People and consent

**25.** Is there a consent or photo release for members today? If not, can one be added to sign-up?  
_Fills:_ `consent.release_form`  
_If you don't know:_ left empty for now; no member face without a Consent List row

_Answer:_ ______________________________________

**26.** Who on the team may appear in videos, and who may not?  
_Fills:_ `team.on_camera`  
_If you don't know:_ nobody named: no team faces

_Answer:_ ______________________________________

**27.** Are children ever at NUMA, and should they ever appear? (Default: never.)  
_Fills:_ `consent.children`  
_If you don't know:_ never

_Answer:_ ______________________________________

**28.** Will you record voiceovers yourself? Would you allow a cloned version of your voice for days you don't record?  
_Fills:_ `team.voiceover`, `consent.voice_clone`  
_If you don't know:_ voice_clone false: preset voice or text-only reels

_Answer:_ ______________________________________

## E. Filming

**29.** Who will film: you, staff, or both? Which phone?  
_Fills:_ `team.filming`  
_If you don't know:_ left empty for now; shoot cards are written to whoever films

_Answer:_ ______________________________________

**30.** Best times for a 20-minute batch shoot each week, and when the light is best in each room.  
_Fills:_ `team.filming`  
_If you don't know:_ left empty for now; shoot cards batch by room, no set time

_Answer:_ ______________________________________

**31.** Any rooms or moments that should never be filmed?  
_Fills:_ `team.filming`  
_If you don't know:_ left empty for now; the consent rules decide who appears

_Answer:_ ______________________________________

## F. Accounts and posting

**32.** Is NUMA's Instagram a Business or Creator account, and is it linked to the Facebook Page? Who's the admin?  
_Fills:_ `socials.instagram_account`, `socials.facebook`  
_If you don't know:_ left empty for now; /numa-setup step 3 reads the account type

_Answer:_ ______________________________________

**33.** Who owns the Google Drive, the Google Business profile and the Higgsfield account?  
_Fills:_ `business.account_owners`, `socials.google_business_profile`  
_If you don't know:_ left empty for now

_Answer:_ ______________________________________

**34.** Should reels post automatically, or land ready-to-post for someone to publish? (Default: post automatically.)  
_Fills:_ `posting.auto_post`  
_If you don't know:_ true

_Answer:_ ______________________________________

**35.** Is there any post type you always want to see first, such as offers or anything showing members? (Default: none.)  
_Fills:_ `posting.see_first`, `posting.require_approval`  
_If you don't know:_ see_first []; require_approval false

_Answer:_ ______________________________________

**36.** Where should every call to action point: the Discover NUMA page, the app, or the link in bio?  
_Fills:_ `business.cta_link`  
_If you don't know:_ https://discover.numawellness.org

_Answer:_ ______________________________________

**37.** Are you running paid ads? If so, budget and goal.  
_Fills:_ `positioning.paid_ads`  
_If you don't know:_ not running

_Answer:_ ______________________________________

**38.** Where should the Monday digest go: email, text, or the Claude app?  
_Fills:_ `posting.digest_destination`  
_If you don't know:_ claude app (the scheduled task's notification)

_Answer:_ ______________________________________

## G. What's worked

**39.** Your best-performing posts ever, and why you think they worked.  
_Fills:_ `positioning.past_best_posts`  
_If you don't know:_ none

_Answer:_ ______________________________________

**40.** Anything you've tried that flopped.  
_Fills:_ `positioning.past_flops`  
_If you don't know:_ none

_Answer:_ ______________________________________

**41.** Roughly how many followers today, and how many trials or members come from Instagram?  
_Fills:_ `positioning.audience_size`  
_If you don't know:_ left empty for now

_Answer:_ ______________________________________

## H. Confirm what the research found

**42.** Are these right: 1719 Dauphin St; a 14-person Finnish sauna; 4 cold plunges; opening 5:30 AM Monday to Thursday? What temperature are the plunges and the sauna?  
_Fills:_ `business.location`, `business.facility`, `business.hours`, `business.temperatures`  
_If you don't know:_ keep research; no temperatures in reels

_Answer:_ ______________________________________

**43.** Which phone number should be used everywhere? (Listings show 251-289-1758, 251-310-3656 and 251-423-8238.)  
_Fills:_ `business.phone`  
_If you don't know:_ left empty for now; no phone number in any post

_Answer:_ ______________________________________

**44.** Is the team list right: counselors Scott Moore, LaJuan Humbert (LPC) and Matt Henson (ALC); massage Kandi Roemhildt; facials Natalia Lichtenberger; breathwork guides Fallon Gleason and Joseph Irby? Who would do collab posts?  
_Fills:_ `team.collective`  
_If you don't know:_ keep research list; no collab with a provider

_Answer:_ ______________________________________

**45.** Katie: are you comfortable being the on-camera expert for "Ask the DPT"? What topics would you want to cover, and what would you never comment on?  
_Fills:_ `positioning.ask_the_dpt`  
_If you don't know:_ comfortable unknown: Ask the DPT runs as text-on-screen answers

_Answer:_ ______________________________________

**46.** Which red light panels does NUMA use (make and model), and do they have an FDA clearance? For what exactly?  
_Fills:_ `claims.modalities.red_light.device_facts`  
_If you don't know:_ left empty for now; no device facts in reels

_Answer:_ ______________________________________

**47.** Where does the website's "57 minutes of sauna and 11 of cold a week" line come from? (It's a dosing claim that needs a lawyer's OK before it's used in posts.)  
_Fills:_ `claims.dosing_line`  
_If you don't know:_ blocked stays true

_Answer:_ ______________________________________

**48.** Does the member consent form cover appearing in social posts and AI processing of photos? If not, can that wording be added?  
_Fills:_ `consent.social_posts_covered`, `consent.ai_processing_covered`  
_If you don't know:_ both false: no member face in posts or AI motion without a Consent List row covering it

_Answer:_ ______________________________________

**49.** Would NUMA partner with Mission Fitness, barre3 Mobile, Pure Barre Mobile, run clubs or University of South Alabama teams for collab posts? Any existing relationships?  
_Fills:_ `positioning.collab_partners`  
_If you don't know:_ keep the research order

_Answer:_ ______________________________________

**50.** Would NUMA offer a rate for healthcare workers or students, or a bring-a-friend first plunge?  
_Fills:_ `offerings.rates_considered`, `offerings.offers`  
_If you don't know:_ left empty for now; never promote an unconfirmed rate

_Answer:_ ______________________________________

**51.** Is there an advertising lawyer NUMA already works with to review the claims policy once?  
_Fills:_ `posting.legal_counsel`  
_If you don't know:_ left empty for now; Jude finds counsel; auto-posting stays gated

_Answer:_ ______________________________________
---

**Thank you.** That is everything. From here on NUMA Studio plans, edits and posts on its own; your only job is to film what a shoot card asks for, when it asks.
