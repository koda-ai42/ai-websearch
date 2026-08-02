from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .llama_client import count_tokens
from .llama_discovery import runtime
from .searxng_admin import engine_rows, fetch_configuration


def _result(ok: bool, message: str, **details: Any) -> dict[str, Any]:
    return {"ok": ok, "message": message, **details}


async def check_searxng(search_probe: bool = False) -> dict[str, Any]:
    try:
        payload = await fetch_configuration()
        rows = engine_rows(payload, include_disabled=True)
        enabled = [row for row in rows if row["enabled"]]
        result = _result(
            True,
            "SearXNG configuration endpoint is live.",
            enabled_engines=len(enabled),
            available_engines=len(rows),
        )
        if search_probe:
            endpoint = settings.searxng_url.rstrip("/") + "/search"
            async with httpx.AsyncClient(
                timeout=settings.searxng_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    endpoint,
                    params={"q": "SearXNG", "format": "json", "safesearch": 1},
                )
                response.raise_for_status()
                search_payload = response.json()
            result["search_probe"] = isinstance(search_payload, dict) and isinstance(
                search_payload.get("results"), list
            )
        return result
    except Exception:
        return _result(False, "SearXNG is unavailable or returned an invalid response.")


async def check_llama_cpp() -> dict[str, Any]:
    try:
        server = await runtime.get(force=True)
        token_count = await count_tokens(server, "doctor")
        return _result(
            True,
            "llama.cpp /props and /tokenize are live.",
            detection_mode=server.detection_mode,
            context_tokens=server.context_tokens,
            tokenize_tokens=token_count,
        )
    except Exception as exc:
        code = getattr(exc, "code", "llama_cpp_unavailable")
        return _result(False, "llama.cpp discovery or verification failed.", error=code)


def check_database() -> dict[str, Any]:
    path = Path(settings.database_path).expanduser().resolve()
    if not path.exists():
        return _result(True, "Database has not been created yet.", present=False)
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            fts_chunks = int(connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
        ok = quick_check == "ok" and chunks == fts_chunks
        return _result(
            ok,
            "Database and FTS row counts are consistent."
            if ok
            else "Database or FTS integrity check failed.",
            present=True,
            quick_check=quick_check,
            chunks=chunks,
            fts_chunks=fts_chunks,
        )
    except (OSError, sqlite3.Error):
        return _result(False, "Database could not be inspected safely.", present=True)


async def run_doctor(search_probe: bool = False) -> dict[str, Any]:
    searxng, llama_cpp = await asyncio.gather(
        check_searxng(search_probe),
        check_llama_cpp(),
    )
    checks = {
        "searxng": searxng,
        "llama_cpp": llama_cpp,
        "database": check_database(),
    }
    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}
