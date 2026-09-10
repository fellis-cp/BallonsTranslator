import unittest
import sys
import os
import os.path as osp
import tempfile
import shutil
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from qtpy.QtWidgets import QApplication, QWidget
from READER.ui.loading_overlay import LoadingOverlay, SpinnerWidget
from READER.ui.main_window import ReaderMainWindow


class TestReaderUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_spinner_widget_lifecycle(self):
        parent = QWidget()
        spinner = SpinnerWidget(parent)
        self.assertFalse(spinner._timer.isActive())
        spinner.start()
        self.assertTrue(spinner._timer.isActive())
        spinner._rotate()
        self.assertGreaterEqual(spinner._angle, 0)
        spinner.stop()
        self.assertFalse(spinner._timer.isActive())

    def test_loading_overlay(self):
        parent = QWidget()
        parent.resize(800, 600)
        overlay = LoadingOverlay(parent)
        self.assertTrue(overlay.isHidden())

        overlay.start_loading("Opening BalloonsTranslator", "Launching workspace...", total=0)
        self.assertFalse(overlay.isHidden())
        self.assertEqual(overlay.lbl_title.text(), "Opening BalloonsTranslator")
        self.assertEqual(overlay.lbl_subtitle.text(), "Launching workspace...")
        self.assertTrue(overlay.spinner._timer.isActive())

        overlay.stop_loading()
        self.assertTrue(overlay.isHidden())
        self.assertFalse(overlay.spinner._timer.isActive())

    def test_launch_translator_shows_loading(self):
        window = ReaderMainWindow(translated_dir=self.tmp_dir)
        manga_dir = osp.join(self.tmp_dir, "Test Author", "Test Manga")
        os.makedirs(manga_dir, exist_ok=True)

        with patch("subprocess.Popen") as mock_popen, \
             patch("os.path.exists", return_value=True):
            mock_popen.return_value = MagicMock()
            window.launch_translator_for_manga(manga_dir)
            self.assertFalse(window.loading_overlay.isHidden())
            self.assertEqual(window.loading_overlay.lbl_title.text(), "Opening BalloonsTranslator")
            self.assertIn("Test Manga", window.loading_overlay.lbl_subtitle.text())

            # Trigger timeout callback
            window._on_launch_completed()
            self.assertTrue(window.loading_overlay.isHidden())


if __name__ == '__main__':
    unittest.main()
