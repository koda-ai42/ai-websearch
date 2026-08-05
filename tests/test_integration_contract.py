from ai_websearch.integration_contract import (
    ANSWER_AGENT_INSTRUCTIONS,
    answer_agent_contract,
    validate_answer_response,
    validate_answer_tool_trace,
    validate_answer_transaction,
)
from ai_websearch.server import mcp


def test_answer_agent_contract_allows_only_one_research_call() -> None:
    contract = answer_agent_contract()
    assert contract["allowed_tools"] == ["research"]
    assert contract["max_research_calls_per_question"] == 3
    assert "required_research_calls" not in contract
    assert "query" not in contract
    assert contract["scope"] == {"allow_unrequested_related_claims": False}
    assert contract["validation"] == {
        "required": True,
        "function": "ai_websearch.integration_contract.validate_answer_transaction",
    }
    assert validate_answer_tool_trace(["research"])["compliant"]
    assert not validate_answer_tool_trace(["research", "web_search"])["compliant"]
    assert validate_answer_tool_trace(["research", "research"])["compliant"]
    assert validate_answer_tool_trace(["research", "research", "research"])["compliant"]
    assert validate_answer_tool_trace([])["compliant"]  # 0 calls is allowed by validator


def test_mcp_server_publishes_answer_agent_contract() -> None:
    assert mcp.instructions == ANSWER_AGENT_INSTRUCTIONS


def test_answer_response_requires_provided_citation_and_fetched_date() -> None:
    sources = [
        {
            "citation": "[Example](https://example.test/article)",
            "fetched_at": "2026-08-02T00:00:00Z",
        }
    ]
    compliant = validate_answer_response(
        "Supported by [Example](https://example.test/article), fetched 2026-08-02T00:00:00Z.",
        sources,
        answerable=True,
    )
    assert compliant["compliant"]
    assert not validate_answer_response("Unsupported answer", sources, answerable=True)["compliant"]


def test_insufficient_evidence_does_not_require_citations() -> None:
    assert validate_answer_response(
        "The available evidence is insufficient.",
        [],
        answerable=False,
    )["compliant"]


def test_answer_transaction_requires_original_query_one_call_and_supported_response() -> None:
    query = "What changed in the latest stable release?"
    sources = [
        {
            "citation": "[Release notes](https://example.test/releases/latest)",
            "fetched_at": "2026-08-02T16:38:50+00:00",
        }
    ]
    valid = validate_answer_transaction(
        original_query=query,
        research_queries=[query],
        tool_names=["research"],
        answer=(
            "The release improves retrieval. "
            "[Release notes](https://example.test/releases/latest) "
            "fetched 2026-08-02T16:38:50+00:00."
        ),
        sources=sources,
        answerable=True,
    )
    assert valid["compliant"]

    invalid = validate_answer_transaction(
        original_query=query,
        research_queries=["latest release notes", "current stable version"],
        tool_names=["research", "research"],
        answer="The release improves retrieval.",
        sources=sources,
        answerable=True,
    )
    assert invalid["violations"] == [
        "missing_required_citation_or_fetched_date",
    ]
