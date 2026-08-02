import json
from pathlib import Path

QUEUE = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "fixtures"
    / "live_v1"
    / "judgment_queue.json"
)


def test_live_judgment_queue_is_broad_and_explicitly_unscored() -> None:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert payload["status"] == "human_review_required"
    assert 30 <= len(cases) <= 50
    assert len({case["id"] for case in cases}) == len(cases)
    assert {
        "exact_factual",
        "technical_documentation",
        "current_events",
        "comparative",
        "multi_hop",
        "ambiguous",
        "no_answer",
        "conflicting_sources",
        "access_outcome",
        "adversarial",
    } <= {case["category"] for case in cases}
