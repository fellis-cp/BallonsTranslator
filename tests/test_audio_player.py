import os
import os.path as osp
import tempfile
import unittest
from pathlib import Path

from qtpy.QtWidgets import QApplication
from qtpy.QtCore import Qt

from ballontranslator.utils.proj_imgtrans import ProjImgTrans
from ballontranslator.utils.config import ProgramConfig
from ballontranslator.ui.audio_player import PageAudioPlayer, AudioControlWidget


class ProjAudioLookupTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.proj_dir = self.temp_dir.name
        self.audio_dir = osp.join(self.proj_dir, 'audio')
        os.makedirs(self.audio_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_audio_dir_property(self):
        proj = ProjImgTrans()
        self.assertEqual(proj.audio_dir(), '')
        proj.directory = self.proj_dir
        self.assertEqual(proj.audio_dir(), self.audio_dir)

    def test_get_page_audio_by_stem(self):
        audio_file = osp.join(self.audio_dir, 'page_001.mp3')
        Path(audio_file).touch()

        proj = ProjImgTrans()
        proj.directory = self.proj_dir

        found = proj.get_page_audio_path('page_001.png')
        self.assertEqual(found, audio_file)

    def test_get_page_audio_by_full_name(self):
        audio_file = osp.join(self.audio_dir, 'chapter1.01.png.wav')
        Path(audio_file).touch()

        proj = ProjImgTrans()
        proj.directory = self.proj_dir

        found = proj.get_page_audio_path('chapter1.01.png')
        self.assertEqual(found, audio_file)

    def test_get_page_audio_case_insensitive(self):
        audio_file = osp.join(self.audio_dir, 'PAGE_002.MP3')
        Path(audio_file).touch()

        proj = ProjImgTrans()
        proj.directory = self.proj_dir

        found = proj.get_page_audio_path('page_002.jpg')
        self.assertEqual(found, audio_file)

    def test_get_page_audio_from_language_subfolder_opened_via_reader(self):
        # Language subdirectory created by READER (e.g. manga/IND/)
        lang_dir = osp.join(self.proj_dir, 'IND')
        lang_audio_dir = osp.join(lang_dir, 'audio')
        os.makedirs(lang_audio_dir, exist_ok=True)
        audio_file = osp.join(lang_audio_dir, 'page_003.mp3')
        Path(audio_file).touch()

        proj = ProjImgTrans()
        proj.directory = self.proj_dir
        proj.proj_path = osp.join(lang_dir, 'imgtrans_Test.json')

        found = proj.get_page_audio_path('page_003.png')
        self.assertEqual(found, audio_file)

    def test_get_page_audio_none_when_missing(self):
        proj = ProjImgTrans()
        proj.directory = self.proj_dir

        self.assertIsNone(proj.get_page_audio_path('nonexistent.png'))
        self.assertIsNone(proj.get_page_audio_path(None))


class AudioConfigTest(unittest.TestCase):

    def test_defaults(self):
        cfg = ProgramConfig()
        self.assertTrue(cfg.audio_autoplay)
        self.assertEqual(cfg.audio_volume, 100)
        self.assertFalse(cfg.audio_muted)

    def test_validation_discards_invalid(self):
        with tempfile.NamedTemporaryFile('w+', encoding='utf8') as temp:
            temp.write('{"audio_volume": -10, "audio_autoplay": "not_bool", "audio_muted": 123}')
            temp.flush()
            loaded = ProgramConfig.load(temp.name)

        # Invalid fields are discarded, falling back to safe defaults
        self.assertEqual(loaded.audio_volume, 100)
        self.assertTrue(loaded.audio_autoplay)
        self.assertFalse(loaded.audio_muted)

    def test_preserves_valid(self):
        with tempfile.NamedTemporaryFile('w+', encoding='utf8') as temp:
            temp.write('{"audio_volume": 65, "audio_autoplay": false, "audio_muted": true}')
            temp.flush()
            loaded = ProgramConfig.load(temp.name)

        self.assertEqual(loaded.audio_volume, 65)
        self.assertFalse(loaded.audio_autoplay)
        self.assertTrue(loaded.audio_muted)


class AudioPlayerAndWidgetTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.player = PageAudioPlayer()

    def tearDown(self):
        self.player.stop()
        self.temp_dir.cleanup()

    def test_on_playback_state_changed_with_pyqt6_enum(self):
        try:
            from qtpy.QtMultimedia import QMediaPlayer
            playing_state = QMediaPlayer.PlaybackState.PlayingState
            stopped_state = QMediaPlayer.PlaybackState.StoppedState
        except Exception:
            playing_state = 1
            stopped_state = 0

        states = []
        self.player.playback_state_changed.connect(states.append)

        self.player._on_playback_state_changed(playing_state)
        self.assertTrue(self.player.is_playing)
        self.assertEqual(states[-1], True)

        self.player._on_playback_state_changed(stopped_state)
        self.assertFalse(self.player.is_playing)
        self.assertEqual(states[-1], False)

    def test_player_volume_clamping(self):
        self.player.set_volume(150)
        self.assertEqual(self.player.volume, 100)

        self.player.set_volume(-20)
        self.assertEqual(self.player.volume, 0)

        self.player.set_volume(75)
        self.assertEqual(self.player.volume, 75)

    def test_player_mute_toggle(self):
        self.player.set_muted(False)
        self.assertFalse(self.player.is_muted)
        self.player.toggle_mute()
        self.assertTrue(self.player.is_muted)
        self.player.toggle_mute()
        self.assertFalse(self.player.is_muted)

    def test_player_load_page_audio_none(self):
        events = []
        self.player.media_changed.connect(lambda has_audio, path: events.append((has_audio, path)))

        self.player.load_page_audio(None)
        self.assertFalse(self.player.has_audio)
        self.assertIsNone(self.player.current_audio_path)
        self.assertEqual(events[-1], (False, ''))

    def test_player_load_page_audio_file(self):
        test_audio = osp.join(self.temp_dir.name, 'page.mp3')
        Path(test_audio).touch()

        events = []
        self.player.media_changed.connect(lambda has_audio, path: events.append((has_audio, path)))

        self.player.load_page_audio(test_audio, autoplay=False)
        self.assertTrue(self.player.has_audio)
        self.assertEqual(self.player.current_audio_path, test_audio)
        self.assertEqual(events[-1], (True, test_audio))

    def test_widget_controls_sync_with_player(self):
        widget = AudioControlWidget(self.player)

        # Initially no audio -> play button disabled
        self.assertFalse(widget.playBtn.isEnabled())

        # Load audio file -> play button enabled
        test_audio = osp.join(self.temp_dir.name, 'page_01.mp3')
        Path(test_audio).touch()
        self.player.load_page_audio(test_audio, autoplay=False)
        self.assertTrue(widget.playBtn.isEnabled())

        # Change volume via slider updates player
        widget.volSlider.setValue(45)
        self.assertEqual(self.player.volume, 45)

        # Toggle mute via button updates player
        widget.muteBtn.click()
        self.assertTrue(self.player.is_muted)
        self.assertEqual(widget.volLabel.text(), 'Muted')
        widget.muteBtn.click()
        self.assertFalse(self.player.is_muted)
        self.assertEqual(widget.volLabel.text(), '45%')

        # Replay button calls player.replay
        self.assertTrue(widget.replayBtn.isEnabled())
        widget.replayBtn.click()

    def test_real_audio_playback_integration(self):
        import wave, struct
        real_wav = osp.join(self.temp_dir.name, 'page_real.wav')
        with wave.open(real_wav, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            data = struct.pack('<h', 0) * 4410 # 0.1s
            wav.writeframes(data)

        self.player.load_page_audio(real_wav, autoplay=True)
        self.assertTrue(self.player.has_audio)
        self.assertEqual(self.player.current_audio_path, real_wav)

        self.player.pause()
        self.assertFalse(self.player.is_playing)

        self.player.play()
        self.player.stop()
        self.assertFalse(self.player.is_playing)


if __name__ == '__main__':
    unittest.main()
