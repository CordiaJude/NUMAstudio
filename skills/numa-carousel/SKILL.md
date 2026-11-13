---
name: numa-carousel
description: Build a NUMA component carousel (explainer, protocol, myth vs fact, offer) end to end in Claude Design - pick components, make one private canvas per carousel with the Artifact tool, upload photos, read the canvas back, render 1080x1350 slides locally with design_render.py, LOOK, run the claims and fit checks, hand the slides to /post-reel. Includes the spec fallback that never blocks posting.
---
# NUMA component carousels in Claude Design (R328-R332, DECISIONS D21)

**When:** a plan row whose `kind` is carousel and whose content is new copy (an Ask the DPT explainer, a protocol, a myth vs fact, an offer). A carousel cut from a reel uses formats.py; a photo carousel uses photo_post.py (commands/post-reel.md section 12). **Who:** the designer agent. **Never** ask Katie anything and never add an approval step: the canvas is where Katie and Jude look and edit, and the post is rendered from whatever the canvas holds at posting time.

`S` = `${CLAUDE_PLUGIN_ROOT}/skills/numa-reel-editor/scripts`. `JOB` = the day's job folder. `ROOT` = a new folder in your session's scratchpad (else inside the working directory; the Artifact tool only sends files from there): `ROOT=<scratchpad>/canvas-<slug>`. Log every decision and fallback in `JOB/work/decisions.md` (`HH:MM | carousel | decision | why | fallback`).

| Step | Do | Output |
|---|---|---|
| 1 | Pick components, write `JOB/work/carousel.json`, validate | carousel.json |
| 2 | Create the canvas (once per carousel) | `canvas.url` |
| 3 | Upload photos, build the files, publish | the canvas with every slide |
| 4 | Read the canvas back into `JOB/work/canvas/` | canvas folder |
| 5 | `design_render.py canvas` | `JOB/out/<slug>_carousel_01.jpg` ... |
| 6 | LOOK at the slides | fixes |
| 7 | Claims and fit checks clean | `report.json` `design_render.ok` |
| 8 | Hand to posting | /post-reel |

## 1. Pick the components

5-8 slides (config `formats.outputs` carousel `count`; 2-10 is Instagram's hard limit). Slide 1 is `cover`, the last is `cta`. One idea per slide; at least one `photo` slide when a fitting photo exists (the day's photos, the media library, else brand.json `assets.brand_photos_dir`).

| Component | Use for | Fields (required, *optional*) |
|---|---|---|
| `cover` | the hook | kicker, title, *subtitle* |
| `point` | numbered point | kicker, number, title, body |
| `stat` | one sourced, claims-safe number ("14" people in the sauna) | kicker, stat (<= 8 chars), label, *body*, *source* |
| `myth_fact` | a common mix-up | kicker, myth, fact |
| `quote` | a member or Katie quote (consented, verbatim) | kicker, quote, name, *role* |
| `steps` | a protocol | kicker, title, step1-3, *step4* |
| `offer` | the price card | kicker, title, offer (an offer or session name in brand.json `offerings`), cta, *details* |
| `photo` | a photo with a caption | kicker, caption; slide `photo` path, *`photo_position`* ("50% 38%") |
| `cta` | end slide with the wordmark | title, button, *body* |

Rules: copy follows brand.json `voice` and `claims` (sell the experience, never the outcome; `claims.modalities.<m>.say`); prices are never typed: `offer` takes them from brand.json, and an offer whose price is `needs_katie` is not used (drop the slide, log it); `*word*` = italic cedar-ember emphasis, at most one per slide; a recognizable person on a photo slide only with a `STATE/consent_list.json` entry whose scope covers social posts; the caption opens with a plain searchable phrase (brand.json `captions.opening_rule`) and adds brand.json `claims.safety_line.text` for sauna or cold plunge. Worked example (the Ask the DPT explainer, 6 slides):

