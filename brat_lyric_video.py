#!/usr/bin/env python3
"""
=============================================================================
  BRAT LYRIC VIDEO GENERATOR
  Charli XCX "Brat" Album Aesthetic — Lyric Video Asset Pipeline
=============================================================================

  Creates synchronized lyric videos with the iconic Brat visual style:
    • Lime green background (#8ACE00)
    • Lowercase, compressed, lo-fi text
    • Gaussian blur + nearest-neighbor pixel degradation

  Two output modes:
    1. Full MP4 video (green bg + audio + synced text)
    2. NLE-ready PNG image sequence (transparent alpha) + FCPXML timeline
       for DaVinci Resolve / Final Cut Pro import

=============================================================================
  DEPENDENCIES — install via pip:
    pip install moviepy Pillow numpy

  SYSTEM REQUIREMENTS:
    • FFmpeg must be installed and available on PATH
      macOS:  brew install ffmpeg
    • Python 3.8+

  FONT CONFIGURATION:
    The script uses Arial by default. On macOS, Arial is located at:
      /Library/Fonts/Arial.ttf
      /Library/Fonts/Arial Narrow.ttf

    To change the font, modify the FONT_PATH constant below, e.g.:
      FONT_PATH = "/path/to/your/CustomFont.ttf"
=============================================================================

  USAGE:
    # Mode 1: Generate full MP4 video
    python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.srt --mode video

    # Mode 2: Generate PNG sequence + FCPXML for NLE import
    python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.lrc --mode nle

    # Mode 3: Generate both outputs
    python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.srt --mode both

  OPTIONS:
    --audio       Path to audio file (.mp3 or .wav)
    --lyrics      Path to lyric file (.srt or .lrc)
    --mode        Output mode: 'video', 'nle', or 'both' (default: both)
    --output      Output directory (default: ./brat_output)
    --fps         Video frame rate (default: 30)
    --font        Override font path
    --font-size   Override font size (default: auto-calculated)
=============================================================================
"""

import argparse
import os
import re
import sys

# Isolate models and caching into App Support for clean desktop distribution
os.environ["HF_HOME"] = os.path.expanduser("~/Library/Application Support/BratGenerator/cache/huggingface")
os.environ["TORCH_HOME"] = os.path.expanduser("~/Library/Application Support/BratGenerator/cache/torch")
os.environ["NUMBA_CACHE_DIR"] = os.path.expanduser("~/Library/Application Support/BratGenerator/cache/numba")

import math
import xml.etree.ElementTree as ET
import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# =============================================================================
# CONFIGURATION — Adjust these to taste
# =============================================================================

# Brat green — the exact hex from the album cover
BRAT_GREEN = (138, 206, 0)        # #8ACE00
BRAT_GREEN_HEX = "#8ACE00"

# Text color — pure black
TEXT_COLOR = (0, 0, 0)             # #000000

# Canvas resolution — vertical 9:16 for phone/stories/reels
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

# Font configuration
# On macOS, Arial ships at these paths. Change if needed.
FONT_PATH_CANDIDATES = [
    "/Library/Fonts/Arial Narrow.ttf",       # Preferred: Arial Narrow
    "/Library/Fonts/Arial.ttf",               # Fallback: standard Arial
    "/System/Library/Fonts/Helvetica.ttc",    # System fallback
    "/System/Library/Fonts/SFNSMono.ttf",     # Last resort
]

# Text styling
DEFAULT_FONT_SIZE = 90          # Base font size (px) — auto-adjusted for long lines
TEXT_VERTICAL_STRETCH = 1.10    # 110% vertical stretch to mimic Arial Narrow condensed look
MAX_TEXT_WIDTH_RATIO = 0.85     # Text occupies max 85% of canvas width
LINE_SPACING = 1.15             # Line height multiplier

# Lo-fi degradation effects
BLUR_RADIUS = 1.2               # Gaussian blur radius for the "compressed" look
DOWNSCALE_FACTOR = 0.4          # Downscale to 40% then upscale — creates pixel crunch
# Using NEAREST resampling on upscale introduces the blocky, aliased edges

# Video settings
DEFAULT_FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class LyricLine:
    """Represents a single timestamped line of lyrics."""
    start_time: float   # seconds
    end_time: float     # seconds
    text: str           # the lyric content (will be lowercased)

    def __post_init__(self):
        # Force lowercase — core to the Brat aesthetic
        self.text = self.text.strip().lower()


# =============================================================================
# LYRIC FILE PARSERS
# =============================================================================

def parse_srt(filepath: str) -> List[LyricLine]:
    """
    Parse an SRT subtitle file into LyricLine objects.

    SRT format:
        1
        00:00:01,500 --> 00:00:04,000
        hello world

        2
        00:00:05,000 --> 00:00:08,500
        another line
    """
    lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # Split into subtitle blocks (separated by blank lines)
    blocks = re.split(r"\n\s*\n", content)

    for block in blocks:
        block_lines = block.strip().split("\n")
        if len(block_lines) < 3:
            continue

        # Line 1: sequence number (ignored)
        # Line 2: timestamp range
        # Lines 3+: subtitle text
        timestamp_line = block_lines[1].strip()
        text = " ".join(line.strip() for line in block_lines[2:])

        # Parse timestamps: "00:00:01,500 --> 00:00:04,000"
        match = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            timestamp_line
        )
        if not match:
            print(f"  [WARN] Skipping malformed SRT timestamp: {timestamp_line}")
            continue

        g = match.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0

        if text.strip():
            lines.append(LyricLine(start_time=start, end_time=end, text=text))

    print(f"  [SRT] Parsed {len(lines)} lyric lines from {filepath}")
    return lines


