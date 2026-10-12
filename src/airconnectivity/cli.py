"""Command-line entry point for ``airconn``.

``load`` is implemented (issue #2); ``rank`` and ``report`` are still stubs
that later issues fill in.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import Config

_ENV_DATA_ROOT = "AIRCONN_DATA_ROOT"


def _default_data_root() -> str:
    """Data root from the environment, or a local ``data`` placeholder."""
    return os.environ.get(_ENV_DATA_ROOT, "data")


def _load_command(args: argparse.Namespace) -> int:
    from .io import load_flights, summarise_flights

    periods = args.periods or None
    df = load_flights(args.data_root, periods=periods)
    summary = summarise_flights(df)

    print(f"periods: {', '.join(periods) if periods else '(all discovered)'}")
    print(f"rows: {summary['rows']}")
    if args.summary:
        print("by market segment:")
        for segment, count in sorted(summary["by_market_segment"].items()):
            print(f"  {segment}: {count}")
        print("by flight type:")
        for flight_type, count in sorted(summary["by_flight_type"].items()):
            print(f"  {flight_type}: {count}")
    return 0


def _add_data_root(parser: argparse.ArgumentParser, default: str) -> None:
    """Register ``--data-root`` on a parser (root or subcommand)."""
    parser.add_argument(
        "--data-root",
        default=default,
        help=f"root folder holding <YYYYMM>/ data folders (env {_ENV_DATA_ROOT})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airconn",
        description="Pagerank air connectivity indicator and optimizer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_data_root(parser, _default_data_root())

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    load = subparsers.add_parser("load", help="load flights for a period and print a summary")
    # Allow --data-root after the subcommand too, as documented in the issue.
    # SUPPRESS keeps the root parser's value when the flag is not given here.
    _add_data_root(load, argparse.SUPPRESS)
    load.add_argument(
        "--period",
        action="append",
        dest="periods",
        help="period folder, e.g. 202403; repeatable (default: all discovered)",
    )
    load.add_argument("--summary", action="store_true", help="print counts per segment and type")
    load.set_defaults(func=_load_command)

    rank = subparsers.add_parser("rank", help="rank airports for one or more periods")
    _add_data_root(rank, argparse.SUPPRESS)
    rank.add_argument("--period", action="append", dest="periods", help="period folder; repeatable")
    rank.set_defaults(func=_cmd_rank)

    report = subparsers.add_parser("report", help="compare airport rankings across periods")
    _add_data_root(report, argparse.SUPPRESS)
    report.add_argument("--period", action="append", dest="periods", help="period folder; repeatable")
    report.set_defaults(func=_cmd_report)

    return parser


def _config(args: argparse.Namespace) -> Config:
    return Config(data_root=Path(args.data_root))


def _not_implemented(command: str) -> int:
    print(f"airconn {command}: not implemented yet")
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    _ = _config(args)
    return _not_implemented("rank")


def _cmd_report(args: argparse.Namespace) -> int:
    _ = _config(args)
    return _not_implemented("report")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
