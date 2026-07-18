#!/usr/bin/env python3
"""
=============================================================================
  BRAT LYRIC VIDEO GENERATOR — macOS Desktop GUI
  CustomTkinter interface wrapper for the core audio-visual engine.
=============================================================================
"""

import os
import sys
import shutil
import logging
import threading
from pathlib import Path
import traceback

import customtkinter as ctk
from tkinter import filedialog, messagebox

# Set styling and theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green") # matches the green theme

# Ensure application folders and loggers exist
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/BratGenerator")
os.makedirs(APP_SUPPORT_DIR, exist_ok=True)

# Isolate models and cache to application folder
os.environ["HF_HOME"] = os.path.join(APP_SUPPORT_DIR, "cache", "huggingface")
os.environ["TORCH_HOME"] = os.path.join(APP_SUPPORT_DIR, "cache", "torch")
os.environ["NUMBA_CACHE_DIR"] = os.path.join(APP_SUPPORT_DIR, "cache", "numba")

# Configure logger
log_file = os.path.join(APP_SUPPORT_DIR, "debug.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logging.info("Brat Desktop Application initialized.")

# Import core engine
from brat_lyric_video import (
    parse_lyrics, resolve_font, render_lyric_frame,
    generate_video, generate_nle_assets,
    isolate_vocals, align_lyrics_with_whispermlx,
    BRAT_GREEN_HEX
)


class BratDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("brat lyric video generator")
        self.geometry("750x640")
        self.resizable(False, False)

        # Main States
        self.audio_path = None
        self.lyrics_path = None
        self.output_dir = os.path.expanduser("~/Desktop/Brat Output")
        self.generation_thread = None
        self.is_processing = False

        self.setup_ui()

    def setup_ui(self):
        # ════════════════════════════════════════════════════════════════════
        # HEADER ZONE
        # ════════════════════════════════════════════════════════════════════
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=30, pady=(25, 10))

        self.logo_label = ctk.CTkLabel(
            self.header_frame, 
            text="brat", 
            font=ctk.CTkFont(family="Arial", size=36, weight="bold"),
            text_color="#8ACE00"
        )
        self.logo_label.pack(side="left")

        self.tagline_label = ctk.CTkLabel(
            self.header_frame, 
            text="lyric video generator", 
            font=ctk.CTkFont(family="Arial", size=18, slant="italic"),
            text_color="gray"
        )
        self.tagline_label.pack(side="left", padx=15, pady=(10, 0))

        # ════════════════════════════════════════════════════════════════════
        # FILE SELECTOR DROPZONES (Landing Zone UI)
        # ════════════════════════════════════════════════════════════════════
        self.upload_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.upload_frame.pack(fill="x", padx=30, pady=15)

        # Audio Select Box
        self.audio_box = ctk.CTkFrame(self.upload_frame, border_width=1, border_color="gray", height=130)
        self.audio_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.audio_box.pack_propagate(False)
        self.audio_box.bind("<Button-1>", lambda e: self.select_audio())

        self.audio_label = ctk.CTkLabel(
            self.audio_box, 
            text="🎵 Click to select Audio file", 
            font=ctk.CTkFont(family="Arial", size=14, weight="bold")
        )
        self.audio_label.pack(expand=True)
        self.audio_label.bind("<Button-1>", lambda e: self.select_audio())

        self.audio_hint = ctk.CTkLabel(
            self.audio_box, 
            text=".mp3, .wav, .m4a", 
            font=ctk.CTkFont(family="Arial", size=11),
            text_color="gray"
        )
        self.audio_hint.pack(pady=(0, 20))
        self.audio_hint.bind("<Button-1>", lambda e: self.select_audio())

        # Lyrics Select Box
        self.lyrics_box = ctk.CTkFrame(self.upload_frame, border_width=1, border_color="gray", height=130)
        self.lyrics_box.pack(side="right", fill="both", expand=True, padx=(10, 0))
        self.lyrics_box.pack_propagate(False)
        self.lyrics_box.bind("<Button-1>", lambda e: self.select_lyrics())

        self.lyrics_label = ctk.CTkLabel(
            self.lyrics_box, 
            text="📄 Click to select Lyrics file", 
            font=ctk.CTkFont(family="Arial", size=14, weight="bold")
        )
        self.lyrics_label.pack(expand=True)
        self.lyrics_label.bind("<Button-1>", lambda e: self.select_lyrics())

        self.lyrics_hint = ctk.CTkLabel(
            self.lyrics_box, 
            text="[optional] .srt, .lrc (auto-transcribe if omitted)", 
            font=ctk.CTkFont(family="Arial", size=11),
            text_color="gray"
        )
        self.lyrics_hint.pack(pady=(0, 20))
        self.lyrics_hint.bind("<Button-1>", lambda e: self.select_lyrics())

        # ════════════════════════════════════════════════════════════════════
        # DESTINATION SELECTOR
        # ════════════════════════════════════════════════════════════════════
        self.dest_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.dest_frame.pack(fill="x", padx=30, pady=10)

        self.dest_label = ctk.CTkLabel(self.dest_frame, text="destination:", font=ctk.CTkFont(family="Arial", size=12))
        self.dest_label.pack(side="left")

        self.dest_entry = ctk.CTkEntry(self.dest_frame, width=420)
        self.dest_entry.insert(0, self.output_dir)
        self.dest_entry.pack(side="left", padx=10)

        self.dest_btn = ctk.CTkButton(
            self.dest_frame, 
            text="browse...", 
            width=80,
            command=self.select_destination
        )
        self.dest_btn.pack(side="left")

        # ════════════════════════════════════════════════════════════════════
        # OPTIONS PANEL
        # ════════════════════════════════════════════════════════════════════
        self.options_frame = ctk.CTkFrame(self)
        self.options_frame.pack(fill="both", expand=True, padx=30, pady=15)

        # Output Mode Select
        self.mode_label = ctk.CTkLabel(self.options_frame, text="output mode", font=ctk.CTkFont(family="Arial", size=12, weight="bold"))
        self.mode_label.grid(row=0, column=0, padx=25, pady=(20, 5), sticky="w")

        self.mode_var = ctk.StringVar(value="both")
        self.mode_both = ctk.CTkRadioButton(self.options_frame, text="video + NLE assets", variable=self.mode_var, value="both")
        self.mode_both.grid(row=1, column=0, padx=25, pady=5, sticky="w")
        self.mode_video = ctk.CTkRadioButton(self.options_frame, text="video only (.mp4)", variable=self.mode_var, value="video")
        self.mode_video.grid(row=2, column=0, padx=25, pady=5, sticky="w")
        self.mode_nle = ctk.CTkRadioButton(self.options_frame, text="NLE only (PNG + XML)", variable=self.mode_var, value="nle")
        self.mode_nle.grid(row=3, column=0, padx=25, pady=5, sticky="w")

        # FPS & Font Sliders
        self.fps_label = ctk.CTkLabel(self.options_frame, text="frame rate (fps): 30", font=ctk.CTkFont(family="Arial", size=12, weight="bold"))
        self.fps_label.grid(row=0, column=1, padx=40, pady=(20, 5), sticky="w")

        self.fps_slider = ctk.CTkSlider(self.options_frame, from_=24, to=60, number_of_steps=36, width=220, command=self.update_fps_label)
        self.fps_slider.set(30)
        self.fps_slider.grid(row=1, column=1, padx=40, pady=5, sticky="w")

        self.font_label = ctk.CTkLabel(self.options_frame, text="base text size: 90 px", font=ctk.CTkFont(family="Arial", size=12, weight="bold"))
        self.font_label.grid(row=2, column=1, padx=40, pady=(15, 5), sticky="w")

        self.font_slider = ctk.CTkSlider(self.options_frame, from_=40, to=160, number_of_steps=24, width=220, command=self.update_font_label)
        self.font_slider.set(90)
        self.font_slider.grid(row=3, column=1, padx=40, pady=5, sticky="w")

        # ════════════════════════════════════════════════════════════════════
        # EXECUTION PROGRESS & STATUS ZONE
        # ════════════════════════════════════════════════════════════════════
        self.status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.status_frame.pack(fill="x", padx=30, pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.status_frame, width=690, progress_color="#8ACE00")
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0, 5))
        self.progress_bar.pack_forget() # Hidden initially

        self.status_label = ctk.CTkLabel(
            self.status_frame, 
            text="ready to build", 
            font=ctk.CTkFont(family="Arial", size=12),
            text_color="gray"
        )
        self.status_label.pack()

        # ════════════════════════════════════════════════════════════════════
        # GENERATE EXECUTION BUTTON
        # ════════════════════════════════════════════════════════════════════
        self.generate_btn = ctk.CTkButton(
            self, 
            text="GENERATE BRAT VIDEO", 
            font=ctk.CTkFont(family="Arial", size=16, weight="bold"),
            fg_color="#8ACE00",
            text_color="black",
            hover_color="#76B000",
            height=45,
            command=self.start_processing
        )
        self.generate_btn.pack(fill="x", padx=30, pady=(10, 25))

    # ════════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ════════════════════════════════════════════════════════════════════

    def select_audio(self):
        if self.is_processing: return
        file = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio Files", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac")]
        )
        if file:
            self.audio_path = file
            self.audio_label.configure(text=f"🎵 {Path(file).name}", text_color="#8ACE00")
            self.audio_box.configure(border_color="#8ACE00")

    def select_lyrics(self):
        if self.is_processing: return
        file = filedialog.askopenfilename(
            title="Select Lyrics File (Optional)",
            filetypes=[("Lyric Files", "*.srt *.lrc")]
        )
        if file:
            self.lyrics_path = file
            self.lyrics_label.configure(text=f"📄 {Path(file).name}", text_color="#8ACE00")
            self.lyrics_box.configure(border_color="#8ACE00")
        else:
            self.lyrics_path = None
            self.lyrics_label.configure(text="📄 Click to select Lyrics file", text_color="white")
            self.lyrics_box.configure(border_color="gray")

    def select_destination(self):
        if self.is_processing: return
        folder = filedialog.askdirectory(title="Select Destination Folder")
        if folder:
            self.output_dir = folder
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, folder)

    def update_fps_label(self, val):
        self.fps_label.configure(text=f"frame rate (fps): {int(val)}")

    def update_font_label(self, val):
        self.font_label.configure(text=f"base text size: {int(val)} px")

    # ════════════════════════════════════════════════════════════════════
    # BACKGROUND THREAD ORCHESTRATOR
    # ════════════════════════════════════════════════════════════════════

    def update_status(self, message: str, progress: float):
        """Thread-safe status UI updates."""
        self.after(0, lambda: self.status_label.configure(text=message))
        self.after(0, lambda: self.progress_bar.set(progress))

    def start_processing(self):
        if not self.audio_path:
            messagebox.showerror("Error", "Please select an audio file to start.")
            return

        self.is_processing = True
        self.generate_btn.configure(state="disabled", text="PROCESSING...")
        self.progress_bar.pack(pady=(0, 5))
        self.status_label.configure(text_color="white")

        # Start background processor thread
        self.generation_thread = threading.Thread(target=self.run_pipeline)
        self.generation_thread.start()

    def run_pipeline(self):
        try:
            logging.info("Starting processing worker thread.")
            
            # Setup output folder path
            out_folder = self.dest_entry.get().strip()
            os.makedirs(out_folder, exist_ok=True)
            temp_align_dir = os.path.join(out_folder, "alignment_temp")
            
            # Resolve font
            font_size = int(self.font_slider.get())
            font = resolve_font(size=font_size)

            # Step 1: Vocal isolation
            self.update_status("Step 1/4: Separating vocals using Demucs...", 0.15)
            logging.info("Starting vocal isolation.")
            vocals_path = isolate_vocals(self.audio_path, temp_align_dir)
            logging.info(f"Isolated vocals path: {vocals_path}")

            # Step 2: AI alignment & transcription
            self.update_status("Step 2/4: Performing AI alignment...", 0.40)
            logging.info("Starting WhisperMLX transcription & word alignment.")
            
            # Parse existing lyrics if provided
            lyrics = None
            if self.lyrics_path:
                lyrics = parse_lyrics(self.lyrics_path)
            
            aligned_lyrics = align_lyrics_with_whispermlx(vocals_path, lyrics)
            logging.info("WhisperMLX alignment complete.")

            # Set configuration parameters
            mode = self.mode_var.get()
            fps = int(self.fps_slider.get())

            # Bridge progress helper
            def rendering_callback(msg, val):
                # Scale step 3 between 0.60 and 0.85
                self.update_status(msg, 0.60 + val * 0.25)

            # Step 3 & 4: Render frames & video compilation
            if mode in ("both", "video"):
                self.update_status("Step 3/4: Rendering Dynamic Layout...", 0.60)
                generate_video(
                    aligned_lyrics, self.audio_path, out_folder, font,
                    fps=fps, font_size=font_size, progress_callback=rendering_callback
                )

            if mode in ("both", "nle"):
                self.update_status("Step 3/4: Rendering NLE PNG frames...", 0.60)
                generate_nle_assets(
                    aligned_lyrics, self.audio_path, out_folder, font,
                    fps=fps, font_size=font_size, progress_callback=rendering_callback
                )

            # Cleanup isolated temporary audio files
            if os.path.exists(temp_align_dir):
                logging.info(f"Cleaning up temporary directory: {temp_align_dir}")
                shutil.rmtree(temp_align_dir, ignore_errors=True)

            self.update_status("Done!", 1.0)
            logging.info("Pipeline executed successfully.")
            self.after(0, lambda: messagebox.showinfo("Success", f"Brat video generated successfully!\nSaved to: {out_folder}"))

        except Exception as e:
            tb = traceback.format_exc()
            logging.error(f"Execution Error: {str(e)}\n{tb}")
            self.update_status("Execution failed.", 0.0)
            self.after(0, lambda: messagebox.showerror("Processing Error", f"An error occurred during video generation:\n\n{str(e)}\n\nSee log file for details:\n{log_file}"))
        finally:
            # Enable buttons back
            self.after(0, self.reset_ui)

    def reset_ui(self):
        self.is_processing = False
        self.generate_btn.configure(state="normal", text="GENERATE BRAT VIDEO")
        self.progress_bar.pack_forget()
        self.status_label.configure(text_color="gray", text="ready to build")


if __name__ == "__main__":
    app = BratDesktopApp()
    app.mainloop()
