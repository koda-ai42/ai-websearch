import os
from pathlib import Path

from benchmarks.isolation import isolated_environment


def test_isolated_environment_uses_disposable_database_path() -> None:
    original = os.environ.get("AI_WEBSEARCH_DATABASE_PATH")
    with isolated_environment() as directory:
        database = Path(os.environ["AI_WEBSEARCH_DATABASE_PATH"])
        assert database.parent == directory
        assert database.name == "benchmark.sqlite3"
        assert not database.exists()
    assert not directory.exists()
    assert os.environ.get("AI_WEBSEARCH_DATABASE_PATH") == original


def test_explicit_artifact_root_does_not_delete_user_directory(tmp_path) -> None:
    with isolated_environment(tmp_path) as directory:
        marker = directory / "marker.txt"
        marker.write_text("benchmark", encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == "benchmark"
