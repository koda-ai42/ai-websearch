from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def isolated_environment(root: Path | None = None) -> Iterator[Path]:
    """Provide a disposable DB/artifact directory without touching production paths."""

    old_db = os.environ.get("AI_WEBSEARCH_DATABASE_PATH")
    if root is None:
        manager = tempfile.TemporaryDirectory(prefix="ai-websearch-benchmark-")
        directory = Path(manager.__enter__())
    else:
        manager = None
        directory = root.resolve()
        directory.mkdir(parents=True, exist_ok=True)
    os.environ["AI_WEBSEARCH_DATABASE_PATH"] = str(directory / "benchmark.sqlite3")
    try:
        yield directory
    finally:
        if old_db is None:
            os.environ.pop("AI_WEBSEARCH_DATABASE_PATH", None)
        else:
            os.environ["AI_WEBSEARCH_DATABASE_PATH"] = old_db
        if manager is not None:
            manager.__exit__(None, None, None)
