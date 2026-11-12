#!/usr/bin/env python3
"""Analyze a reel's raw material.

Usage:
    analyze.py RAW_DIR WORK_DIR [--voice FILE] [--music FILE] [--master FILE]
               [--script FILE] [--no-transcribe] [--pad-seconds S] [--json]

Reads RAW_DIR recursively (Drive layout: photos/, clips/, voiceover.*, music.*),
never modifies it, and writes into WORK_DIR:

  master.wav           48 kHz stereo: voice ducked over music (+ ~7.5 s music outro,
                       max 60 s), a loudness-normalized single track, the clips' own
                       sound (clips-only folders), or the offline pad (no audio at all)
  pad.wav              offline music pad, only when the folder has no audio
  analysis.json        schemas/analysis.schema.json (schema_version 2)
  contact_photos.jpg   numbered photo thumbnails P0, P1, ...
  contact_clips.jpg    clip frames about every second, labelled "C<k> @<t>s"
  media/               upright JPG copies (HEIC/HEIF/WEBP, EXIF-rotated photos)

See docs/CONTRACTS.md sections 2, 3 and 9.
"""
from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numa_common as nc  # noqa: E402
import fix_transcript as ft  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
CLIP_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac"}
CONVERT_EXT = {".heic", ".heif", ".webp"}          # always converted to an upright JPG copy
SYSTEM_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "icon\r", "__macosx"}

# Audio roles from file (and folder) names, matched against name tokens.
VOICE_EXACT = {"vo", "vox"}
VOICE_PREFIX = ("voice", "narrat", "memo", "speech", "spoken", "recording")
MUSIC_EXACT = {"bgm"}
MUSIC_PREFIX = ("music", "song", "track", "beat", "soundtrack", "instrumental")
MASTER_EXACT = {"master", "mix", "mixed", "combined", "mixdown"}

