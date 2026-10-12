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


def test_rank_and_report_are_stubbed(capsys: pytest.CaptureFixture[str]) -> None:
    for command in ("rank", "report"):
        assert cli.main([command]) == 0
        assert "not implemented yet" in capsys.readouterr().out


def test_load_without_data_returns_zero_rows(capsys: pytest.CaptureFixture[str]) -> None:
    # Default data root does not exist here; load still succeeds with no rows.
    assert cli.main(["--data-root", "does-not-exist", "load"]) == 0
    assert "rows: 0" in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_data_root_env_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRCONN_DATA_ROOT", "/tmp/somewhere")
    parser = cli.build_parser()
    args = parser.parse_args(["load"])
    assert args.data_root == "/tmp/somewhere"


def test_data_root_flag_after_subcommand_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    # Issue #2 documents `airconn load --data-root PATH ...`.
    assert cli.main(["load", "--data-root", "does-not-exist"]) == 0
    assert "rows: 0" in capsys.readouterr().out


def test_subcommand_data_root_overrides_global(capsys: pytest.CaptureFixture[str]) -> None:
    args = cli.build_parser().parse_args(["--data-root", "/tmp/global", "load", "--data-root", "/tmp/sub"])
    assert args.data_root == "/tmp/sub"


def test_global_data_root_still_works_when_not_repeated() -> None:
    args = cli.build_parser().parse_args(["--data-root", "/tmp/global", "load"])
    assert args.data_root == "/tmp/global"
    assert cli.build_parser().parse_args(["load"]).data_root is not None
