"""Ranking outputs and the month-comparison report (issue #6).

Only aggregated airport-level results are written; flight rows never are.
"""

from __future__ import annotations

import re
from pathlib import Path

import networkx as nx
import pandas as pd

from .graphs import WEIGHT_ATTRIBUTE, static_pagerank, window_flights
from .temporal import compare_pagerank, temporal_pagerank
from .weights import aggregate_edges

#: Ranking methods the report understands.
METHODS: tuple[str, ...] = ("static", "temporal")
_METHOD_CHOICES: tuple[str, ...] = ("static", "temporal", "both")

_RANKING_RE = re.compile(r"^rankings_(?P<period>\d{6})_(?P<freq>[DWM])_(?P<method>[a-z]+)\.csv$")

_RANKING_COLUMNS = ["airport", "rank", "score", "window", "weight"]


def _rank_rows(scores: dict[str, float], window: object, weight: str) -> list[dict[str, object]]:
    """Rank airports by descending score (ties broken by airport code)."""
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"airport": airport, "rank": rank, "score": score, "window": window, "weight": weight}
        for rank, (airport, score) in enumerate(ordered, start=1)
    ]


def _static_scores(window_flights_df: pd.DataFrame, weight: str) -> dict[str, float]:
    edges = aggregate_edges(window_flights_df, weight=weight)
    graph = nx.DiGraph()
    for adep, ades, edge_weight in edges[["adep", "ades", WEIGHT_ATTRIBUTE]].itertuples(index=False):
        graph.add_edge(adep, ades, **{WEIGHT_ATTRIBUTE: float(edge_weight)})
    return static_pagerank(graph)


def rank_airports(
    flights: pd.DataFrame,
    freq: str = "M",
    weight: str = "seats",
    method: str = "both",
) -> dict[str, pd.DataFrame]:
    """Per-window airport rankings, keyed by method (``static`` / ``temporal``)."""
    if method not in _METHOD_CHOICES:
        raise ValueError(f"method must be one of {_METHOD_CHOICES}, got {method!r}")

    rows: dict[str, list[dict[str, object]]] = {"static": [], "temporal": []}
    for start, window_df in window_flights(flights, freq=freq):
        if method in ("static", "both"):
            rows["static"] += _rank_rows(_static_scores(window_df, weight), start, weight)
        if method in ("temporal", "both"):
            rows["temporal"] += _rank_rows(temporal_pagerank(window_df, weight=weight), start, weight)

    wanted = METHODS if method == "both" else (method,)
    return {
        name: pd.DataFrame(rows[name], columns=_RANKING_COLUMNS)
        for name in wanted
    }


def write_rankings(
    flights: pd.DataFrame,
    out_dir: str | Path,
    period: str,
    freq: str = "M",
    weight: str = "seats",
    method: str = "both",
) -> list[Path]:
    """Write ``rankings_<period>_<freq>_<method>.csv`` files and return their paths.

    Only windows that belong to ``period`` are written: an export can contain a
    few flights whose UTC departure falls in an adjacent month, and those partial
    windows must not be averaged into the labelled month.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, frame in rank_airports(flights, freq=freq, weight=weight, method=method).items():
        frame = _restrict_to_period(frame, period)
        path = out / f"rankings_{period}_{freq}_{name}.csv"
        frame.to_csv(path, index=False)
        paths.append(path)
    return paths


def _restrict_to_period(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    """Keep only rows whose ``window`` belongs to ``period`` (``YYYYMM``)."""
    if frame.empty:
        return frame
    labels = pd.to_datetime(frame["window"], utc=True).dt.strftime("%Y%m")
    return frame[labels == period].reset_index(drop=True)


def _load_rankings(directory: str | Path) -> list[tuple[str, str, str, pd.DataFrame]]:
    loaded: list[tuple[str, str, str, pd.DataFrame]] = []
    for path in sorted(Path(directory).glob("rankings_*.csv")):
        match = _RANKING_RE.match(path.name)
        if match:
            loaded.append((match.group("period"), match.group("freq"), match.group("method"), pd.read_csv(path)))
    return loaded


def _monthly_scores(frame: pd.DataFrame) -> dict[str, float]:
    return frame.groupby("airport")["score"].mean().to_dict()


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {airport: rank for rank, (airport, _) in enumerate(ordered, start=1)}


def build_report(rankings_dir: str | Path, out_path: str | Path, top_k: int = 20) -> Path:
    """Write a short Markdown report from the ``rankings_*.csv`` files."""
    loaded = _load_rankings(rankings_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# AirConnectivity report", ""]
    if not loaded:
        lines.append("_No rankings found._")
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out_path

    freqs = sorted({freq for _, freq, _, _ in loaded})
    freq = "M" if "M" in freqs else freqs[0]
    rows = [(period, method, frame) for period, f, method, frame in loaded if f == freq]
    periods = sorted({period for period, _, _ in rows})
    methods = {method for _, method, _ in rows}

    monthly = {(period, method): _monthly_scores(frame) for period, method, frame in rows}
    primary = "temporal" if "temporal" in methods else sorted(methods)[0]

    lines.append(f"Window frequency: **{freq}**")
    lines.append("")
    lines.append(f"Periods: {', '.join(periods)}")
    lines.append("")
    lines.append(f"Methods: {', '.join(sorted(methods))}")
    lines.append("")

    lines.append(f"## Top {top_k} per month ({primary})")
    lines.append("")
    for period in periods:
        scores = monthly.get((period, primary))
        if not scores:
            continue
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        lines.append(f"### {period}")
        lines.append("")
        lines.append("| rank | airport | score |")
        lines.append("| ---: | :--- | ---: |")
        for rank, (airport, score) in enumerate(ordered, start=1):
            lines.append(f"| {rank} | {airport} | {score:.6f} |")
        lines.append("")

    lines.append("## Biggest movers between months")
    lines.append("")
    for previous, current in zip(periods, periods[1:], strict=False):
        previous_scores = monthly.get((previous, primary))
        current_scores = monthly.get((current, primary))
        if not previous_scores or not current_scores:
            continue
        previous_ranks = _rank_map(previous_scores)
        current_ranks = _rank_map(current_scores)
        common = set(previous_ranks) & set(current_ranks)
        movers = sorted(common, key=lambda airport: (-abs(current_ranks[airport] - previous_ranks[airport]), airport))[
            :10
        ]
        lines.append(f"### {previous} -> {current}")
        lines.append("")
        lines.append("| airport | rank change |")
        lines.append("| :--- | ---: |")
        for airport in movers:
            lines.append(f"| {airport} | {previous_ranks[airport] - current_ranks[airport]:+d} |")
        lines.append("")

    if {"static", "temporal"} <= methods:
        lines.append("## Static vs temporal PageRank correlation")
        lines.append("")
        lines.append(f"| period | spearman | kendall | top-{top_k} overlap |")
        lines.append("| :--- | ---: | ---: | ---: |")
        for period in periods:
            static_scores = monthly.get((period, "static"))
            temporal_scores = monthly.get((period, "temporal"))
            if not static_scores or not temporal_scores:
                continue
            comparison = compare_pagerank(temporal_scores, static_scores, k=top_k)
            lines.append(
                f"| {period} | {comparison.spearman:.3f} | {comparison.kendall:.3f} | {comparison.top_k_overlap:.2f} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
