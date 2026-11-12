---
name: numa-brand-check
description: Review a NUMA video, image, graphic or post against NUMA's brand and an agency quality bar before it goes out. Use when asked "is this on brand", "review this reel", "check this before I post", or for feedback on NUMA marketing content.
---

# NUMA Brand Check

1. For a video, pull 8-12 frames evenly across it plus the frames at each cut (`ffmpeg -vf "select='gt(scene,0.25)'"`), check the audio with `volumedetect` and the sample rate (must be 48 kHz or 44.1 kHz, never 96 kHz), and read any captions. For an image, look at it at full size.
2. Score each 1-5 with one line of evidence:
   - **Look:** warm, cinematic, natural tones (cedar/ember warm, water teal, cream); nothing oversaturated or cold except intentional "before" moments.
   - **Type:** elegant serif captions, white with gold-italic emphasis; readable on a phone; nothing in the top 12% or bottom 10% (app UI covers it).
   - **Logo:** NUMA wordmark clean, not stretched, not recolored except white/dark; ends on the logo card for reels.
   - **Voice:** honest, grounded, warm, communal, no hype (see numa-caption).
   - **Craft:** hook in the first second, cuts on the beat, no black bars or stretched images, audio clear and not too close, no typos.
   - **Fit:** vertical 9:16 1080x1920 for Reels/TikTok, 15-60 s.
3. Verdict: **Ship**, **Ship after fixes** (list the top 3 fixes, most important first), or **Redo**. If the numa-reel-editor skill is available and the fixes are edit-level, offer to apply them.
