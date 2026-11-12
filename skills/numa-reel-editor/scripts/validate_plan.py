#!/usr/bin/env python3
"""Validate a plan.json before a render. Fails loudly, never with a traceback.

Usage:
    validate_plan.py PLAN_JSON [ANALYSIS_JSON] [--prefs FILE] [--strict] [--json]

Runs the JSON Schema (schemas/plan.schema.json, and analysis.schema.json for
the analysis) and then every cross-field rule in docs/CONTRACTS.md section 5:
tiling, absolute paths and file existence, duration cap, first-second rules,
zoom range, clip spans, beat alignment, shot length in beats, whip spacing,
transition variety, the one signature moment, caption timing and layout,
caption-vs-transcript alignment, safe area, faces, claims (brand.json via
claims_scan), consent, music license, AI label, end card, leaks, hook, natural
sound, formats, output spec, preference limits and "never open on the logo".

Without ANALYSIS_JSON, `analysis.json` next to the plan is used when it exists.
Each problem is one `ERROR: <where>: <problem> [rule N]` or `WARN: ...` line on
stderr. stdout: `OK: <n> shots, <duration> s, <w> warnings` or a FAILED line;
with --json exactly one JSON report. Exit 0 valid, 1 on any ERROR (or any WARN
with --strict).
"""
from __future__ import annotations

import difflib
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import claims_scan  # noqa: E402

TILE_TOL = 1e-3


@dataclass
class Issue:
    level: str  # "ERROR" | "WARN"
    rule: int
    where: str
    message: str

    def line(self) -> str:
        return f"{self.where}: {self.message} [rule {self.rule}]"

    def as_dict(self) -> dict:
        return asdict(self)


