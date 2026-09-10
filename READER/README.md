# Balloons Manga Reader (`READER/`)

A dedicated, high-performance Manga Reader application built for **BalloonsTranslator**.

The reader automatically scans the `TRANSLATED/` directory, discovers all translated manga volumes, and renders translated dialogue text directly over speech bubbles using the original JSON translation data produced by the translator pipeline.

---

## 🌟 Key Features

1. **Automatic Manga Library**:
   - Recursively scans `TRANSLATED/` for translated manga folders.
   - Generates manga cards with cover thumbnails, title, page counts, and metadata tags.
   - Real-time search/filter and sorting (Recently Added, Title A-Z, Page Count).
   - Instant refresh when new translated manga are saved.

2. **Full-Featured Reader View**:
   - **JSON Speech Bubble Overlay**: Renders translated text with exact formatting, colors, positioning, and rotation using `ballontranslator`'s native project text format (`ProjImgTrans` / `TextBlock`).
   - **Overlay Mode Toggle**: Switch between Translated text overlay, Original Japanese text overlay, or Clean raw image view.
   - **Background Image Toggle**: Switch between Inpainted clean background or original raw page.
   - **Page Navigation**: Previous/Next buttons, interactive page slider, and direct jump.
   - **Reading Direction**: Supports standard Manga Right-to-Left (RTL) or Left-to-Right (LTR) page turning.
   - **Zoom & Fit Controls**: Fit-to-Screen, Fit-to-Width, Free Zoom (`Ctrl + Mouse Wheel`), and reset.
   - **Distraction-Free Fullscreen**: Press `F11` or `Esc` to toggle.
   - **Keyboard Navigation**: Left/Right Arrow, A/D, PageUp/PageDown, Home/End, `+` / `-`.

3. **Seamless Translator Integration**:
   - Easily open any discovered manga volume back inside **BalloonsTranslator** for editing or re-translating.
   - Completely isolated within `READER/` without altering or breaking any existing translator files.

---

## 🚀 How to Run

### Command Line Launcher

From the project root:

```bash
# Launch Reader using launch_reader.py
python READER/launch_reader.py

# Or run via shell script (Linux/macOS)
./READER/launch_reader.sh

# Or Windows batch script
READER\launch_reader.bat
```

### CLI Arguments

```text
--translated-dir PATH   Specify custom TRANSLATED directory (default: ../TRANSLATED)
--manga-dir PATH        Directly open a specific manga directory on startup
--qt-api API            Specify Qt binding (pyqt6, pyside6, pyqt5, pyside2)
```

Example:

```bash
python READER/launch_reader.py --translated-dir ./TRANSLATED --manga-dir "./TRANSLATED/Hiryu Ran/On the Isolated Island: Chapter 1"
```

---

## 📁 Directory Structure

```text
READER/
├── launch_reader.py    # Main CLI application launcher
├── launch_reader.sh    # Linux/macOS shell launcher
├── launch_reader.bat   # Windows batch launcher
├── README.md           # Documentation
├── core/               # Backend logic
│   ├── scanner.py      # Recursive TRANSLATED directory scanner
│   └── loader.py       # Manga project data loader & fallback JSON parser
├── ui/                 # Qt User Interface
│   ├── main_window.py  # Top-level window & stacked view manager
│   ├── library_view.py # Grid/list Manga Library widget
│   ├── reader_view.py  # Reader widget with navigation & toolbar
│   ├── manga_canvas.py # Interactive QGraphicsView canvas for page & overlays
│   └── styles.py       # Dark theme CSS stylesheet
└── tests/              # Unit test suite
    └── test_reader_core.py
```
