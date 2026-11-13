# Questions for Katie

**Numa Studio setup: asked once, and never again.**

These 51 questions are the only ones Numa Studio asks the owners (spec p.54-57). The owners answered them on **2026-11-13**; every answer is now brand data in `brand/brand.json` (or, for people and consent, the private `STATE/people.json`), and those answers override research and earlier defaults (DECISIONS D25). This page records what each answer became and what is still open.

- **Public page.** It names only roles plus the co-founders (and, as question owners, Emma and Jodie). Staff, instructor, provider and member names, on-camera status, collab handles and consent details live in `STATE/people.json` (Drive `_Plan/people.json`), never in this repo.
- **Open questions** are answered by the owner named on each one. Jude enters answers with `/brand-setup`; until then the crew follows the "Until answered" rule.
- Under each question, "Fills" is where the answer is stored.

## Still open (from the owners' answers)

| Q | Open item | Owner |
|---|---|---|
| Q3 | Opening hours may change after the Mindbody data is pulled | Scott and Katie |
| Q6 | Numa Nights and Community Days about every 4 months: confirm the rhythm and dates | Scott and Katie |
| Q13 | Rank the 90-day goals (suggested: memberships, trials, fuller events, followers) | Scott and Katie |
| Q16 | Super Escape: first Thursday (12/3, 1/7, 2/4) or first Wednesday? | Scott and Katie |
| Q16 | To confirm: Member Appreciation Party (Dec 1), Winter Solstice (Dec 22), a February community event | Scott and Katie |
| Q16 | Black Friday gift card bonus: can it be used on massage and facials? (checking with the massage provider) | Scott |
| Q16 | Black Friday membership BOGO: "equal or lesser value" or "equal or greater"? | Scott and Katie |
| Q16 | Black Friday membership BOGO: who cancels a gifted membership after the month, staff or the friend? (staff is safer) | Scott and Katie |
| Q17 | Logo files (every colour version exists; none supplied yet) | Scott and Katie |
| Q18 | More accounts you like | Emma or Jodie |
| Q20 | "Offer" or "deal"? | Scott and Katie |
| Q23 | Music: source and taste | Emma |
| Q27 | Children: never, or only with a parent's yes on record? | Scott and Katie |
| Q32 | Instagram: Business or Creator account, Facebook Page link, admin | Scott or Emma |
| Q33 | Who owns the Google Drive, Google Business Profile and Higgsfield accounts | Scott and Katie |
| Q38 | Monday digest delivery: email, text, or the Claude app? | Scott and Katie |
| Q42 | The sauna's capacity | Scott |
| Q45 | Ask the DPT: on camera? Topics, and never-comment topics | Katie |
| Q46 | Red light panel: FDA-cleared, and for what? | Scott and Katie |
| Q47 | Source of "57 minutes sauna, 11 minutes cold" for the Doc 04 science table | Scott |
| Q49 | AMP agreement: posting terms | Scott and Katie |
| Q50 | Student and over-60 offers | Scott and Katie |

## Open questions from the plugin

| Question | Owner | Stored in | Until answered |
|---|---|---|---|
| Who approves each post, and how: a checkbox on the plan Sheet, a reply, or a Meta Business Suite draft? | Scott and Katie | `posting.approver` | posts are staged, never posted, until approved (DECISIONS D26) |
| May a generic, non-cloned AI voice read the lines when Scott hasn't recorded? | Scott and Katie | `voice.generic_ai_allowed` | no AI voice: music plus on-screen text |
| Where does the music come from (library, licence)? | Emma | `posting.music_source` | licensed library music or the real sound |
| Where is Doc 04 (the consent log)? A Drive link. | Scott and Katie | `consent.log` | the _Plan Consent List is the copy the crew checks |
| Does a person's yes cover sending their face to AI motion? | Scott and Katie | `consent.ai_processing_covered` | no member face goes to AI motion |
| Do licensed brand font files (Domaine Sans Text Light, Avenir Next) exist on the Mac for local renders? | Scott and Katie | `fonts.brand_fonts` | the bundled open stand-ins |
| Logo files: the designer's phoenix mark and wordmark in every colour version | Scott and Katie | `assets.logo`, `assets.wordmark_light` | the bundled website copies |
| Which email tool sends member emails (where NEWBIE may appear)? Mindbody is the booking system (confirmed). | Scott and Katie | `posting.email_tool` | no email drafts |

