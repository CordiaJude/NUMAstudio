#!/usr/bin/env python3
"""Reel engine: renders a 1080x1920 cinematic edit from a JSON plan.
Usage: python3 engine.py plan.json [preview t1 t2 ...]
"""
import cv2, numpy as np, subprocess, math, sys, json, os
from PIL import Image, ImageFont, ImageDraw, ImageFilter, ImageOps, ImageEnhance

P = json.load(open(sys.argv[1]))
W, H, FPS = 1080, 1920, P.get('fps', 30)
DUR = P['duration']; SW, SH = 1296, 2304
OUT = P.get('out_dir', os.path.dirname(os.path.abspath(sys.argv[1])))
HERE = os.path.dirname(os.path.abspath(__file__)); ASSETS = os.path.join(HERE, '..', 'assets')
FONT_R = P.get('font_regular', os.path.join(ASSETS, 'fonts', 'LiberationSerif-Regular.ttf'))
FONT_I = P.get('font_italic', os.path.join(ASSETS, 'fonts', 'LiberationSerif-Italic.ttf'))
import shutil
FFMPEG = shutil.which('ffmpeg')
if not FFMPEG:
    try:
        import imageio_ffmpeg; FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit('ffmpeg not found: run  pip install imageio-ffmpeg  (or brew install ffmpeg)')
ACCENT = tuple(P.get('accent_rgb', [247, 214, 160]))

def ease(p): p = min(max(p, 0), 1); return p * p * (3 - 2 * p)
def eout(p): p = min(max(p, 0), 1); return 1 - (1 - p) ** 3

