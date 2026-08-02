from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ai_websearch import doctor


def test_doctor_checks_live_searxng_configuration_shape(monkeypatch) -> None:
    async def configuration():
        return {
            "engines": [
                {"name": "one", "enabled": True},
                {"name": "two", "enabled": False},
            ]
        }

    monkeypatch.setattr(doctor, "fetch_configuration", configuration)
    result = asyncio.run(doctor.check_searxng())
    assert result["ok"]
    assert result["enabled_engines"] == 1
    assert result["available_engines"] == 2


def test_doctor_requires_props_discovery_and_tokenize(monkeypatch) -> None:
    server = SimpleNamespace(
        detection_mode="manual",
        context_tokens=32768,
    )

    async def detected(*_args, **_kwargs):
        return server

    async def tokenized(selected, text):
        assert selected is server and text == "doctor"
        return 1

    monkeypatch.setattr(doctor.runtime, "get", detected)
    monkeypatch.setattr(doctor, "count_tokens", tokenized)
    result = asyncio.run(doctor.check_llama_cpp())
    assert result["ok"]
    assert result["context_tokens"] == 32768
    assert result["tokenize_tokens"] == 1
