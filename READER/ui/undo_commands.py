import copy
import logging
from typing import Optional, List, Dict, Any, Tuple

try:
    from qtpy.QtWidgets import QUndoCommand
except ImportError:
    from qtpy.QtGui import QUndoCommand

from READER.core.style_utils import copy_fontformat, apply_fontformat_to_block, generate_block_rich_text

LOGGER = logging.getLogger('READER.undo_commands')


def _find_block_idx(blocks: List[Any], block: Any, fallback_idx: int) -> int:
    """Find index of block by object identity, falling back to index."""
    if blocks:
        for i, b in enumerate(blocks):
            if b is block:
                return i
        if 0 <= fallback_idx < len(blocks):
            return fallback_idx
    return -1


class BaseReaderUndoCommand(QUndoCommand):
    """Base class for reader undo commands with page-awareness."""

    def __init__(self, reader_view: Any, page_idx: int, text: str = ""):
        super().__init__(text)
        self.reader_view = reader_view
        self.page_idx = page_idx

    def _ensure_page(self) -> Optional[Any]:
        """Navigate to the command's page if not already viewing it."""
        if self.reader_view is None or self.reader_view.project_data is None:
            return None
        if self.reader_view.current_page_idx != self.page_idx:
            self.reader_view.ensure_page(self.page_idx)
        return self.reader_view.project_data.get_page(self.page_idx)


class AddBlockCommand(BaseReaderUndoCommand):
    """Command to add a text block to a manga page."""

    def __init__(self, reader_view: Any, page_idx: int, block_idx: int, block: Any):
        super().__init__(reader_view, page_idx, f"Add Block #{block_idx + 1}")
        self.block_idx = block_idx
        self.block = block
        self._first_run = True

    def redo(self) -> None:
        if self._first_run:
            # Block was already added during mouseReleaseEvent
            self._first_run = False
            return
        page = self._ensure_page()
        if page is not None:
            if page.blocks is None:
                page.blocks = []
            if self.block not in page.blocks:
                idx = min(self.block_idx, len(page.blocks))
                page.blocks.insert(idx, self.block)
                self.reader_view.on_page_data_changed(select_idx=idx)

    def undo(self) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            idx = _find_block_idx(page.blocks, self.block, self.block_idx)
            if 0 <= idx < len(page.blocks):
                page.blocks.pop(idx)
                self.reader_view.on_page_data_changed(select_idx=-1)


class DeleteBlockCommand(BaseReaderUndoCommand):
    """Command to delete a text block from a manga page."""

    def __init__(self, reader_view: Any, page_idx: int, block_idx: int, block: Any):
        super().__init__(reader_view, page_idx, f"Delete Block #{block_idx + 1}")
        self.block_idx = block_idx
        self.block = block

    def redo(self) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            idx = _find_block_idx(page.blocks, self.block, self.block_idx)
            if 0 <= idx < len(page.blocks):
                page.blocks.pop(idx)
                self.reader_view.on_page_data_changed(select_idx=-1)

    def undo(self) -> None:
        page = self._ensure_page()
        if page is not None:
            if page.blocks is None:
                page.blocks = []
            idx = min(self.block_idx, len(page.blocks))
            page.blocks.insert(idx, self.block)
            self.reader_view.on_page_data_changed(select_idx=idx)


class MoveResizeBlockCommand(BaseReaderUndoCommand):
    """Command to move or resize a text block."""

    def __init__(
        self,
        reader_view: Any,
        page_idx: int,
        block_idx: int,
        old_rect: List[int],
        new_rect: List[int],
        block: Optional[Any] = None,
    ):
        super().__init__(reader_view, page_idx, f"Move/Resize Block #{block_idx + 1}")
        self.block_idx = block_idx
        self.old_rect = list(old_rect)  # [x, y, w, h]
        self.new_rect = list(new_rect)
        self.block = block

    def _apply_rect(self, rect: List[int]) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            idx = _find_block_idx(page.blocks, self.block, self.block_idx)
            if 0 <= idx < len(page.blocks):
                blk = page.blocks[idx]
                x, y, w, h = rect
                xyxy = [x, y, x + w, y + h]
                if hasattr(blk, 'xyxy'):
                    blk.xyxy = xyxy
                if hasattr(blk, '_bounding_rect'):
                    blk._bounding_rect = [x, y, w, h]
                elif isinstance(blk, dict):
                    blk['xyxy'] = xyxy
                    blk['_bounding_rect'] = [x, y, w, h]
                self.reader_view.on_block_geometry_updated(idx)

    def redo(self) -> None:
        self._apply_rect(self.new_rect)

    def undo(self) -> None:
        self._apply_rect(self.old_rect)


