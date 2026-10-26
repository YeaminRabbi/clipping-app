"""SQLite storage. The engine is the only process that touches the database."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Each entry migrates the schema from version i to i + 1. Append only; never edit a shipped migration.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE projects (
        id            INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        settings_json TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE sources (
        id              INTEGER PRIMARY KEY,
        project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        origin          TEXT NOT NULL CHECK (origin IN ('url', 'file')),
        url             TEXT,
        path            TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        duration_ms     INTEGER,
        fps             REAL,
        width           INTEGER,
        height          INTEGER,
        proxy_path      TEXT,
        transcript_path TEXT,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE clips (
        id                 INTEGER PRIMARY KEY,
        source_id          INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        start_ms           INTEGER NOT NULL,
        end_ms             INTEGER NOT NULL,
        score              REAL,
        score_reasons_json TEXT NOT NULL DEFAULT '[]',
        title              TEXT,
        status             TEXT NOT NULL DEFAULT 'suggested'
                           CHECK (status IN ('suggested', 'kept', 'rejected')),
        sort_order         INTEGER NOT NULL DEFAULT 0,
        CHECK (end_ms > start_ms)
    );

    CREATE TABLE clip_formats (
        id                  INTEGER PRIMARY KEY,
        clip_id             INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
        aspect              TEXT NOT NULL,
        mode                TEXT NOT NULL DEFAULT 'smart' CHECK (mode IN ('smart', 'manual', 'fit')),
        crop_keyframes_json TEXT NOT NULL DEFAULT '[]'
    );

    CREATE TABLE caption_styles (
        id         INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        template   TEXT NOT NULL,
        font       TEXT,
        color      TEXT,
        position   TEXT
    );

    CREATE TABLE export_jobs (
        id             INTEGER PRIMARY KEY,
        clip_format_id INTEGER NOT NULL REFERENCES clip_formats(id) ON DELETE CASCADE,
        preset_json    TEXT NOT NULL DEFAULT '{}',
        burn_captions  INTEGER NOT NULL DEFAULT 0,
        export_srt     INTEGER NOT NULL DEFAULT 0,
        status         TEXT NOT NULL DEFAULT 'queued',
        progress       REAL NOT NULL DEFAULT 0,
        output_path    TEXT,
        error          TEXT,
        created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE INDEX idx_sources_project ON sources(project_id);
    CREATE INDEX idx_clips_source ON clips(source_id);
    CREATE INDEX idx_clip_formats_clip ON clip_formats(clip_id);
    CREATE INDEX idx_export_jobs_format ON export_jobs(clip_format_id);
    """,
    # Ingest tracking. `status` moves through: queued -> downloading -> probing -> processing -> ready,
    # or ends in failed / cancelled.
    """
    ALTER TABLE sources ADD COLUMN title TEXT;
    ALTER TABLE sources ADD COLUMN progress REAL NOT NULL DEFAULT 0;
    ALTER TABLE sources ADD COLUMN error TEXT;
    ALTER TABLE sources ADD COLUMN size_bytes INTEGER;
    ALTER TABLE sources ADD COLUMN video_codec TEXT;
    ALTER TABLE sources ADD COLUMN audio_codec TEXT;
    ALTER TABLE sources ADD COLUMN has_audio INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE sources ADD COLUMN is_vfr INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE sources ADD COLUMN poster_path TEXT;
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = path

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success and rolls back on error."""
        conn = self._open()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> int:
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for i in range(version, len(MIGRATIONS)):
                conn.executescript(MIGRATIONS[i])
                conn.execute(f"PRAGMA user_version = {i + 1}")
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def schema_version(self) -> int:
        with self.connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]
