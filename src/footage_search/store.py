from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    asset_id: int
    moment_id: int
    path: str
    kind: str
    timestamp_seconds: float
    thumbnail_path: str
    score: float


class LibraryStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK(kind IN ('photo', 'video')),
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                duration_seconds REAL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                indexed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS moments (
                id INTEGER PRIMARY KEY,
                asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                timestamp_seconds REAL NOT NULL,
                thumbnail_path TEXT NOT NULL,
                embedding BLOB NOT NULL,
                dimensions INTEGER NOT NULL,
                UNIQUE(asset_id, timestamp_seconds)
            );
            CREATE INDEX IF NOT EXISTS moments_asset_id ON moments(asset_id);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def set_setting(self, key: str, value) -> None:
        encoded = json.dumps(value)
        self.connection.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, encoded),
        )
        self.connection.commit()

    def get_setting(self, key: str, default=None):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def reconcile_asset(self, path: Path, kind: str) -> tuple[int, bool]:
        stat = path.stat()
        row = self.connection.execute(
            "SELECT id, size, mtime_ns, status FROM assets WHERE path=?", (str(path),)
        ).fetchone()
        changed = row is None or row["size"] != stat.st_size or row["mtime_ns"] != stat.st_mtime_ns
        if row is None:
            cursor = self.connection.execute(
                "INSERT INTO assets(path, kind, size, mtime_ns) VALUES(?, ?, ?, ?)",
                (str(path), kind, stat.st_size, stat.st_mtime_ns),
            )
            asset_id = int(cursor.lastrowid)
        else:
            asset_id = int(row["id"])
            if changed:
                self.connection.execute("DELETE FROM moments WHERE asset_id=?", (asset_id,))
                self.connection.execute(
                    "UPDATE assets SET kind=?, size=?, mtime_ns=?, status='pending', error=NULL WHERE id=?",
                    (kind, stat.st_size, stat.st_mtime_ns, asset_id),
                )
        self.connection.commit()
        return asset_id, changed or (row is not None and row["status"] != "ready")

    def mark_missing_except(self, paths: Iterable[Path]) -> None:
        present = {str(path) for path in paths}
        rows = self.connection.execute("SELECT id, path FROM assets").fetchall()
        for row in rows:
            if row["path"] not in present:
                self.connection.execute(
                    "UPDATE assets SET status='missing', error='Original media is no longer present' WHERE id=?",
                    (row["id"],),
                )
        self.connection.commit()

    def replace_moments(
        self,
        asset_id: int,
        moments: Iterable[tuple[float, Path, np.ndarray]],
        duration_seconds: float | None,
    ) -> None:
        self.connection.execute("DELETE FROM moments WHERE asset_id=?", (asset_id,))
        for timestamp, thumbnail, embedding in moments:
            vector = np.asarray(embedding, dtype=np.float32)
            self.connection.execute(
                "INSERT INTO moments(asset_id, timestamp_seconds, thumbnail_path, embedding, dimensions) "
                "VALUES(?, ?, ?, ?, ?)",
                (asset_id, timestamp, str(thumbnail), vector.tobytes(), vector.size),
            )
        self.connection.execute(
            "UPDATE assets SET duration_seconds=?, status='ready', error=NULL, indexed_at=datetime('now') WHERE id=?",
            (duration_seconds, asset_id),
        )
        self.connection.commit()

    def mark_error(self, asset_id: int, message: str) -> None:
        self.connection.execute(
            "UPDATE assets SET status='error', error=? WHERE id=?", (message[:1000], asset_id)
        )
        self.connection.commit()

    def invalidate_video_index(self) -> None:
        """Resample videos after the user changes the sampling profile."""
        video_ids = self.connection.execute(
            "SELECT id FROM assets WHERE kind='video' AND status != 'missing'"
        ).fetchall()
        ids = [int(row["id"]) for row in video_ids]
        for asset_id in ids:
            self.connection.execute("DELETE FROM moments WHERE asset_id=?", (asset_id,))
            self.connection.execute(
                "UPDATE assets SET status='pending', error=NULL, indexed_at=NULL WHERE id=?",
                (asset_id,),
            )
        self.connection.commit()
        logger.info("Invalidated video index for resampling: videos=%d", len(ids))

    def stats(self) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT COUNT(*) assets, "
            "SUM(status='ready') ready, SUM(status='error') errors, SUM(status='missing') missing "
            "FROM assets"
        ).fetchone()
        moments = self.connection.execute("SELECT COUNT(*) count FROM moments").fetchone()["count"]
        return {
            "assets": int(row["assets"] or 0),
            "ready": int(row["ready"] or 0),
            "errors": int(row["errors"] or 0),
            "missing": int(row["missing"] or 0),
            "moments": int(moments),
        }

    def search(
        self,
        query_embedding: np.ndarray,
        limit: int = 30,
        included_folders: list[Path] | None = None,
    ) -> list[SearchHit]:
        started = time.perf_counter()
        query = np.asarray(query_embedding, dtype=np.float32)
        rows = self.connection.execute(
            "SELECT m.id moment_id, m.asset_id, m.timestamp_seconds, m.thumbnail_path, "
            "m.embedding, m.dimensions, a.path, a.kind "
            "FROM moments m JOIN assets a ON a.id=m.asset_id WHERE a.status='ready'"
        ).fetchall()
        if included_folders is not None:
            roots = [Path(folder) for folder in included_folders]
            rows = [
                row
                for row in rows
                if any(Path(row["path"]).is_relative_to(root) for root in roots)
            ]
        logger.info("Ranking search candidates: moments=%d dimensions=%d limit=%d", len(rows), query.size, limit)
        best_by_asset: dict[int, SearchHit] = {}
        for row in rows:
            if row["dimensions"] != query.size:
                continue
            vector = np.frombuffer(row["embedding"], dtype=np.float32)
            score = float(np.dot(query, vector))
            hit = SearchHit(
                asset_id=int(row["asset_id"]),
                moment_id=int(row["moment_id"]),
                path=row["path"],
                kind=row["kind"],
                timestamp_seconds=float(row["timestamp_seconds"]),
                thumbnail_path=row["thumbnail_path"],
                score=score,
            )
            previous = best_by_asset.get(hit.asset_id)
            if previous is None or hit.score > previous.score:
                best_by_asset[hit.asset_id] = hit
        hits = sorted(best_by_asset.values(), key=lambda item: item.score, reverse=True)[:limit]
        logger.info(
            "Ranking complete in %.3fs: grouped_assets=%d returned=%d",
            time.perf_counter() - started,
            len(best_by_asset),
            len(hits),
        )
        return hits
