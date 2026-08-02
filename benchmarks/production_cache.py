from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from ai_websearch import store
from ai_websearch.config import settings


def run_production_cache_benchmark(_path: Path | None = None) -> dict:
    original = settings.database_path
    try:
        with tempfile.TemporaryDirectory(prefix="ai-websearch-cache-benchmark-") as directory:
            settings.database_path = str(Path(directory) / "cache.sqlite3")
            stored = store.store_document(
                "https://cache-benchmark.test/article",
                "https://cache-benchmark.test/article",
                "Cached evidence",
                "Previously fetched useful public evidence.",
                "2020-01-01T00:00:00+00:00",
                None,
                "old-topic",
                ["Previously fetched useful public evidence."],
                np.asarray([[1.0, 0.0]], dtype=np.float32),
            )
            fallback = store.find_stale_source(
                "https://cache-benchmark.test/article",
                "new-topic",
                refresh_outcome="captcha",
            )
            old_rows = store.fetch_all_chunks("old-topic")
            new_rows = store.fetch_all_chunks("new-topic")
            with store.connect() as connection:
                active_versions = int(
                    connection.execute("SELECT COUNT(*) FROM sources WHERE active = 1").fetchone()[
                        0
                    ]
                )
    finally:
        settings.database_path = original

    return {
        "schema_version": "1.0",
        "run_mode": "offline_production_cache",
        "accuracy": {
            "stale_fallback_retrievable": bool(fallback and new_rows),
            "old_topic_still_retrievable": bool(old_rows),
            "refresh_outcome_recorded": bool(fallback and fallback.refresh_outcome == "captcha"),
        },
        "reliability": {
            "good_source_preserved": bool(fallback and fallback.source_id == stored.source_id),
            "active_versions": active_versions,
            "cache_status": fallback.cache_status if fallback else None,
            "network_access": False,
            "model_inference": False,
        },
        "latency": {
            "measured": False,
            "database_operations": 5,
        },
        "limitations": [
            "Uses a disposable SQLite database and a fixed vector without model inference.",
            "Does not execute a browser refresh; the terminal refresh outcome is injected.",
        ],
    }