def parse_lrc(filepath: str) -> List[LyricLine]:
    """
    Parse an LRC lyric file into LyricLine objects.

    LRC format:
        [00:12.50]hello world
        [00:15.75]another line

    Also handles metadata tags like [ti:Title], [ar:Artist], etc.
    Supports multiple timestamps per line: [00:12.50][00:30.00]repeated lyric
    """
    entries = []  # (start_time, text) tuples
    timestamp_pattern = re.compile(r"\[(\d{2}):(\d{2})[.:](\d{2,3})\]")
    metadata_pattern = re.compile(r"\[[a-zA-Z]{2}:.*\]")

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Skip metadata tags like [ti:Song Title]
            if metadata_pattern.match(raw_line) and not timestamp_pattern.match(raw_line):
                continue

            # Extract all timestamps from the line
            timestamps = timestamp_pattern.findall(raw_line)
            if not timestamps:
                continue

            # Text is everything after the last closing bracket
            text = timestamp_pattern.sub("", raw_line).strip()
            if not text:
                continue

            # Each timestamp maps to the same text
            for mm, ss, frac in timestamps:
                # Handle both 2-digit (hundredths) and 3-digit (milliseconds) fractions
                if len(frac) == 2:
                    frac_seconds = int(frac) / 100.0
                else:
                    frac_seconds = int(frac) / 1000.0

                start = int(mm) * 60 + int(ss) + frac_seconds
                entries.append((start, text))

    # Sort by start time
    entries.sort(key=lambda x: x[0])

    # Convert to LyricLines — end time is the start of the next line
    lines = []
    for i, (start, text) in enumerate(entries):
        if i + 1 < len(entries):
            end = entries[i + 1][0]
        else:
            # Last line: display for 4 seconds or until some reasonable end
            end = start + 4.0
        lines.append(LyricLine(start_time=start, end_time=end, text=text))

    print(f"  [LRC] Parsed {len(lines)} lyric lines from {filepath}")
    return lines


def parse_lyrics(filepath: str) -> List[LyricLine]:
    """Auto-detect format and parse the lyrics file."""
    ext = Path(filepath).suffix.lower()
    if ext == ".srt":
        return parse_srt(filepath)
    elif ext == ".lrc":
        return parse_lrc(filepath)
    else:
        raise ValueError(
            f"Unsupported lyric format: '{ext}'. Use .srt or .lrc files."
        )


# =============================================================================
# FONT RESOLUTION
# =============================================================================

def resolve_font(override_path: Optional[str] = None, size: int = DEFAULT_FONT_SIZE) -> ImageFont.FreeTypeFont:
    """
    Locate and load a TrueType font.
    Tries the override path first, then the candidate list.
    """
    candidates = [override_path] if override_path else []
    candidates.extend(FONT_PATH_CANDIDATES)

    for path in candidates:
        if path and os.path.isfile(path):
            print(f"  [FONT] Using: {path}")
            return ImageFont.truetype(path, size)

    # Ultimate fallback — Pillow's built-in bitmap font (ugly but functional)
    print("  [FONT] WARNING: No TrueType font found! Using Pillow default.")
    print("         Install Arial or set --font /path/to/font.ttf")
    return ImageFont.load_default()


# =============================================================================
# DYNAMIC SQUARE WRAPPING ALGORITHMS
# =============================================================================

