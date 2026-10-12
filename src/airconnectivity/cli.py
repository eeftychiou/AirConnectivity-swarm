"""Command-line entry point for ``airconn``.

Implements the ``load``, ``rank`` and ``report`` subcommands (``report`` builds
a Markdown comparison or, with ``--html``, an interactive bokeh report).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import DEFAULT_MARKET_SEGMENTS

_ENV_DATA_ROOT = "AIRCONN_DATA_ROOT"


def _default_data_root() -> str:
    """Data root from the environment, or a local ``data`` placeholder."""
    return os.environ.get(_ENV_DATA_ROOT, "data")


def _parse_periods(value: str | list[str] | None) -> list[str]:
    """Normalise periods from ``202403,202404``, ``["202403", "202404"]`` or both."""
    if not value:
        return []
    parts = value if isinstance(value, (list, tuple)) else [value]
    periods: list[str] = []
    for part in parts:
        periods.extend(item.strip() for item in str(part).split(",") if item.strip())
    return periods


def _load_command(args: argparse.Namespace) -> int:
    from .io import load_flights, summarise_flights

    periods = args.periods or None
    segments = args.segments or DEFAULT_MARKET_SEGMENTS
    df = load_flights(args.data_root, periods=periods, market_segments=segments)
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


def _rank_command(args: argparse.Namespace) -> int:
    from .io import discover_periods, load_flights
    from .report import write_rankings

    periods = _parse_periods(args.periods) or discover_periods(args.data_root)
    for period in periods:
        df = load_flights(args.data_root, periods=[period])
        for path in write_rankings(df, args.out, period, freq=args.window, weight=args.weight, method=args.method):
            print(f"wrote {path}")
    return 0


def _report_command(args: argparse.Namespace) -> int:
    from .report import build_report, write_rankings

    if not args.html:
        print(f"wrote {build_report(args.rankings, args.out)}")
        return 0

    import pandas as pd

    from .io import load_flights
    from .report_html import build_html_report

    periods = _parse_periods(args.periods)
    frames: list[pd.DataFrame] = []
    if args.data_root and periods:
        for period in periods:
            df = load_flights(args.data_root, periods=[period])
            frames.append(df)
            # (Re)compute the monthly and daily rankings the HTML needs, unless present.
            for freq in ("M", "D"):
                if not (Path(args.rankings) / f"rankings_{period}_{freq}_temporal.csv").exists():
                    write_rankings(df, args.rankings, period, freq=freq, weight=args.weight, method="both")
    flights = pd.concat(frames, ignore_index=True) if frames else None

    path = build_html_report(
        args.rankings,
        args.html,
        top_n=args.top_n,
        inline=args.inline,
        flights=flights,
        weight=args.weight,
        periods=periods or None,
    )
    print(f"wrote {path}")
    return 0


def _add_data_root(parser: argparse.ArgumentParser, default: str) -> None:
    """Register ``--data-root`` on a parser (root or subcommand)."""
    parser.add_argument(
        "--data-root",
        default=default,
        help=f"root folder holding <YYYYMM>/ data folders (env {_ENV_DATA_ROOT})",
    )


def build_parser() -> argparse.ArgumentParser:
    from .graphs import WINDOW_FREQUENCIES
    from .weights import WEIGHT_MODES

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
    load.add_argument(
        "--segments",
        action="append",
        dest="segments",
        metavar="SEGMENT",
        help="STATFOR segment to keep; repeatable. Defaults to the passenger set; "
        "pass a narrower list (e.g. --segments Mainline) to exclude 'Not Classified'.",
    )
    load.set_defaults(func=_load_command)

    rank = subparsers.add_parser("rank", help="write per-period airport rankings as CSV")
    _add_data_root(rank, argparse.SUPPRESS)
    rank.add_argument("--periods", help="comma-separated periods, e.g. 202403,202404")
    rank.add_argument("--window", choices=list(WINDOW_FREQUENCIES), default="M", help="window frequency")
    rank.add_argument("--weight", choices=list(WEIGHT_MODES), default="seats", help="edge weight scheme")
    rank.add_argument("--method", choices=["static", "temporal", "both"], default="both", help="PageRank method")
    rank.add_argument("--out", default="outputs", help="output directory for the CSV files")
    rank.set_defaults(func=_rank_command)

    report = subparsers.add_parser("report", help="build the Markdown or bokeh HTML report")
    _add_data_root(report, argparse.SUPPRESS)
    report.add_argument("--rankings", default="outputs", help="directory of rankings_*.csv files")
    report.add_argument("--out", default="outputs/report.md", help="output Markdown report (without --html)")
    report.add_argument("--html", help="write an interactive bokeh HTML report to this path instead")
    report.add_argument(
        "--periods",
        nargs="+",
        help="periods to (re)compute rankings for, space- or comma-separated, e.g. 202403 202404",
    )
    report.add_argument("--top-n", type=int, default=25, dest="top_n", help="airports per chart")
    report.add_argument("--inline", action="store_true", help="embed bokeh resources for offline viewing")
    report.add_argument("--weight", default="seats", help="edge weight scheme noted in the report header")
    report.set_defaults(func=_report_command)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
