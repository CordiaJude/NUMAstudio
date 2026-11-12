#!/usr/bin/env python3
"""Correct the voiceover transcript in analysis.json.

Usage:
    fix_transcript.py ANALYSIS_JSON [--script FILE] [--dry-run] [--json]

Order of fixes (spec p.6, transcript failure row):
  1. With --script (plain text of the shoot card's voiceover script), align the
     recognized words to the script and let the script win for spelling and
     punctuation. Timing is kept: only `words[].w` changes (a word the recognizer
     split in two, e.g. "Moby le" for "Mobile", is merged into one word that
     spans both timings).
  2. Apply brand.json `transcript_fixes` (e.g. "Moby" -> "Mobile") to the words
     the script did not confirm.
  3. When there is no transcript, or it has almost nothing in common with the
     script, the captions come from the script, timed to the voice activity in
     the audio (`words[].source` = "script").

Rewrites `words`, `transcript`, appends to `corrections` and `warnings`, validates
against schemas/analysis.schema.json and writes the file atomically.
Deterministic: the same input gives the same output.
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402

APPEAR_LEAD_S = 0.4          # caption appear = max(start, end - 0.4) (spec p.17)
GARBAGE_RATIO = 0.3          # below this similarity to the script the transcript may be unusable...
GARBAGE_MEAN_PROB = 0.5      # ...when the recognizer was also unsure on average...
GARBAGE_FEW_WORDS = 0.25     # ...or heard fewer words than this fraction of the script
SCRIPT_MISMATCH_WARNING = ("transcript differs from the shoot-card script (confident recognition kept; "
                           "the voiceover may be ad-libbed)")
WORD_SIMILARITY = 0.5        # misheard word vs script word: replace when this similar (or anchored by context)
MAX_BLOCK = 4                # longest mismatch run (words) the aligner rewrites
SCRIPT_FALLBACK_WARNING = "captions from the script, timed to the audio (transcript missing or unusable)"

_TOKEN_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)
_POSSESSIVE_RE = re.compile(r"^(.*?)(['’]s)$", re.I)


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------
def split_token(word: str) -> tuple[str, str, str]:
    """'"Moby,"' -> ('"', 'Moby', ',"'): leading punctuation, core, trailing punctuation."""
    m = _TOKEN_RE.match(word)
    if not m:
        return "", word, ""
    pre, core, post = m.groups()
    if not core:  # only punctuation
        return "", word, ""
    return pre, core, post


def norm(text: str) -> str:
    """Lowercase letters and digits only ("Don't," -> "dont")."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def appear_time(start: float, end: float) -> float:
    """Caption appear time: max(start, end - 0.4 s) (Whisper start times run early)."""
    return round(max(float(start), float(end) - APPEAR_LEAD_S), 2)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b), autojunk=False).ratio()


def join_words(words: Sequence[dict]) -> str:
    return " ".join(w["w"] for w in words)


# ---------------------------------------------------------------------------
# Brand fixes
# ---------------------------------------------------------------------------
def load_fixes(brand: dict | None = None) -> tuple[list[str], list[dict]]:
    """(protect phrases, fixes) from brand.json `transcript_fixes`."""
    brand = brand if brand is not None else nc.load_brand()
    tf = brand.get("transcript_fixes") or {}
    return list(tf.get("protect") or []), list(tf.get("fixes") or [])


def _protected_indices(words: Sequence[dict], protect: Sequence[str]) -> set[int]:
    keys = [norm(w["w"]) for w in words]
    out: set[int] = set()
    for phrase in protect:
        pk = [norm(p) for p in phrase.split() if norm(p)]
        if not pk:
            continue
        for i in range(len(keys) - len(pk) + 1):
            if keys[i:i + len(pk)] == pk:
                out.update(range(i, i + len(pk)))
    return out


def _variant_matches(core: str, variant: str, case_sensitive: bool) -> bool:
    return core == variant if case_sensitive else core.lower() == variant.lower()


