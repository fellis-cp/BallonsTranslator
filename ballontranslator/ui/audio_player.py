import os
import os.path as osp
from typing import Optional

from qtpy import PYQT5, PYQT6
from qtpy.QtCore import QObject, QUrl, Signal, Qt, QEvent
from qtpy.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QToolButton,
    QSlider,
    QLabel,
    QMenu,
    QAction,
    QFrame,
    QShortcut,
)
from qtpy.QtGui import QIcon, QDesktopServices, QKeySequence, QWheelEvent, QMouseEvent

from ballontranslator.utils import shared
from ballontranslator.utils.config import pcfg
from ballontranslator.ui.misc import themed_icon_path


class PageAudioPlayer(QObject):
    """Audio player for per-page audio tracks in comic projects.

    Handles PyQt5 and PyQt6 differences, safely no-ops in headless mode
    or when audio hardware is unavailable.

    >>> player = PageAudioPlayer()
    >>> player.is_playing
    False
    """

    playback_state_changed = Signal(bool)
    media_changed = Signal(bool, str)
    volume_changed = Signal(int)
    muted_changed = Signal(bool)
    autoplay_changed = Signal(bool)
    position_changed = Signal(int)
    duration_changed = Signal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._current_path: Optional[str] = None
        self._is_playing: bool = False
        self._volume: int = max(0, min(100, int(getattr(pcfg, 'audio_volume', 100))))
        self._muted: bool = bool(getattr(pcfg, 'audio_muted', False))
        self._autoplay: bool = bool(getattr(pcfg, 'audio_autoplay', True))
        self._available: bool = False
        self._player = None
        self._audio_output = None

        self._setup_player()

    def _setup_player(self) -> None:
        from qtpy.QtCore import QCoreApplication
        if shared.HEADLESS or QCoreApplication.instance() is None:
            return
        try:
            from qtpy.QtMultimedia import QMediaPlayer
            self._player = QMediaPlayer(self)
            if PYQT6:
                from qtpy.QtMultimedia import QAudioOutput
                self._audio_output = QAudioOutput(self)
                self._player.setAudioOutput(self._audio_output)
                self._audio_output.setVolume(max(0.0, min(1.0, self._volume / 100.0)))
                self._audio_output.setMuted(self._muted)
                self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            else:
                self._player.setVolume(self._volume)
                self._player.setMuted(self._muted)
                self._player.stateChanged.connect(self._on_playback_state_changed)

            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._available = True
        except Exception:
            self._available = False

    def _on_playback_state_changed(self, state) -> None:
        if hasattr(state, 'value'):
            is_playing = (state.value == 1)
        else:
            try:
                is_playing = (int(state) == 1)
            except Exception:
                is_playing = bool(state)
        if self._is_playing != is_playing:
            self._is_playing = is_playing
            self.playback_state_changed.emit(is_playing)

    def _on_position_changed(self, pos: int) -> None:
        self.position_changed.emit(max(0, int(pos)))

    def _on_duration_changed(self, dur: int) -> None:
        self.duration_changed.emit(max(0, int(dur)))

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_muted(self) -> bool:
        return self._muted

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def autoplay(self) -> bool:
        return self._autoplay

    @property
    def position(self) -> int:
        if self._available and self._player is not None:
            try:
                return max(0, int(self._player.position()))
            except Exception:
                pass
        return 0

    @property
    def duration(self) -> int:
        if self._available and self._player is not None:
            try:
                return max(0, int(self._player.duration()))
            except Exception:
                pass
        return 0

    @property
    def current_audio_path(self) -> Optional[str]:
        return self._current_path

    @property
    def has_audio(self) -> bool:
        return bool(self._current_path and osp.isfile(self._current_path))

    def load_page_audio(self, audio_path: Optional[str], autoplay: Optional[bool] = None) -> None:
        """Load audio for the current page and optionally auto-play it."""
        should_play = self._autoplay if autoplay is None else bool(autoplay)
        self.stop()

        if not audio_path or not osp.isfile(audio_path):
            self._current_path = None
            self.media_changed.emit(False, '')
            self.position_changed.emit(0)
            self.duration_changed.emit(0)
            return

        self._current_path = audio_path
        if self._available and self._player is not None:
            url = QUrl.fromLocalFile(osp.abspath(audio_path))
            try:
                if PYQT6:
                    self._player.setSource(url)
                else:
                    from qtpy.QtMultimedia import QMediaContent
                    self._player.setMedia(QMediaContent(url))
            except Exception:
                self._current_path = None
                self.media_changed.emit(False, '')
                return

        self.media_changed.emit(True, audio_path)
        if should_play:
            self.play()

    def play(self) -> None:
        if not self._available or not self._current_path or not self._player:
            return
        try:
            self._player.play()
            self._is_playing = True
            self.playback_state_changed.emit(True)
        except Exception:
            self._is_playing = False
            self.playback_state_changed.emit(False)

    def pause(self) -> None:
        if not self._available or not self._player:
            return
        try:
            self._player.pause()
            self._is_playing = False
            self.playback_state_changed.emit(False)
        except Exception:
            pass

    def stop(self) -> None:
        if not self._available or not self._player:
            return
        try:
            self._player.stop()
            self._is_playing = False
            self.playback_state_changed.emit(False)
        except Exception:
            pass

    def seek(self, position_ms: int) -> None:
        if self._available and self._player is not None:
            try:
                self._player.setPosition(max(0, int(position_ms)))
            except Exception:
                pass

    def replay(self) -> None:
        if not self._available or not self._player or not self._current_path:
            return
        self.seek(0)
        self.play()

    def toggle_play_pause(self) -> None:
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        self._volume = volume
        pcfg.audio_volume = volume
        if self._available:
            if PYQT6 and self._audio_output is not None:
                self._audio_output.setVolume(volume / 100.0)
            elif self._player is not None:
                self._player.setVolume(volume)
        self.volume_changed.emit(volume)

    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        self._muted = muted
        pcfg.audio_muted = muted
        if self._available:
            if PYQT6 and self._audio_output is not None:
                self._audio_output.setMuted(muted)
            elif self._player is not None:
                self._player.setMuted(muted)
        self.muted_changed.emit(muted)

    def toggle_mute(self) -> None:
        self.set_muted(not self._muted)

    def set_autoplay(self, autoplay: bool) -> None:
        self._autoplay = bool(autoplay)
        pcfg.audio_autoplay = self._autoplay
        self.autoplay_changed.emit(self._autoplay)


