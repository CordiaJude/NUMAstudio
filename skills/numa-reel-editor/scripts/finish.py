#!/usr/bin/env python3
"""Master audio, mux with rendered video, QA.
Usage: python3 finish.py <work_dir> <output.mp4> [--clean-voice]
"""
import sys, os, subprocess, shutil, re
work, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]); clean = '--clean-voice' in sys.argv
FF = shutil.which('ffmpeg')
if not FF:
    import imageio_ffmpeg; FF = imageio_ffmpeg.get_ffmpeg_exe()
V = os.path.join(work, 'video_noaudio.mp4'); M = os.path.join(work, 'master.wav'); A = os.path.join(work, 'aud.wav')
info = subprocess.run([FF, '-i', V], capture_output=True, text=True).stderr
h, m, s = re.search(r'Duration: (\d+):(\d+):([\d.]+)', info).groups(); D = int(h) * 3600 + int(m) * 60 + float(s)
room = '' if clean else 'aecho=0.85:0.5:28|55|90:0.14|0.09|0.05,'
af = (f"highpass=f=85,equalizer=f=180:t=q:w=1:g=-2.5,equalizer=f=3800:t=q:w=1.4:g=-4,equalizer=f=7000:t=q:w=1:g=-2.5,lowpass=f=11000,{room}"
      f"acompressor=threshold=-20dB:ratio=2:attack=15:release=200,aresample=48000,loudnorm=I=-15:TP=-1.5:LRA=9,aresample=48000,"
      f"afade=t=in:d=0.3,afade=t=out:st={max(D - 1.2, 0):.2f}:d=1.2")
subprocess.run([FF, '-v', 'error', '-y', '-i', M, '-af', af, '-t', f'{D:.2f}', '-ar', '48000', '-ac', '2', A], check=True)
subprocess.run([FF, '-v', 'error', '-y', '-i', V, '-i', A, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                '-ar', '48000', '-shortest', '-movflags', '+faststart', out], check=True)
vd = subprocess.run([FF, '-i', out, '-af', 'volumedetect', '-vn', '-f', 'null', '-'], capture_output=True, text=True).stderr
mean = float(re.search(r'mean_volume: ([-\d.]+)', vd).group(1))
for k, t in enumerate([D * x for x in (0.05, 0.25, 0.45, 0.65, 0.85, 0.97)]):
    subprocess.run([FF, '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', out, '-frames:v', '1', '-vf', 'scale=270:480', os.path.join(work, f'qa_{k}.jpg')])
from PIL import Image
S = Image.new('RGB', (270 * 6, 480))
for k in range(6): S.paste(Image.open(os.path.join(work, f'qa_{k}.jpg')), (270 * k, 0))
S.save(os.path.join(work, 'qa_strip.jpg'))
print(f'OK {out}  duration {D:.1f}s  audio mean {mean} dB  size {os.path.getsize(out) / 1e6:.1f} MB')
if mean < -28: print('WARNING: audio is very quiet')