def convert_to_accumulation_states(
    lyrics: List[LyricLine],
    font: ImageFont.FreeTypeFont,
    font_size: int
) -> List[LyricLine]:
    """
    Takes parsed LyricLines, converts them to word-level entries,
    groups words into stanzas, and generates word accumulation states
    formatted as JSON for precise coordinate rendering.
    """
    import random
    import hashlib
    import json
    
    # 1. Expand multi-word lines to word-level entries
    words = []
    for line in lyrics:
        split_words = line.text.split()
        if len(split_words) <= 1:
            words.append(line)
        else:
            duration = line.end_time - line.start_time
            word_duration = duration / len(split_words)
            for i, w in enumerate(split_words):
                w_start = line.start_time + i * word_duration
                w_end = w_start + word_duration
                words.append(LyricLine(start_time=w_start, end_time=w_end, text=w))

    # 2. Group sequential words into stanzas (8 or 10 words)
    stanzas = []
    i = 0
    while i < len(words):
        first_w = words[i]
        # Use stable seed based on first word's text and time
        seed_val = int(hashlib.md5(f"{first_w.text}_{first_w.start_time}".encode('utf-8')).hexdigest(), 16)
        rng = random.Random(seed_val)
        has_line4 = rng.random() < 0.30
        target_len = 10 if has_line4 else 8
        
        stanza_words = []
        while len(stanza_words) < target_len and i < len(words):
            w = words[i]
            if stanza_words:
                prev_w = stanza_words[-1]
                gap = w.start_time - prev_w.end_time
                if gap > 2.0:
                    break # end stanza early on silent gap
            stanza_words.append(w)
            i += 1
        stanzas.append(stanza_words)

    # 3. Create accumulation states as JSON strings
    states = []
    for stanza in stanzas:
        if not stanza:
            continue
            
        # Determine full Line 1 words to establish TARGET_WIDTH
        full_line1 = [w.text for w in stanza[0:min(3, len(stanza))]]
        
        # Word accumulation loops
        for k in range(1, len(stanza) + 1):
            active_lines = [
                [w.text for w in stanza[0:min(k, 3)]] if k >= 1 else [],
                [w.text for w in stanza[3:min(k, 5)]] if k >= 4 else [],
                [w.text for w in stanza[5:min(k, 8)]] if k >= 6 else [],
                [w.text for w in stanza[8:min(k, 10)]] if k >= 9 else []
            ]
            # Clean trailing empty lines
            while active_lines and not active_lines[-1]:
                active_lines.pop()
                
            state_data = {
                "active_lines": active_lines,
                "full_line1": full_line1
            }
            
            # Timing
            start = stanza[k-1].start_time
            if k < len(stanza):
                end = stanza[k].start_time
            else:
                end = stanza[k-1].end_time
                
            states.append(LyricLine(start_time=start, end_time=end, text=json.dumps(state_data)))
            
    return states


# =============================================================================
# TEXT RENDERING ENGINE — The Brat Aesthetic
# =============================================================================

def render_lyric_frame(
    text: str,
    font: ImageFont.FreeTypeFont,
    with_background: bool = True,
    font_size: int = DEFAULT_FONT_SIZE,
    font_path: Optional[str] = None,
) -> Image.Image:
    """
    Render a single lyric frame with coordinate-based justification and alignment.
    """
    import json
    
    # 1. Parse text (JSON layout or fallback)
    try:
        data = json.loads(text)
        active_lines = data["active_lines"]
        full_line1 = data["full_line1"]
    except Exception:
        # Fallback if text is not JSON (e.g. from live preview API inputs)
        lines = text.split('\n')
        active_lines = [line.split() for line in lines if line.strip()]
        full_line1 = active_lines[0] if active_lines else []

    if not active_lines or not any(active_lines):
        return render_blank_frame(with_background)

    # Calculate standard character spacing
    w_space = font.getlength(" ")
    bbox_std = font.getbbox("Mg")
    font_h = bbox_std[3] - bbox_std[1]
    line_step = int(font_h * LINE_SPACING)

    # 2. Calculate TARGET_WIDTH from full Line 1 (Words 1-3)
    def get_line_natural_width(word_list):
        if not word_list:
            return 0
        w_words = sum(font.getlength(w) for w in word_list)
        return w_words + w_space * (len(word_list) - 1)

    target_width = get_line_natural_width(full_line1)
    if target_width <= 0:
        target_width = 1

    # 3. Lay out words and collect draw tasks relative to (0, 0)
    draw_tasks = []
    for line_idx, line_words in enumerate(active_lines):
        if not line_words:
            continue
        y = line_idx * line_step
        
        # Line 1 & Line 3: standard space-separated
        if line_idx in (0, 2):
            cur_x = 0.0
            for w in line_words:
                draw_tasks.append((w, cur_x, y))
                cur_x += font.getlength(w) + w_space
                
        # Line 2 & Line 4: space-between layout justified to Line 1 width
        elif line_idx in (1, 3):
            if len(line_words) == 1:
                # Place Word 0 at left edge
                draw_tasks.append((line_words[0], 0.0, y))
            elif len(line_words) >= 2:
                # Word 0: Far Left
                draw_tasks.append((line_words[0], 0.0, y))
                # Word 1: Far Right (snapped to target_width)
                w1_w = font.getlength(line_words[1])
                x_pos = max(font.getlength(line_words[0]) + w_space, target_width - w1_w)
                draw_tasks.append((line_words[1], x_pos, y))

    if not draw_tasks:
        return render_blank_frame(with_background)

    # 4. Compute bounding box of active draw tasks
    min_x = min(t[1] for t in draw_tasks)
    max_x = max(t[1] + font.getlength(t[0]) for t in draw_tasks)
    min_y = min(t[2] for t in draw_tasks)
    max_y = max(t[2] + font_h for t in draw_tasks)

    block_w = max_x - min_x
    block_h = max_y - min_y

    # Center bounding box on canvas
    left_x = (CANVAS_WIDTH - block_w) // 2
    top_y = (CANVAS_HEIGHT - block_h) // 2

    # Draw on transparent canvas
    text_canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_canvas)
    line_color = TEXT_COLOR + (255,)

    for word_text, rx, ry in draw_tasks:
        draw_x = left_x + (rx - min_x)
        draw_y = top_y + (ry - min_y)
        draw.text((draw_x, draw_y), word_text, font=font, fill=line_color)

    # --- Step 2: Vertical stretch (110%) ---
    stretched_height = int(CANVAS_HEIGHT * TEXT_VERTICAL_STRETCH)
    text_canvas = text_canvas.resize(
        (CANVAS_WIDTH, stretched_height),
        Image.LANCZOS
    )
    crop_top = (stretched_height - CANVAS_HEIGHT) // 2
    text_canvas = text_canvas.crop((0, crop_top, CANVAS_WIDTH, crop_top + CANVAS_HEIGHT))

    # --- Step 3: Lo-fi pixel degradation ---
    small_w = max(1, int(CANVAS_WIDTH * DOWNSCALE_FACTOR))
    small_h = max(1, int(CANVAS_HEIGHT * DOWNSCALE_FACTOR))
    small = text_canvas.resize((small_w, small_h), Image.LANCZOS)
    text_canvas = small.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.NEAREST)

    # --- Step 4: Gaussian blur ---
    r, g, b, a = text_canvas.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = rgb.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
    a = a.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS * 0.5))
    text_canvas = Image.merge("RGBA", (*rgb.split(), a))

    # --- Step 5: Composite ---
    if with_background:
        bg = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BRAT_GREEN + (255,))
        bg.paste(text_canvas, (0, 0), text_canvas)
        return bg.convert("RGB")
    else:
        return text_canvas