class Checker:
    """Collects issues for one plan. `run()` returns the list."""

    def __init__(self, plan: Any, analysis: Any = None, prefs: dict | None = None,
                 plan_path: Path | None = None, analysis_path: Path | None = None):
        self.plan = plan
        self.analysis = analysis
        self.prefs = prefs or {}
        self.plan_path = plan_path
        self.analysis_path = analysis_path
        self.issues: list[Issue] = []
        self._probe: dict[str, dict | None] = {}
        self._img_size: dict[str, tuple[int, int] | None] = {}
        self._fonts: dict[tuple[str, int], Any] = {}

    # -- recording --------------------------------------------------------
    def err(self, rule: int, where: str, msg: str) -> None:
        self.issues.append(Issue("ERROR", rule, where, msg))

    def wrn(self, rule: int, where: str, msg: str) -> None:
        self.issues.append(Issue("WARN", rule, where, msg))

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _cfg(dotted: str, default: Any) -> Any:
        try:
            return nc.config_value(dotted, default)
        except nc.UserError:
            return default

    def _brand_path(self, getter, *args) -> Path | None:
        try:
            return getter(*args)
        except nc.UserError:
            return None

    def _clip_info(self, path: str) -> dict | None:
        """{duration, has_audio} for a clip: from analysis.json when listed, else probed (cached)."""
        if path in self._probe:
            return self._probe[path]
        info = None
        if isinstance(self.analysis, dict):
            for c in self.analysis.get("clips") or []:
                if isinstance(c, dict) and path in (c.get("path"), c.get("prepared_path")):
                    info = {"duration": c.get("duration"), "has_audio": c.get("has_audio")}
                    break
        if info is None and os.path.isfile(path):
            try:
                mi = nc.media_info(path)
                info = {"duration": mi.get("duration"), "has_audio": mi.get("has_audio")}
            except nc.UserError:
                info = None
        self._probe[path] = info
        return info

    def _image_size(self, path: str) -> tuple[int, int] | None:
        if path in self._img_size:
            return self._img_size[path]
        size = None
        if isinstance(self.analysis, dict):
            for p in self.analysis.get("photos") or []:
                if isinstance(p, dict) and path in (p.get("path"), p.get("prepared_path")) and p.get("size"):
                    size = (int(p["size"][0]), int(p["size"][1]))
                    break
        if size is None and os.path.isfile(path):
            try:
                from PIL import Image
                with Image.open(path) as im:
                    size = im.size
            except Exception:  # noqa: BLE001 - unreadable image: size unknown, other rules report it
                size = None
        self._img_size[path] = size
        return size

    def _font(self, path: str, px: int):
        key = (path, px)
        if key not in self._fonts:
            try:
                from PIL import ImageFont
                self._fonts[key] = ImageFont.truetype(path, px)
            except Exception:  # noqa: BLE001 - missing/broken font is reported by rule 5
                self._fonts[key] = None
        return self._fonts[key]

    # -- main -------------------------------------------------------------
    def run(self) -> list[Issue]:
        P = self.plan
        if not isinstance(P, dict):
            self.err(1, "plan", "must be a JSON object")
            return self.issues
        for line in nc.schema_errors("plan", P):
            where, _, msg = line.partition(": ")
            self.err(1, where, msg)
        if self.analysis is not None:
            if not isinstance(self.analysis, dict):
                self.err(1, "analysis", "must be a JSON object")
                self.analysis = None
            else:
                aerrs = nc.schema_errors("analysis", self.analysis)
                for line in aerrs:
                    where, _, msg = line.partition(": ")
                    self.err(1, f"analysis {where}", msg)
                if aerrs:
                    self.analysis = None
        if any(i.rule == 1 and not i.where.startswith("analysis") for i in self.issues):
            return self.issues  # cross-field rules need a well-formed plan

        self.D = float(P["duration"])
        self.fps = float(P.get("fps", 30))
        self.size = P.get("size") or [1080, 1920]
        self.v2 = P.get("schema_version", 1) == 2
        self.shots = P["shots"]
        self.lines = P.get("lines") or []
        self.ec = P.get("endcard")
        self.beats = sorted(b for b in (self.analysis or {}).get("beats") or [] if isinstance(b, (int, float)))

        self.check_tiling()
        self.check_paths()
        self.check_duration()
        self.check_first_shot()
        self.check_shots()
        self.check_beats()
        self.check_transitions()
        self.check_signature()
        self.check_lines()
        self.check_transcript()
        self.check_layout()
        self.check_claims()
        self.check_safety()
        self.check_endcard()
        self.check_leaks()
        self.check_hook()
        self.check_nat()
        self.check_formats()
        self.check_output_spec()
        self.check_prefs()
        return self.issues

    # -- rules 2, 3 ---------------------------------------------------------
    def check_tiling(self) -> None:
        prev = 0.0
        for i, s in enumerate(self.shots):
            t0, t1 = float(s["t0"]), float(s["t1"])
            if i == 0 and abs(t0) > TILE_TOL:
                self.err(2, "shots[0].t0", f"must be 0, got {t0:g}")
            elif i > 0 and abs(t0 - prev) > TILE_TOL:
                kind = "gap" if t0 > prev else "overlap"
                self.err(2, f"shots[{i}].t0", f"{t0:g} does not continue from shots[{i - 1}].t1 {prev:g} ({kind})")
            if t1 <= t0:
                self.err(2, f"shots[{i}]", f"t1 {t1:g} must be after t0 {t0:g}")
            elif t1 - t0 < 0.3:
                self.wrn(3, f"shots[{i}]", f"only {t1 - t0:.2f} s long (shorter than 0.3 s)")
            prev = t1
        if abs(prev - self.D) > TILE_TOL:
            self.err(2, f"shots[{len(self.shots) - 1}].t1", f"last shot ends at {prev:g}, duration is {self.D:g}")

    # -- rules 4, 5, 39 ----------------------------------------------------
    def _paths(self) -> list[tuple[str, str]]:
        P = self.plan
        out: list[tuple[str, str]] = []
        if P.get("out_dir"):
            out.append(("out_dir", P["out_dir"]))
        for i, s in enumerate(self.shots):
            out.append((f"shots[{i}].src", s["src"]))
        for k in ("font_regular", "font_italic"):
            if P.get(k):
                out.append((k, P[k]))
        if isinstance(self.ec, dict) and self.ec.get("logo"):
            out.append(("endcard.logo", self.ec["logo"]))
        for i, n in enumerate(P.get("nat") or []):
            out.append((f"nat[{i}].src", n["src"]))
        m = P.get("music")
        if isinstance(m, dict) and m.get("path"):
            out.append(("music.path", m["path"]))
        fm = P.get("formats") or {}
        for i, c in enumerate(fm.get("carousel") or []):
            if c.get("src"):
                out.append((f"formats.carousel[{i}].src", c["src"]))
        for i, h in enumerate(fm.get("hook_variants") or []):
            if h.get("src"):
                out.append((f"formats.hook_variants[{i}].src", h["src"]))
        return out

    def check_paths(self) -> None:
        for where, p in self._paths():
            if not os.path.isabs(p):
                self.err(4, where, f"must be an absolute path: {p}")
                continue
            if where == "out_dir":
                if not os.path.isdir(p):
                    if os.path.exists(p):
                        self.err(5, where, f"is not a folder: {p}")
                    elif not os.path.isdir(os.path.dirname(p.rstrip("/\\")) or "/"):
                        self.err(5, where, f"folder not found (nor its parent): {p}")
                continue
            if not os.path.isfile(p):
                self.err(5, where, f"file not found: {p}")
        P = self.plan
        # effective fonts and logo when defaulted from brand.json
        for k, style in (("font_regular", "regular"), ("font_italic", "italic")):
            if not P.get(k):
                fp = self._brand_path(nc.brand_font, style)
                if fp is None or not fp.is_file():
                    self.err(5, k, f"brand.json default font not found: {fp}")
        if isinstance(self.ec, dict) and not self.ec.get("logo"):
            lp = self._brand_path(nc.brand_asset, "wordmark")
            if lp is None or not lp.is_file():
                self.err(5, "endcard.logo", f"brand.json default wordmark not found: {lp}")
        # rule 39: never open on the logo
        logos = set()
        for key in ("wordmark", "secondary_mark", "wordmark_light"):
            lp = self._brand_path(nc.brand_asset, key)
            if lp is not None:
                logos.add(os.path.realpath(lp))
        if isinstance(self.ec, dict) and self.ec.get("logo") and os.path.isabs(self.ec["logo"]):
            logos.add(os.path.realpath(self.ec["logo"]))
        firsts = [("shots[0].src", self.shots[0]["src"])]
        for i, h in enumerate((P.get("formats") or {}).get("hook_variants") or []):
            if h.get("src"):
                firsts.append((f"formats.hook_variants[{i}].src", h["src"]))
        for where, src in firsts:
            if os.path.isabs(src) and os.path.realpath(src) in logos:
                self.err(39, where, "the reel opens on the logo; open on the strongest image instead")

    # -- rules 6, 7 --------------------------------------------------------
    def check_duration(self) -> None:
        cap = float(self._cfg("render.length_s.hard_max", 180))
        lo, hi = self._cfg("render.length_s.main_reel", [15, 60])
        if self.D > cap:
            self.err(6, "duration", f"{self.D:g} s is over the {cap:g} s cap")
        elif not (lo <= self.D <= hi):
            self.wrn(7, "duration", f"{self.D:g} s is outside the {lo:g}-{hi:g} s main-reel range (growth reels run 45-60 s)")

    # -- rules 8, 9, 40 ----------------------------------------------------
    def check_first_shot(self) -> None:
        s0 = self.shots[0]
        tr = s0.get("tr", "cut")
        if tr in ("whip", "wipe", "fade", "leakfade"):
            self.err(8, "shots[0].tr", f"'{tr}' needs a previous shot (and a fade from black is over 0.2 s); use 'cut'")
        elif tr in ("punch", "flash"):
            self.wrn(9, "shots[0].tr", f"'{tr}' on the first shot; prefer 'cut'")
        z = s0.get("z", [1.02, 1.14])
        pan = s0.get("pan", [0, 0])
        if (s0.get("kind", "image") == "image" and z[0] == z[1] and (not pan or all(v == 0 for v in pan))
                and tr == "cut" and not self.plan.get("hook")):
            self.err(40, "shots[0]", "no movement from frame 1: a static still with no zoom, pan, punch or hook text")

    # -- rules 10-13, box geometry, 12 ------------------------------------
    def check_shots(self) -> None:
        for i, s in enumerate(self.shots):
            z = s.get("z", [1.02, 1.14])
            if not all(0.95 <= v <= 1.5 for v in z):
                self.err(10, f"shots[{i}].z", f"{z} is outside 0.95-1.5")
            elif z[0] == z[1]:
                self.wrn(11, f"shots[{i}].z", f"static shot (zoom {z[0]:g} to {z[1]:g}); every shot moves")
            kind = s.get("kind", "image")
            src = s["src"]
            if kind == "video":
                if "crop" in s:
                    self.err(13, f"shots[{i}].crop", "crop applies to images only, not video shots")
                span = (float(s["t1"]) - float(s["t0"])) * float(s.get("speed", 1.0))
                start = float(s.get("start", 0))
                info = self._clip_info(src) if os.path.isabs(src) else None
                if info and info.get("duration"):
                    if start + span > info["duration"] + 1.0 / self.fps:
                        self.wrn(12, f"shots[{i}]", f"clip time {start:g}+{span:.2f} s runs past the clip's end "
                                                    f"({info['duration']:.2f} s); the last frame freezes")
            elif "crop" in s:
                l, t, r, b = s["crop"]
                size = self._image_size(src) if os.path.isabs(src) else None
                if r <= l or b <= t:
                    self.err(13, f"shots[{i}].crop", f"{s['crop']} is empty (right/bottom must exceed left/top)")
                elif size and (r > size[0] or b > size[1]):
                    self.err(13, f"shots[{i}].crop", f"{s['crop']} is outside the {size[0]}x{size[1]} image")
            for key in ("faces", "blur"):
                for j, box in enumerate(s.get(key) or []):
                    x, y, w, h = box
                    if w <= 0 or h <= 0 or x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
                        self.err(13, f"shots[{i}].{key}[{j}]", f"{box} is not a box inside the frame (x+w and y+h <= 1, w and h > 0)")

    # -- rules 14, 15 -------------------------------------------------------
    def _beat_period(self) -> float | None:
        if len(self.beats) < 2:
            return None
        diffs = [b - a for a, b in zip(self.beats, self.beats[1:]) if b > a]
        return statistics.median(diffs) if diffs else None

    def _endcard_index(self) -> int | None:
        if not isinstance(self.ec, dict):
            return None
        for i, s in enumerate(self.shots):
            if abs(float(s["t0"]) - float(self.ec["t"])) <= TILE_TOL + 1.0 / self.fps:
                return i
        return None

    def check_beats(self) -> None:
        if not self.beats:
            return
        tol = float(self._cfg("render.beat_tolerance_frames", 1)) / self.fps
        off = []
        for i, s in enumerate(self.shots[1:], 1):
            t = float(s["t0"])
            d = min(abs(t - b) for b in self.beats)
            if d > tol + 1e-6:
                off.append(i)
                self.wrn(14, f"shots[{i}].t0", f"cut at {t:.3f} s is {d * 1000:.0f} ms off the nearest beat (more than one frame)")
        period = self._beat_period()
        if not period:
            return
        max_beats = int(self._cfg("render.max_shot_beats", 4))
        eci = self._endcard_index()
        for i, s in enumerate(self.shots):
            if s.get("peak") or i == eci:
                continue
            t0, t1 = float(s["t0"]), float(s["t1"])
            if self.beats[0] - tol <= t0 and t1 <= self.beats[-1] + period + tol:
                n = sum(1 for b in self.beats if t0 - tol <= b < t1 - tol)
            else:
                n = round((t1 - t0) / period)
            if n > max_beats:
                self.wrn(15, f"shots[{i}]", f"holds {n} beats ({t1 - t0:.2f} s), more than {max_beats}, without peak: true")

    # -- rules 16, 17 ---------------------------------------------------------
    def check_transitions(self) -> None:
        trs = [s.get("tr", "cut") for s in self.shots]
        cuts = len(self.shots) - 1
        whips = [i for i, t in enumerate(trs) if t == "whip"]
        allowed = math.ceil(cuts / 3) if cuts else 0
        if len(whips) > allowed:
            self.wrn(16, "shots", f"{len(whips)} whips in {cuts} cuts; at most one every third cut ({allowed})")
        for a, b in zip(whips, whips[1:]):
            if b - a < 3:
                self.wrn(16, f"shots[{b}].tr", f"whip only {b - a} cut(s) after the whip at shots[{a}]; at most every third cut")
        if len(self.shots) > 6 and len(set(trs[1:])) < 3:
            self.wrn(17, "shots", f"only {len(set(trs[1:]))} transition type(s) across {len(self.shots)} shots; vary them (3+)")

    # -- rule 18 -----------------------------------------------------------
    def check_signature(self) -> None:
        trs = [s.get("tr", "cut") for s in self.shots]
        eci = self._endcard_index()
        wipes = trs.count("wipe")
        flashes = [i for i, t in enumerate(trs) if t == "flash" and i != eci]
        if wipes > 1:
            self.wrn(18, "shots", f"{wipes} wipes; the reel gets exactly one signature moment")
        elif wipes == 0 and not flashes:
            self.wrn(18, "shots", "no signature moment: no before/after wipe and no flash reveal outside the end card")
        sig = self.plan.get("signature")
        if isinstance(sig, dict):
            t, typ = float(sig["t"]), sig["type"]
            ok = any(abs(float(s["t0"]) - t) <= 1.0 / self.fps + TILE_TOL and s.get("tr", "cut") == typ
                     for s in self.shots[1:])
            if not ok:
                self.err(18, "signature", f"no shot starts at {t:g} s with tr '{typ}'")

    # -- rules 19-21, 23 --------------------------------------------------------
    def check_lines(self) -> None:
        prev_last = None
        prev_end = None
        for j, ln in enumerate(self.lines):
            times = [float(w[1]) for w in ln["words"]]
            if any(b < a for a, b in zip(times, times[1:])):
                self.err(19, f"lines[{j}]", "word appear times are not in ascending order")
            if prev_last is not None and times[0] < prev_last:
                self.err(19, f"lines[{j}]", f"starts at {times[0]:g} s, before line {j - 1}'s last word ({prev_last:g} s)")
            end = float(ln["end"])
            if end < max(times):
                self.err(20, f"lines[{j}].end", f"{end:g} is before its last word appears ({max(times):g} s)")
            if end > self.D + TILE_TOL:
                self.err(20, f"lines[{j}].end", f"{end:g} is after the reel ends ({self.D:g} s)")
            if prev_end is not None and times[0] < prev_end - TILE_TOL:
                self.wrn(21, f"lines[{j}]", f"starts at {times[0]:g} s while line {j - 1} is still on screen (until {prev_end:g} s)")
            text = " ".join(w[0] for w in ln["words"])
            if len(text) > 80:
                self.wrn(23, f"lines[{j}]", f"{len(text)} characters (over 80); one short sentence per line")
            prev_last, prev_end = max(times), end

    # -- rule 24 -----------------------------------------------------------
    @staticmethod
    def _normw(w: str) -> str:
        return re.sub(r"[^\w']+", "", w.lower()).strip("'")

    def check_transcript(self) -> None:
        if not isinstance(self.analysis, dict):
            return
        tw = [w for w in self.analysis.get("words") or [] if isinstance(w, dict)]
        if not tw or not self.lines:
            return
        cap = [(j, k, w) for j, ln in enumerate(self.lines) for k, w in enumerate(ln["words"])]
        a = [self._normw(w[0]) for _, _, w in cap]
        b = [self._normw(w["w"]) for w in tw]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        shown = 0

        def timing(ci: int, ti: int) -> None:
            j, k, w = cap[ci]
            d = abs(float(w[1]) - float(tw[ti]["appear"]))
            where = f"lines[{j}].words[{k}]"
            if d > 0.5:
                self.err(24, where, f"'{w[0]}' appears at {float(w[1]):g} s, the voice says it at {float(tw[ti]['appear']):g} s ({d:.2f} s off)")
            elif d > 0.15:
                self.wrn(24, where, f"'{w[0]}' appears {d:.2f} s off the voice ({float(tw[ti]['appear']):g} s)")

        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for ci, ti in zip(range(i1, i2), range(j1, j2)):
                    timing(ci, ti)
                shown += i2 - i1
            elif op == "replace":
                n = min(i2 - i1, j2 - j1)
                for ci, ti in zip(range(i1, i1 + n), range(j1, j1 + n)):
                    j, k, w = cap[ci]
                    self.wrn(24, f"lines[{j}].words[{k}]", f"'{w[0]}' does not match the transcript word '{tw[ti]['w']}'")
                    timing(ci, ti)
                shown += n
                for ci in range(i1 + n, i2):
                    j, k, w = cap[ci]
                    self.err(24, f"lines[{j}].words[{k}]", f"'{w[0]}' is not in the transcript")
            elif op == "delete":
                for ci in range(i1, i2):
                    j, k, w = cap[ci]
                    self.err(24, f"lines[{j}].words[{k}]", f"'{w[0]}' is not in the transcript")
        missing = len(tw) - shown
        if missing > max(3, 0.1 * len(tw)):
            self.wrn(24, "lines", f"captions show {shown} of {len(tw)} spoken words; every spoken word appears as it's spoken")

    # -- rules 22, 25, 26 ----------------------------------------------------
    def _effective_font(self, style: str) -> str | None:
        p = self.plan.get(f"font_{style}")
        if p:
            return p
        fp = self._brand_path(nc.brand_font, style)
        return str(fp) if fp else None

    def _rows(self, words: list) -> int | None:
        W = self.size[0]
        scale = W / 1080.0
        px = int(round(float(self._cfg("render.captions.font_px", 92)) * scale))
        box = 960 * scale
        fr, fi = self._effective_font("regular"), self._effective_font("italic")
        fonts = {False: self._font(fr, px) if fr else None, True: self._font(fi, px) if fi else None}
        if fonts[False] is None:
            return None
        rows, rw = 1, 0.0
        for w in words:
            f = fonts[bool(len(w) > 2 and w[2])] or fonts[False]
            ww = f.getlength(w[0]) + 26 * scale
            if rw + ww > box and rw > 0:
                rows += 1
                rw = 0.0
            rw += ww
        return rows

    def check_layout(self) -> None:
        W, H = self.size
        top = float(self._cfg("render.safe_area.top_fraction", 0.12)) * H
        bottom = H - float(self._cfg("render.safe_area.bottom_fraction", 0.10)) * H
        max_rows = int(self._cfg("render.captions.max_rows", 2))
        row_h = 124 * H / 1920.0
        cy = float(self.plan.get("caption_y", float(self._cfg("render.captions.default_y", 1420)) * H / 1920.0))
        for j, ln in enumerate(self.lines):
            rows = self._rows(ln["words"])
            if rows is None:
                continue
            if rows > max_rows:
                self.err(22, f"lines[{j}]", f"wraps to {rows} rows (max {max_rows}); split it into shorter lines")
            y0, y1 = cy - rows * row_h / 2, cy + rows * row_h / 2
            if y0 < top or y1 > bottom:
                self.err(25, f"lines[{j}]", f"caption block {y0:.0f}-{y1:.0f} px is outside the safe area ({top:.0f}-{bottom:.0f} px)")
            self._faces_vs_caption(j, ln, y0, y1)
        hook = self.plan.get("hook")
        if isinstance(hook, dict) and "y" in hook:
            half = float(self._cfg("render.captions.font_px", 92)) * H / 1920.0 * 0.6
            hy = float(hook["y"])
            if hy - half < top or hy + half > bottom:
                self.err(25, "hook.y", f"{hy:g} px puts the hook text outside the safe area ({top:.0f}-{bottom:.0f} px)")

    def _faces_vs_caption(self, j: int, ln: dict, y0: float, y1: float) -> None:
        W, H = self.size
        t0, t1 = float(ln["words"][0][1]), float(ln["end"])
        cx0, cx1 = (W - 960 * W / 1080) / 2, (W + 960 * W / 1080) / 2
        for i, s in enumerate(self.shots):
            if float(s["t1"]) <= t0 or float(s["t0"]) >= t1 or not s.get("faces"):
                continue
            size = None
            if s.get("kind", "image") == "image":
                size = self._image_size(s["src"]) if os.path.isabs(s["src"]) else None
                if size and s.get("crop"):
                    l, t, r, b = s["crop"]
                    size = (max(1, r - l), max(1, b - t))
            elif isinstance(self.analysis, dict):
                for c in self.analysis.get("clips") or []:
                    if s["src"] in (c.get("path"), c.get("prepared_path")):
                        size = tuple(c["size"])
            if not size:
                continue
            sw, sh = size
            z = s.get("z", [1.02, 1.14])
            k = max(W / sw, H / sh) * (z[0] + z[1]) / 2
            fx, fy = s.get("focus", [0.5, 0.5])
            for fb in s["faces"]:
                x0 = (fb[0] - fx) * sw * k + W / 2
                x1 = (fb[0] + fb[2] - fx) * sw * k + W / 2
                fy0 = (fb[1] - fy) * sh * k + H / 2
                fy1 = (fb[1] + fb[3] - fy) * sh * k + H / 2
                if x0 < cx1 and cx0 < x1 and fy0 < y1 and y0 < fy1:
                    self.wrn(26, f"lines[{j}]", f"caption block covers a face in shots[{i}]; move caption_y or reframe")
                    return

    # -- rule 27 -----------------------------------------------------------
    def check_claims(self) -> None:
        for h in claims_scan.scan_plan(self.plan):
            msg = f'{"banned claim" if h.severity == "fail" else "check wording"} "{h.label}": "{h.match}"'
            if h.suggestion:
                msg += f' (try: "{h.suggestion}")'
            (self.err if h.severity == "fail" else self.wrn)(27, h.where, msg)

    # -- rules 28-30 ----------------------------------------------------------
    def check_safety(self) -> None:
        P = self.plan
        for i, s in enumerate(self.shots):
            if s.get("people") is True and s.get("consent") is not True:
                self.err(28, f"shots[{i}]", "shows people without consent: true (blur them or use another shot)")
        m = P.get("music")
        if self.v2:
            if not isinstance(m, dict):
                self.err(29, "music", "missing: a v2 plan records its music source and license")
            elif m["source"] not in ("natural", "pad") and not (m.get("license") or "").strip():
                self.err(29, "music.license", f"empty for source '{m['source']}'; record where the license comes from")
        ai = P.get("ai") or {}
        gen = [i for i, s in enumerate(self.shots) if s.get("ai_generated")]
        if (ai.get("people") or ai.get("scenes") or gen) and not ai.get("label_required"):
            why = "ai.people/ai.scenes" if (ai.get("people") or ai.get("scenes")) else f"shots{gen} are ai_generated"
            self.err(30, "ai.label_required", f"must be true: {why} (Instagram's AI label)")

    # -- rules 31, 32 ---------------------------------------------------------
    def check_endcard(self) -> None:
        if not isinstance(self.ec, dict):
            return
        t = float(self.ec["t"])
        if not (0 < t < self.D):
            self.err(31, "endcard.t", f"{t:g} is not inside the reel (0, {self.D:g})")
            return
        hold = self.D - t
        lo = float(self._cfg("render.endcard.min_hold_s", 3.5))
        hi = float(self._cfg("render.endcard.max_hold_s", 5.0))
        if hold < lo - TILE_TOL:
            self.wrn(32, "endcard.t", f"end card holds {hold:.2f} s, less than {lo:g} s")
        elif hold > hi + TILE_TOL:
            self.wrn(32, "endcard.t", f"end card holds {hold:.2f} s, more than {hi:g} s")
        if not any(abs(float(s["t0"]) - t) <= TILE_TOL for s in self.shots):
            self.wrn(32, "endcard.t", f"{t:g} s is not on a shot boundary")

    # -- rule 33 -----------------------------------------------------------
    def check_leaks(self) -> None:
        for i, (t, d, strength) in enumerate(self.plan.get("leaks") or []):
            if t + d > self.D + TILE_TOL:
                self.wrn(33, f"leaks[{i}]", f"runs to {t + d:g} s, past the end ({self.D:g} s)")
            if strength > 0.6:
                self.wrn(33, f"leaks[{i}]", f"strength {strength:g} is above 0.6 (strong leaks wash out the picture)")

    # -- rule 34 -----------------------------------------------------------
    def check_hook(self) -> None:
        hook = self.plan.get("hook")
        if isinstance(hook, dict):
            t1 = float(hook.get("t1", 2.0))
            if t1 > self.D:
                self.err(34, "hook.t1", f"{t1:g} is after the reel ends ({self.D:g} s)")
        elif self.v2:
            self.wrn(34, "hook", "no hook text: the hook should be on screen from frame 0 (sound-off viewing)")

    # -- rule 35 -----------------------------------------------------------
    def check_nat(self) -> None:
        for i, n in enumerate(self.plan.get("nat") or []):
            t, dur, start = float(n["t"]), float(n["dur"]), float(n["start"])
            if t + dur > self.D + TILE_TOL:
                self.wrn(35, f"nat[{i}]", f"burst runs to {t + dur:g} s, past the reel end ({self.D:g} s)")
            info = self._clip_info(n["src"]) if os.path.isabs(n["src"]) else None
            if info:
                if info.get("has_audio") is False:
                    self.wrn(35, f"nat[{i}].src", "the clip has no audio")
                if info.get("duration") and start + dur > info["duration"] + TILE_TOL:
                    self.wrn(35, f"nat[{i}]", f"clip time {start:g}+{dur:g} s runs past the clip's end ({info['duration']:.2f} s)")

    # -- rule 36 -----------------------------------------------------------
    def check_formats(self) -> None:
        fm = self.plan.get("formats")
        if not isinstance(fm, dict):
            return
        lo, hi = self._cfg("render.length_s.reach_cut", [8, 12])

        def inside(where: str, t: float) -> None:
            if not (0 <= t <= self.D):
                self.err(36, where, f"{t:g} s is outside the reel (0-{self.D:g} s)")

        rc = fm.get("reach_cut")
        if isinstance(rc, dict):
            t0, t1 = float(rc["t0"]), float(rc["t1"])
            inside("formats.reach_cut.t0", t0)
            inside("formats.reach_cut.t1", t1)
            if not (lo - TILE_TOL <= t1 - t0 <= hi + TILE_TOL):
                self.err(36, "formats.reach_cut", f"{t1 - t0:.2f} s long; a reach cut runs {lo:g}-{hi:g} s")
        for i, st in enumerate(fm.get("story") or []):
            inside(f"formats.story[{i}].t", float(st["t"]))
        for i, c in enumerate(fm.get("carousel") or []):
            if "t" in c:
                inside(f"formats.carousel[{i}].t", float(c["t"]))
        if isinstance(fm.get("cover"), dict):
            inside("formats.cover.t", float(fm["cover"]["t"]))

    # -- rule 37 -----------------------------------------------------------
    def check_output_spec(self) -> None:
        fps = float(self._cfg("render.fps", 30))
        size = list(self._cfg("render.size", [1080, 1920]))
        if self.fps != fps:
            self.wrn(37, "fps", f"{self.fps:g}; the main reel is {fps:g} fps")
        if list(self.size) != size:
            self.wrn(37, "size", f"{self.size[0]}x{self.size[1]}; the main reel is {size[0]}x{size[1]}")

    # -- rule 38 -----------------------------------------------------------
    def check_prefs(self) -> None:
        if not self.prefs:
            return
        p = self.prefs
        trs = [s.get("tr", "cut") for s in self.shots]

        def limit(key: str, value: float, what: str, more: bool = True) -> None:
            if key in p and isinstance(p[key], (int, float)):
                bad = value > p[key] if more else value < p[key]
                if bad:
                    self.wrn(38, "prefs", f"{what} {value:g} breaks the feedback preference {key} = {p[key]:g}")

        limit("max_whips", trs.count("whip"), "whips")
        limit("max_flashes", trs.count("flash"), "flashes")
        limit("max_leaks", len(self.plan.get("leaks") or []), "light leaks")
        limit("max_leak_strength", max([lk[2] for lk in self.plan.get("leaks") or []] or [0]), "leak strength")
        limit("max_duration", self.D, "duration")
        limit("min_duration", self.D, "duration", more=False)
        limit("max_shot_seconds", max(float(s["t1"]) - float(s["t0"]) for s in self.shots), "longest shot (s)")
        limit("min_shot_seconds", min(float(s["t1"]) - float(s["t0"]) for s in self.shots), "shortest shot (s)", more=False)
        limit("max_caption_chars", max([len(" ".join(w[0] for w in ln["words"])) for ln in self.lines] or [0]),
              "longest caption line (characters)")
        gold = max([sum(1 for w in ln["words"] if len(w) > 2 and w[2]) for ln in self.lines] or [0])
        limit("max_gold_words", gold, "gold words in a line")


