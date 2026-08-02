import argparse

import pytest

from benchmarks.cli import LIVE_ENV_GUARD, _validate_live_opt_in, build_parser


def args(*, live: bool, allow_live: bool) -> argparse.Namespace:
    return argparse.Namespace(live=live, allow_live=allow_live)


def test_offline_mode_needs_no_opt_in(monkeypatch) -> None:
    monkeypatch.delenv(LIVE_ENV_GUARD, raising=False)
    _validate_live_opt_in(args(live=False, allow_live=False))


@pytest.mark.parametrize("flag,environment", [(False, None), (True, None), (False, "1")])
def test_live_mode_requires_double_explicit_opt_in(monkeypatch, flag, environment) -> None:
    if environment is None:
        monkeypatch.delenv(LIVE_ENV_GUARD, raising=False)
    else:
        monkeypatch.setenv(LIVE_ENV_GUARD, environment)
    with pytest.raises(SystemExit, match="require both"):
        _validate_live_opt_in(args(live=True, allow_live=flag))


def test_accepted_live_opt_in_still_defers_to_manual_matrix(monkeypatch) -> None:
    monkeypatch.setenv(LIVE_ENV_GUARD, "1")
    with pytest.raises(SystemExit, match="intentionally not automated"):
        _validate_live_opt_in(args(live=True, allow_live=True))


def test_cli_preserves_stage1_default_and_requires_explicit_later_stages() -> None:
    parser = build_parser()
    assert parser.parse_args([]).stage == "1"
    assert parser.parse_args(["--stage", "2"]).stage == "2"
    assert parser.parse_args(["--stage", "3"]).stage == "3"
    assert parser.parse_args(["--stage", "4"]).stage == "4"
    assert parser.parse_args(["--stage", "5"]).stage == "5"
    assert parser.parse_args(["--stage", "6"]).stage == "6"
    assert parser.parse_args(["--stage", "7"]).stage == "7"
    assert parser.parse_args(["--stage", "8"]).stage == "8"
    assert parser.parse_args(["--stage", "11"]).stage == "11"
    assert parser.parse_args(["--all"]).all is True
