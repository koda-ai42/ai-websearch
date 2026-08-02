from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import httpx
import yaml

from .config import settings


class SearxngAdminError(RuntimeError):
    pass


async def fetch_configuration() -> dict[str, Any]:
    endpoint = settings.searxng_url.rstrip("/") + "/config"
    try:
        async with httpx.AsyncClient(
            timeout=settings.searxng_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise SearxngAdminError("SearXNG /config is unavailable or invalid.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("engines"), list):
        raise SearxngAdminError("SearXNG /config did not return an engine list.")
    return payload


def engine_rows(payload: dict[str, Any], include_disabled: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in payload.get("engines", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        enabled = bool(raw.get("enabled"))
        if not include_disabled and not enabled:
            continue
        categories = raw.get("categories")
        rows.append(
            {
                "name": raw["name"],
                "enabled": enabled,
                "shortcut": str(raw.get("shortcut") or ""),
                "categories": [str(item) for item in categories]
                if isinstance(categories, list)
                else [],
            }
        )
    return sorted(rows, key=lambda row: row["name"].casefold())


def update_engine_overrides(
    config_path: Path,
    names: list[str],
    *,
    enabled: bool,
    available_names: set[str] | None = None,
) -> list[str]:
    normalized = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    if not normalized:
        raise SearxngAdminError("At least one engine name is required.")
    if available_names is not None:
        lookup = {name.casefold(): name for name in available_names}
        unknown = [name for name in normalized if name.casefold() not in lookup]
        if unknown:
            raise SearxngAdminError("Unknown SearXNG engine: " + ", ".join(unknown))
        normalized = [lookup[name.casefold()] for name in normalized]

    try:
        raw = (
            yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        )
    except (OSError, yaml.YAMLError) as exc:
        raise SearxngAdminError("Could not read the SearXNG settings file.") from exc
    payload = raw or {}
    if not isinstance(payload, dict):
        raise SearxngAdminError("SearXNG settings must contain a YAML mapping.")
    configured = payload.get("engines", [])
    if configured is None:
        configured = []
    if not isinstance(configured, list):
        raise SearxngAdminError("The SearXNG engines setting must contain a list.")

    by_name: dict[str, dict[str, Any]] = {}
    passthrough: list[Any] = []
    for item in configured:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            by_name[item["name"].casefold()] = dict(item)
        else:
            passthrough.append(item)
    for name in normalized:
        entry = by_name.get(name.casefold(), {"name": name})
        entry["disabled"] = not enabled
        by_name[name.casefold()] = entry
    payload["engines"] = passthrough + sorted(
        by_name.values(), key=lambda item: str(item["name"]).casefold()
    )

    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    # Parse the final document before replacing the active configuration.
    yaml.safe_load(rendered)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(config_path.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(config_path)
    return normalized


def restart_searxng(container_name: str = "ai-websearch-searxng") -> None:
    try:
        completed = subprocess.run(
            ["podman", "restart", container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SearxngAdminError("Could not restart the SearXNG Podman container.") from exc
    if completed.returncode != 0:
        raise SearxngAdminError("The SearXNG Podman container restart failed.")


async def configure_engines(
    config_path: Path,
    names: list[str],
    *,
    enabled: bool,
    restart: bool,
) -> list[str]:
    configuration = await fetch_configuration()
    available = {row["name"] for row in engine_rows(configuration, include_disabled=True)}
    changed = await asyncio.to_thread(
        update_engine_overrides,
        config_path,
        names,
        enabled=enabled,
        available_names=available,
    )
    if restart:
        await asyncio.to_thread(restart_searxng)
    return changed
