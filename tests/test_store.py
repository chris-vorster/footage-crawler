from pathlib import Path

import numpy as np

from footage_search.store import LibraryStore


def test_search_groups_moments_by_media_asset(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    video = media / "one.mp4"
    photo = media / "two.jpg"
    video.write_bytes(b"video")
    photo.write_bytes(b"photo")
    store = LibraryStore(tmp_path / "library.sqlite3")
    video_id, _ = store.reconcile_asset(video, "video")
    photo_id, _ = store.reconcile_asset(photo, "photo")
    store.replace_moments(
        video_id,
        [
            (1.0, tmp_path / "v1.jpg", np.array([1.0, 0.0], dtype=np.float32)),
            (5.0, tmp_path / "v2.jpg", np.array([0.8, 0.2], dtype=np.float32)),
        ],
        10.0,
    )
    store.replace_moments(
        photo_id,
        [(0.0, tmp_path / "p.jpg", np.array([0.0, 1.0], dtype=np.float32))],
        None,
    )

    hits = store.search(np.array([1.0, 0.0], dtype=np.float32))

    assert [hit.path for hit in hits] == [str(video), str(photo)]
    assert hits[0].timestamp_seconds == 1.0
    assert len(hits) == 2
    store.close()


def test_reconcile_preserves_unchanged_ready_asset(tmp_path: Path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"photo")
    store = LibraryStore(tmp_path / "library.sqlite3")
    asset_id, changed = store.reconcile_asset(photo, "photo")
    assert changed is True
    store.replace_moments(
        asset_id,
        [(0.0, tmp_path / "thumb.jpg", np.array([1.0], dtype=np.float32))],
        None,
    )

    same_id, changed = store.reconcile_asset(photo, "photo")

    assert same_id == asset_id
    assert changed is False
    store.close()


def test_search_can_filter_results_to_checked_library_folders(tmp_path: Path):
    included = tmp_path / "included"
    excluded = tmp_path / "excluded"
    included.mkdir()
    excluded.mkdir()
    included_photo = included / "one.jpg"
    excluded_photo = excluded / "two.jpg"
    included_photo.write_bytes(b"photo")
    excluded_photo.write_bytes(b"photo")
    store = LibraryStore(tmp_path / "library.sqlite3")
    included_id, _ = store.reconcile_asset(included_photo, "photo")
    excluded_id, _ = store.reconcile_asset(excluded_photo, "photo")
    store.replace_moments(
        included_id,
        [(0.0, tmp_path / "one-thumb.jpg", np.array([1.0, 0.0], dtype=np.float32))],
        None,
    )
    store.replace_moments(
        excluded_id,
        [(0.0, tmp_path / "two-thumb.jpg", np.array([1.0, 0.0], dtype=np.float32))],
        None,
    )

    hits = store.search(
        np.array([1.0, 0.0], dtype=np.float32), included_folders=[included]
    )

    assert [hit.path for hit in hits] == [str(included_photo)]
    assert store.search(np.array([1.0, 0.0], dtype=np.float32), included_folders=[]) == []
    store.close()


def test_changing_sampling_profile_invalidates_only_videos(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    photo = tmp_path / "photo.jpg"
    video.write_bytes(b"video")
    photo.write_bytes(b"photo")
    store = LibraryStore(tmp_path / "library.sqlite3")
    video_id, _ = store.reconcile_asset(video, "video")
    photo_id, _ = store.reconcile_asset(photo, "photo")
    vector = np.array([1.0, 0.0], dtype=np.float32)
    store.replace_moments(video_id, [(0.0, tmp_path / "video-thumb.jpg", vector)], 10.0)
    store.replace_moments(photo_id, [(0.0, tmp_path / "photo-thumb.jpg", vector)], None)

    store.invalidate_video_index()

    assert store.reconcile_asset(video, "video")[1] is True
    assert store.reconcile_asset(photo, "photo")[1] is False
    hits = store.search(vector)
    assert [hit.path for hit in hits] == [str(photo)]
    store.close()
