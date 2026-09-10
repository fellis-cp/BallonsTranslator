#!/usr/bin/env python3
"""
Launcher entry point for the Manga Reader Application.
"""

import sys
import os
import os.path as osp
import argparse
from pathlib import Path

# Add workspace parent directory to sys.path so ballontranslator dependencies are accessible
READER_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = READER_DIR.parent

# Auto-switch to workspace .venv python if available and not already in use
venv_python = WORKSPACE_DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if venv_python.exists() and os.environ.get("READER_VENV_SWITCHED") != "1":
    try:
        if Path(sys.executable).resolve() != venv_python.resolve():
            os.environ["READER_VENV_SWITCHED"] = "1"
            os.execv(str(venv_python), [str(venv_python)] + sys.argv)
    except Exception:
        pass

if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

# Ensure CWD is always the workspace root so data/models paths resolve properly
os.chdir(str(WORKSPACE_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="BalloonsTranslator - Manga Reader Application")
    parser.add_argument(
        "--translated-dir",
        default="",
        type=str,
        help="Path to TRANSLATED manga root directory (defaults to ../TRANSLATED)",
    )
    parser.add_argument(
        "--manga-dir",
        default="",
        type=str,
        help="Directly open a specific manga folder on startup",
    )
    parser.add_argument(
        "--qt-api",
        default="pyqt6",
        choices=["pyqt6", "pyside6", "pyqt5", "pyside2"],
        help="Qt API binding to use",
    )

    args, _ = parser.parse_known_args()

    os.environ['QT_API'] = args.qt_api

    # Determine default TRANSLATED directory
    translated_dir = args.translated_dir
    if not translated_dir:
        candidate = WORKSPACE_DIR / "TRANSLATED"
        if candidate.exists():
            translated_dir = str(candidate.resolve())
        else:
            translated_dir = str(WORKSPACE_DIR.resolve())

    # Initialize Qt
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QApplication

    app_args = sys.argv
    app = QApplication(app_args)
    app.setApplicationName("BalloonsMangaReader")
    app.setApplicationVersion("1.0.0")

    # Set up high DPI scaling for Qt5 if applicable
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    from READER.ui.main_window import ReaderMainWindow


    window = ReaderMainWindow(
        translated_dir=translated_dir,
        open_manga_path=args.manga_dir,
    )
    window.show()

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