SAMPLE_RATE = 48000
WHISPER_MODEL = "small.en"
CONTACT_CELL = (240, 300)       # thumbnail box in a contact sheet
CONTACT_COLS = 6
CLIP_FRAMES_MAX = 30            # contact frames per clip (about one per second up to this)
CLIP_AUDIO_MIN_DB = -45.0       # quieter clip sound is not usable natural sound
MUSIC_BED_LU = -4.0             # music level under the voice before ducking (LU relative to target)
PAD_BPM = 80.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
class Notes:
    """Collects degradations: printed as WARN lines and kept for analysis.json `warnings`."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def warn(self, msg: str) -> None:
        nc.warn(msg)
        if msg not in self.items:
            self.items.append(msg)


def natural_key(text: str) -> list:
    """'img10' sorts after 'img2'; case-insensitive, then exact text as tie-break."""
    parts = re.split(r"(\d+)", text.lower())
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts] + [(2, 0, text)]


def name_tokens(text: str) -> list[str]:
    """'VoiceMemo_02 final' -> ['voice', 'memo', '02', 'final']."""
    return [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text)]


def _tokens_role(tokens: Sequence[str]) -> str | None:
    voice = any(t in VOICE_EXACT or t.startswith(VOICE_PREFIX) for t in tokens)
    music = any(t in MUSIC_EXACT or t.startswith(MUSIC_PREFIX) for t in tokens)
    if voice and music:
        return "master"
    if voice:
        return "voice"
    if music:
        return "music"
    if any(t in MASTER_EXACT for t in tokens):
        return "master"
    return None


def guess_role(path: Path, raw: Path | None = None) -> tuple[str | None, str]:
    """Role of an audio file from its name, else its folder names: (voice|music|master|None, reason).

    A name holding both voice and music words (e.g. voiceover_and_music.mp3) or a
    mix/master word is a combined master track."""
    role = _tokens_role(name_tokens(path.stem))
    if role:
        return role, f"file name '{path.name}'"
    if raw is not None:
        try:
            parents = path.parent.relative_to(raw).parts
        except ValueError:
            parents = ()
        for folder in reversed(parents):
            role = _tokens_role(name_tokens(folder))
            if role:
                return role, f"folder name '{folder}'"
    return None, f"name '{path.name}' gives no role"


def is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") or part.lower() in SYSTEM_NAMES or part.startswith("~$") for part in rel.parts)


def scan_raw(raw: Path, notes: Notes) -> dict[str, list[Path]]:
    """Classify RAW recursively by extension (case-insensitive); hidden/system files skipped."""
    if not raw.exists():
        raise nc.UserError(f"raw folder not found: {raw}")
    if not raw.is_dir():
        raise nc.UserError(f"raw folder is not a folder: {raw}")
    found: dict[str, list[Path]] = {"photos": [], "clips": [], "audio": [], "other": []}
    files = [p for p in raw.rglob("*") if p.is_file() and not is_hidden(p.relative_to(raw))]
    for p in sorted(files, key=lambda q: natural_key(q.relative_to(raw).as_posix())):
        ext = p.suffix.lower()
        kind = ("photos" if ext in IMAGE_EXT else "clips" if ext in CLIP_EXT
                else "audio" if ext in AUDIO_EXT else "other")
        if kind != "other" and p.stat().st_size == 0:
            notes.warn(f"{p.relative_to(raw)}: empty file, skipped")
            continue
        found[kind].append(p.resolve())
    return found


def assign_roles(audio_files: Sequence[Path], raw: Path, voice: Path | None = None, music: Path | None = None,
                 master: Path | None = None, notes: Notes | None = None) -> dict:
    """Pick the voice, music and master files. Deterministic rules, in order:

    1. --master overrides everything (one combined track); --voice/--music set those roles.
    2. A file whose name says both voice and music (or mix/master) is the master
       (a finished combined track wins over separate files).
    3. Otherwise the first voice-named and first music-named files (sorted order).
    4. Files with no role in their name fill a missing role: the only audio file
       becomes the master; next to a music file it is the voice; next to a voice
       file it is the music.
    Extra files are ignored with a WARN. Returns {voice, music, master, roles[]}."""
    notes = notes or Notes()
    roles: list[dict] = []
    chosen: dict[str, Path | None] = {"voice": None, "music": None, "master": None}

    def note(path: Path, role: str, reason: str) -> None:
        roles.append({"path": str(path), "role": role, "reason": reason})

    if master or voice or music:
        for role, p in (("master", master), ("voice", voice), ("music", music)):
            if p:
                chosen[role] = p
                note(p, role, "command-line override")
        if master and (voice or music):
            notes.warn("--master given: --voice/--music are ignored (the master is used as one combined track)")
            chosen["voice"] = chosen["music"] = None
        used = {p for p in chosen.values() if p}
        for p in audio_files:
            if p not in used:
                note(p, "ignored", "a role was set on the command line")
        return {**chosen, "roles": roles}

    guessed = [(p, *guess_role(p, raw)) for p in audio_files]
    by_role: dict[str | None, list[tuple[Path, str]]] = {}
    for p, role, why in guessed:
        by_role.setdefault(role, []).append((p, why))
    if by_role.get("master"):
        p, why = by_role["master"][0]
        chosen["master"] = p
        note(p, "master", f"{why} says voice and music in one track")
    else:
        for role in ("voice", "music"):
            if by_role.get(role):
                p, why = by_role[role][0]
                chosen[role] = p
                note(p, role, why)
        unknown = list(by_role.get(None, []))
        if unknown:
            if not chosen["voice"] and not chosen["music"]:
                p, why = unknown.pop(0)
                chosen["master"] = p
                note(p, "master", f"{why}; the only unnamed audio file is used as one combined track")
            elif not chosen["voice"]:
                p, why = unknown.pop(0)
                chosen["voice"] = p
                note(p, "voice", f"{why}; it fills the missing voice role next to the music file")
            elif not chosen["music"]:
                p, why = unknown.pop(0)
                chosen["music"] = p
                note(p, "music", f"{why}; it fills the missing music role next to the voice file")
    used = {p for p in chosen.values() if p}
    for p, role, why in guessed:
        if p not in used:
            note(p, "ignored", f"{why}; another file already has the {role or 'remaining'} role")
            notes.warn(f"audio file ignored: {p.name} ({role or 'no role in its name'}; use --voice/--music/--master to choose)")
    return {**chosen, "roles": roles}


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
def decode_f32(path: str | Path, sr: int, *, seconds: float | None = None, loop: bool = False):
    """Decode any audio/video file to mono float32 at `sr` via ffmpeg (no temp file)."""
    import numpy as np
    cmd = [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr)]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-f", "f32le", "-"]
    proc = nc.run(cmd, what=f"ffmpeg decode {Path(path).name}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def measure_loudness(path: str | Path, prefilter: str = "") -> dict:
    """EBU R128 measurement via ffmpeg loudnorm (first pass): input_i, input_tp, input_lra, input_thresh, target_offset."""
    cfg = loudness_cfg()
    chain = (prefilter + "," if prefilter else "") + (
        f"loudnorm=I={cfg['i']}:TP={cfg['tp']}:LRA={cfg['lra']}:print_format=json")
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af", chain,
                   "-f", "null", "-"], what="ffmpeg loudness")
    text = proc.stderr.decode("utf-8", "replace")
    start, end = text.rfind("{"), text.rfind("}")
    if start < 0 or end < start:
        raise nc.UserError(f"cannot measure loudness of {path}")
    data = json.loads(text[start:end + 1])
    out = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            v = float(data.get(k))
        except (TypeError, ValueError):
            v = float("-inf")
        out[k] = v
    return out


def loudness_cfg() -> dict:
    lc = nc.config_value("render.loudness", {}) or {}
    return {"i": float(lc.get("integrated_lufs", -15)), "tp": float(lc.get("true_peak_db", -1.5)),
            "lra": float(lc.get("lra", 9))}


def normalize_to(src: str | Path, dst: str | Path, *, prefilter: str = "", seconds: float | None = None,
                 notes: Notes | None = None) -> None:
    """Two-pass loudnorm (linear) of src into dst: 48 kHz stereo 16-bit WAV at the
    config loudness target (render.loudness)."""
    cfg = loudness_cfg()
    m = measure_loudness(src, prefilter)
    base = [nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(src), "-vn"]
    tail = (["-t", f"{seconds:.3f}"] if seconds else []) + ["-ar", str(SAMPLE_RATE), "-ac", "2",
                                                            "-c:a", "pcm_s16le", str(dst)]
    if not math.isfinite(m["input_i"]) or m["input_i"] < -70:
        if notes:
            notes.warn(f"{Path(src).name}: the audio is silent; not normalized")
        chain = prefilter or "anull"
    else:
        chain = (prefilter + "," if prefilter else "") + (
            f"loudnorm=I={cfg['i']}:TP={cfg['tp']}:LRA={cfg['lra']}:measured_I={m['input_i']:.2f}"
            f":measured_TP={m['input_tp']:.2f}:measured_LRA={m['input_lra']:.2f}"
            f":measured_thresh={m['input_thresh']:.2f}:offset={m['target_offset']:.2f}:linear=true")
    if seconds:
        chain += f",apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f}"  # exactly `seconds` long
    nc.run(base + ["-af", chain + f",aresample={SAMPLE_RATE}"] + tail, what="ffmpeg normalize")


def _gain_to(path: Path, target: float) -> float:
    m = measure_loudness(path)
    if not math.isfinite(m["input_i"]) or m["input_i"] < -70:
        return 0.0
    return max(-40.0, min(30.0, target - m["input_i"]))


def outro_seconds() -> float:
    return float(nc.config_value("render.outro_music_only_s.default", 7.5) or 7.5)


def max_reel_seconds() -> float:
    rng = nc.config_value("render.length_s.main_reel", [15, 60]) or [15, 60]
    return float(rng[1])


def mix_voice_music(voice: Path, music: Path, dst: Path, notes: Notes) -> float:
    """Voice over music with sidechain ducking (music drops under speech, comes up for
    the outro). Length = voice + outro (config, ~7.5 s), capped at 60 s; the music
    loops when it is shorter. Returns the length."""
    vdur = nc.media_duration(voice)
    cap = max_reel_seconds()
    total = min(vdur + outro_seconds(), cap)
    if vdur > cap:
        notes.warn(f"voiceover is {vdur:.1f} s: the reel is capped at {cap:.0f} s, so the voice is cut")
    target = loudness_cfg()["i"]
    gv = _gain_to(voice, target - 1.0)
    gm = _gain_to(music, target - 1.0 + MUSIC_BED_LU)
    fade = min(1.5, total / 4)
    fmt = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    graph = (
        f"[0:a]{fmt},volume={gv:.2f}dB,apad=whole_dur={total:.3f},atrim=0:{total:.3f},asplit=2[vkey][vmix];"
        f"[1:a]{fmt},volume={gm:.2f}dB,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[mus];"
        f"[mus][vkey]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350:makeup=1[duck];"
        f"[duck][vmix]amix=inputs=2:normalize=0:duration=first,atrim=0:{total:.3f},"
        f"afade=t=out:st={total - fade:.3f}:d={fade:.3f}[mix]")
    with tempfile.TemporaryDirectory(prefix="numa_mix_") as tmp:
        raw_mix = Path(tmp) / "mix.wav"
        nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(voice),
                "-stream_loop", "-1", "-i", str(music), "-filter_complex", graph, "-map", "[mix]",
                "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_f32le", "-t", f"{total:.3f}", str(raw_mix)],
               what="ffmpeg voice+music mix")
        normalize_to(raw_mix, dst, seconds=total, notes=notes)
    return total


def concat_clip_audio(clips: Sequence[dict], dst: Path, notes: Notes) -> float:
    """The clips' own sound, in clip order, as one normalized track (max 60 s)."""
    cap = max_reel_seconds()
    with tempfile.TemporaryDirectory(prefix="numa_clipaudio_") as tmp:
        joined = Path(tmp) / "clips.wav"
        args: list[str] = []
        for c in clips:
            args += ["-i", c["path"]]
        fmt = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
        parts = "".join(f"[{i}:a]{fmt}[a{i}];" for i in range(len(clips)))
        graph = parts + "".join(f"[a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=0:a=1[out]"
        nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", *args,
                "-filter_complex", graph, "-map", "[out]", "-t", f"{cap:.3f}", "-c:a", "pcm_f32le", str(joined)],
               what="ffmpeg clip audio")
        normalize_to(joined, dst, notes=notes)
    return nc.media_duration(dst)


