from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .indexing import IndexWorker, ModelLoadWorker, RetrievalEngine, SearchWorker
from .retrieval import MODEL_DIRECTORY_NAME
from .store import LibraryStore, SearchHit

logger = logging.getLogger(__name__)

APP_YELLOW = "#EDD047"
APP_BLACK = "#171717"
APP_WHITE = "#FFFFFF"

APP_STYLE = """
QWidget { color: #171717; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI'; font-size: 14px; }
QMainWindow, QDialog { background: #F5F5F2; }
QFrame#appHeader { background: #171717; border-bottom: 1px solid #171717; }
QFrame#card { background: #FFFFFF; border: 1px solid #D8D8D2; border-radius: 16px; }
QLabel#eyebrow { color: #171717; font-size: 11px; font-weight: 700; }
QLabel#title { font-family: Georgia; font-size: 34px; font-weight: 600; }
QLabel#muted { color: #646464; }
QLabel#localBadge { color: #EDD047; font-size: 11px; font-weight: 700; }
QPushButton { min-height: 38px; padding: 0 16px; border-radius: 9px; border: 1px solid #171717; background: #FFFFFF; color: #171717; font-weight: 600; }
QPushButton:hover { background: #F4F4F0; }
QPushButton:disabled { color: #8A8A8A; border-color: #C9C9C3; background: #F2F2EF; }
QPushButton#primary, QPushButton#searchButton { color: #FFFFFF; border: 1px solid #171717; background: #171717; }
QPushButton#primary:hover, QPushButton#searchButton:hover { background: #383838; }
QLineEdit { min-height: 46px; padding: 0 14px; border: 1px solid #171717; border-radius: 12px; background: #FFFFFF; font-size: 16px; }
QLineEdit:focus { border: 2px solid #555555; }
QProgressBar { height: 10px; border: 0; border-radius: 5px; background: #DDDDD7; text-align: center; color: transparent; }
QProgressBar::chunk { border-radius: 5px; background: #171717; }
QListWidget { border: 0; background: transparent; outline: 0; }
QListWidget::item { margin: 0 0 8px 0; }
QListWidget::item:selected { background: #DADADA; color: #171717; }
QRadioButton, QCheckBox { spacing: 10px; padding: 7px 2px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #171717; border-radius: 3px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #171717; border: 1px solid #171717; }
QRadioButton::indicator { width: 17px; height: 17px; border: 1px solid #171717; border-radius: 9px; background: #FFFFFF; }
QRadioButton::indicator:checked { background: #171717; border: 3px solid #777777; }
"""


def asset_path(filename: str) -> Path:
    packaged = Path(__file__).resolve().parent / "assets" / filename
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[2] / filename


def application_icon_path() -> Path:
    mac_icon = asset_path("app_icon_rounded.icns")
    if sys.platform == "darwin" and mac_icon.is_file():
        return mac_icon
    return asset_path("app_icon_rounded.png")


def apply_checkbox_style(checkbox: QCheckBox) -> None:
    checkmark = asset_path("checkmark.svg").as_posix()
    checkbox.setStyleSheet(
        f'QCheckBox::indicator:checked {{ image: url("{checkmark}"); }}'
    )