## A. The business

**1.** How do you write the name: NUMA, Numa, or NUMA Wellness Collective, and when?  
_Fills:_ `business.name_usage`  
_Status:_ Answered  

_Answer (2026-11-13):_ Always "Numa", never "NUMA". Full name: Numa Wellness Collective. The free track is always "The Numa Reset".

**2.** Address, the area of Mobile you're in, and how people describe where you are.  
_Fills:_ `business.location`  
_Status:_ Answered  

_Answer (2026-11-13):_ 1719 Dauphin Street, Mobile, AL 36604. Midtown Mobile, across from Soul Caffeine and next to Via, on Dauphin Street.

**3.** Regular hours, and every closure or holiday you already know about for the next 6 months.  
_Fills:_ `business.hours`, `closures.known`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ check `business.hours.under_review` before printing hours  

_Answer (2026-11-13):_ Mon, Tue, Wed, Fri 5:30am-6:30pm; Thu 6:00am-6:30pm; Sat 8:00am-11:30am; closed Sunday. No classes 1:30-3:30pm daily. Closures: Thanksgiving Nov 25-27, Christmas Eve and Day, New Year's Eve open until 12pm, New Year's Day, Good Friday to Easter Sunday (Mar 26-28, 2027). Open: the hours are under review after the Mindbody data is pulled.

**4.** Every service and its price: memberships, drop-ins, class packs, 1-on-1s, and what's included in each.  
_Fills:_ `offerings.sessions`, `offerings.memberships`  
_Status:_ Answered  

_Answer (2026-11-13):_ Every price is in `offerings.sessions`, `offerings.visit_pass_bundles`, `offerings.memberships` and `offerings.offers`, exactly as given. Massage, facials and counseling are priced by each provider (never stated). Gift cards in any amount.

**5.** Discover NUMA ($49): exactly what's included, how long it lasts, and where people sign up (which link)?  
_Fills:_ `offerings.offers`, `business.booking`  
_Status:_ Answered  

_Answer (2026-11-13):_ Discover Numa, $49: one month, 3 classes, 3 red light sessions, unlimited Flow Space. One time only, no commitment, ends on its own. Sign up through the bio link, linktr.ee/numawc.

**6.** Numa Nights and Clinical Conversations: how often, who leads them, what happens, and the next dates.  
_Fills:_ `offerings.events`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ no event dates in posts until they are in `offerings.promotions`  

_Answer (2026-11-13):_ Numa Nights and Community Days are special events, about once every 4 months (possible February, then June and October). Clinical Conversations is cancelled for now: never promote it. Open: the 4-month rhythm is not confirmed.

**7.** Who's on the team: names, roles, and who's comfortable being on camera.  
_Fills:_ `team.collective`, `team.on_camera`  
_Status:_ Answered  

_Answer (2026-11-13):_ Co-founders Scott and Katie Moore, plus a yoga teacher, two breathwork guides, studio staff, the person who posts to social (Emma), two counselors, a massage therapist, an esthetician and a partner physician. Names and who may be featured are in the private STATE/people.json, not in this repo. On camera: Scott, Katie, instructors and staff, and members who say yes.

**8.** The founding story in your words: why NUMA, the old house, the opening date, the hardest moment.  
_Fills:_ `business.founding_story`  
_Status:_ Answered  

_Answer (2026-11-13):_ "We started Numa because we needed it." It started from the owners' own burnout. Opened Nov 1, 2025 in a restored building; they built their own sauna and plunges. Hardest moments: construction and permit delays; this year, seeing the gaps in their leadership.

**9.** What makes NUMA different from every other gym, spa or studio in Mobile?  
_Fills:_ `positioning.differentiator`  
_Status:_ Answered  

_Answer (2026-11-13):_ Breath comes first; a guide is always nearby; the space feels premium; a real community; counseling, massage and facials under one roof.

**10.** Who do you see most at NUMA (age, life stage, why they come), and who do you want more of?  
_Fills:_ `positioning.target_audiences`  
_Status:_ Answered  

