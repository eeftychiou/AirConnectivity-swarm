"""Command-line entry point for ``airconn``.

Issue #1 wires the skeleton: ``--help`` plus the ``load``, ``rank`` and
``report`` subcommands. Later issues fill the subcommands in; for now they
validate their arguments and report that the work is not implemented yet.
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airconn",
        description="Pagerank air connectivity indicator and optimizer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--data-root",
        default=_default_data_root(),
        help=f"root folder holding <YYYYMM>/ data folders (env {_ENV_DATA_ROOT})",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    load = subparsers.add_parser("load", help="load flights for a period and print a summary")
    load.add_argument("--period", help="period folder, e.g. 202403")
    load.add_argument("--summary", action="store_true", help="print counts per segment and type")
    load.set_defaults(func=_cmd_load)

    rank = subparsers.add_parser("rank", help="rank airports for one or more periods")
    rank.add_argument("--period", action="append", dest="periods", help="period folder; repeatable")
    rank.set_defaults(func=_cmd_rank)

    report = subparsers.add_parser("report", help="compare airport rankings across periods")
    report.add_argument("--period", action="append", dest="periods", help="period folder; repeatable")
    report.set_defaults(func=_cmd_report)

    return parser


def _config(args: argparse.Namespace) -> Config:
    return Config(data_root=Path(args.data_root))


def _not_implemented(command: str) -> int:
    print(f"airconn {command}: not implemented yet")
    return 0


def _cmd_load(args: argparse.Namespace) -> int:
    _ = _config(args)
    return _not_implemented("load")


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
