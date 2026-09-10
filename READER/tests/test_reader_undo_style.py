"""Unit tests for READER undo/redo commands and style inheritance."""
import copy
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Minimal stubs so tests run without Qt or BallonsTranslator installed
# ---------------------------------------------------------------------------

class _FakeFontFormat:
    """Minimal FontFormat stand-in."""
    def __init__(self, family="Comic Sans", stroke_width=3.0):
        self.font_family = family
        self.stroke_width = stroke_width
        self.font_size = 24.0
        self.srgb = [200, 50, 50]
        self.frgb = [255, 255, 255]
        self.italic = False
        self.font_weight = 700
        self.alignment = 1
        self.line_spacing = 1.2
        self.letter_spacing = 0.0
        self.text_effects = None


class _FakeTextBlock:
    """Minimal TextBlock stand-in."""
    def __init__(self, xyxy=(10, 20, 110, 70)):
        self.xyxy = list(xyxy)
        self._bounding_rect = [xyxy[0], xyxy[1], xyxy[2] - xyxy[0], xyxy[3] - xyxy[1]]
        self.text = []
        self.translation = ""
        self.rich_text = ""
        self.fontformat = _FakeFontFormat()


class _FakePage:
    def __init__(self, blocks=None):
        self.blocks = blocks if blocks is not None else []
        self.page_name = "test_page.png"


class _FakeProjectData:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.title = "TestManga"

    def get_page(self, idx):
        if 0 <= idx < len(self.pages):
            return self.pages[idx]
        return None


# ---------------------------------------------------------------------------
# Patch Qt and heavy imports before importing undo_commands / style_utils
# ---------------------------------------------------------------------------
import sys
import types

def _install_qt_stubs():
    """Install minimal stubs so modules load without Qt."""
    # QUndoCommand stub
    class QUndoCommand:
        def __init__(self, text=""):
            self._text = text
        def redo(self): pass
        def undo(self): pass

    # qtpy.QtWidgets stub
    qtpy_mod = types.ModuleType("qtpy")
    widgets_mod = types.ModuleType("qtpy.QtWidgets")
    widgets_mod.QUndoCommand = QUndoCommand
    sys.modules.setdefault("qtpy", qtpy_mod)
    sys.modules.setdefault("qtpy.QtWidgets", widgets_mod)

    # BallonsTranslator stubs
    bt_mod = types.ModuleType("ballontranslator")
    bt_utils = types.ModuleType("ballontranslator.utils")
    bt_textblock = types.ModuleType("ballontranslator.utils.textblock")
    bt_textblock.TextBlock = _FakeTextBlock
    bt_ff = types.ModuleType("ballontranslator.utils.fontformat")
    bt_ff.FontFormat = _FakeFontFormat
    bt_ui = types.ModuleType("ballontranslator.ui")
    bt_te = types.ModuleType("ballontranslator.ui.text_engine")
    bt_te_ann = types.ModuleType("ballontranslator.ui.text_engine.annotations")
    bt_te_ann.to_rich_text_html = None
    bt_te_pf = types.ModuleType("ballontranslator.ui.text_engine.pipeline_formatting")
    bt_te_pf._load_text_block_document = None

    for name, mod in [
        ("ballontranslator", bt_mod),
        ("ballontranslator.utils", bt_utils),
        ("ballontranslator.utils.textblock", bt_textblock),
        ("ballontranslator.utils.fontformat", bt_ff),
        ("ballontranslator.ui", bt_ui),
        ("ballontranslator.ui.text_engine", bt_te),
        ("ballontranslator.ui.text_engine.annotations", bt_te_ann),
        ("ballontranslator.ui.text_engine.pipeline_formatting", bt_te_pf),
    ]:
        sys.modules.setdefault(name, mod)


_install_qt_stubs()