class EditTextBlockCommand(BaseReaderUndoCommand):
    """Command to edit original text or translation of a text block."""

    def __init__(
        self,
        reader_view: Any,
        page_idx: int,
        block_idx: int,
        field: str,
        old_val: Any,
        new_val: Any,
        block: Optional[Any] = None,
    ):
        super().__init__(reader_view, page_idx, f"Edit {field.title()} #{block_idx + 1}")
        self.block_idx = block_idx
        self.field = field
        self.old_val = copy.deepcopy(old_val)
        self.new_val = copy.deepcopy(new_val)
        self.block = block

    def _apply_val(self, val: Any) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            idx = _find_block_idx(page.blocks, self.block, self.block_idx)
            if 0 <= idx < len(page.blocks):
                blk = page.blocks[idx]
                if self.field == 'text':
                    lines = val if isinstance(val, list) else (val.split('\n') if val else [])
                    if hasattr(blk, 'text'):
                        blk.text = lines
                    elif isinstance(blk, dict):
                        blk['text'] = lines
                elif self.field == 'translation':
                    trans_str = str(val or "")
                    if hasattr(blk, 'translation'):
                        blk.translation = trans_str
                    elif isinstance(blk, dict):
                        blk['translation'] = trans_str
                    generate_block_rich_text(blk)

                self.reader_view.on_block_text_updated(idx)

    def redo(self) -> None:
        self._apply_val(self.new_val)

    def undo(self) -> None:
        self._apply_val(self.old_val)


class ApplyStyleCommand(BaseReaderUndoCommand):
    """Command to apply font formatting and style to one or more text blocks."""

    def __init__(
        self,
        reader_view: Any,
        page_idx: int,
        target_indices: List[int],
        old_states: Dict[int, Tuple[Any, str]],  # {block_idx: (copy_fontformat(fontformat), rich_text)}
        new_format: Any,
        blocks_map: Optional[Dict[int, Any]] = None,
    ):
        super().__init__(reader_view, page_idx, "Apply Font Style")
        self.target_indices = list(target_indices)
        self.old_states = old_states
        self.new_format = copy_fontformat(new_format)
        self.blocks_map = blocks_map or {}

    def redo(self) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            for orig_idx in self.target_indices:
                blk_ref = self.blocks_map.get(orig_idx)
                idx = _find_block_idx(page.blocks, blk_ref, orig_idx)
                if 0 <= idx < len(page.blocks):
                    blk = page.blocks[idx]
                    apply_fontformat_to_block(blk, self.new_format, generate_rich_text=True, preserve_size=True)
            self.reader_view.on_page_data_changed(select_idx=-1)

    def undo(self) -> None:
        page = self._ensure_page()
        if page is not None and page.blocks:
            for orig_idx, (old_fmt, old_rt) in self.old_states.items():
                blk_ref = self.blocks_map.get(orig_idx)
                idx = _find_block_idx(page.blocks, blk_ref, orig_idx)
                if 0 <= idx < len(page.blocks):
                    blk = page.blocks[idx]
                    apply_fontformat_to_block(blk, old_fmt, generate_rich_text=False, preserve_size=False)
                    if hasattr(blk, 'rich_text'):
                        blk.rich_text = old_rt
                    elif isinstance(blk, dict):
                        blk['rich_text'] = old_rt
            self.reader_view.on_page_data_changed(select_idx=-1)
