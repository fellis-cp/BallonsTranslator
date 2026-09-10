import os
import os.path as osp
import logging
import threading
from typing import List, Optional, Any

from qtpy.QtCore import QThread, Signal

from READER.core.loader import load_manga_project, MangaPage, MangaProjectData
from READER.core.style_utils import get_reference_fontformat, apply_fontformat_to_block, generate_block_rich_text

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

HAS_OCR_MODULES = False
OCR_ENGINE_LIST: List[str] = []
try:
    from ballontranslator.modules import OCR, GET_VALID_OCR
    from ballontranslator.utils.textblock import TextBlock
    from ballontranslator.utils.io_utils import imread
    HAS_OCR_MODULES = True
    available_ocr = GET_VALID_OCR()
    if available_ocr:
        OCR_ENGINE_LIST = list(available_ocr)
        # Prioritize fast & reliable manga OCR engines in default ordering
        priority_engines = ["ppv6_onnx", "PaddleOCRVLManga", "hayai_ocr_v2", "manga_ocr", "mit48px_ctc", "mit48px"]
        for pe in reversed(priority_engines):
            if pe in OCR_ENGINE_LIST:
                OCR_ENGINE_LIST.remove(pe)
                OCR_ENGINE_LIST.insert(0, pe)
except ImportError:
    OCR = None
    TextBlock = None
    imread = None


