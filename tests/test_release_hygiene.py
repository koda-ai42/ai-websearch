from __future__ import annotations

from scripts.check_release import unsafe_path


def test_release_path_policy_allows_public_configuration() -> None:
    assert not unsafe_path(".env.example")
    assert not unsafe_path("docs/example.json")
    assert not unsafe_path("src/ai_websearch/store.py")


def test_release_path_policy_rejects_runtime_and_private_artifacts() -> None:
    for path in (
        ".env",
        ".env.production",
        "data/evidence.sqlite3",
        "logs/research.log",
        "browser-profile/Default/Cookies",
        "captured-pages/result.html",
        "models/reranker.safetensors",
        "src/ai_websearch/__pycache__/store.cpython-312.pyc",
    ):
        assert unsafe_path(path), path
