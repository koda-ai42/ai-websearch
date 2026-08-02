from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from ai_websearch import cli
from ai_websearch.searxng_admin import engine_rows, update_engine_overrides

CONFIG = {
    "engines": [
        {"name": "brave", "enabled": True, "shortcut": "br", "categories": ["general"]},
        {"name": "google", "enabled": False, "shortcut": "go", "categories": ["general"]},
    ]
}


def test_engine_rows_show_live_enabled_state() -> None:
    assert [row["name"] for row in engine_rows(CONFIG)] == ["brave"]
    assert [row["name"] for row in engine_rows(CONFIG, include_disabled=True)] == [
        "brave",
        "google",
    ]


def test_engine_override_update_preserves_other_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.yml"
    path.write_text(
        "use_default_settings: true\nserver:\n  bind_address: 0.0.0.0\n", encoding="utf-8"
    )
    changed = update_engine_overrides(
        path, ["Google"], enabled=False, available_names={"google", "brave"}
    )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert changed == ["google"]
    assert payload["use_default_settings"] is True
    assert payload["server"]["bind_address"] == "0.0.0.0"
    assert payload["engines"] == [{"name": "google", "disabled": True}]


def test_engine_override_rejects_unknown_without_modifying_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.yml"
    original = "use_default_settings: true\n"
    path.write_text(original, encoding="utf-8")
    try:
        update_engine_overrides(path, ["unknown"], enabled=True, available_names={"brave"})
    except RuntimeError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("unknown engine was accepted")
    assert path.read_text(encoding="utf-8") == original


def test_cli_engine_list_json(monkeypatch, capsys) -> None:
    async def configuration():
        return CONFIG

    monkeypatch.setattr(cli, "fetch_configuration", configuration)
    code = asyncio.run(
        cli._run(cli.build_parser().parse_args(["searxng", "engines", "list", "--json"]))
    )
    assert code == 0
    assert '"name": "brave"' in capsys.readouterr().out


def test_doctor_output_does_not_require_live_services(monkeypatch, capsys) -> None:
    async def doctor(_probe):
        return {"ok": False, "checks": {"searxng": {"ok": False, "message": "unavailable"}}}

    monkeypatch.setattr(cli, "run_doctor", doctor)
    code = asyncio.run(cli._run(cli.build_parser().parse_args(["doctor"])))
    assert code == 1
    assert "FAIL searxng: unavailable" in capsys.readouterr().out


def test_cli_searxng_status(monkeypatch, capsys) -> None:
    async def configuration():
        return CONFIG

    monkeypatch.setattr(cli, "fetch_configuration", configuration)
    code = asyncio.run(cli._run(cli.build_parser().parse_args(["searxng", "status", "--json"])))
    assert code == 0
    output = capsys.readouterr().out
    assert '"enabled_engines": 1' in output
    assert '"ok": true' in output


def test_cli_has_single_serve_entry_point() -> None:
    args = cli.build_parser().parse_args(["serve"])
    assert args.command == "serve"


def test_server_shutdown_treats_keyboard_interrupt_as_normal(monkeypatch) -> None:
    from ai_websearch import server

    observed = {}

    async def initialize():
        return type(
            "Detected",
            (),
            {"metadata": lambda self: {"detection_mode": "auto", "context_tokens": 4096}},
        )()

    async def initialize_reranker():
        return None

    class Application:
        def run(self, **kwargs):
            observed.update(kwargs)
            raise KeyboardInterrupt

    monkeypatch.setattr(server.runtime, "initialize", initialize)
    monkeypatch.setattr(server.reranker, "initialize", initialize_reranker)
    monkeypatch.setattr(server, "setup_logging", lambda: None)
    monkeypatch.setattr(server, "initialize_database", lambda: None)
    monkeypatch.setattr(server, "create_mcp", lambda _toolset: Application())
    server.main("answer")
    assert observed["show_banner"] is False


def test_cache_audit_defaults_to_dry_run(monkeypatch, capsys) -> None:
    observed = []

    def audit(*, apply=False):
        observed.append(apply)
        return {
            "sources_assessed": 2,
            "usable": 1,
            "quarantined": 1,
            "changed": 2,
        }

    monkeypatch.setattr(cli, "audit_source_quality", audit)
    code = asyncio.run(cli._run(cli.build_parser().parse_args(["cache", "audit"])))
    assert code == 0
    assert observed == [False]
    assert "dry-run" in capsys.readouterr().out


def test_agent_contract_is_machine_readable(capsys) -> None:
    code = asyncio.run(cli._run(cli.build_parser().parse_args(["agent-contract", "--json"])))
    assert code == 0
    output = capsys.readouterr().out
    assert '"allowed_tools": [' in output
    assert '"research"' in output