class AccessibleVolumeSlider(QSlider):
    """Volume slider with mouse-wheel support for easy adjustments."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self.setValue(min(100, self.value() + 5))
        elif delta < 0:
            self.setValue(max(0, self.value() - 5))
        event.accept()


class AudioControlWidget(QWidget):
    """Accessible, prominent media capsule widget for page audio playback."""

    def __init__(self, player: PageAudioPlayer, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.player = player
        self.project = None
        self._raw_track_name = ""
        self.setObjectName('AudioControlWidget')
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 6, 2)
        layout.setSpacing(5)

        # 1. Replay button (restart from beginning)
        self.replayBtn = QToolButton(self)
        self.replayBtn.setObjectName('AudioReplayButton')
        self.replayBtn.setFixedSize(22, 22)
        self.replayBtn.setAutoRaise(True)
        self.replayBtn.setIcon(QIcon(themed_icon_path('fontfmt_reload.svg')))
        self.replayBtn.setToolTip(self.tr('Replay track from start (Ctrl+Alt+R)'))
        self.replayBtn.clicked.connect(self.on_replay_clicked)
        self.replayBtn.setEnabled(False)
        layout.addWidget(self.replayBtn)

        # 2. Prominent Play/Pause Button
        self.playBtn = QToolButton(self)
        self.playBtn.setObjectName('AudioPlayButton')
        self.playBtn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.playBtn.setFixedHeight(22)
        self.playBtn.setMinimumWidth(72)
        self.playBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.playBtn.clicked.connect(self.on_play_clicked)
        self.playBtn.setEnabled(False)
        self.playBtn.setToolTip(self.tr('Play / Pause Page Audio (Alt+P)'))
        layout.addWidget(self.playBtn)

        # 3. Track name label
        self.trackLabel = QLabel(self)
        self.trackLabel.setObjectName('AudioTrackLabel')
        self.trackLabel.setMaximumWidth(130)
        self.trackLabel.setText(self.tr('♫ No audio'))
        layout.addWidget(self.trackLabel)

        # 4. Time display label
        self.timeLabel = QLabel('--:--', self)
        self.timeLabel.setObjectName('AudioTimeLabel')
        layout.addWidget(self.timeLabel)

        # 5. Visual divider
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        divider.setFixedHeight(14)
        layout.addWidget(divider)

        # 6. Mute / Speaker button
        self.muteBtn = QToolButton(self)
        self.muteBtn.setObjectName('AudioMuteButton')
        self.muteBtn.setFixedSize(22, 22)
        self.muteBtn.setAutoRaise(True)
        self.muteBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.muteBtn.clicked.connect(self.on_mute_clicked)
        self.muteBtn.setToolTip(self.tr('Mute / Unmute (Alt+M, Scroll wheel adjusts volume)'))
        self.muteBtn.installEventFilter(self)
        layout.addWidget(self.muteBtn)

        # 7. Wide, accessible Volume Slider
        self.volSlider = AccessibleVolumeSlider(Qt.Orientation.Horizontal, self)
        self.volSlider.setObjectName('AudioVolumeSlider')
        self.volSlider.setRange(0, 100)
        self.volSlider.setValue(self.player.volume)
        self.volSlider.setFixedWidth(100)
        self.volSlider.setFixedHeight(18)
        self.volSlider.setToolTip(f'{self.tr("Volume")}: {self.player.volume}% (Scroll wheel adjusts)')
        self.volSlider.valueChanged.connect(self.on_volume_changed)
        layout.addWidget(self.volSlider)

        # 8. Volume percentage label
        self.volLabel = QLabel(f'{self.player.volume}%', self)
        self.volLabel.setObjectName('AudioVolLabel')
        self.volLabel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volLabel.setToolTip(self.tr('Click to toggle mute, double-click for 100%'))
        self.volLabel.installEventFilter(self)
        layout.addWidget(self.volLabel)

        # Player signal bindings
        self.player.playback_state_changed.connect(self.on_player_state_changed)
        self.player.media_changed.connect(self.on_player_media_changed)
        self.player.volume_changed.connect(self.on_player_volume_changed)
        self.player.muted_changed.connect(self.on_player_muted_changed)
        self.player.position_changed.connect(self.on_position_changed)
        self.player.duration_changed.connect(self.on_duration_changed)

        # Global shortcuts for accessibility
        shortcut_play = QShortcut(QKeySequence("Alt+P"), self)
        shortcut_play.activated.connect(self.on_play_clicked)
        shortcut_mute = QShortcut(QKeySequence("Alt+M"), self)
        shortcut_mute.activated.connect(self.on_mute_clicked)
        shortcut_replay = QShortcut(QKeySequence("Ctrl+Alt+R"), self)
        shortcut_replay.activated.connect(self.on_replay_clicked)

        self.update_ui_state()

    def set_project(self, project) -> None:
        self.project = project

    def update_ui_state(self) -> None:
        has_audio = self.player.has_audio
        is_playing = self.player.is_playing
        is_muted = self.player.is_muted

        self.playBtn.setEnabled(has_audio)
        self.replayBtn.setEnabled(has_audio)

        if not has_audio:
            self.playBtn.setText(self.tr('No Audio'))
            self.playBtn.setIcon(QIcon(themed_icon_path('audio_play.svg')))
            self.playBtn.setProperty('isPlaying', 'false')
            self.trackLabel.setText(self.tr('♫ No audio'))
            self.timeLabel.setText('--:--')
        else:
            if is_playing:
                self.playBtn.setText(self.tr('Pause'))
                self.playBtn.setIcon(QIcon(themed_icon_path('audio_pause.svg')))
                self.playBtn.setProperty('isPlaying', 'true')
            else:
                self.playBtn.setText(self.tr('Play'))
                self.playBtn.setIcon(QIcon(themed_icon_path('audio_play.svg')))
                self.playBtn.setProperty('isPlaying', 'false')

        # Refresh play button stylesheet property
        style = self.playBtn.style()
        if style:
            style.unpolish(self.playBtn)
            style.polish(self.playBtn)

        # Mute icon
        mute_icon_name = 'audio_mute.svg' if is_muted else 'audio_volume.svg'
        self.muteBtn.setIcon(QIcon(themed_icon_path(mute_icon_name)))

        # Volume label
        if is_muted:
            self.volLabel.setText(self.tr('Muted'))
        else:
            self.volLabel.setText(f'{self.player.volume}%')

    def update_icons(self) -> None:
        self.replayBtn.setIcon(QIcon(themed_icon_path('fontfmt_reload.svg')))
        self.update_ui_state()

    def on_play_clicked(self) -> None:
        self.player.toggle_play_pause()

    def on_replay_clicked(self) -> None:
        self.player.replay()

    def on_mute_clicked(self) -> None:
        self.player.toggle_mute()

    def on_volume_changed(self, value: int) -> None:
        self.player.set_volume(value)
        self.volSlider.setToolTip(f'{self.tr("Volume")}: {value}% (Scroll wheel adjusts)')

    def on_player_state_changed(self, is_playing: bool) -> None:
        self.update_ui_state()

    def on_player_media_changed(self, has_audio: bool, path: str) -> None:
        if has_audio and path:
            filename = osp.basename(path)
            self._raw_track_name = filename
            fm = self.trackLabel.fontMetrics()
            elided = fm.elidedText(f'♫ {filename}', Qt.TextElideMode.ElideRight, 130)
            self.trackLabel.setText(elided)
            self.trackLabel.setToolTip(f'{self.tr("Page Audio Track")}: {filename}\n{path}')
        else:
            self._raw_track_name = ""
            self.trackLabel.setText(self.tr('♫ No audio'))
            self.trackLabel.setToolTip(self.tr('No audio for this page in audio/ folder'))
            self.timeLabel.setText('--:--')
        self.update_ui_state()

    def on_player_volume_changed(self, volume: int) -> None:
        if self.volSlider.value() != volume:
            self.volSlider.blockSignals(True)
            self.volSlider.setValue(volume)
            self.volSlider.blockSignals(False)
        self.volSlider.setToolTip(f'{self.tr("Volume")}: {volume}% (Scroll wheel adjusts)')
        self.update_ui_state()

    def on_player_muted_changed(self, muted: bool) -> None:
        self.update_ui_state()

    def on_position_changed(self, pos_ms: int) -> None:
        self._update_time_display(pos_ms, self.player.duration)

    def on_duration_changed(self, dur_ms: int) -> None:
        self._update_time_display(self.player.position, dur_ms)

    def _update_time_display(self, pos_ms: int, dur_ms: int) -> None:
        if not self.player.has_audio or dur_ms <= 0:
            self.timeLabel.setText('--:--')
            return
        pos_s = max(0, pos_ms // 1000)
        dur_s = max(0, dur_ms // 1000)
        self.timeLabel.setText(f'{pos_s // 60}:{pos_s % 60:02d} / {dur_s // 60}:{dur_s % 60:02d}')

    def on_autoplay_toggled(self, checked: bool) -> None:
        self.player.set_autoplay(checked)

    def on_open_audio_folder(self) -> None:
        if self.project and hasattr(self.project, 'audio_dir'):
            adir = self.project.audio_dir()
            if osp.isdir(adir):
                QDesktopServices.openUrl(QUrl.fromLocalFile(osp.abspath(adir)))

    def on_reload_audio(self) -> None:
        if self.project and hasattr(self.project, 'get_page_audio_path'):
            audio_path = self.project.get_page_audio_path()
            self.player.load_page_audio(audio_path, autoplay=self.player.autoplay)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.muteBtn, self.volLabel) and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            step = 5 if delta > 0 else -5
            self.player.set_volume(self.player.volume + step)
            return True

        if watched is self.volLabel:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self.player.set_volume(100)
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.player.toggle_mute()
                return True

        return super().eventFilter(watched, event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)

        auto_ac = menu.addAction(self.tr('Auto-play Page Audio'))
        auto_ac.setCheckable(True)
        auto_ac.setChecked(self.player.autoplay)
        auto_ac.toggled.connect(self.on_autoplay_toggled)

        menu.addSeparator()

        # Volume quick presets
        vol_menu = menu.addMenu(self.tr('Volume Preset'))
        for preset in (100, 75, 50, 25):
            ac = vol_menu.addAction(f'{preset}%')
            ac.triggered.connect(lambda _c=False, v=preset: self.player.set_volume(v))

        mute_ac = vol_menu.addAction(self.tr('Mute / Unmute'))
        mute_ac.triggered.connect(self.on_mute_clicked)

        menu.addSeparator()
        if self.project and hasattr(self.project, 'audio_dir') and osp.isdir(self.project.audio_dir()):
            open_ac = menu.addAction(self.tr('Open Audio Folder'))
            open_ac.triggered.connect(self.on_open_audio_folder)

        reload_ac = menu.addAction(self.tr('Reload Page Audio'))
        reload_ac.triggered.connect(self.on_reload_audio)

        menu.exec_(event.globalPos())
