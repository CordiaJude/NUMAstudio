#!/usr/bin/env python3
"""Analyze raw material for a reel.
Usage: python3 analyze.py <raw_dir> <work_dir> [--music FILE] [--voice FILE] [--master FILE]
Produces in work_dir: master.wav (voice+music mixed, or the single master track),
analysis.json (duration, bpm, beats, words with timestamps, media inventory),
contact_photos.jpg / contact_clips.jpg (numbered thumbnails to look at).
"""
import sys, os, json, glob, subprocess, shutil, argparse
import numpy as np
from PIL import Image, ImageOps, ImageDraw
ap = argparse.ArgumentParser(); ap.add_argument('raw'); ap.add_argument('work')
ap.add_argument('--music'); ap.add_argument('--voice'); ap.add_argument('--master')
a = ap.parse_args(); os.makedirs(a.work, exist_ok=True)
FF = shutil.which('ffmpeg')
if not FF:
    import imageio_ffmpeg; FF = imageio_ffmpeg.get_ffmpeg_exe()
def run(*c): subprocess.run([FF, '-v', 'error', '-y', *c], check=True)
def dur(f):
    out = subprocess.run([FF, '-i', f], capture_output=True, text=True).stderr
    for l in out.splitlines():
        if 'Duration:' in l:
            h, m, s = l.split('Duration:')[1].split(',')[0].strip().split(':'); return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0

raw = os.path.abspath(a.raw); work = os.path.abspath(a.work)
IMG = ('.jpg', '.jpeg', '.png', '.heic', '.webp'); VID = ('.mp4', '.mov', '.m4v'); AUD = ('.mp3', '.wav', '.m4a', '.aac')
files = sorted(f for f in glob.glob(os.path.join(raw, '**', '*'), recursive=True) if os.path.isfile(f))
photos = [f for f in files if f.lower().endswith(IMG)]; clips = [f for f in files if f.lower().endswith(VID)]
auds = [f for f in files if f.lower().endswith(AUD)]
# HEIC -> JPG
conv = []
for p in photos:
    if p.lower().endswith('.heic'):
        from pillow_heif import register_heif_opener; register_heif_opener()
        q = os.path.splitext(p)[0] + '.jpg'; Image.open(p).convert('RGB').save(q, quality=95); conv.append(q)
    else: conv.append(p)
photos = conv
# audio roles
def guess(keys): return next((f for f in auds if any(k in os.path.basename(f).lower() for k in keys)), None)
voice = a.voice or guess(['vo', 'voice', 'narrat', 'memo', 'speech'])
music = a.music or guess(['music', 'song', 'track', 'beat', 'audio'])
master = a.master
if not master and voice and music and voice != music:
    vd = dur(voice); total = min(vd + 7.5, 60)
    run('-i', voice, '-i', music, '-filter_complex',
        f'[1]volume=-14dB,atrim=0:{total},asetpts=N/SR/TB[m];[0]apad=pad_dur={total}[v];'
        f'[m][v]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];[md][v]amix=inputs=2:weights=1 1.6:normalize=0,atrim=0:{total}',
        '-ar', '48000', '-ac', '2', os.path.join(work, 'master.wav'))
    beats_src = music
else:
    master = master or voice or music or (auds[0] if auds else None)
    if not master: sys.exit('NO AUDIO FOUND: need a voiceover and/or music file')
    run('-i', master, '-ar', '48000', '-ac', '2', os.path.join(work, 'master.wav')); beats_src = master
M = os.path.join(work, 'master.wav'); D = dur(M)
# words
words = []
try:
    run('-i', voice or M, '-ac', '1', '-ar', '16000', '-f', 'f32le', os.path.join(work, 'a.raw'))
    from faster_whisper import WhisperModel
    wm = WhisperModel('small.en', compute_type='int8')
    segs, _ = wm.transcribe(np.fromfile(os.path.join(work, 'a.raw'), np.float32), word_timestamps=True)
    for s in segs:
        for w in s.words:
            words.append({'w': w.word.strip(), 'appear': round(max(w.start, w.end - 0.4), 2), 'end': round(w.end, 2)})
except Exception as e: print('transcription failed:', e)
# beats
import librosa
y, sr = librosa.load(beats_src, sr=22050, duration=D)
tempo, bf = librosa.beat.beat_track(y=y, sr=sr); beats = [round(float(b), 2) for b in librosa.frames_to_time(bf, sr=sr)]
# contact sheets
def sheet(items, name, label):
    if not items: return
    th = []
    for i, (im, lab) in enumerate(items):
        t = ImageOps.contain(im.convert('RGB'), (240, 300)); c = Image.new('RGB', (250, 330), (20, 20, 20)); c.paste(t, ((250 - t.width) // 2, 5))
        ImageDraw.Draw(c).text((6, 310), f'{label}{i}: {lab}'[:38], fill=(255, 230, 160)); th.append(c)
    cols = 6; rows = (len(th) + cols - 1) // cols; S = Image.new('RGB', (250 * cols, 330 * rows))
    for i, c in enumerate(th): S.paste(c, ((i % cols) * 250, (i // cols) * 330))
    S.save(os.path.join(work, name), quality=85)
sheet([(Image.open(p), os.path.basename(p)) for p in photos], 'contact_photos.jpg', 'P')
ci = []; cinfo = []
for k, c in enumerate(clips):
    cd = dur(c); cinfo.append({'id': f'C{k}', 'path': c, 'duration': round(cd, 2)})
    for t in np.arange(0.5, cd, max(1.0, cd / 8)):
        f = os.path.join(work, 'tmp.jpg'); run('-ss', f'{t:.2f}', '-i', c, '-frames:v', '1', '-vf', 'scale=480:-2', f)
        ci.append((Image.open(f).copy(), f'{os.path.basename(c)} @{t:.1f}s'))
sheet(ci, 'contact_clips.jpg', 'C')
out = {'duration': round(D, 2), 'bpm': float(np.atleast_1d(tempo)[0]), 'beats': beats, 'words': words,
       'transcript': ' '.join(w['w'] for w in words), 'audio': {'voice': voice, 'music': music, 'master': M},
       'photos': [{'id': f'P{i}', 'path': p, 'size': Image.open(p).size} for i, p in enumerate(photos)], 'clips': cinfo}
json.dump(out, open(os.path.join(work, 'analysis.json'), 'w'), indent=1)
print(json.dumps({k: out[k] for k in ('duration', 'bpm', 'transcript')}, indent=1)); print('photos', len(photos), 'clips', len(clips))
