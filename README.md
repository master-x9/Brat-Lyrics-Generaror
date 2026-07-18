# 🟢 BRAT Lyric Video Generator
Generate lyric videos with the iconic **Charli XCX "Brat"** album aesthetic — lime green background, lo-fi compressed text, all lowercase.
![Brat Aesthetic]([https://upload.wikimedia.org/wikipedia/en/b/b9/Charli_XCX_-_Brat.png](https://imgs.search.brave.com/FbIrAXumkqD6LgrqdN1x_5Y7HUd-HxsEp5kpCypl4js/rs:fit:860:0:0:0/g:ce/aHR0cHM6Ly91cGxv/YWQud2lraW1lZGlh/Lm9yZy93aWtpcGVk/aWEvY29tbW9ucy90/aHVtYi82LzYwL0No/YXJsaV9YQ1hfLV9C/cmF0XyUyOGFsYnVt/X2NvdmVyJTI5LnBu/Zy81MTJweC1DaGFy/bGlfWENYXy1fQnJh/dF8lMjhhbGJ1bV9j/b3ZlciUyOS5wbmc))
## Quick Start
```bash
# 1. Install dependencies
pip install moviepy Pillow numpy
# 2. Ensure ffmpeg is installed
brew install ffmpeg
# 3. Generate a full MP4 video
python brat_lyric_video.py --audio your_song.mp3 --lyrics your_lyrics.srt --mode video
# 4. Or generate NLE-ready assets for DaVinci Resolve
python brat_lyric_video.py --audio your_song.mp3 --lyrics your_lyrics.srt --mode nle
# 5. Or generate both
python brat_lyric_video.py --audio your_song.mp3 --lyrics your_lyrics.srt --mode both
```
## Features
### 🎬 Two Output Modes
|
 Mode 
|
 Output 
|
 Best For 
|
|
------
|
--------
|
----------
|
|
`video`
|
 Single 
`.mp4`
 file with synced audio 
|
 Quick previews, direct upload 
|
|
`nle`
|
 PNG sequence + FCPXML + EDL 
|
 Professional editing in DaVinci Resolve / FCP 
|
|
`both`
|
 All of the above 
|
 Full pipeline 
|
### 🎨 Authentic Brat Aesthetic
- **Background**: Exact Brat green `#8ACE00`
- **Typography**: Arial Narrow (or Arial with 110% vertical stretch), all lowercase, black
- **Lo-Fi Effects**:
  - Gaussian blur (radius 1.5) for compressed softness
  - Downscale → nearest-neighbor upscale for pixel crunch
  - Subtle alpha edge blur for organic degradation
### 📐 Technical Specs
- **Resolution**: 1080×1920 (vertical 9:16)
- **Frame Rate**: 30fps (configurable)
- **Codec**: H.264 video / AAC audio
- **PNG Output**: RGBA with transparent alpha channel
## Input Formats
### SRT (SubRip Subtitle)
```
1
00:00:02,000 --> 00:00:05,500
i might say something stupid
2
00:00:06,000 --> 00:00:09,000
i guess i'm just that girl
```
### LRC (Lyrics)
```
[00:02.00]i might say something stupid
[00:06.00]i guess i'm just that girl
```
## CLI Options
```
--audio       Path to audio file (.mp3 or .wav)         [required]
--lyrics      Path to lyric file (.srt or .lrc)         [required]
--mode        Output mode: video | nle | both           [default: both]
--output      Output directory                          [default: ./brat_output]
--fps         Frame rate                                [default: 30]
--font        Override font path                        [default: auto-detect]
--font-size   Font size in pixels                       [default: 90]
```
## NLE Import Instructions
### DaVinci Resolve
1. **File → Import → Timeline**
2. Select `brat_timeline.fcpxml`
3. Drag your audio onto the A1 track
4. The transparent PNG lyric overlays will be perfectly timed
### Final Cut Pro
1. **File → Import → XML**
2. Select `brat_timeline.fcpxml`
### Adobe Premiere Pro
1. **File → Import** → select `brat_timeline.edl`
2. Relink the PNG files from the `png_sequence/` folder
## Customization
Edit the constants at the top of `brat_lyric_video.py`:
```python
BRAT_GREEN = (138, 206, 0)        # Change the background color
TEXT_COLOR = (0, 0, 0)             # Change text color
DEFAULT_FONT_SIZE = 90             # Adjust text size
BLUR_RADIUS = 1.5                  # More = softer, less = sharper
DOWNSCALE_FACTOR = 0.4             # Lower = more pixelated
TEXT_VERTICAL_STRETCH = 1.10       # Vertical text stretch ratio
```
## Font Configuration
The script auto-detects fonts in this order:
1. `/Library/Fonts/Arial Narrow.ttf`
2. `/Library/Fonts/Arial.ttf`
3. `/System/Library/Fonts/Helvetica.ttc`
4. Pillow default (fallback)
Override with `--font /path/to/your/font.ttf`.
## License
MIT — Do whatever you want with it. Go make something brat.
