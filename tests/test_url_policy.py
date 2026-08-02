from pathlib import Path

from ai_websearch.security import safe_model_label
from ai_websearch.url_policy import check_url


def test_url_policy_rejects_non_http_and_credentials(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yml"
    policy.write_text("blocked_domains: []\n", encoding="utf-8")
    assert not check_url("file:///etc/passwd", policy_path=policy).allowed
    assert not check_url("https://user:password@example.test", policy_path=policy).allowed
    assert not check_url("https://example.test/data?api_key=secret", policy_path=policy).allowed
    assert not check_url("http://127.0.0.1/admin", policy_path=policy).allowed
    assert not check_url("http://[::1]/admin", policy_path=policy).allowed
    assert not check_url("http://metadata.local/latest", policy_path=policy).allowed
    assert check_url("https://example.test/article", policy_path=policy).allowed


def test_url_policy_blocking_does_not_score_or_rank_domains(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yml"
    policy.write_text("blocked_domains:\n  - blocked.test\n", encoding="utf-8")
    result = check_url("https://sub.blocked.test/article", policy_path=policy)
    assert not result.allowed
    assert not hasattr(result, "score")


def test_absolute_model_paths_are_reduced_to_safe_labels() -> None:
    assert safe_model_label("/private/models/secret-model") == "secret-model"
    assert (
        safe_model_label("sentence-transformers/public-model")
        == "sentence-transformers/public-model"
    )
