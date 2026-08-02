from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from ai_websearch import context_packer, llama_client, search, store
from ai_websearch.config import settings
from ai_websearch.errors import ContextBudgetError


class _FakeAsyncClient:
    def __init__(self, counters: dict[str, int]) -> None:
        self.counters = counters

    async def __aenter__(self):
        self.counters["entered"] += 1
        return self

    async def __aexit__(self, *_args):
        self.counters["closed"] += 1


@pytest.mark.parametrize(
    ("module", "scope_name"),
    [
        (search, "searxng_client_scope"),
        (llama_client, "llama_client_scope"),
    ],
)
def test_nested_http_scopes_reuse_and_close_one_owned_client(
    monkeypatch,
    module,
    scope_name: str,
) -> None:
    counters = {"created": 0, "entered": 0, "closed": 0}

    def factory(**_kwargs):
        counters["created"] += 1
        return _FakeAsyncClient(counters)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)

    async def exercise() -> None:
        scope = getattr(module, scope_name)
        async with scope() as first:
            async with scope() as second:
                assert first is second

    asyncio.run(exercise())
    assert counters == {"created": 1, "entered": 1, "closed": 1}


def test_scoped_service_clients_clear_response_cookies() -> None:
    assert "client.cookies.clear()" in inspect.getsource(search.web_search)
    assert "client.cookies.clear()" in inspect.getsource(llama_client.count_tokens)


def test_exact_token_count_stops_at_the_validated_fixed_point(monkeypatch) -> None:
    calls = 0

    async def exact_count(serialized: str) -> int:
        nonlocal calls
        calls += 1
        embedded = json.loads(serialized)["budget"]["packed_result_tokens"]
        return 100 + len(str(embedded))

    monkeypatch.setattr(context_packer.runtime, "count", exact_count)
    payload = {"budget": {"packed_result_tokens": 0}}
    count, validated = asyncio.run(context_packer._stable_count(payload))
    assert count == 103
    assert validated["budget"]["packed_result_tokens"] == 103
    assert calls == 3


def test_exact_token_count_fails_if_the_result_never_stabilizes(monkeypatch) -> None:
    async def unstable(serialized: str) -> int:
        embedded = json.loads(serialized)["budget"]["packed_result_tokens"]
        return int(embedded) + 1

    monkeypatch.setattr(context_packer.runtime, "count", unstable)
    with pytest.raises(ContextBudgetError) as captured:
        asyncio.run(context_packer._stable_count({"budget": {"packed_result_tokens": 0}}))
    assert captured.value.details == {"validation_attempts": 4}


def test_database_schema_initializes_once_and_each_connection_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    original_path = settings.database_path
    original_timeout = settings.database_busy_timeout_seconds
    settings.database_path = str(tmp_path / "lifecycle.sqlite3")
    settings.database_busy_timeout_seconds = 0.25
    calls = 0
    migrate = store._migrate_schema

    def counted_migration(connection):
        nonlocal calls
        calls += 1
        return migrate(connection)

    monkeypatch.setattr(store, "_migrate_schema", counted_migration)
    store.clear_database_initialization_cache()
    try:
        for _ in range(2):
            with store.connect() as connection:
                assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 250
        assert calls == 1
    finally:
        settings.database_path = original_path
        settings.database_busy_timeout_seconds = original_timeout
        store.clear_database_initialization_cache()