def data_directory() -> Path:
    override = os.environ.get("FOOTAGE_CRAWLER_DATA_DIR") or os.environ.get("FOOTAGE_SEARCH_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
        current, legacy = root / "Footage Crawler", root / "Footage Search"
        return legacy if legacy.exists() and not current.exists() else current
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        current, legacy = root / "Footage Crawler", root / "Footage Search"
        return legacy if legacy.exists() and not current.exists() else current
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    current, legacy = root / "footage-crawler", root / "footage-search"
    return legacy if legacy.exists() and not current.exists() else current


def heading(text: str, object_name: str = "title") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setWordWrap(True)
    return label


class SetupPage(QWidget):
    start_requested = Signal(list, bool, bool, str)

    def __init__(self):
        super().__init__()
        self.folders: list[Path] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(70, 44, 70, 44)
        outer.setSpacing(18)
        outer.addWidget(heading("FIRST-RUN SETUP", "eyebrow"))
        outer.addWidget(heading("Build a searchable Footage Library"))
        intro = heading(
            "Choose a folder and Footage Crawler will index photos and timestamped video moments locally. Originals stay untouched.",
            "muted",
        )
        outer.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        form = QVBoxLayout(card)
        form.setContentsMargins(28, 25, 28, 25)
        form.setSpacing(14)
        form.addWidget(heading("1  Choose folders", "eyebrow"))
        self.folder_list = QListWidget()
        self.folder_list.setFixedHeight(92)
        form.addWidget(self.folder_list)
        folder_actions = QHBoxLayout()
        choose = QPushButton("Add folder…")
        choose.clicked.connect(self.choose_folder)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_folder)
        folder_actions.addWidget(choose)
        folder_actions.addWidget(remove)
        folder_actions.addStretch()
        form.addLayout(folder_actions)

        form.addSpacing(8)
        form.addWidget(heading("2  Include media", "eyebrow"))
        media_row = QHBoxLayout()
        self.photos = QCheckBox("Photos")
        self.videos = QCheckBox("Videos")
        apply_checkbox_style(self.photos)
        apply_checkbox_style(self.videos)
        self.photos.setChecked(True)
        self.videos.setChecked(True)
        media_row.addWidget(self.photos)
        media_row.addWidget(self.videos)
        media_row.addStretch()
        form.addLayout(media_row)

        form.addSpacing(8)
        form.addWidget(heading("3  Sampling profile", "eyebrow"))
        self.profile_group = QButtonGroup(self)
        choices = (
            ("fast", "Fast — inspect videos every 20 seconds"),
            ("balanced", "Balanced — inspect videos every 10 seconds"),
            ("accurate", "Accurate — inspect videos every 5 seconds"),
        )
        for key, text in choices:
            radio = QRadioButton(text)
            radio.setProperty("profile", key)
            self.profile_group.addButton(radio)
            form.addWidget(radio)
            if key == "balanced":
                radio.setChecked(True)
        outer.addWidget(card)
        outer.addStretch()
        self.start_button = QPushButton("Start local indexing")
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.emit_start)
        outer.addWidget(self.start_button, alignment=Qt.AlignmentFlag.AlignRight)

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose a media folder")
        if selected:
            path = Path(selected).resolve()
            if path not in self.folders:
                self.folders.append(path)
                self.folder_list.addItem(str(path))
            self.start_button.setEnabled(bool(self.folders))

    def remove_folder(self) -> None:
        for item in self.folder_list.selectedItems():
            path = Path(item.text())
            if path in self.folders:
                self.folders.remove(path)
            self.folder_list.takeItem(self.folder_list.row(item))
        self.start_button.setEnabled(bool(self.folders))

    def emit_start(self) -> None:
        if not self.photos.isChecked() and not self.videos.isChecked():
            QMessageBox.warning(self, "Choose media", "Include photos, videos, or both.")
            return
        selected = self.profile_group.checkedButton()
        self.start_requested.emit(
            self.folders,
            self.photos.isChecked(),
            self.videos.isChecked(),
            selected.property("profile"),
        )


