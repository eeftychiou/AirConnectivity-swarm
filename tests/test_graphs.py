"""Tests for time-windowed graphs and static weighted PageRank."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest

from airconnectivity.graphs import static_pagerank, window_metrics, windows


def _flights(rows: list[tuple[str, str, str]], ac_type: str = "A320") -> pd.DataFrame:
    """Build a minimal flights frame from (adep, ades, off_block_time) rows."""
    df = pd.DataFrame(rows, columns=["adep", "ades", "off_block_time"])
    df["off_block_time"] = pd.to_datetime(df["off_block_time"], utc=True)
    df["arrival_time"] = df["off_block_time"]
    df["ac_type"] = ac_type
    return df


def _hub_graph() -> nx.DiGraph:
    """B and C both feed the hub A; A points to B."""
    graph = nx.DiGraph()
    graph.add_edge("B", "A", Weight=1.0)
    graph.add_edge("C", "A", Weight=1.0)
    graph.add_edge("A", "B", Weight=1.0)
    return graph


def test_static_pagerank_sums_to_one_and_hub_ranks_first() -> None:
    ranks = static_pagerank(_hub_graph())

    assert sum(ranks.values()) == pytest.approx(1.0)
    assert max(ranks, key=ranks.get) == "A"


def test_static_pagerank_matches_networkx_baseline() -> None:
    graph = _hub_graph()
    assert static_pagerank(graph) == pytest.approx(nx.pagerank(graph, alpha=0.85, weight="Weight"))


def test_static_pagerank_respects_alpha() -> None:
    graph = _hub_graph()
    assert static_pagerank(graph, alpha=0.5) == pytest.approx(nx.pagerank(graph, alpha=0.5, weight="Weight"))


def test_windows_buckets_by_day() -> None:
    flights = _flights(
        [
            ("EGLL", "LFPG", "2024-03-01 06:00:00"),
            ("LFPG", "EHAM", "2024-03-01 18:00:00"),
            ("EGLL", "EHAM", "2024-03-02 09:00:00"),
        ]
    )
    result = list(windows(flights, freq="D"))

    assert [start for start, _ in result] == [
        pd.Timestamp("2024-03-01", tz="UTC"),
        pd.Timestamp("2024-03-02", tz="UTC"),
    ]
    assert result[0][1].number_of_edges() == 2
    assert result[1][1].number_of_edges() == 1


def test_windows_buckets_by_iso_week_monday_start() -> None:
    # 2024-03-03 is a Sunday (previous ISO week), 2024-03-04 is a Monday.
    flights = _flights(
        [
            ("EGLL", "LFPG", "2024-03-03 23:00:00"),
            ("LFPG", "EHAM", "2024-03-04 00:30:00"),
        ]
    )
    result = list(windows(flights, freq="W"))

    assert [start for start, _ in result] == [
        pd.Timestamp("2024-02-26", tz="UTC"),  # Monday of the week containing Sun 03-03
        pd.Timestamp("2024-03-04", tz="UTC"),
    ]


def test_windows_buckets_by_month() -> None:
    flights = _flights(
        [
            ("EGLL", "LFPG", "2024-03-15 06:00:00"),
            ("LFPG", "EHAM", "2024-04-02 06:00:00"),
        ]
    )
    result = list(windows(flights, freq="M"))

    assert [start for start, _ in result] == [
        pd.Timestamp("2024-03-01", tz="UTC"),
        pd.Timestamp("2024-04-01", tz="UTC"),
    ]


def test_windows_aggregate_frequency_per_route() -> None:
    flights = _flights(
        [
            ("EGLL", "LFPG", "2024-03-01 06:00:00"),
            ("EGLL", "LFPG", "2024-03-01 12:00:00"),
            ("LFPG", "EHAM", "2024-03-01 20:00:00"),
        ]
    )
    (_, graph), = list(windows(flights, freq="D", weight="frequency"))

    assert graph["EGLL"]["LFPG"]["Weight"] == 2.0
    assert graph["LFPG"]["EHAM"]["Weight"] == 1.0


def test_windows_support_seats_weight() -> None:
    flights = _flights([("EGLL", "LFPG", "2024-03-01 06:00:00")], ac_type="A320")
    (_, graph), = list(windows(flights, freq="D", weight="seats"))

    assert graph["EGLL"]["LFPG"]["Weight"] == 180.0


def test_windows_empty_flights_yields_nothing() -> None:
    empty = _flights([])
    assert list(windows(empty, freq="D")) == []


def test_windows_invalid_frequency_raises() -> None:
    flights = _flights([("EGLL", "LFPG", "2024-03-01 06:00:00")])
    with pytest.raises(ValueError, match="freq must be one of"):
        list(windows(flights, freq="Q"))


def test_window_metrics_table_shape_and_values() -> None:
    flights = _flights(
        [
            ("EGLL", "LFPG", "2024-03-01 06:00:00"),
            ("LFPG", "EHAM", "2024-03-01 08:00:00"),
            ("EHAM", "EGLL", "2024-03-01 10:00:00"),
            ("EGLL", "EHAM", "2024-03-02 09:00:00"),
        ]
    )
    metrics = window_metrics(flights, freq="D")

    assert metrics.columns.tolist() == [
        "airport",
        "window",
        "pagerank",
        "in_degree",
        "out_degree",
        "strength",
    ]
    first_day = metrics[metrics["window"] == pd.Timestamp("2024-03-01", tz="UTC")]
    assert set(first_day["airport"]) == {"EGLL", "LFPG", "EHAM"}
    assert first_day["pagerank"].sum() == pytest.approx(1.0)
    # EGLL is on both the 1st and the 2nd.
    assert len(metrics[metrics["airport"] == "EGLL"]) == 2
    assert (metrics["strength"] >= 0).all()