def make_pad(dst: Path, seconds: float) -> None:
    """Deterministic offline music pad (last-resort fallback): a warm four-chord pad
    at 80 BPM with a soft pulse on every beat, 48 kHz stereo 16-bit."""
    import numpy as np
    sr = SAMPLE_RATE
    n = int(round(seconds * sr))
    t = np.arange(n, dtype=np.float64) / sr
    beat = 60.0 / PAD_BPM
    chords = [  # Cmaj7, Am7, Fmaj7, G6 (Hz), two bars each
        (130.81, 164.81, 196.00, 246.94), (110.00, 130.81, 164.81, 196.00),
        (87.31, 130.81, 174.61, 220.00), (98.00, 123.47, 146.83, 164.81)]
    bar = beat * 4
    idx = (t // (bar * 2)).astype(int) % len(chords)
    pad = np.zeros(n)
    for c, freqs in enumerate(chords):
        mask = idx == c
        if not mask.any():
            continue
        tm = t[mask]
        tone = sum(np.sin(2 * np.pi * f * tm) + 0.4 * np.sin(2 * np.pi * f * 2.003 * tm) for f in freqs)
        pad[mask] = tone / (len(freqs) * 1.4)
    local = np.mod(t, bar * 2)
    swell = np.minimum(1.0, local / 0.6) * np.minimum(1.0, (bar * 2 - local) / 0.3)
    phase = np.mod(t, beat)
    pulse = np.exp(-phase * 18.0) * np.sin(2 * np.pi * 55.0 * phase) * 0.9
    tick = np.exp(-phase * 90.0) * np.sin(2 * np.pi * 1800.0 * phase) * 0.12
    sig = 0.32 * pad * (0.6 + 0.4 * swell) + 0.45 * pulse + tick
    fade_in, fade_out = min(1.0, seconds / 4), min(2.5, seconds / 3)
    env = np.minimum(1.0, t / fade_in) * np.minimum(1.0, (seconds - t) / fade_out)
    sig = sig * np.clip(env, 0.0, 1.0)
    sig = sig / max(1e-9, float(np.max(np.abs(sig)))) * 0.6
    pcm = (sig * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1).tobytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo)


