from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_websearch import store
from ai_websearch.config import settings


def test_embedding_database_identity_includes_immutable_revision() -> None:
    assert settings.embedding_model in settings.embedding_model_identity
    assert settings.embedding_model_revision in settings.embedding_model_identity


def _legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE rag_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO rag_metadata VALUES('embedding_model', 'sentence-transformers/all-MiniLM-L6-v2');
            CREATE TABLE sources(
                id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, canonical_url TEXT,
                title TEXT DEFAULT '', domain TEXT DEFAULT '', topic TEXT, fetched_at TEXT NOT NULL,
                published_at TEXT, content_hash TEXT NOT NULL, source_score REAL DEFAULT 0.5,
                source_explanation TEXT DEFAULT '', markdown TEXT NOT NULL,
                UNIQUE(canonical_url, content_hash)
            );
            CREATE TABLE chunks(
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL, url TEXT NOT NULL,
                canonical_url TEXT, title TEXT DEFAULT '', topic TEXT, fetched_at TEXT NOT NULL,
                published_at TEXT, chunk_index INTEGER NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL,
                embedding BLOB NOT NULL, dim INTEGER NOT NULL, token_estimate INTEGER DEFAULT 0,
                source_score REAL DEFAULT 0.5, source_explanation TEXT DEFAULT '',
                FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
                UNIQUE(source_id, chunk_index)
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id UNINDEXED, title, text, url UNINDEXED, topic UNINDEXED
            );
            INSERT INTO sources VALUES(
                1, 'https://example.test', 'https://example.test', 'Example', 'example.test', 'topic',
                '2026-01-01', NULL, 'hash', 0.9, 'obsolete', 'evidence'
            );
            INSERT INTO chunks VALUES(
                1, 1, 'https://example.test', 'https://example.test', 'Example', 'topic', '2026-01-01',
                NULL, 0, 'evidence', 'hash', X'00000000', 1, 1, 0.9, 'obsolete'
            );
            INSERT INTO chunks_fts VALUES(1, 'Example', 'evidence', 'https://example.test', 'topic');
            """
        )


def test_source_scoring_columns_are_removed_transactionally(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _legacy_database(path)
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            source_columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)")}
            chunk_columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
            assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 1
            assert (
                connection.execute(
                    "SELECT value FROM rag_metadata WHERE key='schema_version'"
                ).fetchone()[0]
                == "5"
            )
            assert connection.execute("SELECT active FROM sources").fetchone()[0] == 1
            assert (
                connection.execute("SELECT quality_status FROM sources").fetchone()[0] == "unknown"
            )
            assert connection.execute("SELECT topic FROM source_topics").fetchone()[0] == "topic"
            assert "published_at_source" in source_columns
            assert "published_at_source" in chunk_columns
        assert not {"source_score", "source_explanation"} & source_columns
        assert not {"source_score", "source_explanation"} & chunk_columns
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        settings.database_path = original
