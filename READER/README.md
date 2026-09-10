# Balloons Manga Library & Launcher (`READER/`)

A dedicated Manga Library and Manager application built for **BalloonsTranslator**.

The library automatically scans the `TRANSLATED/` directory, discovers all translated manga volumes organized by author and series, and lets you open any selected manga directly in **BalloonsTranslator**.

---

## 🌟 Key Features

1. **Automatic Manga Library**:
   - Recursively scans `TRANSLATED/` for translated manga folders.
   - Hierarchical browsing: Authors Grid → Series / Folder Grid → Manga Chapters Grid.
   - Generates manga cards with cover thumbnails, titles, page counts, verification badges, and favorite status.
   - Real-time search/filter and sorting (Recently Added, Title A-Z, Page Count).
   - Breadcrumb navigation with instant folder jumps.

2. **Direct BalloonsTranslator Launch**:
   - Picking any manga card immediately launches **BalloonsTranslator** with that manga folder (`--proj-dir`).
   - Context menu options for opening folders and managing favorites.

---

## 🚀 How to Run

### Command Line Launcher

From the project root:

```bash
# Launch Library using launch_reader.py
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
│   └── favorites.py    # Favorites persistence manager
├── ui/                 # Qt User Interface
│   ├── main_window.py  # Top-level window & header
│   ├── library_view.py # Hierarchical Manga Library widget
│   ├── loading_overlay.py # Scanning overlay widget
│   └── styles.py       # Dark theme CSS stylesheet
└── tests/              # Unit test suite
    └── test_reader_core.py
```
