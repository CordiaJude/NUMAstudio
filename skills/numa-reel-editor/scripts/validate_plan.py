#!/usr/bin/env python3
"""Validate a plan.json before a long render. Fails loudly.
Usage: python3 validate_plan.py plan.json [analysis.json]
Exit code 0 = OK (warnings allowed), 1 = errors.
"""
import json, os, sys, re

TRANSITIONS = {'cut', 'punch', 'whip', 'leakfade', 'fade', 'flash', 'wipe'}
LOOKS = {'before', 'warm', 'none'}
BANNED = [
    r'inflammat', r'\bimmun', r'\bdetox', r'\btoxin', r'burns? (fat|calories)', r'weight[- ]?loss', r'\bheal(s|ing)?\b',
    r'\bcures?\b', r'\btreats?\b', r'\bprevents?\b', r'\banxiety\b', r'\bdepression\b', r'\bptsd\b', r'\barthritis\b',
    r'pain relief', r'blood pressure', r'heart health', r'anti-?aging', r'\bcollagen\b', r'\bwrinkles?\b', r'\bcovid',
    r'science-?backed', r'clinically proven', r'studies show', r'fda[- ]approved', r'\bdopamine\b',
]

def main():
    plan_path = sys.argv[1]
    P = json.load(open(plan_path))
    A = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
    errs, warns = [], []
    D = P.get('duration')
    if not isinstance(D, (int, float)) or D <= 0: errs.append('duration missing or not positive')
    elif D > 180: errs.append(f'duration {D}s is over 3 minutes (not recommended to non-followers)')
    elif D > 90: warns.append(f'duration {D}s: growth reels should be 45-60 s')
    shots = P.get('shots') or []
    if not shots: errs.append('no shots')
    prev_t1 = 0.0
    for i, s in enumerate(shots):
        tag = f'shot {i}'
        for k in ('src', 't0', 't1'):
            if k not in s: errs.append(f'{tag}: missing {k}')
        if 'src' in s:
            if not os.path.isabs(s['src']): errs.append(f'{tag}: src must be an absolute path')
            elif not os.path.exists(s['src']): errs.append(f'{tag}: file not found {s["src"]}')
        if 't0' in s and 't1' in s:
            if abs(s['t0'] - prev_t1) > 1e-3: errs.append(f'{tag}: t0 {s["t0"]} does not continue from previous t1 {prev_t1}')
            if s['t1'] <= s['t0']: errs.append(f'{tag}: t1 <= t0')
            elif s['t1'] - s['t0'] < 0.3: warns.append(f'{tag}: shorter than 0.3 s')
            prev_t1 = s['t1']
        tr = s.get('tr', 'cut')
        if tr not in TRANSITIONS: errs.append(f'{tag}: unknown transition {tr}')
        if tr == 'whip' and i == 0: errs.append(f'{tag}: first shot cannot whip')
        if s.get('look', 'warm') not in LOOKS: errs.append(f'{tag}: unknown look {s.get("look")}')
        z = s.get('z', [1.02, 1.14])
        if not (isinstance(z, list) and len(z) == 2 and all(0.95 <= v <= 1.5 for v in z)): errs.append(f'{tag}: z must be [a, b] within 0.95-1.5')
        if s.get('kind', 'image') == 'video' and s.get('start', 0) < 0: errs.append(f'{tag}: negative clip start')
    if shots and D and abs(prev_t1 - D) > 1e-3: errs.append(f'last shot ends at {prev_t1}, duration is {D}')
    whips = sum(1 for s in shots if s.get('tr') == 'whip')
    if shots and whips > len(shots) / 3 + 1: warns.append(f'{whips} whips in {len(shots)} shots: max about every third cut')
    if shots and len({s.get('tr', 'cut') for s in shots}) < 3 and len(shots) > 6: warns.append('fewer than 3 transition types: looks repetitive')
    # beat alignment
    if A and A.get('beats') and shots:
        beats = A['beats']; fps = P.get('fps', 30); off = []
        for i, s in enumerate(shots[1:], 1):
            d = min(abs(s['t0'] - b) for b in beats)
            if d > 1.0 / fps + 1e-3: off.append(f'{i}@{s["t0"]:.2f} (+{d:.2f}s)')
        if off: warns.append(f'{len(off)} cuts not on a beat: ' + ', '.join(off[:8]))
    # captions
    words_all = []
    lines = P.get('lines', [])
    last_end = -1
    for j, ln in enumerate(lines):
        ws = ln.get('words', [])
        if not ws: errs.append(f'line {j}: no words'); continue
        times = [w[1] for w in ws]
        if times != sorted(times): errs.append(f'line {j}: word times out of order')
        if ln.get('end', 0) < times[-1]: errs.append(f'line {j}: end before last word appears')
        if times[0] < last_end - 0.05: warns.append(f'line {j}: starts before line {j-1} has faded out')
        if D and ln.get('end', 0) > D: errs.append(f'line {j}: ends after the video')
        last_end = ln.get('end', 0)
        words_all += [w[0] for w in ws]
        if sum(len(w[0]) + 1 for w in ws) > 80: warns.append(f'line {j}: long caption line, may wrap to 3 rows')
    text = ' '.join(words_all).lower()
    hits = sorted({m.group(0) for pat in BANNED for m in re.finditer(pat, text)})
    if hits: errs.append('banned-claims words in captions: ' + ', '.join(hits))
    if A and A.get('words') and words_all:
        spoken = len(A['words']); shown = len(words_all)
        if abs(spoken - shown) > max(3, 0.1 * spoken): warns.append(f'captions have {shown} words, transcript has {spoken}')
    ec = P.get('endcard')
    if ec:
        if D and not (0 < ec.get('t', -1) < D): errs.append('endcard.t outside the video')
        elif D and D - ec['t'] < 3.5: warns.append('end card shorter than 3.5 s')
        if ec.get('logo') and not os.path.exists(ec['logo']): errs.append('endcard logo not found')
    for L in P.get('leaks', []):
        if len(L) != 3 or not (0 <= L[2] <= 0.6): errs.append(f'leak {L}: must be [time, duration, strength 0-0.6]')
    for w in warns: print('WARN ', w)
    for e in errs: print('ERROR', e)
    print('OK' if not errs else f'FAILED with {len(errs)} error(s)')
    sys.exit(1 if errs else 0)

if __name__ == '__main__':
    main()
