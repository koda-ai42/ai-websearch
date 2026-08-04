from __future__ import annotations

from typing import Any, Iterable

ANSWER_AGENT_ALLOWED_TOOLS = ("research",)
LOW_LEVEL_DIAGNOSTIC_TOOLS = ("web_search", "scrape_url", "ingest_url")
ANSWER_AGENT_INSTRUCTIONS = (
    "For answer-generation tasks, call research exactly once with the original user question "
    "unchanged. Do not compose web_search, scrape_url, or ingest_url calls. Do not add related "
    "information or claims the user did not request. If research "
    "reports answerability.answerable=false, state that the available evidence is insufficient. "
    "Otherwise use only packed evidence and include a provided Markdown citation and its exact "
    "fetched date."
    "If the question is time-related, do not infer the relevant items from ordering alone but use timestamps and time cues"
)


def answer_agent_contract() -> dict[str, Any]:
    return {
        "allowed_tools": list(ANSWER_AGENT_ALLOWED_TOOLS),
        "required_research_calls": 1,
        "query": {"require_original_unchanged": True},
        "scope": {"allow_unrequested_related_claims": False},
        "on_insufficient_evidence": "state_uncertainty",
        "citations": {
            "require_provided_markdown_link": True,
            "require_fetched_date": True,
        },
        "validation": {
            "required": True,
            "function": "ai_websearch.integration_contract.validate_answer_transaction",
        },
        "instructions": ANSWER_AGENT_INSTRUCTIONS,
    }


def validate_answer_tool_trace(tool_names: Iterable[str]) -> dict[str, Any]:
    observed = list(tool_names)
    disallowed = [name for name in observed if name not in ANSWER_AGENT_ALLOWED_TOOLS]
    research_calls = observed.count("research")
    return {
        "compliant": research_calls == 1 and not disallowed and len(observed) == 1,
        "research_calls": research_calls,
        "disallowed_tools": disallowed,
    }


def validate_answer_response(
    answer: str,
    sources: list[dict[str, Any]],
    *,
    answerable: bool,
) -> dict[str, Any]:
    if not answerable:
        return {
            "compliant": True,
            "answerable": False,
            "citations_found": 0,
            "fetched_dates_found": 0,
        }
    citations = [
        str(source.get("citation"))
        for source in sources
        if isinstance(source.get("citation"), str) and source.get("citation")
    ]
    fetched_dates = [
        str(source.get("fetched_at"))
        for source in sources
        if isinstance(source.get("fetched_at"), str) and source.get("fetched_at")
    ]
    citations_found = sum(citation in answer for citation in citations)
    fetched_dates_found = sum(fetched_at in answer for fetched_at in fetched_dates)
    return {
        "compliant": citations_found > 0 and fetched_dates_found > 0,
        "answerable": True,
        "citations_found": citations_found,
        "fetched_dates_found": fetched_dates_found,
    }


def validate_answer_transaction(
    *,
    original_query: str,
    research_queries: Iterable[str],
    tool_names: Iterable[str],
    answer: str,
    sources: list[dict[str, Any]],
    answerable: bool,
) -> dict[str, Any]:
    """Validate the enforceable parts of one answer-agent transaction."""

    observed_queries = list(research_queries)
    query_preserved = observed_queries == [original_query]
    trace = validate_answer_tool_trace(tool_names)
    response = validate_answer_response(answer, sources, answerable=answerable)
    violations = []
    if not query_preserved:
        violations.append("original_query_not_preserved")
    if not trace["compliant"]:
        violations.append("invalid_tool_trace")
    if not response["compliant"]:
        violations.append("missing_required_citation_or_fetched_date")
    return {
        "compliant": not violations,
        "query_preserved": query_preserved,
        "tool_trace": trace,
        "response": response,
        "violations": violations,
    }
