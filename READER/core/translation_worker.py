import logging
import threading
from typing import List, Optional, Any

from qtpy.QtCore import QThread, Signal

from READER.core.loader import load_manga_project, MangaProjectData

LOGGER = logging.getLogger('READER.translation_worker')

HAS_MODULES = False
try:
    import ballontranslator.modules.translators.trans_playwrigt as _tp
    from ballontranslator.modules.translators.base import TRANSLATORS
    from ballontranslator.utils.proj_imgtrans import ProjImgTrans
    HAS_MODULES = True
except ImportError:
    TRANSLATORS = None
    ProjImgTrans = None


class TranslationTaskWorker(QThread):
    """Background worker thread for translating manga text blocks using Playwright / BallonsTranslator modules."""

    progress = Signal(int, int, str)
    page_finished = Signal(str, list)
    task_completed = Signal(bool, str)

    def __init__(
        self,
        manga_dir: str,
        json_path: Optional[str] = None,
        target_pages: Optional[List[str]] = None,
        target_block_indices: Optional[List[int]] = None,
        translator_engine: str = "Gemini Playwright",
        source_lang: str = "日本語",
        target_lang: str = "English",
        parent=None,
    ):
        super().__init__(parent)
        self.manga_dir = manga_dir
        self.json_path = json_path
        self.target_pages = target_pages  # If None, translates all pages in volume
        self.target_block_indices = target_block_indices  # If None, translates all blocks on page
        self.translator_engine = translator_engine
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._stop_event = threading.Event()

    def request_cancel(self) -> None:
        """Cancel ongoing translation task."""
        self._stop_event.set()

    def run(self) -> None:
        """Execute translation task on background thread."""
        try:
            if not HAS_MODULES or not ProjImgTrans or not TRANSLATORS:
                self.task_completed.emit(False, "BalloonsTranslator modules unavailable.")
                return

            proj = ProjImgTrans()
            proj.load(self.manga_dir, json_path=self.json_path)

            pages_to_run = self.target_pages or list(proj.pages.keys())
            total = len(pages_to_run)

            if total == 0:
                self.task_completed.emit(True, "No pages to translate.")
                return

            self.progress.emit(0, total, f"Initializing {self.translator_engine} translator...")

            # Resolve translator class
            translator_cls = TRANSLATORS.module_dict.get(self.translator_engine)
            if not translator_cls:
                # Fallback to Gemini Playwright if available
                translator_cls = TRANSLATORS.module_dict.get("Gemini Playwright")
            
            if not translator_cls:
                # Fallback to first available
                keys = list(TRANSLATORS.module_dict.keys())
                if keys:
                    translator_cls = TRANSLATORS.module_dict.get(keys[0])

            if not translator_cls:
                self.task_completed.emit(False, f"Translator '{self.translator_engine}' not found.")
                return

            # Instantiate translator
            translator = translator_cls(
                lang_source=self.source_lang,
                lang_target=self.target_lang,
                raise_unsupported_lang=False
            )

            if hasattr(translator, 'set_stop_event'):
                translator.set_stop_event(self._stop_event)

            for idx, pagename in enumerate(pages_to_run):
                if self._stop_event.is_set():
                    self.task_completed.emit(False, "Translation cancelled by user.")
                    return

                self.progress.emit(idx + 1, total, f"Translating {pagename} ({idx + 1}/{total})...")

                blocks = proj.pages.get(pagename, [])
                if blocks:
                    if self.target_block_indices is not None and len(pages_to_run) == 1:
                        target_blks = [
                            blocks[i] for i in self.target_block_indices
                            if 0 <= i < len(blocks)
                        ]
                        if target_blks:
                            translator.translate_textblk_lst(
                                target_blks,
                                project=proj,
                                page_key=pagename,
                                full_page=False
                            )
                    else:
                        translator.translate_textblk_lst(
                            blocks,
                            project=proj,
                            page_key=pagename,
                            full_page=True
                        )

                self.page_finished.emit(pagename, blocks)

            # Save updated project JSON
            proj.save()
            self.task_completed.emit(True, f"Successfully translated {total} page(s).")

        except Exception as e:
            LOGGER.error(f"Translation worker error: {e}", exc_info=True)
            self.task_completed.emit(False, f"Translation error: {str(e)}")