def render_blank_frame(with_background: bool = True) -> Image.Image:
    """Render a blank frame (no lyrics visible) — just the green background or transparent."""
    if with_background:
        return Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BRAT_GREEN)
    else:
        return Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))


# =============================================================================
# MODE 1: FULL MP4 VIDEO GENERATION
# =============================================================================

import subprocess
import shutil

def isolate_vocals(audio_path: str, output_dir: str) -> str:
    """
    Isolates the vocal track from instrumentation using Demucs.
    """
    print("  [DEMUCS] Isolating vocals from audio track...")
    
    # Check if demucs is installed
    try:
        import demucs
    except ImportError:
        raise ImportError("demucs is not installed. Please run: pip install demucs")

    # Output directory for demucs
    demucs_out = os.path.join(output_dir, "demucs_sep")
    os.makedirs(demucs_out, exist_ok=True)

    # Run demucs command
    cmd = [
        sys.executable, "-m", "demucs",
        "-o", demucs_out,
        "--two-stems=vocals",
        audio_path
    ]
    
    print(f"  [DEMUCS] Running command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    # Locate isolated vocals path: demucs_sep/htdemucs/<track_name>/vocals.wav
    track_name = Path(audio_path).stem
    
    # Locate vocals file recursively
    import glob
    matches = glob.glob(os.path.join(demucs_out, "**", "vocals.wav"), recursive=True)
    if matches:
        vocals_path = matches[0]
        print(f"  [DEMUCS] Isolated vocals located at: {vocals_path}")
        return vocals_path
    else:
        raise FileNotFoundError("Demucs completed but vocals.wav was not found in output directory.")

def align_lyrics_with_whispermlx(vocals_path: str, lyrics: Optional[List[LyricLine]] = None) -> List[LyricLine]:
    """
    Performs transcription and word-level alignment using mlx-whisper (Apple Silicon optimized).
    """
    print("  [MLX-WHISPER] Running automated speech-to-text alignment pipeline...")
    
    try:
        import mlx_whisper
    except ImportError:
        raise ImportError("mlx-whisper is not installed. Please run: pip install mlx-whisper")

    # Load large-v3-turbo model from huggingface
    model_name = "mlx-community/whisper-large-v3-turbo"
    print(f"  [MLX-WHISPER] Loading Whisper model: {model_name}...")
    
    # Transcribe with word timestamps enabled
    print("  [MLX-WHISPER] Transcribing isolated vocal track...")
    result = mlx_whisper.transcribe(vocals_path, path_or_hf_repo=model_name, word_timestamps=True)
    print("  [MLX-WHISPER] Transcription complete.")
    
    # Extract all transcribed words with timestamps
    transcribed_words = []
    for seg in result.get("segments", []):
        for w_dict in seg.get("words", []):
            if "word" in w_dict and "start" in w_dict and "end" in w_dict:
                transcribed_words.append({
                    "word": w_dict["word"].strip(),
                    "start": w_dict["start"],
                    "end": w_dict["end"]
                })
                
    if not transcribed_words:
        raise ValueError("MLX-Whisper transcription succeeded but no word timestamps were generated.")
        
    # If no custom lyrics are provided, use transcribed words directly
    if not lyrics:
        print(f"  [MLX-WHISPER] Using transcribed lyrics ({len(transcribed_words)} words).")
        aligned_words = []
        for tw in transcribed_words:
            aligned_words.append(LyricLine(
                start_time=tw["start"],
                end_time=tw["end"],
                text=tw["word"]
            ))
        return aligned_words

    # If custom lyrics are provided, align them sequentially with transcribed word timestamps
    print(f"  [MLX-WHISPER] Aligning parsed lyric file ({len(lyrics)} lines) with Whisper timestamps...")
    
    # Flatten original lyrics into single words
    lyric_words = []
    for line in lyrics:
        for w in line.text.split():
            lyric_words.append(w)
            
    # Align sequentially
    aligned_words = []
    t_idx = 0
    for lw in lyric_words:
        clean_lw = re.sub(r'[^\w]', '', lw.lower())
        match_found = False
        
        # Search for a match in the neighborhood of transcribed words to handle sync
        search_limit = min(t_idx + 15, len(transcribed_words))
        for j in range(t_idx, search_limit):
            clean_tw = re.sub(r'[^\w]', '', transcribed_words[j]["word"].lower())
            if clean_lw == clean_tw or clean_lw in clean_tw or clean_tw in clean_lw:
                aligned_words.append(LyricLine(
                    start_time=transcribed_words[j]["start"],
                    end_time=transcribed_words[j]["end"],
                    text=lw
                ))
                t_idx = j + 1
                match_found = True
                break
                
        if not match_found:
            # Fallback interpolation if word doesn't match transcription (e.g. lyric vs vocal difference)
            if t_idx < len(transcribed_words):
                start = transcribed_words[t_idx]["start"]
                end = transcribed_words[t_idx]["end"]
            else:
                start = transcribed_words[-1]["end"] if transcribed_words else 0.0
                end = start + 0.3
            aligned_words.append(LyricLine(
                start_time=start,
                end_time=end,
                text=lw
            ))
            
    print(f"  [MLX-WHISPER] Aligned {len(aligned_words)} lyric words successfully.")
    return aligned_words


def generate_video(
    lyrics: List[LyricLine],
    audio_path: str,
    output_dir: str,
    font: ImageFont.FreeTypeFont,
    fps: int = DEFAULT_FPS,
    font_size: int = DEFAULT_FONT_SIZE,
    font_path: Optional[str] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
):
    """
    Generate a complete MP4 video with synced lyrics over Brat green background.
    Uses moviepy for audio/video multiplexing with ffmpeg backend.
    """
    # Import moviepy here so it's not required for NLE-only mode
    from moviepy import (
        ImageClip,
        AudioFileClip,
        CompositeVideoClip,
        concatenate_videoclips,
    )

    print("\n" + "=" * 60)
    print("  GENERATING MP4 VIDEO")
    print("=" * 60)

    # Convert incoming lyrics to dynamic word-level accumulation states
    lyrics = convert_to_accumulation_states(lyrics, font, font_size)

    output_path = os.path.join(output_dir, "brat_lyric_video.mp4")

    # Load audio to get total duration
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    print(f"  [AUDIO] Duration: {total_duration:.2f}s")

    # Pre-render all unique lyric frames as PIL images
    print("  [RENDER] Pre-rendering lyric frames...")
    frame_cache = {}
    blank_frame = render_blank_frame(with_background=True)
    blank_array = np.array(blank_frame)

    for i, lyric in enumerate(lyrics):
        if progress_callback:
            progress_callback(f"Step 3/4: Rendering Dynamic Layout ({i+1}/{len(lyrics)})...", float(i) / len(lyrics))
        if lyric.text not in frame_cache:
            img = render_lyric_frame(
                lyric.text, font, with_background=True,
                font_size=font_size, font_path=font_path
            )
            frame_cache[lyric.text] = np.array(img)
            print(f"    [{i+1}/{len(lyrics)}] \"{lyric.text[:50]}...\"" if len(lyric.text) > 50 else f"    [{i+1}/{len(lyrics)}] \"{lyric.text}\"")

    # Build video clips from pre-rendered frames
    print("  [VIDEO] Building clip sequence...")
    clips = []
    prev_end = 0.0

    for lyric in lyrics:
        # Insert blank gap before this lyric (if there's dead time)
        if lyric.start_time > prev_end + 0.01:
            gap_duration = lyric.start_time - prev_end
            gap_clip = (
                ImageClip(blank_array)
                .with_duration(gap_duration)
                .with_start(0)
            )
            clips.append(gap_clip)

        # The lyric frame
        duration = lyric.end_time - lyric.start_time
        if duration <= 0:
            continue

        lyric_clip = (
            ImageClip(frame_cache[lyric.text])
            .with_duration(duration)
            .with_start(0)
        )
        clips.append(lyric_clip)
        prev_end = lyric.end_time

    # Fill remaining time after last lyric with blank
    if prev_end < total_duration:
        trailing = (
            ImageClip(blank_array)
            .with_duration(total_duration - prev_end)
            .with_start(0)
        )
        clips.append(trailing)

    # Concatenate all clips into final video
    print("  [VIDEO] Concatenating clips...")
    video = concatenate_videoclips(clips, method="compose")
    # Force exact duration and constant frame rate to prevent drift
    print("  [EXPORT] Aligning audio & video durations to prevent drift...")
    audio = audio.with_duration(total_duration)
    video = video.with_duration(total_duration)
    video = video.with_audio(audio)

    if progress_callback:
        progress_callback("Step 4/4: Compiling Final Video...", 0.90)
    # Write to file
    print(f"  [EXPORT] Writing to {output_path}")
    print(f"           Resolution: {CANVAS_WIDTH}x{CANVAS_HEIGHT} @ {fps}fps")
    video.write_videofile(
        output_path,
        fps=fps,
        codec=VIDEO_CODEC,
        audio_codec=AUDIO_CODEC,
        ffmpeg_params=["-fps_mode", "cfr"], # Enforce Constant Frame Rate (CFR)
        threads=4,
        logger="bar",
    )

    print(f"\n  ✅ Video saved: {output_path}")
    return output_path
def generate_nle_assets(
    lyrics: List[LyricLine],
    audio_path: str,
    output_dir: str,
    font: ImageFont.FreeTypeFont,
    fps: int = DEFAULT_FPS,
    font_size: int = DEFAULT_FONT_SIZE,
    font_path: Optional[str] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
):
    """
    Generate a PNG image sequence (transparent alpha) and an FCPXML timeline file
    for importing into DaVinci Resolve, Final Cut Pro, or other NLEs.

    Output structure:
      output_dir/
        png_sequence/
          001_hello_world.png        ← transparent text frame
          002_another_line.png       ← ...
          000_blank.png              ← blank transparent frame
        brat_timeline.fcpxml         ← FCPXML for DaVinci Resolve / FCP
        brat_timeline.edl            ← CMX3600 EDL (simpler alternative)
    """
    print("\n" + "=" * 60)
    print("  GENERATING NLE ASSETS (PNG + FCPXML + EDL)")
    print("=" * 60)

    # Convert incoming lyrics to dynamic word-level accumulation states
    lyrics = convert_to_accumulation_states(lyrics, font, font_size)

    png_dir = os.path.join(output_dir, "png_sequence")
    os.makedirs(png_dir, exist_ok=True)

    # --- Render PNG sequence ---
    print("  [PNG] Rendering transparent lyric frames...")

    # Render blank frame
    blank_path = os.path.join(png_dir, "000_blank.png")
    blank_frame = render_blank_frame(with_background=False)
    blank_frame.save(blank_path, "PNG")

    png_paths = []
    for i, lyric in enumerate(lyrics):
        if progress_callback:
            progress_callback(f"Step 3/4: Rendering Dynamic Layout ({i+1}/{len(lyrics)})...", float(i) / len(lyrics))
        # Create a filename-safe version of the text
        safe_text = re.sub(r"[^a-z0-9]+", "_", lyric.text.lower())[:40].strip("_")
        filename = f"{i+1:03d}_{safe_text}.png"
        filepath = os.path.join(png_dir, filename)

        img = render_lyric_frame(
            lyric.text, font, with_background=False,
            font_size=font_size, font_path=font_path
        )
        img.save(filepath, "PNG")
        png_paths.append(filepath)
        print(f"    [{i+1}/{len(lyrics)}] {filename}")

    if progress_callback:
        progress_callback("Step 4/4: Compiling NLE XML Timeline...", 0.90)
    # --- Generate FCPXML timeline ---
    print("  [FCPXML] Building timeline...")
    fcpxml_path = _generate_fcpxml(lyrics, png_paths, blank_path, audio_path, output_dir, fps)

    # --- Generate EDL (simpler alternative) ---
    print("  [EDL] Building edit decision list...")
    edl_path = _generate_edl(lyrics, png_paths, output_dir, fps)

    print(f"\n  ✅ PNG sequence: {png_dir}/")
    print(f"  ✅ FCPXML:       {fcpxml_path}")
    print(f"  ✅ EDL:          {edl_path}")

    return png_dir, fcpxml_path, edl_path


def _frames_to_timecode(total_frames: int, fps: int) -> str:
    """Convert a frame count to SMPTE timecode HH:MM:SS:FF."""
    h = total_frames // (fps * 3600)
    remainder = total_frames % (fps * 3600)
    m = remainder // (fps * 60)
    remainder = remainder % (fps * 60)
    s = remainder // fps
    f = remainder % fps
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _seconds_to_frame_count(seconds: float, fps: int) -> int:
    """Convert seconds to frame count."""
    return int(round(seconds * fps))


def _generate_edl(
    lyrics: List[LyricLine],
    png_paths: List[str],
    output_dir: str,
    fps: int
) -> str:
    """
    Generate a CMX3600-format EDL for the lyric sequence.
    Each lyric line is one event with its source PNG as the reel.
    """
    edl_path = os.path.join(output_dir, "brat_timeline.edl")

    with open(edl_path, "w", encoding="utf-8") as f:
        f.write("TITLE: BRAT_LYRIC_VIDEO\n")
        f.write(f"FCM: NON-DROP FRAME\n\n")

        for i, (lyric, png_path) in enumerate(zip(lyrics, png_paths)):
            event_num = i + 1
            # Reel name: 8 chars max for CMX3600 compatibility
            reel = f"LYR{event_num:04d}"[:8]

            # Source timecodes (each PNG is treated as a still — 00:00:00:00 to duration)
            src_in = "00:00:00:00"
            duration_frames = _seconds_to_frame_count(lyric.end_time - lyric.start_time, fps)
            src_out = _frames_to_timecode(duration_frames, fps)

            # Record timecodes (position on the output timeline)
            rec_in = _frames_to_timecode(_seconds_to_frame_count(lyric.start_time, fps), fps)
            rec_out = _frames_to_timecode(_seconds_to_frame_count(lyric.end_time, fps), fps)

            # Event line: EVENT# REEL TRACK TRANSITION SRC_IN SRC_OUT REC_IN REC_OUT
            f.write(f"{event_num:03d}  {reel}  V     C        {src_in} {src_out} {rec_in} {rec_out}\n")
            # Comment with the actual lyric text and file path
            f.write(f"* FROM CLIP NAME: {os.path.basename(png_path)}\n")
            f.write(f"* LYRIC: {lyric.text.replace(chr(10), ' ')}\n")
            f.write(f"\n")

    return edl_path


def _generate_fcpxml(
    lyrics: List[LyricLine],
    png_paths: List[str],
    blank_path: str,
    audio_path: str,
    output_dir: str,
    fps: int,
) -> str:
    """
    Generate an FCPXML (version 1.9) timeline for DaVinci Resolve / Final Cut Pro.

    The timeline contains:
      - V1: PNG lyric frames placed at their synced timestamps
      - A1: The original audio file spanning the full duration
    """
    fcpxml_path = os.path.join(output_dir, "brat_timeline.fcpxml")

    # Calculate total duration from audio or last lyric
    if lyrics:
        total_duration_s = max(l.end_time for l in lyrics)
    else:
        total_duration_s = 0.0

    # FCPXML uses rational time: "numerator/denominator" e.g., "30000/1000s" = 30s
    def time_str(seconds: float) -> str:
        """Convert seconds to FCPXML rational time format."""
        # Use frame-accurate timing
        frames = int(round(seconds * fps))
        return f"{frames}/{fps}s"

    # Build XML tree
    root = ET.Element("fcpxml", version="1.9")

    # --- Resources ---
    resources = ET.SubElement(root, "resources")

    # Format resource (defines the video format)
    ET.SubElement(resources, "format", {
        "id": "r1",
        "name": f"FFVideoFormat{CANVAS_HEIGHT}p{fps}",
        "frameDuration": f"1/{fps}s",
        "width": str(CANVAS_WIDTH),
        "height": str(CANVAS_HEIGHT),
    })

    # Asset resources for each PNG
    for i, png_path in enumerate(png_paths):
        abs_path = os.path.abspath(png_path)
        asset = ET.SubElement(resources, "asset", {
            "id": f"asset_{i+1}",
            "name": os.path.basename(png_path),
            "src": f"file://{abs_path}",
            "start": "0s",
            "duration": "0s",
            "hasVideo": "1",
        })
        ET.SubElement(asset, "media-rep", {
            "kind": "original-media",
            "src": f"file://{abs_path}",
        })

    # Audio asset
    audio_abs = os.path.abspath(audio_path)
    ET.SubElement(resources, "asset", {
        "id": "audio_asset",
        "name": os.path.basename(audio_path),
        "src": f"file://{audio_abs}",
        "start": "0s",
        "duration": time_str(total_duration_s),
        "hasAudio": "1",
    })

    # --- Library / Event / Project ---
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Brat Lyric Video")
    project = ET.SubElement(event, "project", name="Brat Lyrics")

    # Sequence
    sequence = ET.SubElement(project, "sequence", {
        "format": "r1",
        "duration": time_str(total_duration_s),
        "tcStart": "0s",
        "tcFormat": "NDF",
    })

    spine = ET.SubElement(sequence, "spine")

    # Place each lyric PNG on the timeline
    prev_end = 0.0
    for i, (lyric, png_path) in enumerate(zip(lyrics, png_paths)):
        # Insert gap if there's dead time before this lyric
        if lyric.start_time > prev_end + (1.0 / fps):
            gap_duration = lyric.start_time - prev_end
            ET.SubElement(spine, "gap", {
                "name": f"Gap {i}",
                "offset": time_str(prev_end),
                "duration": time_str(gap_duration),
                "start": time_str(prev_end),
            })

        # Place the lyric clip
        clip_duration = lyric.end_time - lyric.start_time
        clip = ET.SubElement(spine, "clip", {
            "name": os.path.basename(png_path),
            "ref": f"asset_{i+1}",
            "offset": time_str(lyric.start_time),
            "duration": time_str(clip_duration),
            "start": "0s",
            "format": "r1",
        })
        # Add a note with the lyric text
        ET.SubElement(clip, "note").text = lyric.text

        prev_end = lyric.end_time

    # --- Write XML ---
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    with open(fcpxml_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

    return fcpxml_path


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🟢 BRAT LYRIC VIDEO GENERATOR — Charli XCX Aesthetic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate full MP4 video
  python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.srt --mode video

  # Generate PNG sequence + FCPXML for DaVinci Resolve
  python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.lrc --mode nle

  # Generate both outputs
  python brat_lyric_video.py --audio song.mp3 --lyrics lyrics.srt --mode both
        """,
    )
    parser.add_argument(
        "--audio", required=True,
        help="Path to audio file (.mp3 or .wav)"
    )
    parser.add_argument(
        "--lyrics", default=None,
        help="Path to timestamped lyrics file (.srt or .lrc) [Optional]"
    )
    parser.add_argument(
        "--mode", choices=["video", "nle", "both"], default="both",
        help="Output mode: 'video' (MP4), 'nle' (PNG+FCPXML), or 'both' (default: both)"
    )
    parser.add_argument(
        "--output", default="./brat_output",
        help="Output directory (default: ./brat_output)"
    )
    parser.add_argument(
        "--fps", type=int, default=DEFAULT_FPS,
        help=f"Video frame rate (default: {DEFAULT_FPS})"
    )
    parser.add_argument(
        "--font", default=None,
        help="Path to TrueType font file (default: auto-detect Arial)"
    )
    parser.add_argument(
        "--font-size", type=int, default=DEFAULT_FONT_SIZE,
        help=f"Font size in pixels (default: {DEFAULT_FONT_SIZE})"
    )
    parser.add_argument(
        "--no-align", action="store_true",
        help="Disable automatic WhisperX/Demucs alignment and use basic parser instead"
    )

    args = parser.parse_args()

    # --- Validate inputs ---
    if not os.path.isfile(args.audio):
        print(f"❌ Audio file not found: {args.audio}")
        sys.exit(1)

    if args.lyrics and not os.path.isfile(args.lyrics):
        print(f"❌ Lyrics file not found: {args.lyrics}")
        sys.exit(1)

    if args.no_align and not args.lyrics:
        print("❌ Cannot use --no-align without providing a --lyrics file.")
        sys.exit(1)

    # --- Setup ---
    print("\n" + "=" * 60)
    print("  🟢  BRAT LYRIC VIDEO GENERATOR")
    print("  Charli XCX Album Aesthetic")
    print("=" * 60)

    os.makedirs(args.output, exist_ok=True)
    print(f"\n  Output directory: {os.path.abspath(args.output)}")

    # Parse lyrics if provided
    lyrics = None
    if args.lyrics:
        print(f"\n  Parsing lyrics: {args.lyrics}")
        lyrics = parse_lyrics(args.lyrics)
        if not lyrics:
            print("❌ No lyric lines found! Check your lyrics file.")
            sys.exit(1)

    # Run Demucs vocal isolation & WhisperMLX phoneme alignment
    temp_dir = os.path.join(args.output, "alignment_temp")
    if not args.no_align:
        print("\n  [ALIGNMENT] Starting AI audio-lyrics alignment pipeline...")
        try:
            vocals_path = isolate_vocals(args.audio, temp_dir)
            lyrics = align_lyrics_with_whispermlx(vocals_path, lyrics)
        except Exception as e:
            print(f"  ⚠️  [ALIGNMENT] Alignment pipeline failed: {e}")
            if not lyrics:
                print("❌ No lyrics provided and automated transcription failed. Cannot proceed.")
                # Cleanup temp directory before exiting
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                sys.exit(1)
            else:
                print("                Falling back to basic lyric timestamp ingestion.")
    else:
        print("\n  [ALIGNMENT] Skipping AI alignment pipeline (--no-align).")

    # Load font
    print(f"\n  Loading font...")
    font = resolve_font(args.font, args.font_size)

    # Determine effective font path for re-loading at different sizes
    effective_font_path = args.font
    if not effective_font_path:
        for path in FONT_PATH_CANDIDATES:
            if os.path.isfile(path):
                effective_font_path = path
                break

    # --- Execute modes ---
    if args.mode in ("video", "both"):
        generate_video(
            lyrics, args.audio, args.output, font,
            fps=args.fps,
            font_size=args.font_size,
            font_path=effective_font_path,
        )

    if args.mode in ("nle", "both"):
        generate_nle_assets(
            lyrics, args.audio, args.output, font,
            fps=args.fps,
            font_size=args.font_size,
            font_path=effective_font_path,
        )

    # --- Cleanup ---
    if os.path.exists(temp_dir):
        print("\n  [CLEANUP] Cleaning up temporary isolated vocal files...")
        shutil.rmtree(temp_dir, ignore_errors=True)

    # --- Summary ---
    print("\n" + "=" * 60)
    print("  🟢  ALL DONE!")
    print("=" * 60)
    print(f"  Output: {os.path.abspath(args.output)}/")
    if args.mode in ("video", "both"):
        print(f"    📹  brat_lyric_video.mp4")
    if args.mode in ("nle", "both"):
        print(f"    🖼️   png_sequence/")
        print(f"    📋  brat_timeline.fcpxml  (DaVinci Resolve / FCP)")
        print(f"    📋  brat_timeline.edl     (CMX3600 universal)")
    print()
    print("  NLE IMPORT INSTRUCTIONS:")
    print("  ─────────────────────────")
    print("  DaVinci Resolve:")
    print("    File → Import → Timeline → select brat_timeline.fcpxml")
    print("    Then drag your audio onto the A1 track.")
    print()
    print("  Final Cut Pro:")
    print("    File → Import → XML → select brat_timeline.fcpxml")
    print()
    print("  Generic NLE (Premiere, etc.):")
    print("    Import brat_timeline.edl as a new sequence,")
    print("    then relink the PNG files from png_sequence/")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
