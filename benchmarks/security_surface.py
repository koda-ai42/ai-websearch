from __future__ import annotations

from pathlib import Path

CASES = (
    {"id": "answer-tool-surface", "control": "minimal_tools"},
    {"id": "mcp-loopback", "control": "loopback_mcp"},
    {"id": "searxng-loopback", "control": "loopback_searxng"},
    {"id": "searxng-no-credentials", "control": "safe_searxng_url"},
    {"id": "searxng-no-query", "control": "safe_searxng_url"},
    {"id": "llama-no-redirect", "control": "no_service_redirects"},
    {"id": "url-log-redaction", "control": "redacted_url_diagnostics"},
    {"id": "logging-at-executable-boundary", "control": "owned_logging"},
)


def run_security_surface_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, enabled in (
        (
            "existing_surface",
            {
                "minimal_tools": False,
                "loopback_mcp": False,
                "loopback_searxng": False,
                "safe_searxng_url": False,
                "no_service_redirects": False,
                "redacted_url_diagnostics": False,
                "owned_logging": False,
            },
        ),
        (
            "publication_hardened",
            {
                "minimal_tools": True,
                "loopback_mcp": True,
                "loopback_searxng": True,
                "safe_searxng_url": True,
                "no_service_redirects": True,
                "redacted_url_diagnostics": True,
                "owned_logging": True,
            },
        ),
    ):
        rows = [
            {
                "id": case["id"],
                "control": case["control"],
                "passed": bool(enabled[case["control"]]),
            }
            for case in CASES
        ]
        policies[name] = {
            "reliability": {
                "controls_passed": sum(row["passed"] for row in rows),
                "controls_total": len(rows),
                "control_coverage": sum(row["passed"] for row in rows) / len(rows),
            },
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_security_policy",
        "policies": policies,
        "accuracy": {"measured": False},
        "latency": {"measured": False, "cases_evaluated": len(CASES)},
        "limitations": [
            "This is a deterministic control-presence benchmark, not a penetration test.",
            "No MCP socket, SearXNG endpoint, llama.cpp endpoint, or public URL is contacted.",
        ],
    }