def apply_brand_fixes(words: list[dict], protect: Sequence[str], fixes: Sequence[dict],
                      skip: set[int] | None = None) -> list[dict]:
    """Replace misheard brand words in place (whole word, punctuation and "'s" kept).

    Returns corrections [{index, from, to, reason: "brand_fix"}]. Indices in `skip`
    (confirmed by the script) and words inside a `protect` phrase are left alone."""
    skip = set(skip or ()) | _protected_indices(words, protect)
    corrections: list[dict] = []
    for i, word in enumerate(words):
        if i in skip:
            continue
        pre, core, post = split_token(word["w"])
        base, suffix = core, ""
        pm = _POSSESSIVE_RE.match(core)
        for fix in fixes:
            to = fix.get("to")
            if not to:
                continue
            cs = bool(fix.get("case_sensitive"))
            hit = None
            for variant in fix.get("variants") or []:
                if " " in variant.strip():
                    continue  # single-word variants only: timing is per word
                if _variant_matches(base, variant, cs):
                    hit = (to, "")
                    break
                if pm and _variant_matches(pm.group(1), variant, cs):
                    hit = (to, pm.group(2))
                    break
            if not hit:
                continue
            nxt = fix.get("next_words")
            if nxt:
                if i + 1 >= len(words):
                    continue
                following = norm(words[i + 1]["w"])
                if following not in {norm(n) for n in nxt}:
                    continue
            new = f"{pre}{hit[0]}{hit[1]}{post}"
            if new != word["w"]:
                corrections.append({"index": i, "from": word["w"], "to": new, "reason": "brand_fix"})
                word["w"] = new
            break
    return corrections


# ---------------------------------------------------------------------------
# Script alignment
# ---------------------------------------------------------------------------
_LABEL_RE = re.compile(r"^\s*(?:VO|V\.O\.|VOICEOVER|VOICE[- ]OVER|NARRATOR|SCRIPT)\s*[:\-–—]\s*", re.I)


def script_tokens(text: str) -> list[str]:
    """Words of a voiceover script: stage directions in [brackets] or (parentheses)
    and leading "VO:" / "Voiceover:" labels removed; punctuation kept on the words."""
    text = text.replace("﻿", "")
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    tokens: list[str] = []
    for line in text.splitlines():
        line = _LABEL_RE.sub("", line)
        tokens.extend(t for t in line.split() if norm(t))
    return tokens


