import ast
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ai_websearch"
EXPECTED_MCP_SIGNATURES = {
    "web_search": ["query", "max_results", "freshness", "language"],
    "scrape_url": ["url"],
    "ingest_url": ["url", "topic"],
    "research": [
        "query",
        "topic",
        "freshness",
        "language",
        "context_mode",
        "context_budget_tokens",
        "max_page_attempts",
        "max_sources",
        "max_chunks",
        "mode",
    ],
    "retrieve_context": [
        "query",
        "topic",
        "context_mode",
        "context_budget_tokens",
        "top_k",
        "max_sources",
        "max_chunks",
    ],
    "score_sources": ["urls"],
    "list_sources": ["topic", "limit", "min_score"],
    "delete_source": ["source_id"],
}


def test_mcp_tool_signatures_match_the_supported_interface() -> None:
    tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
    discovered = {}
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in EXPECTED_MCP_SIGNATURES
        ):
            discovered[node.name] = [argument.arg for argument in node.args.args]
    assert discovered == EXPECTED_MCP_SIGNATURES


def test_numeric_mcp_limits_default_to_none() -> None:
    tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for function_name, limit_names in {
        "research": {"max_page_attempts", "max_sources", "max_chunks"},
        "retrieve_context": {"top_k", "max_sources", "max_chunks"},
    }.items():
        function = functions[function_name]
        arguments = function.args.args
        defaults = [None] * (len(arguments) - len(function.args.defaults)) + list(
            function.args.defaults
        )
        defaults_by_name = {
            argument.arg: default for argument, default in zip(arguments, defaults, strict=True)
        }
        for name in limit_names:
            default = defaults_by_name[name]
            assert isinstance(default, ast.Constant)
            assert default.value is None


def test_generated_mcp_schema_exposes_only_the_new_research_controls() -> None:
    from ai_websearch.server import create_mcp

    schemas = {
        tool.name: tool.parameters
        for tool in asyncio.run(create_mcp("admin").list_tools())
        if tool.name in {"research", "retrieve_context"}
    }
    research_properties = schemas["research"]["properties"]
    context_properties = schemas["retrieve_context"]["properties"]

    assert "depth" not in research_properties
    assert "allow_manual_captcha" not in research_properties
    assert "depth" not in context_properties
    assert research_properties["mode"]["enum"] == ["rapid", "deep", "auto"]
    for name in ("max_page_attempts", "max_sources", "max_chunks"):
        assert research_properties[name]["default"] is None
        assert research_properties[name]["anyOf"][0]["minimum"] == 1
    for name in ("top_k", "max_sources", "max_chunks"):
        assert context_properties[name]["default"] is None
        assert context_properties[name]["anyOf"][0]["minimum"] == 1


def test_default_and_opt_in_mcp_toolsets_are_minimal_and_stable() -> None:
    from ai_websearch.server import create_mcp

    names = {
        toolset: {tool.name for tool in asyncio.run(create_mcp(toolset).list_tools())}
        for toolset in ("answer", "diagnostic", "admin")
    }
    assert names["answer"] == {"research"}
    assert names["diagnostic"] == {
        "research",
        "web_search",
        "scrape_url",
        "retrieve_context",
        "score_sources",
        "list_sources",
    }
    assert names["admin"] == set(EXPECTED_MCP_SIGNATURES)


def test_server_import_does_not_configure_global_logging() -> None:
    tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
    top_level_calls = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert not any(
        isinstance(call.func, ast.Name) and call.func.id == "setup_logging"
        for call in top_level_calls
    )


def test_llama_service_calls_never_follow_redirects() -> None:
    source = (SOURCE / "llama_client.py").read_text(encoding="utf-8")
    assert "follow_redirects=True" not in source
    assert source.count("follow_redirects=False") == 2


def test_production_does_not_import_benchmark_harness() -> None:
    for path in SOURCE.glob("*.py"):
        assert "benchmarks" not in path.read_text(encoding="utf-8")


def test_production_has_no_interactive_captcha_handoff() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.glob("*.py"))
    for forbidden in (
        "allow_manual_captcha",
        "manual_action_available",
        "manual_captcha_timeout_seconds",
        "manual_captcha_handoff",
        "_wait_for_manual_captcha",
        "headless=not interactive",
    ):
        assert forbidden not in source


def test_security_boilerplate_is_not_stored_or_embedded() -> None:
    source = (SOURCE / "orchestrator.py").read_text(encoding="utf-8")
    assert "wrap_untrusted" not in source
    assert "UNTRUSTED WEB CONTENT" not in source


def test_stage2_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage2" not in path.read_text(encoding="utf-8").lower()


def test_stage3_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage3" not in path.read_text(encoding="utf-8").lower()


def test_stage4_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage4" not in path.read_text(encoding="utf-8").lower()


def test_stage5_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage5" not in path.read_text(encoding="utf-8").lower()


def test_stage6_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage6" not in path.read_text(encoding="utf-8").lower()


def test_stage7_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage7" not in path.read_text(encoding="utf-8").lower()


def test_stage8_is_not_referenced_by_production() -> None:
    for path in SOURCE.glob("*.py"):
        assert "stage8" not in path.read_text(encoding="utf-8").lower()
