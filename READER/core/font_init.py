import sys
import os
import os.path as osp
from pathlib import Path
import logging

from qtpy.QtGui import QFontDatabase, QFont, QGuiApplication
from qtpy.QtWidgets import QApplication

from ballontranslator.utils import shared
from ballontranslator.utils.io_utils import find_all_files_recursive
from ballontranslator.utils.font_registry import (
    build_font_registry,
    ensure_font_registry_overrides,
)
from ballontranslator.ui.text_engine.font_family import (
    register_qt_font_family_aliases,
)
from ballontranslator.utils.config import load_config

LOGGER = logging.getLogger('READER.font_init')

FONT_EXTS = {'.ttf', '.otf', '.ttc', '.pfb'}


def init_font_engine(program_path: str = None) -> None:
    """Initialize BalloonsTranslator font database, font registry, and family aliases.

    Loads fonts from fonts/ directory so text engine rendering matches main translator.
    """
    if program_path is None:
        program_path = shared.PROGRAM_PATH

    # Load configuration
    try:
        load_config(shared.CONFIG_PATH)
    except Exception as e:
        LOGGER.warning(f"Could not load config: {e}")

    # Register bundled application fonts from fonts/
    fonts_dir = osp.join(program_path, 'fonts')
    font_paths = []
    if osp.exists(fonts_dir):
        font_paths = [
            str(Path(p).resolve())
            for p in find_all_files_recursive(fonts_dir, FONT_EXTS)
        ]
        for fp in font_paths:
            QFontDatabase.addApplicationFont(fp)

    # Initialize Font Database
    font_database = QFontDatabase() if not shared.FLAG_QT6 else QFontDatabase
    system_families = sorted(font_database.families(), key=str.casefold)

    font_registry_path = ensure_font_registry_overrides(program_path)
    shared.FONT_REGISTRY = build_font_registry(
        font_database,
        font_paths,
        system_families,
        locale=shared.DEFAULT_DISPLAY_LANG or 'en_US',
        font_registry_path=(
            str(font_registry_path) if font_registry_path is not None else None
        ),
    )
    shared.FONT_FAMILIES = set(font_database.families())

    # Register Qt font family aliases for special/bracketed font names
    font_aliases = register_qt_font_family_aliases(
        font_database.families(),
        font_database.styles if hasattr(font_database, 'styles') else (lambda f: []),
    )
    if font_aliases:
        LOGGER.info(f"Registered Qt font family aliases: {len(font_aliases)}")

    # App Default Font
    app_font = QFont('Microsoft YaHei UI')
    if not app_font.exactMatch() or sys.platform == 'darwin':
        app = QApplication.instance()
        if app:
            app_font = app.font()
    app_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app_font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias
    )
    if QApplication.instance():
        QGuiApplication.setFont(app_font)

    shared.DEFAULT_FONT_FAMILY = app_font.family()
    shared.APP_DEFAULT_FONT = app_font.family()
    LOGGER.info("Font engine initialized successfully.")
