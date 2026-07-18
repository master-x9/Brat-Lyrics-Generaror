#!/usr/bin/env python3
"""
=============================================================================
  BRAT LYRIC VIDEO GENERATOR — Web UI
  Flask server wrapping the core brat_lyric_video.py engine
=============================================================================

  USAGE:
    python3 app.py
    Then open http://localhost:5000 in your browser.

  DEPENDENCIES:
    pip3 install flask moviepy Pillow numpy
=============================================================================
"""

import os
import sys
import json
import time
import uuid
import shutil
import zipfile
import threading
import traceback
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, render_template, request, jsonify,
    send_file, send_from_directory, url_for
)

# Import our core generator
from brat_lyric_video import (
    parse_lyrics, resolve_font, render_lyric_frame,
    generate_video, generate_nle_assets,
    BRAT_GREEN_HEX, DEFAULT_FONT_SIZE, DEFAULT_FPS,
    FONT_PATH_CANDIDATES, CANVAS_WIDTH, CANVAS_HEIGHT,
)

# =============================================================================
# Flask App Configuration
# =============================================================================

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["OUTPUT_FOLDER"] = os.path.join(os.path.dirname(__file__), "outputs")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

# In-memory job tracking
jobs = {}

ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
ALLOWED_LYRIC_EXT = {".srt", ".lrc"}


# =============================================================================
# Job Processing (Background Thread)
# =============================================================================

class GenerationJob:
    """Tracks state of a video generation job."""
    def __init__(self, job_id, audio_path, lyrics_path, mode, fps, font_size):
        self.job_id = job_id
        self.audio_path = audio_path
        self.lyrics_path = lyrics_path
        self.mode = mode
        self.fps = fps
        self.font_size = font_size
        self.status = "queued"       # queued → parsing → rendering → encoding → done / error
        self.progress = 0            # 0-100
        self.message = "waiting to start..."
        self.error = None
        self.output_dir = os.path.join(app.config["OUTPUT_FOLDER"], job_id)
        self.created_at = datetime.now().isoformat()
        self.outputs = {}            # {type: filepath}
        self.lyric_count = 0
        self.preview_path = None

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "outputs": {k: os.path.basename(v) for k, v in self.outputs.items()},
            "lyric_count": self.lyric_count,
            "preview_path": self.preview_path,
        }