def track_beats(path: str | Path, seconds: float, *, loop: bool = False, notes: Notes | None = None):
    """librosa beat tracking -> (bpm or None, [beat times]). Deterministic."""
    import numpy as np
    sr = 22050
    y = decode_f32(path, sr, seconds=seconds, loop=loop)
    if y.size < sr or float(np.max(np.abs(y))) < 1e-4:
        if notes:
            notes.warn("no beats: the beat track is silent or shorter than 1 s")
        return None, []
    try:
        import librosa
    except Exception as e:  # noqa: BLE001 - optional at runtime: degrade, never fail
        if notes:
            notes.warn(f"beat tracking unavailable ({type(e).__name__}: {e}); bpm is null")
        return None, []
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    times = [round(float(x), 2) for x in librosa.frames_to_time(frames, sr=sr)]
    if bpm <= 0 or len(times) < 2:
        if notes:
            notes.warn("beat tracking found no beats; cut on the music by ear")
        return None, []
    return round(bpm, 2), times


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
NO_SPEECH_PROB = 0.6
MIN_AVG_LOGPROB = -1.0
HARD_MIN_AVG_LOGPROB = -1.5
MAX_COMPRESSION = 2.4
MIN_WORD_PROB = 0.1
MIN_MEAN_WORD_PROB = 0.35


def word_entry(text: str, start: float, end: float, p: float | None = None) -> dict:
    """One analysis word: appear = max(start, end - 0.4), end kept."""
    start = max(0.0, float(start))
    end = max(start, float(end))
    w = {"w": text, "appear": ft.appear_time(start, end), "end": round(end, 2), "start": round(start, 2)}
    if p is not None:
        w["p"] = round(min(1.0, max(0.0, float(p))), 3)
    return w


def filter_segments(segments: Sequence[Any]) -> list[dict]:
    """Words from Whisper segments, dropping what is not speech: segments judged
    non-speech (no_speech_prob high with low confidence, very low avg_logprob,
    repetitive text), words with no letters or digits (e.g. music symbols) and very
    unlikely words. A transcript whose words are, on average, unlikely is dropped."""
    words: list[dict] = []
    for s in segments:
        nsp = float(getattr(s, "no_speech_prob", 0.0) or 0.0)
        lp = float(getattr(s, "avg_logprob", 0.0) or 0.0)
        cr = float(getattr(s, "compression_ratio", 0.0) or 0.0)
        if (nsp > NO_SPEECH_PROB and lp < MIN_AVG_LOGPROB) or lp < HARD_MIN_AVG_LOGPROB or cr > MAX_COMPRESSION:
            continue
        for w in getattr(s, "words", None) or []:
            text = (w.word or "").strip()
            if not any(ch.isalnum() for ch in text):
                continue
            prob = float(getattr(w, "probability", 1.0) or 0.0)
            if prob < MIN_WORD_PROB:
                continue
            words.append(word_entry(text, w.start, w.end, prob))
    if words and sum(w["p"] for w in words) / len(words) < MIN_MEAN_WORD_PROB:
        return []
    return words


def transcribe(path: str | Path, notes: Notes) -> list[dict] | None:
    """faster-whisper small.en int8, word timestamps, VAD filter, audio decoded to
    16 kHz float32 first. Returns words, or None when transcription failed (WARN)."""
    try:
        audio = decode_f32(path, 16000)
    except nc.UserError as e:
        notes.warn(f"transcription skipped: cannot decode {Path(path).name}: {e}")
        return None
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001 - missing or broken install degrades to no captions
        notes.warn(f"transcription unavailable (faster-whisper: {type(e).__name__}: {e}); the reel gets no captions "
                   "unless a script is given")
        return None
    try:
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            audio, language="en", beam_size=5, temperature=0.0, word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False, hallucination_silence_threshold=2.0)
        return filter_segments(list(segments))
    except Exception as e:  # noqa: BLE001 - a failed transcript never kills analyze (R24)
        detail = " ".join(str(e).split())
        notes.warn(f"transcription failed ({type(e).__name__}: {detail}); the reel gets no captions "
                   "unless a script is given")
        return None


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
def _register_heif() -> bool:
    try:
        from pillow_heif import register_heif_opener
    except Exception:  # noqa: BLE001
        return False
    register_heif_opener()
    return True


