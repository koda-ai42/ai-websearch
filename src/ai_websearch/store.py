from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from .clean import content_hash
from .config import settings
from .content_quality import QUALITY_POLICY_VERSION, assess_content_quality
from .errors import EmbeddingModelMismatchError, FtsQueryError
from .models import IngestResult
from .security import safe_model_label

SCHEMA_VERSION = 5
EMBEDDING_INPUT_VERSION = "clean_sections_v3"
FTS_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
_initialization_lock = threading.Lock()
_initialized_databases: set[tuple[str, int, int]] = set()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS rag_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    canonical_url TEXT,
    title TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    topic TEXT,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    published_at_source TEXT,
    content_hash TEXT NOT NULL,
    markdown TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    quality_status TEXT NOT NULL DEFAULT 'unknown',
    quality_reason TEXT NOT NULL DEFAULT '',
    quality_version INTEGER NOT NULL DEFAULT 0,
    UNIQUE(canonical_url, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_sources_topic ON sources(topic);
CREATE INDEX IF NOT EXISTS idx_sources_fetched_at ON sources(fetched_at);

CREATE TABLE IF NOT EXISTS source_topics (
    source_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    PRIMARY KEY(source_id, topic),
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_topics_topic ON source_topics(topic);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT,
    title TEXT DEFAULT '',
    topic TEXT,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    published_at_source TEXT,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dim INTEGER NOT NULL,
    token_estimate INTEGER DEFAULT 0,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE(source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_topic ON chunks(topic);
CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    text,
    url UNINDEXED,
    topic UNINDEXED
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    source_columns = _columns(conn, "sources")
    chunk_columns = _columns(conn, "chunks")
    obsolete = [
        ("sources", "source_score", source_columns),
        ("sources", "source_explanation", source_columns),
        ("chunks", "source_score", chunk_columns),
        ("chunks", "source_explanation", chunk_columns),
    ]
    try:
        with conn:
            for table, column, existing in obsolete:
                if column in existing:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            if "active" not in source_columns:
                conn.execute("ALTER TABLE sources ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
                conn.execute(
                    """UPDATE sources SET active = CASE WHEN id IN (
                           SELECT MAX(id) FROM sources GROUP BY canonical_url
                       ) THEN 1 ELSE 0 END"""
                )
            if "quality_status" not in source_columns:
                conn.execute(
                    "ALTER TABLE sources ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'unknown'"
                )
            if "quality_reason" not in source_columns:
                conn.execute(
                    "ALTER TABLE sources ADD COLUMN quality_reason TEXT NOT NULL DEFAULT ''"
                )
            if "quality_version" not in source_columns:
                conn.execute(
                    "ALTER TABLE sources ADD COLUMN quality_version INTEGER NOT NULL DEFAULT 0"
                )
            if "published_at_source" not in source_columns:
                conn.execute("ALTER TABLE sources ADD COLUMN published_at_source TEXT")
            if "published_at_source" not in chunk_columns:
                conn.execute("ALTER TABLE chunks ADD COLUMN published_at_source TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sources_canonical_active ON sources(canonical_url, active)"
            )
            conn.execute(
                """INSERT OR IGNORE INTO source_topics(source_id, topic)
                   SELECT id, topic FROM sources WHERE topic IS NOT NULL AND trim(topic) != ''"""
            )
            conn.execute(
                "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
    except sqlite3.Error as exc:
        raise RuntimeError(
            "Database schema migration failed; no source-scoring data was removed."
        ) from exc


def connect() -> sqlite3.Connection:
    path = settings.db_path
    conn = sqlite3.connect(path, timeout=settings.database_busy_timeout_seconds)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(settings.database_busy_timeout_seconds * 1000)}")
        stat = path.stat()
        identity = (str(path), int(stat.st_dev), int(stat.st_ino))
        with _initialization_lock:
            if identity not in _initialized_databases:
                conn.executescript(SCHEMA)
                _migrate_schema(conn)
                _initialized_databases.add(identity)
    except Exception:
        conn.close()
        raise
    for database_file in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            if database_file.exists():
                os.chmod(database_file, 0o600)
        except OSError:
            pass
    return conn


def clear_database_initialization_cache() -> None:
    """Reset process-local lifecycle state for isolated tests and maintenance."""

    with _initialization_lock:
        _initialized_databases.clear()


def _metadata_dict(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM rag_metadata")}


def embedding_metadata() -> dict:
    with connect() as conn:
        values = _metadata_dict(conn)
    dim = values.get("embedding_dimension")
    return {
        "embedding_model": values.get("embedding_model"),
        "embedding_dimension": int(dim) if dim and dim.isdigit() else None,
        "embedding_normalized": values.get("embedding_normalized") == "true",
        "embedding_input_version": values.get("embedding_input_version"),
    }


def initialize_database() -> None:
    with connect() as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        values = _metadata_dict(conn)
        stored_model = values.get("embedding_model")
        stored_input_version = values.get("embedding_input_version")
        if count and (
            stored_model != settings.embedding_model_identity
            or stored_input_version != EMBEDDING_INPUT_VERSION
        ):
            raise EmbeddingModelMismatchError(
                "The existing database uses a different embedding model or input representation.",
                details={
                    "database_model": safe_model_label(stored_model),
                    "configured_model": safe_model_label(settings.embedding_model_identity),
                    "database_input_version": stored_input_version,
                    "configured_input_version": EMBEDDING_INPUT_VERSION,
                },
                resolution="Back up and rebuild the evidence database before changing embedding inputs.",
            )
        if not count:
            conn.execute(
                "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_model', ?)",
                (settings.embedding_model_identity,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_normalized', 'true')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_input_version', ?)",
                (EMBEDDING_INPUT_VERSION,),
            )
            if stored_model and stored_model != settings.embedding_model_identity:
                conn.execute("DELETE FROM rag_metadata WHERE key = 'embedding_dimension'")
            conn.commit()


def ensure_embedding_metadata(model_name: str, dimension: int) -> None:
    with connect() as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        values = _metadata_dict(conn)
        stored_model = values.get("embedding_model")
        stored_dim = values.get("embedding_dimension")
        stored_input_version = values.get("embedding_input_version")
        mismatch = (
            stored_model not in {None, model_name}
            or (stored_dim is not None and int(stored_dim) != dimension)
            or (count and stored_input_version != EMBEDDING_INPUT_VERSION)
        )
        if count and mismatch:
            raise EmbeddingModelMismatchError(
                "The configured embedding model is incompatible with vectors already stored in the database.",
                details={
                    "database_model": safe_model_label(stored_model),
                    "database_dimension": int(stored_dim) if stored_dim else None,
                    "configured_model": safe_model_label(model_name),
                    "configured_dimension": dimension,
                    "database_input_version": stored_input_version,
                    "configured_input_version": EMBEDDING_INPUT_VERSION,
                },
                resolution="Back up and rebuild the evidence database before changing embedding inputs.",
            )
        conn.execute(
            "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_model', ?)",
            (model_name,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_dimension', ?)",
            (str(dimension),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_normalized', 'true')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO rag_metadata(key, value) VALUES('embedding_input_version', ?)",
            (EMBEDDING_INPUT_VERSION,),
        )
        conn.commit()


def vector_to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def blob_to_vector(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 3.5 + 0.999))


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


def _associate_topic(conn: sqlite3.Connection, source_id: int, topic: str | None) -> None:
    if topic and topic.strip():
        conn.execute(
            "INSERT OR IGNORE INTO source_topics(source_id, topic) VALUES(?, ?)",
            (source_id, topic),
        )


def _quality_fields(title: str, markdown: str) -> tuple[str, str, int]:
    assessment = assess_content_quality(title, markdown)
    status = "usable" if assessment.usable else "quarantined"
    return status, assessment.reason, QUALITY_POLICY_VERSION


def audit_source_quality(*, apply: bool = False) -> dict:
    """Assess active stored sources without exposing or deleting their content."""

    rows_out: list[dict] = []
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, markdown, quality_status, quality_reason, quality_version
               FROM sources WHERE active = 1 ORDER BY id"""
        ).fetchall()
        for row in rows:
            status, reason, version = _quality_fields(row["title"] or "", row["markdown"])
            changed = (
                row["quality_status"] != status
                or row["quality_reason"] != reason
                or int(row["quality_version"] or 0) != version
            )
            rows_out.append(
                {
                    "source_id": int(row["id"]),
                    "previous_status": row["quality_status"],
                    "proposed_status": status,
                    "reason": reason,
                    "changed": changed,
                }
            )
            if apply and changed:
                conn.execute(
                    """UPDATE sources SET quality_status = ?, quality_reason = ?,
                              quality_version = ? WHERE id = ?""",
                    (status, reason, version, int(row["id"])),
                )
        if apply:
            conn.commit()
    return {
        "applied": apply,
        "sources_assessed": len(rows_out),
        "usable": sum(row["proposed_status"] == "usable" for row in rows_out),
        "quarantined": sum(row["proposed_status"] == "quarantined" for row in rows_out),
        "changed": sum(row["changed"] for row in rows_out),
        "sources": rows_out,
    }


def find_fresh_source(url: str, topic: str | None, ttl_hours: int) -> IngestResult | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, ttl_hours))
    with connect() as conn:
        row = conn.execute(
            """SELECT id, url, canonical_url, title, fetched_at, published_at,
                      published_at_source, content_hash,
                      markdown, quality_status, quality_reason, quality_version
               FROM sources
               WHERE active = 1 AND (url = ? OR canonical_url = ?)
               ORDER BY fetched_at DESC LIMIT 1""",
            (url, url),
        ).fetchone()
        if row is None:
            return None
        try:
            fetched = datetime.fromisoformat(str(row["fetched_at"]).replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        if fetched < cutoff:
            return None
        status = row["quality_status"]
        reason = row["quality_reason"]
        version = int(row["quality_version"] or 0)
        if version != QUALITY_POLICY_VERSION or status == "unknown":
            status, reason, version = _quality_fields(row["title"] or "", row["markdown"])
            conn.execute(
                """UPDATE sources SET quality_status = ?, quality_reason = ?,
                          quality_version = ? WHERE id = ?""",
                (status, reason, version, int(row["id"])),
            )
        if status == "quarantined":
            conn.commit()
            return None
        _associate_topic(conn, int(row["id"]), topic)
        conn.commit()
    return IngestResult(
        ok=True,
        source_id=int(row["id"]),
        url=str(row["url"]),
        canonical_url=row["canonical_url"],
        title=row["title"] or "",
        topic=topic,
        fetched_at=row["fetched_at"],
        published_at=row["published_at"],
        published_at_source=row["published_at_source"],
        content_hash=row["content_hash"],
        cache_status="fresh_hit",
    )


def find_stale_source(
    url: str,
    topic: str | None,
    *,
    refresh_outcome: str,
) -> IngestResult | None:
    """Associate the newest usable active version after a failed refresh."""

    with connect() as conn:
        row = conn.execute(
            """SELECT id, url, canonical_url, title, fetched_at, published_at,
                      published_at_source, content_hash,
                      markdown, quality_status, quality_reason, quality_version
               FROM sources
               WHERE active = 1 AND (url = ? OR canonical_url = ?)
               ORDER BY fetched_at DESC LIMIT 1""",
            (url, url),
        ).fetchone()
        if row is None:
            return None
        status = row["quality_status"]
        reason = row["quality_reason"]
        version = int(row["quality_version"] or 0)
        if version != QUALITY_POLICY_VERSION or status == "unknown":
            status, reason, version = _quality_fields(row["title"] or "", row["markdown"])
            conn.execute(
                """UPDATE sources SET quality_status = ?, quality_reason = ?,
                          quality_version = ? WHERE id = ?""",
                (status, reason, version, int(row["id"])),
            )
        if status == "quarantined":
            conn.commit()
            return None
        _associate_topic(conn, int(row["id"]), topic)
        conn.commit()
    return IngestResult(
        ok=True,
        source_id=int(row["id"]),
        url=str(row["url"]),
        canonical_url=row["canonical_url"],
        title=row["title"] or "",
        topic=topic,
        fetched_at=row["fetched_at"],
        published_at=row["published_at"],
        published_at_source=row["published_at_source"],
        content_hash=row["content_hash"],
        cache_status="stale_fallback",
        refresh_outcome=refresh_outcome,
    )


def reuse_stored_content(
    canonical_url: str,
    content_hash_value: str,
    topic: str | None,
    fetched_at: str,
    published_at: str | None = None,
    published_at_source: str | None = None,
) -> IngestResult | None:
    """Reactivate unchanged or historical content without recomputing embeddings."""

    with connect() as conn:
        row = conn.execute(
            """SELECT id, url, canonical_url, title, content_hash,
                      published_at, published_at_source
               FROM sources WHERE canonical_url = ? AND content_hash = ? LIMIT 1""",
            (canonical_url, content_hash_value),
        ).fetchone()
        if row is None:
            return None
        source_id = int(row["id"])
        conn.execute("UPDATE sources SET active = 0 WHERE canonical_url = ?", (canonical_url,))
        conn.execute(
            """UPDATE sources SET active = 1, fetched_at = ?,
                      published_at = COALESCE(published_at, ?),
                      published_at_source = COALESCE(published_at_source, ?),
                      quality_status = 'usable', quality_reason = 'substantive_content',
                      quality_version = ?
               WHERE id = ?""",
            (
                fetched_at,
                published_at,
                published_at_source,
                QUALITY_POLICY_VERSION,
                source_id,
            ),
        )
        conn.execute(
            """UPDATE chunks SET fetched_at = ?,
                      published_at = COALESCE(published_at, ?),
                      published_at_source = COALESCE(published_at_source, ?)
               WHERE source_id = ?""",
            (fetched_at, published_at, published_at_source, source_id),
        )
        _associate_topic(conn, source_id, topic)
        conn.commit()
    return IngestResult(
        ok=True,
        source_id=source_id,
        url=str(row["url"]),
        canonical_url=row["canonical_url"],
        title=row["title"] or "",
        topic=topic,
        fetched_at=fetched_at,
        published_at=published_at or row["published_at"],
        published_at_source=published_at_source or row["published_at_source"],
        content_hash=row["content_hash"],
        cache_status="content_reused",
    )


def store_document(
    url: str,
    canonical_url: str | None,
    title: str,
    markdown: str,
    fetched_at: str,
    published_at: str | None,
    topic: str | None,
    chunks: list[str],
    embeddings: np.ndarray,
    *,
    published_at_source: str | None = None,
) -> IngestResult:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk count and embedding count differ")
    if embeddings.ndim != 2 or embeddings.shape[1] < 1:
        raise ValueError("Embeddings must be a non-empty 2-D array")
    quality_status, quality_reason, quality_version = _quality_fields(title, markdown)
    if quality_status != "usable":
        raise ValueError(f"Refusing to store unusable content: {quality_reason}")
    ensure_embedding_metadata(settings.embedding_model_identity, int(embeddings.shape[1]))

    chash = content_hash(markdown)
    canonical = canonical_url or url
    try:
        with connect() as conn:
            existing = conn.execute(
                "SELECT id FROM sources WHERE canonical_url = ? AND content_hash = ?",
                (canonical, chash),
            ).fetchone()
            if existing:
                source_id = int(existing["id"])
                conn.execute("UPDATE sources SET active = 0 WHERE canonical_url = ?", (canonical,))
                conn.execute(
                    """UPDATE sources SET active = 1, fetched_at = ?,
                              published_at = COALESCE(published_at, ?),
                              published_at_source = COALESCE(published_at_source, ?),
                              quality_status = ?, quality_reason = ?, quality_version = ?
                       WHERE id = ?""",
                    (
                        fetched_at,
                        published_at,
                        published_at_source,
                        quality_status,
                        quality_reason,
                        quality_version,
                        source_id,
                    ),
                )
                conn.execute(
                    """UPDATE chunks SET fetched_at = ?,
                              published_at = COALESCE(published_at, ?),
                              published_at_source = COALESCE(published_at_source, ?)
                       WHERE source_id = ?""",
                    (fetched_at, published_at, published_at_source, source_id),
                )
                _associate_topic(conn, source_id, topic)
                conn.commit()
                return IngestResult(
                    ok=True,
                    source_id=source_id,
                    url=url,
                    canonical_url=canonical,
                    title=title,
                    topic=topic,
                    fetched_at=fetched_at,
                    published_at=published_at,
                    published_at_source=published_at_source,
                    chunks_stored=0,
                    content_hash=chash,
                    cache_status="content_reused",
                )

            conn.execute("UPDATE sources SET active = 0 WHERE canonical_url = ?", (canonical,))
            cur = conn.execute(
                """
                INSERT INTO sources(
                    url, canonical_url, title, domain, topic, fetched_at,
                    published_at, published_at_source, content_hash, markdown, quality_status,
                    quality_reason, quality_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    canonical,
                    title,
                    domain_from_url(canonical),
                    topic,
                    fetched_at,
                    published_at,
                    published_at_source,
                    chash,
                    markdown,
                    quality_status,
                    quality_reason,
                    quality_version,
                ),
            )
            if cur.lastrowid is None:
                raise RuntimeError("SQLite did not return a source identifier.")
            source_id = int(cur.lastrowid)
            _associate_topic(conn, source_id, topic)
            for index, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                cur = conn.execute(
                    """
                    INSERT INTO chunks(
                        source_id, url, canonical_url, title, topic, fetched_at,
                        published_at, published_at_source, chunk_index, text, text_hash, embedding,
                        dim, token_estimate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        url,
                        canonical,
                        title,
                        topic,
                        fetched_at,
                        published_at,
                        published_at_source,
                        index,
                        chunk,
                        content_hash(chunk),
                        vector_to_blob(vector),
                        int(vector.shape[0]),
                        estimate_tokens(chunk),
                    ),
                )
                if cur.lastrowid is None:
                    raise RuntimeError("SQLite did not return a chunk identifier.")
                conn.execute(
                    "INSERT INTO chunks_fts(chunk_id, title, text, url, topic) VALUES (?, ?, ?, ?, ?)",
                    (int(cur.lastrowid), title, chunk, canonical, topic or ""),
                )
            conn.commit()
        return IngestResult(
            ok=True,
            source_id=source_id,
            url=url,
            canonical_url=canonical,
            title=title,
            topic=topic,
            fetched_at=fetched_at,
            published_at=published_at,
            published_at_source=published_at_source,
            chunks_stored=len(chunks),
            content_hash=chash,
            cache_status="stored",
        )
    except sqlite3.Error as exc:
        raise RuntimeError(f"Database error while storing document: {exc}") from exc


def delete_source(source_id: int) -> bool:
    with connect() as conn:
        chunk_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,))
        ]
        for chunk_id in chunk_ids:
            conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        conn.commit()
        return cur.rowcount > 0


def list_sources(topic: str | None = None, limit: int = 50, min_score: float = 0.0) -> list[dict]:
    # min_score remains accepted for MCP compatibility but has no effect.
    del min_score
    limit = max(1, min(limit, 500))
    with connect() as conn:
        if topic:
            rows = conn.execute(
                """SELECT s.id, s.url, s.canonical_url, s.title, s.domain,
                          st.topic, s.fetched_at, s.published_at,
                          s.published_at_source, s.content_hash,
                          s.quality_status, s.quality_reason, s.quality_version,
                          length(s.markdown) AS chars
                   FROM sources s JOIN source_topics st ON st.source_id = s.id
                   WHERE st.topic = ? AND s.active = 1
                   ORDER BY s.fetched_at DESC LIMIT ?""",
                (topic, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, url, canonical_url, title, domain, topic, fetched_at,
                          published_at, published_at_source, content_hash,
                          quality_status, quality_reason,
                          quality_version,
                          length(markdown) AS chars
                   FROM sources WHERE active = 1
                   ORDER BY fetched_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def fetch_all_chunks(topic: str | None = None) -> list[sqlite3.Row]:
    with connect() as conn:
        if topic:
            return conn.execute(
                """SELECT c.* FROM chunks c
                   JOIN sources s ON s.id = c.source_id
                   LEFT JOIN source_topics st ON st.source_id = s.id AND st.topic = ?
                   WHERE s.active = 1 AND s.quality_status != 'quarantined'
                     AND (st.topic = ? OR (st.topic IS NULL AND c.topic = ?))""",
                (topic, topic, topic),
            ).fetchall()
        return conn.execute(
            """SELECT c.* FROM chunks c JOIN sources s ON s.id = c.source_id
               WHERE s.active = 1 AND s.quality_status != 'quarantined'"""
        ).fetchall()


def build_fts_query(query: str) -> str:
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)))
    terms = [term for term in terms if len(term) > 1]
    informative = [term for term in terms if term not in FTS_STOPWORDS]
    selected = informative or terms
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in selected)


def keyword_search(query: str, top_k: int = 50, topic: str | None = None) -> dict[int, float]:
    q = build_fts_query(query)
    if not q:
        return {}
    try:
        with connect() as conn:
            if topic:
                rows = conn.execute(
                    """SELECT chunks_fts.chunk_id,
                              bm25(chunks_fts, 0.0, 2.0, 1.0, 0.0, 0.0) AS rank
                       FROM chunks_fts
                       JOIN chunks c ON c.id = chunks_fts.chunk_id
                       JOIN sources s ON s.id = c.source_id
                       LEFT JOIN source_topics st ON st.source_id = s.id AND st.topic = ?
                       WHERE chunks_fts MATCH ? AND s.active = 1
                         AND s.quality_status != 'quarantined'
                         AND (st.topic = ? OR (st.topic IS NULL AND c.topic = ?))
                       ORDER BY rank LIMIT ?""",
                    (topic, q, topic, topic, top_k),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT chunks_fts.chunk_id,
                              bm25(chunks_fts, 0.0, 2.0, 1.0, 0.0, 0.0) AS rank
                       FROM chunks_fts
                       JOIN chunks c ON c.id = chunks_fts.chunk_id
                       JOIN sources s ON s.id = c.source_id
                       WHERE chunks_fts MATCH ? AND s.active = 1
                         AND s.quality_status != 'quarantined'
                       ORDER BY rank LIMIT ?""",
                    (q, top_k),
                ).fetchall()
    except sqlite3.OperationalError as exc:
        message = str(exc).casefold()
        if "fts5" in message or "syntax" in message or "unterminated" in message:
            raise FtsQueryError(
                "The keyword query could not be executed safely.",
                resolution="Simplify the query and retry.",
            ) from exc
        raise RuntimeError("SQLite keyword retrieval failed.") from exc
    # SQLite FTS5 assigns better BM25 matches numerically lower values.
    # Negating preserves that ordering for callers that treat larger as better.
    return {int(row["chunk_id"]): -float(row["rank"]) for row in rows}


def get_chunks_by_ids(ids) -> dict[int, sqlite3.Row]:
    ids = list(dict.fromkeys(int(value) for value in ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM chunks WHERE id IN ({placeholders})", ids).fetchall()
    return {int(row["id"]): row for row in rows}


def reset_topic(topic: str) -> int:
    with connect() as conn:
        source_ids = [
            int(row["source_id"])
            for row in conn.execute("SELECT source_id FROM source_topics WHERE topic = ?", (topic,))
        ]
        conn.execute("DELETE FROM source_topics WHERE topic = ?", (topic,))
        orphan_ids = [
            source_id
            for source_id in source_ids
            if conn.execute(
                "SELECT 1 FROM source_topics WHERE source_id = ? LIMIT 1", (source_id,)
            ).fetchone()
            is None
        ]
        conn.commit()
    for source_id in orphan_ids:
        delete_source(source_id)
    return len(source_ids)


def vacuum_db() -> None:
    conn = connect()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