# Now import the modules under test
from READER.core.style_utils import (
    get_reference_fontformat,
    apply_fontformat_to_block,
    copy_fontformat,
    generate_block_rich_text,
)
from READER.ui.undo_commands import (
    _find_block_idx,
    AddBlockCommand,
    DeleteBlockCommand,
    MoveResizeBlockCommand,
    EditTextBlockCommand,
    ApplyStyleCommand,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader_view(page_idx=0, page=None):
    """Return a minimal reader_view mock that satisfies undo command callbacks."""
    rv = MagicMock()
    rv.current_page_idx = page_idx
    rv.project_data = _FakeProjectData(pages=[page or _FakePage()])
    rv.project_data.get_page = lambda idx: rv.project_data.pages[idx] if 0 <= idx < len(rv.project_data.pages) else None
    # ensure_page does nothing for now
    rv.ensure_page = MagicMock()
    return rv


# ---------------------------------------------------------------------------
# Tests: style_utils
# ---------------------------------------------------------------------------

class TestStyleUtils(unittest.TestCase):

    def test_copy_fontformat_dict(self):
        """copy_fontformat on a dict returns a deep copy."""
        d = {"font_family": "Arial", "stroke_width": 2.5}
        c = copy_fontformat(d)
        self.assertEqual(c["font_family"], "Arial")
        c["font_family"] = "Helvetica"
        self.assertEqual(d["font_family"], "Arial", "original must not be mutated")

    def test_copy_fontformat_object(self):
        """copy_fontformat on a FontFormat-like object returns a deep copy."""
        ff = _FakeFontFormat()
        c = copy_fontformat(ff)
        self.assertEqual(c.stroke_width, ff.stroke_width)
        c.stroke_width = 99.0
        self.assertNotEqual(ff.stroke_width, 99.0, "original must not be mutated")

    def test_copy_fontformat_none(self):
        """copy_fontformat(None) returns None."""
        self.assertIsNone(copy_fontformat(None))

    def test_get_reference_fontformat_from_page_block(self):
        """Should return the best-rated block fontformat on current page."""
        blk = _FakeTextBlock()
        blk.fontformat.stroke_width = 5.0  # high quality
        page = _FakePage(blocks=[blk])
        ref = get_reference_fontformat(current_page=page)
        self.assertIsNotNone(ref, "Expected a reference FontFormat")

    def test_get_reference_fontformat_no_blocks(self):
        """Returns None/default when no blocks exist on page or project.

        Without BallonsTranslator config available, style_utils falls back to a
        built-in FontFormat default ("Microsoft YaHei UI") when FontFormat is
        importable, or returns None when it is not.  In either case the result
        must not raise, and when a value is returned it must have stroke_width.
        """
        page = _FakePage(blocks=[])
        ref = get_reference_fontformat(current_page=page)
        # Acceptable outcomes: None, or a format object with stroke_width
        if ref is not None:
            sw = getattr(ref, 'stroke_width', None)
            if sw is None and isinstance(ref, dict):
                sw = ref.get('stroke_width')
            self.assertIsNotNone(sw, "Returned format must have stroke_width")

    def test_get_reference_fontformat_falls_back_to_project(self):
        """Falls back to project-level blocks when current page has no blocks."""
        other_blk = _FakeTextBlock()
        other_blk.fontformat.stroke_width = 8.0
        other_page = _FakePage(blocks=[other_blk])

        empty_page = _FakePage(blocks=[])
        proj = _FakeProjectData(pages=[empty_page, other_page])

        ref = get_reference_fontformat(current_page=empty_page, project_data=proj)
        self.assertIsNotNone(ref, "Should find fontformat on another page")

    def test_apply_fontformat_to_block_copies_fields(self):
        """apply_fontformat_to_block should copy font_family and stroke_width."""
        src_fmt = _FakeFontFormat(family="Noto Sans", stroke_width=4.0)
        target = _FakeTextBlock()
        target.fontformat.stroke_width = 0.0  # bare default

        apply_fontformat_to_block(target, src_fmt, generate_rich_text=False, preserve_size=False)

        self.assertEqual(target.fontformat.stroke_width, 4.0)
        # family should also be copied
        self.assertEqual(target.fontformat.font_family, "Noto Sans")

    def test_generate_block_rich_text_no_engine(self):
        """generate_block_rich_text returns empty string when text engine is unavailable."""
        blk = _FakeTextBlock()
        blk.translation = "Hello"
        result = generate_block_rich_text(blk)
        # Without the full BallonsTranslator engine, returns "" or the translation
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# Tests: _find_block_idx
# ---------------------------------------------------------------------------

class TestFindBlockIdx(unittest.TestCase):

    def test_finds_by_identity(self):
        blk_a = _FakeTextBlock()
        blk_b = _FakeTextBlock()
        blk_c = _FakeTextBlock()
        blocks = [blk_a, blk_b, blk_c]
        self.assertEqual(_find_block_idx(blocks, blk_c, 0), 2)

    def test_falls_back_to_index_when_no_match(self):
        """When block is not in list, returns the fallback index."""
        outsider = _FakeTextBlock()
        blocks = [_FakeTextBlock(), _FakeTextBlock()]
        self.assertEqual(_find_block_idx(blocks, outsider, 1), 1)

    def test_returns_minus_one_when_empty(self):
        self.assertEqual(_find_block_idx([], _FakeTextBlock(), 0), -1)

    def test_returns_minus_one_when_fallback_out_of_range(self):
        blocks = [_FakeTextBlock()]
        self.assertEqual(_find_block_idx(blocks, _FakeTextBlock(), 99), -1)


# ---------------------------------------------------------------------------
# Tests: AddBlockCommand
# ---------------------------------------------------------------------------

class TestAddBlockCommand(unittest.TestCase):

    def _make(self, blocks=None):
        page = _FakePage(blocks=blocks or [])
        rv = _make_reader_view(page=page)
        blk = _FakeTextBlock()
        page.blocks.append(blk)
        cmd = AddBlockCommand(rv, 0, 0, blk)
        return rv, page, cmd, blk

    def test_first_redo_is_noop(self):
        """First redo() should be a no-op because the block was already added."""
        rv, page, cmd, blk = self._make()
        pre_len = len(page.blocks)
        cmd.redo()
        self.assertEqual(len(page.blocks), pre_len, "Block must not be added twice")
        rv.on_page_data_changed.assert_not_called()

    def test_undo_removes_block(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()  # first pass: noop
        cmd.undo()
        self.assertNotIn(blk, page.blocks)
        rv.on_page_data_changed.assert_called_once_with(select_idx=-1)

    def test_second_redo_re_adds_block(self):
        rv, page, cmd, blk = self._make(blocks=[])
        cmd.redo()  # noop
        cmd.undo()
        cmd.redo()  # should re-add
        self.assertIn(blk, page.blocks)


# ---------------------------------------------------------------------------
# Tests: DeleteBlockCommand
# ---------------------------------------------------------------------------

class TestDeleteBlockCommand(unittest.TestCase):

    def _make(self):
        blk = _FakeTextBlock()
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)
        cmd = DeleteBlockCommand(rv, 0, 0, blk)
        return rv, page, cmd, blk

    def test_redo_removes_block(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()
        self.assertNotIn(blk, page.blocks)
        rv.on_page_data_changed.assert_called_once_with(select_idx=-1)

    def test_undo_restores_block(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()
        cmd.undo()
        self.assertIn(blk, page.blocks)
        rv.on_page_data_changed.assert_called_with(select_idx=0)

    def test_undo_redo_cycle(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()
        cmd.undo()
        cmd.redo()
        self.assertNotIn(blk, page.blocks)


# ---------------------------------------------------------------------------
# Tests: MoveResizeBlockCommand
# ---------------------------------------------------------------------------

class TestMoveResizeBlockCommand(unittest.TestCase):

    def _make(self):
        blk = _FakeTextBlock(xyxy=(0, 0, 100, 50))
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)
        old_rect = [0, 0, 100, 50]
        new_rect = [20, 30, 80, 40]
        cmd = MoveResizeBlockCommand(rv, 0, 0, old_rect, new_rect, block=blk)
        return rv, page, cmd, blk

    def test_redo_applies_new_rect(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()
        self.assertEqual(blk._bounding_rect, [20, 30, 80, 40])
        rv.on_block_geometry_updated.assert_called_once_with(0)

    def test_undo_restores_old_rect(self):
        rv, page, cmd, blk = self._make()
        cmd.redo()
        rv.on_block_geometry_updated.reset_mock()
        cmd.undo()
        self.assertEqual(blk._bounding_rect, [0, 0, 100, 50])
        rv.on_block_geometry_updated.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# Tests: EditTextBlockCommand
# ---------------------------------------------------------------------------

class TestEditTextBlockCommand(unittest.TestCase):

    def _make_translation(self):
        blk = _FakeTextBlock()
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)
        cmd = EditTextBlockCommand(rv, 0, 0, 'translation', "old text", "new text", block=blk)
        return rv, page, cmd, blk

    def test_redo_sets_new_translation(self):
        rv, page, cmd, blk = self._make_translation()
        cmd.redo()
        self.assertEqual(blk.translation, "new text")
        rv.on_block_text_updated.assert_called_once_with(0)

    def test_undo_restores_old_translation(self):
        rv, page, cmd, blk = self._make_translation()
        cmd.redo()
        rv.on_block_text_updated.reset_mock()
        cmd.undo()
        self.assertEqual(blk.translation, "old text")
        rv.on_block_text_updated.assert_called_once_with(0)

    def test_redo_undo_cycle_text_field(self):
        blk = _FakeTextBlock()
        blk.text = ["old line"]
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)
        cmd = EditTextBlockCommand(rv, 0, 0, 'text', ["old line"], ["new", "lines"], block=blk)
        cmd.redo()
        self.assertEqual(blk.text, ["new", "lines"])
        cmd.undo()
        self.assertEqual(blk.text, ["old line"])


# ---------------------------------------------------------------------------
# Tests: ApplyStyleCommand
# ---------------------------------------------------------------------------

class TestApplyStyleCommand(unittest.TestCase):

    def test_redo_applies_new_format(self):
        blk = _FakeTextBlock()
        blk.fontformat.stroke_width = 0.0
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)

        new_fmt = _FakeFontFormat(stroke_width=5.0)
        old_states = {0: (copy_fontformat(blk.fontformat), "")}
        blocks_map = {0: blk}

        cmd = ApplyStyleCommand(rv, 0, [0], old_states, new_fmt, blocks_map=blocks_map)
        cmd.redo()

        self.assertEqual(blk.fontformat.stroke_width, 5.0)
        rv.on_page_data_changed.assert_called_with(select_idx=-1)

    def test_undo_restores_old_format(self):
        blk = _FakeTextBlock()
        blk.fontformat.stroke_width = 0.0
        page = _FakePage(blocks=[blk])
        rv = _make_reader_view(page=page)

        new_fmt = _FakeFontFormat(stroke_width=7.0)
        old_states = {0: (copy_fontformat(blk.fontformat), "saved_rich_text")}
        blocks_map = {0: blk}

        cmd = ApplyStyleCommand(rv, 0, [0], old_states, new_fmt, blocks_map=blocks_map)
        cmd.redo()
        rv.on_page_data_changed.reset_mock()
        cmd.undo()

        self.assertEqual(blk.fontformat.stroke_width, 0.0)
        self.assertEqual(blk.rich_text, "saved_rich_text")
        rv.on_page_data_changed.assert_called_with(select_idx=-1)

    def test_apply_to_multiple_blocks(self):
        blk_a = _FakeTextBlock()
        blk_b = _FakeTextBlock()
        for b in (blk_a, blk_b):
            b.fontformat.stroke_width = 0.0
        page = _FakePage(blocks=[blk_a, blk_b])
        rv = _make_reader_view(page=page)

        new_fmt = _FakeFontFormat(stroke_width=4.0)
        old_states = {
            0: (copy_fontformat(blk_a.fontformat), ""),
            1: (copy_fontformat(blk_b.fontformat), ""),
        }
        blocks_map = {0: blk_a, 1: blk_b}

        cmd = ApplyStyleCommand(rv, 0, [0, 1], old_states, new_fmt, blocks_map=blocks_map)
        cmd.redo()
        self.assertEqual(blk_a.fontformat.stroke_width, 4.0)
        self.assertEqual(blk_b.fontformat.stroke_width, 4.0)

        cmd.undo()
        self.assertEqual(blk_a.fontformat.stroke_width, 0.0)
        self.assertEqual(blk_b.fontformat.stroke_width, 0.0)


if __name__ == "__main__":
    unittest.main()