class ResultRow(QWidget):
    def __init__(self, hit: SearchHit):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 12, 8)
        thumb = QLabel()
        thumb.setFixedSize(176, 110)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(hit.thumbnail_path)
        thumb.setPixmap(pixmap.scaled(176, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(thumb)
        copy = QVBoxLayout()
        match = QLabel(f"{max(0, min(100, round((hit.score + 1) * 50)))}% visual match")
        match.setObjectName("eyebrow")
        copy.addWidget(match)
        name = QLabel(Path(hit.path).name)
        name.setFont(QFont(name.font().family(), 15, QFont.Weight.DemiBold))
        copy.addWidget(name)
        timestamp = "Photo" if hit.kind == "photo" else format_time(hit.timestamp_seconds)
        detail = QLabel(f"{timestamp}  ·  {Path(hit.path).parent}")
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        copy.addWidget(detail)
        copy.addStretch()
        layout.addLayout(copy, 1)


class ClickableVideoWidget(QVideoWidget):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewDialog(QDialog):
    def __init__(self, hit: SearchHit, parent=None):
        super().__init__(parent)
        self.hit = hit
        self.setWindowTitle(Path(hit.path).name)
        self.resize(920, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        if hit.kind == "video":
            self._video_started = False
            self._initial_seek_applied = False
            self.video = ClickableVideoWidget()
            self.video.setCursor(Qt.CursorShape.PointingHandCursor)
            self.video.setToolTip("Click to play or pause")
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.mediaStatusChanged.connect(self._seek_when_loaded)
            self.player.seekableChanged.connect(self._seek_when_possible)
            self.player.durationChanged.connect(self._duration_available)
            self.player.playbackStateChanged.connect(self._playback_changed)
            self.player.errorOccurred.connect(self._playback_error)
            self.video.clicked.connect(self._toggle_play)
            layout.addWidget(self.video, 1)
            self.playback_status = QLabel("Loading video…  ·  Click video to play or pause")
            self.playback_status.setObjectName("muted")
            layout.addWidget(self.playback_status)
        else:
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(hit.path)
            image.setPixmap(pixmap.scaled(860, 520, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(image, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(f"{Path(hit.path).name}  ·  {format_time(hit.timestamp_seconds) if hit.kind == 'video' else 'Photo'}"))
        bottom.addStretch()
        reveal = QPushButton("Reveal original")
        reveal.clicked.connect(self._reveal)
        bottom.addWidget(reveal)
        layout.addLayout(bottom)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.hit.kind == "video" and not self._video_started:
            self._video_started = True
            QTimer.singleShot(0, self._start_video)

    def _start_video(self) -> None:
        logger.info(
            "Opening video preview: path=%s timestamp=%.3fs",
            self.hit.path,
            self.hit.timestamp_seconds,
        )
        self.player.setSource(QUrl.fromLocalFile(self.hit.path))
        self.player.play()

    def _seek_when_loaded(self, status) -> None:
        logger.info("Video preview media status: path=%s status=%s", self.hit.path, status.name)
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._apply_initial_seek()
            self.player.play()

    def _seek_when_possible(self, seekable: bool) -> None:
        if seekable:
            self._apply_initial_seek()

    def _duration_available(self, duration: int) -> None:
        if duration > 0:
            self._apply_initial_seek()

    def _apply_initial_seek(self) -> None:
        if self._initial_seek_applied:
            return
        target = max(0, round(self.hit.timestamp_seconds * 1000))
        duration = self.player.duration()
        if target and not self.player.isSeekable() and duration <= 0:
            return
        if duration > 0:
            target = min(target, max(0, duration - 250))
        logger.info(
            "Seeking video preview: path=%s position_ms=%d duration_ms=%d",
            self.hit.path,
            target,
            duration,
        )
        self.player.setPosition(target)
        self._initial_seek_applied = True

    def _playback_changed(self, state) -> None:
        logger.info("Video preview playback state: path=%s state=%s", self.hit.path, state.name)
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.playback_status.setText("Playing  ·  Click video to pause")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.playback_status.setText("Paused  ·  Click video to play")
        else:
            self.playback_status.setText("Stopped  ·  Click video to play")

    def _playback_error(self, error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        detail = message or error.name
        logger.error("Video preview failed: path=%s error=%s", self.hit.path, detail)
        self.playback_status.setText(f"Could not play this video: {detail}")

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            logger.info("Video preview pause requested: path=%s", self.hit.path)
            self.player.pause()
        else:
            logger.info("Video preview play requested: path=%s", self.hit.path)
            self.player.play()

    def _reveal(self) -> None:
        path = Path(self.hit.path)
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def format_time(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


class FolderManagerDialog(QDialog):
    def __init__(
        self,
        folders: list[Path],
        profile: str = "balanced",
        include_photos: bool = True,
        include_videos: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Library settings")
        self.resize(680, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(heading("LIBRARY SETTINGS", "eyebrow"))
        layout.addWidget(heading("Folders and indexing"))
        layout.addWidget(heading("LIBRARY FOLDERS", "eyebrow"))
        note = heading(
            "Removed directories are marked missing on the next Rescan; originals are never deleted.",
            "muted",
        )
        layout.addWidget(note)
        self.folder_list = QListWidget()
        for folder in folders:
            self.folder_list.addItem(str(folder))
        layout.addWidget(self.folder_list, 1)
        layout.addWidget(heading("MEDIA TYPES", "eyebrow"))
        media_note = heading(
            "Choose which kinds of media should be indexed and included in search results.",
            "muted",
        )
        layout.addWidget(media_note)
        media_row = QHBoxLayout()
        self.photos = QCheckBox("Photos")
        self.videos = QCheckBox("Videos")
        apply_checkbox_style(self.photos)
        apply_checkbox_style(self.videos)
        self.photos.setChecked(include_photos)
        self.videos.setChecked(include_videos)
        media_row.addWidget(self.photos)
        media_row.addWidget(self.videos)
        media_row.addStretch()
        layout.addLayout(media_row)
        layout.addWidget(heading("VIDEO SAMPLING", "eyebrow"))
        sampling_note = heading(
            "Choose how often Footage Crawler inspects moments inside videos. More frequent sampling takes longer.",
            "muted",
        )
        layout.addWidget(sampling_note)
        self.profile_group = QButtonGroup(self)
        profiles = (
            ("fast", "Fast — every 20 seconds"),
            ("balanced", "Balanced — every 10 seconds"),
            ("accurate", "Accurate — every 5 seconds"),
        )
        profile_row = QHBoxLayout()
        for key, label in profiles:
            radio = QRadioButton(label)
            radio.setProperty("profile", key)
            radio.setChecked(key == profile)
            self.profile_group.addButton(radio)
            profile_row.addWidget(radio)
        profile_row.addStretch()
        layout.addLayout(profile_row)
        actions = QHBoxLayout()
        self.add = QPushButton("Add folder…")
        self.add.clicked.connect(self.add_folder)
        self.remove = QPushButton("Remove selected")
        self.remove.clicked.connect(self.remove_selected)
        actions.addWidget(self.add)
        actions.addWidget(self.remove)
        actions.addStretch()
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.reject)
        self.save = QPushButton("Save and Rescan")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.accept)
        actions.addWidget(self.cancel)
        actions.addWidget(self.save)
        layout.addLayout(actions)
        self._update_save()

    def add_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose a media folder")
        existing = {self.folder_list.item(i).text() for i in range(self.folder_list.count())}
        if selected and str(Path(selected).resolve()) not in existing:
            self.folder_list.addItem(str(Path(selected).resolve()))
        self._update_save()

    def remove_selected(self) -> None:
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))
        self._update_save()

    def _update_save(self) -> None:
        self.save.setEnabled(self.folder_list.count() > 0)

    def folders(self) -> list[Path]:
        return [Path(self.folder_list.item(i).text()) for i in range(self.folder_list.count())]

    def profile(self) -> str:
        selected = self.profile_group.checkedButton()
        return selected.property("profile") if selected else "balanced"

    def include_photos(self) -> bool:
        return self.photos.isChecked()

    def include_videos(self) -> bool:
        return self.videos.isChecked()


class LoadingPage(QWidget):
    retry_requested = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(90, 70, 90, 70)
        outer.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(660)
        content = QVBoxLayout(card)
        content.setContentsMargins(40, 38, 40, 38)
        content.setSpacing(16)
        content.addWidget(heading("STARTING FOOTAGE CRAWLER", "eyebrow"))
        self.title = heading("Loading AI model")
        content.addWidget(self.title)
        self.detail = heading(
            "Preparing private visual search. The model stays on this computer.", "muted"
        )
        content.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        content.addWidget(self.progress)
        self.retry = QPushButton("Try again")
        self.retry.setObjectName("primary")
        self.retry.clicked.connect(self.retry_requested)
        self.retry.hide()
        content.addWidget(self.retry, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()

    def set_phase(self, message: str) -> None:
        self.detail.setText(message)

    def show_error(self, message: str) -> None:
        self.detail.setText(f"The AI model could not be loaded.\n\n{message}")
        self.progress.hide()
        self.retry.show()

    def reset(self) -> None:
        self.detail.setText("Preparing private visual search. The model stays on this computer.")
        self.progress.show()
        self.retry.hide()


class HomePage(QWidget):
    search_requested = Signal(str, list)
    rescan_requested = Signal()
    manage_folders_requested = Signal()
    pause_requested = Signal(bool)

    def __init__(self):
        super().__init__()
        self.hits: list[SearchHit] = []
        self.folder_checks: dict[Path, QCheckBox] = {}
        self.paused = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(34, 30, 34, 30)
        outer.setSpacing(24)

        main = QVBoxLayout()
        main.addWidget(heading("SEARCH HOME", "eyebrow"))
        main.addWidget(heading("Find a visual moment"))
        self.result_label = QLabel("Index some footage, then describe what you want to find.")
        self.result_label.setObjectName("muted")
        main.addWidget(self.result_label)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setFixedHeight(50)
        self.search.setPlaceholderText("Try “a red train”, “people on a beach”, or “night driving”…")
        self.search.returnPressed.connect(self._search)
        search_row.addWidget(self.search, 1)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("searchButton")
        self.search_button.setFixedHeight(50)
        self.search_button.clicked.connect(self._search)
        search_row.addWidget(self.search_button)
        main.addLayout(search_row)
        self.results = QListWidget()
        self.results.itemActivated.connect(self._open_result)
        self.results.itemClicked.connect(self._open_result)
        main.addWidget(self.results, 1)
        outer.addLayout(main, 1)

        sidebar = QFrame()
        sidebar.setObjectName("card")
        sidebar.setFixedWidth(370)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 22, 22, 22)
        side.addWidget(heading("SEARCH FOLDERS", "eyebrow"))
        self.status = QLabel("All folders included")
        self.status.setFont(QFont(self.status.font().family(), 20, QFont.Weight.DemiBold))
        side.addWidget(self.status)
        self.detail = QLabel("Tick folders to include in search results.")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        side.addWidget(self.detail)
        self.folder_scroll = QScrollArea()
        self.folder_scroll.setObjectName("folderFilters")
        self.folder_scroll.setWidgetResizable(True)
        self.folder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.folder_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.folder_scroll.setMinimumHeight(80)
        self.folder_scroll.setMaximumHeight(220)
        self.folder_scroll.setStyleSheet(
            "QScrollArea#folderFilters, QScrollArea#folderFilters > QWidget > QWidget "
            "{ background: #FFFFFF; }"
        )
        self.folder_container = QWidget()
        self.folder_layout = QVBoxLayout(self.folder_container)
        self.folder_layout.setContentsMargins(0, 6, 0, 6)
        self.folder_layout.setSpacing(4)
        self.folder_layout.addStretch()
        self.folder_scroll.setWidget(self.folder_container)
        side.addWidget(self.folder_scroll)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        side.addWidget(self.progress)
        self.current_file = QLabel()
        self.current_file.setObjectName("muted")
        self.current_file.setWordWrap(True)
        side.addWidget(self.current_file)
        side.addStretch()
        self.manage_folders = QPushButton("Library settings")
        self.manage_folders.clicked.connect(self.manage_folders_requested)
        side.addWidget(self.manage_folders)
        self.pause = QPushButton("Pause")
        self.pause.clicked.connect(self._pause)
        self.pause.hide()
        side.addWidget(self.pause)
        self.rescan_button = QPushButton("Rescan folders")
        self.rescan_button.setObjectName("primary")
        self.rescan_button.clicked.connect(self.rescan_requested)
        side.addWidget(self.rescan_button)
        outer.addWidget(sidebar)

    def _search(self) -> None:
        query = self.search.text().strip()
        if query:
            self.search.setEnabled(False)
            self.search_button.setEnabled(False)
            self.result_label.setText("Searching locally…")
            self.search_requested.emit(query, self.included_folders())

    @staticmethod
    def short_folder_name(folder: Path) -> str:
        parts = folder.parts
        if len(parts) <= 3:
            return str(folder)
        return f"…/{'/'.join(parts[-3:])}"

    def set_folders(self, folders: list[Path]) -> None:
        previous = {str(path): checkbox.isChecked() for path, checkbox in self.folder_checks.items()}
        for checkbox in self.folder_checks.values():
            self.folder_layout.removeWidget(checkbox)
            checkbox.deleteLater()
        self.folder_checks.clear()
        for folder in folders:
            path = Path(folder)
            checkbox = QCheckBox(self.short_folder_name(path))
            apply_checkbox_style(checkbox)
            checkbox.setToolTip(str(path))
            checkbox.setChecked(previous.get(str(path), True))
            checkbox.checkStateChanged.connect(self._update_folder_summary)
            self.folder_layout.insertWidget(self.folder_layout.count() - 1, checkbox)
            self.folder_checks[path] = checkbox
        self._update_folder_summary()

    def included_folders(self) -> list[Path]:
        return [path for path, checkbox in self.folder_checks.items() if checkbox.isChecked()]

    def _update_folder_summary(self, *_args) -> None:
        total = len(self.folder_checks)
        included = len(self.included_folders())
        if not total:
            self.status.setText("No folders indexed")
        elif included == total:
            self.status.setText("All folders included")
        else:
            self.status.setText(f"{included} of {total} included")

    def show_hits(self, query: str, hits: list[SearchHit]) -> None:
        self.search.setEnabled(True)
        self.search_button.setEnabled(True)
        self.hits = hits
        self.results.clear()
        self.result_label.setText(f"{len(hits)} Media Assets for “{query}”")
        for hit in hits:
            item = QListWidgetItem()
            row = ResultRow(hit)
            item.setSizeHint(row.sizeHint())
            self.results.addItem(item)
            self.results.setItemWidget(item, row)

    def search_failed(self, message: str) -> None:
        self.search.setEnabled(True)
        self.search_button.setEnabled(True)
        self.result_label.setText("Search could not complete")
        QMessageBox.critical(self, "Search failed", message)

    def search_phase(self, message: str) -> None:
        self.result_label.setText(message)

    def _open_result(self, item: QListWidgetItem) -> None:
        index = self.results.row(item)
        if 0 <= index < len(self.hits):
            PreviewDialog(self.hits[index], self).exec()

    def set_stats(self, stats: dict) -> None:
        self.detail.setText("Tick folders to include in search results.")
        self._update_folder_summary()

    def indexing_started(self) -> None:
        self.status.setText("Indexing locally")
        self.detail.setText("Your folder choices will be used for searches.")
        self.progress.setValue(0)
        self.progress.show()
        self.pause.show()
        self.manage_folders.setEnabled(False)

    def indexing_progress(self, current: int, total: int, path: str) -> None:
        if not self.paused:
            self.status.setText("Indexing locally")
        self.progress.setValue(round(current / max(1, total) * 100))
        self.current_file.setText(path)

    def indexing_finished(self) -> None:
        self.progress.hide()
        self.pause.hide()
        self.manage_folders.setEnabled(True)
        self.current_file.clear()
        self.paused = False
        self.pause.setText("Pause")

    def _pause(self) -> None:
        self.paused = not self.paused
        self.pause.setText("Resume" if self.paused else "Pause")
        self.status.setText("Indexing paused" if self.paused else "Indexing locally")
        self.pause_requested.emit(self.paused)


class MainWindow(QMainWindow):
    pause_indexer = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Footage Crawler")
        self.setWindowIcon(QIcon(str(application_icon_path())))
        self.resize(1180, 760)
        self.data_path = data_directory()
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.database_path = self.data_path / "library.sqlite3"
        logger.info("Opening Footage Crawler: data_directory=%s", self.data_path)
        self.store = LibraryStore(self.database_path)
        self.engine = RetrievalEngine(self.data_path / "models" / MODEL_DIRECTORY_NAME)
        self.model_thread: QThread | None = None
        self.model_worker: ModelLoadWorker | None = None
        self.index_thread: QThread | None = None
        self.index_worker: IndexWorker | None = None
        self.search_jobs: dict[QThread, SearchWorker] = {}

        shell = QWidget()
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName("appHeader")
        header_texture = asset_path("header_texture_yellow.png").as_posix()
        header.setStyleSheet(
            f"""
            QFrame#appHeader {{
                background-color: {APP_YELLOW};
                background-image: url("{header_texture}");
                background-repeat: repeat;
                background-position: top left;
                border-bottom: 1px solid {APP_BLACK};
            }}
            """
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 10, 24, 10)
        self.brand_logo = QLabel()
        self.brand_logo.setAccessibleName("Footage Crawler")
        logo = QPixmap(str(asset_path("footage_crawler_wordmark_transparent.png")))
        self.brand_logo.setPixmap(
            logo.scaled(
                190,
                50,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        header_layout.addWidget(self.brand_logo)
        header_layout.addStretch()
        local = QLabel("LOCAL ONLY")
        local.setObjectName("localBadge")
        header_layout.addWidget(local)
        layout.addWidget(header)
        self.pages = QStackedWidget()
        self.loading = LoadingPage()
        self.setup = SetupPage()
        self.home = HomePage()
        self.pages.addWidget(self.loading)
        self.pages.addWidget(self.setup)
        self.pages.addWidget(self.home)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(shell)

        self.setup.start_requested.connect(self.start_indexing)
        self.home.search_requested.connect(self.start_search)
        self.home.rescan_requested.connect(self.rescan)
        self.home.manage_folders_requested.connect(self.manage_folders)
        self.home.pause_requested.connect(self.pause_indexer)
        self.pause_indexer.connect(self._set_index_paused)
        self.loading.retry_requested.connect(self.start_model_loading)

        folders = self.store.get_setting("folders", [])
        if folders:
            self.destination_page = self.home
            self.home.set_folders([Path(folder) for folder in folders])
            self.home.set_stats(self.store.stats())
        else:
            self.destination_page = self.setup
        self.pages.setCurrentWidget(self.loading)
        QTimer.singleShot(0, self.start_model_loading)

    def start_model_loading(self) -> None:
        if self.model_thread and self.model_thread.isRunning():
            return
        logger.info("Starting startup model load")
        self.loading.reset()
        self.pages.setCurrentWidget(self.loading)
        thread = QThread(self)
        worker = ModelLoadWorker(self.engine)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self.loading.set_phase)
        worker.completed.connect(self._model_ready)
        worker.failed.connect(self._model_failed)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._model_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self.model_thread = thread
        self.model_worker = worker
        thread.start()

    def _model_ready(self, device: str) -> None:
        logger.info("Startup model ready: device=%s", device)
        self.pages.setCurrentWidget(self.destination_page)

    def _model_failed(self, message: str) -> None:
        logger.error("Startup model load failed: %s", message)
        self.loading.show_error(message)

    def _model_thread_finished(self) -> None:
        logger.info("Startup model worker thread finished")
        self.model_worker = None
        self.model_thread = None

    def start_indexing(self, folders: list[Path], photos: bool, videos: bool, profile: str) -> None:
        if self.index_thread and self.index_thread.isRunning():
            logger.info("Ignoring indexing request because a job is already running")
            return
        logger.info(
            "Starting indexing UI job: folders=%s photos=%s videos=%s profile=%s",
            [str(path) for path in folders],
            photos,
            videos,
            profile,
        )
        self.store.set_setting("folders", [str(path) for path in folders])
        self.store.set_setting("include_photos", photos)
        self.store.set_setting("include_videos", videos)
        self.store.set_setting("profile", profile)
        self.pages.setCurrentWidget(self.home)
        self.home.set_folders(folders)
        self.home.indexing_started()
        thread = QThread(self)
        worker = IndexWorker(
            self.database_path,
            self.data_path,
            folders,
            photos,
            videos,
            profile,
            self.engine,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self.home.status.setText)
        worker.progress.connect(self.home.indexing_progress)
        worker.completed.connect(self._index_completed)
        worker.failed.connect(self._index_failed)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._index_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self.index_thread = thread
        self.index_worker = worker
        thread.start()

    def rescan(self) -> None:
        folders = [Path(path) for path in self.store.get_setting("folders", [])]
        logger.info("Rescan requested: folders=%s", [str(path) for path in folders])
        if not folders:
            self.pages.setCurrentWidget(self.setup)
            return
        self.start_indexing(
            folders,
            self.store.get_setting("include_photos", True),
            self.store.get_setting("include_videos", True),
            self.store.get_setting("profile", "balanced"),
        )

    def manage_folders(self) -> None:
        dialog = FolderManagerDialog(
            [Path(path) for path in self.store.get_setting("folders", [])],
            self.store.get_setting("profile", "balanced"),
            self.store.get_setting("include_photos", True),
            self.store.get_setting("include_videos", True),
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous = self.store.get_setting("folders", [])
            previous_profile = self.store.get_setting("profile", "balanced")
            previous_photos = self.store.get_setting("include_photos", True)
            previous_videos = self.store.get_setting("include_videos", True)
            folders = dialog.folders()
            profile = dialog.profile()
            include_photos = dialog.include_photos()
            include_videos = dialog.include_videos()
            logger.info(
                "Library settings changed: previous_folders=%s current_folders=%s "
                "previous_profile=%s current_profile=%s previous_photos=%s current_photos=%s "
                "previous_videos=%s current_videos=%s",
                previous,
                [str(path) for path in folders],
                previous_profile,
                profile,
                previous_photos,
                include_photos,
                previous_videos,
                include_videos,
            )
            self.store.set_setting("folders", [str(path) for path in folders])
            self.store.set_setting("profile", profile)
            self.store.set_setting("include_photos", include_photos)
            self.store.set_setting("include_videos", include_videos)
            if profile != previous_profile:
                self.store.invalidate_video_index()
            self.start_indexing(
                folders,
                include_photos,
                include_videos,
                profile,
            )

    def _set_index_paused(self, paused: bool) -> None:
        if self.index_worker:
            self.index_worker.set_paused(paused)

    def _index_completed(self, stats: dict) -> None:
        logger.info("Indexing UI job completed: stats=%s", stats)
        self.home.indexing_finished()
        self.home.set_stats(stats)

    def _index_failed(self, message: str) -> None:
        logger.error("Indexing UI job failed: %s", message)
        self.home.indexing_finished()
        self.home.status.setText("Indexing stopped")
        QMessageBox.critical(self, "Indexing failed", message)

    def _index_thread_finished(self) -> None:
        logger.info("Indexing worker thread finished")
        self.index_worker = None
        self.index_thread = None

    def start_search(self, query: str, folders: list[Path]) -> None:
        logger.info(
            "Starting search worker: query=%r included_folders=%s",
            query,
            [str(folder) for folder in folders],
        )
        thread = QThread(self)
        worker = SearchWorker(self.database_path, query, self.engine, folders)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self.home.search_phase)
        worker.completed.connect(self.home.show_hits)
        worker.failed.connect(self.home.search_failed)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda thread=thread: self._search_thread_finished(thread))
        thread.finished.connect(thread.deleteLater)
        self.search_jobs[thread] = worker
        thread.start()

    def _search_thread_finished(self, thread: QThread) -> None:
        self.search_jobs.pop(thread, None)
        logger.info("Search worker thread finished")

    def closeEvent(self, event) -> None:
        logger.info("Footage Crawler window closing")
        if self.index_worker:
            self.index_worker.cancel()
        self.store.close()
        super().closeEvent(event)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("FOOTAGE_CRAWLER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logging.captureWarnings(True)
    logger.info("Footage Crawler process starting")
    app = QApplication(sys.argv)
    app.setApplicationName("Footage Crawler")
    app.setOrganizationName("Footage Crawler")
    app.setWindowIcon(QIcon(str(application_icon_path())))
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
