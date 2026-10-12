"""Time-windowed graphs and the static weighted PageRank baseline.

Flights are bucketed by their departure time (UTC) into daily, ISO-weekly or
monthly windows. Each window becomes a directed graph weighted by the issue #3
scheme, and PageRank plus degree/strength metrics are computed per airport.
"""

from __future__ import annotations

from collections.abc import Iterator

import networkx as nx
import pandas as pd

from .weights import aggregate_edges

#: Supported window frequencies.
WINDOW_FREQUENCIES: tuple[str, ...] = ("D", "W", "M")

#: Edge attribute holding the (summed) weight, matching the ported 2021 code.
WEIGHT_ATTRIBUTE = "Weight"


def _window_start(times: pd.Series, freq: str) -> pd.Series:
    """Map departure timestamps to their UTC window start.

    ``D`` -> midnight, ``W`` -> Monday of the ISO week, ``M`` -> first of month.
    """
    if freq not in WINDOW_FREQUENCIES:
        raise ValueError(f"freq must be one of {WINDOW_FREQUENCIES}, got {freq!r}")

    utc = pd.to_datetime(times, utc=True)
    naive = utc.dt.tz_localize(None)

    if freq == "D":
        starts = naive.dt.normalize()
    elif freq == "W":
        starts = (naive - pd.to_timedelta(naive.dt.weekday, unit="D")).dt.normalize()
    else:  # "M"
        starts = naive.dt.to_period("M").dt.start_time

    return starts.dt.tz_localize("UTC")


def windows(
    flights: pd.DataFrame,
    freq: str = "D",
    weight: str = "frequency",
    distance_source: str = "gcd",
    depart_column: str = "off_block_time",
) -> Iterator[tuple[pd.Timestamp, nx.DiGraph]]:
    """Yield ``(window_start, DiGraph)`` for each non-empty UTC window.

    A flight belongs to the window of its departure; edges are the flights
    aggregated per ``(ADEP, ADES)`` and weighted with the #3 scheme. Windows are
    yielded in chronological order.
    """
    if freq not in WINDOW_FREQUENCIES:
        raise ValueError(f"freq must be one of {WINDOW_FREQUENCIES}, got {freq!r}")

    df = flights.copy()
    if df.empty:
        return
    if depart_column not in df.columns:
        raise KeyError(f"departure column {depart_column!r} not in flights")

    df["_window_start"] = _window_start(df[depart_column], freq)

    for start, group in df.groupby("_window_start", sort=True):
        edges = aggregate_edges(group, weight=weight, distance_source=distance_source)
        graph = nx.DiGraph()
        for adep, ades, edge_weight in edges[["adep", "ades", WEIGHT_ATTRIBUTE]].itertuples(index=False):
            graph.add_edge(adep, ades, **{WEIGHT_ATTRIBUTE: float(edge_weight)})
        yield start, graph


def static_pagerank(
    graph: nx.DiGraph,
    alpha: float = 0.85,
    weight: str = WEIGHT_ATTRIBUTE,
) -> dict[str, float]:
    """Static weighted PageRank of ``graph`` (the 2021 code's baseline)."""
    return dict(nx.pagerank(graph, alpha=alpha, weight=weight))


def window_metrics(
    flights: pd.DataFrame,
    freq: str = "D",
    weight: str = "frequency",
    distance_source: str = "gcd",
    alpha: float = 0.85,
    depart_column: str = "off_block_time",
) -> pd.DataFrame:
    """Per-window metrics table: airport, window, pagerank, degrees, strength.

    ``strength`` is the total weighted degree (in + out).
    """
    columns = ["airport", "window", "pagerank", "in_degree", "out_degree", "strength"]
    records: list[dict[str, object]] = []

    for start, graph in windows(
        flights, freq=freq, weight=weight, distance_source=distance_source, depart_column=depart_column
    ):
        pagerank = static_pagerank(graph, alpha=alpha)
        for airport in graph.nodes():
            records.append(
                {
                    "airport": airport,
                    "window": start,
                    "pagerank": pagerank[airport],
                    "in_degree": graph.in_degree(airport),
                    "out_degree": graph.out_degree(airport),
                    "strength": graph.in_degree(airport, weight=WEIGHT_ATTRIBUTE)
                    + graph.out_degree(airport, weight=WEIGHT_ATTRIBUTE),
                }
            )

    return pd.DataFrame.from_records(records, columns=columns)
