#!/usr/bin/env python3
"""NUMA Studio test suite (milestone M3). Builds five material folders from bundled brand photos and
generated audio, then runs analyze -> baseline_plan -> validate_plan -> engine (short render) -> finish
and checks the output file. No network, no credits.
Usage: python3 tests/run_tests.py [--keep] [--voice REAL_VOICE_FILE] [--only NAME]
"""
import os, sys, json, shutil, subprocess, tempfile, argparse, re, time
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, 'skills', 'numa-reel-editor', 'scripts')
BP = os.path.join(ROOT, 'skills', 'numa-reel-editor', 'assets', 'brand-photos')
ap = argparse.ArgumentParser(); ap.add_argument('--keep', action='store_true'); ap.add_argument('--voice'); ap.add_argument('--only')
ap.add_argument('--seconds', type=float, default=10.0)
a = ap.parse_args()
FF = shutil.which('ffmpeg')
if not FF:
    import imageio_ffmpeg; FF = imageio_ffmpeg.get_ffmpeg_exe()
PY = sys.executable

def ff(*args): subprocess.run([FF, '-v', 'error', '-y', *args], check=True)
def music(path, secs=40):  # 100 BPM pad with a kick on every beat
    ff('-f', 'lavfi', '-i', f"aevalsrc='0.12*sin(2*PI*220*t)+0.1*sin(2*PI*277*t)+0.08*sin(2*PI*330*t)+0.7*sin(2*PI*55*t)*exp(-18*mod(t,0.6))':s=44100:d={secs}", '-ac', '2', path)
def fake_voice(path, secs=14):  # gated, pitch-wobbling tone: tests the mix path, not transcription
    ff('-f', 'lavfi', '-i', f"aevalsrc='0.4*sin(2*PI*(170+35*sin(2*PI*3*t))*t)*lt(mod(t,0.45),0.3)*lt(t,{secs-1})':s=24000:d={secs}", path)
def photos(dst, n=5, heic=False, landscape=True):
    os.makedirs(dst, exist_ok=True); fs = sorted(os.listdir(BP))[:n]
    for k, f in enumerate(fs):
        im = Image.open(os.path.join(BP, f)).convert('RGB')
        if landscape and k == 1: im = im.crop((0, int(im.height * 0.3), im.width, int(im.height * 0.3 + im.width * 0.66)))
        if heic:
            import pillow_heif; pillow_heif.register_heif_opener(); im.save(os.path.join(dst, f'IMG_{k}.heic'))
        else: im.save(os.path.join(dst, f'photo_{k}.jpg'), quality=92)
def clips(dst):
    os.makedirs(dst, exist_ok=True); fs = sorted(os.listdir(BP))
    ff('-loop', '1', '-i', os.path.join(BP, fs[0]), '-vf', "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='1+0.002*on':d=150:s=1080x1920:fps=30", '-t', '5', '-pix_fmt', 'yuv420p', os.path.join(dst, 'clip_vertical.mp4'))
    ff('-loop', '1', '-i', os.path.join(BP, fs[1]), '-vf', "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z='1+0.002*on':d=150:s=1920x1080:fps=30", '-t', '5', '-pix_fmt', 'yuv420p', os.path.join(dst, 'clip_landscape.mov'))

def build(name, root):
    raw = os.path.join(root, name, 'raw'); os.makedirs(raw, exist_ok=True)
    if name == 'photos_music': photos(raw); music(os.path.join(raw, 'music.mp3'))
    elif name == 'clips_only': clips(raw); music(os.path.join(raw, 'music.mp3'))
    elif name == 'voice_and_music':
        photos(raw); music(os.path.join(raw, 'music.mp3'))
        if a.voice: ff('-i', a.voice, '-t', '16', os.path.join(raw, 'voiceover.m4a'))
        else: fake_voice(os.path.join(raw, 'voiceover.wav'))
    elif name == 'combined_track':
        photos(raw)
        if a.voice: ff('-i', a.voice, '-t', '30', os.path.join(raw, 'audio.mp3'))
        else: music(os.path.join(raw, 'audio.mp3'))
    elif name == 'heic_photos': photos(raw, heic=True); music(os.path.join(raw, 'music.mp3'))
    return raw, os.path.join(root, name, 'work')

def probe(path):
    out = subprocess.run([FF, '-i', path], capture_output=True, text=True).stderr
    v = re.search(r'Video: h264.*?(\d{3,4})x(\d{3,4})', out); au = re.search(r'Audio: aac.*?(\d+) Hz', out)
    d = re.search(r'Duration: (\d+):(\d+):([\d.]+)', out)
    return (int(v.group(1)), int(v.group(2))) if v else None, int(au.group(1)) if au else None, (int(d.group(2)) * 60 + float(d.group(3))) if d else 0

CASES = ['photos_music', 'clips_only', 'voice_and_music', 'combined_track', 'heic_photos']
root = tempfile.mkdtemp(prefix='numa_tests_'); results = []
for name in CASES:
    if a.only and name != a.only: continue
    t = time.time(); ok, why = True, ''
    try:
        raw, work = build(name, root)
        extra = ['--master', os.path.join(raw, 'audio.mp3')] if name == 'combined_track' else []
        r = subprocess.run([PY, os.path.join(S, 'analyze.py'), raw, work, *extra], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('analyze: ' + r.stderr[-400:])
        A = json.load(open(os.path.join(work, 'analysis.json')))
        if not A['beats']: raise RuntimeError('no beats detected')
        r = subprocess.run([PY, os.path.join(S, 'baseline_plan.py'), work, '--duration', str(a.seconds)], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('baseline: ' + r.stderr[-400:])
        r = subprocess.run([PY, os.path.join(S, 'validate_plan.py'), os.path.join(work, 'plan.json'), os.path.join(work, 'analysis.json')], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('validate: ' + r.stdout[-600:])
        r = subprocess.run([PY, os.path.join(S, 'engine.py'), os.path.join(work, 'plan.json')], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('engine: ' + r.stderr[-400:])
        out = os.path.join(work, f'{name}.mp4')
        r = subprocess.run([PY, os.path.join(S, 'finish.py'), work, out], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('finish: ' + r.stderr[-400:])
        size, hz, dur = probe(out)
        if size != (1080, 1920): raise RuntimeError(f'video size {size}')
        if hz != 48000: raise RuntimeError(f'audio {hz} Hz')
        if abs(dur - a.seconds) > 0.6: raise RuntimeError(f'duration {dur:.2f}s')
        why = f'{len(A["photos"])} photos, {len(A["clips"])} clips, {len(A["words"])} words, {A["bpm"]:.0f} BPM, {dur:.1f}s'
    except Exception as e:
        ok, why = False, str(e)
    results.append((name, ok, why, time.time() - t)); print(f'{"PASS" if ok else "FAIL"}  {name:16s} {time.time()-t:5.0f}s  {why}', flush=True)
print(f'\n{sum(r[1] for r in results)}/{len(results)} passed' + (f'  (files kept in {root})' if a.keep else ''))
if not a.keep: shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if all(r[1] for r in results) else 1)
