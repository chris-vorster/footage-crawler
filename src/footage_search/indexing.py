from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .media import (
    discover,
    photo_thumbnail,
    require_ffmpeg,
    sample_timestamps,
    video_duration,
    video_frame,
)
from .retrieval import VisualRetriever, install_model, model_is_installed
from .store import LibraryStore

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """Keep model creation and inference on one persistent native thread."""

    def __init__(self, model_directory: Path):
        self.model_directory = model_directory
        self._retriever: VisualRetriever | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="footage-inference")

    def _load(self) -> str:
        if self._retriever is None:
            started = time.perf_counter()
            install_model(self.model_directory)
            logger.info("Loading installed visual model on the inference thread")
            self._retriever = VisualRetriever(self.model_directory)
            logger.info(
                "Visual model ready: device=%s elapsed=%.2fs",
                self._retriever.device,
                time.perf_counter() - started,
            )
        return self._retriever.device

    def load(self) -> str:
        return self._executor.submit(self._load).result()

    def is_installed(self) -> bool:
        return model_is_installed(self.model_directory)

    def embed_images(self, paths: list[Path]):
        def operation():
            self._load()
            return self._retriever.embed_images(paths)

        return self._executor.submit(operation).result()

    def embed_text(self, query: str):
        def operation():
            self._load()
            return self._retriever.embed_text(query)

        return self._executor.submit(operation).result()

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


class ModelLoadWorker(QObject):
    phase = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: RetrievalEngine):
        super().__init__()
        self.engine = engine

    @Slot()
    def run(self) -> None:
        try:
            if self.engine.is_installed():
                self.phase.emit("Opening the AI model stored on this computer…")
            else:
                self.phase.emit("Downloading the AI model once for future offline use…")
            device = self.engine.load()
            self.completed.emit(device)
        except Exception as error:
            logger.exception("Startup model loading failed")
            self.failed.emit(str(error))


class IndexWorker(QObject):
    phase = Signal(str)
    progress = Signal(int, int, str)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: Path,
        cache_path: Path,
        folders: list[Path],
        include_photos: bool,
        include_videos: bool,
        profile: str,
        engine: RetrievalEngine,
    ):
        super().__init__()
        self.database_path = database_path
        self.cache_path = cache_path
        self.folders = folders
        self.include_photos = include_photos
        self.include_videos = include_videos
        self.profile = profile
        self.engine = engine
        self._paused = threading.Event()
        self._cancelled = threading.Event()

    @Slot()
    def run(self) -> None:
        store = LibraryStore(self.database_path)
        started = time.perf_counter()
        try:
            logger.info(
                "Indexing job started: folders=%s photos=%s videos=%s profile=%s",
                [str(folder) for folder in self.folders],
                self.include_photos,
                self.include_videos,
                self.profile,
            )
            self.phase.emit("Scanning folders")
            media = []
            for folder in self.folders:
                logger.info("Scanning folder: %s", folder)
                discovered = discover(folder, self.include_photos, self.include_videos)
                logger.info("Folder scan complete: folder=%s discovered=%d", folder, len(discovered))
                media.extend(discovered)
            unique_media = list(dict.fromkeys(media))
            logger.info("Scan complete: discovered=%d", len(unique_media))
            store.mark_missing_except(path for path, _ in unique_media)
            pending = []
            for path, kind in unique_media:
                asset_id, needs_index = store.reconcile_asset(path, kind)
                if needs_index:
                    pending.append((asset_id, path, kind))
            logger.info("Reconciliation complete: pending=%d unchanged=%d", len(pending), len(unique_media) - len(pending))
            if not pending:
                logger.info("Indexing job complete: library already current")
                self.progress.emit(len(unique_media), len(unique_media), "Library is already current")
                self.completed.emit(store.stats())
                return

            if any(kind == "video" for _, _, kind in pending):
                require_ffmpeg()
            self.phase.emit("Loading the local visual model")
            device = self.engine.load()
            logger.info("Indexing will use device=%s", device)
            self.phase.emit("Indexing photos and video moments")
            total = len(pending)
            for index, (asset_id, path, kind) in enumerate(pending, start=1):
                if self._cancelled.is_set():
                    logger.info("Indexing job cancelled at %d/%d", index - 1, total)
                    break
                while self._paused.is_set() and not self._cancelled.wait(0.2):
                    pass
                self.progress.emit(index - 1, total, path.name)
                asset_started = time.perf_counter()
                logger.info("Indexing asset %d/%d: kind=%s path=%s", index, total, kind, path)
                try:
                    target_dir = self.cache_path / "thumbnails" / str(asset_id)
                    if kind == "photo":
                        thumbnail = photo_thumbnail(path, target_dir / "000000.jpg")
                        embedding = self.engine.embed_images([thumbnail])[0]
                        store.replace_moments(asset_id, [(0.0, thumbnail, embedding)], None)
                    else:
                        duration = video_duration(path)
                        timestamps = sample_timestamps(duration, self.profile)
                        logger.info(
                            "Sampling video: path=%s duration=%.2fs moments=%d",
                            path,
                            duration,
                            len(timestamps),
                        )
                        frames = [
                            video_frame(path, timestamp, target_dir / f"{round(timestamp * 1000):09d}.jpg")
                            for timestamp in timestamps
                        ]
                        moments = []
                        for start in range(0, len(frames), 8):
                            batch = frames[start:start + 8]
                            embeddings = self.engine.embed_images(batch)
                            moments.extend(
                                (timestamps[start + offset], frame, embeddings[offset])
                                for offset, frame in enumerate(batch)
                            )
                        store.replace_moments(asset_id, moments, duration)
                    logger.info(
                        "Indexed asset %d/%d in %.2fs: path=%s",
                        index,
                        total,
                        time.perf_counter() - asset_started,
                        path,
                    )
                except Exception as error:
                    logger.exception("Asset indexing failed: path=%s", path)
                    store.mark_error(asset_id, str(error))
            self.progress.emit(total, total, "Indexing complete")
            stats = store.stats()
            logger.info("Indexing job complete in %.2fs: stats=%s", time.perf_counter() - started, stats)
            self.completed.emit(stats)
        except Exception as error:
            logger.exception("Indexing job failed")
            self.failed.emit(str(error))
        finally:
            store.close()

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    @Slot()
    def cancel(self) -> None:
        self._cancelled.set()
        self._paused.clear()


class SearchWorker(QObject):
    phase = Signal(str)
    completed = Signal(str, list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: Path,
        query: str,
        engine: RetrievalEngine,
        included_folders: list[Path] | None = None,
    ):
        super().__init__()
        self.database_path = database_path
        self.query = query
        self.engine = engine
        self.included_folders = included_folders

    @Slot()
    def run(self) -> None:
        store = LibraryStore(self.database_path)
        started = time.perf_counter()
        try:
            logger.info(
                "Search started: query=%r included_folders=%s",
                self.query,
                None if self.included_folders is None else [str(path) for path in self.included_folders],
            )
            self.phase.emit("Preparing the local visual model…")
            device = self.engine.load()
            logger.info("Search model ready: device=%s", device)
            self.phase.emit("Encoding your search…")
            embedding = self.engine.embed_text(self.query)
            self.phase.emit("Ranking Indexed Photos and Moments…")
            hits = store.search(embedding, included_folders=self.included_folders)
            logger.info(
                "Search complete in %.2fs: query=%r hits=%d",
                time.perf_counter() - started,
                self.query,
                len(hits),
            )
            self.completed.emit(self.query, hits)
        except Exception as error:
            logger.exception("Search failed: query=%r", self.query)
            self.failed.emit(str(error))
        finally:
            store.close()
