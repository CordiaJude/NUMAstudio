---
description: Check that this computer and Claude are ready to run NUMA Studio (packages, Google Drive, Higgsfield)
---
Run a readiness check for the NUMA Studio plugin and report each item as ✅ or ❌ with the one-line fix:

1. **Python packages:** install if missing: `pip install --break-system-packages faster-whisper librosa opencv-python-headless pillow numpy imageio-ffmpeg pillow-heif` (drop the flag if pip rejects it). Confirm `python3 -c "import cv2, librosa, faster_whisper, imageio_ffmpeg"` works.
2. **Engine smoke test:** write a 3-second plan.json that uses `assets/brand-photos/sauna-logo.jpg` and the end card from the numa-reel-editor skill's `assets/`, run `scripts/engine.py plan.json preview 1 2.5`, and look at preview.jpg.
3. **Google Drive:** is a Google Drive connector connected? If not, search the connector registry and suggest it. List the top-level folders and ask which one Katie will drop reel material into. Remember the answer for future runs if memory is available.
4. **Higgsfield:** is the Higgsfield connector connected? Call `balance`. One 5-second motion clip (seedance_2_5) costs about 35 credits, and a typical reel uses 2-4 clips (70-140 credits). Report how many reels the balance covers.
5. Finish with: "Ready. Drop photos/clips + music + voiceover in a dated Drive folder and run /make-reel."
