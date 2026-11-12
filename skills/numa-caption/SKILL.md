---
name: numa-caption
description: Writes the copy for a NUMA Wellness Collective reel or post in NUMA's voice - three Instagram caption options with one recommended, 3-5 hashtags, a one-line Story text and a short email paragraph - and scans all of it, hashtags included, against the claims policy. Use for every /make-reel copy step (the copywriter agent) and whenever NUMA caption, hook, hashtag, Story or newsletter copy is needed.
---

# NUMA Caption Writer

Copy sells the experience, never the outcome, in NUMA's voice. Katie never picks or approves anything: you recommend one option and the Director posts it.

`S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`. Read first: the reel's `work/plan.json` (`hook`, `lines`, `endcard`, `meta`, `ai`), the shoot card (topic, CTA, share line, paid-creator note) and brand/brand.json:

| Need | brand.json key |
|---|---|
| Voice (honest, grounded, warm, communal; invites people to participate, never to perform; no hype) | `voice.description`, `voice.reference_lines`, `voice.site_lines` |
| Name spelling ("NUMA"; "Numa Nights" keeps its own) | `business.name` |
| Offers and prices (Discover NUMA, $49 one month) and the link | `offerings.offers`, `business.cta_link` |
| Opening rule | `captions.opening_rule` |
| Hashtags: count, base tags, community tag, never-use list | `captions.hashtags` |
| Creator disclosure | `captions.disclosure` |
| Community word, emoji rule | `voice.community_word`, `voice.emoji` |
| Share line example | `voice.share_line_example` |
| Claims | `claims.banned`, `claims.modalities`, `claims.rules`, `claims.safety_line` |

## 1. Three caption options, one recommended

Write 3 options, each from a different angle, and mark one **Recommended** with a one-line reason (the angle that best fits the reel's goal in `meta.goal` and its hook):

| Angle | Leads with | Example first line |
|---|---|---|
| Community | the people and the shared ritual | "Cold plunge in Mobile, AL, done together." |
| Experience | what the session feels like (never what it fixes) | "Sauna in Midtown Mobile: deep, quiet heat to unwind." |
| Story | the reel's moment or arc | "Breathwork in Mobile, AL: a first class, start to finish." |

Every option:
1. **Line 1 opens with a plain searchable phrase** ("cold plunge in Mobile, AL", "sauna near Midtown Mobile", "breathwork in Mobile"), then the hook; under about 12 words so it shows before "more". Instagram search reads it.
2. **2-4 short body lines** with concrete details (the 14-person Finnish sauna, 4 cold plunges, the guide's name and title from `team.collective`).
3. **One soft call to action**, rotated: "Try Discover NUMA: one month, $49 (link in bio)", "Come breathe with us", "See you at Numa Nights". Ask the DPT reels carry no booking pitch (education only).
4. **The share line** when the reel has one: echo it ("Send this to the friend who needs a reset."). Sends reach new people.
5. **Safety line** (`claims.safety_line.text`) on cold and heat reels.
6. **Hashtags on the last line: 3-5** = the `captions.hashtags.base` tags (#MobileAL #MidtownMobile #GulfCoastWellness) + one topic tag (#coldplunge, #sauna, #breathwork) + the NUMA community tag from `captions.hashtags.community_tag` when it has a value (while it is null, leave it out; never invent one). Never a tag from `captions.hashtags.never` or one that states a benefit.
7. Emojis per `voice.emoji` (default 0-2, earthy: 🌿 🌊 🤍); no hype, no exclamation runs, no "game changer".

## 2. Story line and email paragraph (R236)

- **Story text:** one line, at most 8 words, for the Story the day after the reel ("Three minutes of cold. Walk out awake.").
- **Email paragraph:** 40-70 words for NUMA's newsletter, plain sentences, one link (`business.cta_link`), no hashtags, no emojis.

## 3. Rules that change the first line

- **Paid or comped creators** (the shoot card or plan row says so): the first line starts with "#ad" or "I get free sessions" (`captions.disclosure`), and the reel carries the same disclosure on screen. Reviews are never bought or conditioned on being positive.
- **AI label:** when plan `ai.label_required` is true, add the line `AI label: ON (Instagram "AI info")` to the copy file for posting. The label is a posting setting, not caption text.
- **Testimonials:** experience only ("my favorite hour of the week"); never a member's health outcome.

## 4. Claims scan (every option, the Story line, the email, the hashtags)

```
python3 "$S/claims_scan.py" - --hashtags "#MobileAL #MidtownMobile #GulfCoastWellness #coldplunge" --json <<'EOF'
<all three options, the Story line and the email paragraph>
EOF
```
Exit 1 (`ERROR:` lines): rewrite those words into experience language (`claims.modalities` "say" lines) and scan again; a disclaimer or "may help" never fixes a claim. A `WARN:` line: reword unless the phrase is clearly innocent, and say which you kept and why.

## 5. The copy file (`out/SLUG_copy.txt`)

```
RECOMMENDED (option 2): the experience angle matches the reel's hook.

OPTION 1 - Community
<caption>

OPTION 2 - Experience (recommended)
<caption>

OPTION 3 - Story
<caption>

HASHTAGS: #MobileAL #MidtownMobile #GulfCoastWellness #coldplunge
STORY: <one line>
EMAIL: <paragraph>
AI label: OFF
MUSIC: <plan music.source; "add a Sound Collection track at posting" only when music.source is sound_collection>
```

## Worked example (cold plunge, First Plunge series)

> Cold plunge in Mobile, AL: your first three minutes.
> Everyone hates the cold. Then the timer ends and you're grinning.
> Four plunges, one cedar sauna, and a room full of people doing it with you.
> Talk to your doctor first if you have a heart, blood pressure or breathing condition.
> Send this to the friend who says they could never.
> #MobileAL #MidtownMobile #GulfCoastWellness #coldplunge