def load_prefs(path: str | os.PathLike) -> dict:
    """Numeric limits from a --prefs file: {"max_whips": 1} or {"limits": {...}} (prefs.py limits --json)."""
    data = nc.read_json(Path(path).expanduser().resolve(), "prefs file")
    if isinstance(data, dict) and isinstance(data.get("limits"), dict):
        data = data["limits"]
    if not isinstance(data, dict):
        raise nc.UserError(f"prefs file {path}: expected a JSON object of limits such as {{\"max_whips\": 1}}")
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def validate(plan: Any, analysis: Any = None, prefs: dict | None = None,
             plan_path: Path | None = None) -> list[Issue]:
    """Validate a plan dict (and optional analysis dict). Returns the issues; never raises on bad data."""
    return Checker(plan, analysis, prefs, plan_path).run()


def main(argv: list[str] | None = None) -> int:
    ap = nc.ArgParser(prog="validate_plan.py", description="Validate a plan.json before rendering (docs/CONTRACTS.md section 5).")
    ap.add_argument("plan", metavar="PLAN_JSON")
    ap.add_argument("analysis", nargs="?", metavar="ANALYSIS_JSON", help="default: analysis.json next to the plan")
    ap.add_argument("--prefs", metavar="FILE", help="preference limits, e.g. {\"max_whips\": 1}")
    ap.add_argument("--strict", action="store_true", help="warnings fail too")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    plan_path = Path(args.plan).expanduser().resolve()
    plan = nc.read_json(plan_path, "plan")
    analysis_path = None
    if args.analysis:
        analysis_path = Path(args.analysis).expanduser().resolve()
    elif (plan_path.parent / "analysis.json").is_file():
        analysis_path = plan_path.parent / "analysis.json"
    analysis = nc.read_json(analysis_path, "analysis") if analysis_path else None
    prefs = load_prefs(args.prefs) if args.prefs else None

    issues = validate(plan, analysis, prefs, plan_path)
    errors = [i for i in issues if i.level == "ERROR"]
    warns = [i for i in issues if i.level == "WARN"]
    for i in warns:
        nc.warn(i.line())
    for i in errors:
        nc.error_line(i.line())
    failed = bool(errors) or (args.strict and bool(warns))
    n_shots = len(plan.get("shots") or []) if isinstance(plan, dict) else 0
    duration = plan.get("duration") if isinstance(plan, dict) else None
    if args.json:
        nc.print_json({
            "ok": not failed, "plan": str(plan_path), "analysis": str(analysis_path) if analysis_path else None,
            "shots": n_shots, "duration": duration,
            "errors": [i.as_dict() for i in errors], "warnings": [i.as_dict() for i in warns],
        })
    elif failed:
        print(f"FAILED: {len(errors)} error(s), {len(warns)} warning(s)" + (" (--strict)" if not errors else ""))
    else:
        print(f"OK: {n_shots} shots, {duration:g} s, {len(warns)} warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    nc.run_cli(main)
