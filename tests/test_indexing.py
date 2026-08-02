from pathlib import Path

import numpy as np
from PIL import Image

from footage_search.indexing import IndexWorker, SearchWorker
from footage_search.store import LibraryStore


class FakeRetriever:
    def embed_images(self, paths):
        return np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (len(paths), 1))


class FakeEngine:
    def __init__(self):
        self.retriever = FakeRetriever()

    def load(self):
        return "cpu"

    def embed_images(self, paths):
        return self.retriever.embed_images(paths)

    def embed_text(self, query):
        return np.array([1.0, 0.0], dtype=np.float32)


def test_photo_vertical_slice_indexes_and_persists(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    Image.new("RGB", (80, 60), "red").save(media / "red.jpg")
    database = tmp_path / "library.sqlite3"
    completed = []
    worker = IndexWorker(database, tmp_path / "cache", [media], True, False, "fast", FakeEngine())
    worker.completed.connect(completed.append)

    worker.run()

    assert completed[0]["ready"] == 1
    assert completed[0]["moments"] == 1
    store = LibraryStore(database)
    hits = store.search(np.array([1.0, 0.0], dtype=np.float32))
    assert Path(hits[0].path).name == "red.jpg"
    assert Path(hits[0].thumbnail_path).is_file()
    store.close()


def test_search_worker_reports_phases_and_results(tmp_path: Path):
    media = tmp_path / "photo.jpg"
    media.write_bytes(b"photo")
    database = tmp_path / "library.sqlite3"
    store = LibraryStore(database)
    asset_id, _ = store.reconcile_asset(media, "photo")
    store.replace_moments(
        asset_id,
        [(0.0, tmp_path / "thumb.jpg", np.array([1.0, 0.0], dtype=np.float32))],
        None,
    )
    store.close()
    phases, results, failures = [], [], []
    worker = SearchWorker(database, "red photo", FakeEngine())
    worker.phase.connect(phases.append)
    worker.completed.connect(lambda query, hits: results.append((query, hits)))
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert phases == [
        "Preparing the local visual model…",
        "Encoding your search…",
        "Ranking Indexed Photos and Moments…",
    ]
    assert results[0][0] == "red photo"
    assert results[0][1][0].path == str(media)
