from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .config import settings
from .doctor import run_doctor
from .integration_contract import answer_agent_contract
from .searxng_admin import SearxngAdminError, configure_engines, engine_rows, fetch_configuration
from .store import audit_source_quality

DEFAULT_SEARXNG_SETTINGS = settings.searxng_config_path
CRAWL4AI_ATTRIBUTION = (
    "This product includes software developed by UncleCode (https://x.com/unclecode) "
    "as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai)."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-websearch",
        description="Local-first web research for llama.cpp",
        epilog=CRAWL4AI_ATTRIBUTION,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="start the Streamable HTTP MCP server")
    serve.add_argument(
        "--toolset",
        choices=("answer", "diagnostic", "admin"),
        help="override the minimal answer-only MCP toolset for this process",
    )

    doctor = subcommands.add_parser("doctor", help="check local service readiness")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.add_argument(
        "--search-probe", action="store_true", help="run one real SearXNG upstream search"
    )

    contract = subcommands.add_parser(
        "agent-contract", help="print the answer-agent integration contract"
    )
    contract.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    searxng = subcommands.add_parser(
        "searxng", help="inspect or configure the local SearXNG service"
    )
    searxng_commands = searxng.add_subparsers(dest="searxng_command", required=True)
    status = searxng_commands.add_parser("status", help="check the configured SearXNG endpoint")
    status.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    engines = searxng_commands.add_parser("engines", help="inspect or configure SearXNG engines")
    engine_commands = engines.add_subparsers(dest="engine_command", required=True)
    listing = engine_commands.add_parser("list", help="list engines reported by SearXNG")
    listing.add_argument("--all", action="store_true", help="include disabled engines")
    listing.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    for action in ("enable", "disable"):
        change = engine_commands.add_parser(action, help=f"{action} one or more SearXNG engines")
        change.add_argument(
            "names", nargs="+", help="engine names as reported by `engines list --all`"
        )
        change.add_argument(
            "--restart", action="store_true", help="restart the managed Podman container"
        )
        change.add_argument(
            "--settings", type=Path, default=DEFAULT_SEARXNG_SETTINGS, help=argparse.SUPPRESS
        )

    cache = subcommands.add_parser("cache", help="inspect cached evidence quality")
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    audit = cache_commands.add_parser("audit", help="assess active cached sources")
    audit.add_argument(
        "--apply", action="store_true", help="quarantine unusable sources without deleting them"
    )
    audit.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def _print_doctor(payload: dict[str, Any]) -> None:
    for name, check in payload["checks"].items():
        state = "OK" if check["ok"] else "FAIL"
        print(f"{state:4} {name}: {check['message']}")


async def _run(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        payload = await run_doctor(args.search_probe)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_doctor(payload)
        return 0 if payload["ok"] else 1

    if args.command == "agent-contract":
        payload = answer_agent_contract()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload["instructions"])
        return 0

    if args.command == "cache":
        payload = audit_source_quality(apply=args.apply)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            action = "applied" if args.apply else "dry-run"
            print(
                f"{action}: assessed={payload['sources_assessed']} "
                f"usable={payload['usable']} quarantined={payload['quarantined']} "
                f"changed={payload['changed']}"
            )
        return 0

    if args.searxng_command == "status":
        configuration = await fetch_configuration()
        rows = engine_rows(configuration, include_disabled=True)
        payload = {
            "ok": True,
            "endpoint": settings.searxng_url,
            "engines": len(rows),
            "enabled_engines": sum(1 for row in rows if row["enabled"]),
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                f"OK SearXNG: {payload['endpoint']} "
                f"({payload['enabled_engines']}/{payload['engines']} engines enabled)"
            )
        return 0

    if args.engine_command == "list":
        rows = engine_rows(await fetch_configuration(), include_disabled=args.all)
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            for row in rows:
                state = "enabled" if row["enabled"] else "disabled"
                categories = ",".join(row["categories"])
                print(f"{row['name']}\t{state}\t{row['shortcut']}\t{categories}")
        return 0

    changed = await configure_engines(
        args.settings.resolve(),
        args.names,
        enabled=args.engine_command == "enable",
        restart=args.restart,
    )
    state = "enabled" if args.engine_command == "enable" else "disabled"
    print(f"{state}: " + ", ".join(changed))
    if not args.restart:
        print("Restart SearXNG to apply the change.")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        from .server import main as serve

        serve(toolset=args.toolset)
        return
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except SearxngAdminError as exc:
        print(f"error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