def read_script(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.is_file():
        raise nc.UserError(f"script file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = p.read_text(encoding="latin-1")
    tokens = script_tokens(text)
    if not tokens:
        raise nc.UserError(f"script file has no words: {p}")
    return tokens


def script_ratio(words: Sequence[dict], tokens: Sequence[str]) -> float:
    """Similarity 0-1 of the transcript to the script (normalized word sequences)."""
    a = [norm(w["w"]) for w in words]
    b = [norm(t) for t in tokens]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _restyle(token: str, word: str) -> str:
    """The script token, keeping the recognizer's punctuation when the script has none."""
    if split_token(token)[2] or not split_token(word)[2]:
        return token
    return token + split_token(word)[2]


def align_to_script(words: Sequence[dict], tokens: Sequence[str]) -> tuple[list[dict], list[dict], set[int]]:
    """Align recognized words to script tokens (difflib on normalized words).

    Equal runs take the script's spelling/punctuation. Short mismatch runs are
    rewritten when they look misheard: 1:1 when similar or anchored between
    matching words, n:1 merges ("Moby le" -> "Mobile") and 1:n splits are folded
    into one word when the letters agree. Timing is never invented: a merged word
    keeps the first word's start/appear and the last word's end.
    Returns (new words, corrections, indices confirmed by the script)."""
    src = [dict(w) for w in words]
    a = [norm(w["w"]) for w in src]
    b = [norm(t) for t in tokens]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = sm.get_opcodes()
    out: list[dict] = []
    corrections: list[dict] = []
    confirmed: set[int] = set()

    def keep(w: dict) -> None:
        out.append(w)

    def change(w: dict, new_text: str, *, confirm: bool = True) -> None:
        if new_text != w["w"]:
            corrections.append({"index": len(out), "from": w["w"], "to": new_text, "reason": "script"})
            w = dict(w, w=new_text)
        if confirm:
            confirmed.add(len(out))
        out.append(w)

    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                change(src[i], _restyle(tokens[j], src[i]["w"]))
            continue
        if tag in ("delete", "insert"):
            # ad-libbed words stay as heard; script words that were not spoken get no caption
            for i in range(i1, i2):
                keep(src[i])
            continue
        n, m = i2 - i1, j2 - j1
        anchored = (k == 0 or ops[k - 1][0] == "equal") and (k == len(ops) - 1 or ops[k + 1][0] == "equal")
        heard = "".join(a[i1:i2])
        written = "".join(b[j1:j2])
        if n > MAX_BLOCK or m > MAX_BLOCK:
            for i in range(i1, i2):
                keep(src[i])
            continue
        if n == m:
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if similarity(src[i]["w"], tokens[j]) >= WORD_SIMILARITY or (anchored and n == 1):
                    change(src[i], _restyle(tokens[j], src[i]["w"]))
                else:
                    keep(src[i])
            continue
        if difflib.SequenceMatcher(None, heard, written, autojunk=False).ratio() < 0.6:
            for i in range(i1, i2):
                keep(src[i])
            continue
        if n > m:
            # the recognizer split words: group the heard words onto the script tokens
            groups = _group(a[i1:i2], b[j1:j2])
            for (g0, g1), j in zip(groups, range(j1, j2)):
                first, last = src[i1 + g0], src[i1 + g1 - 1]
                merged = dict(first, end=last["end"])
                if "p" in first:
                    merged["p"] = round(min(src[i1 + x].get("p", 1.0) for x in range(g0, g1)), 3)
                heard_text = " ".join(src[i1 + x]["w"] for x in range(g0, g1))
                new_text = _restyle(tokens[j], last["w"])
                corrections.append({"index": len(out), "from": heard_text, "to": new_text, "reason": "script"})
                confirmed.add(len(out))
                merged["w"] = new_text
                out.append(merged)
        else:
            # the recognizer joined words: keep one word per heard word, script text spread over them
            groups = _group(b[j1:j2], a[i1:i2])
            for (g0, g1), i in zip(groups, range(i1, i2)):
                change(src[i], " ".join(tokens[j1 + x] for x in range(g0, g1)))
    return out, corrections, confirmed


def _group(longer: Sequence[str], shorter: Sequence[str]) -> list[tuple[int, int]]:
    """Split `longer` (n items) into len(shorter) contiguous groups whose joined
    letters best match each item of `shorter` (character-length proportional)."""
    n, m = len(longer), len(shorter)
    targets = [max(1, len(s)) for s in shorter]
    total_t = sum(targets)
    lens = [max(1, len(x)) for x in longer]
    total_l = sum(lens)
    bounds = [0]
    acc_t = 0
    for g in range(m - 1):
        acc_t += targets[g]
        goal = acc_t / total_t * total_l
        lo = bounds[-1] + 1
        hi = n - (m - 1 - g)
        best, best_err = lo, float("inf")
        acc = sum(lens[:lo])
        for cut in range(lo, hi + 1):
            err = abs(acc - goal)
            if err < best_err:
                best, best_err = cut, err
            if cut < n:
                acc += lens[cut]
        bounds.append(best)
    bounds.append(n)
    return [(bounds[g], bounds[g + 1]) for g in range(m)]


# ---------------------------------------------------------------------------
# Captions from the script, timed to the audio
# ---------------------------------------------------------------------------
def _decode_16k(path: str | Path):
    import numpy as np
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                   "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], what="ffmpeg decode")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def energy_spans(audio, sr: int = 16000) -> list[tuple[float, float]]:
    """Voice-activity spans from frame energy (works on a dry voiceover)."""
    import numpy as np
    hop = int(sr * 0.03)
    if audio.size < hop:
        return []
    frames = audio[: audio.size // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) + 1e-9)
    if db.max() < -60:
        return []
    floor = float(np.percentile(db, 10))
    thresh = max(floor + 10.0, float(db.max()) - 35.0)
    active = db > thresh
    spans: list[list[float]] = []
    for idx in np.flatnonzero(active):
        t0, t1 = idx * 0.03, (idx + 1) * 0.03
        if spans and t0 - spans[-1][1] < 0.3:
            spans[-1][1] = t1
        else:
            spans.append([t0, t1])
    return [(round(s, 3), round(e, 3)) for s, e in spans if e - s >= 0.15]


def silero_spans(audio, sr: int = 16000) -> list[tuple[float, float]] | None:
    """Speech spans from faster-whisper's Silero VAD, or None when it is unavailable."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    try:
        ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    except Exception:  # noqa: BLE001 - VAD model missing or broken: fall back to energy
        return None
    return [(round(t["start"] / sr, 3), round(t["end"] / sr, 3)) for t in ts]


def speech_spans(analysis: dict) -> list[tuple[float, float]]:
    """Where the voice is in the reel's audio: the voiceover file by energy (it is dry),
    a combined track by Silero VAD (else frame energy). Without Silero the spans
    stop before the music outro so script captions never run into it."""
    audio = analysis.get("audio") or {}
    duration = float(analysis.get("duration") or 0.0)
    voice, master = audio.get("voice"), audio.get("master")
    spans: list[tuple[float, float]] | None = None
    exact = False
    try:
        if voice and Path(voice).is_file():
            data = _decode_16k(voice)
            spans = silero_spans(data)
            exact = True  # a dry voiceover: energy is reliable too
            spans = spans or energy_spans(data)
        elif master and Path(master).is_file():
            data = _decode_16k(master)
            spans = silero_spans(data)
            exact = spans is not None
            if spans is None:
                spans = energy_spans(data)
    except nc.UserError:
        spans = None
    outro = float(nc.config_value("render.outro_music_only_s.default", 7.5) or 7.5)
    has_music = bool(audio.get("music") or audio.get("combined") or audio.get("source") in ("combined", "clips"))
    limit = duration
    if not exact and has_music and duration > outro + 3:
        limit = duration - outro
    if duration > 0:
        spans = [(s, min(e, limit)) for s, e in (spans or []) if s < limit - 0.1]
    if not spans and limit > 0:
        spans = [(min(0.3, limit / 4), max(limit - 0.3, 0.5))]
    return spans or []


def words_from_script(tokens: Sequence[str], spans: Sequence[tuple[float, float]]) -> list[dict]:
    """Time script tokens across the speech spans, proportional to their length
    (sentence ends weigh a little more, like a pause)."""
    spans = [(float(s), float(e)) for s, e in spans if e > s]
    if not tokens or not spans:
        return []
    weights = [len(norm(t)) + 2 + (3 if t.rstrip("\"'”’)").endswith((".", "!", "?")) else 1 if t.endswith((",", ";", ":")) else 0)
               for t in tokens]
    total_w = float(sum(weights))
    total_t = sum(e - s for s, e in spans)

    def at(x: float) -> float:
        """Speech-time offset x -> absolute time."""
        for s, e in spans:
            if x <= e - s + 1e-9:
                return s + x
            x -= e - s
        return spans[-1][1]

    out: list[dict] = []
    acc = 0.0
    for tok, wt in zip(tokens, weights):
        t0 = at(acc / total_w * total_t)
        acc += wt
        t1 = at(acc / total_w * total_t)
        t1 = max(t1, t0 + 0.05)
        out.append({"w": tok, "appear": appear_time(t0, t1), "end": round(t1, 2), "start": round(t0, 2),
                    "source": "script"})
    return out


# ---------------------------------------------------------------------------
# The whole correction pass
# ---------------------------------------------------------------------------
def correct(analysis: dict, script: Sequence[str] | None = None, brand: dict | None = None,
            *, allow_script_timing: bool = True) -> dict:
    """Run the correction pass on an analysis dict (modified in place and returned).

    Returns the analysis with `words`, `transcript`, `corrections` (appended) and
    `warnings` (appended) updated. `allow_script_timing` False never replaces the
    transcript with script-timed words (used for music-only material)."""
    protect, fixes = load_fixes(brand)
    words = [dict(w) for w in analysis.get("words") or []]
    corrections: list[dict] = []
    warnings = list(analysis.get("warnings") or [])
    confirmed: set[int] = set()
    if script:
        ratio = script_ratio(words, script)
        probs = [float(w.get("p", 1.0)) for w in words]
        unsure = bool(probs) and sum(probs) / len(probs) < GARBAGE_MEAN_PROB
        few = len(words) < max(3, GARBAGE_FEW_WORDS * len(script))
        garbage = not words or (ratio < GARBAGE_RATIO and (unsure or few))
        if words and ratio < GARBAGE_RATIO and not garbage and SCRIPT_MISMATCH_WARNING not in warnings:
            nc.warn(SCRIPT_MISMATCH_WARNING)
            warnings.append(SCRIPT_MISMATCH_WARNING)
        if garbage and allow_script_timing:
            spans = speech_spans(analysis)
            new = words_from_script(script, spans)
            if new:
                if words:
                    corrections.append({"index": 0, "from": join_words(words)[:200], "to": join_words(new)[:200],
                                        "reason": "script"})
                words = new
                confirmed = set(range(len(words)))
                if SCRIPT_FALLBACK_WARNING not in warnings:
                    warnings.append(SCRIPT_FALLBACK_WARNING)
                analysis["voice_present"] = True  # captions exist, so the voice chain and captions apply
        elif words and ratio >= GARBAGE_RATIO:  # an unrelated script must not respell a kept transcript
            words, script_corr, confirmed = align_to_script(words, script)
            corrections.extend(script_corr)
    corrections.extend(apply_brand_fixes(words, protect, fixes, skip=confirmed))
    analysis["words"] = words
    analysis["transcript"] = join_words(words)
    analysis["corrections"] = list(analysis.get("corrections") or []) + corrections
    if warnings:
        analysis["warnings"] = warnings
    return analysis


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="fix_transcript.py",
                      description="Correct the transcript in analysis.json: shoot-card script first, "
                                  "then brand.json transcript_fixes; captions from the script when the "
                                  "transcript is missing or unusable.")
    ap.add_argument("analysis", metavar="ANALYSIS_JSON", help="work/analysis.json written by analyze.py")
    ap.add_argument("--script", metavar="FILE", help="plain text of the shoot card's voiceover script")
    ap.add_argument("--dry-run", action="store_true", help="print the corrections without writing")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    path = Path(args.analysis).resolve()
    analysis = nc.read_json(path, "analysis.json")
    if not isinstance(analysis, dict) or analysis.get("schema_version") != nc.ANALYSIS_SCHEMA_VERSION:
        raise nc.UserError(f"{path} is not a schema_version 2 analysis.json: re-run analyze.py on the job's raw/ folder")
    nc.validate_against("analysis", analysis, str(path))
    tokens = read_script(args.script) if args.script else None
    before = len(analysis.get("corrections") or [])
    audio = analysis.get("audio") or {}
    music_only = (not audio.get("voice") and not audio.get("combined") and audio.get("source") != "clips"
                  and not analysis.get("voice_present"))
    correct(analysis, tokens, allow_script_timing=not music_only)
    new = analysis["corrections"][before:]
    from_script = any(w.get("source") == "script" for w in analysis["words"])
    nc.validate_against("analysis", analysis, "corrected analysis")
    if not args.dry_run:
        nc.write_json(path, analysis)
    if args.json:
        nc.print_json({"analysis": str(path), "written": not args.dry_run, "corrections": new,
                       "words": len(analysis["words"]), "from_script": from_script,
                       "transcript": analysis["transcript"]})
        return 0
    for c in new:
        print(f'{c["reason"]}: word {c["index"]}: "{c["from"]}" -> "{c["to"]}"')
    verb = "would apply" if args.dry_run else "applied"
    print(f"{verb} {len(new)} correction(s); {len(analysis['words'])} words"
          + (" (captions from the script)" if from_script else ""))
    print(f"transcript: {analysis['transcript']}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