_Answer (2026-11-13):_ Most often working moms, late 30s to mid 40s, tired and overwhelmed, usually invited by a friend. Also men, athletes, couples, kids 10+ with a parent, people who start with yoga. Want more of: people who long to change and live differently.

**11.** The top three reasons people join, and the top three reasons people hesitate (cold fear, price, time, "not for me").  
_Fills:_ `positioning.join_reasons`, `positioning.hesitations`  
_Status:_ Answered  

_Answer (2026-11-13):_ Join: a break from the chaos, a friend's invite, the community. Hesitate: fear of the cold, not sure the time is worth it, women and younger people don't want to come alone.

**12.** Any member stories you love, and would those members agree to be featured?  
_Fills:_ `positioning.member_stories`  
_Status:_ Answered  

_Answer (2026-11-13):_ All member stories are in Doc 04 with a yes on record. The four to lead with, and the one member cleared for one existing post only, are named in STATE/people.json (private).

## B. Goals

**13.** What should these reels do in the next 90 days: more trials, more memberships, fuller events, more followers? Rank them.  
_Fills:_ `positioning.goals_90d`  
_Status:_ Open (owner: Scott and Katie)  
_Until answered:_ plan with the suggested order  

_Answer (2026-11-13):_ Suggested order: 1. memberships, 2. trials, 3. fuller events, 4. followers (an adviser's advice: grow Foundation memberships).

**14.** Which offer matters most right now?  
_Fills:_ `offerings.priority_offer`  
_Status:_ Answered  

_Answer (2026-11-13):_ Discover Numa ($49) is the paid door; The Numa Reset (free breathwork track) is the free door.

**15.** Is anything full (classes at capacity) that you should not promote?  
_Fills:_ `offerings.do_not_promote`  
_Status:_ Answered  

_Answer (2026-11-13):_ Not consistently. Saturday morning Experience classes are most often full: don't send new people there; point them to weekday classes.

**16.** What's coming in the next 3 months: launches, new services, events, price changes, anniversaries?  
_Fills:_ `offerings.upcoming`, `offerings.events`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ unconfirmed items are never promoted  

_Answer (2026-11-13):_ Confirmed promotions with dates are in `offerings.promotions` (bring-a-friend through Nov 30; Holiday Day Pass and Unlimited Weekly Pass Nov 23-Dec 31; Black Friday Nov 27-30; Super Escape monthly; holiday party rentals; Friday Escape at 12pm from Jan 1; Polished and Prepped 1/8 and 1/11; Date Night 1/15). NEWBIE (50% off a first class, from Dec 1) is emails and front desk only. Not promoted: Clinical Conversations, merch, Embodied Story Group. No price changes. Open: Super Escape day (first Thursday or first Wednesday); to confirm: Member Appreciation Party (Dec 1), Winter Solstice (Dec 22), a February community event, student and over-60 offers; Black Friday questions (below).

## C. Brand and taste

**17.** Do you have official brand colors (codes) and fonts? Who made your logo, and are there light and dark versions?  
_Fills:_ `palette`, `fonts`, `assets.wordmark_light`, `assets.logo_credit`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ bundled wordmark and phoenix mark; open-font stand-ins  

_Answer (2026-11-13):_ Dark Teal #06272E, Tan/Gold #CA8B3A, Beige #F2EADB, Light Blue #C6E2E3, Blue #94BBC7, Light #FBFAF8. Fonts: Domaine Sans Text Light and Avenir Next (commercial: never in the repo; open stand-ins are bundled). Logo: a phoenix mark and a wordmark by the owners' designer; every colour version exists. Open: the logo files, and whether licensed font files exist for local renders.

**18.** Show us 3 Instagram accounts whose videos you love, and say what you love about each.  
_Fills:_ `voice.inspiration_accounts`  
_Status:_ Partly open (owner: Emma or Jodie)  

_Answer (2026-11-13):_ An adviser likes The Home Spruce on Instagram for its simple, clear messaging. Videos and real people perform best for Numa. Open: more examples.

**19.** Anything you dislike seeing in wellness content (too salesy, too clinical, too "influencer")?  
_Fills:_ `voice.dislikes`  
_Status:_ Answered  

_Answer (2026-11-13):_ Quote cards, designed flyers and posters, salesy lines, fear or pressure, shaming, anything that makes Numa the hero, and "optimized" talk.

**20.** Words you always use, and words you never want used.  
_Fills:_ `voice.words_always`, `voice.words_never`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ write "offer"  

_Answer (2026-11-13):_ Always: take a deep breath, calm in the chaos, show up, rhythm, return to yourself, Visit Passes. OK now: transformation, transformative, journey. Never: NUMA, credits, Explore Numa, Discover Pass, cheap, heal, treats, cures (the claims scanner flags each). Open: "offer" or "deal"? Doc 03 says "offer".

**21.** What do you call the people who come: members, community, the collective?  
_Fills:_ `voice.community_word`, `captions.hashtags.community_tag`  
_Status:_ Answered  

_Answer (2026-11-13):_ Members, our people, the movement, the collective. (The community hashtag is still unchosen.)

**22.** Emojis in captions: yes, a few, or none?  
_Fills:_ `voice.emoji`  
_Status:_ Answered  

_Answer (2026-11-13):_ None. The claims scanner flags any emoji.

**23.** Music you picture under NUMA videos (calm piano, ambient, acoustic, upbeat), and anything you never want.  
_Fills:_ `voice.music_taste`  
_Status:_ Open (owner: Emma)  
_Until answered:_ licensed library music or the real sound  

_Answer (2026-11-13):_ Music source and taste. Never trending or popular songs.

**24.** Topics that are off-limits, and anything a lawyer, doctor or insurer has told you not to claim.  
_Fills:_ `voice.off_limits_topics`, `claims.banned`  
_Status:_ Answered  

_Answer (2026-11-13):_ Never say anything treats, heals, cures or prevents a condition. No promised results. Red light "supports" or "improves", never "restores elasticity". No claim that the sauna clears alcohol or that the cold plunge lowers inflammation. Never say a service "is" HSA/FSA eligible. No comparisons to competitors.

## D. People and consent

**25.** Is there a consent or photo release for members today? If not, can one be added to sign-up?  
_Fills:_ `consent.release_form`  
_Status:_ Answered  

_Answer (2026-11-13):_ Each person is asked, one at a time, before we show them or use their words. Permissions are logged in Doc 04.

**26.** Who on the team may appear in videos, and who may not?  
_Fills:_ `team.on_camera`  
_Status:_ Answered  

_Answer (2026-11-13):_ Scott, Katie, instructors and staff, and members who say yes. Who not to feature is in STATE/people.json (private).

**27.** Are children ever at NUMA, and should they ever appear? (Default: never.)  
_Fills:_ `consent.children`  
_Status:_ Open (owner: Scott and Katie)  
_Until answered:_ never  

_Answer (2026-11-13):_ Kids 10 and up come (10 to 14 with a parent); past posts showed kids with a parent's yes. Open: never, or only with a parent's yes on record?

**28.** Will you record voiceovers yourself? Would you allow a cloned version of your voice for days you don't record?  
_Fills:_ `team.voiceover`, `consent.voice_clone`  
_Status:_ Answered  

_Answer (2026-11-13):_ Scott records voiceovers. No cloned voices.

## E. Filming

**29.** Who will film: you, staff, or both? Which phone?  
_Fills:_ `team.filming`  
_Status:_ Answered  

_Answer (2026-11-13):_ Anyone working in the studio, on the Numa iPhone 14 Pro.

**30.** Best times for a 20-minute batch shoot each week, and when the light is best in each room.  
_Fills:_ `team.filming`  
_Status:_ Answered  

_Answer (2026-11-13):_ Monday to Thursday, 9 to 11am. On Tuesday there's a yoga class, so film in the Flow Space.

**31.** Any rooms or moments that should never be filmed?  
_Fills:_ `team.filming`  
_Status:_ Answered  

_Answer (2026-11-13):_ Never film counseling rooms when clients are in them or without the counselor's permission; bathrooms and locker rooms while people are changing; the kitchen and breakroom.

## F. Accounts and posting

**32.** Is NUMA's Instagram a Business or Creator account, and is it linked to the Facebook Page? Who's the admin?  
_Fills:_ `socials.instagram_account`, `socials.facebook`  
_Status:_ Partly open (owner: Scott or Emma)  
_Until answered:_ /numa-setup step 3 reads the account type  

_Answer (2026-11-13):_ @numawellnessmobile; posts go out through Meta Business Suite to Instagram and Facebook. Open: Business or Creator account, the Facebook Page link, and who the admin is.

**33.** Who owns the Google Drive, the Google Business profile and the Higgsfield account?  
_Fills:_ `business.account_owners`, `socials.google_business_profile`  
_Status:_ Partly open (owner: Scott and Katie)  

_Answer (2026-11-13):_ The Numa Wellness account, owned by Emma and Scott. Open: who owns the Google Drive, the Google Business Profile and Higgsfield.

**34.** Should reels post automatically, or land ready-to-post for someone to publish? (Default: post automatically.)  
_Fills:_ `posting.auto_post`  
_Status:_ Answered  

_Answer (2026-11-13):_ Nothing goes out without a person approving it (`posting.human_approval_required`).

**35.** Is there any post type you always want to see first, such as offers or anything showing members? (Default: none.)  
_Fills:_ `posting.see_first`, `posting.require_approval`  
_Status:_ Answered  

_Answer (2026-11-13):_ Any post that shows a member needs that member's yes first (`posting.member_yes_required`).

**36.** Where should every call to action point: the Discover NUMA page, the app, or the link in bio?  
_Fills:_ `business.cta_link`  
_Status:_ Answered  

_Answer (2026-11-13):_ The one bio link: linktr.ee/numawc (Discover Numa and The Numa Reset).

**37.** Are you running paid ads? If so, budget and goal.  
_Fills:_ `positioning.paid_ads`  
_Status:_ Answered  

_Answer (2026-11-13):_ None yet. No ads until website tracking is set up.

**38.** Where should the Monday digest go: email, text, or the Claude app?  
_Fills:_ `posting.digest_destination`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ the scheduled task's notification  

_Answer (2026-11-13):_ The weekly recap of last week and the week ahead; Katie and Scott read it now, the Studio Manager later. Open: delivery by email, text, or the Claude app?

## G. What's worked

**39.** Your best-performing posts ever, and why you think they worked.  
_Fills:_ `positioning.past_best_posts`  
_Status:_ Answered  

_Answer (2026-11-13):_ Recoverymaxxing reel 13,100 views; a partner athlete's collab 10,000; "The work you put in" 1,800; event recap "What a night" 1,300; member testimony reel 1,100; local partner collab 911; a member's first cold plunge (collab with 4 accounts). What they share: real people on camera, collabs, and lines about what the member walks out with.

**40.** Anything you've tried that flopped.  
_Fills:_ `positioning.past_flops`  
_Status:_ Answered  

_Answer (2026-11-13):_ The "Feel Fully Rejuvenated" graphic, the Testimony Tuesday quote card, the Attune Together event poster, quote cards, hashtag-only captions. Athletic Advantage launched to zero signups because the bio link was broken.

**41.** Roughly how many followers today, and how many trials or members come from Instagram?  
_Fills:_ `positioning.audience_size`  
_Status:_ Answered  

_Answer (2026-11-13):_ 807 followers on Aug 31, 2026; usual reach 400-700 views per post. Trials from Instagram can't be counted yet (no tracking).

## H. Confirm what the research found

**42.** Are these right: 1719 Dauphin St; a 14-person Finnish sauna; 4 cold plunges; opening 5:30 AM Monday to Thursday? What temperature are the plunges and the sauna?  
_Fills:_ `business.location`, `business.facility`, `business.hours`, `business.temperatures`  
_Status:_ Partly open (owner: Scott)  
_Until answered:_ never state a sauna capacity  

_Answer (2026-11-13):_ 1719 Dauphin St and 4 cold plunges: correct. Opens 5:30am Mon, Tue, Wed and Fri; Thursday 6:00am. Plunges are kept at 44-52°F (a 34° dip is rare: never state it). Sauna runs 175-190°F. Open: the sauna's capacity ("14-person" is not confirmed).

**43.** Which phone number should be used everywhere? (Listings show 251-289-1758, 251-310-3656 and 251-423-8238.)  
_Fills:_ `business.phone`  
_Status:_ Answered  

_Answer (2026-11-13):_ 251-310-3656, everywhere.

**44.** Is the team list right: counselors Scott Moore, LaJuan Humbert (LPC) and Matt Henson (ALC); massage Kandi Roemhildt; facials Natalia Lichtenberger; breathwork guides Fallon Gleason and Joseph Irby? Who would do collab posts?  
_Fills:_ `team.collective`  
_Status:_ Answered  

_Answer (2026-11-13):_ Confirmed by role: two counselors (LPC, ALC) plus Scott, a massage therapist, an esthetician, two breathwork guides, a yoga teacher; a partner physician (MD), not an employee. Collab posts: the massage therapist, the yoga teacher and the esthetician. Names and handles are in STATE/people.json (private).

**45.** Katie: are you comfortable being the on-camera expert for "Ask the DPT"? What topics would you want to cover, and what would you never comment on?  
_Fills:_ `positioning.ask_the_dpt`  
_Status:_ Open (owner: Katie)  
_Until answered:_ Ask the DPT runs as text-on-screen answers  

_Answer (2026-11-13):_ Is Katie the on-camera expert? Topics, and topics she'd never comment on?

**46.** Which red light panels does NUMA use (make and model), and do they have an FDA clearance? For what exactly?  
_Fills:_ `claims.modalities.red_light.device_facts`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ "FDA-cleared" stays banned  

_Answer (2026-11-13):_ Block Blu Light Red Light Therapy Panel Elite XL. Open: is it FDA-cleared, and for what? (The waiver says "FDA-cleared".)

**47.** Where does the website's "57 minutes of sauna and 11 of cold a week" line come from? (It's a dosing claim that needs a lawyer's OK before it's used in posts.)  
_Fills:_ `claims.dosing_line`  
_Status:_ Partly open (owner: Scott)  
_Until answered:_ blocked: "source pending (Scott)"  

