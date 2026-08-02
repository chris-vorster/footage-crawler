import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from footage_search.app import (
    APP_STYLE,
    APP_YELLOW,
    ClickableVideoWidget,
    FolderManagerDialog,
    HomePage,
    LoadingPage,
    SetupPage,
    application_icon_path,
    asset_path,
)


def qt_app():
    return QApplication.instance() or QApplication([])


def test_requested_search_home_layout_and_status_transition():
    app = qt_app()
    home = HomePage()
    home.resize(1100, 700)
    home.show()
    home.detail.setText("4,587 of 44,263 Media Assets ready")
    home.indexing_started()
    home.status.setText("Loading the local visual model")
    home.indexing_progress(1, 10, "example.jpg")
    app.processEvents()

    assert home.result_label.geometry().top() < home.search.geometry().top()
    assert home.search_button.text() == "Search"
    assert home.search_button.height() == home.search.height()
    assert home.pause.geometry().bottom() <= home.rescan_button.geometry().top()
    assert home.status.text() == "Indexing locally"
    assert home.detail.text() == "Your folder choices will be used for searches."
    home.close()


def test_folders_can_be_removed_in_setup_and_library_manager(tmp_path: Path):
    qt_app()
    setup = SetupPage()
    setup.folders = [tmp_path]
    setup.folder_list.addItem(str(tmp_path))
    setup.folder_list.item(0).setSelected(True)
    setup.remove_folder()
    assert setup.folders == []
    assert setup.start_button.isEnabled() is False

    manager = FolderManagerDialog([tmp_path], "accurate", False, True)
    manager.show()
    qt_app().processEvents()
    button_tops = {button.geometry().top() for button in (manager.add, manager.remove, manager.cancel, manager.save)}
    assert len(button_tops) == 1
    manager.folder_list.item(0).setSelected(True)
    manager.remove_selected()
    assert manager.folder_list.count() == 0
    assert manager.save.isEnabled() is False
    assert manager.profile() == "accurate"
    assert manager.include_photos() is False
    assert manager.include_videos() is True
    manager.close()


def test_library_settings_can_change_video_sampling_profile(tmp_path: Path):
    qt_app()
    manager = FolderManagerDialog([tmp_path], "balanced")
    fast = next(
        button for button in manager.profile_group.buttons() if button.property("profile") == "fast"
    )
    fast.setChecked(True)

    assert manager.profile() == "fast"


def test_library_settings_can_select_any_media_type_combination(tmp_path: Path):
    qt_app()
    manager = FolderManagerDialog([tmp_path], "balanced", True, True)

    manager.photos.setChecked(False)
    assert manager.include_photos() is False
    assert manager.include_videos() is True

    manager.photos.setChecked(True)
    manager.videos.setChecked(False)
    assert manager.include_photos() is True
    assert manager.include_videos() is False

    manager.photos.setChecked(False)
    assert manager.include_photos() is False
    assert manager.include_videos() is False


def test_loading_page_announces_model_and_can_show_retry():
    qt_app()
    page = LoadingPage()
    assert page.title.text() == "Loading AI model"
    assert page.progress.minimum() == 0
    assert page.progress.maximum() == 0
    assert page.retry.isHidden()
    page.show_error("offline")
    assert page.retry.isHidden() is False


def test_clicking_video_surface_emits_play_pause_action():
    app = qt_app()
    video = ClickableVideoWidget()
    clicks = []
    video.clicked.connect(lambda: clicks.append(True))
    video.resize(320, 180)
    video.show()
    app.processEvents()

    QTest.mouseClick(video, Qt.MouseButton.LeftButton)

    assert clicks == [True]
    video.close()


def test_brand_assets_and_basic_palette_are_available():
    assert asset_path("app_icon_rounded.icns").is_file()
    assert asset_path("app_icon_rounded.png").is_file()
    assert asset_path("footage_crawler_logo.png").is_file()
    assert asset_path("header.png").is_file()
    assert QIcon(str(application_icon_path())).isNull() is False
    assert APP_YELLOW == "#EDD047"
    assert APP_YELLOW in APP_STYLE
    assert "background: #171717" in APP_STYLE
    assert "background: #FFFFFF" in APP_STYLE
    assert "background: #EDD047" not in APP_STYLE


def test_search_folder_filters_default_to_all_and_emit_checked_folders(tmp_path: Path):
    qt_app()
    home = HomePage()
    first = tmp_path / "archive" / "client" / "shoot-one"
    second = tmp_path / "archive" / "client" / "shoot-two"
    home.set_folders([first, second])

    assert home.included_folders() == [first, second]
    assert home.folder_checks[first].text() == "…/archive/client/shoot-one"
    assert home.folder_checks[first].toolTip() == str(first)

    emitted = []
    home.search_requested.connect(lambda query, folders: emitted.append((query, folders)))
    home.folder_checks[first].setChecked(False)
    home.search.setText("night driving")
    home._search()

    assert emitted == [("night driving", [second])]
    assert home.status.text() == "1 of 2 included"