def canvas(im):
    if im.width / im.height < 0.85:
        return ImageOps.fit(im, (SW, SH), Image.LANCZOS)
    hh = int(SH * 0.92); ww = int(im.width * hh / im.height); CW = max(ww, SW)
    bg = ImageOps.fit(im, (CW, SH)).filter(ImageFilter.GaussianBlur(80)); bg = ImageEnhance.Brightness(bg).enhance(0.4)
    fg = im.resize((ww, hh), Image.LANCZOS)
    m = Image.new('L', (ww, hh), 0); ImageDraw.Draw(m).rectangle((0, 40, ww, hh - 40), fill=255); m = m.filter(ImageFilter.GaussianBlur(40))
    bg.paste(fg, ((CW - ww) // 2, (SH - hh) // 2), m); return bg

_vig = {}
def grade_arr(a, look):
    """a: float32 RGB 0..1"""
    if look == 'before':
        g = a.mean(2, keepdims=True); a = g + (a - g) * 0.55
        a = a * np.array([0.94, 0.98, 1.05], np.float32); a = 0.06 + a * 0.9
        a = np.clip(a, 0, 1) ** 1.08
    elif look == 'warm':
        g = a.mean(2, keepdims=True); a = g + (a - g) * 1.08
        a = np.clip(a * np.array([1.04, 1.0, 0.93], np.float32), 0, 1)
        a = a + 0.06 * np.sin(np.pi * a) * (a - 0.5) * 2; a = 0.02 + a * 0.97
    k = a.shape[:2]
    if k not in _vig:
        y, x = np.mgrid[0:k[0], 0:k[1]]
        r = np.sqrt(((x / k[1]) - .5) ** 2 * 1.6 + ((y / k[0]) - .5) ** 2)
        _vig[k] = (1 - 0.45 * np.clip((r - 0.3) / 0.45, 0, 1) ** 1.6)[..., None].astype(np.float32)
    return np.clip(a * _vig[k], 0, 1)

def to_bgr(a): return cv2.cvtColor((a * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

class ImgSrc:
    def __init__(s, path, look, crop=None):
        im = Image.open(path).convert('RGB')
        if crop: im = im.crop(tuple(crop))
        im = im.filter(ImageFilter.UnsharpMask(1.4, 55, 2))
        s.img = to_bgr(grade_arr(np.asarray(canvas(im)).astype(np.float32) / 255, look))
    def get(s, trel): return s.img

class VidSrc:
    """Video clip: frames read sequentially, graded, filled to canvas."""
    def __init__(s, path, look, start=0.0, speed=1.0):
        s.path, s.look, s.start, s.speed = path, look, start, speed
        s.cap = None; s.idx = -1; s.cur = None
    def get(s, trel):
        if s.cap is None:
            s.cap = cv2.VideoCapture(s.path); s.vfps = s.cap.get(cv2.CAP_PROP_FPS) or 30
            s.n = int(s.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        want = min(max(int((s.start + max(trel, 0) * s.speed) * s.vfps), 0), s.n - 1)
        if want < s.idx or want > s.idx + 30:
            s.cap.set(cv2.CAP_PROP_POS_FRAMES, want); s.idx = want - 1
        while s.idx < want:
            ok, fr = s.cap.read()
            if not ok: break
            s.idx += 1; s.raw = fr
        if s.cur is None or s.cur[0] != s.idx:
            c = canvas_fast(s.raw)
            rgb = cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
            s.cur = (s.idx, to_bgr(grade_arr(rgb, s.look)))
        return s.cur[1]

_masks = {}
def _cover(img, w, h, interp=cv2.INTER_AREA):
    ih, iw = img.shape[:2]; k = max(w / iw, h / ih)
    r = cv2.resize(img, (max(w, int(iw * k + 0.5)), max(h, int(ih * k + 0.5))), interpolation=interp)
    y0 = (r.shape[0] - h) // 2; x0 = (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]
def canvas_fast(bgr):
    """OpenCV version of canvas() for video frames (about 20x faster than the PIL path)."""
    ih, iw = bgr.shape[:2]
    if iw / ih < 0.85:
        return _cover(bgr, SW, SH, cv2.INTER_LINEAR)
    hh = int(SH * 0.92); ww = int(iw * hh / ih); CW = max(ww, SW)
    small = _cover(bgr, max(CW // 8, 8), SH // 8)
    bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 10), (CW, SH), interpolation=cv2.INTER_LINEAR)
    bg = (bg.astype(np.float32) * 0.4)
    fg = cv2.resize(bgr, (ww, hh), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    key = (ww, hh)
    if key not in _masks:
        m = np.zeros((hh, ww), np.float32); m[40:hh - 40, :] = 1
        _masks[key] = cv2.GaussianBlur(m, (0, 0), 40)[..., None]
    m = _masks[key]; x0 = (CW - ww) // 2; y0 = (SH - hh) // 2
    reg = bg[y0:y0 + hh, x0:x0 + ww]
    bg[y0:y0 + hh, x0:x0 + ww] = fg * m + reg * (1 - m)
    return np.clip(bg, 0, 255).astype(np.uint8)

SHOTS = P['shots']; SRC = []
for sh in SHOTS:
    if sh.get('kind', 'image') == 'video':
        SRC.append(VidSrc(sh['src'], sh.get('look', 'warm'), sh.get('start', 0), sh.get('speed', 1.0)))
    else:
        SRC.append(ImgSrc(sh['src'], sh.get('look', 'warm'), sh.get('crop')))

def view(i, t, extra=1.0):
    sh = SHOTS[i]; t0, t1 = sh['t0'], sh['t1']
    z0, z1 = sh.get('z', [1.02, 1.14]); px, py = sh.get('pan', [0, 0])
    img = SRC[i].get(t - t0)
    p = (t - t0) / (t1 - t0); pc = min(max(p, 0), 1)
    pe = 0.5 - 0.5 * math.cos(math.pi * pc) + (min(p, 1.6) - 1) * 0.15 * (p > 1)
    z = (z0 + (z1 - z0) * pe) * extra
    vw = SW / z; a = vw / W; CW = img.shape[1]
    cx = CW / 2 + px * SW * pe; cy = SH / 2 + py * SH * pe
    if CW > SW + 10:
        q = (CW - vw) / 2 * 0.85; dr = 1 if i % 2 else -1
        cx = CW / 2 + dr * q * (2 * pe - 1)
    cx = min(max(cx, vw / 2), CW - vw / 2); vh = H * a; cy = min(max(cy, vh / 2), SH - vh / 2)
    M = np.float32([[a, 0, cx - W / 2 * a], [0, a, cy - H / 2 * a]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)

def hblur(img, n):
    n = int(n)
    return img if n < 3 else cv2.filter2D(img, -1, np.ones((1, n), np.float32) / n)

def screen(base, layer):
    b = base.astype(np.float32) / 255
    return ((1 - (1 - b) * (1 - layer)) * 255).astype(np.uint8)

def leak(t, strength, seed=0):
    if strength <= 0.01: return None
    h, w = 120, 68; y, x = np.mgrid[0:h, 0:w].astype(np.float32); out = np.zeros((h, w, 3), np.float32)
    for j, (col, sp) in enumerate([((0.25, 0.55, 1.0), 0.6), ((0.35, 0.3, 1.0), -0.45), ((0.1, 0.75, 1.0), 0.3)]):
        cx = w * (0.5 + 0.6 * math.sin(t * sp + j * 2.1 + seed)); cy = h * (0.5 + 0.5 * math.cos(t * sp * 0.7 + j + seed))
        r = w * (0.55 + 0.15 * j)
        out += np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r))[..., None] * np.array(col, np.float32)
    return np.clip(cv2.resize(out, (W, H), interpolation=cv2.INTER_CUBIC) * strength, 0, 1)

def bloom(img, amt=0.2):
    s = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    hi = cv2.GaussianBlur(np.clip((s - 0.62) / 0.38, 0, 1), (0, 0), 9)
    return screen(img, cv2.resize(hi, (W, H)) * amt)

def whip(a, b, t):
    tc = SHOTS[b]['t0']; p = min(max((t - (tc - 0.14)) / 0.28, 0), 1); off = int(ease(p) * W)
    A = view(a, t); Bv = view(b, t); out = np.empty_like(A)
    out[:, :W - off] = A[:, off:]; out[:, W - off:] = Bv[:, :off]
    return hblur(out, 6 + 160 * math.sin(math.pi * p))

def frame_at(t):
    i = max(k for k in range(len(SHOTS)) if SHOTS[k]['t0'] <= t + 1e-6)
    t0 = SHOTS[i]['t0']; tr = SHOTS[i].get('tr', 'cut'); prev = i - 1; dt = t - t0
    if i + 1 < len(SHOTS) and SHOTS[i + 1].get('tr') == 'whip' and t > SHOTS[i + 1]['t0'] - 0.14: return whip(i, i + 1, t)
    if tr == 'whip' and dt < 0.14 and prev >= 0: return whip(prev, i, t)
    img = view(i, t)
    if tr == 'punch' and dt < 0.22:
        p = eout(dt / 0.22); img = view(i, t, 1 + 0.16 * (1 - p))
        img = cv2.addWeighted(img, 1, np.full_like(img, 255), 0.28 * (1 - p), 0)
    elif tr in ('fade', 'leakfade') and dt < 0.5 and prev >= 0:
        a = ease(dt / 0.5); img = cv2.addWeighted(view(prev, t), 1 - a, img, a, 0)
    elif tr == 'flash' and dt < 0.35:
        img = cv2.addWeighted(img, 1, np.full_like(img, 255), 0.85 * (1 - eout(dt / 0.35)), 0)
    elif tr == 'wipe' and dt < 1.0 and prev >= 0:
        p = ease(dt); before = view(prev, t); xpos = int(-80 + p * (W + 160))
        m = np.zeros((H, W), np.float32); m[:, :max(0, xpos)] = 1; m = cv2.GaussianBlur(m, (0, 0), 30)
        img = (img * m[..., None] + before * (1 - m[..., None])).astype(np.uint8)
        if 0 < xpos < W:
            g = np.zeros((H, W), np.float32); g[:, max(0, xpos - 2):xpos + 2] = 1
            img = screen(img, np.clip(cv2.GaussianBlur(g, (0, 0), 14)[..., None] * 3 * np.array([0.6, 0.85, 1.0]), 0, 1))
    return img

# ---- captions: lines = [{"words": [["This",0.62], ["Katie",1.42,1]], "end": 2.45}]
FR = ImageFont.truetype(FONT_R, 92); FI = ImageFont.truetype(FONT_I, 100)
def sprite(txt, it):
    f = FI if it else FR; bx = ImageDraw.Draw(Image.new('L', (1, 1))).textbbox((0, 0), txt, font=f)
    im = Image.new('RGBA', (bx[2] + 40, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((20, 18), txt, font=f, fill=(ACCENT + (255,)) if it else (255, 252, 246, 255))
    a = np.asarray(im).astype(np.float32) / 255
    return a, cv2.GaussianBlur(a[..., 3], (0, 0), 8) * 0.75, bx[2]
CAP = []
for ln in P.get('lines', []):
    spr = [(sprite(w[0], len(w) > 2 and w[2]), w[1]) for w in ln['words']]
    rows, row, rw = [], [], 0
    for sp, ts in spr:
        ww = sp[2] + 26
        if rw + ww > 960 and row: rows.append((row, rw)); row, rw = [], 0
        row.append((sp, ts)); rw += ww
    rows.append((row, rw)); placed = []; ytop = P.get('caption_y', 1420) - (len(rows) - 1) * 62
    for r, (row, rw) in enumerate(rows):
        x = (W - rw) // 2
        for sp, ts in row: placed.append((sp, ts, x - 20, ytop + r * 124)); x += sp[2] + 26
    CAP.append((placed, ln['words'][0][1], ln['end']))

def draw_caps(img, t):
    f = img.astype(np.float32) / 255
    for placed, ts0, tend in CAP:
        if t < ts0 - 0.05 or t > tend + 0.35: continue
        lo = 1 - ease((t - tend) / 0.35) if t > tend else 1
        for (a, sh, _), ts, x, y in placed:
            p = (t - ts) / 0.28
            if p <= 0: continue
            al = eout(p) * lo; yy = y + int(22 * (1 - eout(p))); hh, ww = sh.shape
            x0, x1 = max(x, 0), min(x + ww, W); reg = f[yy:yy + hh, x0:x1]
            s_ = sh[:, x0 - x:x1 - x, None] * al; reg[:] = reg * (1 - s_)
            ac = a[:, x0 - x:x1 - x, 3:4] * al; reg[:] = reg * (1 - ac) + a[:, x0 - x:x1 - x, 2::-1] * ac
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)

# ---- end card: {"t": 34.16, "logo": "logo.png", "logo_width": 820, "tagline": "...", "subtitle": "..."}
EC = P.get('endcard')
def alpha_text(txt, size, font, spacing=0):
    f = ImageFont.truetype(font, size); txt = (' ' * spacing).join(txt) if spacing else txt
    bx = ImageDraw.Draw(Image.new('L', (1, 1))).textbbox((0, 0), txt, font=f)
    im = Image.new('L', (bx[2] + 10, bx[3] + 20), 0); ImageDraw.Draw(im).text((5, 5), txt, font=f, fill=255)
    return np.asarray(im).astype(np.float32) / 255
if EC:
    if EC.get('logo'):
        lg = Image.open(EC['logo']).convert('RGBA'); lw = EC.get('logo_width', 820)
        lg = lg.resize((lw, int(lg.height * lw / lg.width)), Image.LANCZOS); la = np.asarray(lg).astype(np.float32) / 255
        # use alpha if present, else luminance-inverted (dark logo on white)
        EC['_logo'] = la[..., 3] if la[..., 3].min() < 0.99 else np.clip(1 - la[..., :3].mean(2) * 1.15, 0, 1)
    if EC.get('tagline'): EC['_tag'] = alpha_text(EC['tagline'].upper(), 34, FONT_R, 1)
    if EC.get('subtitle'): EC['_sub'] = alpha_text(EC['subtitle'], 58, FONT_I)

def place(f, alpha, cx, cy, col, al, scale=1.0):
    if al <= 0: return
    if scale != 1.0: alpha = cv2.resize(alpha, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    h, w = alpha.shape; x = int(cx - w / 2); y = int(cy - h / 2)
    sh = cv2.GaussianBlur(alpha, (0, 0), 10) * 0.55 * al; reg = f[y:y + h, x:x + w]
    reg[:] = reg * (1 - sh[..., None]); a = alpha[..., None] * al
    reg[:] = reg * (1 - a) + np.array(col[::-1], np.float32) * a

def endcard(img, t):
    if not EC or t < EC['t'] + 0.35: return img
    f = img.astype(np.float32) / 255; T = EC['t']
    if '_logo' in EC: p1 = eout((t - T - 0.45) / 0.9); place(f, EC['_logo'], W / 2, 900, (1, 1, 1), p1, 1.06 - 0.06 * p1)
    if '_tag' in EC: place(f, EC['_tag'], W / 2, 1040, (1, 1, 1), eout((t - T - 0.95) / 0.8))
    if '_sub' in EC: place(f, EC['_sub'], W / 2, 1500, tuple(c / 255 for c in ACCENT), eout((t - T - 1.65) / 0.9))
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)

LEAKS = P.get('leaks', [])
GRAD = (1 - 0.42 * np.clip((np.arange(H) - 1050) / 700, 0, 1) ** 1.3).astype(np.float32)[:, None, None]
rng = np.random.default_rng(3); GR = [rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32) for _ in range(6)]

def render(t):
    img = bloom(frame_at(t), 0.2); s = 0
    for tc, d, a in LEAKS:
        if tc - 0.2 < t < tc + d: s = max(s, a * math.sin(math.pi * (t - tc + 0.2) / (d + 0.2)))
    L = leak(t, s, seed=int(t // 5))
    if L is not None: img = screen(img, L)
    if not EC or t < EC['t'] + 0.2: img = (img.astype(np.float32) * GRAD).astype(np.uint8)
    img = endcard(draw_caps(img, t), t)
    g = cv2.resize(GR[int(t * FPS) % 6], (W, H))
    img = np.clip(img.astype(np.float32) + g[..., None] * 5.0, 0, 255)
    if t < 0.4: img *= ease(t / 0.4)
    if t > DUR - 0.8: img *= 1 - ease((t - DUR + 0.8) / 0.8)
    return img.astype(np.uint8)

if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[2] == 'preview':
        ts = list(map(float, sys.argv[3:])); tiles = []
        for t in ts: tiles.append(cv2.resize(render(t), (270, 480)))
        rows = [np.hstack(tiles[k:k + 5] + [np.zeros_like(tiles[0])] * (5 - len(tiles[k:k + 5]))) for k in range(0, len(tiles), 5)]
        cv2.imwrite(os.path.join(OUT, 'preview.jpg'), np.vstack(rows)); print('preview.jpg'); sys.exit()
    N = int(DUR * FPS); vid = os.path.join(OUT, 'video_noaudio.mp4')
    p = subprocess.Popen([FFMPEG, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-maxrate', '14M', '-bufsize', '28M', '-pix_fmt', 'yuv420p', vid], stdin=subprocess.PIPE)
    for n in range(N):
        p.stdin.write(render(n / FPS).tobytes())
        if n % 150 == 0: print(f'{n}/{N}', flush=True)
    p.stdin.close(); p.wait(); print('done', vid)