```json
{"schema_version": 1, "slug": "2026-12-08-sauna-vs-red-light",
 "title": "NUMA Carousel · 2026-12-08 · Sauna vs red light", "date": "2026-12-08",
 "caption": "Sauna vs red light in Mobile, AL: what's actually different? ... Talk to your doctor first if you have a heart, blood pressure or breathing condition.\n\n#MobileAL #MidtownMobile #GulfCoastWellness",
 "slides": [
  {"component": "cover", "fields": {"kicker": "Ask the DPT", "title": "Sauna vs red light: what's *different*?", "subtitle": "Two warm rooms, two very different sessions. Katie breaks it down."}},
  {"component": "point", "fields": {"kicker": "The sauna", "number": "1", "title": "Heat that surrounds you", "body": "Our 14-person Finnish sauna warms the air around you. Deep, quiet heat to unwind."}},
  {"component": "photo", "photo": "skills/numa-reel-editor/assets/brand-photos/red-light.jpg", "photo_position": "50% 38%", "fields": {"kicker": "Red light", "caption": "Red light is *light*, not heat. You sit in front of a panel's warm glow."}},
  {"component": "myth_fact", "fields": {"kicker": "Common mix-up", "myth": "Red light is just a sauna with colored bulbs.", "fact": "A sauna heats the air. A red light panel shines light on you. Two different tools."}},
  {"component": "steps", "fields": {"kicker": "Try both", "title": "One easy way to start", "step1": "Begin in the sauna and let yourself settle.", "step2": "Step out, cool down and drink some water.", "step3": "Finish with a calm, warm red light session."}},
  {"component": "cta", "fields": {"title": "Feel the difference for yourself.", "body": "Your reset starts here.", "button": "discover.numawellness.org"}}]}
```
```
python3 "$S/design_render.py" validate "$JOB/work/carousel.json"
```
Every `ERROR:` (banned claim, missing field, unknown offer, `needs_katie` price) is fixed in carousel.json before step 2. `WARN:` lines are reworded when the wording can be safer; otherwise kept and logged.

## 2. Create the canvas (one per carousel)

`carousel.json` already has `canvas.url` (a re-run): the canvas is Katie's now. Never rebuild or overwrite it: go to step 4. Otherwise one call, title = carousel.json `title` ("NUMA Carousel · <date> · <topic>"):
```
Artifact {"action": "publish", "type_url": "https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd",
          "title": "NUMA Carousel · 2026-12-08 · Sauna vs red light", "auto_open": "after_first_write"}
```
Save the reply's `url` in carousel.json `canvas.url` at once. Every later call uses that `url`; never `type_url` again.

**Design system.** config/studio.json `carousel.design_system_url` is null: no design system; the bundled NUMA components are the look (never one of the account's other design systems: they are not NUMA's). When it holds a link: read its `project/README.md` and `project/tokens.json` (two `read` calls with `path`, in one message), pass `--design-system <that link>` to `build` (it writes the `designSystems` record and the server-side copy of its `tokens.json` to `project/ds/numa/`), and when its README names stylesheets or scripts for a Design canvas, add each to the `files` map as `"project/ds/numa/<file>": {"artifact": "<link>", "path": "project/<file>"}` and its `<link rel="stylesheet" href="ds/numa/<file>">` after the `support.js` line of every artboard in `ROOT/project/` before publishing. Its fonts must be uploaded files or the bundled Fraunces/Inter: a Google font outside those fails the render.

## 3. Upload, build, publish

