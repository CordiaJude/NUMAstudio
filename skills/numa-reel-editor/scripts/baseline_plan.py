#!/usr/bin/env python3
"""Build a valid, beat-synced starting plan from analysis.json. The Director then improves it
(story order, looks, signature moment, key words); it is never the final creative plan.
Usage: python3 baseline_plan.py <work_dir> [--duration S] [--subtitle "..."]
"""
import json, os, sys, argparse

HERE = os.path.dirname(os.path.abspath(__file__)); ASSETS = os.path.normpath(os.path.join(HERE, '..', 'assets'))
ap = argparse.ArgumentParser(); ap.add_argument('work'); ap.add_argument('--duration', type=float)
ap.add_argument('--subtitle', default='Less noise. More presence.')
a = ap.parse_args(); work = os.path.abspath(a.work)
A = json.load(open(os.path.join(work, 'analysis.json')))
D = min(a.duration or A['duration'], A['duration'], 60.0)
beats = [b for b in A.get('beats', []) if b < D] or [i * 0.5 for i in range(int(D * 2))]
step = beats[1] - beats[0] if len(beats) > 1 else 0.5

media = [{'kind': 'image', 'src': p['path']} for p in A.get('photos', [])]
for c in A.get('clips', []):
    media.append({'kind': 'video', 'src': c['path'], 'start': round(max(0.0, c['duration'] / 2 - 2), 2), 'dur': c['duration']})
if not media:
    bp = os.path.join(ASSETS, 'brand-photos')
    media = [{'kind': 'image', 'src': os.path.join(bp, f)} for f in sorted(os.listdir(bp))]

# end card: last 4-5 s, starting on a beat
end_t = max([b for b in beats if b <= D - 4.0] or [max(0.5, D - 4.5)])
# cuts every 4 beats (2 beats in the first 20% for energy)
cuts = [0.0]; i = 0
while True:
    n = 2 if cuts[-1] < D * 0.2 else 4
    i += n
    if i >= len(beats) or beats[i] >= end_t - 0.8: break
    cuts.append(beats[i])
cuts.append(end_t)
trs = ['punch', 'punch', 'whip', 'punch', 'leakfade', 'punch', 'flash']
shots = []
for k in range(len(cuts) - 1):
    m = dict(media[k % len(media)]); t0, t1 = round(cuts[k], 3), round(cuts[k + 1], 3)
    s = {'src': m['src'], 'look': 'warm', 't0': t0, 't1': t1,
         'z': [1.02, 1.14] if k % 2 == 0 else [1.15, 1.03], 'pan': [0, 0], 'tr': 'cut' if k == 0 else trs[(k - 1) % len(trs)]}
    if m['kind'] == 'video':
        s.update(kind='video', start=m['start'])
    shots.append(s)
shots.append({'src': os.path.join(ASSETS, 'heroimage.jpg'), 'look': 'none', 't0': round(end_t, 3), 't1': round(D, 3), 'z': [1.0, 1.08], 'tr': 'flash'})

# captions: break on pauses > 0.45 s, sentence ends, or 7 words
lines, cur = [], []
words = [w for w in A.get('words', []) if w['appear'] < end_t - 0.3]
for j, w in enumerate(words):
    cur.append(w)
    nxt = words[j + 1] if j + 1 < len(words) else None
    if not nxt or len(cur) >= 7 or nxt['appear'] - w['end'] > 0.45 or w['w'].endswith(('.', '!', '?')):
        lines.append(cur); cur = []
L = []
for j, ln in enumerate(lines):
    nxt_start = lines[j + 1][0]['appear'] if j + 1 < len(lines) else end_t
    ws = [[w['w'], round(w['appear'], 2)] for w in ln]
    ws[-1].append(1)  # last word in gold italic; the Director picks better key words
    L.append({'words': ws, 'end': round(max(ln[-1]['appear'] + 0.3, min(ln[-1]['end'] + 0.6, nxt_start - 0.15)), 2)})
plan = {'duration': round(D, 3), 'out_dir': work, 'shots': shots, 'lines': L,
        'leaks': [[round(cuts[min(2, len(cuts) - 1)], 2), 1.0, 0.35], [round(end_t, 2), 1.4, 0.4]],
        'endcard': {'t': round(end_t, 3), 'logo': os.path.join(ASSETS, 'Numa_Workmark_Dark.png'), 'tagline': 'Wellness Collective', 'subtitle': a.subtitle}}
json.dump(plan, open(os.path.join(work, 'plan.json'), 'w'), indent=1)
print(f'plan.json: {len(shots)} shots, {len(L)} caption lines, {D:.1f}s, beat {step:.2f}s')