class OCRTaskWorker(QThread):
    """Background worker thread for running OCR on manga text blocks."""

    progress = Signal(int, int, str)
    block_finished = Signal(int, str)      # (block_idx, recognized_text)
    task_completed = Signal(bool, str)     # (success, message)

    def __init__(
        self,
        image_path: str,
        blocks: List[Any],
        target_block_indices: Optional[List[int]] = None,
        ocr_engine: str = "ppv6_onnx",
        parent=None,
    ):
        super().__init__(parent)
        self.image_path = image_path
        self.blocks = blocks
        self.target_block_indices = target_block_indices  # None means all blocks in list
        self.ocr_engine = ocr_engine
        self._stop_event = threading.Event()

    def request_cancel(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            # Ensure CWD is workspace root so relative data/models paths work properly
            workspace_dir = osp.abspath(osp.join(osp.dirname(__file__), '..', '..'))
            if osp.exists(workspace_dir):
                os.chdir(workspace_dir)

            if not HAS_OCR_MODULES or not OCR:
                self.task_completed.emit(False, "OCR modules unavailable.")
                return

            if not osp.exists(self.image_path):
                self.task_completed.emit(False, f"Image file not found: {self.image_path}")
                return

            # Read image in RGB format
            try:
                if imread is not None:
                    img_rgb = imread(self.image_path)
                else:
                    import cv2
                    img_bgr = cv2.imread(self.image_path)
                    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            except Exception as e:
                import cv2
                img_bgr = cv2.imread(self.image_path)
                if img_bgr is None:
                    self.task_completed.emit(False, f"Failed to load image: {e}")
                    return
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

            indices = self.target_block_indices if self.target_block_indices is not None else list(range(len(self.blocks)))
            total = len(indices)
            if total == 0:
                self.task_completed.emit(True, "No text blocks to OCR.")
                return

            self.progress.emit(0, total, f"Initializing OCR engine ({self.ocr_engine})...")

            # Resolve OCR module (handles LazyModuleSpec)
            spec_or_cls = OCR.module_dict.get(self.ocr_engine)
            if not spec_or_cls and OCR_ENGINE_LIST:
                for candidate in OCR_ENGINE_LIST:
                    spec_or_cls = OCR.module_dict.get(candidate)
                    if spec_or_cls:
                        break

            if not spec_or_cls:
                self.task_completed.emit(False, f"OCR engine '{self.ocr_engine}' not available.")
                return

            try:
                ocr_cls = spec_or_cls.resolve() if hasattr(spec_or_cls, 'resolve') else spec_or_cls
                ocr_inst = ocr_cls()
            except Exception as e:
                self.task_completed.emit(False, f"Failed to initialize OCR engine '{self.ocr_engine}': {e}")
                return

            for i, blk_idx in enumerate(indices):
                if self._stop_event.is_set():
                    self.task_completed.emit(False, "OCR cancelled by user.")
                    return

                if blk_idx < 0 or blk_idx >= len(self.blocks):
                    continue

                blk = self.blocks[blk_idx]
                self.progress.emit(i, total, f"Running OCR on block #{blk_idx + 1} ({i+1}/{total})...")

                if TextBlock and not isinstance(blk, TextBlock):
                    xyxy = blk.get('xyxy', [0, 0, 100, 100])
                    tb = TextBlock(xyxy=xyxy)
                else:
                    tb = blk

                try:
                    ocr_inst.run_ocr(img_rgb, [tb])
                    if hasattr(tb, 'get_text'):
                        text_str = tb.get_text()
                    elif hasattr(tb, 'text') and isinstance(tb.text, list):
                        text_str = "\n".join(tb.text)
                    elif isinstance(tb, dict):
                        text_str = "\n".join(tb.get('text', []))
                    else:
                        text_str = str(getattr(tb, 'text', ''))

                    # Sync recognized text back to the input block instance
                    if hasattr(blk, 'text'):
                        blk.text = text_str.split('\n') if text_str else []
                    elif isinstance(blk, dict):
                        blk['text'] = text_str.split('\n') if text_str else []

                    self.block_finished.emit(blk_idx, text_str)
                except Exception as e:
                    LOGGER.warning(f"OCR failed for block #{blk_idx}: {e}")

            self.progress.emit(total, total, "OCR complete.")
            self.task_completed.emit(True, f"OCR finished for {total} block(s).")
        except Exception as e:
            LOGGER.exception("OCR task worker encountered error")
            self.task_completed.emit(False, f"OCR error: {str(e)}")


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
            workspace_dir = osp.abspath(osp.join(osp.dirname(__file__), '..', '..'))
            if osp.exists(workspace_dir):
                os.chdir(workspace_dir)

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
            spec_or_cls = TRANSLATORS.module_dict.get(self.translator_engine)
            if not spec_or_cls:
                # Fallback to Gemini Playwright if available
                spec_or_cls = TRANSLATORS.module_dict.get("Gemini Playwright")
            
            if not spec_or_cls:
                # Fallback to first available
                keys = list(TRANSLATORS.module_dict.keys())
                if keys:
                    spec_or_cls = TRANSLATORS.module_dict.get(keys[0])

            if not spec_or_cls:
                self.task_completed.emit(False, f"Translator '{self.translator_engine}' not found.")
                return

            try:
                translator_cls = spec_or_cls.resolve() if hasattr(spec_or_cls, 'resolve') else spec_or_cls
            except Exception as e:
                LOGGER.error(f"Failed to resolve translator class for '{self.translator_engine}': {e}", exc_info=True)
                self.task_completed.emit(False, f"Failed to load '{self.translator_engine}': {e}")
                return

            # Instantiate translator
            try:
                translator = translator_cls(
                    lang_source=self.source_lang,
                    lang_target=self.target_lang,
                    raise_unsupported_lang=False
                )
            except Exception as e:
                LOGGER.error(f"Failed to instantiate translator '{self.translator_engine}': {e}", exc_info=True)
                self.task_completed.emit(False, f"Failed to initialize '{self.translator_engine}': {e}")
                return

            if hasattr(translator, 'set_stop_event'):
                translator.set_stop_event(self._stop_event)

            for idx, pagename in enumerate(pages_to_run):
                if self._stop_event.is_set():
                    self.task_completed.emit(False, "Translation cancelled by user.")
                    return

                self.progress.emit(idx + 1, total, f"Translating {pagename} ({idx + 1}/{total})...")

                blocks = proj.pages.get(pagename, [])
                if blocks:
                    # Convert raw dicts to TextBlock if needed
                    converted_blocks = []
                    for blk in blocks:
                        if TextBlock and not isinstance(blk, TextBlock):
                            tb = TextBlock(
                                xyxy=blk.get('xyxy', [0, 0, 100, 100]),
                                text=blk.get('text', []),
                                translation=blk.get('translation', ''),
                            )
                            converted_blocks.append(tb)
                        else:
                            converted_blocks.append(blk)
                    proj.pages[pagename] = converted_blocks
                    blocks = converted_blocks

                    # Find reference styling across the project/page
                    ref_fmt = None
                    for p_blks in proj.pages.values():
                        for b in p_blks:
                            fmt = getattr(b, 'fontformat', None)
                            if fmt and (getattr(fmt, 'stroke_width', 0) > 0 or getattr(fmt, 'alignment', 0) == 1):
                                ref_fmt = fmt
                                break
                        if ref_fmt:
                            break
                    if not ref_fmt:
                        ref_fmt = get_reference_fontformat(project_data=proj)

                    if self.target_block_indices is not None and len(pages_to_run) == 1:
                        target_blks = [
                            blocks[i] for i in self.target_block_indices
                            if 0 <= i < len(blocks)
                        ]
                        if target_blks:
                            # Apply reference styling to any unstyled target block
                            if ref_fmt:
                                for b in target_blks:
                                    bfmt = getattr(b, 'fontformat', None)
                                    if bfmt is None or (getattr(bfmt, 'stroke_width', 0) == 0 and getattr(bfmt, 'alignment', 0) == 0):
                                        apply_fontformat_to_block(b, ref_fmt, generate_rich_text=False, preserve_size=True)

                            translator.translate_textblk_lst(
                                target_blks,
                                project=proj,
                                page_key=pagename,
                                full_page=False
                            )
                            for b in target_blks:
                                generate_block_rich_text(b)
                    else:
                        # Apply reference styling to any unstyled block
                        if ref_fmt:
                            for b in blocks:
                                bfmt = getattr(b, 'fontformat', None)
                                if bfmt is None or (getattr(bfmt, 'stroke_width', 0) == 0 and getattr(bfmt, 'alignment', 0) == 0):
                                    apply_fontformat_to_block(b, ref_fmt, generate_rich_text=False, preserve_size=True)

                        translator.translate_textblk_lst(
                            blocks,
                            project=proj,
                            page_key=pagename,
                            full_page=True
                        )
                        for b in blocks:
                            generate_block_rich_text(b)

                self.page_finished.emit(pagename, blocks)

            # Save updated project JSON
            proj.save()
            self.task_completed.emit(True, f"Successfully translated {total} page(s).")

        except Exception as e:
            LOGGER.error(f"Translation worker error: {e}", exc_info=True)
            self.task_completed.emit(False, f"Translation error: {str(e)}")