```
python3 "$S/design_render.py" build "$JOB/work/carousel.json" --root "$ROOT" --uploads-only --json
```
Upload every listed file in ONE call (up to 25):
```
Artifact {"action": "publish", "url": "<canvas url>", "asset": true,
          "file_paths": ["<ROOT>/uploads/red-light.jpg", "<ROOT>/uploads/wordmark.png"]}
```
Write each returned `/_blob/<id>` into carousel.json `canvas.blobs` under its `key` from the listing (the slide's `photo` string, or `wordmark`). Then:
```
python3 "$S/design_render.py" build "$JOB/work/carousel.json" --root "$ROOT" --json
```
Publish the index with the first artboard, then all the others in one more call (`files` = the JSON's `files` map; with a design system its extra entries ride in the first call):
```
Artifact {"action": "publish", "url": "<canvas url>", "root": "<ROOT>", "file_path": "<ROOT>/project/canvas.json",
          "files": {"project/Main.dc.html": "project/Main.dc.html"}}
Artifact {"action": "publish", "url": "<canvas url>", "root": "<ROOT>", "file_path": "<ROOT>/project/Slide02.dc.html",
          "files": {"project/Slide03.dc.html": "project/Slide03.dc.html", "...": "...", "project/Slide06.dc.html": "project/Slide06.dc.html"}}
```
The canvas shows one 1080x1350 artboard per slide in a row and a sticky note with the posting date and caption. It stays private; Katie and Jude open it from their claude.ai artifacts.

## 4. Read the canvas back

Always read, even right after publishing: Katie may have edited it.
```
Artifact {"action": "read", "url": "<canvas url>", "path": "project/canvas.json"}
Artifact {"action": "read", "url": "<canvas url>", "paths": ["project/Main.dc.html", "project/Slide02.dc.html", "...every board in canvas.json boards...", "artifact-type/dc-runtime.js"]}
```
(With a design system, add its `project/ds/numa/...` files to `paths`.) The reply names the folder the files were saved in (`<saved>`). Then list the images the artboards use and read each by id, one call per id (`paths` does not fetch assets):
```
python3 "$S/design_render.py" canvas "<saved>" --list-blobs
Artifact {"action": "read", "url": "<canvas url>", "path": "3e7d88922a5aa1df5bdb4359ac914310"}
rm -rf "$JOB/work/canvas" && cp -R "<saved>" "$JOB/work/canvas"
```

## 5. Render

```
python3 "$S/design_render.py" canvas "$JOB/work/canvas" --out "$JOB/out" --slug SLUG --json
```
Writes `JOB/out/SLUG_carousel_01.jpg` ... in reading order, `JOB/out/carousel_sheet.jpg` and `report.json` `design_render`. Takes a few seconds.

## 6. LOOK

Open `JOB/out/carousel_sheet.jpg`, then every slide at full size. Check: the slides read in order as one story; the hook works on slide 1 alone; each slide has one idea and reads on a phone; no text clipped, crowded or orphaned (a single word on its last line: shorten); the photo crop keeps the subject (move `photo_position`); NUMA spelled right; the wordmark on the last slide; no recognizable person without consent. Anything off: fix it (step 7) and render again.

## 7. Claims and fit checks

`design_render.py` exits 1 on any ERROR: a banned claim in the rendered text (Katie's edits included), text overflowing its box, a font that did not load, a blank slide, wrong size, a `[PRICE]` placeholder. Fix on the canvas, never only locally:
1. Edit `project/<board>` in `ROOT` (copy it from `JOB/work/canvas/project/` first when the canvas changed since you built it): shorten or reword the text, keep the markup.
2. Publish only the changed boards: `Artifact {"action": "publish", "url": "<canvas url>", "root": "<ROOT>", "file_path": "<ROOT>/project/Slide04.dc.html"}`. Refused because someone saved meanwhile: read the boards the refusal names, redo the edit, publish again.
3. Steps 4-5 again. At most 3 rounds, then the fallback row "render still fails".

## 8. Hand to posting

`report.json` `design_render.ok` true: hand `JOB` to /post-reel with the caption from carousel.json (alt text per slide: the slide's `text` in report.json). **Before posting (D21):** right before /post-reel publishes, run steps 4, 5 and 7 again so Katie's latest canvas edits go out; when that read or render fails, post the slides already in `JOB/out` and log it.

## Fallbacks (in order; log each `fallback carousel.<n>`)

| # | Failure | Move |
|---|---|---|
| 1 | Artifact tool not visible, canvas create/publish/upload refused | `python3 "$S/design_render.py" spec "$JOB/work/carousel.json" --out "$JOB/out" --json`: the same components and pixels without a canvas; LOOK as in step 6 |
| 2 | Canvas read fails at build time | the spec render (row 1) from carousel.json |
| 3 | Canvas read or render fails at posting time | post the build-day slides in `JOB/out` |
| 4 | Render still fails after 3 rounds | fix the copy in carousel.json, spec render (row 1) |
| 5 | `Chromium for Playwright is not installed` / `Python Playwright is not installed` | one line to Jude with the fix: `pip install -r requirements.txt, then python -m playwright install chromium`; today posts a photo carousel instead (photo_post.py, commands/post-reel.md section 12) |
| 6 | An offer price is `needs_katie` | replace the offer slide with a `cta` slide pointing at brand.json `business.cta_link` |