def image_metrics(im) -> tuple[float, float]:
    """(sharpness = variance of Laplacian on a 1080-wide grey copy, brightness = mean luma 0-1)."""
    import cv2
    import numpy as np
    g = im.convert("L")
    if g.width != 1080:
        g = g.resize((1080, max(1, round(g.height * 1080 / g.width))), resample=3)
    a = np.asarray(g, dtype=np.uint8)
    sharp = float(cv2.Laplacian(a, cv2.CV_64F).var())
    return round(sharp, 2), round(float(a.mean()) / 255.0, 4)


def _unique_name(media_dir: Path, stem: str, used: set[str]) -> Path:
    safe = re.sub(r"[^\w.-]+", "_", stem).strip("._") or "photo"
    name, k = f"{safe}.jpg", 1
    while name.lower() in used:
        k += 1
        name = f"{safe}_{k}.jpg"
    used.add(name.lower())
    return media_dir / name


def process_photo(path: Path, pid: str, media_dir: Path, used: set[str], notes: Notes) -> tuple[dict, Any] | None:
    """Analysis entry for one photo (+ the upright image for the contact sheet), or
    None (WARN) when unreadable. HEIC/HEIF/WEBP and EXIF-rotated photos get an
    upright JPG copy in WORK/media/ so every consumer sees the photo the right way up."""
    from PIL import Image, ImageOps
    ext = path.suffix.lower()
    if ext in (".heic", ".heif") and not _register_heif():
        notes.warn(f"{path.name}: HEIC support missing (pip install pillow-heif); photo skipped")
        return None
    try:
        with Image.open(path) as im:
            im.load()
            orientation = im.getexif().get(0x0112, 1) or 1
            upright = ImageOps.exif_transpose(im)
            mode = im.mode
    except Exception as e:  # noqa: BLE001 - unreadable photo: skip it, keep going
        notes.warn(f"{path.name}: unreadable image ({type(e).__name__}); skipped")
        return None
    entry: dict[str, Any] = {"id": pid, "path": str(path)}
    needs_copy = ext in CONVERT_EXT or orientation != 1 or mode not in ("RGB", "L", "RGBA", "LA", "P")
    if needs_copy:
        out = _unique_name(media_dir, path.stem, used)
        media_dir.mkdir(parents=True, exist_ok=True)
        rgb = upright.convert("RGBA") if upright.mode in ("P", "LA") else upright
        if rgb.mode == "RGBA":
            bg = Image.new("RGB", rgb.size, (0, 0, 0))
            bg.paste(rgb, mask=rgb.split()[3])
            rgb = bg
        rgb = rgb.convert("RGB")
        rgb.save(out, "JPEG", quality=95)
        entry["path"] = str(out)
        entry["orig_path"] = str(path)
        upright = rgb
    entry["size"] = [int(upright.width), int(upright.height)]
    entry["sharpness"], entry["brightness"] = image_metrics(upright)
    return entry, upright


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------
def clip_sample_times(duration: float) -> tuple[float, float, int]:
    """(first time, step, count): about one frame per second from 0.5 s, at most CLIP_FRAMES_MAX."""
    first = 0.5 if duration > 1.0 else 0.0
    span = max(0.0, duration - first - 0.05)
    step = max(1.0, span / CLIP_FRAMES_MAX)
    count = max(1, min(CLIP_FRAMES_MAX, int(span // step) + 1))
    return first, step, count


def extract_frames(path: str, duration: float, tmp: Path, cid: str) -> list[tuple[float, Path]]:
    first, step, count = clip_sample_times(duration)
    pattern = tmp / f"{cid}_%03d.jpg"
    # the first frame at or after each sample time (exact, unlike the fps filter's rounding)
    sel = (f"select='gte(t\\,{first:.3f})*(isnan(prev_selected_t)+gt(floor((t-{first:.3f})/{step:.4f})\\,"
           f"floor((prev_selected_t-{first:.3f})/{step:.4f})))'")
    nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", path, "-an",
            "-vf", f"{sel},scale=540:-2", "-fps_mode", "vfr", "-frames:v", str(count), "-q:v", "3", str(pattern)],
           what=f"ffmpeg frames {Path(path).name}")
    frames = sorted(tmp.glob(f"{cid}_*.jpg"))
    return [(round(first + k * step, 1), f) for k, f in enumerate(frames)]


def clip_shake(path: str, duration: float) -> float | None:
    """Camera shake: mean deviation (% of frame width) of the frame-to-frame motion
    path from its 0.5 s moving average, sampled at 10 fps on a 160 px copy."""
    import cv2
    import numpy as np
    w = 160
    proc = nc.run([nc.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-an",
                   "-t", f"{min(duration, 60.0):.3f}", "-vf", f"fps=10,scale={w}:-2,format=gray",
                   "-f", "rawvideo", "-"], what="ffmpeg shake")
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    info = nc.media_info(path)
    vw, vh = info.get("width") or w, info.get("height") or w
    h = int(round(vh * w / vw / 2)) * 2
    if h <= 0 or data.size < w * h * 3:
        return None
    frames = data[: data.size // (w * h) * (w * h)].reshape(-1, h, w).astype(np.float32)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    path_xy = [np.zeros(2)]
    for a, b in zip(frames[:-1], frames[1:]):
        (dx, dy), _ = cv2.phaseCorrelate(a, b, win)
        path_xy.append(path_xy[-1] + np.array([dx, dy]))
    traj = np.array(path_xy)
    k = 5
    if len(traj) <= k:
        return 0.0
    kernel = np.ones(k) / k
    smooth = np.stack([np.convolve(np.pad(traj[:, i], (k // 2, k // 2), mode="edge"), kernel, mode="valid")
                       for i in range(2)], axis=1)
    dev = np.linalg.norm(traj - smooth, axis=1)
    return round(float(dev.mean()) / w * 100.0, 3)


def clip_audio_info(cid: str, path: str) -> dict | None:
    """{id, peaks (clip time), mean_db} when the clip's own sound is usable, else None."""
    import numpy as np
    try:
        y = decode_f32(path, 16000)
    except nc.UserError:
        return None
    if y.size < 1600:
        return None
    mean_db = 20 * math.log10(float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) + 1e-9)
    if mean_db < CLIP_AUDIO_MIN_DB:
        return None
    hop = 800  # 50 ms
    fr = y[: y.size // hop * hop].reshape(-1, hop).astype(np.float64)
    db = 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-9)
    thresh = max(mean_db + 6.0, -30.0)
    cand = [i for i in range(1, len(db) - 1) if db[i] >= thresh and db[i] >= db[i - 1] and db[i] >= db[i + 1]]
    cand.sort(key=lambda i: (-db[i], i))
    peaks: list[int] = []
    for i in cand:
        if all(abs(i - j) * 0.05 >= 1.0 for j in peaks):
            peaks.append(i)
        if len(peaks) == 5:
            break
    return {"id": cid, "peaks": sorted(round(i * 0.05, 2) for i in peaks), "mean_db": round(mean_db, 1)}


def process_clip(path: Path, cid: str, tmp: Path, notes: Notes) -> tuple[dict, list] | None:
    """Analysis entry for one clip (+ contact frames), or None (WARN) when unreadable."""
    import cv2
    import numpy as np
    from PIL import Image
    try:
        info = nc.media_info(path)
    except nc.UserError:
        notes.warn(f"{path.name}: unreadable video; skipped")
        return None
    dur = info.get("duration") or 0.0
    if not info.get("has_video") or not info.get("width") or dur <= 0:
        notes.warn(f"{path.name}: no video stream or no duration; skipped")
        return None
    entry: dict[str, Any] = {"id": cid, "path": str(path), "duration": round(float(dur), 2),
                             "has_audio": bool(info.get("has_audio")), "fps": round(float(info.get("fps") or 0.0), 3),
                             "size": [int(info["width"]), int(info["height"])]}
    if info.get("rotation"):
        entry["rotation"] = float(info["rotation"])
    try:
        frames = extract_frames(str(path), float(dur), tmp, cid)
    except nc.UserError:
        notes.warn(f"{path.name}: cannot read frames; skipped")
        return None
    if not frames:
        notes.warn(f"{path.name}: no decodable frames; skipped")
        return None
    sheet_items, sharp, bright = [], [], []
    for t, f in frames:
        with Image.open(f) as im:
            rgb = im.convert("RGB")
        a = np.asarray(rgb.convert("L"), dtype=np.uint8)
        sharp.append(float(cv2.Laplacian(a, cv2.CV_64F).var()))
        bright.append(float(a.mean()) / 255.0)
        sheet_items.append((rgb, f"{cid} @{t:.1f}s"))
    entry["sharpness"] = round(float(np.median(sharp)), 2)
    entry["brightness"] = round(float(np.mean(bright)), 4)
    try:
        shake = clip_shake(str(path), float(dur))
    except nc.UserError:
        shake = None
    if shake is not None:
        entry["shake"] = shake
    return entry, sheet_items


# ---------------------------------------------------------------------------
# Contact sheets
# ---------------------------------------------------------------------------
def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(nc.FONTS_DIR / "LiberationSerif-Regular.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(items: Sequence[tuple[Any, str]], out: Path) -> Path | None:
    """Grid of labelled thumbnails (6 per row). Removes a stale sheet when there are no items."""
    from PIL import Image, ImageDraw, ImageOps
    if not items:
        if out.exists():
            out.unlink()
        return None
    cw, ch = CONTACT_CELL
    label_h = 30
    font = _font(20)
    cols = min(CONTACT_COLS, len(items))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cw + 10) + 10, rows * (ch + label_h + 10) + 10), (24, 22, 20))
    draw = ImageDraw.Draw(sheet)
    for i, (im, label) in enumerate(items):
        x = 10 + (i % cols) * (cw + 10)
        y = 10 + (i // cols) * (ch + label_h + 10)
        thumb = ImageOps.contain(im.convert("RGB"), (cw, ch))
        sheet.paste(thumb, (x + (cw - thumb.width) // 2, y + (ch - thumb.height) // 2))
        text = label
        while draw.textlength(text, font=font) > cw and len(text) > 4:
            text = text[:-2] + "…"
        draw.text((x + 2, y + ch + 4), text, font=font, fill=(255, 226, 160))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def _resolve_override(value: str | None, flag: str) -> Path | None:
    if not value:
        return None
    p = Path(value).expanduser().resolve()
    if not p.is_file():
        raise nc.UserError(f"{flag} file not found: {p}")
    return p


def analyze(raw: Path, work: Path, *, voice: Path | None = None, music: Path | None = None,
            master: Path | None = None, script: Sequence[str] | None = None, transcribe_audio: bool = True,
            pad_seconds: float = 30.0) -> dict:
    """Run the whole analysis; writes WORK outputs and returns the analysis dict."""
    notes = Notes()
    raw, work = raw.resolve(), work.resolve()
    found = scan_raw(raw, notes)
    if not (found["photos"] or found["clips"] or found["audio"]):
        extra = f" ({len(found['other'])} other file(s) ignored)" if found["other"] else ""
        raise nc.UserError(f"no photos, clips or audio in {raw}{extra}: download the Drive day folder into raw/ first")
    work.mkdir(parents=True, exist_ok=True)
    media_dir = work / "media"

    # -- visuals
    photos, photo_imgs, used_names = [], [], set()
    for p in found["photos"]:
        res = process_photo(p, f"P{len(photos)}", media_dir, used_names, notes)
        if res:
            photos.append(res[0])
            photo_imgs.append((res[1], f"{res[0]['id']} {p.name}"))
    clips, clip_imgs = [], []
    with tempfile.TemporaryDirectory(prefix="numa_frames_") as tmp:
        for p in found["clips"]:
            res = process_clip(p, f"C{len(clips)}", Path(tmp), notes)
            if res:
                clips.append(res[0])
                clip_imgs.extend(res[1])
        sheet_photos = contact_sheet(photo_imgs, work / "contact_photos.jpg")
        sheet_clips = contact_sheet(clip_imgs, work / "contact_clips.jpg")
    if not photos and not clips:
        notes.warn(f"no usable photos or clips in {raw}: the Director's fallback is the bundled brand photos "
                   f"({nc.BRAND_PHOTOS_DIR})")

    clip_audio = []
    for c in clips:
        if c["has_audio"]:
            ca = clip_audio_info(c["id"], c["path"])
            if ca:
                clip_audio.append(ca)

    # -- audio
    readable_audio = []
    for a in found["audio"]:
        try:
            info = nc.media_info(a)
        except nc.UserError:
            notes.warn(f"{a.name}: unreadable audio; skipped")
            continue
        if not info.get("has_audio") or not info.get("duration"):
            notes.warn(f"{a.name}: no audio stream; skipped")
            continue
        readable_audio.append(a)
    roles = assign_roles(readable_audio, raw, voice, music, master, notes)
    v, m, mst = roles["voice"], roles["music"], roles["master"]
    master_wav = work / "master.wav"
    pad_wav = work / "pad.wav"
    audio: dict[str, Any] = {"voice": None, "music": None, "master": None}
    beat_src, beat_loop = None, False
    transcribe_src = None
    source = "none"
    if pad_wav.exists():
        pad_wav.unlink()
    if mst:
        normalize_to(mst, master_wav, notes=notes)
        audio.update(combined=True)
        beat_src, transcribe_src, source = master_wav, mst, "combined"
    elif v and m:
        mix_voice_music(v, m, master_wav, notes)
        audio.update(voice=str(v), music=str(m), combined=False)
        beat_src, beat_loop, transcribe_src, source = m, True, v, "voice+music"
    elif v:
        normalize_to(v, master_wav, notes=notes)
        audio.update(voice=str(v), combined=False)
        beat_src, transcribe_src, source = master_wav, v, "voice"
        notes.warn("no music file: master.wav is the voiceover alone (the Director picks music)")
    elif m:
        normalize_to(m, master_wav, notes=notes)
        audio.update(music=str(m), combined=False)
        beat_src, source = m, "music"
    elif clip_audio:
        usable = [c for c in clips if c["id"] in {ca["id"] for ca in clip_audio}]
        concat_clip_audio(usable, master_wav, notes)
        audio.update(combined=False)
        beat_src, transcribe_src, source = master_wav, master_wav, "clips"
        notes.warn("no voiceover or music file: master.wav is the clips' own sound")
    elif pad_seconds > 0:
        make_pad(pad_wav, pad_seconds)
        normalize_to(pad_wav, master_wav, notes=notes)
        audio.update(music=str(pad_wav), generated_pad=True, combined=False)
        beat_src, source = pad_wav, "pad"
        notes.warn(f"no audio in the folder: generated an offline {pad_seconds:g} s music pad (last-resort fallback; "
                   "the Director should find folder, Library or generated music first)")
    else:
        if master_wav.exists():
            master_wav.unlink()
        notes.warn("no audio in the folder and --pad-seconds 0: no master.wav; voice_present is false "
                   "(the Director's music fallbacks apply)")
    if mst:
        audio["master_source"] = str(mst)
    duration = 0.0
    if source != "none":
        audio["master"] = str(master_wav)
        duration = round(nc.media_duration(master_wav), 2)
    audio["source"] = source
    audio["roles"] = roles["roles"]
    if clip_audio:
        audio["clip_audio"] = clip_audio

    # -- beats
    bpm, beats = (None, [])
    if beat_src is not None and duration > 0:
        bpm, beats = track_beats(beat_src, duration, loop=beat_loop, notes=notes)

    # -- words
    words: list[dict] = []
    transcribed_ok = False
    if transcribe_src is not None and transcribe_audio:
        res = transcribe(transcribe_src, notes)
        if res is not None:
            words, transcribed_ok = res, True
    elif transcribe_src is not None:
        nc.info("transcription skipped (--no-transcribe)")
    voice_present = bool(v) or (transcribed_ok and bool(words))
    if source == "combined" and transcribed_ok and not words:
        notes.warn("no speech found in the combined track: treated as music only (no captions)")

    analysis: dict[str, Any] = {
        "schema_version": nc.ANALYSIS_SCHEMA_VERSION,
        "duration": duration,
        "bpm": bpm,
        "beats": beats,
        "words": words,
        "transcript": ft.join_words(words),
        "voice_present": voice_present,
        "audio": audio,
        "photos": photos,
        "clips": clips,
        "corrections": [],
        "contact_sheets": {"photos": str(sheet_photos) if sheet_photos else None,
                           "clips": str(sheet_clips) if sheet_clips else None},
    }
    # -- corrections (brand fixes; script alignment or captions from the script)
    allow_script = bool(v) or source in ("combined", "clips")
    ft.correct(analysis, script, allow_script_timing=allow_script)
    analysis["warnings"] = list(dict.fromkeys(list(analysis.get("warnings") or []) + notes.items))
    nc.validate_against("analysis", analysis, "analysis.json")
    nc.write_json(work / "analysis.json", analysis)
    return analysis


def build_parser() -> nc.ArgParser:
    ap = nc.ArgParser(prog="analyze.py", description="Analyze a reel's raw folder: audio mix, transcript, beats, "
                                                     "media inventory and contact sheets.")
    ap.add_argument("raw", metavar="RAW_DIR", help="the job's raw/ folder (searched recursively)")
    ap.add_argument("work", metavar="WORK_DIR", help="the job's work/ folder (created)")
    ap.add_argument("--voice", metavar="FILE", help="use this file as the voiceover")
    ap.add_argument("--music", metavar="FILE", help="use this file as the music")
    ap.add_argument("--master", metavar="FILE", help="use this one file (voice and music together) as the master")
    ap.add_argument("--script", metavar="FILE", help="plain text of the shoot card's voiceover script")
    ap.add_argument("--no-transcribe", action="store_true", help="skip speech-to-text")
    ap.add_argument("--pad-seconds", type=float, default=30.0, metavar="S",
                    help="length of the offline pad when the folder has no audio (0 = none; default 30)")
    ap.add_argument("--json", action="store_true", help="print one JSON report on stdout")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.pad_seconds < 0 or args.pad_seconds > 180:
        raise nc.UsageError("--pad-seconds must be between 0 and 180")
    voice = _resolve_override(args.voice, "--voice")
    music = _resolve_override(args.music, "--music")
    master = _resolve_override(args.master, "--master")
    script = ft.read_script(args.script) if args.script else None
    work = Path(args.work).expanduser().resolve()
    a = analyze(Path(args.raw).expanduser(), work, voice=voice, music=music, master=master, script=script,
                transcribe_audio=not args.no_transcribe, pad_seconds=args.pad_seconds)
    report = {"analysis": str(work / "analysis.json"), "duration": a["duration"], "bpm": a["bpm"],
              "beats": len(a["beats"]), "voice_present": a["voice_present"], "words": len(a["words"]),
              "transcript": a["transcript"], "photos": len(a["photos"]), "clips": len(a["clips"]),
              "audio_source": a["audio"]["source"], "master": a["audio"]["master"],
              "corrections": len(a.get("corrections") or []), "warnings": a.get("warnings") or []}
    if args.json:
        nc.print_json(report)
        return 0
    print(f"analysis: {report['analysis']}")
    print(f"audio: {report['audio_source']}, duration {a['duration']:.2f} s, "
          f"bpm {a['bpm'] if a['bpm'] is not None else 'none'}, {len(a['beats'])} beats")
    print(f"photos: {len(a['photos'])}, clips: {len(a['clips'])}, voice: {'yes' if a['voice_present'] else 'no'}")
    print(f"transcript ({len(a['words'])} words, {report['corrections']} corrections): {a['transcript'] or '(none)'}")
    return 0


if __name__ == "__main__":
    nc.run_cli(main)
