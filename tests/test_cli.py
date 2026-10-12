"""Tests for the ``airconn`` CLI skeleton."""

from __future__ import annotations

import pytest

from airconnectivity import cli


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    assert "load" in out
    assert "rank" in out
    assert "report" in out


def test_subcommands_are_stubbed_and_return_zero(capsys: pytest.CaptureFixture[str]) -> None:
    for command in ("load", "rank", "report"):
        assert cli.main([command]) == 0
        assert "not implemented yet" in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_data_root_env_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRCONN_DATA_ROOT", "/tmp/somewhere")
    parser = cli.build_parser()
    args = parser.parse_args(["load"])
    assert args.data_root == "/tmp/somewhere"


def test_data_root_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRCONN_DATA_ROOT", "/tmp/somewhere")
    parser = cli.build_parser()
    args = parser.parse_args(["--data-root", "/tmp/explicit", "load"])
    assert args.data_root == "/tmp/explicit"