_Answer (2026-11-13):_ Checked and approved by the owners. Open: add its source to the Doc 04 science table.

**48.** Does the member consent form cover appearing in social posts and AI processing of photos? If not, can that wording be added?  
_Fills:_ `consent.social_posts_covered`, `consent.ai_processing_covered`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ no member face goes to AI motion  

_Answer (2026-11-13):_ Covered: each person is asked before their photo is posted or their words used. Open (plugin): does that yes cover sending a face to AI motion?

**49.** Would NUMA partner with Mission Fitness, barre3 Mobile, Pure Barre Mobile, run clubs or University of South Alabama teams for collab posts? Any existing relationships?  
_Fills:_ `positioning.collab_partners`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ no AMP collab post until its terms are reviewed  

_Answer (2026-11-13):_ AMP: active partner. University of South Alabama: ended (follow up with soccer and the other teams). Pure Barre: talked and dropped off passes. Mission Fitness: a Kolibri partner, not a Numa partner. barre3, run clubs: none. CREW: didn't take it up. Open: review the AMP agreement for posting terms.

**50.** Would NUMA offer a rate for healthcare workers or students, or a bring-a-friend first plunge?  
_Fills:_ `offerings.rates_considered`, `offerings.offers`  
_Status:_ Partly open (owner: Scott and Katie)  
_Until answered:_ never promote an unconfirmed rate  

_Answer (2026-11-13):_ 15% off memberships for healthcare workers, veterans, active military, police, firefighters, EMTs, teachers and ministry leaders. Bring a friend: free through Nov 30. Black Friday offers. Open: student and over-60 offers.

**51.** Is there an advertising lawyer NUMA already works with to review the claims policy once?  
_Fills:_ `posting.legal_counsel`  
_Status:_ Answered  

_Answer (2026-11-13):_ Skip. The lawyer review is dropped; a person approves every post instead (`posting.legal_review_done` is kept as a waived gate).
---

**Thank you.** From here on Numa Studio plans, edits and stages every post on its own; a person approves each post before it goes out, and your only filming job is what a shoot card asks for, when it asks.