def run_generation(job: GenerationJob):
    """Execute the generation pipeline in a background thread."""
    temp_dir = os.path.join(job.output_dir, "alignment_temp")
    try:
        os.makedirs(job.output_dir, exist_ok=True)

        # --- Step 1: Parse lyrics if provided ---
        job.status = "parsing"
        job.message = "parsing lyrics file if provided..."
        job.progress = 5

        lyrics = None
        if job.lyrics_path and os.path.isfile(job.lyrics_path):
            try:
                lyrics = parse_lyrics(job.lyrics_path)
                job.lyric_count = len(lyrics)
            except Exception as e:
                print(f"Error parsing lyrics file: {e}")

        # Run Vocal Isolation and Alignment / Auto-Transcription
        job.status = "aligning"
        job.message = "running vocal isolation & AI alignment..."
        job.progress = 10
        
        from brat_lyric_video import isolate_vocals, align_lyrics_with_whispermlx
        
        try:
            vocals_path = isolate_vocals(job.audio_path, temp_dir)
            lyrics = align_lyrics_with_whispermlx(vocals_path, lyrics)
            job.lyric_count = len(lyrics)
            job.message = f"aligned {len(lyrics)} words"
            job.progress = 15
        except Exception as e:
            traceback.print_exc()
            if not lyrics:
                raise ValueError(f"Automated transcription failed: {str(e)}. Please upload a lyric file (.srt/.lrc)")
            else:
                job.message = "alignment failed, using basic timestamps"
                job.progress = 15

        # --- Step 2: Load font ---
        job.status = "rendering"
        job.message = "loading font..."
        job.progress = 18
        font = resolve_font(size=job.font_size)

        # Determine font path for the generator
        effective_font_path = None
        for path in FONT_PATH_CANDIDATES:
            if os.path.isfile(path):
                effective_font_path = path
                break

        # --- Step 3: Generate preview frame ---
        job.message = "generating preview..."
        job.progress = 22

        if lyrics:
            # We want to render a preview of the middle lyric state
            mid_idx = len(lyrics) // 2
            preview_img = render_lyric_frame(
                lyrics[mid_idx].text, font, with_background=True,
                font_size=job.font_size, font_path=effective_font_path
            )
            preview_path = os.path.join(job.output_dir, "preview.png")
            preview_img.save(preview_path, "PNG")
            job.preview_path = f"/api/output/{job.job_id}/preview.png"

        # --- Step 4: Generate outputs ---
        if job.mode in ("video", "both"):
            job.message = "rendering video frames..."
            job.progress = 30

            video_path = generate_video(
                lyrics, job.audio_path, job.output_dir, font,
                fps=job.fps,
                font_size=job.font_size,
                font_path=effective_font_path,
            )
            job.outputs["video"] = video_path
            job.progress = 70 if job.mode == "both" else 90

        if job.mode in ("nle", "both"):
            job.message = "generating nle assets..."
            job.progress = 75 if job.mode == "both" else 30

            png_dir, fcpxml_path, edl_path = generate_nle_assets(
                lyrics, job.audio_path, job.output_dir, font,
                fps=job.fps,
                font_size=job.font_size,
                font_path=effective_font_path,
            )
            job.outputs["fcpxml"] = fcpxml_path
            job.outputs["edl"] = edl_path
            job.outputs["png_dir"] = png_dir

            # Create a zip of all NLE assets
            job.message = "packaging nle assets..."
            job.progress = 88
            zip_path = os.path.join(job.output_dir, "brat_nle_assets.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(fcpxml_path, "brat_timeline.fcpxml")
                zf.write(edl_path, "brat_timeline.edl")
                for png_file in sorted(Path(png_dir).glob("*.png")):
                    zf.write(str(png_file), f"png_sequence/{png_file.name}")
            job.outputs["nle_zip"] = zip_path

        # --- Done ---
        job.status = "done"
        job.progress = 100
        job.message = "generation complete!"

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.message = f"error: {str(e)}"
        traceback.print_exc()
    finally:
        if os.path.exists(temp_dir):
            print(f"Cleaning up temporary alignment folder: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# Routes
# =============================================================================

@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start a generation job."""
    if "audio" not in request.files:
        return jsonify({"error": "Audio file is required."}), 400

    audio_file = request.files["audio"]
    lyrics_file = request.files.get("lyrics")

    if not audio_file.filename:
        return jsonify({"error": "Audio file is required."}), 400

    audio_ext = Path(audio_file.filename).suffix.lower()
    lyrics_ext = Path(lyrics_file.filename).suffix.lower() if (lyrics_file and lyrics_file.filename) else ""

    if audio_ext not in ALLOWED_AUDIO_EXT:
        return jsonify({"error": f"Unsupported audio format: {audio_ext}. Use: {', '.join(ALLOWED_AUDIO_EXT)}"}), 400

    if lyrics_file and lyrics_file.filename:
        if lyrics_ext not in ALLOWED_LYRIC_EXT:
            return jsonify({"error": f"Unsupported lyrics format: {lyrics_ext}. Use: {', '.join(ALLOWED_LYRIC_EXT)}"}), 400

    # Get options
    mode = request.form.get("mode", "both")
    fps = int(request.form.get("fps", DEFAULT_FPS))
    font_size = int(request.form.get("font_size", DEFAULT_FONT_SIZE))

    if mode not in ("video", "nle", "both"):
        return jsonify({"error": "Mode must be 'video', 'nle', or 'both'."}), 400

    # Create job
    job_id = str(uuid.uuid4())[:8]
    job_dir = os.path.join(app.config["UPLOAD_FOLDER"], job_id)
    os.makedirs(job_dir, exist_ok=True)

    # Save uploaded files
    audio_path = os.path.join(job_dir, f"audio{audio_ext}")
    lyrics_path = os.path.join(job_dir, f"lyrics{lyrics_ext}") if (lyrics_file and lyrics_file.filename) else None

    audio_file.save(audio_path)
    if lyrics_path:
        lyrics_file.save(lyrics_path)

    job = GenerationJob(job_id, audio_path, lyrics_path, mode, fps, font_size)
    jobs[job_id] = job

    # Start generation thread
    thread = threading.Thread(target=run_generation, args=(job,))
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    """Get the status of a job."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job.to_dict())


@app.route("/api/download/<job_id>/<type_name>")
def api_download(job_id, type_name):
    """Download an output file."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    filepath = job.outputs.get(type_name)
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found."}), 404

    return send_file(filepath, as_attachment=True)


@app.route("/api/preview-lyric", methods=["POST"])
def api_preview_lyric():
    """Generate a quick preview of a single lyric line with current settings."""
    text = request.json.get("text", "brat")
    font_size = int(request.json.get("font_size", DEFAULT_FONT_SIZE))

    font = resolve_font(size=font_size)
    img = render_lyric_frame(text.lower(), font, with_background=True, font_size=font_size)

    preview_dir = os.path.join(app.config["OUTPUT_FOLDER"], "_previews")
    os.makedirs(preview_dir, exist_ok=True)
    preview_id = str(uuid.uuid4())[:8]
    preview_path = os.path.join(preview_dir, f"{preview_id}.png")
    img.save(preview_path, "PNG")

    return jsonify({"preview_url": f"/api/preview-image/{preview_id}"})


@app.route("/api/preview-image/<preview_id>")
def api_preview_image(preview_id):
    """Serve a preview image."""
    preview_dir = os.path.join(app.config["OUTPUT_FOLDER"], "_previews")
    filepath = os.path.join(preview_dir, f"{preview_id}.png")
    if not os.path.isfile(filepath):
        return jsonify({"error": "Preview not found."}), 404
    return send_file(filepath, mimetype="image/png")


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🟢  BRAT LYRIC VIDEO GENERATOR — Web UI")
    print("=" * 60)
    print(f"  Open http://localhost:5000 in your browser")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
